"""Four source choices persist without media imports or provider calls."""
import unittest
from tests import test_business_growthrova_images as image_tests
from tests.test_business_growthrova_preview import OTHER


class ImageSourceTests(unittest.TestCase):
    def setUp(self):
        self.flow = image_tests.GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.url = self.flow.url + '/source-choice'

    def choose(self, route, version=0, revision=1, **extra):
        return self.flow.client.put(self.url, headers=self.flow.headers, json=dict(
            route=route, expectedSourceVersion=version, expectedRevision=revision, **extra))

    def test_four_sources_reopen_without_photos_and_do_not_change_campaign_or_spend(self):
        original = self.flow.client.get(self.flow.root+'/'+self.flow.ident, headers=self.flow.headers).json['document']
        for version, route in enumerate(('website', 'upload', 'mix', 'create')):
            result = self.choose(route, version)
            self.assertEqual(result.status_code, 200, result.json)
            expected = dict(route=route, version=version+1)
            self.assertEqual(result.json, expected)
            reopened = self.flow.create().test_client()
            self.assertEqual(reopened.get(self.flow.url, headers=self.flow.headers).json['sourceChoice'], expected)
        saved = self.flow.client.get(self.flow.root+'/'+self.flow.ident, headers=self.flow.headers).json
        self.assertEqual(saved['document'], original)
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(self.flow.provider.calls, [])

    def test_lost_ack_is_idempotent_but_stale_conflicting_choice_is_held(self):
        first = self.choose('upload')
        self.assertEqual(first.status_code, 200, first.json)
        self.assertEqual(self.choose('upload').json, first.json)
        self.assertEqual(self.choose('website').status_code, 409)
        self.assertEqual(self.choose('mix', 1).status_code, 200)
        self.assertEqual(self.choose('upload').status_code, 409)
        self.flow.save_document(self.flow.doc, 1, '6')
        self.assertEqual(self.choose('create', 2).status_code, 409)
        self.assertEqual(self.choose('create', 2, 2).status_code, 200)

    def test_scope_validation_and_source_route_do_not_authorise_imports(self):
        for route, extra in [('other', {}), ('create', {'rightsApproved':True})]:
            self.assertEqual(self.choose(route, **extra).status_code, 400)
        self.assertEqual(self.choose('create', True).status_code, 400)
        self.assertEqual(self.flow.client.put(self.url, json={}).status_code, 401)
        self.flow.auth.owner = OTHER
        self.assertEqual(self.choose('create').status_code, 403)
        self.flow.auth.allowed = False
        self.assertEqual(self.choose('create').status_code, 403)
        self.assertEqual(self.flow.provider.calls, [])

    def test_saved_website_choice_cannot_silently_generate_but_empty_photo_create_can(self):
        self.flow.configured()
        self.assertEqual(self.choose('website').status_code, 200)
        held = self.flow.generate()
        self.assertEqual(held.status_code, 409, held.json)
        self.assertEqual(held.json['code'], 'image_source_choice')
        self.assertEqual(self.flow.provider.calls, [])
        self.assertEqual(self.choose('create', 1).status_code, 200)
        candidate = self.flow.generate().json
        self.assertEqual(candidate['state'], 'proposed')
        self.assertEqual(candidate.get('sourceRoute'), 'create', 'Retain the source route at request time')
        self.assertEqual(candidate.get('sourceChoiceVersion'), 2)
        self.assertEqual(self.choose('website', 2).status_code, 200)
        self.assertEqual(self.flow.generate().json['sourceRoute'], 'create', 'Source changes preserve prior request replay')
        self.assertEqual(self.flow.client.get(self.flow.url+'/'+candidate['operationId']+'/original',
            headers=self.flow.headers).data, self.flow.provider.png)
        self.assertEqual(len(self.flow.provider.calls), 1)
