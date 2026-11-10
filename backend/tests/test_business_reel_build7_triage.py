import unittest
from business_reel_build7_triage import summarise

class TriageTests(unittest.TestCase):
 def test_normal_scan_still_requires_human(self):
  x=summarise({'technicalMotionPass':True,'issues':[],'warnings':[]})
  self.assertFalse(x['machineCanApprove']);self.assertEqual(x['disposition'],'human_review_required');self.assertEqual(x['paidCalls'],0)
 def test_freeze_escalated(self):
  x=summarise({'technicalMotionPass':True,'issues':[],'warnings':['localised_frozen_segment_needs_review']})
  self.assertEqual(x['priority'],'high');self.assertTrue(any(t['code']=='localised_frozen_segment_needs_review' for t in x['reviewTasks']))
 def test_critical_failure_cannot_approve(self):
  x=summarise({'technicalMotionPass':False,'issues':['near_blank_across_timeline']})
  self.assertEqual(x['disposition'],'technical_rejected');self.assertFalse(x['machineCanApprove'])
 def test_duplicate_warnings_collapsed(self):
  x=summarise({'technicalMotionPass':True,'issues':[],'warnings':['low_detail_requires_review']*3})
  self.assertEqual(len([t for t in x['reviewTasks'] if t['code']=='low_detail_requires_review']),1)
 def test_bad_report_rejected(self):
  with self.assertRaises(ValueError):summarise({'technicalMotionPass':True,'issues':[], 'warnings':'fake'})

if __name__=='__main__':unittest.main()
