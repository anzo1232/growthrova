"""A requested alternative is a new illustration; it never replaces its parent."""
import copy
import base64
import io
import json
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
import requests
from PIL import Image
from tests import test_business_growthrova_images as fixtures
from tests.test_business_growthrova_preview import OTHER


class ImageAlternativeTests(unittest.TestCase):
    def setUp(self):
        self.flow = fixtures.GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.flow.configured()
        self.parent = self.flow.generate().json
        self.sibling = self.flow.generate(operationId='4'*32,
            visualBrief='An illustrative wheel and tools with quiet space for composed words.').json
        self.brief = 'A closer illustrative wheel detail on a warm neutral background; keep room for composed words.'

    def alternative(self, **changes):
        return self.flow.generate(operationId='5'*32, parentOperationId=self.parent['operationId'],
                                  visualBrief=self.brief, **changes)

    def test_alternative_reopens_with_parent_bytes_favourites_and_siblings_unchanged(self):
        f = self.flow
        before = f.client.get(f.root+'/'+f.ident, headers=f.headers).json
        choice = dict(selectedIds=[self.parent['operationId'], self.sibling['operationId']],
                      expectedRevision=1, expectedSelectionVersion=0)
        self.assertEqual(f.client.put(f.url+'/selection', headers=f.headers, json=choice).status_code, 200)
        original_bytes = f.provider.png
        # Different child pixels make an accidental parent overwrite observable.
        with Image.open(io.BytesIO(original_bytes)) as image:
            image.paste('#cc8844', (0, 0, 800, 1024))
            output = io.BytesIO()
            image.save(output, 'PNG')
        alternative_bytes = output.getvalue()
        f.provider.envelope = {'data': [{'b64_json': base64.b64encode(alternative_bytes).decode()}]}
        response = self.alternative()
        self.assertEqual(response.status_code, 200, response.json)
        child = response.json
        self.assertEqual(child['parentOperationId'], self.parent['operationId'])
        self.assertEqual(child['parentSha256'], self.parent['sha256'])
        self.assertEqual(child['alternativeType'], 'new_illustration')
        self.assertNotEqual(child['sha256'], self.parent['sha256'])
        self.assertEqual(child['independentReview'], 'pending')
        self.assertNotIn('observations', child)
        self.assertEqual(len(f.provider.calls), 3)
        self.assertNotIn('image', f.provider.calls[-1][1]['json'], 'No reference bytes are uploaded')
        reopened = f.create().test_client().get(f.url, headers=f.headers).json
        self.assertEqual(reopened['candidates'], [child, self.sibling, self.parent])
        self.assertEqual(reopened['selection']['selectedIds'], choice['selectedIds'])
        for candidate in (self.parent, self.sibling):
            raw = f.client.get(f.url+'/'+candidate['operationId']+'/original', headers=f.headers)
            self.assertEqual(raw.data, original_bytes)
        self.assertEqual(f.client.get(f.url+'/'+child['operationId']+'/original', headers=f.headers).data, alternative_bytes)
        self.assertEqual(f.client.get(f.root+'/'+f.ident, headers=f.headers).json, before)
        self.assertEqual(self.alternative().json, child)
        self.assertEqual(f.generate(operationId='7'*32, parentOperationId=self.parent['operationId'],
                                    visualBrief=self.brief).json, child)
        self.assertEqual(len(f.provider.calls), 3)

    def test_uncertain_alternative_is_recovered_without_retry_or_parent_change(self):
        self.flow.provider.failure = requests.Timeout('synthetic no acknowledgement')
        result = self.alternative()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'uncertain')
        self.assertEqual(self.alternative().json, result.json)
        self.assertEqual(len(self.flow.provider.calls), 3)
        with closing(sqlite3.connect(self.flow.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_image_requests').fetchone()[0], 3)
        self.assertEqual(self.flow.client.get(self.flow.url, headers=self.flow.headers).json['candidates'][-1], self.parent)

    def test_missing_parent_wrong_day_and_stale_brand_denied_before_reservation(self):
        f = self.flow
        for change in ({'parentOperationId':'9'*32}, {'parentOperationId':True},
                       {'day':2}, {'visualBrief':self.parent['visualBrief']}):
            data = {**f.data, 'operationId':'5'*32, 'parentOperationId':self.parent['operationId'],
                    'visualBrief':self.brief, **change}
            response = f.client.post(f.url, headers=f.headers, json=data)
            self.assertIn(response.status_code, (400,409), response.json)
        doc = copy.deepcopy(f.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='modern')
        f.save_document(doc, 1, '6')
        self.assertEqual(self.alternative(expectedRevision=2).status_code, 409)
        self.assertEqual(len(f.provider.calls), 2)
        with closing(sqlite3.connect(f.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_image_requests').fetchone()[0], 2)

    def test_foreign_and_unfunded_requests_do_not_use_alternative_as_bypass(self):
        f = self.flow
        f.auth.owner = OTHER
        self.assertEqual(self.alternative().status_code, 403)
        f.auth.owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        f.client = f.create().test_client()
        self.assertEqual(self.alternative().status_code, 503)
        self.assertEqual(len(f.provider.calls), 2)

    def test_changed_canvas_quality_or_model_is_held_before_quote_or_reservation(self):
        f = self.flow
        with closing(sqlite3.connect(f.path)) as con:
            before = con.execute('SELECT * FROM growthrova_image_requests').fetchall()
        for index, (setting, changes) in enumerate((('canvas', {'size':'1024x1536'}),
                                                   ('quality', {'quality':'high'}),
                                                   ('model', {})), start=5):
            config = replace(f.config, model='gemini-3-pro-image') if setting == 'model' else f.config
            client = f.create(image_config=config, image_http=f.provider).test_client()
            data = {**f.data, 'operationId':str(index)*32, 'parentOperationId':self.parent['operationId'],
                    'visualBrief':self.brief, **changes}
            for suffix in ('/estimate', ''):
                with self.subTest(setting=setting, endpoint=suffix or '/images'):
                    response = client.post(f.url+suffix, headers=f.headers, json=data)
                    self.assertEqual(response.status_code, 409, response.json)
                    self.assertEqual(response.json['code'], 'image_settings_changed')
        with closing(sqlite3.connect(f.path)) as con:
            self.assertEqual(con.execute('SELECT * FROM growthrova_image_requests').fetchall(), before)
        self.assertEqual(len(f.provider.calls), 2)
        self.assertEqual(f.client.get(f.url+'/'+self.parent['operationId']+'/original',
                                     headers=f.headers).data, f.provider.png)

    def test_recent_alternative_keeps_its_original_in_bounded_history(self):
        f = self.flow
        # An older unselected original must still be available for comparison.
        with closing(sqlite3.connect(f.path)) as con:
            for index in range(21):
                operation = format(index+100, '032x')
                candidate = {**self.sibling, 'operationId': operation}
                con.execute('INSERT INTO growthrova_image_requests VALUES(?,?,?,?,?,?)',
                    (f.ident, operation, operation, 0, json.dumps(candidate), f.provider.png))
            con.commit()
        response = self.alternative()
        self.assertEqual(response.status_code, 200, response.json)
        candidates = f.client.get(f.url, headers=f.headers).json['candidates']
        self.assertIn(self.parent, candidates)
        self.assertLessEqual(len(candidates), 80)
        self.assertEqual(len(f.provider.calls), 3)
