"""Paid video jobs must be safe, reproducible and never double-submit."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from PIL import Image
import business_marketing_drafts as drafts
from tests.test_business_marketing_drafts import document
import business_runway_video as video

DID='a'*32
class VideoJobTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
  drafts.initialise(self.con);video.initialise(self.con)
  doc=document();drafts.save_draft(self.con,{'id':DID,'expectedRevision':0,'mutationId':'b'*32,'document':doc})
  self.image=self.root/'test-hero.png';Image.new('RGB',(768,960),(75,99,113)).save(self.image)
  class Client:
   count=0
   def balance(self):return 900
   def submit_video(self,request):
    self.count+=1
    assert request['model']=='gen4_turbo'
    assert request['duration']==5 and request['ratio']=='720:1280'
    assert request['promptImage'].startswith('data:image/jpeg;base64,')
    assert len(request['promptText'])<1000
    return {'id':'cccccccc-cccc-4ccc-8ccc-cccccccccccc'}
   def task(self,task_id):return {'id':task_id,'status':'RUNNING'}
  self.client=Client()
  from tests.business_scene_fixture import seed_video
  seed_video(self.con,DID,self.image)
 def test_single_submission_and_replay_no_extra_paid_job(self):
  a=video.start_job(self.con,DID,1,self.image,self.root,client=self.client,max_credits=25)
  b=video.start_job(self.con,DID,1,self.image,self.root,client=self.client,max_credits=25)
  self.assertEqual(a['id'],b['id']);self.assertEqual(self.client.count,1)
  self.assertEqual(a['reservedCredits'],25);self.assertFalse(a['publishApproved'])
 def test_exact_cap_and_source_guard(self):
  for cap in (0,24):
   with self.assertRaises(video.VideoError):video.start_job(self.con,DID,1,self.image,self.root,client=self.client,max_credits=cap)
  with self.assertRaises(video.VideoError):video.start_job(self.con,DID,2,self.image,self.root,client=self.client,max_credits=25)
  with self.assertRaises(video.VideoError):video.start_job(self.con,DID,1,self.root/'absent.png',self.root,client=self.client,max_credits=25)
  self.assertEqual(self.client.count,0)
 def test_lost_provider_submission_never_retries(self):
  def unknown(request):self.client.count+=1;raise TimeoutError('ack lost')
  self.client.submit_video=unknown
  a=video.start_job(self.con,DID,1,self.image,self.root,client=self.client,max_credits=25)
  self.assertEqual(a['status'],'submission_unknown')
  b=video.start_job(self.con,DID,1,self.image,self.root,client=self.client,max_credits=25)
  self.assertEqual(a['id'],b['id']);self.assertEqual(self.client.count,1)
 def test_provider_poll_timeout_is_not_relabelled_bad_creative(self):
  job=video.start_job(self.con,DID,1,self.image,self.root,client=self.client,max_credits=25)
  class TimeoutClient:
   def task(self,identifier):raise TimeoutError('Provider request read timed out')
  updated=video.refresh_job(self.con,job['id'],self.root,client=TimeoutClient())
  self.assertEqual(updated['status'],'queued')
  self.assertIsNone(updated['actualCredits'])
  self.assertTrue(updated['errorCode'].startswith('poll_unavailable'))
  self.assertFalse(updated['retryAllowed'])
 def test_source_version_change_is_not_same_video(self):
  a=video.start_job(self.con,DID,1,self.image,self.root,client=self.client,max_credits=25)
  Image.new('RGB',(768,960),(155,30,45)).save(self.image)
  with self.assertRaises(video.VideoError):video.start_job(self.con,DID,1,self.image,self.root,client=self.client,max_credits=50)
  self.assertEqual(self.client.count,1)
