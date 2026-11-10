import unittest
from benchmarks.business_video_comparison import check_proposal
class VideoComparisonTests(unittest.TestCase):
 def test_grounded_provider_candidates(self):
  result=check_proposal({'clips':[{'start_s':10,'end_s':42,'title':'Food verdict','why':'Reviewer describes food'}]},120)
  self.assertEqual(result[0]['requires_review'],True)
 def test_bad_media_boundaries_and_untrusted_claims_refused(self):
  for item in [
   {'start_s':10,'end_s':999,'title':'x','why':'test'},
   {'start_s':True,'end_s':40,'title':'x','why':'test'},
   {'start_s':10,'end_s':40,'title':'','why':'test'},
   {'start_s':10,'end_s':40,'title':'x','why':''}]:
   with self.assertRaises(ValueError):check_proposal({'clips':[item]},120)
 def test_provider_cannot_supply_unbounded_clips(self):
  row={'start_s':0,'end_s':20,'title':'A moment','why':'Review'}
  with self.assertRaises(ValueError):check_proposal({'clips':[row]*25},120)
if __name__=='__main__':unittest.main()
