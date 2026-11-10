"""The owner's real identity, editable WebVTT and complete-edit approval gates."""
import os,uuid,json,hashlib,unittest,base64,time
from unittest.mock import patch
import business_marketing_drafts as drafts
from pathlib import Path
from PIL import Image
import business_reel_brand_lock as brand
import business_reel_captions as captions
import business_reel_workbench as reel
from tests.test_business_reel_workbench import ReelReliabilityTests

class BrandAndCaptionTests(unittest.TestCase):
 def setUp(self):
  self.fixture=ReelReliabilityTests('test_idempotent_project_and_original_paid_job_receipts_are_preserved')
  self.fixture.setUp()
  self.addCleanup(self.fixture.doCleanups)
  self.con=self.fixture.c;self.project=self.fixture.project;self.root=self.fixture.root
 def image(self):
  source=self.root/('owned-'+uuid.uuid4().hex+'.png')
  Image.new('RGB',(210,180),(50,60,70)).save(source)
  return source
 def lock(self):
  return brand.lock(self.con,self.project,self.root,
   brand_name='Fixture Persian Restaurant',primary='#142a30',accent='#d3a663',
   contact_url='https://example.org/bookings',style='editorial',
   logo_path=self.image(),owner_confirmed=True,
   owner_attestation='The image was created for this isolated QA fixture and is explicitly authorised here.')
 def reviewed_clip(self):
  job,_=self.fixture.provider_fixture('hook',0)
  reel.attach_verified_job(self.con,self.project,'hook',job,self.root)
  self.fixture.accept_fixture_shot('hook',
   'Physically plausible movement, accurate role and legible framing for fixture','synthetic_director')
  return reel.prepare_edits(self.con,self.project,self.root)
 def test_brand_identity_and_original_logo_immutable(self):
  with self.assertRaises(brand.BrandLockError):
   brand.lock(self.con,self.project,self.root,brand_name='Other Restaurant',
    primary='#112233',accent='#332211',contact_url='https://example.org/',
    style='modern',logo_path=self.image(),owner_confirmed=True,
    owner_attestation='A real separate owner approval was recorded for this logo and verified identity.')
  kit=self.lock()
  self.assertTrue(kit['locked'])
  self.assertEqual(kit['primary'],'#142A30')
  self.assertEqual(kit['style'],'editorial')
  with self.assertRaises(brand.BrandLockError):self.lock()
  folder=self.root/'reel_workbench'/self.project/'owner-verified-brand.png'
  folder.write_bytes(folder.read_bytes()+b'tamper')
  with self.assertRaises(brand.BrandLockError):brand.read(self.con,self.project,self.root)
 def test_caption_tracks_are_editable_without_reencoding_the_actual_video(self):
  self.reviewed_clip();file=reel.preview_file(self.con,self.project,'wip',self.root)
  original=hashlib.sha256(file.read_bytes()).hexdigest()
  cues=[{'start':0.1,'end':1.25,'text':'Real food, crafted carefully.'},
    {'start':1.26,'end':2.48,'text':'Discover the details.'}]
  style={'typeface':'editorial','weight':'bold','placement':'bottom_safe'}
  first=self.save_captions(cues=cues,source='owner_written_text',
   style=style,owner_confirmed=True)
  self.assertTrue(first['externalSidecar']);self.assertFalse(first['bakedIntoVideo'])
  self.assertEqual(first['captionRevision'],1)
  firstfile=captions.file_for(self.con,self.project,'wip',self.root)
  self.assertIn('WEBVTT',firstfile.read_text())
  self.assertIn('00:00:00.100 --> 00:00:01.250',firstfile.read_text())
  second=self.save_captions(
    cues=[{'start':.1,'end':1.8,'text':'Carefully prepared from the beginning.'}],
    source='owner_written_text',style=style,owner_confirmed=True)
  self.assertEqual(second['captionRevision'],2)
  self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),original)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_caption_tracks').fetchone()[0],2)
  self.assertEqual(reel.read(self.con,self.project)['captionTracks']['wip']['captionRevision'],2)
  self.assertEqual(reel.read(self.con,self.project)['customerAllowanceConsumed'],0)
 def test_captions_cannot_fabricate_transcript_or_overlap(self):
  self.reviewed_clip();style={'typeface':'modern','weight':'bold','placement':'bottom_safe'}
  with self.assertRaises(captions.CaptionError):
   self.save_captions(
    cues=[{'start':0,'end':2,'text':'Our award-winning guaranteed restaurant'}],
    source='auto_transcript',style=style,owner_confirmed=True)
  with self.assertRaises(captions.CaptionError):
   self.save_captions(
    cues=[{'start':0,'end':1.5,'text':'First idea'},{'start':1,'end':2,'text':'Overlapping'}],
    source='owner_verified_transcript',style=style,owner_confirmed=True)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_caption_tracks').fetchone()[0],0)

 def save_captions(self,**details):
  edit=self.con.execute('SELECT revision_no FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',(self.project,'wip')).fetchone()
  current=captions.latest(self.con,self.project,'wip')
  details.setdefault('expected_edit_revision',edit['revision_no'])
  details.setdefault('expected_caption_revision',current['captionRevision'] if current else 0)
  return captions.save(self.con,self.project,'wip',self.root,**details)
 def simple_captions(self,**overrides):
  details={'cues':[{'start':.1,'end':1.6,'text':'Owner verified <b>literal</b> & text > markup.'}],
   'source':'owner_written_text','style':{'typeface':'editorial','weight':'bold','placement':'bottom_safe'},
   'owner_confirmed':True}
  details.update(overrides)
  return self.save_captions(**details)
 def new_audio_edit(self,changed_timing=False):
  old=self.con.execute('SELECT * FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',(self.project,'wip')).fetchone()
  original=reel.preview_file(self.con,self.project,'wip',self.root)
  revision=old['revision_no']+1
  target=original.parent/f'wip-{revision}.mp4';target.write_bytes(original.read_bytes())
  manifest=json.loads(old['ordered_shots_json'])
  if changed_timing:
   if isinstance(manifest,list):manifest[0]['seconds']=float(manifest[0]['seconds'])+.25
   else:raise AssertionError('Fixture requires the actual ordered-shot list')
  self.con.execute("""INSERT INTO business_reel_edits
   (id,project_id,variant,ordered_shots_json,sha256,bytes,status,created,revision_no)
   VALUES(?,?,?,?,?,?,?,?,?)""",
   (uuid.uuid4().hex,self.project,'wip',json.dumps(manifest),old['sha256'],old['bytes'],
    'internal_audio_review_only',time.time(),revision))
  return old['revision_no'],revision,target
 def test_uploaded_original_logo_survives_and_is_hashed_separately(self):
  source=self.root/'owner-original.jpg'
  Image.new('RGB',(210,180),(50,60,70)).save(source,'JPEG',quality=91)
  original=source.read_bytes()
  result=brand.lock_uploaded(self.con,self.project,self.root,
   logo_base64=base64.b64encode(original).decode('ascii'),mime='image/jpeg',
   brand_name='Fixture Persian Restaurant',primary='#142a30',accent='#d3a663',
   contact_url='https://example.org/bookings',style='editorial',owner_confirmed=True,
   owner_attestation='This original JPEG is an isolated authorised owner-upload test fixture.')
  folder=self.root/'reel_workbench'/self.project
  preserved=folder/'owner-verified-brand-original.jpg'
  self.assertEqual(preserved.read_bytes(),original)
  self.assertEqual(result['originalLogoSha256'],hashlib.sha256(original).hexdigest())
  self.assertNotEqual(result['originalLogoSha256'],result['logoSha256'])
  self.assertTrue(result['originalBytesPreserved'])
  self.assertEqual(result['originalLogoFormat'],'JPEG')
  preserved.write_bytes(original+b'tamper')
  with self.assertRaises(brand.BrandLockError) as error:brand.read(self.con,self.project,self.root)
  self.assertEqual(error.exception.code,'logo_changed')
 def test_archived_campaign_cannot_lock_brand_or_save_captions(self):
  self.reviewed_clip()
  project=reel._project(self.con,self.project)
  with patch.object(drafts,'read_draft',return_value={'revision':project['revision']+1}):
   with self.assertRaises(brand.BrandLockError) as error:self.lock()
   self.assertEqual((error.exception.code,error.exception.status),('stale_revision',409))
   with self.assertRaises(captions.CaptionError) as error:self.simple_captions()
   self.assertEqual((error.exception.code,error.exception.status),('stale_revision',409))
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_brand_locks').fetchone()[0],0)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_caption_tracks').fetchone()[0],0)
 def test_caption_literal_markup_and_sidecar_hash_and_stale_save(self):
  self.reviewed_clip();first=self.simple_captions()
  file=captions.file_for(self.con,self.project,'wip',self.root);blob=file.read_bytes()
  self.assertIn(b'&lt;b&gt;literal&lt;/b&gt; &amp; text &gt; markup.',blob)
  self.assertEqual(first['sha256'],hashlib.sha256(blob).hexdigest())
  self.assertIn('<b>literal</b>',first['cues'][0]['text'])
  with self.assertRaises(captions.CaptionError) as error:self.simple_captions(expected_caption_revision=0)
  self.assertEqual(error.exception.status,409)
  self.assertEqual(file.read_bytes(),blob)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_caption_tracks').fetchone()[0],1)
 def test_caption_save_rejects_changed_preview_and_preserves_prior_track(self):
  self.reviewed_clip();first=self.simple_captions()
  sidecar=captions.file_for(self.con,self.project,'wip',self.root);prior=sidecar.read_bytes()
  video=reel.preview_file(self.con,self.project,'wip',self.root);blob=video.read_bytes()
  video.write_bytes(bytes([blob[0]^1])+blob[1:])
  with self.assertRaises(captions.CaptionError) as error:self.simple_captions()
  self.assertEqual((error.exception.code,error.exception.status),('changed_source',409))
  self.assertEqual(sidecar.read_bytes(),prior)
  self.assertEqual(captions.latest(self.con,self.project,'wip')['captionRevision'],1)
 def test_audio_copy_inherits_exact_verified_sidecar_without_committing(self):
  self.reviewed_clip();first=self.simple_captions()
  original=captions.file_for(self.con,self.project,'wip',self.root);blob=original.read_bytes()
  prior=self.con.execute('SELECT id FROM business_reel_caption_tracks WHERE project_id=?',(self.project,)).fetchone()['id']
  old,new,target=self.new_audio_edit()
  self.assertIsNone(captions.latest(self.con,self.project,'wip'))
  result=captions.inherit_for_audio_edit(self.con,self.project,'wip',self.root,
   from_edit_revision=old,to_edit_revision=new)
  self.assertTrue(self.con.in_transaction)
  self.assertEqual((result['editRevision'],result['captionRevision']),(new,1))
  self.assertEqual(result['inheritedFrom'],prior)
  self.assertEqual(result['source'],first['source'])
  self.assertEqual(result['cues'],first['cues'])
  self.assertEqual(result['style'],first['style'])
  self.assertEqual(captions.file_for(self.con,self.project,'wip',self.root).read_bytes(),blob)
  self.assertEqual(result['sha256'],first['sha256'])
  self.con.rollback()
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_caption_tracks').fetchone()[0],1)
  self.assertEqual(self.con.execute('SELECT MAX(revision_no) FROM business_reel_edits WHERE project_id=?',(self.project,)).fetchone()[0],old)
  self.assertEqual(original.read_bytes(),blob)
 def test_audio_inheritance_rejects_changed_visual_timing(self):
  self.reviewed_clip();self.simple_captions()
  old,new,_=self.new_audio_edit(changed_timing=True)
  with self.assertRaises(captions.CaptionError) as error:
   captions.inherit_for_audio_edit(self.con,self.project,'wip',self.root,from_edit_revision=old,to_edit_revision=new)
  self.assertEqual(error.exception.code,'visual_timing_changed')
  self.assertIsNone(captions.latest(self.con,self.project,'wip'))
  self.assertFalse((self.root/'reel_workbench'/self.project/f'wip-edit{new}-captions1.vtt').exists())
  self.con.rollback()
 def test_audio_inheritance_rejects_changed_source_sidecar(self):
  self.reviewed_clip();self.simple_captions()
  path=captions.file_for(self.con,self.project,'wip',self.root);path.write_bytes(path.read_bytes()+b'tamper')
  old,new,_=self.new_audio_edit()
  with self.assertRaises(captions.CaptionError) as error:
   captions.inherit_for_audio_edit(self.con,self.project,'wip',self.root,from_edit_revision=old,to_edit_revision=new)
  self.assertEqual(error.exception.code,'changed_source')
  self.assertIsNone(captions.latest(self.con,self.project,'wip'))
  self.assertFalse((self.root/'reel_workbench'/self.project/f'wip-edit{new}-captions1.vtt').exists())
  self.con.rollback()
