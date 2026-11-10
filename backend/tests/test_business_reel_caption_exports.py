"""Exact caption-export receipts and delivery contract, using synthetic byte fixtures.

Real caption pixels, audio and duration are exercised by the renderer tests.
These fixtures assert persistence/approval behaviour, not artistic quality.
"""
import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import business_reel_caption_exports as exports
import business_reel_caption_render as renderer
import business_reel_workbench as reel
from tests import test_business_reel_finish_receipts as fixtures


class CaptionExportTests(unittest.TestCase):
    def setUp(self):
        fixtures.FinishReceiptTests.setUp(self)
        self.caption("a")
        self.caption("b")
        self.calls = []
        self.render_patch = patch.object(renderer, "render", side_effect=self.fake_render)
        self.render_patch.start()
        self.addCleanup(self.render_patch.stop)

    def caption(self, *args, **kwargs):
        return fixtures.FinishReceiptTests.caption(self, *args, **kwargs)

    def review(self, *args, **kwargs):
        return fixtures.FinishReceiptTests.review(self, *args, **kwargs)

    def choose(self, *args, **kwargs):
        return fixtures.FinishReceiptTests.choose(self, *args, **kwargs)

    def fake_render(self, video, output, **kwargs):
        self.calls.append((Path(video).read_bytes(), kwargs))
        data = b"synthetic rendered receipt fixture " + json.dumps(kwargs, sort_keys=True).encode()
        Path(output).write_bytes(data)
        return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "width": 720, "height": 1280, "duration": kwargs["expected_duration"],
                "rendererVersion": 1}

    def request(self, variant="a", state=None):
        state = state or reel.read(self.c, self.project)
        edit = next(e for e in state["edits"] if e["variant"] == variant)
        track = state["captionTracks"][variant]
        return dict(expected_content_sha256=edit["contentSha256"],
                    expected_edit_revision=edit["revision"],
                    expected_caption_revision=track["captionRevision"])

    def render(self, variant="a", request=None):
        return exports.render(self.c, self.project, variant, self.root,
                              **(request or self.request(variant)))

    def download(self, variant="a", state=None):
        state = state or reel.read(self.c, self.project)
        edit = next(e for e in state["edits"] if e["variant"] == variant)
        return exports.approved_file(self.c, self.project, variant, self.root,
                expected_content_sha256=edit["contentSha256"],
                expected_review_set_sha256=state["reviewSetSha256"])

    def test_new_video_changes_review_identity_preserves_sources_and_is_idempotent(self):
        original = (self.folder_path / "a-1.mp4").read_bytes()
        vtt = (self.folder_path / "a-edit1-captions1.vtt").read_bytes()
        self.review("a"); before = self.review("b"); self.choose(state=before)
        request = self.request(state=before)
        rendered = self.render(request=request)
        edit = next(e for e in rendered["edits"] if e["variant"] == "a")
        self.assertTrue(edit["captionsBakedIntoVideo"])
        self.assertFalse(rendered["bothEditsQualityChecked"])
        self.assertFalse(rendered["localOwnerChoiceRecorded"])
        self.assertNotEqual(edit["contentSha256"], request["expected_content_sha256"])
        self.assertEqual((self.folder_path / "a-1.mp4").read_bytes(), original)
        self.assertEqual((self.folder_path / "a-edit1-captions1.vtt").read_bytes(), vtt)
        self.assertEqual(self.calls[0][0], original)
        self.assertEqual(len(self.calls), 1)
        replay = self.render(request=request)
        self.assertEqual(replay["reviewSetSha256"], rendered["reviewSetSha256"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM business_reel_caption_exports").fetchone()[0], 1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM business_reel_owner_choice_receipts").fetchone()[0], 1)
        self.assertEqual(rendered["customerAllowanceConsumed"], 0)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM runway_cinematic_shots").fetchone()[0], 0)

    def test_review_and_download_use_the_same_captioned_bytes_and_selected_cut(self):
        self.render()
        with self.assertRaises(exports.CaptionExportError) as denied:
            self.download()
        self.assertEqual(denied.exception.code, "delivery_not_approved")
        with patch.object(reel.delivery_qc, "verify", return_value={
                "technicalReelPass": True, "audioPresent": True,
                "mobileSafeTextPass": True, "ownerBrandDetailsReviewed": True}) as review:
            self.review("a")
            self.assertEqual(review.call_args.args[0], exports.preview_file(
                self.c, self.project, "a", self.root))
        self.review("b")
        selected = self.choose()
        delivered = self.download(state=selected)
        self.assertIn(b"synthetic rendered receipt fixture", delivered.read_bytes())
        with self.assertRaises(exports.CaptionExportError):
            self.download("b", state=selected)
        self.assertFalse(selected["schedulePermitted"])

    def test_caption_edit_expires_delivery_and_preserves_prior_export_and_receipts(self):
        self.render()
        self.review("a"); self.review("b")
        chosen = self.choose()
        old = self.download(state=chosen); original = old.read_bytes()
        self.caption("a", "Different owner-written wording")
        state = reel.read(self.c, self.project)
        edit = next(e for e in state["edits"] if e["variant"] == "a")
        self.assertFalse(edit["captionsBakedIntoVideo"])
        self.assertIsNone(edit["captionExport"])
        self.assertFalse(state["localOwnerChoiceRecorded"])
        with self.assertRaises(exports.CaptionExportError):
            self.download(state=chosen)
        updated = self.render()
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM business_reel_caption_exports").fetchone()[0], 2)
        self.assertFalse(updated["bothEditsQualityChecked"])
        self.assertEqual(exports.preview_file(self.c, self.project, "a", self.root).read_bytes(),
                         b"synthetic rendered receipt fixture " + json.dumps(self.calls[-1][1], sort_keys=True).encode())

    def test_change_during_render_does_not_store_or_deliver_stale_video(self):
        original = self.fake_render
        def changed(video, output, **kwargs):
            metadata = original(video, output, **kwargs)
            self.caption("a", "New caption saved while the earlier render ran")
            return metadata
        with patch.object(renderer, "render", side_effect=changed):
            with self.assertRaises(exports.CaptionExportError) as denied:
                self.render()
        self.assertEqual(denied.exception.code, "stale_review")
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM business_reel_caption_exports").fetchone()[0], 0)
        self.assertFalse(list(self.folder_path.glob("captioned-*.mp4")))
        self.assertFalse(list(self.folder_path.glob(".caption-export-*")))
        self.assertEqual(reel.read(self.c, self.project)["captionTracks"]["a"]["captionRevision"], 2)

    def test_database_failure_removes_only_new_output(self):
        source = (self.folder_path / "a-1.mp4").read_bytes()
        self.c.execute("""CREATE TRIGGER reject_caption_receipt BEFORE INSERT ON
            business_reel_caption_exports BEGIN SELECT RAISE(ABORT,'fixture failure'); END""")
        self.c.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.render()
        self.assertFalse(list(self.folder_path.glob("captioned-*.mp4")))
        self.assertEqual((self.folder_path / "a-1.mp4").read_bytes(), source)
        self.assertFalse(self.c.in_transaction)

    def test_tampered_export_never_reuses_approval_or_silently_rerenders(self):
        self.render(); self.review("a"); self.review("b"); chosen = self.choose()
        path = self.download(state=chosen)
        path.write_bytes(b"tampered")
        with self.assertRaises(reel.ReelError):
            self.download(state=chosen)
        with self.assertRaises(reel.ReelError):
            self.render()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM business_reel_caption_exports").fetchone()[0], 1)

    def test_incomplete_cut_and_stale_request_are_rejected_before_render(self):
        old = self.request()
        self.caption("a", "New copy invalidates the old request")
        with self.assertRaises(exports.CaptionExportError):
            self.render(request=old)
        self.c.execute("""UPDATE business_reel_edits SET ordered_shots_json=?
            WHERE project_id=? AND variant='a'""",
            (json.dumps([{"slot": "hook", "seconds": 6, "sha256": "f"*64}]), self.project))
        self.c.commit()
        with self.assertRaises(exports.CaptionExportError) as denied:
            self.render()
        self.assertEqual(denied.exception.code, "incomplete_cut")
        self.assertEqual(len(self.calls), 0)


if __name__ == "__main__":
    unittest.main()
