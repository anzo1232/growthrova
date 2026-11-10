"""Nonbillable route/pixel regression for the real Handover layout failure."""
import base64
import copy
import hashlib
import io
import unittest
from PIL import Image, ImageDraw
from tests import test_business_nano_banana_pro as fixtures


class ImageLedCompositionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NanoBananaProTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        with Image.new('RGB', (1792, 2400), '#916b43') as source:
            draw = ImageDraw.Draw(source)
            # Coloured edge markers prove full-source preservation, not a crop.
            draw.rectangle((0, 0, 1791, 100), fill='#dd3020')
            draw.rectangle((0, 2300, 1791, 2399), fill='#2060dd')
            for y in range(200, 2200, 100):
                draw.line((100, y, 1600, y), fill='#cab9a0', width=30)
            buf = io.BytesIO()
            source.save(buf, 'JPEG', quality=95)
        self.original = buf.getvalue()
        f.provider.envelope['candidates'][0]['content']['parts'][0]['inlineData'] = dict(
            mimeType='image/jpeg', data=base64.b64encode(self.original).decode())
        response = f.generate(size='portrait_2k')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['state'], 'proposed', response.json)
        self.candidate = response.json
        self.doc = copy.deepcopy(f.flow.doc)
        self.doc['brandKit'] = dict(name='Fictional Studio', font_style='modern',
            primary_color='#123d30', secondary_color='#f6f0e4')
        self.doc['posts'][0].update(graphicText='Your business is your thing. Bookkeeping can be ours.',
            callToAction='Book a consultation.')
        # Layout-only QA: deliberately fictional copy, not sourced business claims.
        self.doc = f.flow.save_document(self.doc, 1, '6')['document']
        self.url = f.flow.url + '/' + self.candidate['operationId']

    def test_portrait_image_is_prominent_with_complete_words_and_no_new_inference(self):
        f = self.fixture
        response = f.client.get(self.url+'/static-preview?revision=2', headers=f.flow.headers)
        self.assertEqual(response.status_code, 200, response.json)
        manifest = response.json['manifest']
        x, y, w, h = manifest['layout']['photoBox']
        self.assertGreater(w*h/(1080*1350), .25,
            'Portrait artwork must not shrink to the old narrow 14%-of-canvas panel')
        self.assertAlmostEqual(w/h, 1792/2400, delta=.003)
        self.assertEqual(manifest['layout']['copy'], self.doc['posts'][0]['graphicText'])
        self.assertEqual(manifest['post'], self.doc['posts'][0])
        raw = base64.b64decode(response.json['previewBase64'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest['previewSha256'])
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.size, (1080, 1350))
            self.assertGreater(image.getpixel((x+w//2, y+5))[0], 180)
            self.assertGreater(image.getpixel((x+w//2, y+h-5))[2], 180)
        self.assertEqual(f.client.get(self.url+'/original', headers=f.flow.headers).data, self.original)
        fresh = f.flow.create().test_client()
        self.assertEqual(fresh.get(self.url+'/static-preview?revision=2', headers=f.flow.headers).json, response.json)
        self.assertEqual(len(f.provider.calls), 1)
        self.assertFalse(manifest['approved'])

    def test_all_frames_keep_text_separate_from_complete_image(self):
        f = self.fixture
        for frame, height, top, bottom in [('portrait',1350,0,1350), ('square',1080,0,1080), ('story',1920,250,1580)]:
            with self.subTest(frame=frame):
                result = f.client.get(self.url+f'/static-preview?revision=2&frame={frame}', headers=f.flow.headers)
                self.assertEqual(result.status_code, 200, result.json)
                layout = result.json['manifest']['layout']
                x, y, w, h = layout['photoBox']
                self.assertAlmostEqual(w/h, 1792/2400, delta=.003)
                self.assertGreaterEqual(y, top)
                self.assertLessEqual(y+h, bottom)
                self.assertLessEqual(layout['textBlocks'][0]['bottom'], y)
                # Every copy block is below the image and within the safe area.
                for block in layout['textBlocks'][1:]:
                    self.assertGreaterEqual(block['top'], y+h)
                    self.assertLessEqual(block['bottom'], block['limit'])
                    self.assertLessEqual(block['limit'], bottom)
                    self.assertGreaterEqual(block['fontSize'], 48)
                self.assertEqual(result.json['manifest']['height'], height)
        self.assertEqual(len(f.provider.calls), 1)

    def test_classic_multiline_brand_survives_saved_route_and_reopen(self):
        f = self.fixture
        self.doc['brandKit'].update(name='Harbour Plumbing and Heating Services', font_style='classic')
        saved = f.flow.save_document(self.doc, 2, '7')['document']
        result = f.client.get(self.url+'/static-preview?revision=3', headers=f.flow.headers)
        self.assertEqual(result.status_code, 200, result.json)
        manifest = result.json['manifest']
        self.assertEqual(manifest['brandKit'], saved['brandKit'])
        self.assertEqual(manifest['post'], saved['posts'][0])
        self.assertEqual(manifest['layout']['layout'], 'classic-editorial')
        name, headline, _ = manifest['layout']['textBlocks']
        self.assertGreater(name['bottom']-name['top'], 100)
        self.assertLess(name['bottom'], headline['top'])
        fresh = f.flow.create().test_client()
        self.assertEqual(fresh.get(self.url+'/static-preview?revision=3', headers=f.flow.headers).json, result.json)
        self.assertEqual(f.client.get(self.url+'/original', headers=f.flow.headers).data, self.original)
        self.assertEqual(len(f.provider.calls), 1)


if __name__ == '__main__':
    unittest.main()
