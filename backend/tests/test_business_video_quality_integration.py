"""Fake provider success is NOT creative success: frozen output is rejected without paid retries."""
import hashlib,json,sqlite3,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import business_marketing_drafts as drafts
import business_runway_video as first
import business_cinematic_video as cinema
from tests.test_business_marketing_drafts import document

class FrozenPaidVideoIntegrationTests(unittest.TestCase):
 def setUp(self):
  folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
  drafts.initialise(self.db);first.initialise(self.db);cinema.initialise(self.db)
  d=document();d['business']='Encore VIP';d['observedFacts']=['Encore VIP','Private aviation, VIP concierge, exclusive events']
  drafts.save_draft(self.db,{'id':'a'*32,'mutationId':'b'*32,'expectedRevision':0,'document':d})
  self.still=self.root/'still.png';Image.new('RGB',(768,1280),(140,90,60)).save(self.still)
  from tests.business_scene_fixture import seed_video,seed_cinema
  seed_video(self.db,'a'*32,self.still);seed_cinema(self.db,'a'*32,'concierge_arrival')
 def fake_store(self,url,target,*,expected_duration=5):
  target.parent.mkdir(parents=True,exist_ok=True)
  subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i','color=c=gray:size=720x1280:rate=10',
    '-t',str(expected_duration),'-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(target)],
    timeout=35,check=True,capture_output=True)
  data=target.read_bytes()
  return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'duration':expected_duration}
 def test_legacy_video_frozen_result_rejected_charged_and_not_fetched_twice(self):
  class Client:
   reads=0
   def balance(self):return 900
   def submit_video(self,payload):return {'id':'abcdabcd-1234-4abc-8abc-1234567890ab'}
   def task(self,jid):
    self.reads+=1
    return {'id':jid,'status':'SUCCEEDED','output':['https://sample.test/s.mp4'],'cost':{'credits':25}}
  client=Client()
  made=first.start_job(self.db,'a'*32,1,self.still,self.root,client=client,max_credits=25)
  with patch.object(first,'_store_video',side_effect=self.fake_store):
   status=first.refresh_job(self.db,made['id'],self.root,client=client)
   again=first.refresh_job(self.db,made['id'],self.root,client=client)
  self.assertEqual(status['status'],'rejected_quality')
  self.assertEqual(status['actualCredits'],25)
  self.assertFalse(status['publishApproved']);self.assertFalse(status['retryAllowed'])
  self.assertEqual(client.reads,1)
  self.assertEqual(again['status'],'rejected_quality')
  self.assertEqual(status['asset']['motionReview']['technicalMotionPass'],False)
 def test_cinematic_frozen_result_rejected_preserves_cost(self):
  class Client:
   reads=0
   def balance(self):return 900
   def submit_text_video(self,payload):return {'id':'abcdabcd-1234-4abc-8abc-1234567890ab'}
   def task(self,jid):
    self.reads+=1
    return {'id':jid,'status':'SUCCEEDED','output':['https://sample.test/s.mp4'],'cost':{'credits':96}}
  client=Client()
  made=cinema.submit(self.db,'a'*32,1,'concierge_arrival',root=self.root,client=client,max_credits=96)
  with patch.object(cinema.vid,'_store_video',side_effect=self.fake_store):
   status=cinema.refresh(self.db,made['id'],self.root,client=client)
   again=cinema.refresh(self.db,made['id'],self.root,client=client)
  self.assertEqual(status['status'],'rejected_quality')
  self.assertEqual(status['creditsCharged'],96)
  self.assertEqual(status['errorCode'],'insufficient_motion')
  self.assertFalse(status['approvedForUse']);self.assertFalse(status['retryAllowed'])
  self.assertEqual(client.reads,1);self.assertEqual(again['status'],'rejected_quality')
