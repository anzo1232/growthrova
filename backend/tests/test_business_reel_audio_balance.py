"""FFmpeg-only voice/music ducking from separately rights-attested local files."""
import array,hashlib,math,subprocess,sys,unittest,wave
from unittest.mock import patch
from tests import test_business_reel_workbench as fixture_module
import business_reel_workbench as reel

class SoundtrackTests(unittest.TestCase):
 def setUp(self):
  self.fixt=fixture_module.ReelReliabilityTests('test_idempotent_project_and_original_paid_job_receipts_are_preserved')
  self.fixt.setUp();self.addCleanup(self.fixt.doCleanups)
  self.root=self.fixt.root;self.con=self.fixt.c;self.project=self.fixt.project
  for i,slot in enumerate(('hook','craft','experience')):
   job,_=self.fixt.provider_fixture(slot,i)
   reel.attach_verified_job(self.con,self.project,slot,job,self.root)
   self.fixt.accept_fixture_shot(slot,'Original QA footage reviewed for movement and technical integrity','director_team')
  reel.prepare_edits(self.con,self.project,self.root)
 def sound(self,name,frequency,length=12,*,amplitude=.2,active=None):
  """Owned PCM test tone, with optional silence around a speech surrogate."""
  output=self.root/(name+'.wav');rate=44100
  samples=array.array('h',(round(32767*amplitude*math.sin(2*math.pi*frequency*i/rate))
    if active is None or active[0]<=i/rate<active[1] else 0 for i in range(round(length*rate))))
  if sys.byteorder!='little':samples.byteswap()
  with wave.open(str(output),'wb') as wav:
   wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(samples.tobytes())
  return output
 def component(self,samples,frequency,start,end):
  """Measure one independent tone in a real decoded mix, not its total volume."""
  window=samples[round(start*44100):round(end*44100)]
  self.assertEqual(len(window),round((end-start)*44100))
  real=sum(sample*math.cos(2*math.pi*frequency*i/44100) for i,sample in enumerate(window))
  imag=sum(sample*math.sin(2*math.pi*frequency*i/44100) for i,sample in enumerate(window))
  return 2*math.hypot(real,imag)/len(window)/32768
 def test_voice_ducking_yields_audible_mix_with_immutable_versions(self):
  old=reel.preview_file(self.con,self.project,'a',self.root)
  oldhash=hashlib.sha256(old.read_bytes()).hexdigest()
  music=self.sound('synthetic-owned-music',330);voice=self.sound('synthetic-owner-voice',760)
  music_rights='Test signal is generated locally; use authorised only for noncommercial internal QA.'
  voice_rights='Synthetic voice tone generated locally for owned testing.'
  mixed=reel.attach_authorised_audio(self.con,self.project,'a',self.root,music,
   rights_attestation=music_rights,voiceover_path=voice,
   voice_rights_attestation=voice_rights,owner_confirmed=True)
  self.assertEqual(next(x for x in mixed['edits'] if x['variant']=='a')['revision'],2)
  self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),oldhash)
  new=reel.preview_file(self.con,self.project,'a',self.root)
  self.assertNotEqual(old,new)
  meta=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type',
   '-of','default=nk=1:nw=1',str(new)],capture_output=True,text=True,check=True,timeout=10)
  self.assertIn('audio',meta.stdout)
  rows=self.con.execute('SELECT * FROM business_reel_audio_evidence').fetchall()
  self.assertEqual(len(rows),1)
  evidence=rows[0]
  self.assertEqual(evidence['original_sha256'],oldhash)
  self.assertEqual(evidence['track_sha256'],hashlib.sha256(music.read_bytes()).hexdigest())
  self.assertEqual(evidence['voice_sha256'],hashlib.sha256(voice.read_bytes()).hexdigest())
  self.assertEqual(evidence['rights_attestation'],music_rights)
  self.assertEqual(evidence['voice_rights_attestation'],voice_rights)
  self.assertEqual(reel.read(self.con,self.project)['customerAllowanceConsumed'],0)
 def test_music_ducks_during_speech_and_recovers_in_silence(self):
  # Distinct frequencies let us isolate music in the actual compressed AAC mix.
  # The 760 Hz burst is a synthetic sidechain trigger, not a real spoken voice.
  music=self.sound('synthetic-continuous-music',330,amplitude=.32)
  voice=self.sound('synthetic-speech-surrogate',760,amplitude=.6,active=(2,4.2))
  reel.attach_authorised_audio(self.con,self.project,'a',self.root,music,
   rights_attestation='Self-created synthetic music tone cleared for local signal-processing QA only.',
   voiceover_path=voice,voice_rights_attestation='Self-created burst tone used as a speech surrogate in local QA only.',
   owner_confirmed=True)
  new=reel.preview_file(self.con,self.project,'a',self.root)
  decoded=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(new),
   '-map','0:a:0','-ac','1','-ar','44100','-f','s16le','-c:a','pcm_s16le','pipe:1'],
   capture_output=True,check=True,timeout=20)
  samples=array.array('h');samples.frombytes(decoded.stdout)
  if sys.byteorder!='little':samples.byteswap()
  before=self.component(samples,330,.7,1.5)
  during=self.component(samples,330,2.8,3.6)
  after=self.component(samples,330,5.2,6)
  speech=self.component(samples,760,2.8,3.6)
  silent_voice=self.component(samples,760,5.2,6)
  self.music_levels={'before':before,'during':during,'after':after,
    'speech':speech,'silent_voice':silent_voice}
  self.assertGreater(before,.015,self.music_levels)
  self.assertLess(during,before*.5,self.music_levels)
  self.assertGreater(after,before*.8,self.music_levels)
  self.assertLess(after,before*1.2,self.music_levels)
  self.assertGreater(speech,during*5,self.music_levels)
  self.assertLess(silent_voice,speech*.02,self.music_levels)
  self.assertEqual(reel.read(self.con,self.project)['customerAllowanceConsumed'],0)
 def test_separate_bounded_speech_rights_required(self):
  music=self.sound('synthetic-music',330);voice=self.sound('synthetic-voice',760)
  for rights in (None,'Synthetic voice rights assertion. '*20):
   with self.subTest(rights_length=0 if rights is None else len(rights)):
    with self.assertRaises(reel.ReelError):
     reel.attach_authorised_audio(self.con,self.project,'a',self.root,music,
      rights_attestation='I own this synthetic music file used only for internal tests.',
      voiceover_path=voice,voice_rights_attestation=rights,owner_confirmed=True)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_audio_evidence').fetchone()[0],0)
 def test_changed_music_or_voice_during_encode_leaves_no_receipt_or_new_edit(self):
  real_run=subprocess.run
  before_edits=self.con.execute('SELECT COUNT(*) FROM business_reel_edits').fetchone()[0]
  for changed in ('music','voice'):
   with self.subTest(changed=changed):
    music=self.sound('synthetic-music-'+changed,330)
    voice=self.sound('synthetic-voice-'+changed,760)
    target=music if changed=='music' else voice
    def change_after_encode(command,*args,**kwargs):
     result=real_run(command,*args,**kwargs)
     if command[0]=='ffmpeg' and str(voice) in command:
      target.write_bytes(target.read_bytes()+b'changed-after-source-approval')
     return result
    with patch.object(reel.subprocess,'run',side_effect=change_after_encode):
     with self.assertRaises(reel.ReelError) as raised:
      reel.attach_authorised_audio(self.con,self.project,'a',self.root,music,
       rights_attestation='Synthetic music authorised solely for this local immutability test.',
       voiceover_path=voice,voice_rights_attestation='Synthetic speech surrogate authorised solely for this local test.',
       owner_confirmed=True)
    self.assertEqual(raised.exception.code,'audio_source_changed')
    self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_audio_evidence').fetchone()[0],0)
    self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_edits').fetchone()[0],before_edits)
    folder=self.root/'reel_workbench'/self.project
    self.assertFalse((folder/'a-2.mp4').exists())
    self.assertFalse((folder/'.a-2-pending.mp4').exists())

 def save_fixture_caption(self):
  import business_reel_captions as captions
  return captions.save(self.con,self.project,'a',self.root,
   cues=[{'start':0,'end':2,'text':'Locally verified fixture hook'}],
   source='owner_written_text',style={'typeface':'sans','weight':'bold','placement':'bottom_safe'},
   expected_edit_revision=1,expected_caption_revision=0,owner_confirmed=True)

 def test_first_caption_saved_during_mix_is_carried_to_audio_revision(self):
  import business_reel_captions as captions
  music=self.sound('synthetic-music-concurrent-caption',330)
  real_run=subprocess.run
  def save_after_encode(command,*args,**kwargs):
   result=real_run(command,*args,**kwargs)
   if command[0]=='ffmpeg' and str(music) in command:self.save_fixture_caption()
   return result
  with patch.object(reel.subprocess,'run',side_effect=save_after_encode):
   reel.attach_authorised_audio(self.con,self.project,'a',self.root,music,
    rights_attestation='Synthetic music cleared for local caption lifecycle verification only.',
    owner_confirmed=True)
  current=captions.latest(self.con,self.project,'a')
  self.assertIsNotNone(current)
  self.assertEqual(current['editRevision'],2)
  self.assertTrue(current['inheritedFrom'])
  self.assertEqual(current['cues'][0]['text'],'Locally verified fixture hook')
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_caption_tracks').fetchone()[0],2)

 def test_failed_audio_commit_removes_only_new_video_and_inherited_sidecar(self):
  import sqlite3
  self.save_fixture_caption()
  folder=self.root/'reel_workbench'/self.project
  original=(folder/'a-edit1-captions1.vtt').read_bytes()
  music=self.sound('synthetic-music-commit-failure',330)
  connection=self.con
  class CommitFailure:
   def __getattr__(self,name):return getattr(connection,name)
   def commit(self):raise sqlite3.OperationalError('Synthetic failed audio commit')
  with self.assertRaises(sqlite3.OperationalError):
   reel.attach_authorised_audio(CommitFailure(),self.project,'a',self.root,music,
    rights_attestation='Synthetic music cleared for local transaction cleanup verification only.',
    owner_confirmed=True)
  self.assertFalse((folder/'a-2.mp4').exists())
  self.assertFalse((folder/'a-edit2-captions1.vtt').exists())
  self.assertEqual((folder/'a-edit1-captions1.vtt').read_bytes(),original)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_caption_tracks').fetchone()[0],1)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_audio_evidence').fetchone()[0],0)
