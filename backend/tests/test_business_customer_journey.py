"""Website-to-approval journey evidence, not a published or generated campaign."""
import sqlite3,unittest,uuid
from tests.test_business_offer_research import dossier,FACT,DID
from tests.test_business_marketing_drafts import document
import business_marketing_drafts as drafts
import business_scene_contracts as contracts
import business_customer_journey as journey

class JourneyTests(unittest.TestCase):
 def setUp(self):
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
  drafts.initialise(self.con);contracts.initialise(self.con)
  doc=document();doc.update(business='Roof Shop',sourceUrl='https://roof-shop.example/',observedFacts=[FACT])
  drafts.save_draft(self.con,{'id':DID,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':doc})
 def review(self,data=None):
  return journey.prepare(self.con,DID,1,dossier() if data is None else data,as_of='2026-10-28')
 def test_produces_customer_facing_journey_without_claiming_generated_content(self):
  before=self.con.total_changes;p=self.review()
  self.assertEqual(self.con.total_changes,before)
  self.assertEqual(p['business'],'Roof Shop')
  self.assertTrue(p['marketingPlan']['postCount']>0)
  self.assertEqual(p['creativeQueue'][0]['status'],'held_for_reference_and_review')
  self.assertFalse(p['publishing']['allowed'])
  self.assertFalse(p['paidGeneration']['allowed'])
  self.assertEqual(p['nextOwnerAction'],'provide_authentic_assets')
  self.assertEqual(p['research']['status'],'needs_internal_scene_review')
 def test_unknown_research_does_not_make_fake_ready_creative(self):
  d=dossier();d['angles'][0]['actionCue']='install solar panels'
  p=self.review(d)
  self.assertEqual(p['creativeQueue'][0]['status'],'blocked_by_research')
  self.assertEqual(p['nextOwnerAction'],'resolve_business_evidence')
 def test_no_sources_is_not_turned_into_a_campaign(self):
  with self.assertRaises(journey.JourneyError):
   self.review({'sources':[],'angles':[]})
 def test_always_preserves_plan_and_revision_identity(self):
  p=self.review()
  self.assertEqual(p['draftId'],DID)
  self.assertEqual(p['revision'],1)
  self.assertRegex(p['documentSha256'],r'^[a-f0-9]{64}$')
  self.assertTrue(p['needsOwnerApproval'])
  self.assertFalse(p['resultsVerified'])
if __name__=='__main__':unittest.main()
