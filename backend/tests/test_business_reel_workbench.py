"""No paid API calls. Explicitly synthetic fixture media and invented test receipts."""
import hashlib,json,sqlite3,subprocess,tempfile,time,uuid,unittest
from pathlib import Path
import business_marketing_drafts as drafts
import business_cinematic_video as cinematic
import business_reel_workbench as reel
import business_reel_brand_lock as brand_lock
from PIL import Image
from tests.test_business_marketing_drafts import document

class ReelReliabilityTests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory(prefix='clippr-reel-fixture-')
  self.addCleanup(self.folder.cleanup)
  self.root=Path(self.folder.name)
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
  drafts.initialise(self.c);cinematic.initialise(self.c);reel.initialise(self.c)
  self.did='a'*32
  doc=document();doc['business']='Fixture Persian Restaurant'
  doc['editorialShortlist']={'status':'three_directions_ready_for_asset_intake','candidates':[
   {'id':f'direction-{i}','role':'Verified craft research','media':'Reel','format':'9:16',
    'direction':f'Use authentic detail number {i}','hook':f'Hook {i} rooted in Persian food',
    'evidence':{'kind':('method','heritage','bread')[i],'label':'paragraph '+str(i),'quote':'Source-mentioned food technique %d and actual preparation.'%i}}
   for i in range(3)]}
  drafts.save_draft(self.c,{'id':self.did,'mutationId':uuid.uuid4().hex,'expectedRevision':0,'document':doc})
  self.project=reel.create(self.c,self.did,1)['id']
 def provider_fixture(self,slot, index, *, quality=True):
  jobid=uuid.uuid4().hex;path=self.root/'cinematic_shots'/(jobid+'.mp4');path.parent.mkdir(exist_ok=True)
  if quality:
   f=f'testsrc2=size=540x960:rate=12'
  else:
   f=f'color=c=black:size=540x960:rate=12'
  subprocess.run(['ffmpeg','-y','-nostdin','-v','error','-f','lavfi','-i',f,'-t','8',
     '-c:v','libx264','-preset','ultrafast','-crf','36',str(path)],check=True,capture_output=True,timeout=30)
  meta={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
  self.c.execute('INSERT INTO runway_cinematic_shots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
    jobid,self.did,1,'synthetic_'+str(index),'fingerprint_'+jobid,'completed',
    str(uuid.uuid4()),json.dumps({'model':'synthetic_test'}),96,96,json.dumps(meta),None,time.time(),time.time()))
  self.c.commit()
  return jobid,path
 def accept_fixture_shot(self,slot,reason,reviewer):
  # Synthetic colour-bar footage is not real food or people. This only tests
  # immutable human-review bookkeeping, not genuine creative quality.
  row=self.c.execute('SELECT qc_json FROM business_reel_shots WHERE project_id=? AND slot=?',
    (self.project,slot)).fetchone()
  visual=json.loads(row['qc_json'])['cheapVisualReview']
  stamp=visual['frameSamples'][2]['timeSeconds']
  checks=[{'category':item,'verdict':'pass',
    'timeSeconds':stamp,
    'evidence':'Synthetic fixture reviewer records this category for orchestration test only.'}
    for item in __import__('business_reel_visual_intelligence').ISSUES]
  reel.record_manual_visual_review(self.c,self.project,slot,checks,reviewer)
  return reel.internal_review(self.c,self.project,slot,'accepted',reason,reviewer)
 def test_technical_pass_requires_all_human_visual_categories_before_creative_acceptance(self):
  job,_=self.provider_fixture('hook',22)
  reel.attach_verified_job(self.c,self.project,'hook',job,self.root)
  with self.assertRaises(reel.ReelError):
   reel.internal_review(self.c,self.project,'hook','accepted',
    'The scene has a realistic subject and smooth movement','quality_director_1')
  self.assertFalse(reel.read(self.c,self.project)['slots'][0]['manualVisualReviewRecorded'])
  self.accept_fixture_shot('hook','Synthetic fixture manual categories reviewed in isolated QA only','quality_director_1')
  self.assertTrue(reel.read(self.c,self.project)['slots'][0]['manualVisualReviewRecorded'])
  self.assertEqual(reel.read(self.c,self.project)['slots'][0]['automaticVisualReviewStatus'],'not_run')
 def test_model_critical_hand_failure_is_a_durable_rejection_without_paid_retry(self):
  job,_=self.provider_fixture('craft',24)
  reel.attach_verified_job(self.c,self.project,'craft',job,self.root)
  shot=self.c.execute('SELECT qc_json FROM business_reel_shots WHERE project_id=? AND slot=?',(self.project,'craft')).fetchone()
  sample=json.loads(shot['qc_json'])['cheapVisualReview']
  message={'videoSha256':sample['videoSha256'],'model':'offline_vision_fixture',
   'findings':[{'category':'hands','severity':'critical','confidence':.98,
    'timeSeconds':sample['frameSamples'][3]['timeSeconds'],
    'explanation':'A synthetic test visual evaluator identifies fused and malformed hands in the scene.'}]}
  report=reel.record_external_visual_findings(self.c,self.project,'craft',message)
  self.assertEqual(report['report']['stage'],'auto_rejected')
  state=reel.read(self.c,self.project)
  self.assertEqual(state['slots'][1]['productionStatus'],'semantic_rejected')
  self.assertEqual(state['customerAllowanceConsumed'],0)
  self.assertFalse(state['autoPaidRetry'])
  with self.assertRaises(reel.ReelError):
   reel.record_external_visual_findings(self.c,self.project,'craft',message)
  with self.assertRaises(reel.ReelError):
   reel.internal_review(self.c,self.project,'craft','accepted',
    'Fused hands should never be approved by overriding a critical finding','quality_director_1')
 def test_paid_vision_adapter_is_approval_gated_without_provider_call(self):
  job,_=self.provider_fixture('experience',25)
  reel.attach_verified_job(self.c,self.project,'experience',job,self.root)
  sample=json.loads(self.c.execute('SELECT qc_json FROM business_reel_shots WHERE project_id=? AND slot=?',
    (self.project,'experience')).fetchone()[0])['cheapVisualReview']
  message={'videoSha256':sample['videoSha256'],'model':'approved_vision_adapter_v1','findings':[]}
  with self.assertRaises(reel.ReelError):
   reel.record_external_visual_findings(self.c,self.project,'experience',message,vision_spend_approved=False)
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_machine_findings').fetchone()[0],0)
 def test_technical_failure_is_held_without_customer_credit_charge(self):
  jobid,_=self.provider_fixture('hook',0,quality=False)
  state=reel.attach_verified_job(self.c,self.project,'hook',jobid,self.root)
  self.assertEqual(state['slots'][0]['productionStatus'],'technical_rejected')
  self.assertEqual(state['customerAllowanceConsumed'],0)
  self.assertEqual(state['providerCreditsObserved'],96)
  self.assertEqual(state['recovery']['alternatives'],2)
  self.assertFalse(state['autoPaidRetry'])
  self.assertFalse(state['publiclyComplete'])
  with self.assertRaises(reel.ReelError):reel.prepare_edits(self.c,self.project,self.root)
 def test_rejected_creative_and_unknown_submission_are_not_retried(self):
  jobid,_=self.provider_fixture('hook',1)
  state=reel.attach_verified_job(self.c,self.project,'hook',jobid,self.root)
  self.assertEqual(state['slots'][0]['productionStatus'],'awaiting_internal_review')
  state=reel.internal_review(self.c,self.project,'hook','rejected','Recognisable object is malformed and cannot represent the business', 'quality_director_1')
  self.assertEqual(state['slots'][0]['productionStatus'],'rejected')
  with self.assertRaises(reel.ReelError):reel.internal_review(self.c,self.project,'hook','accepted','Changed my mind after review','quality_director_1')
  self.c.execute('INSERT INTO runway_cinematic_shots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
    uuid.uuid4().hex,self.did,1,'unknown_first','unknown_hash','submission_unknown',None,
    '{}',96,None,None,'provider_connection_error',time.time(),time.time()))
  self.c.commit()
  updated=reel.read(self.c,self.project)
  self.assertEqual(updated['providerSubmissionUnknownJobs'],1)
  self.assertTrue(updated['recovery']['reconcileUnknownJobBeforeNewSpend'])
  self.assertEqual(updated['customerAllowanceConsumed'],0)
 def test_good_shots_make_wip_then_two_alternative_zero_cost_edits(self):
  ids=[]
  for index,slot in enumerate(('hook','craft','experience')):
   jobid,_=self.provider_fixture(slot,index)
   ids.append(jobid)
   state=reel.attach_verified_job(self.c,self.project,slot,jobid,self.root)
   self.assertEqual(state['slots'][index]['productionStatus'],'awaiting_internal_review')
   self.accept_fixture_shot(slot,
    'Checked actual motion, creative continuity, material realism and mobile crop', 'internal_art_director')
  status=reel.read(self.c,self.project)
  self.assertTrue(status['privateWorkInProgress']);self.assertFalse(status['publiclyComplete'])
  self.assertEqual(status['customerAllowanceConsumed'],0)
  self.assertEqual(status['providerCreditsObserved'],288)
  result=reel.prepare_edits(self.c,self.project,self.root)
  self.assertEqual([x['variant'] for x in result['edits']],['a','b','wip'])
  for variant in ('a','b','wip'):
   actual=reel.preview_file(self.c,self.project,variant,self.root)
   self.assertTrue(actual.stat().st_size>10000)
   probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nk=1:nw=1',str(actual)],check=True,capture_output=True,text=True)
   self.assertGreater(float(probe.stdout),5)
  self.assertEqual(reel.prepare_edits(self.c,self.project,self.root)['edits'],result['edits'])
  # No customer allowance charge, even when all 3 candidate shots pass.
  self.assertEqual(reel.allowance_status(self.c,self.project),0)
  self.assertFalse(result['customerCanPublish'])
 def test_partial_reel_preview_history_keeps_original_versions(self):
  first,_=self.provider_fixture('hook',1)
  reel.attach_verified_job(self.c,self.project,'hook',first,self.root)
  self.accept_fixture_shot('hook',
    'Verified object geometry, clear visual subject and natural physical movement','internal_review_team')
  first_wip=reel.prepare_edits(self.c,self.project,self.root)
  self.assertEqual([x['variant'] for x in first_wip['edits']],['wip'])
  original=reel.preview_file(self.c,self.project,'wip',self.root)
  before=original.read_bytes()
  second,_=self.provider_fixture('craft',2)
  reel.attach_verified_job(self.c,self.project,'craft',second,self.root)
  self.accept_fixture_shot('craft',
    'Visual treatment is distinct from opening and camera movement is believable','internal_review_team')
  second_wip=reel.prepare_edits(self.c,self.project,self.root)
  self.assertEqual(second_wip['editHistoryCount'],2)
  self.assertEqual(second_wip['edits'][0]['revision'],2)
  self.assertEqual(original.read_bytes(),before)
  note=reel.save_feedback(self.c,self.project,'wip','Please shorten the first shot and hold on the craft action longer.')
  self.assertEqual(len(note['feedback']),1)
  self.assertEqual(note['customerAllowanceConsumed'],0)
  with self.assertRaises(reel.ReelError):
   reel.save_feedback(self.c,self.project,'wip','yes')
 def test_variations_across_four_business_sectors_are_saved_without_spend(self):
  for business in ('Berenjak Persian Restaurant','Encore VIP Concierge','The Beauty Retreat','Marleo Construction'):
   with self.subTest(business=business):
    did=uuid.uuid4().hex;doc=document();doc['business']=business
    doc['editorialShortlist']={'status':'three_directions_ready_for_asset_intake','candidates':[
     {'id':'sector_'+str(i),'role':'Brand-specific creative','media':'Reel','format':'9:16',
      'direction':'Distinct subject','hook':business+' creative direction '+str(i),
      'evidence':{'kind':('method','heritage','service')[i],'label':'website paragraph','quote':business+' published a distinct service and customer experience.'}}
     for i in range(3)]}
    drafts.save_draft(self.c,{'id':did,'mutationId':uuid.uuid4().hex,'expectedRevision':0,'document':doc})
    result=reel.create(self.c,did,1)
    self.assertEqual(result['slots'][3]['sourceDirection'],'Verified brand and contact closing card')
    self.assertNotEqual(result['slots'][2]['sourceDirection'],result['slots'][3]['sourceDirection'])
    self.assertEqual(result['customerAllowanceConsumed'],0)
    self.assertEqual(result['acceptedShots'],0)
    self.assertFalse(result['paidGenerationAllowed'])
 def test_cross_draft_and_checksum_change_are_refused(self):
  other=uuid.uuid4().hex
  doc=document();drafts.save_draft(self.c,{'id':other,'mutationId':uuid.uuid4().hex,'expectedRevision':0,'document':doc})
  external_id=uuid.uuid4().hex
  jobid,path=self.provider_fixture('hook',0)
  self.c.execute('UPDATE runway_cinematic_shots SET draft_id=? WHERE id=?',(other,jobid));self.c.commit()
  with self.assertRaises(reel.ReelError):reel.attach_verified_job(self.c,self.project,'hook',jobid,self.root)
  self.c.execute('UPDATE runway_cinematic_shots SET draft_id=? WHERE id=?',(self.did,jobid));self.c.commit()
  path.write_bytes(path.read_bytes()+b'changed')
  with self.assertRaises(reel.ReelError):reel.attach_verified_job(self.c,self.project,'hook',jobid,self.root)
 def test_all_shots_still_need_complete_edit_signoff_before_owner_review(self):
  owned_logo=self.root/'synthetic-owner-logo.png'
  Image.new('RGB',(240,240),(23,40,50)).save(owned_logo,'PNG')
  brand_lock.lock(self.c,self.project,self.root,brand_name='Fixture Persian Restaurant',
    primary='#172832',accent='#C5A276',contact_url='https://example.org/',
    style='editorial',logo_path=owned_logo,
    owner_attestation='The logo was generated here solely for synthetic local QA and is approved for fixture review.',
    owner_confirmed=True)
  for index,slot in enumerate(reel.SLOTS):
   if slot=='payoff':
    reel.prepare_local_endcard(self.c,self.project,self.root,
      name='Fixture Persian Restaurant',cta='Explore our menu',
      contact_url='https://example.org/',owner_confirmed=True)
    reel.internal_review(self.c,self.project,slot,'accepted',
     'Verified actual business name and owned source URL; typography and mobile crop reviewed',
     'internal_art_director')
   else:
    job,_=self.provider_fixture(slot,index)
    reel.attach_verified_job(self.c,self.project,slot,job,self.root)
    self.accept_fixture_shot(slot,
     'Photorealism, object movement and shot framing manually confirmed for this fixture', 'internal_art_director')
  self.assertEqual(reel.read(self.c,self.project)['status'],'awaiting_internal_edit_review')
  reel.prepare_edits(self.c,self.project,self.root)
  before=reel.read(self.c,self.project)
  self.assertFalse(before['internallyReviewedFinalEdit'])
  self.assertEqual(before['customerAllowanceConsumed'],0)
  # A silent private preview cannot be accepted as the final consumer Reel.
  with self.assertRaises(reel.ReelError):
   reel.internal_review_final_edit(self.c,self.project,'a','accepted',
     'All details reviewed but the soundtrack is absent in this test',
     'internal_art_director',self.root)
  soundtrack=self.root/'synthetic-self-created-test-audio.wav'
  subprocess.run(['ffmpeg','-y','-nostdin','-v','error','-f','lavfi',
    '-i','sine=frequency=440:sample_rate=44100:duration=20',
    '-c:a','pcm_s16le',str(soundtrack)],check=True,capture_output=True,timeout=20)
  reel.attach_authorised_audio(self.c,self.project,'a',self.root,soundtrack,
    rights_attestation='Synthetic tone made locally for this fixture and approved for QA testing only.',
    owner_confirmed=True)
  safe={'brandAndCtaVerified':True,'claimsChecked':True,'allMediaRightsReviewed':True,
   'textBoxes':[{'subject':'brand','x':85,'y':500,'width':550,'height':135},
    {'subject':'cta','x':90,'y':685,'width':540,'height':130},
    {'subject':'contact','x':85,'y':855,'width':550,'height':120}]}
  after=reel.internal_review_final_edit(self.c,self.project,'a','accepted',
    'Reviewed the full synthetic test timeline with audible tone and text safe areas',
    'internal_art_director',self.root,quality_approval=safe)
  self.assertEqual(after['status'],'awaiting_internal_edit_review')
  self.assertFalse(after['internallyReviewedFinalEdit'])
  reel.attach_authorised_audio(self.c,self.project,'b',self.root,soundtrack,
    rights_attestation='Synthetic tone is owned and approved for local QA tests only, not commercial posting.',
    owner_confirmed=True)
  other=reel.internal_review_final_edit(self.c,self.project,'b','accepted',
    'Reviewed the second soundtracked synthetic variant with brand crop and volume checks',
    'internal_art_director',self.root,quality_approval=safe)
  self.assertEqual(other['status'],'ready_for_owner_review')
  self.assertTrue(other['internallyReviewedFinalEdit'])
  chosen=reel.record_local_owner_choice(self.c,self.project,'a',self.root,
     expected_content_sha256=next(e['contentSha256'] for e in other['edits'] if e['variant']=='a'),
     expected_review_set_sha256=other['reviewSetSha256'],
    owner_reference='synthetic_owner_qa_reference',
    approval_note='I have reviewed the two complete synthetic Reel edits and select A for local QA only.',
    owner_confirmed=True)
  self.assertTrue(chosen['localOwnerChoiceRecorded'])
  self.assertEqual(chosen['locallySelectedVariant'],'a')
  self.assertFalse(chosen['schedulePermitted'])
  self.assertEqual(chosen['customerAllowanceConsumed'],0)
  with self.assertRaises(reel.ReelError):
   reel.record_local_owner_choice(self.c,self.project,'b',self.root,
      expected_content_sha256=next(e['contentSha256'] for e in other['edits'] if e['variant']=='b'),
      expected_review_set_sha256=other['reviewSetSha256'],
     owner_reference='synthetic_owner_qa_reference',
     approval_note='Trying to silently override an existing owner choice',owner_confirmed=True)
  self.assertEqual(after['customerAllowanceConsumed'],0)
  self.assertFalse(after['customerCanPublish'])
  with self.assertRaises(reel.ReelError):
   reel.internal_review_final_edit(self.c,self.project,'a','rejected',
    'Changed reviewer verdict without preserving the first decision history',
    'internal_art_director',self.root,quality_approval=safe)
 def test_older_preview_schema_migrates_without_erasing_legacy_rows(self):
  old=sqlite3.connect(':memory:');old.row_factory=sqlite3.Row
  self.addCleanup(old.close)
  old.execute("""CREATE TABLE business_reel_edits(
   id TEXT PRIMARY KEY,project_id TEXT NOT NULL,variant TEXT NOT NULL,
   ordered_shots_json TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,
   status TEXT NOT NULL,created REAL NOT NULL,UNIQUE(project_id,variant))""")
  old.execute('INSERT INTO business_reel_edits VALUES(?,?,?,?,?,?,?,?)',
   ('1'*32,self.project,'wip','["hook"]','a'*64,2048,'internal_preview_only',time.time()))
  reel.initialise(old)
  item=old.execute('SELECT revision_no,sha256 FROM business_reel_edits').fetchone()
  self.assertEqual(item['revision_no'],1)
  self.assertEqual(item['sha256'],'a'*64)
  self.assertEqual(old.execute('SELECT COUNT(*) FROM business_reel_edits_legacy_20261021').fetchone()[0],1)
  reel.initialise(old)
  self.assertEqual(old.execute('SELECT COUNT(*) FROM business_reel_edits').fetchone()[0],1)
 def test_idempotent_project_and_original_paid_job_receipts_are_preserved(self):
  a=reel.create(self.c,self.did,1);b=reel.create(self.c,self.did,1)
  self.assertEqual(a['id'],b['id']);self.assertEqual(a['status'],'awaiting_approved_media')
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_projects').fetchone()[0],1)
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_allowances').fetchone()[0],0)
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0],0)
  self.assertIsNone(reel.read_for_draft(self.c,'b'*32))
