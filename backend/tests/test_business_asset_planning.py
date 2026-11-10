"""No cross-tenant media leakage or automatic creative permissions."""
import hashlib,sqlite3,tempfile,unittest
from pathlib import Path
from PIL import Image
import business_asset_catalog as catalog
import business_asset_planning as planning
class Tests(unittest.TestCase):
 def setUp(self):
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
  catalog.initialise(self.con)
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.file=Path(tmp.name)/'source.png';Image.new('RGB',(32,32)).save(self.file)
 def add(self,org='org-A',brand='biz-A',asset='photo-A',consent='owner_asserted'):
  data={'organisationId':org,'businessId':brand,'assetId':asset,'mediaKind':'photo','mimeType':'image/png','sourceSha256':hashlib.sha256(self.file.read_bytes()).hexdigest(),'sourceBytes':self.file.stat().st_size,'rightsStatement':'Owner declares permission for marketing uses','consentStatus':consent,'originalName':'source.png'}
  catalog.record(self.con,data,self.file)
 def test_scoping_and_candidate_status(self):
  self.add();self.add(org='org-B',brand='biz-B',asset='photo-B')
  a=planning.shortlist(self.con,'org-A','biz-A')
  self.assertEqual([x['assetId'] for x in a['assets']],['photo-A'])
  self.assertEqual(a['assets'][0]['planningStatus'],'candidate_pending_scene_review')
  self.assertFalse(a['assets'][0]['sourceAvailableForGeneration'])
  self.assertFalse(a['assets'][0]['mayClaimRealBusinessProof'])
  self.assertFalse(a['publishingEnabled'])
 def test_unconfirmed_owner_rights_stay_held(self):
  self.add(consent='not_confirmed')
  self.assertEqual(planning.shortlist(self.con,'org-A','biz-A')['assets'][0]['planningStatus'],'pending_rights_review')
 def test_missing_and_invalid_scope(self):
  self.assertEqual(planning.shortlist(self.con,'org-A','biz-B')['assets'],[])
  with self.assertRaises(planning.PlanningError):planning.shortlist(self.con,'org-A','biz-A',kind='pdf')
if __name__=='__main__':unittest.main()
