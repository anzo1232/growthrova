"""Google boundary fixtures exercise real routes/ledger; no paid requests."""
import base64
from contextlib import closing
from dataclasses import replace
import io
import json
import sqlite3
import unittest
from unittest.mock import patch
from PIL import Image


class NanoBananaProTests(unittest.TestCase):
    def setUp(self):
        from tests.test_business_growthrova_images import GrowthrovaImageTests
        self.flow = GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        for name, value in [('AUTHORISED_IMAGE_LIFETIME_MICROUSD', 5000000),
                            ('AUTHORISED_IMAGE_CALL_MICROUSD', 500000)]:
            hold = patch('business_growthrova_images.' + name, value)
            hold.start()
            self.addCleanup(hold.stop)
        from business_growthrova_images import ImageConfig
        self.config = ImageConfig.from_environment({
            'GROWTHROVA_IMAGE_ENABLED': 'true',
            'GROWTHROVA_IMAGE_GOOGLE_API_KEY': 'synthetic-google-key-not-real',
            'GROWTHROVA_IMAGE_API_KEY': 'synthetic-openai-key-wrong-provider',
            'GROWTHROVA_IMAGE_BUDGET_MICROUSD': '2000000',
            'GROWTHROVA_IMAGE_CALL_CAP_MICROUSD': '500000',
            'GROWTHROVA_IMAGE_INPUT_RATE_MICROUSD_PER_MILLION': '2000000',
            'GROWTHROVA_IMAGE_OUTPUT_COST_MICROUSD': '234000',
        })
        buf = io.BytesIO()
        fixture = Image.new('RGB', (2048, 2048), '#38554a')
        from PIL import ImageDraw
        draw = ImageDraw.Draw(fixture)
        for row in range(16):
            for column in range(16):
                draw.rectangle((column*112, row*112, column*112+111, row*112+111),
                               fill=((row*29+column*11)%256,
                                     (row*13+column*31)%256,
                                     (row*37+column*17)%256))
        for stripe in range(24):
            draw.rectangle((2048*7//8, stripe*2048//24, 2048-1, (stripe+1)*2048//24-1),
                           fill='white' if stripe%2 else 'black')
        fixture.save(buf, 'PNG')
        self.png = buf.getvalue()
        self.provider = self.flow.provider
        self.provider.envelope = {
            'candidates': [{'content': {'role':'model', 'parts': [
                {'inlineData': {'mimeType':'image/png', 'data':base64.b64encode(self.png).decode()}}
            ]}, 'finishReason':'STOP'}],
            'usageMetadata': {'promptTokenCount':100, 'candidatesTokenCount':1120, 'totalTokenCount':1220}
        }
        self.client = self.flow.create(image_config=self.config, image_http=self.provider).test_client()

    def generate(self, **changes):
        return self.client.post(self.flow.url, headers=self.flow.headers,
            json={**self.flow.data, 'size':'square_2k', 'quality':'standard', **changes})

    def test_default_google_route_reserves_and_persists_exact_pixels_without_cross_provider_key(self):
        status = self.client.get(self.flow.url, headers=self.flow.headers).json
        result = self.generate()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'proposed')
        self.assertEqual(result.json['model'], 'gemini-3-pro-image')
        self.assertEqual(result.json['size'], '2048x2048')
        self.assertEqual(status['modelLabel'], 'Nano Banana Pro')
        self.assertEqual(status['qualities'], ['standard'])
        url, options = self.provider.calls[0]
        self.assertEqual(url, 'https://generativelanguage.googleapis.com/v1/models/gemini-3-pro-image:generateContent')
        self.assertEqual(options['headers']['x-goog-api-key'], 'synthetic-google-key-not-real')
        self.assertNotIn('Authorization', options['headers'])
        self.assertEqual(options['json']['generationConfig']['imageConfig'],
                         {'aspectRatio':'1:1', 'imageSize':'2K'})
        self.assertEqual(options['json']['generationConfig']['candidateCount'], 1)
        self.assertNotIn('tools', options['json'])
        with closing(sqlite3.connect(self.flow.path)) as con:
            reservation = con.execute('SELECT reservation FROM growthrova_image_requests').fetchone()[0]
            self.assertGreaterEqual(reservation, 234000)
        self.assertEqual(self.generate().json, result.json)
        fresh = self.flow.create(image_config=self.config, image_http=self.provider).test_client()
        original = fresh.get(self.flow.url+'/'+result.json['operationId']+'/original', headers=self.flow.headers)
        self.assertEqual(original.data, self.png)
        self.assertEqual(len(self.provider.calls), 1)

    def test_empty_google_key_never_borrows_openai_key(self):
        from business_growthrova_images import ImageConfig
        config = ImageConfig.from_environment({
            'GROWTHROVA_IMAGE_API_KEY':'synthetic-openai-key-wrong-provider',
            'OPENAI_API_KEY':'synthetic-ambient-key',
            'GEMINI_API_KEY':'synthetic-ambient-google-key',
        })
        self.assertEqual(config.key, '')
        client = self.flow.create(image_config=config, image_http=self.provider).test_client()
        response = client.post(self.flow.url, headers=self.flow.headers,
            json={**self.flow.data, 'size':'square_2k','quality':'standard'})
        self.assertEqual(response.status_code, 503, response.json)
        self.assertEqual(self.provider.calls, [])

    def test_alternative_keeps_native_frame_across_legacy_alias_and_normalised_quality(self):
        parent = self.generate(size='1024x1024', quality='low').json
        self.assertEqual(parent['requestedFrame'], '1024x1024')
        self.assertEqual(parent['size'], '2048x2048')
        self.assertEqual(parent['quality'], 'standard')
        data = {**self.flow.data, 'operationId':'5'*32, 'parentOperationId':parent['operationId'],
                'visualBrief':'A closer illustrative wheel detail with quiet space above for composed words.',
                'size':'square_2k', 'quality':'standard'}
        estimate = self.client.post(self.flow.url+'/estimate', headers=self.flow.headers, json=data)
        self.assertEqual(estimate.status_code, 200, estimate.json)
        child = self.client.post(self.flow.url, headers=self.flow.headers, json=data)
        self.assertEqual(child.status_code, 200, child.json)
        self.assertEqual(child.json['state'], 'proposed', child.json)
        self.assertEqual(child.json['parentSha256'], parent['sha256'])
        self.assertEqual(child.json['reservedMicrousd'], estimate.json['reservationMicrousd'])
        self.assertEqual(self.provider.calls[-1][1]['json']['generationConfig']['imageConfig'],
                         {'aspectRatio':'1:1', 'imageSize':'2K'})
        self.assertEqual(self.client.post(self.flow.url, headers=self.flow.headers, json=data).json, child.json)
        self.assertEqual(len(self.provider.calls), 2)

    def test_wrong_google_pixels_are_held_without_retry(self):
        self.provider.envelope['candidates'][0]['content']['parts'][0]['inlineData']['data'] = base64.b64encode(self.flow.provider.png).decode()
        result = self.generate()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'uncertain')
        self.assertEqual(self.generate().json, result.json)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.client.get(self.flow.url+'/'+result.json['operationId']+'/original',
                         headers=self.flow.headers).status_code, 409)

    def test_nonfinished_google_response_is_not_accepted(self):
        self.provider.envelope['candidates'][0]['finishReason'] = 'MAX_TOKENS'
        result = self.generate()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'uncertain')
        self.assertEqual(self.generate().json, result.json)
        self.assertEqual(len(self.provider.calls), 1)

