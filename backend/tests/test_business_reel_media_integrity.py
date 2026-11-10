"""Actual damaged compressed packets must not pass source or delivery checks.

The synthetic media is a decoding regression fixture, never client acceptance.
"""
import hashlib
import json
import subprocess
import unittest

import business_reel_delivery_qc as delivery
import business_reel_owner_media as owner_media
from tests import test_business_reel_delivery_qc as delivery_fixture
from tests import test_business_reel_owner_media as owner_fixture


def damage_interior_packet(path, stream):
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', stream,
        '-show_packets', '-show_entries', 'packet=pos,size', '-of', 'json', str(path)],
        check=True, capture_output=True, timeout=15)
    packets = json.loads(result.stdout)['packets']
    packet = packets[len(packets) // 2]
    start, size = int(packet['pos']), int(packet['size'])
    data = bytearray(path.read_bytes())
    data[start:start + size] = b'\x00' * size
    path.write_bytes(data)
    # This is an actual decoder failure with a parseable container and unchanged
    # file size, not an exception or subprocess success mocked by the test.
    decoded = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path),
        '-map', '0:' + stream + ':0', '-f', 'null', '-'],
        capture_output=True, timeout=25)
    if not decoded.stderr.strip():
        raise AssertionError('Damaged fixture did not produce a real decoder error')
    return hashlib.sha256(bytes(data)).hexdigest()


class FinalDeliveryDecodeIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = delivery_fixture.CompleteReelQC('test_audio_crop_brand_claims_checks_then_human_signoff_required')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def assert_damaged_delivery_rejected(self, stream):
        fixture = self.fixture
        digest = damage_interior_packet(fixture.sample, stream)
        with self.assertRaises(delivery.DeliveryError):
            delivery.verify(fixture.sample, expected_duration=5,
                            approval=fixture.attested, has_audio_evidence=True)
        self.assertEqual(hashlib.sha256(fixture.sample.read_bytes()).hexdigest(), digest)

    def test_corrupt_video_cannot_pass_final_approval(self):
        self.assert_damaged_delivery_rejected('v')

    def test_corrupt_audio_cannot_pass_with_normal_loudness(self):
        self.assert_damaged_delivery_rejected('a')


class OwnerSourceDecodeIntegrityTests(unittest.TestCase):
    def test_source_normalisation_cannot_hide_damaged_camera_packet(self):
        fixture = owner_fixture.ExistingAuthorisedFootageTests('test_failed_owner_media_commit_cleans_new_output_and_preserves_source')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        digest = damage_interior_packet(fixture.original, 'v')
        with self.assertRaises(owner_media.OwnerMediaError) as rejected:
            owner_media.select(fixture.con, fixture.project, 'hook', fixture.src,
                fixture.root, owner_confirmed=True,
                rights_note='Self-created technical video for local decoder integrity testing only.')
        self.assertEqual(rejected.exception.code, 'source_decode_failed')
        self.assertEqual(fixture.con.execute('SELECT COUNT(*) FROM business_reel_owner_media').fetchone()[0], 0)
        folder = fixture.root / 'reel_workbench' / fixture.project
        self.assertFalse((folder / 'real-hook.mp4').exists())
        self.assertFalse((folder / '.real-hook-pending.mp4').exists())
        self.assertEqual(hashlib.sha256(fixture.original.read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
