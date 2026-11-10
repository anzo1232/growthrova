"""Immutable captioned MP4 deliveries for the isolated local Business workspace.

Rendering never grants creative approval, spends provider credits or consumes a
customer allowance. Source edits and editable VTT tracks remain unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path


class CaptionExportError(ValueError):
    def __init__(self, message, code="caption_export_unavailable", status=409):
        super().__init__(message)
        self.code = code
        self.status = status


def initialise(con):
    con.execute("""CREATE TABLE IF NOT EXISTS business_reel_caption_exports(
        id TEXT PRIMARY KEY,project_id TEXT NOT NULL,variant TEXT NOT NULL,
        edit_revision INTEGER NOT NULL,caption_revision INTEGER NOT NULL,
        input_content_sha256 TEXT NOT NULL,video_sha256 TEXT NOT NULL,
        bytes INTEGER NOT NULL,render_json TEXT NOT NULL,created REAL NOT NULL,
        UNIQUE(project_id,variant,input_content_sha256))""")


def _record(con, project_id, variant, input_sha):
    return con.execute("""SELECT * FROM business_reel_caption_exports
        WHERE project_id=? AND variant=? AND input_content_sha256=?""",
        (project_id, variant, input_sha)).fetchone()


def _folder(root, project_id):
    if not isinstance(project_id, str) or not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise CaptionExportError("Invalid Reel project", "invalid_id", 400)
    parent = Path(root) / "reel_workbench"
    folder = parent / project_id
    if parent.is_symlink() or folder.is_symlink() or not folder.is_dir():
        raise CaptionExportError("Private Reel folder is unavailable", "unsafe_path")
    return folder


def _path(root, row):
    if row["variant"] not in ("a", "b") or not re.fullmatch(r"[a-f0-9]{32}", row["id"]):
        raise CaptionExportError("Invalid caption export record", "invalid_export")
    return _folder(root, row["project_id"]) / (
        "captioned-" + row["variant"] + "-" + row["id"] + ".mp4")


def _verify_file(root, row):
    path = _path(root, row)
    if (path.is_symlink() or not path.is_file() or
            path.stat().st_size != row["bytes"] or
            hashlib.sha256(path.read_bytes()).hexdigest() != row["video_sha256"]):
        raise CaptionExportError(
            "The saved captioned video changed. Its earlier approval cannot be used.",
            "asset_changed")
    return path


def describe(row):
    if row is None:
        return None
    return {
        "id": row["id"], "sha256": row["video_sha256"], "bytes": row["bytes"],
        "editRevision": row["edit_revision"],
        "captionRevision": row["caption_revision"],
        "inputContentSha256": row["input_content_sha256"],
        "bakedIntoVideo": True, "providerCreditsUsed": 0,
        "customerAllowanceConsumed": 0, "published": False,
    }


def current(con, project_id, variant, input_sha, root=None):
    """Resolve only an export of the current exact clean edit, captions and brand."""
    row = _record(con, project_id, variant, input_sha)
    if row is not None and root is not None:
        _verify_file(root, row)
    return describe(row)


def _context(con, project_id, variant, root):
    import business_marketing_drafts as drafts
    import business_reel_workbench as reel
    import business_reel_captions as captions
    import business_reel_brand_lock as brand

    if variant not in ("a", "b"):
        raise CaptionExportError("Choose a complete social or cinematic cut", "invalid_variant", 400)
    project = reel._project(con, project_id)
    if drafts.read_draft(con, project["draft_id"])["revision"] != project["revision"]:
        raise CaptionExportError("This campaign changed. Open its current version.", "stale_revision")
    edit = con.execute("""SELECT * FROM business_reel_edits
        WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1""",
        (project_id, variant)).fetchone()
    if edit is None:
        raise CaptionExportError("Assemble the complete cut before rendering captions", "cut_not_ready")
    track = captions.latest(con, project_id, variant)
    if not track or not track["ownerVerifiedText"]:
        raise CaptionExportError("Save your verified hook or subtitles first", "captions_missing")
    locked = brand.read(con, project_id, root)
    if not locked["locked"]:
        raise CaptionExportError("Save the genuine business branding first", "brand_not_locked")
    wanted_type = "sans" if locked["style"] == "minimal" else locked["style"]
    if track["style"]["typeface"] != wanted_type:
        raise CaptionExportError("Caption typography must match the saved brand", "caption_brand_mismatch")
    base_sha = reel._content_sha256(con, project_id, edit, root, include_export=False)
    return edit, track, locked, base_sha


def _complete_manifest(con, project_id, edit):
    """A partial historical A/B cut must not acquire a delivery label."""
    import business_reel_workbench as reel
    manifest = json.loads(edit["ordered_shots_json"])
    if (not isinstance(manifest, list) or len(manifest) != len(reel.SLOTS) or
            any(not isinstance(part, dict) for part in manifest) or
            {part.get("slot") for part in manifest} != set(reel.SLOTS)):
        raise CaptionExportError("Rebuild this cut with all four reviewed stages", "incomplete_cut")
    accepted = {row["slot"]: row["sha256"] for row in reel._shots(con, project_id)
                if row["internal_verdict"] == "accepted"}
    for row in con.execute("""SELECT slot,render_sha256 FROM business_reel_owner_media
            WHERE project_id=? AND approval_status='accepted'""", (project_id,)):
        if row["slot"] in accepted:
            raise CaptionExportError("Two sources claim the same Reel stage", "source_conflict")
        accepted[row["slot"]] = row["render_sha256"]
    endcard = con.execute("""SELECT sha256,status FROM business_reel_local_endcards
        WHERE project_id=?""", (project_id,)).fetchone()
    if endcard and endcard["status"] == "accepted":
        accepted["payoff"] = endcard["sha256"]
    if any(part.get("sha256") != accepted.get(part["slot"]) or part["slot"] not in accepted
           for part in manifest):
        raise CaptionExportError(
            "Rebuild the complete cut from the currently reviewed footage and ending",
            "stale_cut_source")


def render(con, project_id, variant, root, *, expected_content_sha256,
           expected_edit_revision, expected_caption_revision):
    import business_reel_workbench as reel
    import business_reel_caption_render as renderer

    if (not isinstance(expected_content_sha256, str) or
            not re.fullmatch(r"[a-f0-9]{64}", expected_content_sha256) or
            type(expected_edit_revision) is not int or
            type(expected_caption_revision) is not int):
        raise CaptionExportError("Reload the exact saved edit and caption version", "stale_review")
    if con.in_transaction:
        raise CaptionExportError("Finish the current save before rendering", "save_in_progress")
    edit, track, locked, base_sha = _context(con, project_id, variant, root)
    current_sha = reel._content_sha256(con, project_id, edit, root)
    if (expected_edit_revision != edit["revision_no"] or
            expected_caption_revision != track["captionRevision"] or
            expected_content_sha256 not in (base_sha, current_sha)):
        raise CaptionExportError("The cut or captions changed. Review the saved version.", "stale_review")
    _complete_manifest(con, project_id, edit)
    existing = _record(con, project_id, variant, base_sha)
    if existing is not None:
        _verify_file(root, existing)
        return reel.read(con, project_id)

    folder = _folder(root, project_id)
    source = reel.preview_file(con, project_id, variant, root)
    export_id = uuid.uuid4().hex
    target = folder / ("captioned-" + variant + "-" + export_id + ".mp4")
    target_created = False
    transaction_started = False
    try:
        # Render a private byte-for-byte snapshot so later edits cannot change
        # the file being read by FFmpeg. Recheck the live source before saving.
        with tempfile.TemporaryDirectory(prefix=".caption-export-", dir=folder) as scratch:
            snapshot = Path(scratch) / "source.mp4"
            shutil.copyfile(source, snapshot)
            os.chmod(snapshot, 0o600)
            if hashlib.sha256(snapshot.read_bytes()).hexdigest() != edit["sha256"]:
                raise CaptionExportError("The source changed before rendering", "asset_changed")
            output = Path(scratch) / "captioned.mp4"
            try:
                metadata = renderer.render(snapshot, output, cues=track["cues"],
                    style=track["style"], brand=locked,
                    expected_duration=reel._saved_edit_duration(edit["ordered_shots_json"]))
            except renderer.CaptionRenderError as exc:
                raise CaptionExportError(str(exc), exc.code, exc.status) from exc
            if (output.is_symlink() or not output.is_file() or
                    not 1 <= output.stat().st_size <= 65 * 1024 * 1024):
                raise CaptionExportError("Captioned video could not be verified", "render_failed", 422)
            output_sha = hashlib.sha256(output.read_bytes()).hexdigest()
            output_size = output.stat().st_size
            if (metadata.get("sha256") != output_sha or metadata.get("bytes") != output_size):
                raise CaptionExportError("Rendered video evidence does not match its bytes", "render_failed", 422)

            con.execute("BEGIN IMMEDIATE")
            transaction_started = True
            latest_edit, latest_track, _, latest_base = _context(con, project_id, variant, root)
            _complete_manifest(con, project_id, latest_edit)
            if (latest_base != base_sha or latest_edit["revision_no"] != edit["revision_no"] or
                    latest_track["captionRevision"] != track["captionRevision"]):
                raise CaptionExportError(
                    "This edit changed during rendering. Your newer work is preserved.",
                    "stale_review")
            # A concurrent identical request may already have completed.
            existing = _record(con, project_id, variant, base_sha)
            if existing is not None:
                _verify_file(root, existing)
                con.commit()
                transaction_started = False
                return reel.read(con, project_id)
            # Exclusive link makes promotion atomic without overwriting history.
            os.link(output, target)
            target_created = True
            os.chmod(target, 0o600)
            con.execute("""INSERT INTO business_reel_caption_exports VALUES(
                ?,?,?,?,?,?,?,?,?,?)""",
                (export_id, project_id, variant, edit["revision_no"],
                 track["captionRevision"], base_sha, output_sha, output_size,
                 json.dumps(metadata, sort_keys=True), time.time()))
            con.commit()
            transaction_started = False
    except Exception:
        if transaction_started:
            con.rollback()
        if target_created:
            target.unlink(missing_ok=True)
        raise
    return reel.read(con, project_id)


def preview_file(con, project_id, variant, root):
    """Return the actual rendition bound to the current review identity."""
    import business_reel_workbench as reel
    edit = con.execute("""SELECT * FROM business_reel_edits
        WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1""",
        (project_id, variant)).fetchone()
    if edit is None:
        return reel.preview_file(con, project_id, variant, root)
    base_sha = reel._content_sha256(con, project_id, edit, root, include_export=False)
    row = _record(con, project_id, variant, base_sha)
    return _verify_file(root, row) if row is not None else reel.preview_file(
        con, project_id, variant, root)


def approved_file(con, project_id, variant, root, *,
                  expected_content_sha256, expected_review_set_sha256):
    """Private download only after review and owner choice of these exact bytes."""
    import business_reel_workbench as reel
    state = reel.read(con, project_id)
    selected = next((edit for edit in state["edits"] if edit["variant"] == variant), None)
    if (variant not in ("a", "b") or not selected or
            selected["contentSha256"] != expected_content_sha256 or
            state["reviewSetSha256"] != expected_review_set_sha256):
        raise CaptionExportError("The reviewed versions changed. Reopen both cuts.", "stale_review")
    if (not state["isCurrentRevision"] or
            not state["build7Readiness"]["readyForPrivateHandoff"] or
            not state["localOwnerChoiceRecorded"] or
            state["locallySelectedVariant"] != variant or
            not selected.get("captionsBakedIntoVideo")):
        raise CaptionExportError(
            "Review both current cuts and record the owner's choice before delivery.",
            "delivery_not_approved")
    verified = {}
    for name in ("a", "b"):
        edit = con.execute("""SELECT * FROM business_reel_edits
            WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1""",
            (project_id, name)).fetchone()
        verified[name] = reel._content_sha256(con, project_id, edit, root)
    if (verified.get(variant) != expected_content_sha256 or
            reel._review_set_sha256(verified) != expected_review_set_sha256):
        raise CaptionExportError("The approved media changed before download.", "stale_review")
    return preview_file(con, project_id, variant, root)
