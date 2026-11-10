"""Owner observations bind retained pixels and relevant context, never artistic approval."""
import copy
import json
import sqlite3
from contextlib import closing
import unittest
from tests import test_business_growthrova_images as image_tests
from tests.test_business_growthrova_preview import OTHER


class GeneratedObservationTests(unittest.TestCase):
    def setUp(self):
        self.flow = image_tests.GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.flow.configured()
        self.candidate = self.flow.generate().json
        self.url = self.flow.url + '/' + self.candidate['operationId'] + '/observations'
        self.data = dict(reviewId='a'*32, expectedRevision=1, expectedReviewVersion=0,
                         sha256=self.candidate['sha256'],
                         checks=dict(visual='needs_changes', factual='not_reviewed',
                                     brand='not_reviewed', commercial='not_reviewed'),
                         note='The wheel shape is unsuitable for this bicycle campaign. Keep the original for comparison.')

    def submit(self, **changes):
        return self.flow.client.post(self.url, headers=self.flow.headers, json={**self.data, **changes})

    def status(self):
        return self.flow.client.get(self.flow.url, headers=self.flow.headers).json['candidates'][0]

    def test_observation_reopens_replays_and_holds_composition_without_losing_original(self):
        result = self.submit()
        self.assertEqual(result.status_code, 200, result.json)
        observed = result.json
        self.assertEqual(observed['reviewVersion'], 1)
        self.assertEqual(observed['observations'][0]['outcome'], 'needs_changes')
        self.assertEqual(observed['observations'][0]['reviewerRole'], 'owner_observation')
        self.assertTrue(observed['observations'][0]['current'])
        self.assertEqual(observed['independentReview'], 'pending')
        self.assertEqual(observed['state'], 'proposed', 'Preserve provider result; review hold is separate')
        self.assertEqual(self.submit().json, observed, 'Lost acknowledgement replay must not append twice')
        self.assertEqual(self.flow.generate().json, observed, 'Generation replay cannot hide saved review holds')
        reopened = self.flow.create().test_client()
        self.assertEqual(reopened.get(self.flow.url, headers=self.flow.headers).json['candidates'][0], observed)
        self.assertEqual(reopened.get(self.url.replace('/observations', '/original'), headers=self.flow.headers).data,
                         self.flow.provider.png)
        held = reopened.get(self.url.replace('/observations', '/static-preview?revision=1'), headers=self.flow.headers)
        self.assertEqual(held.status_code, 409, held.json)
        self.assertEqual(held.json['code'], 'image_observation_held')
        self.assertEqual(len(self.flow.provider.calls), 1)
        self.assertEqual(self.submit(note='Changed note using the same review identity.').status_code, 409)
        self.assertEqual(self.submit(reviewId='b'*32).status_code, 409, 'Concurrent stale review is held')

    def test_context_invalidation_is_scoped_and_prior_rejection_cannot_silently_disappear(self):
        self.assertEqual(self.submit().status_code, 200)
        doc = copy.deepcopy(self.flow.doc)
        doc['posts'][1]['copyDraft'] = 'A different saved post stays separate from this image review.'
        self.flow.save_document(doc, 1, '6')
        self.assertTrue(self.status()['observations'][0]['current'], 'Sibling edit does not stale selected review')
        doc['posts'][0]['graphicText'] = 'Plan your bicycle service'
        self.flow.save_document(doc, 2, '7')
        stale = self.status()
        self.assertFalse(stale['observations'][0]['current'])
        self.assertTrue(stale['compositionHeld'], 'A known rejection requires another explicit observation')
        updated = self.submit(reviewId='b'*32, expectedRevision=3, expectedReviewVersion=1,
            checks=dict(visual='checked', factual='checked', brand='not_reviewed', commercial='not_reviewed'),
            note='Compared the retained illustration against the updated brief; visual and factual checks only.')
        self.assertEqual(updated.status_code, 200, updated.json)
        self.assertEqual(len(updated.json['observations']), 2)
        self.assertEqual(updated.json['observations'][0]['reviewId'], 'a'*32)
        self.assertEqual(updated.json['observations'][1]['outcome'], 'observed')
        self.assertFalse(updated.json['compositionHeld'])
        self.assertEqual(updated.json['independentReview'], 'pending')
        self.assertFalse(updated.json['canPublish'])
        with closing(sqlite3.connect(self.flow.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_image_requests').fetchone()[0], 1)
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_unrelated_check_preserves_rejection_until_that_criterion_is_rechecked(self):
        doc = copy.deepcopy(self.flow.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='modern')
        self.flow.save_document(doc, 1, '6')
        self.data['expectedRevision'] = 2
        self.assertEqual(self.submit().status_code, 200)
        unrelated = dict(reviewId='b'*32, expectedReviewVersion=1,
            checks=dict(visual='not_reviewed', factual='not_reviewed',
                        brand='checked', commercial='not_reviewed'),
            note='Checked the palette only. The earlier wheel-shape issue is still unresolved.')
        result = self.submit(**unrelated)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertTrue(result.json['compositionHeld'], 'An unrelated brand check cannot clear a visual rejection')
        self.assertEqual(self.submit(**unrelated).json, result.json)
        client = self.flow.create().test_client()
        reopened = client.get(self.flow.url, headers=self.flow.headers).json['candidates'][0]
        self.assertTrue(reopened['compositionHeld'])
        self.assertEqual(len(reopened['observations']), 2)
        preview = self.url.replace('/observations', '/static-preview?revision=2')
        self.assertEqual(client.get(preview, headers=self.flow.headers).status_code, 409)
        resolved = self.submit(reviewId='c'*32, expectedReviewVersion=2,
            checks=dict(visual='checked', factual='not_reviewed', brand='not_reviewed', commercial='not_reviewed'),
            note='Reinspected the wheel shape against the intended illustrative direction.')
        self.assertEqual(resolved.status_code, 200, resolved.json)
        self.assertFalse(resolved.json['compositionHeld'])
        self.assertEqual(len(resolved.json['observations']), 3)
        self.assertEqual(client.get(preview, headers=self.flow.headers).status_code, 200)
        self.assertEqual(client.get(self.url.replace('/observations', '/original'),
                                    headers=self.flow.headers).data, self.flow.provider.png)
        self.assertEqual(resolved.json['independentReview'], 'pending')
        self.assertFalse(resolved.json['canPublish'])
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_review_validation_scope_hash_revision_and_uncertain_pixels(self):
        for change in ({'sha256':'0'*64}, {'expectedRevision':0}, {'expectedReviewVersion':True},
                       {'note':' '}, {'checks':{'visual':'checked'}},
                       {'checks':dict(visual='approved', factual='checked', brand='checked', commercial='checked')},
                       {'independentReview':'accepted'}):
            with self.subTest(change=change):
                self.assertIn(self.submit(**change).status_code, (400,409))
        self.assertEqual(self.flow.client.post(self.url, json=self.data).status_code, 401)
        self.flow.auth.owner = OTHER
        self.assertEqual(self.submit().status_code, 403)
        self.flow.auth.allowed = False
        self.assertEqual(self.submit().status_code, 403)
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_stored_bytes_must_match_review_hash_and_no_claim_can_clear_technical_hold(self):
        with closing(sqlite3.connect(self.flow.path)) as con:
            stored = {**self.candidate, 'state':'held'}
            con.execute('UPDATE growthrova_image_requests SET result_json=?', (json.dumps(stored),))
            con.commit()
        result = self.submit(checks=dict.fromkeys(('visual','factual','brand','commercial'),'checked'))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'held')
        self.assertTrue(result.json['compositionHeld'])
        with closing(sqlite3.connect(self.flow.path)) as con:
            con.execute('UPDATE growthrova_image_requests SET image_bytes=?', (b'corrupt retained bytes',))
            con.commit()
        self.assertEqual(self.submit(reviewId='b'*32, expectedReviewVersion=1).status_code, 409)
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_uncertain_request_without_pixels_cannot_receive_an_observation(self):
        with closing(sqlite3.connect(self.flow.path)) as con:
            con.execute('UPDATE growthrova_image_requests SET image_bytes=NULL')
            con.commit()
        result = self.submit()
        self.assertEqual(result.status_code, 409, result.json)
        self.assertEqual(result.json['code'], 'image_held')
        self.assertEqual(len(self.flow.provider.calls), 1)
