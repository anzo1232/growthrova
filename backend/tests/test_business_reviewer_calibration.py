"""Offline held-out reviewer calibration; authored labels are not perceptual truth."""
import unittest
import business_reviewer_calibration as c

H='a'*64
def case(id, label, prediction, source=None):
 return {'id':id,'sourceSha256':source or id[0]*64,'groundTruth':label,
         'reviewDecision':prediction,'labelOrigin':'independent_preexisting_review',
         'reviewOrigin':'separate_review_session','evidenceReference':'offline-reference-'+id}

class CalibrationTests(unittest.TestCase):
 def test_false_approval_and_rejection_are_separately_counted(self):
  report=c.evaluate([case('a1','reject','approve'),case('b1','approve','reject'),
                     case('c1','reject','reject'),case('d1','approve','approve')])
  self.assertEqual(report['falseApprovals'],1)
  self.assertEqual(report['falseRejections'],1)
  self.assertEqual(report['correctDecisions'],2)
  self.assertEqual(report['creativeApproved'],False)
 def test_unknown_truth_and_abstentions_are_not_hidden_from_denominator(self):
  report=c.evaluate([case('a1','unknown','approve'),case('b1','reject','abstain')])
  self.assertEqual(report['scoredCases'],0)
  self.assertEqual(report['uncertainCases'],1)
  self.assertEqual(report['abstentions'],1)
  self.assertIsNone(report['accuracy'])
 def test_same_media_is_not_independent_holdout(self):
  with self.assertRaises(c.CalibrationError):
   c.evaluate([case('a1','reject','reject',H),case('b1','approve','approve',H)])
 def test_same_label_and_review_source_cannot_claim_independence(self):
  v=case('a1','reject','approve')
  v['reviewOrigin']=v['labelOrigin']
  with self.assertRaises(c.CalibrationError):c.evaluate([v])
 def test_invalid_sha_identity_and_guessing_are_blocked(self):
  for v in [dict(case('a1','reject','approve'),sourceSha256='fake'),
            dict(case('a1','reject','approve'),groundTruth='good'),
            dict(case('a1','reject','approve'),reviewDecision='pass')]:
   with self.subTest(v=v),self.assertRaises(c.CalibrationError):c.evaluate([v])
 def test_untrusted_positive_labels_are_excluded(self):
  v=case('a1','approve','approve');v['labelOrigin']='generated_ai_self_label'
  with self.assertRaises(c.CalibrationError):c.evaluate([v])
 def test_duplicate_ids_are_rejected(self):
  with self.assertRaises(c.CalibrationError):c.evaluate([case('a1','reject','reject'),case('a1','reject','reject')])
 def test_no_network_spend_or_automatic_release(self):
  r=c.evaluate([case('a1','reject','reject')])
  self.assertEqual(r['providerCalls'],0)
  self.assertEqual(r['networkRequests'],0)
  self.assertFalse(r['creativeApproved'])
  self.assertFalse(r['canPublish'])
if __name__=='__main__':unittest.main()
