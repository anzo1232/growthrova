"""Image favourites preserve pixels and holds; selection is never approval."""
import copy
import json
import sqlite3
import unittest
from contextlib import closing
from tests import test_business_growthrova_images as fixtures
from tests.test_business_growthrova_preview import OTHER


class ImageSelectionTests(unittest.TestCase):
    def setUp(self):
        self.flow = fixtures.GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.flow.configured()
        self.first = self.flow.generate().json
        self.second = self.flow.generate(operationId='4'*32,
            visualBrief='Illustrative bicycle wheel detail with generous space beside the subject.').json
        self.url = self.flow.url+'/selection'

    def select(self, ids, version=0, revision=1):
        return self.flow.client.put(self.url, headers=self.flow.headers, json=dict(
            selectedIds=ids, expectedSelectionVersion=version, expectedRevision=revision))

    def test_multiple_favourites_reopen_and_clear_without_mutation_or_inference(self):
        ids = [self.first['operationId'], self.second['operationId']]
        before = self.flow.client.get(self.flow.root+'/'+self.flow.ident, headers=self.flow.headers).json
        saved = self.select(ids)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json, dict(selectedIds=ids, version=1))
        reopened = self.flow.create().test_client().get(self.flow.url, headers=self.flow.headers).json
        self.assertEqual(reopened['selection'], saved.json)
        self.assertEqual({c['operationId'] for c in reopened['candidates']}, set(ids))
        self.assertEqual(self.select(ids).json, saved.json, 'Lost acknowledgement must replay')
        self.assertEqual(self.select(ids[::-1]).status_code, 409)
        self.assertEqual(self.select([], 1).json, dict(selectedIds=[], version=2))
        self.assertEqual(self.flow.client.get(self.flow.root+'/'+self.flow.ident, headers=self.flow.headers).json, before)
        self.assertEqual(len(self.flow.provider.calls), 2)
        self.assertEqual(self.flow.client.get(self.flow.url+'/'+ids[0]+'/original', headers=self.flow.headers).data, self.flow.provider.png)

    def test_unknown_uncertain_duplicates_and_stale_scope_are_denied(self):
        for ids in (['f'*32], [self.first['operationId']]*2, 'not-a-list', [False], ['a'*32]*21):
            self.assertIn(self.select(ids).status_code, (400, 409))
        self.flow.provider.failure = TimeoutError('Synthetic ambiguous provider failure')
        uncertain = self.flow.generate(operationId='5'*32,
            visualBrief='Illustrative bicycle silhouette in a calm editorial composition.').json
        self.assertEqual(uncertain['state'], 'uncertain')
        self.assertEqual(self.select([uncertain['operationId']]).status_code, 409)
        self.flow.save_document(self.flow.doc, 1, '6')
        self.assertEqual(self.select([self.first['operationId']]).status_code, 409)
        self.flow.auth.owner = OTHER
        self.assertEqual(self.select([], revision=2).status_code, 403)
        self.flow.auth.allowed = False
        self.assertEqual(self.select([], revision=2).status_code, 403)
        self.assertEqual(self.flow.client.put(self.url, json={}).status_code, 401)

    def test_selected_older_candidate_remains_visible_and_held_pixels_stay_held(self):
        # Use retained real fixture bytes, rather than twenty extra provider calls.
        with closing(sqlite3.connect(self.flow.path)) as con:
            held = copy.deepcopy(self.first)
            held.update(state='held', issues=['Synthetic review hold'])
            con.execute('UPDATE growthrova_image_requests SET result_json=? WHERE operation_id=?',
                        (json.dumps(held), held['operationId']))
            for index in range(21):
                candidate = {**self.second, 'operationId':format(index+100, '032x')}
                con.execute('INSERT INTO growthrova_image_requests VALUES(?,?,?,?,?,?)',
                    (self.flow.ident, candidate['operationId'], 'fixture-'+str(index), 0,
                     json.dumps(candidate), self.flow.provider.png))
            con.commit()
        result = self.select([held['operationId']])
        self.assertEqual(result.status_code, 200, result.json)
        status = self.flow.client.get(self.flow.url, headers=self.flow.headers).json
        selected = next(c for c in status['candidates'] if c['operationId'] == held['operationId'])
        self.assertEqual(selected['state'], 'held')
        self.assertFalse(selected['canPublish'])
        self.assertEqual(selected['sha256'], held['sha256'])
        self.assertEqual(len(self.flow.provider.calls), 2)
