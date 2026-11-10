"""Offline playable temporal evidence. Fixtures do not establish creative quality."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import business_media_replay as replay
import business_temporal_review as temporal


class TemporalReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox = tempfile.TemporaryDirectory(prefix='business-temporal-test-')
        cls.root = Path(cls.sandbox.name)
        cls.video = cls.root / 'source.mp4'
        subprocess.run([
            'ffmpeg', '-v', 'error', '-nostdin',
            '-f', 'lavfi', '-i', 'testsrc2=size=180x320:rate=12',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100',
            '-t', '3.25', '-c:v', 'libx264', '-preset', 'ultrafast',
            '-c:a', 'aac', '-shortest', str(cls.video),
        ], check=True, capture_output=True, timeout=30)
        cls.packet = replay.prepare(cls.video, cls.root / 'samples', samples=6)
        cls.manifest = temporal.prepare_clips(cls.video, cls.packet, cls.root / 'clips')

    @classmethod
    def tearDownClass(cls):
        cls.sandbox.cleanup()

    @staticmethod
    def signed(manifest):
        manifest['manifestSha256'] = temporal._fingerprint(
            {k: v for k, v in manifest.items() if k != 'manifestSha256'}
        )
        return manifest

    def finding(self, **overrides):
        clip = self.manifest['clips'][0]
        note = {
            'windowId': clip['windowId'],
            'clipSha256': clip['clipSha256'],
            'atSeconds': clip['startSeconds'] + 0.5,
            'category': 'physics', 'severity': 'major',
            'reviewerReference': 'independent-reviewer-logged',
            'reviewOrigin': 'manual_review_declared',
            'observation': 'A reviewer flagged a questionable physical interaction at this source time.',
        }
        note.update(overrides)
        return note

    def test_real_playable_video_and_audio_cover_every_temporal_window(self):
        self.assertTrue(temporal.verify_clips(self.video, self.packet, self.manifest))
        self.assertEqual(len(self.manifest['clips']), len(self.packet['temporalWindows']))
        self.assertEqual(len(self.manifest['clips']), 2)
        for clip, expected in zip(self.manifest['clips'], self.packet['temporalWindows']):
            self.assertEqual((clip['startSeconds'], clip['endSeconds']),
                             (expected['startSeconds'], expected['endSeconds']))
            self.assertTrue(clip['hasVideo'])
            self.assertTrue(clip['hasAudio'])
            self.assertGreater(clip['decodedVideoFrames'], 0)
            self.assertLess(abs(clip['clipDurationSeconds'] - (
                clip['playbackEndSeconds'] - clip['playbackStartSeconds'])), 0.16)
            self.assertTrue(Path(clip['clipFile']).is_file())
        self.assertEqual(self.manifest['coverage'],
                         'full_timeline_playable_derivative_clips_not_verified_watching')
        self.assertFalse(self.manifest['wholeExportViewed'])
        self.assertFalse(self.manifest['creativeApproved'])
        self.assertEqual(self.manifest['providerCalls'], 0)

    def test_boundary_handles_preserve_continuity_context(self):
        first, second = self.manifest['clips']
        self.assertEqual(first['playbackStartSeconds'], 0)
        self.assertEqual(second['playbackEndSeconds'], self.packet['durationSeconds'])
        self.assertGreater(first['playbackEndSeconds'], second['startSeconds'])
        self.assertLess(second['playbackStartSeconds'], first['endSeconds'])
        for clip in (first, second):
            self.assertLessEqual(clip['playbackStartSeconds'], clip['startSeconds'])
            self.assertGreaterEqual(clip['playbackEndSeconds'], clip['endSeconds'])

    def test_forged_full_view_or_approval_is_rejected_even_if_resigned(self):
        for key, value in [('wholeExportViewed', True), ('creativeApproved', True),
                           ('coverage', 'verified_human_review'), ('providerCalls', 1)]:
            with self.subTest(key=key):
                modified = self.signed(dict(self.manifest, **{key: value}))
                with self.assertRaises(temporal.TemporalReviewError):
                    temporal.verify_clips(self.video, self.packet, modified)

    def test_missing_or_swapped_window_cannot_claim_complete_playback(self):
        incomplete = self.signed(dict(self.manifest, clips=self.manifest['clips'][:1]))
        with self.assertRaises(temporal.TemporalReviewError):
            temporal.verify_clips(self.video, self.packet, incomplete)
        swapped = self.signed(dict(self.manifest, clips=list(reversed(self.manifest['clips']))))
        with self.assertRaises(temporal.TemporalReviewError):
            temporal.verify_clips(self.video, self.packet, swapped)

    def test_mutated_clip_or_missing_clip_is_not_accepted(self):
        clip = Path(self.manifest['clips'][0]['clipFile'])
        content = clip.read_bytes()
        try:
            clip.write_bytes(content + b'tamper')
            with self.assertRaises(temporal.TemporalReviewError):
                temporal.verify_clips(self.video, self.packet, self.manifest)
            clip.unlink()
            with self.assertRaises(temporal.TemporalReviewError):
                temporal.verify_clips(self.video, self.packet, self.manifest)
        finally:
            clip.write_bytes(content)

    def test_rebound_source_and_replay_packet_fail_closed(self):
        alternate = self.root / 'alternate.mp4'
        alternate.write_bytes(self.video.read_bytes() + b'changed')
        with self.assertRaises(temporal.TemporalReviewError):
            temporal.verify_clips(alternate, self.packet, self.manifest)
        forged = dict(self.packet, sourceSha256='0' * 64)
        with self.assertRaises(temporal.TemporalReviewError):
            temporal.verify_clips(self.video, forged, self.manifest)

    def test_wrong_clip_hash_and_timestamp_cannot_be_given_specific_finding(self):
        with self.assertRaises(temporal.TemporalReviewError):
            temporal.assess_clip_findings(
                self.video, self.packet, self.manifest,
                [self.finding(clipSha256='f' * 64)])
        with self.assertRaises(temporal.TemporalReviewError):
            temporal.assess_clip_findings(
                self.video, self.packet, self.manifest,
                [self.finding(atSeconds=self.manifest['clips'][0]['endSeconds'] + 0.01)])

    def test_source_specific_bad_motion_finding_rejects_not_approves(self):
        report = temporal.assess_clip_findings(
            self.video, self.packet, self.manifest, [self.finding()])
        self.assertEqual(report['disposition'], 'rejected_by_attributed_clip_finding')
        self.assertTrue(report['sourceSpecificRejection'])
        self.assertFalse(report['wholeExportViewed'])
        self.assertFalse(report['creativeApproved'])
        self.assertFalse(report['published'])
        self.assertEqual(len(report['annotatedWindows']), 1)
        self.assertEqual(len(report['unannotatedWindows']), 1)

    def test_even_all_positive_fixture_notes_cannot_imply_creative_approval(self):
        findings = [self.finding(
            windowId=clip['windowId'], clipSha256=clip['clipSha256'],
            atSeconds=(clip['startSeconds'] + clip['endSeconds']) / 2,
            severity='none', category='motion',
            observation='Offline test fixture note only; perceptual quality is unverified.'
        ) for clip in self.manifest['clips']]
        report = temporal.assess_clip_findings(self.video, self.packet, self.manifest, findings)
        self.assertEqual(report['disposition'], 'needs_independent_creative_review')
        self.assertEqual(len(report['unannotatedWindows']), 0)
        self.assertFalse(report['wholeExportViewed'])
        self.assertFalse(report['creativeApproved'])

    def test_invalid_review_origin_and_unlocated_project_claims_are_blocked(self):
        for fields in ({'reviewOrigin':'ai_generated_quality_ground_truth'},
                       {'reviewerReference':'x'},
                       {'observation':'Looks good'},
                       {'category':'roofing'},
                       {'type':'project_feedback'}):
            with self.subTest(fields=fields), self.assertRaises(temporal.TemporalReviewError):
                temporal.assess_clip_findings(
                    self.video, self.packet, self.manifest, [self.finding(**fields)])

    def test_manifest_forgery_does_not_change_actual_clip_duration(self):
        changed = copy.deepcopy(self.manifest)
        changed['clips'][0]['clipDurationSeconds'] = 0.05
        with self.assertRaises(temporal.TemporalReviewError):
            temporal.verify_clips(self.video, self.packet, self.signed(changed))

    def test_previous_verified_rejection_cannot_be_downgraded_by_empty_notes(self):
        frame = self.packet['sampledFrames'][0]
        prior = replay.assess(self.video, self.packet, [{
            'type': 'sampled_frame', 'category': 'physics', 'severity': 'major',
            'frameIndex': frame['index'], 'frameSha256': frame['sha256'],
            'reviewerReference': 'offline-fixture-prior-review',
            'observation': 'A prior negative finding on a labelled synthetic test fixture.',
        }])
        report = temporal.assess_clip_findings(
            self.video, self.packet, self.manifest, [], prior_replay_assessment=prior)
        self.assertEqual(report['disposition'], 'rejected_by_prior_or_clip_finding')
        self.assertTrue(report['sourceSpecificRejection'])
        self.assertTrue(report['priorReplaySourceSpecificRejection'])

    def test_unlocated_prior_rejection_feedback_remains_a_hold(self):
        prior = replay.assess(self.video, self.packet, [{
            'type': 'project_feedback', 'category': 'people', 'severity': 'critical',
            'reviewerReference': 'project-user-offline-fixture',
            'observation': 'The earlier project was rejected for unsuitable synthetic workers.',
        }])
        result = temporal.assess_clip_findings(
            self.video, self.packet, self.manifest, [], prior_replay_assessment=prior)
        self.assertEqual(result['disposition'], 'hold_prior_unlocated_feedback')
        self.assertFalse(result['sourceSpecificRejection'])

    def test_tampered_or_foreign_prior_review_is_not_trusted(self):
        prior = replay.assess(self.video, self.packet, [])
        for changed in (dict(prior, creativeApproved=True),
                        dict(prior, sourceSha256='f'*64),
                        dict(prior, sourceSpecificRejection=True)):
            with self.subTest(changed=changed), self.assertRaises(temporal.TemporalReviewError):
                temporal.assess_clip_findings(
                    self.video, self.packet, self.manifest, [],
                    prior_replay_assessment=changed)

    def test_manifest_cannot_be_used_as_video_quality_score(self):
        result = temporal.assess_clip_findings(
            self.video, self.packet, self.manifest, [])
        self.assertEqual(result['disposition'], 'needs_temporal_review')
        self.assertEqual(result['providerCalls'], 0)
        self.assertEqual(result['networkRequests'], 0)
        self.assertIsNone(result['qualityScore'])
        self.assertFalse(result['canPublish'])


if __name__ == '__main__':
    unittest.main()
