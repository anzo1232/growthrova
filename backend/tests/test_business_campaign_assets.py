import sqlite3,unittest,uuid,hashlib,tempfile
from pathlib import Path
from PIL import Image
import business_asset_catalog as catalog
import business_campaign_assets as campaign
import business_campaign_identity as identity
import business_marketing_drafts as drafts
from tests.test_business_marketing_drafts import document

class CampaignAssetsTests(unittest.TestCase):
 def setUp(self):
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
  drafts.initialise(self.con);catalog.initialise(self.con);identity.initialise(self.con)
  self.did=uuid.uuid4().hex;self.doc=document();self.doc['business']='fixture-restaurant'
  drafts.save_draft(self.con,{'id':self.did,'mutationId':uuid.uuid4().hex,'expectedRevision':0,'document':self.doc})
  identity.bind_internal(self.con,self.did,1,'org-123','fixture-restaurant',verified_owner_reference='verified-account-test-fixture')
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.file=Path(tmp.name)/'logo.png';Image.new('RGB',(48,48)).save(self.file)
  catalog.record(self.con,{'organisationId':'org-123','businessId':'fixture-restaurant','assetId':'restaurant-logo','mediaKind':'logo','mimeType':'image/png','sourceSha256':hashlib.sha256(self.file.read_bytes()).hexdigest(),'sourceBytes':self.file.stat().st_size,'rightsStatement':'Owner affirms rights to this business logo','consentStatus':'owner_asserted','originalName':'restaurant.png'},self.file)
 def test_correct_campaign_sees_held_candidate_without_spend(self):
  result=campaign.overview(self.con,self.did,1,'org-123','fixture-restaurant')
  self.assertEqual(result['assetCount'],1)
  self.assertEqual(result['assetCandidates'][0]['assetId'],'restaurant-logo')
  self.assertFalse(result['canSpend']);self.assertFalse(result['canPublish'])
  self.assertFalse(result['ownerAssetsInProduction'])
 def test_wrong_organisation_cannot_see_asset(self):
  with self.assertRaises(campaign.CampaignAssetError):campaign.overview(self.con,self.did,1,'org-456','fixture-restaurant')
 def test_wrong_business_and_stale_revision_fail(self):
  with self.assertRaises(campaign.CampaignAssetError):campaign.overview(self.con,self.did,1,'org-123','different-restaurant')
  with self.assertRaises(campaign.CampaignAssetError):campaign.overview(self.con,self.did,2,'org-123','fixture-restaurant')
 def test_kind_filter(self):
  self.assertEqual(campaign.overview(self.con,self.did,1,'org-123','fixture-restaurant',kind='video')['assetCount'],0)
if __name__=='__main__':unittest.main()
