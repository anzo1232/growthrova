import unittest,uuid,copy
import business_marketing_drafts as drafts
import business_campaign_identity as identity
from tests.test_business_campaign_assets import CampaignAssetsTests
import business_campaign_readiness as readiness
class ReadinessTests(CampaignAssetsTests):
 def test_calendar_and_assets_stay_draft_only(self):
  result=readiness.overview(self.con,self.did,1,'org-123','fixture-restaurant')
  self.assertEqual(result['ownerAssetCount'],1)
  self.assertEqual(result['calendarCoverage'],len(self.doc['posts']))
  self.assertFalse(result['researchVerified'])
  self.assertFalse(result['mediaProduced']);self.assertFalse(result['canSpend']);self.assertFalse(result['canPublish'])
  self.assertTrue(all(not p['published'] and not p['mediaReady'] for p in result['calendarEntries']))
 def test_incomplete_calendar_is_explicit_blocker(self):
  did=uuid.uuid4().hex
  partial=copy.deepcopy(self.doc);partial['posts']=partial['posts'][:7]
  self.con.commit()
  drafts.save_draft(self.con,{'id':did,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':partial})
  identity.bind_internal(self.con,did,1,'org-123','fixture-restaurant',verified_owner_reference='verified-account-test-fixture')
  result=readiness.overview(self.con,did,1,'org-123','fixture-restaurant')
  self.assertFalse(result['completeThirtyDayCalendar'])
  self.assertEqual(result['nextAction'],'complete_thirty_day_calendar')
  self.assertEqual(result['calendarCoverage']+len(result['calendarGaps']),30)
 def test_no_foreign_campaign_calendar(self):
  with self.assertRaises(readiness.ReadinessError):readiness.overview(self.con,self.did,1,'org-456','fixture-restaurant')
 def test_no_stale_campaign_calendar(self):
  with self.assertRaises(readiness.ReadinessError):readiness.overview(self.con,self.did,2,'org-123','fixture-restaurant')
if __name__=='__main__':unittest.main()
