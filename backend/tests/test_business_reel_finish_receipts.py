"""Approval bookkeeping fixtures only; actual FFmpeg QC has separate integration tests."""
import hashlib,json,time,unittest,uuid
from unittest.mock import patch
from PIL import Image
import business_marketing_drafts as drafts
import business_reel_brand_lock as brand
import business_reel_workbench as reel
from tests import test_business_reel_workbench as fixtures

class FinishReceiptTests(unittest.TestCase):
 def setUp(self):
  fixtures.ReelReliabilityTests.setUp(self)
  logo=self.root/'fixture-logo.png'
  Image.new('RGB',(240,240),(30,50,40)).save(logo)
  brand.lock(self.c,self.project,self.root,brand_name='Fixture Persian Restaurant',
   primary='#1E3228',accent='#D0AF80',contact_url='https://example.org/',style='editorial',
   logo_path=logo,owner_attestation='Synthetic brand for isolated bookkeeping tests only, created and authorised locally.',
   owner_confirmed=True)
  self.folder_path=self.root/'reel_workbench'/self.project
  end=self.folder_path/'endcard-local.mp4';end.write_bytes(b'endcard fixture bytes')
  endsha=hashlib.sha256(end.read_bytes()).hexdigest()
  self.c.execute('INSERT INTO business_reel_local_endcards (project_id,sha256,bytes,brand_name,cta,contact_url,status,review_reason,reviewer,created,brand_logo_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
   (self.project,endsha,end.stat().st_size,'Fixture Persian Restaurant','Explore the menu',
    'https://example.org/','accepted','Fixture review','fixture_reviewer',time.time(),
    brand.read(self.c,self.project)['logoSha256']))
  for slot in ('hook','craft','experience'):
   self.c.execute('INSERT INTO business_reel_shots VALUES(?,?,?,?,?,?,?,?,?,?,?)',
    (uuid.uuid4().hex,self.project,slot,uuid.uuid4().hex,'f'*64,'{}','accepted',
     'Isolated state fixture','fixture_reviewer',time.time(),time.time()))
  for variant in ('a','b'):
   path=self.folder_path/(variant+'-1.mp4');path.write_bytes(('unit fixture '+variant).encode())
   self.c.execute('INSERT INTO business_reel_edits VALUES(?,?,?,?,?,?,?,?,?)',
    (uuid.uuid4().hex,self.project,variant,
     json.dumps([{'slot':slot,'seconds':1,'sha256':'f'*64} for slot in ('hook','craft','experience')]+[{'slot':'payoff','seconds':3,'sha256':endsha}]),
     hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_size,'internal_preview_only',time.time(),1))
  self.c.commit()
  self.qc=patch.object(reel.delivery_qc,'verify',return_value={
   'technicalReelPass':True,'audioPresent':True,'mobileSafeTextPass':True,'ownerBrandDetailsReviewed':True})
  self.qc.start();self.addCleanup(self.qc.stop)

 def review(self,variant):
  return reel.internal_review_final_edit(self.c,self.project,variant,'accepted',
   'Only fixture state transitions are verified here; not real creative quality.',
   'fixture_reviewer',self.root,quality_approval={'captionTextAndTimingVerified':True,'captionLayoutReviewed':True})

 def caption(self,variant,text='Owner supplied fixture hook',style=None):
  version=self.c.execute('SELECT COALESCE(MAX(track_revision),0)+1 FROM business_reel_caption_tracks WHERE project_id=? AND variant=?',
   (self.project,variant)).fetchone()[0]
  data=('WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n'+text+'\n').encode()
  path=self.folder_path/f'{variant}-edit1-captions{version}.vtt';path.write_bytes(data)
  self.c.execute('INSERT INTO business_reel_caption_tracks (id,project_id,variant,edit_revision,track_revision,source,cues_json,brand_style_json,vtt_sha256,bytes,owner_verified,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
   (uuid.uuid4().hex,self.project,variant,1,version,'owner_written_text',
    json.dumps([{'start':0,'end':2,'text':text}]),
    json.dumps(style or {'typeface':'editorial','weight':'bold','placement':'bottom_safe'}),
    hashlib.sha256(data).hexdigest(),len(data),1,time.time()))
  self.c.commit()
  return path

 def choose(self,variant='a',state=None):
  state=state or reel.read(self.c,self.project)
  edit=next(e for e in state['edits'] if e['variant']==variant)
  return reel.record_local_owner_choice(self.c,self.project,variant,self.root,
   owner_reference='fixture_owner_reference',approval_note='Reviewed both exact fixture versions for local bookkeeping only.',
   owner_confirmed=True,expected_content_sha256=edit['contentSha256'],
   expected_review_set_sha256=state['reviewSetSha256'])

 def test_caption_change_invalidates_review_without_erasing_old_receipt(self):
  self.review('a');ready=self.review('b')
  self.assertTrue(ready['bothEditsQualityChecked'])
  self.caption('a')
  self.assertFalse(reel.read(self.c,self.project)['bothEditsQualityChecked'])
  self.review('a')
  self.assertTrue(reel.read(self.c,self.project)['bothEditsQualityChecked'])
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_review_receipts').fetchone()[0],3)

 def test_other_cut_change_invalidates_owner_choice_and_rejects_stale_browser(self):
  self.review('a');old=self.review('b');self.choose(state=old)
  self.caption('b','A changed alternative hook')
  changed=reel.read(self.c,self.project)
  self.assertFalse(changed['localOwnerChoiceRecorded'])
  self.assertFalse(changed['bothEditsQualityChecked'])
  self.review('b')
  with self.assertRaises(reel.ReelError) as denied:self.choose(state=old)
  self.assertEqual(denied.exception.code,'stale_review')
  chosen=self.choose()
  self.assertTrue(chosen['localOwnerChoiceRecorded'])
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_owner_choice_receipts').fetchone()[0],2)
  self.assertFalse(chosen['schedulePermitted']);self.assertEqual(chosen['customerAllowanceConsumed'],0)

 def test_caption_style_is_part_of_review_even_when_words_match(self):
  self.caption('a');self.review('a');self.review('b')
  self.caption('a',style={'typeface':'editorial','weight':'regular','placement':'middle_safe'})
  self.assertFalse(reel.read(self.c,self.project)['bothEditsQualityChecked'])

 def test_archived_campaign_cannot_keep_or_receive_current_owner_choice(self):
  self.review('a');state=self.review('b');self.choose(state=state)
  saved=drafts.read_draft(self.c,self.did)
  drafts.save_draft(self.c,{'id':self.did,'mutationId':uuid.uuid4().hex,'expectedRevision':1,'document':saved['document']})
  archived=reel.read(self.c,self.project)
  self.assertFalse(archived['localOwnerChoiceRecorded'])
  self.assertFalse(archived['bothEditsQualityChecked'])
  with self.assertRaises(reel.ReelError) as denied:self.choose(state=state)
  self.assertEqual(denied.exception.code,'stale_revision')
  with self.assertRaises(reel.ReelError):reel.save_feedback(self.c,self.project,'a','An archived edit must be read only')

 def test_owner_choice_rechecks_caption_and_video_bytes(self):
  path=self.caption('b');self.review('a');state=self.review('b')
  original=path.read_bytes();path.write_bytes(original+b'changed')
  with self.assertRaises(reel.ReelError):self.choose(state=state)
  path.write_bytes(original)
  video=self.folder_path/'a-1.mp4';video.write_bytes(b'altered preview')
  with self.assertRaises(reel.ReelError):self.choose(state=state)
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_owner_choice_receipts').fetchone()[0],0)

 def test_unbound_legacy_reviews_remain_history_and_cannot_approve_current_media(self):
  for variant in ('a','b'):
   self.c.execute('INSERT INTO business_reel_final_reviews VALUES(?,?,?,?,?,?,?,?)',
    (uuid.uuid4().hex,self.project,variant,1,'accepted',json.dumps({'verifiedQc':{
      'technicalReelPass':True,'audioPresent':True,'mobileSafeTextPass':True,
      'ownerBrandDetailsReviewed':True}}),'legacy_fixture',time.time()))
  self.c.commit();reel.initialise(self.c)
  self.assertFalse(reel.read(self.c,self.project)['bothEditsQualityChecked'])
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_final_reviews').fetchone()[0],2)

 def test_brand_lock_can_upgrade_text_only_ending_without_overwriting_original(self):
  self.c.execute('UPDATE business_reel_local_endcards SET brand_logo_sha256=NULL WHERE project_id=?',(self.project,));self.c.commit()
  original=self.folder_path/'endcard-local.mp4';old=original.read_bytes()
  def render(*args,**kwargs):
   target=args[5];target.write_bytes(b'new branded ending fixture')
   return {'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size}
  with patch.object(reel.native_endcard,'render',side_effect=render):
   result=reel.prepare_local_endcard(self.c,self.project,self.root,
    name='Fixture Persian Restaurant',cta='Explore our menu',contact_url='https://example.org/',owner_confirmed=True)
  self.assertEqual(original.read_bytes(),old)
  ending=next(s for s in result['slots'] if s['slot']=='payoff')
  self.assertTrue(ending['masterLogoUsed'])
  self.assertEqual(ending['productionStatus'],'awaiting_internal_review')
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_endcard_history').fetchone()[0],1)
  with self.assertRaises(reel.ReelError):
   reel.prepare_local_endcard(self.c,self.project,self.root,
    name='Fixture Persian Restaurant',cta='Explore our menu',contact_url='https://example.org/',owner_confirmed=True)

 def test_final_caption_review_cannot_be_implied_from_brand_review(self):
  self.caption('a')
  with self.assertRaises(reel.ReelError) as denied:
   reel.internal_review_final_edit(self.c,self.project,'a','accepted',
    'Brand review alone does not verify subtitle timing and safe placement.',
    'fixture_reviewer',self.root,quality_approval={})
  self.assertEqual(denied.exception.code,'caption_review_missing')

 def test_earlier_three_shot_cut_cannot_pass_after_fourth_shot_is_accepted(self):
  row=self.c.execute("SELECT id,ordered_shots_json FROM business_reel_edits WHERE variant='a'").fetchone()
  manifest=[p for p in json.loads(row['ordered_shots_json']) if p['slot']!='experience']
  self.c.execute('UPDATE business_reel_edits SET ordered_shots_json=? WHERE id=?',(json.dumps(manifest),row['id']));self.c.commit()
  with self.assertRaises(reel.ReelError) as denied:self.review('a')
  self.assertEqual(denied.exception.code,'incomplete_cut')

 def test_stale_source_or_duplicate_slot_in_manifest_cannot_pass_final_review(self):
  row=self.c.execute("SELECT id,ordered_shots_json FROM business_reel_edits WHERE variant='a'").fetchone()
  manifest=json.loads(row['ordered_shots_json']);manifest[0]['sha256']='0'*64
  self.c.execute('UPDATE business_reel_edits SET ordered_shots_json=? WHERE id=?',(json.dumps(manifest),row['id']));self.c.commit()
  with self.assertRaises(reel.ReelError) as denied:self.review('a')
  self.assertEqual(denied.exception.code,'stale_cut_source')
  manifest=json.loads(row['ordered_shots_json']);manifest[1]=manifest[0]
  self.c.execute('UPDATE business_reel_edits SET ordered_shots_json=? WHERE id=?',(json.dumps(manifest),row['id']));self.c.commit()
  with self.assertRaises(reel.ReelError) as denied:self.review('a')
  self.assertEqual(denied.exception.code,'incomplete_cut')

 def test_caption_style_saved_before_brand_lock_must_match_final_brand(self):
  self.caption('a',style={'typeface':'modern','weight':'bold','placement':'bottom_safe'})
  with self.assertRaises(reel.ReelError) as denied:self.review('a')
  self.assertEqual(denied.exception.code,'caption_brand_mismatch')
