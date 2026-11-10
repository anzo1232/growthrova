"""Real routes/store with nonbillable image fixtures: technical validity is not approval."""
import base64
from contextlib import closing
import io
import sqlite3
import unittest
from PIL import Image, ImageDraw
from tests import test_business_growthrova_images as image_tests
import business_image_quality as quality

class GeneratedPreflightTests(unittest.TestCase):
    def setUp(self):
        self.flow=image_tests.GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.flow.configured()

    def test_completed_blank_output_is_held_without_losing_pixels_or_retrying(self):
        buf=io.BytesIO()
        Image.new('RGB',(1024,1024),'#123456').save(buf,'PNG')
        raw=buf.getvalue()
        self.flow.provider.envelope={'data':[{'b64_json':base64.b64encode(raw).decode()}]}
        result=self.flow.generate()
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['state'],'held',result.json)
        self.assertIn('low_visual_detail',result.json['technicalReview']['flags'])
        self.assertFalse(result.json['technicalReview']['ownerApproved'])
        self.assertEqual(result.json['independentReview'],'pending')
        self.assertEqual(self.flow.generate().json,result.json)
        reopened=self.flow.create(image_config=self.flow.config,image_http=self.flow.provider).test_client()
        self.assertEqual(reopened.get(self.flow.url,headers=self.flow.headers).json['candidates'][0],result.json)
        self.assertEqual(reopened.get(self.flow.url+'/'+result.json['operationId']+'/original',headers=self.flow.headers).data,raw)
        held=reopened.get(self.flow.url+'/'+result.json['operationId']+'/static-preview?revision=1',headers=self.flow.headers)
        self.assertNotEqual(held.status_code,200)
        self.assertEqual(len(self.flow.provider.calls),1)
        with closing(sqlite3.connect(self.flow.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_image_requests').fetchone()[0],1)

    def test_valid_square_has_technical_receipt_but_no_artistic_or_factual_approval(self):
        result=self.flow.generate()
        self.assertEqual(result.status_code,200,result.json)
        self.assertIn('technicalReview',result.json)
        review=result.json['technicalReview']
        self.assertEqual(review['flags'],[])
        self.assertEqual(review['qualityStatus'],'awaiting_visual_and_brand_review')
        self.assertFalse(review['ownerApproved'])
        self.assertFalse(review['claimsVerified'])
        self.assertEqual(result.json['independentReview'],'pending')
        self.assertFalse(result.json['canPublish'])

    def test_native_portrait_matches_requested_frame_and_wrong_frame_still_flags(self):
        image=Image.new('RGB',(1792,2400),'#38554a')
        draw=ImageDraw.Draw(image)
        for n in range(24):
            draw.rectangle((1568,n*100,1791,(n+1)*100-1),fill='white' if n%2 else 'black')
        try:
            result=quality.inspect_image(image,expected_aspect_ratio=3/4)
        except TypeError:
            self.fail('Technical inspection must support the requested native 3:4 frame')
        self.assertEqual(result['flags'],[])
        self.assertIn('unexpected_aspect_ratio',quality.inspect_image(image,expected_aspect_ratio=1)['flags'])
        for ratio in (0,-1,True,float('nan'),float('inf'),'3:4'):
            with self.subTest(ratio=ratio):
                with self.assertRaises(ValueError):
                    quality.inspect_image(image,expected_aspect_ratio=ratio)
