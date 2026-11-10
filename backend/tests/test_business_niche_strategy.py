import unittest
from business_niche_strategy import profile,blueprint
CASES=[
 ('J&A Roofing',['Roof repairs and guttering in Portsmouth','Roofing inspections for local homes'],'local_service'),
 ('Bistro',['Restaurant serving a published tasting menu','Chef-led dining experiences'],'hospitality'),
 ('Hair Studio',['Barber services and haircuts with bookings','Men grooming consultations'],'bookable_service'),
 ('Digital Shop',['Ecommerce store with shipping and clothing','Product inventory and returns'],'retail_product'),
 ('Legal Firm',['Solicitor services for property conveyancing','Legal consultation appointments'],'professional_service'),
 ('Medical Academy',['Training courses for healthcare qualifications','Academy course certificates and enrolment'],'training'),
 ('Clippr',['SaaS platform for automated video clips','Software subscription and dashboard'],'software'),
 ('Event Group',['Wedding venue and ticketed live entertainment','Private event bookings'],'events'),
 ('Niche X',['Custom acoustic calibration for specialist instruments','Specialised consultancy and equipment servicing'],'other'),
]
class NicheStrategyTests(unittest.TestCase):
 def test_diverse_businesses(self):
  for name,facts,expected in CASES:
   with self.subTest(name=name):
    p=profile(name,facts);self.assertEqual(p['primaryTrait'],expected)
    b=blueprint(p,budget_credits=192)
    self.assertEqual(len(b['shots']),4)
    self.assertEqual(b['creditsReserved'],0)
    self.assertFalse(b['readyForProduction'])
    self.assertFalse(b['canSpend'])
    self.assertTrue(any(s['mediaPolicy']=='owner_authorised_only' for s in b['shots']))
 def test_empty_evidence_fails_closed(self):
  with self.assertRaises(ValueError):profile('Business',['short'])
 def test_client_proof_is_real_media_only(self):
  p=profile('J&A Roofing',['Roof repairs and guttering in Portsmouth','Roof inspections'])
  self.assertEqual(blueprint(p)['shots'][2]['mediaPolicy'],'owner_authorised_only')
 def test_regulated_claims_risk(self):
  p=profile('Clinic',['Medical clinic services and patient consultations'])
  self.assertIn('regulated_or_high_trust_claims',p['risks'])
if __name__=='__main__':unittest.main()
