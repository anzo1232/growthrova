"""Local-only, idempotent agency-kit job orchestration. Never uses provider credits."""
import json,hashlib,sqlite3,tempfile,unittest
from pathlib import Path
import business_marketing_drafts as drafts
from tests.test_business_agency_pack import AgencyPackTests

class PackJobTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
  drafts.initialise(self.con)
  from business_agency_pack_jobs import initialise
  initialise(self.con)
  case=AgencyPackTests();case.setUp();self.addCleanup(case.doCleanups)
  self.image=case.image
  self.doc=case.doc
  drafts.save_draft(self.con,{'id':'a'*32,'mutationId':'b'*32,'expectedRevision':0,'document':self.doc})
 def test_repeated_requests_return_same_job_without_rerender(self):
  from business_agency_pack_jobs import enqueue_pack,render_pack,read_pack
  first=enqueue_pack(self.con,'a'*32,1,self.root)
  second=enqueue_pack(self.con,'a'*32,1,self.root)
  self.assertEqual(first['id'],second['id'])
  self.assertEqual(first['status'],'queued')
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM marketing_pack_jobs').fetchone()[0],1)
  render_pack(self.con,first['id'],self.root,source_image=self.image)
  job=read_pack(self.con,first['id'])
  self.assertEqual(job['status'],'done')
  self.assertTrue((self.root/'marketing_packs'/first['id']/'campaign-kit.zip').is_file())
  self.assertEqual(read_pack(self.con,first['id'])['files'],job['files'])
 def test_revision_conflict_prevents_outdated_result(self):
  from business_agency_pack_jobs import enqueue_pack,PackError
  with self.assertRaises(PackError):enqueue_pack(self.con,'a'*32,5,self.root)
 def test_untrusted_pack_paths_are_denied(self):
  from business_agency_pack_jobs import asset_path,PackError,enqueue_pack,render_pack
  job=enqueue_pack(self.con,'a'*32,1,self.root);render_pack(self.con,job['id'],self.root,source_image=self.image)
  for item in ('../secret.txt','other.png','notes.env','.hidden','./manifest.json'):
   with self.assertRaises(PackError):asset_path(self.con,job['id'],self.root,item)
  self.assertEqual(asset_path(self.con,job['id'],self.root,'hero-ad.png').suffix,'.png')
 def test_no_paid_runway_request_is_needed_for_typography_pack(self):
  from business_agency_pack_jobs import enqueue_pack,render_pack
  job=enqueue_pack(self.con,'a'*32,1,self.root)
  result=render_pack(self.con,job['id'],self.root,source_image=None)
  self.assertEqual(result['status'],'done')
  info=json.loads((self.root/'marketing_packs'/job['id']/'manifest.json').read_text())
  self.assertEqual(info['assetOrigin'],'typography_only_concepts')
 def test_prior_pack_format_is_not_reused_after_asset_recipe_changes(self):
  from business_agency_pack_jobs import enqueue_pack,latest_pack
  job=enqueue_pack(self.con,'a'*32,1,self.root)
  self.con.execute('UPDATE marketing_pack_jobs SET fingerprint=? WHERE id=?',('previous_format',job['id']))
  self.con.commit()
  self.assertEqual(latest_pack(self.con,'a'*32),[])
 def test_owner_confirmed_website_picture_updates_pack_without_spending_ai_credits(self):
  from business_agency_pack_jobs import enqueue_pack,render_pack,latest_pack
  from business_website_media import import_photo
  from PIL import Image
  import io
  # Add the exact image URL to the saved source evidence.
  current=drafts.read_draft(self.con,'a'*32)
  doc=current['document'];photo_url=doc['sourceUrl'].rstrip('/')+'/work-photo.jpg'
  doc['websiteImages']=[{'url':photo_url,'alt':'Work photo from the business website'}]
  drafts.save_draft(self.con,{'id':'a'*32,'mutationId':'c'*32,'expectedRevision':1,'document':doc})
  first=enqueue_pack(self.con,'a'*32,2,self.root)
  raw=io.BytesIO();Image.new('RGB',(800,640),'#a86e4f').save(raw,format='JPEG')
  import_photo(self.con,'a'*32,photo_url,self.root,owner_confirmed=True,
    fetch=lambda *a:(raw.getvalue(),'image/jpeg'),
    resolve=lambda *a,**k:[(None,None,None,None,('93.184.215.14',443))])
  second=enqueue_pack(self.con,'a'*32,2,self.root)
  self.assertNotEqual(first['id'],second['id'])
  self.assertEqual(latest_pack(self.con,'a'*32)[0]['id'],second['id'])
  render_pack(self.con,second['id'],self.root,source_image=None)
  root=self.root/'marketing_packs'/second['id']
  metadata=json.loads((root/'manifest.json').read_text())
  self.assertEqual(metadata['assetOrigin'],'owner_declared_website_photos')
  self.assertEqual(metadata['websitePhotoCount'],1)
  self.assertFalse(metadata['clientMediaRightsVerified'])
 def test_completing_distinct_runway_images_creates_new_pack_version_without_retries(self):
  import business_runway as runway
  from business_agency_pack_jobs import enqueue_pack,latest_pack
  from PIL import Image
  runway.initialise(self.con)
  current=drafts.read_draft(self.con,'a'*32);doc=current['document']
  doc['creatives'][0]['brief']='Professional home services advert, natural photographic geometry and roofing materials, with empty space for clear type.'
  drafts.save_draft(self.con,{'id':'a'*32,'mutationId':'d'*32,'expectedRevision':1,'document':doc})
  early=enqueue_pack(self.con,'a'*32,2,self.root)
  doc=drafts.read_draft(self.con,'a'*32)['document']
  brief=runway._recipe(doc,'creative-1');fp=runway._fingerprint('a'*32,'creative-1',brief)
  path=self.root/'generated'/('e'*32+'.png');path.parent.mkdir();Image.new('RGB',(800,1000),(40,85,140)).save(path,'PNG')
  import hashlib,json,time
  content=path.read_bytes()
  result={'width':800,'height':1000,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content),'qualityStatus':'awaiting_visual_and_brand_review'}
  self.con.execute('INSERT INTO runway_image_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
    ('e'*32,'a'*32,'creative-1',fp,json.dumps(brief),'completed',None,20,20,json.dumps(result),None,time.time(),time.time()))
  self.con.commit()
  later=enqueue_pack(self.con,'a'*32,2,self.root)
  self.assertNotEqual(early['id'],later['id'])
  self.assertEqual(latest_pack(self.con,'a'*32,self.root)[0]['id'],later['id'])
 def test_generated_video_is_included_only_when_verified_and_changes_pack_version(self):
  import business_runway_video as video
  import time,json,hashlib,subprocess
  from business_agency_pack_jobs import enqueue_pack,render_pack,latest_pack
  prior=enqueue_pack(self.con,'a'*32,1,self.root)
  # Source image and provider job are created in a separate private test root.
  original=self.root/'source-media.png'
  from PIL import Image
  Image.new('RGB',(768,960),(25,60,88)).save(original)
  digest=hashlib.sha256(original.read_bytes()).hexdigest()
  raw=self.root/'generated_videos'/('e'*32+'.mp4');raw.parent.mkdir()
  subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=720x1280:rate=24:duration=5',
    '-c:v','libx264','-preset','ultrafast',str(raw)],check=True,timeout=30,capture_output=True)
  info={'bytes':raw.stat().st_size,'sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'qualityStatus':'pending_human_review'}
  self.con.execute('''INSERT INTO runway_video_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
    ('e'*32,'a'*32,1,'f'*64,'completed',None,digest,'{}',25,25,json.dumps(info),None,time.time(),time.time()))
  self.con.commit()
  # Source image digest must match the saved hero. Without that, video is not admitted.
  no_match=enqueue_pack(self.con,'a'*32,1,self.root)
  self.assertEqual(prior['id'],no_match['id'])
