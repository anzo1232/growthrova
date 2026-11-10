import unittest
from benchmarks.twelve_labs_adapter import preflight,analysis_request,ProviderNotReady
class AdapterTest(unittest.TestCase):
 def test_no_key_dry_run(self):
  self.assertEqual(preflight({}),{'provider':'twelve_labs','configured':False,'network_used':False})
 def test_configured_dry_run_never_leaks_key(self):
  self.assertTrue(preflight({'TWELVE_LABS_API_KEY':'dummy-test-key'})['configured'])
  self.assertNotIn('dummy-test-key',repr(preflight({'TWELVE_LABS_API_KEY':'dummy-test-key'})))
 def test_source_validation(self):
  with self.assertRaises(ProviderNotReady):analysis_request('http://localhost/test.mp4','Find compelling moments')
  self.assertTrue(analysis_request('https://example.org/video.mp4','Find compelling moments')['review_required'])
if __name__=='__main__':unittest.main()
