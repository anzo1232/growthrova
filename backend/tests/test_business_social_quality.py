import unittest
from business_social_quality import screen,campaign_report
class AgencyQualityGateTests(unittest.TestCase):
 def setUp(self):
  self.post={'day':1,'channel':'Instagram','format':'Image advert','theme':'What happens during your roof survey?',
    'copyDraft':'Check the condition of the roof from a safe location and ask a qualified roofer to assess any issues you notice.','callToAction':'Request a roofing inspection'}
 def test_rejects_missing_proof_of_visual_without_regenerating(self):
  item=screen(self.post)
  self.assertEqual(item['status'],'rejected_by_preflight')
  self.assertIn('no_service_relevant_photo_or_approved_visual',item['issues'])
  self.assertFalse(item['autoRetry'])
 def test_video_is_never_presented_as_a_static_post(self):
  item=screen({**self.post,'format':'Reel concept'},illustrative_photo=True,photo_available=True)
  self.assertIn('real_video_required_not_a_static_graphic',item['issues'])
 def test_generic_hooks_fail(self):
  item=screen({**self.post,'theme':'What the brand represents'},photo_available=True,illustrative_photo=True)
  self.assertIn('weak_or_generic_hook',item['issues'])
 def test_good_minimum_evidence_is_still_not_auto_approved(self):
  item=screen(self.post,photo_available=True,illustrative_photo=True)
  self.assertEqual(item['status'],'awaiting_human_creative_review')
  self.assertFalse(item['publishApproved'])
 def test_historic_filler_headline_fails_even_with_authorised_image(self):
  for hook in ('What matters most','A useful place to begin','What the service covers','Common misconceptions'):
   with self.subTest(hook=hook):
    result=screen({**self.post,'theme':hook},photo_available=True,authentic_photo=True)
    self.assertIn('weak_or_generic_hook',result['issues'])
 def test_report_is_scoped_to_social_channels(self):
  report=campaign_report([self.post,{**self.post,'day':2,'channel':'Email'}],illustrative_photo_count=1)
  self.assertEqual(report['reviewed'],2)
  self.assertEqual(report['rejected'],1)
