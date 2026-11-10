import unittest
from tests import test_business_nano_banana_pro as fixtures
class ProviderDiagnosticsTests(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.NanoBananaProTests()
  self.fixture.setUp()
  self.addCleanup(self.fixture.doCleanups)
 def test_unfinished_image_has_safe_diagnostic_and_no_retry(self):
  self.fixture.provider.envelope['candidates'][0]['finishReason']='MAX_TOKENS'
  response=self.fixture.generate()
  self.assertEqual(response.json['state'],'uncertain')
  self.assertEqual(response.json.get('providerDiagnostic',{}).get('finishReasons'),['MAX_TOKENS'])
  self.assertEqual(response.json.get('providerDiagnostic',{}).get('httpStatus'),200)
  self.assertNotIn(self.fixture.config.key,str(response.json))
  self.assertEqual(self.fixture.generate().json,response.json)
  self.assertEqual(len(self.fixture.provider.calls),1)
 def test_http_rejection_reports_reason_without_key_or_retry(self):
  import json
  parent=self.fixture
  class Response:
   status_code=403
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def iter_content(self,*args):
    yield json.dumps({'error':{'status':'PERMISSION_DENIED','message':'Restricted key '+parent.config.key}}).encode()
  def post(url,**kwargs):
   parent.provider.calls.append((url,kwargs))
   return Response()
  parent.provider.post=post
  response=parent.generate()
  self.assertEqual(response.json['state'],'uncertain')
  diag=response.json.get('providerDiagnostic',{})
  self.assertEqual(diag.get('httpStatus'),403)
  self.assertEqual(diag.get('providerStatus'),'PERMISSION_DENIED')
  self.assertNotIn(parent.config.key,str(response.json))
  self.assertEqual(parent.generate().json,response.json)
  self.assertEqual(len(parent.provider.calls),1)
 def test_opt_in_retains_rejected_reply_privately_without_new_call(self):
  from unittest.mock import patch
  from pathlib import Path
  import hashlib,json,stat
  self.fixture.provider.envelope['candidates'][0]['finishReason']='MAX_TOKENS'
  with patch.dict('os.environ',{'GROWTHROVA_IMAGE_CAPTURE_FAILED_RESPONSE':'true','GROWTHROVA_DATABASE_PATH':str(self.fixture.flow.path)}):
   response=self.fixture.generate()
  diagnostic=response.json.get('providerDiagnostic',{})
  capture=Path(self.fixture.flow.path).parent/'image-failure-captures'/(response.json['operationId']+'.json')
  self.assertTrue(capture.is_file())
  self.assertEqual(json.loads(capture.read_bytes()),self.fixture.provider.envelope)
  self.assertEqual(stat.S_IMODE(capture.stat().st_mode),0o600)
  self.assertEqual(diagnostic.get('captureSha256'),hashlib.sha256(capture.read_bytes()).hexdigest())
  self.assertEqual(self.fixture.generate().json,response.json)
  self.assertEqual(len(self.fixture.provider.calls),1)
if __name__=='__main__':unittest.main()
