"""Real shot-based video must be commercial, clearly moving, spend-capped."""
import sqlite3,tempfile,unittest
from pathlib import Path
import business_cinematic_video as cinema
import business_marketing_drafts as drafts
from tests.test_business_marketing_drafts import document
class CinematicTests(unittest.TestCase):
 def setUp(self):
  folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
  drafts.initialise(self.db);cinema.initialise(self.db)
  doc=document();doc['business']='Encore VIP';doc['observedFacts']=['Encore VIP','Bespoke experiences, private aviation, exclusive events, VIP concierge and transfer coordination']
  drafts.save_draft(self.db,{'id':'a'*32,'mutationId':'e'*32,'expectedRevision':0,'document':doc})
  class Fake:
   calls=0
   def balance(self):return 800
   def submit_text_video(self,payload):
    self.calls+=1
    assert payload['model']=='gen4.5' and payload['duration']==8
    assert payload['ratio']=='720:1280'
    assert 'promptImage' not in payload
    assert 'moves' in payload['promptText'].lower()
    assert 'no text' in payload['promptText'].lower()
    return {'id':'abcdefab-1234-4abc-8abc-1234567890ab'}
  self.client=Fake()
  from tests.business_scene_fixture import seed_cinema
  for key in ('concierge_arrival','concierge_transfers'):seed_cinema(self.db,'a'*32,key)
 def test_durable_single_paid_attempt_and_unchanged_replay(self):
  req=cinema.SHOTS['concierge_arrival']
  one=cinema.submit(self.db,'a'*32,1,'concierge_arrival',root=self.root,client=self.client,max_credits=96)
  two=cinema.submit(self.db,'a'*32,1,'concierge_arrival',root=self.root,client=self.client,max_credits=96)
  self.assertEqual(one['id'],two['id']);self.assertEqual(one['creditsReserved'],96);self.assertEqual(self.client.calls,1)
  self.assertFalse(one['approvedForUse'])
 def test_cap_below_cost_prevents_any_api_call(self):
  with self.assertRaises(cinema.CinematicError):
   cinema.submit(self.db,'a'*32,1,'concierge_arrival',root=self.root,client=self.client,max_credits=80)
  self.assertEqual(self.client.calls,0)
 def test_stale_campaign_and_incorrect_sector_rejected(self):
  with self.assertRaises(cinema.CinematicError):cinema.submit(self.db,'a'*32,2,'concierge_arrival',root=self.root,client=self.client,max_credits=96)
  with self.assertRaises(cinema.CinematicError):cinema.submit(self.db,'a'*32,1,'roofing_issue',root=self.root,client=self.client,max_credits=96)
  self.assertEqual(self.client.calls,0)
 def test_second_paid_shot_must_be_separately_bounded(self):
  cinema.submit(self.db,'a'*32,1,'concierge_arrival',root=self.root,client=self.client,max_credits=192)
  with self.assertRaises(cinema.CinematicError):
   cinema.submit(self.db,'a'*32,1,'concierge_transfers',root=self.root,client=self.client,max_credits=96)
  self.assertEqual(self.client.calls,1)
 def test_poll_timeout_preserves_original_provider_job_and_unknown_cost(self):
  first=cinema.submit(self.db,'a'*32,1,'concierge_arrival',root=self.root,client=self.client,max_credits=96)
  class Unreachable:
   def task(self,id):raise TimeoutError('Read timed out; job may be processing')
  result=cinema.refresh(self.db,first['id'],self.root,client=Unreachable())
  self.assertEqual(result['status'],'queued')
  self.assertEqual(result['id'],first['id'])
  self.assertIsNone(result['creditsCharged'])
  self.assertTrue(result['errorCode'].startswith('poll_unavailable'))
  self.assertFalse(result['retryAllowed'])
 def test_submission_timeout_never_resends(self):
  def failure(payload):self.client.calls+=1;raise TimeoutError('lost provider acknowledgement')
  self.client.submit_text_video=failure
  first=cinema.submit(self.db,'a'*32,1,'concierge_arrival',root=self.root,client=self.client,max_credits=96)
  second=cinema.submit(self.db,'a'*32,1,'concierge_arrival',root=self.root,client=self.client,max_credits=96)
  self.assertEqual(first['status'],'submission_unknown')
  self.assertEqual(first['id'],second['id']);self.assertEqual(self.client.calls,1)
 def test_explicit_http_rejection_is_recorded_not_hidden_as_timeout(self):
  from business_runway import RunwayError
  def rejected(payload):self.client.calls+=1;raise RunwayError('Provider rejected invalid settings','provider_http_400',502)
  self.client.submit_text_video=rejected
  got=cinema.submit(self.db,'a'*32,1,'concierge_arrival',root=self.root,client=self.client,max_credits=96)
  self.assertEqual(got['status'],'rejected')
  self.assertEqual(got['errorCode'],'provider_http_400')
  again=cinema.submit(self.db,'a'*32,1,'concierge_arrival',root=self.root,client=self.client,max_credits=96)
  self.assertEqual(got['id'],again['id']);self.assertEqual(self.client.calls,1)
