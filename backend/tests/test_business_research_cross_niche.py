"""Authored cross-niche research graph regressions, NOT model-training or buyer validation."""
import sqlite3,unittest,uuid
import business_marketing_drafts as drafts
import business_scene_contracts as contracts
import business_offer_research as research
from tests.test_business_marketing_drafts import document

EXAMPLES=[
 ('roof','We inspect chimney flashing and repair damaged roof tiles for homeowners.', 'chimney flashing','inspect chimney flashing','local_service',False),
 ('cafe','Our café pours espresso shots into ceramic cups for customers.','espresso shots','pours espresso shots','hospitality',True),
 ('barber','Our barber trims beards and shapes hair during appointments.','beards','trims beards','bookable_service',False),
 ('software','Our SaaS scheduling software displays appointment slots and records customer bookings.','appointment slots','displays appointment slots','software',True),
 ('retail','Our clothing shop packs cotton t-shirts in recyclable boxes for delivery.','cotton t-shirts','packs cotton t-shirts','retail_product',True),
 ('accountant','Our accountant prepares year-end accounts and reviews tax records for businesses.','year-end accounts','prepares year-end accounts','professional_service',False),
 ('training','Our academy teaches students phlebotomy and demonstrates venepuncture on training models.','training models','demonstrates venepuncture','training',False),
 ('events','Our wedding event venue hosts live DJ performances and arranges sound-checks for receptions.','live DJ performances','hosts live DJ performances','events',False),
 ('property','Our estate agency shows apartment floorplans and arranges property viewings for buyers.','apartment floorplans','shows apartment floorplans','property',True),
 ('unknown','We tune historic pipe organs by adjusting reed voicing and wind pressure.','reed voicing','adjusting reed voicing','other',False),
]

class CrossNicheResearchTests(unittest.TestCase):
 def test_supported_offers_keep_their_own_service_action(self):
  for name,fact,subject,action,trait,exact in EXAMPLES:
   with self.subTest(niche=name):
    con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
    try:
     drafts.initialise(con);contracts.initialise(con)
     did=uuid.uuid4().hex;brand='Fixture '+name
     doc=document();doc.update(business=brand,sourceUrl=f'https://{name}-business.example/',observedFacts=[fact])
     drafts.save_draft(con,{'id':did,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':doc})
     snapshot={'sources':[
        {'id':'business','kind':'business','url':f'https://{name}-business.example/services','excerpt':fact,'capturedAt':'2026-10-27','publishedAt':None},
        {'id':'buyers','kind':'buyer','url':f'https://public-discussion.example/{name}','excerpt':'A visitor describes concerns about choosing an appropriate local service provider.','capturedAt':'2026-10-27','publishedAt':'2026-10-26'},
        {'id':'competitor','kind':'competitor','url':f'https://other-{name}.example/offer','excerpt':'Other company claims unbeatable guaranteed success and unlimited free packages.','capturedAt':'2026-10-27','publishedAt':None}],
        'angles':[{'id':'service-action','factIndex':0,'businessSourceId':'business','buyerSourceIds':['buyers'],
            'competitorSourceIds':['competitor'],'subjectCue':subject,'actionCue':action,'peoplePolicy':'illustrative_only',
            'format':'video','role':'process'}]}
     before=con.total_changes
     report=research.compose(con,did,1,snapshot,as_of='2026-10-28')
     self.assertEqual(con.total_changes,before)
     self.assertFalse(report['buyerDemandProven']);self.assertFalse(report['canSpend'])
     self.assertEqual(report['businessTrait'],trait)
     entry=report['candidates'][0]
     if name=='unknown':
      self.assertIn('specialist_niche_research_required',entry['blockers']);self.assertIsNone(entry['intent'])
     else:
      self.assertEqual(entry['blockers'],[],entry)
      self.assertIn(subject,entry['intent']['subject'])
      self.assertIn(action,entry['intent']['action'])
      self.assertEqual(entry['intent']['needsExactIdentity'],exact)
      self.assertNotIn('unlimited free packages',str(entry['intent']))
      self.assertNotIn('guaranteed success',str(entry['intent']))
    finally:con.close()

if __name__=='__main__':unittest.main()
