"""Real files from the existing user media library; entirely synthetic footage."""
import hashlib,json,sqlite3,subprocess,tempfile,time,uuid,unittest
from pathlib import Path
from PIL import Image
import business_website_media as website_media
import business_marketing_drafts as drafts
import business_cinematic_video as cinematic
import business_reel_workbench as reel
import business_reel_owner_media as originals
import business_reel_visual_intelligence as vision
from tests.test_business_marketing_drafts import document
class ExistingAuthorisedFootageTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
  drafts.initialise(self.con);cinematic.initialise(self.con);reel.initialise(self.con);website_media.initialise(self.con)
  self.con.execute('CREATE TABLE sources(id TEXT PRIMARY KEY,filename TEXT NOT NULL,mime TEXT NOT NULL,bytes INTEGER NOT NULL,status TEXT NOT NULL,result_json TEXT,created REAL NOT NULL,updated REAL NOT NULL)')
  did=uuid.uuid4().hex;doc=document()
  doc['editorialShortlist']={'status':'three_directions_ready_for_asset_intake','sector':'restaurant','candidates':[
   {'id':f'concept{i}','role':'Video','media':'Reel','format':'9:16','direction':'Authentic craft',
    'hook':'Real food craft number '+str(i),
    'evidence':{'kind':('method','bread','heritage')[i],'label':'restaurant story',
     'quote':'The restaurant has detailed food and authentic preparation techniques.'}} for i in range(3)]}
  drafts.save_draft(self.con,{'id':did,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':doc})
  self.project_did=did;self.project=reel.create(self.con,did,1)['id']
  self.src=uuid.uuid4().hex
  path=self.root/'files'/(self.src+'.mp4');path.parent.mkdir()
  subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i','testsrc2=size=960x540:rate=12',
   '-t','8','-c:v','libx264','-preset','ultrafast','-crf','32',str(path)],check=True,capture_output=True,timeout=25)
  self.original=path;self.digest=hashlib.sha256(path.read_bytes()).hexdigest()
  self.con.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',(self.src,'genuine-fixture-video.mp4','video/mp4',
    path.stat().st_size,'done',None,time.time(),time.time()))
  self.con.commit()
 def test_owner_permission_required_and_full_landscape_video_kept_uncropped(self):
  note='I have legal permission to use this original business clip in social advertising.'
  with self.assertRaises(originals.OwnerMediaError):
   originals.select(self.con,self.project,'hook',self.src,self.root,owner_confirmed=False,rights_note=note)
  result=originals.select(self.con,self.project,'hook',self.src,self.root,owner_confirmed=True,rights_note=note)
  self.assertEqual(result['originalSha256'],self.digest)
  self.assertEqual(result['originalDimensions'],[960,540])
  self.assertTrue(result['fullFrameRetained'])
  self.assertEqual(result['newPaidCalls'],0)
  self.assertTrue(self.original.is_file())
  entry,path=originals.file_for(self.con,self.project,'hook',self.root)
  self.assertEqual(entry['source_width'],960)
  self.assertEqual(reel.read(self.con,self.project)['slots'][0]['sourceType'],'owner_authorised_video')
  self.assertEqual(reel.read(self.con,self.project)['customerAllowanceConsumed'],0)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0],0)
  with self.assertRaises(originals.OwnerMediaError):
   originals.select(self.con,self.project,'hook',self.src,self.root,owner_confirmed=True,rights_note=note)
 def test_real_source_still_requires_creative_checklist_then_director_acceptance(self):
  originals.select(self.con,self.project,'hook',self.src,self.root,owner_confirmed=True,
    rights_note='Original footage is held with documented permission for this campaign.')
  with self.assertRaises(reel.ReelError):
   reel.internal_review(self.con,self.project,'hook','accepted','Looks visually accurate and compelling in the footage','director_1')
  row=self.con.execute('SELECT qc_json FROM business_reel_owner_media WHERE project_id=? AND slot=?',(self.project,'hook')).fetchone()
  fast=json.loads(row['qc_json'])['fast']
  at=fast['frameSamples'][2]['timeSeconds']
  checks=[{'category':cat,'verdict':'pass','timeSeconds':at,
    'evidence':'Synthetic test fixture demonstrates complete manual checklist capture and original provenance.'} for cat in vision.ISSUES]
  report=reel.record_manual_visual_review(self.con,self.project,'hook',checks,'director_1')
  self.assertTrue(report['assessment']['allPassed'])
  final=reel.internal_review(self.con,self.project,'hook','accepted',
    'Verified full frame, non-deformed subject and documented business rights','director_1')
  self.assertEqual(final['acceptedShots'],1)
  self.assertTrue(final['privateWorkInProgress'])
  cuts=reel.prepare_edits(self.con,self.project,self.root)
  self.assertEqual([x['variant'] for x in cuts['edits']],['wip'])
 def test_owner_declared_photo_is_reference_not_finished_reel(self):
  photoid=uuid.uuid4().hex;folder=self.root/'website_photos'/self.project_did
  folder.mkdir(parents=True)
  photo=folder/(photoid+'.jpg')
  Image.new('RGB',(720,1280),(155,100,68)).save(photo,'JPEG')
  digest=hashlib.sha256(photo.read_bytes()).hexdigest()
  self.con.execute('INSERT INTO marketing_website_media VALUES(?,?,?,?,?,?,?,?)',(
   photoid,self.project_did,'https://example.org/our-food.jpg',digest,photo.stat().st_size,720,1280,time.time()))
  self.con.commit()
  with self.assertRaises(originals.OwnerMediaError):
   originals.stage_approved_photo(self.con,self.project,'hook',photoid,self.root,owner_confirmed=False)
  result=originals.stage_approved_photo(self.con,self.project,'hook',photoid,self.root,owner_confirmed=True)
  self.assertEqual(result['providerCreditsUsed'],0)
  self.assertFalse(result['countsAsAcceptedFootage'])
  output=reel.read(self.con,self.project)
  self.assertEqual(output['slots'][0]['productionStatus'],'awaiting_image_to_video_approval')
  self.assertTrue(output['slots'][0]['ownerMediaSelectionAllowed'])
  self.assertEqual(output['acceptedShots'],0)
  self.assertFalse(output['privateWorkInProgress'])
  with self.assertRaises(reel.ReelError):
   reel.prepare_edits(self.con,self.project,self.root)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0],0)
 def test_source_hash_tamper_cannot_be_used(self):
  originals.select(self.con,self.project,'hook',self.src,self.root,owner_confirmed=True,
    rights_note='Owned test video used only for local art direction without any publication.')
  row,path=originals.file_for(self.con,self.project,'hook',self.root)
  path.write_bytes(path.read_bytes()+b'changed')
  with self.assertRaises(originals.OwnerMediaError):originals.file_for(self.con,self.project,'hook',self.root)

 def provider_attempt(self,slot,status,actual):
  job=uuid.uuid4().hex
  self.con.execute("""INSERT INTO runway_cinematic_shots
   (id,draft_id,revision,shot_key,fingerprint,status,provider_task,request_summary,
    reserved_credits,actual_credits,result_json,error_code,created,updated)
   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
   (job,self.project_did,1,'workbench:'+self.project+':'+slot,uuid.uuid4().hex,
    status,'synthetic-'+job,'{}',12,actual,None,'synthetic_terminal',time.time(),time.time()))
  self.con.commit()
  return job
 def test_reconciled_failed_provider_allows_real_video_without_losing_ledger(self):
  job=self.provider_attempt('hook','failed',0)
  self.assertTrue(reel.read(self.con,self.project)['slots'][0]['ownerMediaSelectionAllowed'])
  result=originals.select(self.con,self.project,'hook',self.src,self.root,owner_confirmed=True,
    rights_note='Original footage is legally authorised for this isolated campaign fixture.')
  self.assertEqual(result['newPaidCalls'],0)
  self.assertFalse(reel.read(self.con,self.project)['slots'][0]['ownerMediaSelectionAllowed'])
  self.assertEqual(result['originalSha256'],self.digest)
  row=self.con.execute('SELECT status,actual_credits FROM runway_cinematic_shots WHERE id=?',(job,)).fetchone()
  self.assertEqual((row['status'],row['actual_credits']),('failed',0))
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0],1)
 def test_inflight_unknown_and_unreconciled_provider_attempts_block_both_source_paths(self):
  job=self.provider_attempt('hook','failed',None)
  for state,cost in [('failed',None),('cancelled',None),('rejected',None),('rejected_quality',None),
    ('submitting',0),('unknown',0),('queued',0),('running',0),('completed',12)]:
   with self.subTest(state=state,cost=cost):
    self.con.execute('UPDATE runway_cinematic_shots SET status=?,actual_credits=? WHERE id=?',(state,cost,job));self.con.commit()
    self.assertFalse(reel.read(self.con,self.project)['slots'][0]['ownerMediaSelectionAllowed'])
    with self.assertRaises(originals.OwnerMediaError) as error:
     originals.select(self.con,self.project,'hook',self.src,self.root,owner_confirmed=True,
       rights_note='This synthetic original has a clear owner permission for this fixture.')
    self.assertEqual(error.exception.code,'existing_provider_attempt')
    with self.assertRaises(originals.OwnerMediaError) as error:
     originals.stage_approved_photo(self.con,self.project,'hook','b'*32,self.root,owner_confirmed=True)
    self.assertEqual(error.exception.code,'existing_provider_attempt')
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_owner_media').fetchone()[0],0)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_still_references').fetchone()[0],0)
 def test_reconciled_rejected_or_cancelled_provider_allows_photo_reference_only(self):
  photoid=uuid.uuid4().hex;folder=self.root/'website_photos'/self.project_did;folder.mkdir(parents=True)
  photo=folder/(photoid+'.jpg');Image.new('RGB',(720,1280),(155,100,68)).save(photo,'JPEG')
  digest=hashlib.sha256(photo.read_bytes()).hexdigest()
  self.con.execute('INSERT INTO marketing_website_media VALUES(?,?,?,?,?,?,?,?)',(
   photoid,self.project_did,'https://example.org/our-food.jpg',digest,photo.stat().st_size,720,1280,time.time()))
  self.con.commit()
  for slot,status in zip(reel.SLOTS[:3],('cancelled','rejected','rejected_quality')):
   with self.subTest(status=status):
    job=self.provider_attempt(slot,status,4)
    result=originals.stage_approved_photo(self.con,self.project,slot,photoid,self.root,owner_confirmed=True)
    self.assertFalse(result['countsAsAcceptedFootage'])
    self.assertEqual(result['providerCreditsUsed'],0)
    row=self.con.execute('SELECT status,actual_credits FROM runway_cinematic_shots WHERE id=?',(job,)).fetchone()
    self.assertEqual((row['status'],row['actual_credits']),(status,4))

 def test_reusing_source_is_rejected_before_render_and_next_source_still_works(self):
  note='Self-created source authorised solely for this local recovery fixture.'
  originals.select(self.con,self.project,'hook',self.src,self.root,owner_confirmed=True,rights_note=note)
  with self.assertRaises(originals.OwnerMediaError) as denied:
   originals.select(self.con,self.project,'craft',self.src,self.root,owner_confirmed=True,rights_note=note)
  self.assertEqual(denied.exception.code,'source_already_used')
  folder=self.root/'reel_workbench'/self.project
  self.assertFalse((folder/'real-craft.mp4').exists())
  alternate=uuid.uuid4().hex;file=self.root/'files'/(alternate+'.mp4');file.write_bytes(self.original.read_bytes())
  self.con.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',(alternate,'second-fixture.mp4','video/mp4',file.stat().st_size,'done',None,time.time(),time.time()));self.con.commit()
  result=originals.select(self.con,self.project,'craft',alternate,self.root,owner_confirmed=True,rights_note=note)
  self.assertEqual(result['slot'],'craft')
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_owner_media').fetchone()[0],2)
  self.assertEqual(hashlib.sha256(self.original.read_bytes()).hexdigest(),self.digest)

 def test_failed_owner_media_commit_cleans_new_output_and_preserves_source(self):
  connection=self.con
  class CommitFailure:
   def __getattr__(self,name):return getattr(connection,name)
   def commit(self):raise sqlite3.OperationalError('Synthetic media registration failure')
  note='Self-created source authorised solely for this local cleanup fixture.'
  with self.assertRaises(sqlite3.OperationalError):
   originals.select(CommitFailure(),self.project,'hook',self.src,self.root,owner_confirmed=True,rights_note=note)
  self.assertFalse((self.root/'reel_workbench'/self.project/'real-hook.mp4').exists())
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_owner_media').fetchone()[0],0)
  self.assertEqual(hashlib.sha256(self.original.read_bytes()).hexdigest(),self.digest)
  self.assertEqual(originals.select(self.con,self.project,'hook',self.src,self.root,owner_confirmed=True,rights_note=note)['slot'],'hook')
