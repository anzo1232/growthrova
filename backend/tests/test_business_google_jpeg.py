import unittest,io,base64,hashlib
from PIL import Image
from tests import test_business_nano_banana_pro as fixtures
class GoogleJpegBoundaryTests(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.NanoBananaProTests();self.fixture.setUp()
  self.addCleanup(self.fixture.doCleanups)
 def test_real_jpeg_format_survives_generation_download_and_replay(self):
  f=self.fixture
  with Image.open(io.BytesIO(f.png)) as image:
   buffer=io.BytesIO();image.save(buffer,'JPEG',quality=90)
  jpeg=buffer.getvalue()
  f.provider.envelope['candidates'][0]['content']['parts'][0]['inlineData']={'mimeType':'image/jpeg','data':base64.b64encode(jpeg).decode()}
  response=f.generate();result=response.json
  self.assertEqual(result['state'],'proposed')
  self.assertEqual(result.get('mimeType'),'image/jpeg')
  self.assertEqual(result['sha256'],hashlib.sha256(jpeg).hexdigest())
  original=f.client.get(f.flow.url+'/'+result['operationId']+'/original',headers=f.flow.headers)
  self.assertEqual(original.status_code,200)
  self.assertEqual(original.mimetype,'image/jpeg')
  self.assertIn('.jpg',original.headers['Content-Disposition'])
  self.assertEqual(original.data,jpeg)
  self.assertEqual(f.generate().json,result)
  self.assertEqual(len(f.provider.calls),1)
 def test_unsupported_pixels_cannot_pass_with_a_jpeg_label(self):
  f=self.fixture
  b=io.BytesIO();Image.new('RGB',(2048,2048),'red').save(b,'GIF')
  f.provider.envelope['candidates'][0]['content']['parts'][0]['inlineData']={'mimeType':'image/jpeg','data':base64.b64encode(b.getvalue()).decode()}
  result=f.generate().json
  self.assertEqual(result['state'],'uncertain')
  self.assertEqual(len(f.provider.calls),1)
if __name__=='__main__':unittest.main()
