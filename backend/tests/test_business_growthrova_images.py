"""Non-billable image HTTP contracts; synthetic pixels are never model quality."""
import base64
from contextlib import closing
import copy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import requests
from PIL import Image

from business_growthrova_preview import create_growthrova_preview
from tests.test_business_growthrova_preview import Transport, PROJECT, ORG, OTHER
from tests.test_business_marketing_drafts import document


class Provider:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.on_call = None
        output = io.BytesIO()
        fixture = Image.new('RGB', (1024, 1024), '#225577')
        from PIL import ImageDraw
        draw = ImageDraw.Draw(fixture)
        for stripe in range(24):
            draw.rectangle((1024*7//8, stripe*1024//24, 1024-1, (stripe+1)*1024//24-1),
                           fill='white' if stripe%2 else 'black')
        fixture.save(output, 'PNG')
        self.png = output.getvalue()
        self.envelope = {'data': [{'b64_json': base64.b64encode(self.png).decode()}]}

    def post(self, url, **options):
        self.calls.append((url, options))
        if self.on_call:
            self.on_call()
        if self.failure:
            raise self.failure
        return self

    status_code = 200
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size): yield json.dumps(self.envelope).encode()


class GrowthrovaImageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = str(Path(temp.name) / 'preview.db')
        self.auth = Transport()
        self.provider = Provider()
        self.headers = {'Authorization': 'Bearer synthetic-valid'}
        self.root = f'/api/growthrova/organisations/{ORG}/marketing-documents'
        self.ident = '1'*32
        self.url = self.root + '/' + self.ident + '/images'
        self.doc = document()
        self.doc['business'] = 'Synthetic workshop'
        self.doc['observedFacts'] = ['Bicycle servicing is available at the workshop.']
        self.doc['posts'][0].update(copyDraft='Bring your bicycle to our workshop for servicing.',
                                   graphicText='Bicycle servicing', callToAction='Contact the workshop')
        strategy = dict(audience='Local bicycle owners', offer='Bicycle servicing', positioning='',
                        callToAction='Contact the workshop', constraints='Synthetic QA only; no offers or results.',
                        factDecisions=[dict(index=0, observation=self.doc['observedFacts'][0],
                                            decision='confirmed', statement='')])
        strategy['confirmedContext'] = {**{k: self.doc[k] for k in ('business','goal','sourceUrl','observedFacts')}, **strategy}
        self.doc['ownerStrategy'] = strategy
        self.app = self.create()
        self.client = self.app.test_client()
        saved = self.client.post(self.root, headers=self.headers, json={
            'id': self.ident, 'mutationId': '2'*32, 'expectedRevision': 0, 'document': self.doc})
        self.assertEqual(saved.status_code, 200, saved.json)
        self.data = dict(operationId='3'*32, expectedRevision=1, day=1,
                        visualBrief='Abstract wheel arcs with a calm blue background and room for the headline.',
                        size='1024x1024', quality='low')

    def create(self, **kwargs):
        return create_growthrova_preview(database_path=self.path, project_url=PROJECT, auth_url=PROJECT,
            anon_key='sb_publishable_synthetic', http=self.auth, **kwargs)

    def configured(self):
        from business_growthrova_images import ImageConfig
        # Hypothetical authority exists ONLY inside this test. Runtime authority remains zero.
        for name, limit in (('AUTHORISED_IMAGE_LIFETIME_MICROUSD', 1000000),
                            ('AUTHORISED_IMAGE_CALL_MICROUSD', 200000)):
            authority = patch('business_growthrova_images.' + name, limit)
            authority.start()
            self.addCleanup(authority.stop)
        self.config = ImageConfig(enabled=True, key='synthetic-image-key-not-real', model='gpt-image-1.5',
            budget_microusd=200000, call_cap_microusd=100000,
            input_rate_microusd_per_million=5000000, output_cost_microusd=20000)
        self.app = self.create(image_config=self.config, image_http=self.provider)
        self.client = self.app.test_client()

    def generate(self, **changes):
        return self.client.post(self.url, headers=self.headers, json={**self.data, **changes})

    def save_document(self, doc, revision, mutation):
        result = self.client.post(self.root, headers=self.headers, json={
            'id': self.ident, 'mutationId': mutation * 32,
            'expectedRevision': revision, 'document': doc})
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def test_generated_static_composition_uses_saved_brand_and_editable_words_without_inference(self):
        self.configured()
        candidate = self.generate().json
        doc = copy.deepcopy(self.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='modern')
        doc['posts'][0]['copyDraft'] = 'Bring your bicycle to our workshop for servicing. ' * 30
        saved = self.save_document(doc, 1, '6')
        url = self.url + '/' + candidate['operationId'] + '/static-preview'
        result = self.client.get(url + '?revision=2', headers=self.headers)
        self.assertEqual(result.status_code, 200, result.json)
        manifest = result.json['manifest']
        raw = base64.b64decode(result.json['previewBase64'])
        import hashlib
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest['previewSha256'])
        self.assertEqual(manifest['origin'], 'generated')
        self.assertEqual(manifest['post'], saved['document']['posts'][0])
        self.assertEqual(manifest['layout']['copy'], 'Bicycle servicing')
        self.assertEqual(manifest['brandKit'], doc['brandKit'])
        self.assertEqual(manifest['backgroundSha256'], candidate['sha256'])
        self.assertFalse(manifest['approved'])
        self.assertFalse(manifest['canPublish'])
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.size, (1080, 1350))
            self.assertEqual(image.getpixel((540, 400)), (34, 85, 119))
        reopened = self.create().test_client()
        self.assertEqual(reopened.get(url+'?revision=2', headers=self.headers).json, result.json)
        doc['posts'][0]['graphicText'] = 'Make time for bicycle servicing.'
        doc['posts'][0]['callToAction'] = 'Contact our workshop team'
        self.save_document(doc, 2, '7')
        edited = self.client.get(url+'?revision=3', headers=self.headers)
        self.assertEqual(edited.status_code, 200, edited.json)
        self.assertEqual(edited.json['manifest']['layout']['copy'], doc['posts'][0]['graphicText'])
        self.assertNotEqual(edited.json['manifest']['previewSha256'], manifest['previewSha256'])
        self.assertEqual(edited.json['manifest']['backgroundSha256'], candidate['sha256'])
        self.assertEqual(self.client.get(url+'?revision=2', headers=self.headers).status_code, 409)
        self.assertEqual(len(self.provider.calls), 1)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_image_requests').fetchone()[0], 1)

    def test_generated_composition_holds_missing_brand_changed_evidence_and_foreign_scope(self):
        self.configured()
        candidate = self.generate().json
        url = self.url+'/'+candidate['operationId']+'/static-preview'
        result = self.client.get(url+'?revision=1', headers=self.headers)
        self.assertEqual(result.status_code, 400, result.json)
        self.assertIn('Brand', result.json['error'])
        doc = copy.deepcopy(self.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='modern')
        doc['ownerStrategy']['constraints'] = 'New reviewed source context.'
        doc['ownerStrategy']['confirmedContext']['constraints'] = doc['ownerStrategy']['constraints']
        self.save_document(doc, 1, '6')
        self.assertEqual(self.client.get(url+'?revision=2', headers=self.headers).status_code, 409)
        self.auth.owner = OTHER
        self.assertEqual(self.client.get(url+'?revision=2', headers=self.headers).status_code, 403)
        self.assertEqual(len(self.provider.calls), 1)

    def test_generated_composition_respects_saved_logo_observation_and_withdrawal(self):
        self.configured()
        candidate = self.generate().json
        doc = copy.deepcopy(self.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='modern')
        self.save_document(doc, 1, '6')
        media = self.root+'/'+self.ident+'/media'
        logo_bytes = io.BytesIO()
        Image.new('RGBA', (200, 100), (250, 60, 20, 255)).save(logo_bytes, 'PNG')
        imported = self.client.post(media, headers=self.headers, data={
            'file': (io.BytesIO(logo_bytes.getvalue()), 'synthetic-logo.png', 'image/png'),
            'rightsStatement': 'Authored synthetic QA logo with marketing permission.',
            'consentStatus': 'owner_asserted'}, content_type='multipart/form-data')
        self.assertEqual(imported.status_code, 201, imported.json)
        logo = imported.json['asset']['assetId']
        selected = self.client.put(media+'/selection', headers=self.headers, json=dict(
            revision=2, selectionVersion=0, assetIds=[logo],
            postAssignments=[dict(day=1, assetIds=[logo], staticLogoAssetId=logo)]))
        self.assertEqual(selected.status_code, 200, selected.json)
        url = self.url+'/'+candidate['operationId']+'/static-preview?revision=2'
        self.assertEqual(self.client.get(url, headers=self.headers).status_code, 400)
        preview = self.client.get(media+'/posts/1/'+logo+'/original-review?revision=2&selectionVersion=1', headers=self.headers)
        self.assertEqual(preview.status_code, 200, preview.json)
        noted = self.client.put(media+'/posts/1/'+logo+'/review-note', headers=self.headers, json=dict(
            revision=2, selectionVersion=1, reviewVersion=0, receipt=preview.json['reviewReceipt'],
            outcome='usable_candidate', note='Synthetic whole logo inspected for exact static use.'))
        self.assertEqual(noted.status_code, 200, noted.json)
        result = self.client.get(url, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.json)
        manifest = result.json['manifest']
        self.assertTrue(manifest['logoIncluded'])
        self.assertEqual(manifest['logoCandidate']['assetId'], logo)
        with Image.open(io.BytesIO(base64.b64decode(result.json['previewBase64']))) as image:
            x,y,w,h = manifest['layout']['logoBox']
            self.assertEqual(image.getpixel((x+w//2,y+h//2)), (250,60,20))
        withdrawn = self.client.post(media+'/'+logo+'/withdraw-permission', headers=self.headers,
            json={'reason': 'Withdraw synthetic logo permission.'})
        self.assertEqual(withdrawn.status_code, 200, withdrawn.json)
        held = self.client.get(url, headers=self.headers)
        self.assertIn(held.status_code, (400,409))
        self.assertNotIn('previewBase64', held.json)
        self.assertEqual(len(self.provider.calls), 1)

    def test_unconfigured_capability_is_clear_and_preserves_saved_work(self):
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        status = self.client.get(self.url, headers=self.headers)
        self.assertEqual(status.status_code, 200, status.json)
        self.assertFalse(status.json['available'])
        self.assertIn('separate image spending', status.json['message'])
        result = self.generate()
        self.assertEqual(result.status_code, 503, result.json)
        self.assertEqual(result.json['code'], 'image_generation_unavailable')
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)
        self.assertEqual(self.provider.calls, [])

    def test_environment_cannot_borrow_text_keys_or_exceed_owner_image_authority(self):
        from business_growthrova_images import ImageConfig, AUTHORISED_IMAGE_LIFETIME_MICROUSD
        ambient = {'OPENAI_API_KEY':'synthetic-ambient-key', 'GROWTHROVA_WRITER_API_KEY':'synthetic-text-key'}
        self.assertEqual(ImageConfig.from_environment(ambient).key, '')
        settings = {**ambient, 'GROWTHROVA_IMAGE_ENABLED':'true',
            'GROWTHROVA_IMAGE_API_KEY':'synthetic-image-key-not-real', 'GROWTHROVA_IMAGE_MODEL':'gpt-image-1.5',
            'GROWTHROVA_IMAGE_BUDGET_MICROUSD':str(AUTHORISED_IMAGE_LIFETIME_MICROUSD + 1), 'GROWTHROVA_IMAGE_CALL_CAP_MICROUSD':'200000',
            'GROWTHROVA_IMAGE_INPUT_RATE_MICROUSD_PER_MILLION':'5000000',
            'GROWTHROVA_IMAGE_OUTPUT_COST_MICROUSD':'20000'}
        config = ImageConfig.from_environment(settings)
        self.assertFalse(config.available(), 'Environment settings cannot exceed owner image-spend authority')
        self.assertNotIn(config.key, repr(config))
        self.client = self.create(image_config=config, image_http=self.provider).test_client()
        self.assertEqual(self.generate().status_code, 503)
        self.assertEqual(self.provider.calls, [])

    def test_generation_reserves_before_http_replays_reopens_and_keeps_generated_separate(self):
        self.configured()
        def check_reservation():
            with closing(sqlite3.connect(self.path)) as con:
                row = con.execute('SELECT reservation,result_json FROM growthrova_image_requests').fetchone()
                self.assertGreater(row[0], 0)
                self.assertEqual(json.loads(row[1])['state'], 'pending')
                self.assertGreater(json.loads(row[1])['outcomeCheckAfter'], json.loads(row[1])['requestedAt'])
        self.provider.on_call = check_reservation
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        result = self.generate()
        self.assertEqual(result.status_code, 200, result.json)
        candidate = result.json
        self.assertEqual(candidate['state'], 'proposed')
        self.assertEqual(candidate['origin'], 'generated')
        self.assertEqual(candidate['independentReview'], 'pending')
        self.assertEqual(candidate['sourceContext']['post'], before['document']['posts'][0])
        self.assertEqual(candidate['sourceContext']['brandKit'], before['document'].get('brandKit'))
        self.assertFalse(candidate['canPublish'])
        self.assertFalse(candidate['canSpend'])
        self.assertEqual(self.generate().json, candidate)
        self.assertEqual(self.generate(operationId='4'*32).json, candidate)
        replay = self.create(image_config=self.config, image_http=self.provider).test_client()
        self.assertEqual(replay.get(self.url, headers=self.headers).json['candidates'], [candidate])
        downloaded = replay.get(self.url+'/'+candidate['operationId']+'/original', headers=self.headers)
        self.assertEqual(downloaded.data, self.provider.png)
        self.assertEqual(downloaded.headers['X-Growthrova-Asset-Origin'], 'generated')
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)
        library = self.client.get(self.root+'/'+self.ident+'/media', headers=self.headers).json
        self.assertEqual(library['assets'], [])
        self.assertEqual(len(self.provider.calls), 1)
        url, options = self.provider.calls[0]
        self.assertEqual(url, 'https://api.openai.com/v1/images/generations')
        self.assertFalse(options['allow_redirects'])
        self.assertTrue(options['stream'])
        self.assertEqual(options['json']['n'], 1)
        self.assertEqual(options['json']['output_format'], 'png')
        self.assertNotIn('image', options['json'])
        self.assertNotIn(self.config.key, json.dumps(candidate))

    def test_uncertain_request_cannot_be_retried_or_double_charged(self):
        self.configured()
        self.provider.failure = requests.Timeout('synthetic timeout')
        result = self.generate()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'uncertain')
        self.assertEqual(self.generate(operationId='4'*32).json, result.json)
        self.assertEqual(self.generate().json, result.json)
        self.assertEqual(self.generate(visualBrief='Different visual direction with a plain background.').status_code, 409)
        self.assertEqual(len(self.provider.calls), 1)

    def test_scope_revision_and_unreviewed_brief_are_denied_before_provider(self):
        self.configured()
        self.assertEqual(self.client.post(self.url, json=self.data).status_code, 401)
        self.assertEqual(self.generate(expectedRevision=0).status_code, 409)
        self.auth.owner = OTHER
        self.assertEqual(self.generate().status_code, 403)
        self.auth.owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        changed = copy.deepcopy(self.doc)
        changed['ownerStrategy'].pop('confirmedContext')
        saved = self.client.post(self.root, headers=self.headers, json={
            'id':self.ident, 'mutationId':'5'*32, 'expectedRevision':1, 'document':changed})
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(self.generate(expectedRevision=2).status_code, 400)
        self.assertEqual(self.provider.calls, [])

    def test_invalid_dimensions_reference_uploads_and_budget_do_not_call_provider(self):
        self.configured()
        for change in ({'size':'1080x1920'}, {'size':'auto'}, {'quality':'auto'}, {'day':True},
                       {'referenceAssetId':'private-original'}, {'visualBrief':'short'}):
            with self.subTest(change=change):
                self.assertEqual(self.generate(**change).status_code, 400)
        from dataclasses import replace
        self.config = replace(self.config, call_cap_microusd=1)
        self.client = self.create(image_config=self.config, image_http=self.provider).test_client()
        self.assertEqual(self.generate().status_code, 409)
        self.assertEqual(self.provider.calls, [])

    def test_malformed_output_remains_held_without_download(self):
        self.configured()
        self.provider.envelope = {'data':[{'url':'https://example.org/untrusted.png'}]}
        result = self.generate()
        self.assertEqual(result.json['state'], 'uncertain')
        self.assertEqual(self.client.get(self.url+'/'+'3'*32+'/original', headers=self.headers).status_code, 409)
        self.assertEqual(self.generate().json, result.json)
        self.assertEqual(len(self.provider.calls), 1)

    def test_wrong_dimensions_and_corrupt_bytes_are_not_exposed_as_validated_images(self):
        self.configured()
        for index, raw in enumerate((b'not an image', self.provider.png), 1):
            with self.subTest(index=index):
                self.provider.envelope = {'data':[{'b64_json':base64.b64encode(raw).decode()}]}
                result = self.generate(operationId=str(index+5)*32, size='1024x1536',
                    visualBrief='Abstract wheel arcs with room for exact words. Variation '+str(index))
                self.assertEqual(result.status_code, 200, result.json)
                self.assertEqual(result.json['state'], 'uncertain')
                self.assertEqual(self.client.get(self.url+'/'+str(index+5)*32+'/original', headers=self.headers).status_code, 409)

    def test_revocation_during_transport_hides_result_and_download(self):
        self.configured()
        self.provider.on_call = lambda: setattr(self.auth, 'allowed', False)
        self.assertEqual(self.generate().status_code, 403)
        self.assertEqual(self.client.get(self.url, headers=self.headers).status_code, 403)
        self.assertEqual(self.client.get(self.url+'/'+'3'*32+'/original', headers=self.headers).status_code, 403)
        self.assertEqual(len(self.provider.calls), 1)


if __name__ == '__main__': unittest.main()
