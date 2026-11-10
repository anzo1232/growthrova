"""Final artwork observations bind composed bytes, never independent approval."""
import copy
import base64
import io
import unittest
from PIL import Image
from tests import test_business_growthrova_images as fixtures
from tests.test_business_growthrova_preview import OTHER


class StaticObservationTests(unittest.TestCase):
    def setUp(self):
        self.flow = fixtures.GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.flow.configured()
        self.image = self.flow.generate().json
        self.doc = copy.deepcopy(self.flow.doc)
        self.doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                                   secondary_color='#FFFFFF', font_style='modern')
        self.flow.save_document(self.doc, 1, '6')
        self.root = self.flow.url + '/' + self.image['operationId']
        self.preview = self.compose().json
        self.data = dict(reviewId='a'*32, expectedRevision=2, expectedReviewVersion=0,
                         sha256=self.preview['manifest']['previewSha256'],
                         checks=dict(visual='checked', factual='checked', brand='not_reviewed',
                                     commercial='not_reviewed', legibility='needs_changes',
                                     crop='checked', cta='not_reviewed'),
                         note='Inspected the composed words on mobile. Headline needs a clearer hierarchy.')

    def compose(self, revision=2, client=None):
        return (client or self.flow.client).get(self.root+'/static-preview?revision='+str(revision), headers=self.flow.headers)

    def submit(self, **changes):
        return self.flow.client.post(self.root+'/static-observations', headers=self.flow.headers,
                                     json={**self.data, **changes})

    def test_square_export_reuses_background_and_binds_observations_to_exact_frame(self):
        f = self.flow
        before = f.client.get(f.root+'/'+f.ident, headers=f.headers).json
        square = f.client.get(self.root+'/static-preview?revision=2&frame=square', headers=f.headers)
        self.assertEqual(square.status_code, 200, square.json)
        manifest = square.json['manifest']
        self.assertEqual((manifest['width'], manifest['height']), (1080, 1080))
        with Image.open(io.BytesIO(base64.b64decode(square.json['previewBase64']))) as pixels:
            self.assertEqual(pixels.size, (1080, 1080))
        self.assertEqual(manifest['post'], self.preview['manifest']['post'])
        self.assertEqual(manifest['backgroundSha256'], self.image['sha256'])
        self.assertTrue(all(b['bottom'] <= b['limit'] <= 1080 for b in manifest['layout']['textBlocks']))
        checked = dict.fromkeys(self.data['checks'], 'checked')
        response = self.submit(exportFrame='square', sha256=manifest['previewSha256'], checks=checked)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertTrue(response.json['observations'][0]['current'])
        self.assertFalse(self.compose().json['artworkReview']['observations'][0]['current'])
        reopened = f.create().test_client().get(self.root+'/static-preview?revision=2&frame=square', headers=f.headers)
        self.assertEqual(reopened.json['previewBase64'], square.json['previewBase64'])
        self.assertTrue(reopened.json['artworkReview']['observations'][0]['current'])
        self.assertEqual(f.client.get(f.root+'/'+f.ident, headers=f.headers).json, before)
        self.assertEqual(len(f.provider.calls), 1, 'Free layout exports cannot invoke image generation')

    def test_story_export_reopens_exact_pixels_and_has_its_own_review_context(self):
        f = self.flow
        before = f.client.get(f.root+'/'+f.ident, headers=f.headers).json
        endpoint = self.root+'/static-preview?revision=2&frame=story'
        response = f.client.get(endpoint, headers=f.headers)
        self.assertEqual(response.status_code, 200, response.json)
        manifest = response.json['manifest']
        self.assertEqual((manifest['width'], manifest['height']), (1080, 1920))
        self.assertEqual(manifest['post'], self.preview['manifest']['post'])
        self.assertEqual(manifest['backgroundSha256'], self.image['sha256'])
        with Image.open(io.BytesIO(base64.b64decode(response.json['previewBase64']))) as pixels:
            self.assertEqual(pixels.size, (1080, 1920))
            self.assertEqual(pixels.crop((0, 0, 1080, 250)).getextrema(), ((18,18),(52,52),(86,86)))
            self.assertEqual(pixels.crop((0, 1580, 1080, 1920)).getextrema(), ((18,18),(52,52),(86,86)))
        checked = dict.fromkeys(self.data['checks'], 'checked')
        result = self.submit(exportFrame='story', sha256=manifest['previewSha256'], checks=checked)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertTrue(result.json['observations'][0]['current'])
        self.assertEqual(self.submit(exportFrame='portrait', sha256=manifest['previewSha256']).status_code, 409)
        reopened = f.create().test_client().get(endpoint, headers=f.headers)
        self.assertEqual(reopened.json['previewBase64'], response.json['previewBase64'])
        self.assertTrue(reopened.json['artworkReview']['observations'][0]['current'])
        self.assertFalse(self.compose().json['artworkReview']['observations'][0]['current'])
        self.assertEqual(f.client.get(f.root+'/'+f.ident, headers=f.headers).json, before)
        self.assertEqual(len(f.provider.calls), 1, 'Story composition and review must not generate images')

    def test_invalid_export_frame_values_fail_as_actionable_validation(self):
        for value in ([], {}, 1, None):
            with self.subTest(value=value):
                self.assertEqual(self.submit(exportFrame=value).status_code, 400)

    def test_objective_change_requires_fresh_artwork_review_even_without_a_destination(self):
        self.assertFalse(self.doc['posts'][0].get('destinationUrl'))
        self.assertEqual(self.submit().status_code, 200)
        self.doc['posts'][0]['objective'] = 'Build awareness'
        self.flow.save_document(self.doc, 2, '7')
        composed = self.compose(revision=3)
        self.assertEqual(composed.status_code, 200, composed.json)
        self.assertEqual(composed.json['previewBase64'], self.preview['previewBase64'],
                         'A changed campaign purpose does not redraw the image')
        self.assertFalse(composed.json['artworkReview']['observations'][0]['current'],
                         'Identical pixels do not imply the same commercial/CTA review context')
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_unsupported_export_frame_is_actionable_and_cannot_review_wrong_pixels(self):
        response = self.flow.client.get(self.root+'/static-preview?revision=2&frame=landscape', headers=self.flow.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.submit(exportFrame='square').status_code, 409)
        self.assertEqual(self.submit(exportFrame='landscape').status_code, 400)
        self.assertEqual(self.compose().json['previewBase64'], self.preview['previewBase64'])
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_exact_artwork_review_replays_and_reopens_without_background_hold_or_provider_call(self):
        response = self.submit()
        self.assertEqual(response.status_code, 200, response.json)
        review = response.json
        self.assertEqual(review['version'], 1)
        self.assertTrue(review['needsChanges'])
        self.assertEqual(review['independentReview'], 'pending')
        self.assertFalse(review['approved'])
        self.assertTrue(review['observations'][0]['current'])
        self.assertEqual(review['observations'][0]['reviewerRole'], 'owner_observation')
        self.assertEqual(self.submit().json, review)
        reopened = self.flow.create().test_client()
        composed = self.compose(client=reopened)
        self.assertEqual(composed.status_code, 200, composed.json)
        self.assertEqual(composed.json['artworkReview'], review)
        self.assertEqual(composed.json['previewBase64'], self.preview['previewBase64'])
        self.assertFalse(composed.json['manifest']['approved'])
        candidate = reopened.get(self.flow.url, headers=self.flow.headers).json['candidates'][0]
        self.assertNotIn('compositionHeld', candidate, 'Artwork rejection must not hide original or prevent repair composition')
        self.assertEqual(len(self.flow.provider.calls), 1)
        self.assertEqual(self.submit(note='Changed payload under the same review identity.').status_code, 409)
        self.assertEqual(self.submit(reviewId='b'*32).status_code, 409)

    def test_only_relevant_changes_invalidate_review_and_old_pixels_cannot_be_reviewed_as_current(self):
        self.assertEqual(self.submit().status_code, 200)
        self.doc['posts'][1]['copyDraft'] = 'A separate bicycle post with a separate customer action.'
        self.flow.save_document(self.doc, 2, '7')
        sibling = self.compose(3).json
        self.assertTrue(sibling['artworkReview']['observations'][0]['current'])
        self.doc['posts'][0]['graphicText'] = 'Make time for bicycle servicing'
        self.flow.save_document(self.doc, 3, '8')
        changed = self.compose(4).json
        self.assertNotEqual(changed['manifest']['previewSha256'], self.data['sha256'])
        self.assertFalse(changed['artworkReview']['observations'][0]['current'])
        self.assertTrue(changed['artworkReview']['needsChanges'])
        self.assertEqual(self.submit(expectedRevision=4, expectedReviewVersion=1, reviewId='b'*32).status_code, 409)
        checks = dict.fromkeys(self.data['checks'], 'checked')
        reviewed = self.submit(expectedRevision=4, expectedReviewVersion=1, reviewId='b'*32,
                               sha256=changed['manifest']['previewSha256'], checks=checks)
        self.assertEqual(reviewed.status_code, 200, reviewed.json)
        self.assertEqual(len(reviewed.json['observations']), 2)
        self.assertFalse(reviewed.json['needsChanges'])
        self.assertEqual(reviewed.json['independentReview'], 'pending')
        self.assertFalse(reviewed.json['approved'])
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_scope_validation_and_no_claim_can_approve_artwork(self):
        for changes in ({'sha256':'0'*64}, {'expectedRevision':1}, {'expectedReviewVersion':True},
                        {'checks':dict.fromkeys(self.data['checks'], 'approved')},
                        {'checks':{'visual':'checked'}}, {'approved':True}, {'note':' '}):
            with self.subTest(changes=changes):
                self.assertIn(self.submit(**changes).status_code, (400,409))
        self.assertEqual(self.flow.client.post(self.root+'/static-observations', json=self.data).status_code, 401)
        self.flow.auth.owner = OTHER
        self.assertEqual(self.submit().status_code, 403)
        self.flow.auth.allowed = False
        self.assertEqual(self.submit().status_code, 403)
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_unrelated_check_cannot_silently_clear_a_known_legibility_problem(self):
        self.assertEqual(self.submit().status_code, 200)
        checks = dict.fromkeys(self.data['checks'], 'not_reviewed')
        checks['visual'] = 'checked'
        response = self.submit(reviewId='b'*32, expectedReviewVersion=1, checks=checks,
                               note='Checked the illustration only; the words still need attention.')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertTrue(response.json['needsChanges'], 'Uninspected text cannot clear a known legibility rejection')
        checks['legibility'] = 'checked'
        resolved = self.submit(reviewId='c'*32, expectedReviewVersion=2, checks=checks,
                               note='Explicitly inspected the text again at phone size after comparison.')
        self.assertEqual(resolved.status_code, 200, resolved.json)
        self.assertFalse(resolved.json['needsChanges'])
        self.assertFalse(resolved.json['approved'])

    def test_destination_survives_reopen_and_stales_review_without_changing_pixels(self):
        self.assertEqual(self.submit().status_code, 200)
        before = self.flow.client.get(self.flow.root+'/'+self.flow.ident, headers=self.flow.headers).json['document']
        self.doc['posts'][0]['destinationUrl'] = 'https://example.org/book-a-service'
        self.flow.save_document(self.doc, 2, '9')
        client = self.flow.create().test_client()
        reopened = client.get(self.flow.root+'/'+self.flow.ident, headers=self.flow.headers).json
        self.assertEqual(reopened['document']['posts'][0].get('destinationUrl'),
                         self.doc['posts'][0]['destinationUrl'])
        composed = self.compose(3, client).json
        self.assertEqual(composed['manifest']['post']['destinationUrl'], self.doc['posts'][0]['destinationUrl'])
        self.assertEqual(composed['previewBase64'], self.preview['previewBase64'])
        self.assertFalse(composed['artworkReview']['observations'][0]['current'])
        self.assertTrue(composed['artworkReview']['needsChanges'])
        self.assertEqual(reopened['document']['posts'][1:], before['posts'][1:])
        self.assertEqual(reopened['document']['posts'][0]['copyDraft'], before['posts'][0]['copyDraft'])
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_invalid_destinations_are_rejected_without_losing_saved_work(self):
        for url in ('javascript:alert(1)', 'http://example.org/book', 'https://user:secret@example.org/',
                    'https://example.org/\nbook', 'https://example.org:invalid/', 'https://example.org/\\book'):
            with self.subTest(url=url):
                doc = copy.deepcopy(self.doc)
                doc['posts'][0]['destinationUrl'] = url
                response = self.flow.client.post(self.flow.root, headers=self.flow.headers, json=dict(
                    id=self.flow.ident, mutationId='f'*32, expectedRevision=2, document=doc))
                self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(self.compose().json['previewBase64'], self.preview['previewBase64'])

    def test_destination_change_cannot_keep_a_stale_copy_review_from_api(self):
        from business_marketing_drafts import normalise_document
        previous = normalise_document(self.doc)
        previous['posts'][0]['status'] = 'copy_reviewed'
        changed = copy.deepcopy(previous)
        changed['posts'][0]['destinationUrl'] = 'https://example.org/book'
        self.assertEqual(normalise_document(changed, previous)['posts'][0]['status'], 'draft')
