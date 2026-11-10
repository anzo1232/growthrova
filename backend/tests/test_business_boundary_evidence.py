"""Offline boundary evidence on actual decoded source frames, never creative acceptance."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import business_media_replay as replay
import business_temporal_review as temporal
import business_boundary_evidence as boundary


class BoundaryEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='business-boundary-fixture-')
        cls.root = Path(cls.tmp.name)
        cls.video = cls.root / 'source.mp4'
        subprocess.run([
            'ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi',
            '-i', 'testsrc2=size=180x320:rate=12', '-t', '4.25',
            '-c:v', 'libx264', '-preset', 'ultrafast', str(cls.video),
        ], capture_output=True, check=True, timeout=30)
        cls.packet = replay.prepare(cls.video, cls.root/'samples', samples=6)
        cls.clips = temporal.prepare_clips(cls.video, cls.packet, cls.root/'clips')
        cls.evidence = boundary.prepare(cls.video, cls.packet, cls.clips, cls.root/'boundaries')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def resign(packet):
        packet['manifestSha256'] = boundary._fingerprint(
            {key: value for key, value in packet.items() if key != 'manifestSha256'})
        return packet

    def note(self, pair=None, **changes):
        pair = pair or self.evidence['pairs'][0]
        result = {
            'boundaryId': pair['boundaryId'],
            'leftFrameSha256': pair['leftFrameSha256'],
            'rightFrameSha256': pair['rightFrameSha256'],
            'category': 'subject_identity', 'comparison': 'inconsistent',
            'reviewOrigin': 'manual_review_declared',
            'reviewerReference': 'fixture-independent-reviewer',
            'observation': 'The property outline is inconsistent across this exact cut in fixture notes.',
        }
        result.update(changes)
        return result

    def assess(self, notes, **kw):
        return boundary.assess(self.video, self.packet, self.clips,
                               self.evidence, notes, **kw)

    def test_all_source_boundaries_have_real_pixel_pairs_and_audio_not_fabricated(self):
        self.assertTrue(boundary.verify(self.video, self.packet, self.clips, self.evidence))
        pairs = self.evidence['pairs']
        self.assertEqual(len(pairs), len(self.packet['temporalWindows'])-1)
        self.assertEqual(len(pairs), 2)
        for pair, previous, following in zip(pairs, self.clips['clips'], self.clips['clips'][1:]):
            self.assertEqual(pair['atSeconds'], previous['endSeconds'])
            self.assertEqual(pair['atSeconds'], following['startSeconds'])
            self.assertLess(pair['leftAtSeconds'], pair['atSeconds'])
            self.assertGreater(pair['rightAtSeconds'], pair['atSeconds'])
            for kind in ('leftFrameFile', 'rightFrameFile', 'pairFile'):
                self.assertTrue(Path(pair[kind]).is_file())
        self.assertFalse(self.evidence['wholeExportViewed'])
        self.assertFalse(self.evidence['creativeApproved'])
        self.assertFalse(self.evidence['canPublish'])
        self.assertEqual(self.evidence['providerCalls'], 0)

    def test_absent_and_swapped_pair_rejected_even_with_fresh_signature(self):
        for forged in (self.evidence['pairs'][:1], list(reversed(self.evidence['pairs']))):
            packet = self.resign(dict(self.evidence, pairs=forged))
            with self.assertRaises(boundary.BoundaryError):
                boundary.verify(self.video, self.packet, self.clips, packet)

    def test_relabelled_frame_time_and_pixel_hash_fail_closed(self):
        for key, value in [('atSeconds', 1.25), ('leftAtSeconds', 1.5),
                           ('rightFrameSha256', 'f'*64)]:
            forged = copy.deepcopy(self.evidence)
            forged['pairs'][0][key] = value
            with self.subTest(key=key), self.assertRaises(boundary.BoundaryError):
                boundary.verify(self.video, self.packet, self.clips, self.resign(forged))

    def test_replaced_frame_or_cropped_montage_rejected(self):
        for key in ('leftFrameFile', 'pairFile'):
            path = Path(self.evidence['pairs'][0][key])
            original = path.read_bytes()
            try:
                path.write_bytes(b'broken png')
                with self.subTest(key=key), self.assertRaises(boundary.BoundaryError):
                    boundary.verify(self.video, self.packet, self.clips, self.evidence)
            finally:
                path.write_bytes(original)

    def test_rehashed_swapped_pixels_cannot_masquerade_as_source(self):
        pair = self.evidence['pairs'][0]
        left = Path(pair['leftFrameFile'])
        original = left.read_bytes()
        try:
            left.write_bytes(Path(pair['rightFrameFile']).read_bytes())
            forged = copy.deepcopy(self.evidence)
            forged['pairs'][0]['leftFrameSha256'] = boundary._sha(left)
            # Even if a malicious actor updates the unkeyed metadata fingerprint,
            # the original video is decoded again and must match source pixels.
            with self.assertRaises(boundary.BoundaryError):
                boundary.verify(self.video, self.packet, self.clips, self.resign(forged))
        finally:
            left.write_bytes(original)

    def test_manifest_approval_forgery_is_refused(self):
        for key, value in [('canPublish', True), ('creativeApproved', True),
                           ('wholeExportViewed', True), ('providerCalls', 1),
                           ('coverage', 'independently_approved')]:
            forged = self.resign(dict(self.evidence, **{key: value}))
            with self.subTest(key=key), self.assertRaises(boundary.BoundaryError):
                boundary.verify(self.video, self.packet, self.clips, forged)

    def test_forged_new_original_and_stale_review_are_rejected(self):
        alternate = self.root/'tampered.mp4'
        alternate.write_bytes(self.video.read_bytes()+b'something')
        with self.assertRaises(boundary.BoundaryError):
            boundary.verify(alternate, self.packet, self.clips, self.evidence)
        stale = copy.deepcopy(self.evidence)
        stale['temporalManifestSha256'] = '0'*64
        with self.assertRaises(boundary.BoundaryError):
            boundary.verify(self.video, self.packet, self.clips, self.resign(stale))

    def test_no_notes_are_not_treated_as_complete_review(self):
        result = self.assess([])
        self.assertEqual(result['disposition'], 'needs_boundary_review')
        self.assertEqual(len(result['unassessedBoundaries']), 2)
        self.assertFalse(result['canPublish'])
        self.assertIsNone(result['qualityScore'])

    def test_recorded_property_identity_and_physics_failures_reject(self):
        notes = [self.note(), self.note(
            self.evidence['pairs'][1], category='physical_mechanics',
            observation='A fixture note alleges impossible liquid motion at a scene transition.')]
        result = self.assess(notes)
        self.assertTrue(result['sourceSpecificRejection'])
        self.assertEqual(result['disposition'], 'rejected_by_attributed_boundary_finding')
        self.assertFalse(result['creativeApproved'])

    def test_complete_positive_declarations_still_do_not_approve(self):
        notes = [self.note(pair, comparison='consistent',
                           observation='A fixture makes a limited continuity claim, not creative approval.')
                 for pair in self.evidence['pairs']]
        result = self.assess(notes)
        self.assertEqual(result['unassessedBoundaries'], [])
        self.assertEqual(result['disposition'], 'needs_independent_creative_review')
        self.assertFalse(result['canPublish'])

    def test_uncertainty_is_exposed_and_not_silent_acceptance(self):
        result = self.assess([self.note(comparison='uncertain')])
        self.assertEqual(result['disposition'], 'hold_uncertain_boundary_evidence')
        self.assertIn(self.evidence['pairs'][0]['boundaryId'], result['uncertainBoundaries'])
        self.assertFalse(result['canPublish'])

    def test_invalid_or_foreign_notes_fail(self):
        invalid = [
            {'rightFrameSha256':'a'*64}, {'category':'foo'},
            {'comparison':'approved'}, {'reviewOrigin':'ai_generated_ground_truth'},
            {'observation':'Looks good'}, {'reviewerReference':'x'},
            {'boundaryId':self.evidence['pairs'][1]['boundaryId']},
        ]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(boundary.BoundaryError):
                self.assess([self.note(**fields)])

    def test_verified_prior_negative_cannot_be_downgraded(self):
        prior = temporal.assess_clip_findings(self.video, self.packet, self.clips, [{
            'windowId': self.clips['clips'][0]['windowId'],
            'clipSha256': self.clips['clips'][0]['clipSha256'],
            'atSeconds': 0.5, 'category': 'physical_realism', 'severity': 'major',
            'reviewerReference': 'fixture-prior-reviewer',
            'reviewOrigin': 'manual_review_declared',
            'observation': 'This is a pre-existing labelled fixture rejection, not a new visual verdict.',
        }])
        complete = [self.note(pair, comparison='consistent',
                              observation='A positive fixture annotation must not erase a prior rejection.')
                    for pair in self.evidence['pairs']]
        result = self.assess(complete, prior_temporal_assessment=prior)
        self.assertEqual(result['disposition'], 'rejected_by_prior_or_boundary_finding')
        self.assertTrue(result['sourceSpecificRejection'])
        with self.assertRaises(boundary.BoundaryError):
            self.assess([], prior_temporal_assessment=dict(prior, sourceSpecificRejection=False))


if __name__ == '__main__':
    unittest.main()
