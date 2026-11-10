"""Human visual QC evidentiary controls; no pretend automatic artistry."""
import unittest
import business_reel_art_review as art
from business_reel_visual_intelligence import ISSUES
class HumanEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.source={'frameSamples':[{'timeSeconds':.3},{'timeSeconds':1.5},{'timeSeconds':2.7}]}
  self.checks=[{'category':x,'verdict':'pass','timeSeconds':1.5,
   'evidence':'A reviewer identifies the exact visible category in this synthetic fixture frame.'} for x in ISSUES]
 def test_all_categories_demanded_even_if_video_file_valid(self):
  result=art.check_categories(self.checks,self.source,required_categories=('food_accuracy',))
  self.assertTrue(result['allPassed'])
  self.assertTrue(result['humanReviewerRequired'])
  self.assertFalse(result['automaticallyApproved'])
  with self.assertRaises(art.ArtReviewError):art.check_categories(self.checks[:-1],self.source)
 def test_do_not_allow_not_applicable_for_physics_food_or_cinematography(self):
  for key in ('physical_realism','composition','cinematography','food_accuracy'):
   with self.subTest(category=key):
    items=[{**x,'verdict':'not_applicable' if x['category']==key else 'pass'} for x in self.checks]
    with self.assertRaises(art.ArtReviewError):
     art.check_categories(items,self.source,required_categories=('food_accuracy',))
 def test_rejection_cannot_be_disguised_as_pass(self):
  items=[{**x,'verdict':'reject' if x['category']=='hands' else 'pass'} for x in self.checks]
  outcome=art.check_categories(items,self.source)
  self.assertFalse(outcome['allPassed'])
  self.assertEqual(outcome['hardFailures'],['hands'])
 def test_fake_timestamp_and_bare_review_are_invalid(self):
  bad=[{**x,'timeSeconds':20} for x in self.checks]
  with self.assertRaises(art.ArtReviewError):art.check_categories(bad,self.source)
  bad=[{**x,'evidence':'looks fine'} for x in self.checks]
  with self.assertRaises(art.ArtReviewError):art.check_categories(bad,self.source)
 def test_unverified_reviewer_identifier_rejected(self):
  for name in ('', 'a', 'user with spaces', '<admin>',None):
   with self.assertRaises(art.ArtReviewError):art.reviewer_id(name)
