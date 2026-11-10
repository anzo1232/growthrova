"""Bad visuals must be excluded from future packs without destroying originals."""
import sqlite3,tempfile,unittest,json,hashlib,time
from pathlib import Path
from PIL import Image
import business_creative_review as reviews
import business_marketing_drafts as drafts
import business_runway as runway
import business_agency_pack_jobs as packs
from tests.test_business_agency_pack import AgencyPackTests

ID='a'*32
class CreativeReviewTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
  self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row;self.addCleanup(self.conn.close)
  drafts.initialise(self.conn);packs.initialise(self.conn);reviews.initialise(self.conn)
  base=AgencyPackTests();base.setUp();self.addCleanup(base.doCleanups);doc=base.doc
  doc['creatives'][0]['brief']='A natural photography composition showing a believable hospitality service concept, not a fake completed job.'
  drafts.save_draft(self.conn,{'id':ID,'mutationId':'e'*32,'expectedRevision':0,'document':doc})
  self.img=self.root/'generated'/('f'*32+'.png');self.img.parent.mkdir()
  Image.new('RGB',(800,1000),(58,103,121)).save(self.img)
  body=self.img.read_bytes()
  receipt={'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),'qualityStatus':'awaiting_visual_and_brand_review'}
  row=runway._recipe(doc,'creative-1')
  self.conn.execute('INSERT INTO runway_image_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(
   'f'*32,ID,'creative-1',runway._fingerprint(ID,'creative-1',row),json.dumps(row),'completed',None,
   20,20,json.dumps(receipt),None,time.time(),time.time()));self.conn.commit()
 def test_rejecting_a_picture_removes_it_from_new_pack_and_retains_paid_evidence(self):
  before=packs.enqueue_pack(self.conn,ID,1,self.root)
  assert 'creative-1' in packs._runway_assets(self.conn,ID,self.root)
  result=reviews.reject(self.conn,ID,'f'*32,'image','irrelevant_subject','A stone still-life instead of the concierge service')
  self.assertEqual(result['status'],'rejected')
  self.assertFalse(result['published'])
  self.assertNotIn('creative-1',packs._runway_assets(self.conn,ID,self.root))
  after=packs.enqueue_pack(self.conn,ID,1,self.root)
  self.assertNotEqual(before['id'],after['id'])
  self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM runway_image_jobs').fetchone()[0],1)
 def test_invalid_motive_and_forged_job_refuse_changes(self):
  with self.assertRaises(reviews.ReviewError):reviews.reject(self.conn,ID,'f'*32,'image','looks_bad','not a permitted reason')
  with self.assertRaises(reviews.ReviewError):reviews.reject(self.conn,ID,'c'*32,'image','irrelevant_subject','Unknown media')
  with self.assertRaises(reviews.ReviewError):reviews.reject(self.conn,'c'*32,'f'*32,'image','irrelevant_subject','Wrong campaign')
 def test_idempotent_flag_never_restores_rejected_asset(self):
  a=reviews.reject(self.conn,ID,'f'*32,'image','near_duplicate','Too close to original image')
  b=reviews.reject(self.conn,ID,'f'*32,'image','near_duplicate','Too close to original image')
  self.assertEqual(a['id'],b['id'])
  self.assertEqual(len(reviews.list_reviews(self.conn,ID)),1)
