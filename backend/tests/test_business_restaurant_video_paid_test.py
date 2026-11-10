"""Exact one-shot paid video authorisation and no retries; fake provider only."""
import sqlite3,tempfile,unittest
from pathlib import Path
import business_restaurant_video_paid_test as v
import business_marketing_drafts as drafts
import business_runway_video as video
import business_cinematic_video as cinema
from tests.test_business_marketing_drafts import document
class OneShotVideoTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
  drafts.initialise(self.con);video.initialise(self.con);cinema.initialise(self.con);v.initialise(self.con)
  d=document();d['business']='The Cedar Restaurant';d['sourceUrl']='https://www.thecedarrestaurant.co.uk/'
  drafts.save_draft(self.con,{'id':v.APPROVED_DRAFT_ID,'expectedRevision':0,'mutationId':'e'*32,'document':d})
  class Client:
   submits=0;reads=0
   def balance(self):return 875
   def submit_text_video(self,p):
    self.submits+=1
    assert p['model']=='gen4.5' and p['ratio']=='720:1280' and p['duration']==5
    assert 'promptImage' not in p
    return {'id':'abcdefab-1234-4abc-8abc-1234567890ab'}
   def task(self,task):
    self.reads+=1
    return {'id':task,'status':'RUNNING'}
  self.client=Client()
  from tests.business_scene_fixture import seed
  seed(self.con,v.APPROVED_DRAFT_ID,{'model':v.MODEL,'duration':v.DURATION,'ratio':v.RATIO,'promptText':v.PROMPT},v.CREDITS)
 def send(self,cap=60,auth=v.AUTHORIZATION):
  return v.submit(self.con,v.APPROVED_DRAFT_ID,approval=auth,max_credits=cap,root=self.root,client=self.client)
 def test_single_submission_and_replayed_id_do_not_charge_twice(self):
  first=self.send();again=self.send()
  self.assertEqual(first['id'],again['id'])
  self.assertEqual(self.client.submits,1)
  self.assertEqual(first['creditsReserved'],60)
  self.assertFalse(first['additionalSpendAllowed']);self.assertFalse(first['published'])
  state=v.refresh(self.con,first['id'],self.root,client=self.client)
  self.assertEqual(state['status'],'running')
  self.assertEqual(self.client.reads,1)
 def test_bad_authorization_or_cap_blocks_before_vendor(self):
  for amount,auth in [(59,v.AUTHORIZATION),(250,v.AUTHORIZATION),(60,'wrong_token')]:
   with self.assertRaises(v.SingleVideoTestError):self.send(cap=amount,auth=auth)
  self.assertEqual(self.client.submits,0)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_paid_video_tests').fetchone()[0],0)
 def test_timeouts_not_retried(self):
  def lost(payload):self.client.submits+=1;raise TimeoutError('provider ack lost')
  self.client.submit_text_video=lost
  one=self.send();two=self.send()
  self.assertEqual(one['status'],'submission_unknown')
  self.assertEqual(one['id'],two['id']);self.assertEqual(self.client.submits,1)
 def test_explicit_400_rejection_recorded_not_blind_retry(self):
  from business_runway import RunwayError
  def rejected(payload):self.client.submits+=1;raise RunwayError('Invalid request','provider_http_400',502)
  self.client.submit_text_video=rejected
  one=self.send();two=self.send()
  self.assertEqual(one['status'],'rejected');self.assertEqual(one['errorCode'],'provider_http_400')
  self.assertEqual(self.client.submits,1);self.assertEqual(one['id'],two['id'])
 def test_campaign_changed_blocked(self):
  edited=document();edited['business']='A different company';edited['sourceUrl']='https://www.thecedarrestaurant.co.uk/'
  drafts.save_draft(self.con,{'id':v.APPROVED_DRAFT_ID,'expectedRevision':1,'mutationId':'f'*32,'document':edited})
  with self.assertRaises(v.SingleVideoTestError):self.send()
  self.assertEqual(self.client.submits,0)
 def test_other_video_ledger_blocks(self):
  self.con.execute('INSERT INTO runway_cinematic_shots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
   ('b'*32,v.APPROVED_DRAFT_ID,1,'concierge_arrival','f'*64,'submission_unknown',None,'{}',96,None,None,'old',1,2))
  with self.assertRaises(v.SingleVideoTestError):self.send()
  self.assertEqual(self.client.submits,0)
 def test_other_campaign_blocked(self):
  with self.assertRaises(v.SingleVideoTestError):
   v.submit(self.con,'b'*32,approval=v.AUTHORIZATION,max_credits=60,root=self.root,client=self.client)
