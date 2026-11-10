"""Original-source measured-PTS motion progression for offline creative review.

Measured PTS + source-redecoded pixels help a reviewer inspect real movement.
Pixel-change scores are visual diagnostics, NOT physical/identity correctness,
and no generated artifact can approve a reel or assert independent viewing.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

import business_media_replay as replay
import business_temporal_review as temporal


class MotionEvidenceError(ValueError):
    pass


VERSION = 1
TARGET_OFFSETS = (-0.25, -0.125, 0.0, 0.125, 0.25)
COVERAGE = "selected_measured_source_pts_frame_progressions_not_all_motion_reviewed"
CATEGORIES = {
    "object_path", "physical_mechanics", "subject_identity",
    "forbidden_people", "product_fidelity", "scene_continuity", "other",
}
REQUEST_KEYS = {"atSeconds", "category", "reviewPrompt"}
ENTRY_KEYS = {
    "requestId", "atSeconds", "category", "reviewPrompt",
    "windowId", "frames", "adjacentPixelChange",
}
FRAME_KEYS = {"frameIndex", "framePtsSeconds", "frameFile", "frameSha256"}
MANIFEST_KEYS = {
    "version", "createdAt", "sourceSha256", "sourceFileSize",
    "sourceDurationSeconds", "sourceFrameCount", "packetSha256",
    "temporalManifestSha256", "reviewDirectory", "requests", "coverage",
    "wholeExportViewed", "creativeApproved", "canPublish", "providerCalls",
    "networkRequests", "limitations", "manifestSha256",
}
NOTE_KEYS = {
    "requestId", "sourceSha256", "frameSha256s", "category", "comparison",
    "reviewOrigin", "reviewerReference", "observation",
}
COMPARISONS = {"consistent", "inconsistent", "uncertain"}
REVIEW_ORIGINS = {"manual_review_declared", "customer_source_specific"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _fingerprint(data):
    return hashlib.sha256(json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def _source(video_path, packet, timeline):
    try:
        temporal.verify_clips(video_path, packet, timeline)
        return replay._safe_video(video_path)
    except (temporal.TemporalReviewError, replay.ReplayError,
            OSError, ValueError, TypeError, KeyError) as exc:
        raise MotionEvidenceError("Original source or temporal provenance failed") from exc


def _frame_times(source):
    """All original decoded-frame best-effort timestamps, never guessed seek PTS."""
    try:
        proc = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_frames", "-show_entries", "frame=best_effort_timestamp_time",
            "-of", "json", str(source),
        ], capture_output=True, check=True, timeout=60)
        rows = json.loads(proc.stdout)["frames"]
        if not isinstance(rows, list) or not 5 <= len(rows) <= 36000:
            raise ValueError("Invalid bounded source frame inventory")
        times = [round(float(row["best_effort_timestamp_time"]), 6) for row in rows]
        if (not all(math.isfinite(t) and t >= 0 for t in times)
                or any(a >= b for a, b in zip(times, times[1:]))):
            raise ValueError("Original frame timestamps missing, duplicated or unsorted")
        return times
    except (OSError, subprocess.SubprocessError, ValueError,
            KeyError, TypeError, OverflowError) as exc:
        raise MotionEvidenceError("Could not verify measured source frame timestamps") from exc


def _validate_requests(requests, duration):
    if not isinstance(requests, list) or not 1 <= len(requests) <= 8:
        raise MotionEvidenceError("Choose one to eight bounded motion review points")
    seen = set()
    for request in requests:
        if not isinstance(request, dict) or set(request) != REQUEST_KEYS:
            raise MotionEvidenceError("Motion request needs exact time, topic and purpose")
        t = request["atSeconds"]
        if (type(t) not in (float, int) or not math.isfinite(t)
                or not 0.3 <= t <= duration - 0.3
                or round(t, 6) in seen):
            raise MotionEvidenceError("Missing, repeated or out-of-bounds review time")
        seen.add(round(t, 6))
        if request["category"] not in CATEGORIES:
            raise MotionEvidenceError("Unknown motion review category")
        reason = request["reviewPrompt"]
        if (not isinstance(reason, str) or not 24 <= len(reason) <= 220
                or any(ord(c) < 32 for c in reason)):
            raise MotionEvidenceError("Specific review question required; no default positivity")


def _indices(times, focus):
    targets = [focus + delta for delta in TARGET_OFFSETS]
    indices = [min(range(len(times)), key=lambda i: abs(times[i] - target))
               for target in targets]
    if len(set(indices)) != 5 or indices != sorted(indices):
        raise MotionEvidenceError("Insufficient distinct decoded source frames near review point")
    return indices


def _window(timeline, time):
    matches = [c["windowId"] for c in timeline["clips"]
               if c["startSeconds"] <= time < c["endSeconds"]]
    if len(matches) != 1:
        raise MotionEvidenceError("Motion point does not identify exactly one source review window")
    return matches[0]


def _extract(source, indices, directory):
    """Extract selected ORIGINAL frame indices in a single offline decode pass."""
    filter_expression = "select=" + "+".join(f"eq(n\\,{i})" for i in indices)
    output = directory / "frame-%02d.png"
    try:
        subprocess.run([
            "ffmpeg", "-v", "error", "-nostdin", "-i", str(source),
            "-vf", filter_expression, "-fps_mode", "vfr",
            "-frames:v", str(len(indices)), "-c:v", "png", str(output),
        ], capture_output=True, check=True, timeout=75)
        frames = sorted(directory.glob("frame-*.png"))
        if len(frames) != len(indices):
            raise ValueError("Incomplete source-decoded frame sequence")
        for file in frames:
            with Image.open(file) as frame:
                frame.verify()
            with Image.open(file) as frame:
                if min(frame.size) < 32 or max(frame.size) > 8192:
                    raise ValueError("Unsafe decoded source image size")
        return frames
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise MotionEvidenceError("Could not extract all requested original source frames") from exc


def _change_scores(files):
    values = []
    for earlier, later in zip(files, files[1:]):
        with Image.open(earlier) as first, Image.open(later) as second:
            a, b = first.convert("RGB"), second.convert("RGB")
            if a.size != b.size:
                raise MotionEvidenceError("Original source frames changed dimensions")
            delta = ImageStat.Stat(ImageChops.difference(a, b)).mean
            values.append(round(sum(delta) / 3, 6))
    return values


def _entry(request, index, times, timeline, destination):
    focus = request["atSeconds"]
    ids = _indices(times, focus)
    name = f"motion-{index:02d}"
    return {
        "requestId": name, "atSeconds": focus,
        "category": request["category"], "reviewPrompt": request["reviewPrompt"],
        "windowId": _window(timeline, focus),
        "frames": [{
            "frameIndex": i, "framePtsSeconds": times[i],
            "frameFile": str(destination / f"{name}-frame-{j:02d}.png"),
        } for j, i in enumerate(ids, 1)],
    }


def prepare(video_path, packet, timeline, requests, out_dir):
    source = _source(video_path, packet, timeline)
    _validate_requests(requests, packet["durationSeconds"])
    destination = Path(out_dir)
    if destination.is_symlink() or destination.exists() or not destination.parent.is_dir():
        raise MotionEvidenceError("Motion evidence requires fresh unused review directory")
    source_hash = _sha(source)
    times = _frame_times(source)
    result_entries = []
    with tempfile.TemporaryDirectory(prefix=".motion-sequence-stage-", dir=destination.parent) as staging:
        stage = Path(staging)
        for i, request in enumerate(requests, 1):
            entry = _entry(request, i, times, timeline, destination)
            with tempfile.TemporaryDirectory(prefix="selected-", dir=stage) as selected:
                output = _extract(source, [f["frameIndex"] for f in entry["frames"]],
                                  Path(selected))
                entry["adjacentPixelChange"] = _change_scores(output)
                for frame, image in zip(entry["frames"], output):
                    frame["frameSha256"] = _sha(image)
                    image.replace(stage / Path(frame["frameFile"]).name)
            result_entries.append(entry)
        if _sha(source) != source_hash:
            raise MotionEvidenceError("Original source changed during frame progression")
        manifest = {
            "version": VERSION, "createdAt": datetime.now(timezone.utc).isoformat(),
            "sourceSha256": source_hash, "sourceFileSize": source.stat().st_size,
            "sourceDurationSeconds": packet["durationSeconds"],
            "sourceFrameCount": len(times), "packetSha256": packet["packetSha256"],
            "temporalManifestSha256": timeline["manifestSha256"],
            "reviewDirectory": str(destination), "requests": result_entries,
            "coverage": COVERAGE, "wholeExportViewed": False,
            "creativeApproved": False, "canPublish": False,
            "providerCalls": 0, "networkRequests": 0,
            "limitations": [
                "Exact source frame indices and measured ffprobe PTS, not inaccurate seek guesses.",
                "Five snapshots per selected point do not prove whole-export viewing or realism.",
                "Adjacent RGB pixel-change magnitudes cannot establish physical trajectories, impact or object identity.",
                "Manual review declarations are not independently authenticated labels.",
                "No creative acceptance, publication, credits or provider submissions authorised.",
            ],
        }
        manifest["manifestSha256"] = _fingerprint(manifest)
        (stage / "motion-sequence-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        stage.replace(destination)
    verify(source, packet, timeline, manifest)
    return manifest


def verify(video_path, packet, timeline, evidence):
    source = _source(video_path, packet, timeline)
    if not isinstance(evidence, dict) or set(evidence) != MANIFEST_KEYS:
        raise MotionEvidenceError("Incomplete motion evidence manifest")
    expected_hash = _fingerprint({k: v for k, v in evidence.items() if k != "manifestSha256"})
    if evidence["manifestSha256"] != expected_hash:
        raise MotionEvidenceError("Motion evidence metadata changed")
    if (evidence["version"] != VERSION or evidence["coverage"] != COVERAGE
            or evidence["wholeExportViewed"] is not False
            or evidence["creativeApproved"] is not False
            or evidence["canPublish"] is not False
            or type(evidence["providerCalls"]) is not int or evidence["providerCalls"] != 0
            or type(evidence["networkRequests"]) is not int or evidence["networkRequests"] != 0):
        raise MotionEvidenceError("Invalid coverage or unauthorised release assertion")
    if (evidence["sourceSha256"] != packet["sourceSha256"]
            or evidence["sourceSha256"] != _sha(source)
            or evidence["sourceFileSize"] != source.stat().st_size
            or evidence["sourceDurationSeconds"] != packet["durationSeconds"]
            or evidence["packetSha256"] != packet["packetSha256"]
            or evidence["temporalManifestSha256"] != timeline["manifestSha256"]):
        raise MotionEvidenceError("Stale or unrelated original source or playable evidence")
    directory = Path(evidence["reviewDirectory"])
    saved = directory / "motion-sequence-manifest.json"
    if (directory.is_symlink() or not directory.is_dir() or saved.is_symlink()
            or not saved.is_file()):
        raise MotionEvidenceError("Persisted motion evidence missing")
    try:
        if json.loads(saved.read_text()) != evidence:
            raise MotionEvidenceError("Persisted motion evidence differs from object")
    except (ValueError, UnicodeError, OSError) as exc:
        raise MotionEvidenceError("Motion manifest was tampered") from exc
    times = _frame_times(source)
    if evidence["sourceFrameCount"] != len(times):
        raise MotionEvidenceError("Source frame inventory changed")
    entries = evidence["requests"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
        raise MotionEvidenceError("Incomplete motion review request inventory")
    originals = []
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise MotionEvidenceError("Malformed motion evidence request")
        request = {k: entry[k] for k in REQUEST_KEYS}
        originals.append(request)
        expected = _entry(request, i, times, timeline, directory)
        if any(entry[k] != expected[k] for k in expected if k != "frames"):
            raise MotionEvidenceError("Motion request or temporal binding changed")
        frames = entry["frames"]
        if not isinstance(frames, list) or len(frames) != 5:
            raise MotionEvidenceError("Original source frame sequence incomplete")
        with tempfile.TemporaryDirectory(prefix="motion-verify-") as scratch:
            output = _extract(source, [f["frameIndex"] for f in expected["frames"]],
                              Path(scratch))
            for actual, baseline, decoded in zip(frames, expected["frames"], output):
                if (not isinstance(actual, dict) or set(actual) != FRAME_KEYS
                        or any(actual[k] != baseline[k] for k in baseline)):
                    raise MotionEvidenceError("Measured original frame index or PTS forged")
                image = Path(actual["frameFile"])
                if (image.is_symlink() or image.parent != directory or not image.is_file()
                        or _sha(image) != actual["frameSha256"]
                        or _sha(decoded) != actual["frameSha256"]):
                    raise MotionEvidenceError("Source-linked decoded motion frame changed")
            if entry["adjacentPixelChange"] != _change_scores(output):
                raise MotionEvidenceError("Motion pixel diagnostics were modified")
    _validate_requests(originals, packet["durationSeconds"])
    return True


def assess(video_path, packet, timeline, evidence, notes, *, prior_replay_assessment=None):
    """Validate attributed source observations, conservatively hold or reject only."""
    verify(video_path, packet, timeline, evidence)
    if not isinstance(notes, list) or len(notes) > 32:
        raise MotionEvidenceError("Bounded attributed motion observations required")
    prior_rejected = False
    prior_unlocated = False
    if prior_replay_assessment is not None:
        if (not isinstance(prior_replay_assessment, dict)
                or not isinstance(prior_replay_assessment.get("observations"), list)):
            raise MotionEvidenceError("Missing historical review provenance")
        try:
            checked = replay.assess(video_path, packet, prior_replay_assessment["observations"])
        except (replay.ReplayError, ValueError, TypeError) as exc:
            raise MotionEvidenceError("Historical source review could not be verified") from exc
        if checked != prior_replay_assessment:
            raise MotionEvidenceError("Historical review has changed")
        prior_rejected = checked["sourceSpecificRejection"]
        prior_unlocated = any(o["type"] == "project_feedback" for o in checked["observations"])
    by_id = {req["requestId"]: req for req in evidence["requests"]}
    reviewed = set()
    inconsistent = False
    uncertain = False
    for note in notes:
        if not isinstance(note, dict) or set(note) != NOTE_KEYS:
            raise MotionEvidenceError("Original source-linked review details required")
        req = by_id.get(note["requestId"])
        if (req is None or req["requestId"] in reviewed
                or note["sourceSha256"] != evidence["sourceSha256"]
                or note["category"] != req["category"]
                or note["frameSha256s"] != [f["frameSha256"] for f in req["frames"]]):
            raise MotionEvidenceError("Review points to mismatched, duplicate or missing source frames")
        if (note["comparison"] not in COMPARISONS
                or note["reviewOrigin"] not in REVIEW_ORIGINS
                or not isinstance(note["reviewerReference"], str)
                or not replay.REF.fullmatch(note["reviewerReference"])
                or not isinstance(note["observation"], str)
                or not 24 <= len(note["observation"]) <= 300
                or any(ord(ch) < 32 for ch in note["observation"])):
            raise MotionEvidenceError("Specific bounded reviewer claim and origin required")
        reviewed.add(req["requestId"])
        inconsistent |= note["comparison"] == "inconsistent"
        uncertain |= note["comparison"] == "uncertain"
    pending = [r["requestId"] for r in evidence["requests"] if r["requestId"] not in reviewed]
    disposition = (
        "rejected_by_prior_or_source_motion_finding" if prior_rejected else
        "rejected_by_source_motion_finding" if inconsistent else
        "hold_prior_unlocated_feedback" if prior_unlocated else
        "hold_uncertain_motion_finding" if uncertain else
        "needs_independent_motion_review"
    )
    return {
        "version": VERSION, "sourceSha256": evidence["sourceSha256"],
        "manifestSha256": evidence["manifestSha256"],
        "reviewedRequestIds": sorted(reviewed), "pendingRequestIds": pending,
        "sourceSpecificRejection": prior_rejected or inconsistent,
        "observations": [dict(n) for n in notes], "disposition": disposition,
        "wholeExportViewed": False, "qualityScore": None, "creativeApproved": False,
        "canPublish": False, "providerCalls": 0, "networkRequests": 0,
        "limitations": [
            "Motion frame PTS and pixel statistics are verified, but no physical reasoning is automatically certified.",
            "Reviewer origin and source-specific claims remain unverified declarations.",
        ],
    }
