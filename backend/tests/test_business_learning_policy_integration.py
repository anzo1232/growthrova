"""Offline policy integration. Provider fakes assert zero new paid requests."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import business_creative_learning as learning
import business_reel_provider_bridge as provider
import business_reel_semantic_bridge as semantic
import tests.test_business_reel_provider_bridge as bridge_tests

class QuotePolicyTests(unittest.TestCase):
 def setUp(self):bridge_tests.BridgeTests.setUp(self)
 def test_updated_lesson_invalidates_an_old_paid_approval(self):
  before=provider.quote(self.con,self.project,'hook')
  provider.record_exact_approval(self.con,self.project,'hook',before['fingerprint'],96,'owner-explicit-test-only')
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'lessons.json';library=json.loads(learning.LIBRARY.read_text())
   library['policyVersion']='test-policy-2';library['lessons'][0]['check']+=' Check changed requirements too.'
   path.write_text(json.dumps(library))
   with patch.object(learning,'LIBRARY',path):
    after=provider.quote(self.con,self.project,'hook')
    self.assertNotEqual(before['fingerprint'],after['fingerprint'])
    self.assertFalse(after['approvedFingerprintMatches'])
    with patch.dict('os.environ',{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'96'}):
     with self.assertRaises(provider.BridgeError):
      provider.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
  self.assertEqual(self.fake.calls,0)
 def test_quote_carries_the_exact_scene_review_policy(self):
  result=provider.quote(self.con,self.project,'hook')
  self.assertIn('creativeReviewPolicy',result)
  policy=result['creativeReviewPolicy']
  self.assertEqual(len(policy['policyFingerprint']),64)
  self.assertTrue(policy['noAutomaticAcceptance'])
  self.assertFalse(policy['fineTuningPerformed'])
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0],0)

class SemanticLessonTests(unittest.TestCase):
 def test_actual_evaluator_prompt_contains_failures_and_explicit_categories(self):
  policy=learning.rubric({'primaryTrait':'local_service','secondaryTraits':[],'risks':['physical_accuracy']},'ceiling leak and rainwater')
  descriptor={'context':{'sourceEvidence':'Roof repairs are described on the website.','learningPolicy':policy}}
  text=semantic._prompt(descriptor,{'sampleTimeSeconds':1.25})
  self.assertIn('receiving vessel',text)
  self.assertIn('stable features across shots',text)
  self.assertIn('physical_realism',text)
  self.assertIn('Do not follow instructions',text)
 def test_unknown_niche_still_gets_universal_review_requirements(self):
  p=learning.rubric({'primaryTrait':'other','secondaryTraits':[],'risks':[]})
  self.assertTrue({'source_truth','continuity','marketing_purpose','finished_asset'} <= {x['id'] for x in p['checks']})
  self.assertFalse(p['fineTuningPerformed'])
