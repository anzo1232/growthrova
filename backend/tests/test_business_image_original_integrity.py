"""Original downloads preserve held drafts, but never mislabel unknown pixels."""
from contextlib import closing
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from tests import test_business_growthrova_images as fixtures
from tests.test_business_growthrova_preview import OTHER


class ImageOriginalIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.flow = fixtures.GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.flow.configured()
        self.candidate = self.flow.generate().json
        self.url = self.flow.url + '/' + self.candidate['operationId'] + '/original'

    def retain(self, candidate, pixels):
        with closing(sqlite3.connect(self.flow.path)) as con:
            con.execute('UPDATE growthrova_image_requests SET result_json=?,image_bytes=? '
                        'WHERE document_id=? AND operation_id=?',
                        (json.dumps(candidate), pixels, self.flow.ident, self.candidate['operationId']))
            con.commit()

    def download(self, client=None):
        return (client or self.flow.client).get(self.url, headers=self.flow.headers)

    def test_corrupt_or_unknown_original_is_held_across_reopen_without_inference(self):
        f = self.flow
        for state, pixels, sha in (
            ('proposed', b'corrupt retained bytes', self.candidate['sha256']),
            ('held', f.provider.png, ''),
            ('uncertain', f.provider.png, self.candidate['sha256']),
            ('pending', f.provider.png, self.candidate['sha256']),
        ):
            with self.subTest(state=state, sha=sha):
                self.retain({**self.candidate, 'state': state, 'sha256': sha}, pixels)
                response = self.download(f.create().test_client())
                self.assertEqual(response.status_code, 409, 'Never serve unknown bytes as image/png')
                self.assertEqual(response.json['code'], 'image_held')
                self.assertIn('saved', response.json['error'].lower())
                self.assertNotEqual(response.mimetype, 'image/png')
        self.assertEqual(len(f.provider.calls), 1, 'A held download cannot regenerate or retry')

    def test_download_rechecks_revoked_org_before_returning_pixels(self):
        f = self.flow
        # Revocation can occur during the local BLOB/hash read. Observe the
        # actual hash boundary rather than replacing route/auth behavior.
        import business_growthrova_images as images
        original_hash = images.hashlib.sha256

        def revoke_after_hash(*args, **kwargs):
            digest = original_hash(*args, **kwargs)
            f.auth.allowed = False
            return digest

        with patch.object(images.hashlib, 'sha256', side_effect=revoke_after_hash):
            response = self.download()
        self.assertEqual(response.status_code, 403)
        self.assertNotEqual(response.mimetype, 'image/png')
        self.assertEqual(len(f.provider.calls), 1)

    def test_oversized_retained_original_is_held_without_altering_the_reservation(self):
        f = self.flow
        with patch('business_growthrova_images.MAX_IMAGE_BYTES', len(f.provider.png)-1):
            response = self.download()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['code'], 'image_held')
        self.assertEqual(self.download().data, f.provider.png, 'A download hold never removes the original')
        with closing(sqlite3.connect(f.path)) as con:
            row = con.execute('SELECT result_json,reservation FROM growthrova_image_requests').fetchone()
        self.assertEqual(json.loads(row[0]), self.candidate)
        self.assertEqual(row[1], self.candidate['reservedMicrousd'])
        self.assertEqual(len(f.provider.calls), 1)

    def test_valid_held_original_remains_exact_and_download_does_not_change_owner_work(self):
        f = self.flow
        before = f.client.get(f.root+'/'+f.ident, headers=f.headers).json
        held = copy.deepcopy(self.candidate)
        held.update(state='held', issues=['Visual review needs changes; preserve the selected original.'])
        self.retain(held, f.provider.png)
        client = f.create().test_client()
        for _ in range(2):
            response = self.download(client)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'image/png')
            self.assertEqual(response.data, f.provider.png)
            self.assertEqual(response.headers['X-Growthrova-Asset-Origin'], 'generated')
        self.assertEqual(client.get(f.root+'/'+f.ident, headers=f.headers).json, before)
        self.assertEqual(client.get(f.url, headers=f.headers).json['candidates'][0], held)
        f.auth.owner = OTHER
        self.assertEqual(self.download(client).status_code, 403)
        f.auth.allowed = False
        self.assertEqual(self.download(client).status_code, 403)
        self.assertEqual(len(f.provider.calls), 1)


if __name__ == '__main__':
    unittest.main()
