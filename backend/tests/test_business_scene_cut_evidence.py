"""Offline scene-change candidate evidence: never conflate detector hits with approved cuts."""
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

import business_media_replay as replay
import business_temporal_review as temporal
import business_scene_cut_evidence as cuts


class SceneCutEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='business-cut-fixture-')
        cls.root = Path(cls.tmp.name)
        cls.video = cls.root/'source.mp4'
        subprocess.run([
            'ffmpeg', '-v', 'error', '-nostdin',
            '-f', 'lavfi', '-i', 'color=c=red:s=180x320:r=12:d=1.5',
            '-f', 'lavfi', '-i', 'color=c=blue:s=180x320:r=12:d=1.5',
            '-f', 'lavfi', '-i', 'color=c=green:s=180x320:r=12:d=1.5',
            '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]',
            '-map', '[v]', '-c:v', 'libx264', '-preset', 'ultrafast',
            str(cls.video),
        ], capture_output=True, check=True, timeout=30)
        cls.packet = replay.prepare(cls.video, cls.root/'samples', samples=6)
        cls.temporal = temporal.prepare_clips(cls.video, cls.packet, cls.root/'clips')
        cls.manifest = cuts.prepare(cls.video, cls.packet, cls.temporal, cls.root/'detected-cuts')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def sign(self, manifest):
        manifest['manifestSha256'] = cuts._fingerprint({
            k: v for k, v in manifest.items() if k != 'manifestSha256'
        })
        return manifest

    def evidence(self, **changes):
        return self.sign(dict(copy.deepcopy(self.manifest), **changes))

    def note(self, candidate=None, **changes):
        item = candidate or self.manifest['candidates'][0]
        result = {
            'candidateId': item['candidateId'],
            'sourcePtsSeconds': item['sourcePtsSeconds'],
            'leftFrameSha256': item['leftFrameSha256'],
            'rightFrameSha256': item['rightFrameSha256'],
            'category': 'subject_identity', 'comparison': 'inconsistent',
            'reviewOrigin': 'manual_review_declared',
            'reviewerReference': 'fixture-independent-reviewer',
            'observation': 'The test review identifies an abrupt visual change, not a real identity verdict.',
        }
        result.update(changes)
        return result

    def assess(self, notes, **kwargs):
        return cuts.assess(self.video, self.packet, self.temporal,
                           self.manifest, notes, **kwargs)

    def test_detects_actual_source_pts_not_fixed_review_grid(self):
        self.assertTrue(cuts.verify(self.video, self.packet, self.temporal, self.manifest))
        hits = self.manifest['candidates']
        self.assertEqual(len(hits), 2)
        self.assertEqual([v['sourcePtsSeconds'] for v in hits], [1.5, 3.0])
        self.assertNotEqual(hits[0]['sourcePtsSeconds'], 2.0)
        self.assertEqual(self.manifest['candidateCount'], len(hits))
        self.assertEqual(self.manifest['sourceSha256'], self.packet['sourceSha256'])
        self.assertEqual(self.manifest['coverage'],
                         'source_scene_change_candidates_not_exhaustive_edit_detection')

    def test_all_candidate_pixels_and_montages_are_source_verified(self):
        for hit in self.manifest['candidates']:
            self.assertLess(hit['leftAtSeconds'], hit['sourcePtsSeconds'])
            self.assertGreater(hit['rightAtSeconds'], hit['sourcePtsSeconds'])
            for key in ('leftFrameFile','rightFrameFile','pairFile'):
                self.assertTrue(Path(hit[key]).is_file())
        self.assertFalse(self.manifest['wholeExportViewed'])
        self.assertFalse(self.manifest['creativeApproved'])
        self.assertFalse(self.manifest['canPublish'])
        self.assertEqual(self.manifest['providerCalls'], 0)
        self.assertEqual(self.manifest['networkRequests'], 0)

    def test_resigned_missing_reordered_or_retimed_candidates_fail(self):
        first, second = self.manifest['candidates']
        for edited in ([first], [second, first], [dict(first, sourcePtsSeconds=2.0), second],
                       [dict(first, leftAtSeconds=0.5), second]):
            with self.subTest(edited=edited), self.assertRaises(cuts.SceneCutError):
                cuts.verify(self.video, self.packet, self.temporal,
                            self.evidence(candidates=edited))

    def test_resigned_new_detector_threshold_or_false_complete_claim_fails(self):
        for change in ({'sceneThreshold': 0.01}, {'candidateCount': 0},
                       {'wholeExportViewed': True}, {'canPublish': True},
                       {'creativeApproved': True}, {'providerCalls': 1},
                       {'coverage': 'all_real_cuts_verified'}):
            with self.subTest(change=change), self.assertRaises(cuts.SceneCutError):
                cuts.verify(self.video, self.packet, self.temporal, self.evidence(**change))

    def test_saved_manifest_must_match_verified_object(self):
        saved = Path(self.manifest['reviewDirectory'])/'scene-cut-manifest.json'
        original = saved.read_bytes()
        try:
            saved.write_text('{"creativeApproved":true}')
            with self.assertRaises(cuts.SceneCutError):
                cuts.verify(self.video, self.packet, self.temporal, self.manifest)
        finally:
            saved.write_bytes(original)

    def test_tampered_png_and_montage_fail_even_with_new_hash(self):
        hit = self.manifest['candidates'][0]
        for path_key, hash_key in (('leftFrameFile','leftFrameSha256'),
                                   ('pairFile','pairSha256')):
            path = Path(hit[path_key])
            original = path.read_bytes()
            try:
                other = self.manifest['candidates'][1]
                path.write_bytes(Path(other[path_key]).read_bytes())
                forged = copy.deepcopy(self.manifest)
                forged['candidates'][0][hash_key] = cuts._sha(path)
                with self.subTest(path=path_key), self.assertRaises(cuts.SceneCutError):
                    cuts.verify(self.video, self.packet, self.temporal, self.sign(forged))
            finally:
                path.write_bytes(original)

    def test_stale_source_replay_or_temporal_manifest_fails(self):
        other = self.root/'other.mp4'
        other.write_bytes(self.video.read_bytes() + b'extra')
        with self.assertRaises(cuts.SceneCutError):
            cuts.verify(other, self.packet, self.temporal, self.manifest)
        with self.assertRaises(cuts.SceneCutError):
            cuts.verify(self.video, self.packet, self.temporal,
                        self.evidence(temporalManifestSha256='0'*64))

    def test_source_without_detected_change_is_not_cleared_for_delivery(self):
        still = self.root/'uniform.mp4'
        subprocess.run([
            'ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi',
            '-i', 'color=c=red:s=180x320:r=12:d=3',
            '-c:v', 'libx264', '-preset', 'ultrafast', str(still),
        ], capture_output=True, check=True, timeout=30)
        packet = replay.prepare(still, self.root/'still-samples', samples=4)
        clips = temporal.prepare_clips(still, packet, self.root/'still-clips')
        manifest = cuts.prepare(still, packet, clips, self.root/'still-cuts')
        self.assertEqual(manifest['candidateCount'], 0)
        self.assertTrue(cuts.verify(still, packet, clips, manifest))
        assessed = cuts.assess(still, packet, clips, manifest, [])
        self.assertEqual(assessed['disposition'], 'needs_independent_original_video_review')
        self.assertFalse(assessed['canPublish'])

    def test_absent_annotations_are_not_human_review(self):
        assessed = self.assess([])
        self.assertEqual(len(assessed['unassessedCandidates']), 2)
        self.assertEqual(assessed['disposition'], 'needs_candidate_review')
        self.assertFalse(assessed['canPublish'])
        self.assertIsNone(assessed['qualityScore'])

    def test_recorded_identity_and_physics_failures_reject_and_remain_attributed(self):
        assessed = self.assess([
            self.note(),
            self.note(self.manifest['candidates'][1], category='physical_mechanics',
                      observation='The test reviewer flags water physics at the second candidate anchor.'),
        ])
        self.assertEqual(assessed['disposition'], 'rejected_by_attributed_candidate_finding')
        self.assertTrue(assessed['sourceSpecificRejection'])
        self.assertEqual(len(assessed['observations']), 2)

    def test_all_consistent_declarations_still_never_creatively_approve(self):
        notes = [self.note(hit, comparison='consistent') for hit in self.manifest['candidates']]
        assessed = self.assess(notes)
        self.assertEqual(assessed['unassessedCandidates'], [])
        self.assertEqual(assessed['disposition'], 'needs_independent_original_video_review')
        self.assertFalse(assessed['canPublish'])

    def test_uncertain_and_invalid_observations_fail_closed(self):
        assessed = self.assess([self.note(comparison='uncertain')])
        self.assertEqual(assessed['disposition'], 'hold_uncertain_scene_change')
        for invalid in ({'candidateId':'other'}, {'sourcePtsSeconds':2.0},
                        {'comparison':'approved'}, {'reviewOrigin':'ai_self_label'},
                        {'observation':'looks good'}, {'leftFrameSha256':'0'*64}):
            with self.subTest(invalid=invalid), self.assertRaises(cuts.SceneCutError):
                self.assess([self.note(**invalid)])
        with self.assertRaises(cuts.SceneCutError):
            self.assess([self.note(), self.note()])

    def test_prior_rejection_cannot_be_reversed_by_new_notes(self):
        prior = temporal.assess_clip_findings(self.video, self.packet, self.temporal, [{
            'windowId': self.temporal['clips'][0]['windowId'],
            'clipSha256': self.temporal['clips'][0]['clipSha256'],
            'atSeconds': 0.5,
            'category': 'physical_realism', 'severity': 'major',
            'reviewerReference': 'fixture-preexisting-reviewer',
            'reviewOrigin': 'manual_review_declared',
            'observation': 'An earlier fixture-specific rejection must be retained without reinterpretation.',
        }])
        positives = [self.note(c, comparison='consistent') for c in self.manifest['candidates']]
        result = self.assess(positives, prior_temporal_assessment=prior)
        self.assertEqual(result['disposition'], 'rejected_by_prior_or_candidate_finding')
        with self.assertRaises(cuts.SceneCutError):
            self.assess([], prior_temporal_assessment=dict(prior, sourceSpecificRejection=False))


if __name__ == '__main__':
    unittest.main()
