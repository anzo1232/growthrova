"""Selected generated originals remain portable, held and byte-identical."""
import hashlib
import io
import json
import sqlite3
import unittest
import zipfile
from contextlib import closing
from unittest.mock import patch

from tests import test_business_growthrova_images as fixtures
from tests.test_business_growthrova_preview import OTHER


class ImageDownloadTests(unittest.TestCase):
    def setUp(self):
        self.flow = fixtures.GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.flow.configured()
        self.parent = self.flow.generate().json
        self.child = self.flow.generate(operationId='4'*32,
            parentOperationId=self.parent['operationId'],
            visualBrief='An illustrative close wheel detail with warm colours and space for the headline.').json
        response = self.flow.client.put(self.flow.url+'/selection', headers=self.flow.headers,
            json=dict(selectedIds=[self.child['operationId']], expectedRevision=1, expectedSelectionVersion=0))
        self.assertEqual(response.status_code, 200, response.json)

    def download(self, query='revision=1&selectionVersion=1'):
        return self.flow.client.get(self.flow.url+'/selected-download?'+query, headers=self.flow.headers)

    def test_reopened_download_contains_exact_originals_lineage_copy_and_review_holds(self):
        f = self.flow
        observation = dict(reviewId='7'*32, expectedRevision=1, expectedReviewVersion=0,
            sha256=self.child['sha256'], checks=dict(visual='needs_changes', factual='not_reviewed',
            brand='not_reviewed', commercial='not_reviewed'), note='Synthetic background needs a more useful visual direction.')
        reviewed = f.client.post(f.url+'/'+self.child['operationId']+'/observations',
                                headers=f.headers, json=observation)
        self.assertEqual(reviewed.status_code, 200, reviewed.json)
        before = f.client.get(f.url, headers=f.headers).json
        saved = f.client.get(f.root+'/'+f.ident, headers=f.headers).json
        f.client = f.create().test_client()  # Disabled provider must not block download.
        response = self.download()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.mimetype, 'application/zip')
        self.assertIn('no-store', response.headers['Cache-Control'])
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['purpose'], 'unapproved_generated_background_review')
            self.assertEqual(manifest['document'], saved['document'])
            self.assertEqual(manifest['selection'], before['selection'])
            self.assertEqual(manifest['sourceChoice'], before['sourceChoice'])
            self.assertEqual(manifest['includedHistory'], 'selected_and_direct_parents_only')
            self.assertFalse(manifest['approved'])
            self.assertFalse(manifest['canPublish'])
            self.assertFalse(manifest['canSpend'])
            self.assertTrue(manifest['requiresIndependentQC'])
            self.assertEqual(len(manifest['candidates']), 2)
            child = next(c for c in manifest['candidates'] if c['operationId'] == self.child['operationId'])
            self.assertTrue(child['compositionHeld'])
            self.assertEqual(child['observations'][0]['outcome'], 'needs_changes')
            self.assertEqual(child['parentSha256'], self.parent['sha256'])
            for candidate in manifest['candidates']:
                pixels = archive.read(candidate['originalFile'])
                self.assertEqual(pixels, f.provider.png)
                self.assertEqual(hashlib.sha256(pixels).hexdigest(), candidate['sha256'])
            self.assertIn('REVIEW-NOT-APPROVED.txt', archive.namelist())
            self.assertNotIn('synthetic-image-key', response.data.decode('latin1'))
        self.assertEqual(self.download().data, response.data, 'Repeated downloads are deterministic and free')
        self.assertEqual(len(f.provider.calls), 2)

    def test_stale_empty_foreign_and_revoked_requests_are_denied(self):
        f = self.flow
        for query, code in [('revision=2&selectionVersion=1', 409),
                            ('revision=1&selectionVersion=0', 409), ('revision=1', 400)]:
            self.assertEqual(self.download(query).status_code, code)
        f.auth.owner = OTHER
        self.assertEqual(self.download().status_code, 403)
        f.auth.owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        f.auth.status = 401
        self.assertIn(self.download().status_code, (401, 403))
        f.auth.status = 200
        f.client.put(f.url+'/selection', headers=f.headers,
            json=dict(selectedIds=[], expectedRevision=1, expectedSelectionVersion=1))
        self.assertEqual(self.download('revision=1&selectionVersion=2').status_code, 409)
        self.assertEqual(len(f.provider.calls), 2)

    def test_corrupt_missing_and_oversized_originals_never_produce_partial_archives(self):
        f = self.flow
        with patch('business_growthrova_images.IMAGE_REVIEW_DOWNLOAD_LIMIT', 10):
            self.assertEqual(self.download().status_code, 409)
        with closing(sqlite3.connect(f.path)) as con:
            con.execute('UPDATE growthrova_image_requests SET image_bytes=? WHERE operation_id=?',
                        (b'corrupt PNG', self.parent['operationId']))
            con.commit()
        response = self.download()
        self.assertEqual(response.status_code, 409)
        self.assertNotEqual(response.mimetype, 'application/zip')
        with closing(sqlite3.connect(f.path)) as con:
            con.execute('DELETE FROM growthrova_image_requests WHERE operation_id=?', (self.parent['operationId'],))
            con.commit()
        self.assertEqual(self.download().status_code, 409)
        self.assertEqual(len(f.provider.calls), 2)
