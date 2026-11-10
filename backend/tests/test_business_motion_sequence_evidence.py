"""Offline actual-decoded source-frame progression: held/negative fixtures, never approval."""
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

import business_media_replay as replay
import business_temporal_review as temporal
import business_motion_sequence_evidence as motion


class MotionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="business-motion-fixture-")
        cls.root = Path(cls.tmp.name)
        cls.video = cls.root / "source.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-nostdin",
            "-f", "lavfi", "-i", "testsrc2=s=160x288:r=12:d=4",
            "-c:v", "libx264", "-preset", "ultrafast", str(cls.video),
        ], capture_output=True, check=True, timeout=30)
        cls.packet = replay.prepare(cls.video, cls.root / "samples", samples=6)
        cls.timeline = temporal.prepare_clips(cls.video, cls.packet, cls.root / "clips")
        cls.requests = [
            {"atSeconds": 1.0, "category": "object_path",
             "reviewPrompt": "Check the motion path across these source frames; no fixture truth claimed."},
            {"atSeconds": 2.5, "category": "subject_identity",
             "reviewPrompt": "Compare identity across adjacent source frames; uncertain until real review."},
        ]
        cls.evidence = motion.prepare(cls.video, cls.packet, cls.timeline,
                                      cls.requests, cls.root / "progression")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def sign(self, document):
        document["manifestSha256"] = motion._fingerprint({
            k: v for k, v in document.items() if k != "manifestSha256"
        })
        return document

    def test_measured_original_frame_pts_and_source_pixel_binding(self):
        self.assertTrue(motion.verify(self.video, self.packet, self.timeline, self.evidence))
        self.assertEqual(len(self.evidence["requests"]), 2)
        for request in self.evidence["requests"]:
            self.assertEqual(len(request["frames"]), 5)
            pts = [f["framePtsSeconds"] for f in request["frames"]]
            indexes = [f["frameIndex"] for f in request["frames"]]
            self.assertEqual(pts, sorted(pts))
            self.assertEqual(indexes, sorted(indexes))
            self.assertTrue(all(Path(f["frameFile"]).is_file() for f in request["frames"]))
            self.assertEqual(len(request["adjacentPixelChange"]), 4)
        self.assertEqual(self.evidence["providerCalls"], 0)
        self.assertFalse(self.evidence["creativeApproved"])
        self.assertFalse(self.evidence["canPublish"])

    def test_missing_or_modified_frame_fails_even_with_hash_replaced(self):
        frame = self.evidence["requests"][0]["frames"][0]
        path = Path(frame["frameFile"])
        original = path.read_bytes()
        try:
            path.write_bytes(Path(self.evidence["requests"][0]["frames"][1]["frameFile"]).read_bytes())
            modified = copy.deepcopy(self.evidence)
            modified["requests"][0]["frames"][0]["frameSha256"] = motion._sha(path)
            with self.assertRaises(motion.MotionEvidenceError):
                motion.verify(self.video, self.packet, self.timeline, self.sign(modified))
        finally:
            path.write_bytes(original)

    def test_forged_pts_or_source_frame_index_fails_even_if_resigned(self):
        for key, value in [("framePtsSeconds", 2.111), ("frameIndex", 888)]:
            modified = copy.deepcopy(self.evidence)
            modified["requests"][0]["frames"][0][key] = value
            with self.subTest(key=key), self.assertRaises(motion.MotionEvidenceError):
                motion.verify(self.video, self.packet, self.timeline, self.sign(modified))

    def test_saved_manifest_cannot_be_tampered_or_removed(self):
        saved = Path(self.evidence["reviewDirectory"]) / "motion-sequence-manifest.json"
        original = saved.read_bytes()
        try:
            saved.write_text('{"creativeApproved":true}')
            with self.assertRaises(motion.MotionEvidenceError):
                motion.verify(self.video, self.packet, self.timeline, self.evidence)
        finally:
            saved.write_bytes(original)

    def test_missing_request_or_duplicate_anchor_does_not_prove_coverage(self):
        modified = copy.deepcopy(self.evidence)
        modified["requests"] = modified["requests"][:1]
        with self.assertRaises(motion.MotionEvidenceError):
            motion.verify(self.video, self.packet, self.timeline, self.sign(modified))
        with self.assertRaises(motion.MotionEvidenceError):
            motion.prepare(self.video, self.packet, self.timeline,
                           [self.requests[0], self.requests[0]], self.root / "unused")

    def test_source_tampering_rejected(self):
        altered = self.root / "changed.mp4"
        altered.write_bytes(self.video.read_bytes() + b"modified")
        with self.assertRaises(motion.MotionEvidenceError):
            motion.verify(altered, self.packet, self.timeline, self.evidence)

    def test_rejects_false_approval_and_tampered_change_scores(self):
        for key, value in [("creativeApproved", True), ("wholeExportViewed", True),
                           ("providerCalls", 1), ("coverage", "all_motion_good")]:
            altered = copy.deepcopy(self.evidence)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(motion.MotionEvidenceError):
                motion.verify(self.video, self.packet, self.timeline, self.sign(altered))
        altered = copy.deepcopy(self.evidence)
        altered["requests"][0]["adjacentPixelChange"][0] = 0
        with self.assertRaises(motion.MotionEvidenceError):
            motion.verify(self.video, self.packet, self.timeline, self.sign(altered))

    def test_unreviewed_source_progression_stays_hold(self):
        assessment = motion.assess(self.video, self.packet, self.timeline, self.evidence, [])
        self.assertFalse(assessment["canPublish"])
        self.assertIsNone(assessment["qualityScore"])
        self.assertEqual(assessment["disposition"], "needs_independent_motion_review")
        self.assertEqual(len(assessment["pendingRequestIds"]), 2)

    def test_declared_inconsistent_finding_rejects_but_cannot_auto_approve(self):
        request = self.evidence["requests"][0]
        note = {
            "requestId": request["requestId"],
            "sourceSha256": self.evidence["sourceSha256"],
            "frameSha256s": [f["frameSha256"] for f in request["frames"]],
            "category": request["category"], "comparison": "inconsistent",
            "reviewOrigin": "manual_review_declared",
            "reviewerReference": "fixture-source-reviewer",
            "observation": "The fixture reviewer claims inconsistent movement; no commercial truth label.",
        }
        assessment = motion.assess(self.video, self.packet, self.timeline,
                                   self.evidence, [note])
        self.assertTrue(assessment["sourceSpecificRejection"])
        self.assertEqual(assessment["disposition"], "rejected_by_source_motion_finding")
        note["comparison"] = "consistent"
        neutral = motion.assess(self.video, self.packet, self.timeline,
                                self.evidence, [note])
        self.assertFalse(neutral["sourceSpecificRejection"])
        self.assertFalse(neutral["canPublish"])
        note["frameSha256s"][0] = "0" * 64
        with self.assertRaises(motion.MotionEvidenceError):
            motion.assess(self.video, self.packet, self.timeline, self.evidence, [note])

    def test_prior_rejection_not_cleared_by_empty_motion_review(self):
        prior = replay.assess(self.video, self.packet, [{
            "type": "project_feedback", "category": "physical_realism",
            "severity": "major", "reviewerReference": "fixture-old-rejection",
            "observation": "This is a synthetic negative fixture, not actual footage accepted by anyone.",
        }])
        result = motion.assess(self.video, self.packet, self.timeline, self.evidence, [],
                               prior_replay_assessment=prior)
        self.assertFalse(result["canPublish"])
        self.assertEqual(result["disposition"], "hold_prior_unlocated_feedback")

    def test_prior_source_pixel_rejection_persists_without_new_motion_notes(self):
        sample = self.packet["sampledFrames"][0]
        prior = replay.assess(self.video, self.packet, [{
            "type": "sampled_frame", "category": "physics",
            "severity": "major", "reviewerReference": "fixture-negative-source",
            "observation": "Synthetic fixture reviewer reported a physics defect, not a real approval.",
            "frameIndex": sample["index"], "frameSha256": sample["sha256"],
        }])
        result = motion.assess(self.video, self.packet, self.timeline, self.evidence, [],
                               prior_replay_assessment=prior)
        self.assertTrue(result["sourceSpecificRejection"])
        self.assertEqual(result["disposition"], "rejected_by_prior_or_source_motion_finding")

    def test_all_positive_declared_motion_notes_still_not_approval(self):
        notes = []
        for request in self.evidence["requests"]:
            notes.append({
                "requestId": request["requestId"], "sourceSha256": self.evidence["sourceSha256"],
                "frameSha256s": [f["frameSha256"] for f in request["frames"]],
                "category": request["category"], "comparison": "consistent",
                "reviewOrigin": "manual_review_declared",
                "reviewerReference": "fixture-positive-declaration",
                "observation": "Synthetic fixture states the example looked consistent; no physical truth claimed.",
            })
        assessment = motion.assess(self.video, self.packet, self.timeline, self.evidence, notes)
        self.assertEqual(assessment["pendingRequestIds"], [])
        self.assertFalse(assessment["canPublish"])
        self.assertFalse(assessment["creativeApproved"])
        self.assertIsNone(assessment["qualityScore"])

    def test_unreviewable_times_and_unknown_category_fail_before_extraction(self):
        for invalid in [
            {"atSeconds": -0.1, "category": "object_path",
             "reviewPrompt": "Inspect the complete original frames for path continuity."},
            {"atSeconds": 1.2, "category": "unknown_specialist_skill",
             "reviewPrompt": "Inspect the complete original frames for path continuity."},
            {"atSeconds": 9999.0, "category": "object_path",
             "reviewPrompt": "Inspect the complete original frames for path continuity."},
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(motion.MotionEvidenceError):
                motion.prepare(self.video, self.packet, self.timeline, [invalid],
                               self.root / "uncreated-invalid")



if __name__ == "__main__":
    unittest.main()
