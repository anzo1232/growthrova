"""Source-specific provider handoff: all external clients are fakes, no Runway spend."""
import json,sqlite3,unittest,uuid,os
from unittest.mock import patch
import business_marketing_drafts as drafts
import business_cinematic_video as cinematic
import business_reel_workbench as reel
import business_reel_provider_bridge as bridge
from tests.test_business_marketing_drafts import document

class BridgeTests(unittest.TestCase):
 def setUp(self):
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
  self.addCleanup(self.con.close)
  drafts.initialise(self.con);cinematic.initialise(self.con);reel.initialise(self.con);bridge.initialise(self.con)
  self.did=uuid.uuid4().hex
  d=document();d['business']='Berenjak Persian Restaurant'
  d['observedFacts']=['Authentic Persian koobideh kabab over the mangal, sangak bread and Tehran-inspired hospitality']
  d['editorialShortlist']={'status':'three_directions_ready_for_asset_intake','sector':'restaurant',
   'candidates':[
    {'id':'craft','role':'Food craft','media':'Reel','format':'9:16','direction':'Close-up chargrill',
      'hook':'The mangal: how Berenjak grills koobideh',
      'evidence':{'kind':'method','label':'official restaurant story','quote':'Koobideh minced lamb is grilled on a long skewer over the traditional mangal.'}},
    {'id':'discovery','role':'Bread discovery','media':'Carousel','format':'4:5','direction':'Stone-baked bread',
      'hook':'Sangak: bread baked on stones',
      'evidence':{'kind':'bread','label':'official food page','quote':'Sangak is baked on hot stones in a traditional Persian oven.'}},
    {'id':'heritage','role':'Restaurant atmosphere','media':'Image','format':'4:5','direction':'Hospitality',
      'hook':"Inspired by Tehran's kabab houses",
      'evidence':{'kind':'heritage','label':'official restaurant story','quote':'Tehran kababi traditions inspire the restaurant hospitality and shared table.'}}]}
  drafts.save_draft(self.con,{'id':self.did,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':d})
  self.project=reel.create(self.con,self.did,1)['id']
  class Fake:
   calls=0
   def balance(self):return 800
   def submit_text_video(self,params):
    self.calls+=1
    assert params['model']=='gen4.5' and params['duration']==8
    assert params['ratio']=='720:1280'
    assert 'koobideh' in params['promptText'].lower()
    return {'id':str(uuid.uuid4())}
  self.fake=Fake()
  from tests.business_scene_fixture import seed_reel
  for slot in ('hook','craft','experience'):seed_reel(self.con,self.project,slot)
 def test_quote_does_not_touch_provider_and_uses_actual_specific_scene(self):
  q=bridge.quote(self.con,self.project,'hook')
  self.assertEqual(q['estimatedCredits'],96)
  self.assertEqual(q['model'],'gen4.5')
  self.assertEqual(q['ratio'],'720:1280')
  self.assertIn('koobideh',q['promptText'].lower())
  self.assertIn('mangal',q['promptText'].lower())
  self.assertFalse(q['spendAuthorisedNow'])
  self.assertFalse(q['modelGenerationStarted'])
  self.assertEqual(self.fake.calls,0)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0],0)
  with self.assertRaises(bridge.BridgeError):bridge.quote(self.con,self.project,'payoff')
 def test_no_approval_never_submits_even_if_client_available(self):
  with patch.dict(os.environ,{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'96'}):
   with self.assertRaises(bridge.BridgeError):
    bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
  self.assertEqual(self.fake.calls,0)
  with self.assertRaises(bridge.BridgeError):
   bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake)
 def test_exact_approval_persists_but_cap_and_disabled_flag_prevent_spend(self):
  q=bridge.quote(self.con,self.project,'hook')
  with self.assertRaises(bridge.BridgeError):
   bridge.record_exact_approval(self.con,self.project,'hook','wrong',96,'owner_explicit_approved')
  with self.assertRaises(bridge.BridgeError):
   bridge.record_exact_approval(self.con,self.project,'hook',q['fingerprint'],288,'owner_explicit_approved')
  approved=bridge.record_exact_approval(self.con,self.project,'hook',q['fingerprint'],96,'owner_explicit_approved')
  self.assertEqual(approved['max_credits'],96)
  self.assertEqual(approved['id'],bridge.record_exact_approval(self.con,self.project,'hook',q['fingerprint'],96,'owner_explicit_approved')['id'])
  with patch.dict(os.environ,{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'0'}):
   with self.assertRaises(bridge.BridgeError):
    bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
  self.assertEqual(self.fake.calls,0)
 def test_mocked_approved_submit_records_one_original_provider_job_and_no_retry(self):
  q=bridge.quote(self.con,self.project,'hook')
  bridge.record_exact_approval(self.con,self.project,'hook',q['fingerprint'],96,'explicit_separate_owner_message')
  with patch.dict(os.environ,{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'96'}):
   one=bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
   two=bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
  self.assertEqual(one['id'],two['id'])
  self.assertEqual(one['status'],'queued')
  self.assertEqual(self.fake.calls,1)
  self.assertEqual(one['creditsReserved'],96)
  self.assertIsNone(one['creditsCharged'])
  self.assertEqual(reel.read(self.con,self.project)['customerAllowanceConsumed'],0)
 def test_mocked_lost_acknowledgment_remains_unknown_without_second_submit(self):
  q=bridge.quote(self.con,self.project,'hook')
  bridge.record_exact_approval(self.con,self.project,'hook',q['fingerprint'],96,'explicit_separate_owner_message')
  def unknown(_):
   self.fake.calls+=1
   raise TimeoutError('Did not get the task ID')
  self.fake.submit_text_video=unknown
  with patch.dict(os.environ,{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'96'}):
   one=bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
   two=bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
  self.assertEqual(one['status'],'submission_unknown')
  self.assertEqual(one['id'],two['id'])
  self.assertEqual(self.fake.calls,1)
  self.assertEqual(reel.read(self.con,self.project)['providerSubmissionUnknownJobs'],1)
 def test_existing_provider_task_can_be_polled_without_new_paid_attempt(self):
  q=bridge.quote(self.con,self.project,'hook')
  bridge.record_exact_approval(self.con,self.project,'hook',q['fingerprint'],96,'owner_explicit_approval')
  with patch.dict(os.environ,{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'96'}):
   first=bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
  class Running:
   count=0
   def task(self,task_id):
    self.count+=1
    return {'id':task_id,'status':'RUNNING'}
  client=Running()
  result=bridge.reconcile_existing(self.con,self.project,'hook','/tmp/isolated-mock-folder',client=client)
  self.assertEqual(result['providerJob']['id'],first['id'])
  self.assertEqual(result['providerJob']['status'],'running')
  self.assertFalse(result['newPaidAttempt'])
  self.assertEqual(result['project']['slots'][0]['productionStatus'],'provider_running')
  self.assertEqual(result['customerAllowanceCharged'],0)
  self.assertEqual(self.fake.calls,1)
  self.assertEqual(client.count,1)
 def test_unknown_submission_refuses_poll_or_retry_without_original_task_id(self):
  q=bridge.quote(self.con,self.project,'hook')
  bridge.record_exact_approval(self.con,self.project,'hook',q['fingerprint'],96,'owner_explicit_approval')
  def unknown(_):
   self.fake.calls+=1
   raise TimeoutError('Acknowledgement lost')
  self.fake.submit_text_video=unknown
  with patch.dict(os.environ,{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'96'}):
   bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
  with self.assertRaises(bridge.BridgeError):
   bridge.reconcile_existing(self.con,self.project,'hook','/tmp/isolated-mock-folder')
  self.assertEqual(self.fake.calls,1)
  self.assertEqual(reel.read(self.con,self.project)['slots'][0]['productionStatus'],'reconcile_required')
 def test_revised_campaign_refuses_old_quote(self):
  q=bridge.quote(self.con,self.project,'hook')
  bridge.record_exact_approval(self.con,self.project,'hook',q['fingerprint'],96,'explicit_separate_owner_message')
  saved=drafts.read_draft(self.con,self.did)
  changed={**saved['document'],'name':'New Berenjak campaign revision'}
  drafts.save_draft(self.con,{'id':self.did,'mutationId':uuid.uuid4().hex,'expectedRevision':1,'document':changed})
  with self.assertRaises(bridge.BridgeError):bridge.quote(self.con,self.project,'hook')
  with patch.dict(os.environ,{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'96'}):
   with self.assertRaises(bridge.BridgeError):
    bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
  self.assertEqual(self.fake.calls,0)

 def test_another_slot_reserved_during_balance_check_cannot_exceed_cap(self):
  for slot in ('hook','craft'):
   prepared=bridge.quote(self.con,self.project,slot)
   bridge.record_exact_approval(self.con,self.project,slot,prepared['fingerprint'],96,'explicit_separate_owner_message')
  class Companion:
   calls=0
   def balance(self):return 800
   def submit_text_video(self,params):
    self.calls+=1
    return {'id':str(uuid.uuid4())}
  companion=Companion()
  def balance_after_other_slot_wins():
   bridge.submit_preapproved(self.con,self.project,'craft',client=companion,allow_paid=True)
   return 800
  self.fake.balance=balance_after_other_slot_wins
  with patch.dict(os.environ,{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'96'}):
   with self.assertRaises(bridge.BridgeError) as denied:
    bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
  self.assertEqual(denied.exception.code,'budget_exceeded')
  self.assertEqual(self.fake.calls,0)
  self.assertEqual(companion.calls,1)
  self.assertEqual(self.con.execute('SELECT SUM(reserved_credits) FROM runway_cinematic_shots').fetchone()[0],96)
  self.assertFalse(self.con.in_transaction)

 def test_two_distinct_approved_slots_fit_an_explicit_two_shot_cap(self):
  for slot in ('hook','craft'):
   prepared=bridge.quote(self.con,self.project,slot)
   bridge.record_exact_approval(self.con,self.project,slot,prepared['fingerprint'],96,'explicit_separate_owner_message')
  submitted=[]
  def receive(params):
   submitted.append(params)
   return {'id':str(uuid.uuid4())}
  self.fake.submit_text_video=receive
  with patch.dict(os.environ,{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'192'}):
   first=bridge.submit_preapproved(self.con,self.project,'hook',client=self.fake,allow_paid=True)
   second=bridge.submit_preapproved(self.con,self.project,'craft',client=self.fake,allow_paid=True)
  self.assertNotEqual(first['id'],second['id'])
  self.assertEqual(len(submitted),2)
  self.assertEqual(self.con.execute('SELECT SUM(reserved_credits) FROM runway_cinematic_shots').fetchone()[0],192)
