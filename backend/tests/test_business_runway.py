"""Runway adapter and no-duplicate-spend tests. These never call a paid API."""
import importlib.util,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import business_marketing_drafts as drafts
from tests.test_business_marketing_drafts import document

class RunwayTests(unittest.TestCase):
 def setUp(self):
  spec=importlib.util.find_spec('business_runway')
  self.assertIsNotNone(spec,'The backend Runway adapter must exist')
  self.api=__import__('business_runway')
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
  drafts.initialise(self.con);self.api.initialise(self.con)
  doc=document();doc['creatives'][0]['brief']='Create a premium editorial fictional image with realistic materials and room for typography.'
  drafts.save_draft(self.con,{'id':'1'*32,'mutationId':'2'*32,'expectedRevision':0,'document':doc})
  class Client:
   submissions=0
   def balance(self):return 1000
   def submit_image(self,payload):
    self.submissions+=1
    return {'id':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'}
  self.client=Client();self.payload={'draftId':'1'*32,'creativeId':'creative-1','expectedRevision':1}
  from tests.business_scene_fixture import seed_image
  seed_image(self.con,'1'*32)
 def test_replayed_request_submits_only_one_paid_task(self):
  first=self.api.start_job(self.con,self.payload,client=self.client,max_credits=20)
  second=self.api.start_job(self.con,self.payload,client=self.client,max_credits=20)
  self.assertEqual(first['id'],second['id']);self.assertEqual(self.client.submissions,1)
  self.assertEqual(first['reservedCredits'],20)
 def test_timeout_has_unknown_outcome_and_never_resubmits(self):
  def timeout(payload):self.client.submissions+=1;raise TimeoutError('connection interrupted')
  self.client.submit_image=timeout
  first=self.api.start_job(self.con,self.payload,client=self.client,max_credits=20)
  self.assertEqual(first['status'],'submission_unknown')
  second=self.api.start_job(self.con,self.payload,client=self.client,max_credits=20)
  self.assertEqual(second['id'],first['id']);self.assertEqual(self.client.submissions,1)
 def test_disabled_or_insufficient_budget_never_submits(self):
  for cap in (0,19):
   with self.assertRaises(self.api.RunwayError):self.api.start_job(self.con,self.payload,client=self.client,max_credits=cap)
  self.assertEqual(self.client.submissions,0)
 def test_stale_document_and_client_model_override_are_rejected(self):
  with self.assertRaises(self.api.RunwayError):self.api.start_job(self.con,{**self.payload,'expectedRevision':0},client=self.client,max_credits=20)
  with self.assertRaises(self.api.RunwayError):self.api.start_job(self.con,{**self.payload,'model':'expensive-unknown'},client=self.client,max_credits=20)
  self.assertEqual(self.client.submissions,0)
 def test_balance_does_not_leak_credentials_or_create_images(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'.env.runway.local';p.write_text('RUNWAY_API_KEY="test-secret-not-real"\n');p.chmod(0o600)
   self.assertEqual(self.api.load_key(p,environ={}), 'test-secret-not-real')
   p.chmod(0o644)
   with self.assertRaises(self.api.RunwayError):self.api.load_key(p,environ={})
 def test_payload_is_fixed_single_image_with_native_four_by_five_output(self):
  self.api.start_job(self.con,self.payload,client=self.client,max_credits=20)
  row=self.con.execute('SELECT request_json FROM runway_image_jobs').fetchone()
  import json
  request=json.loads(row[0]);self.assertEqual(request['outputCount'],1)
  self.assertEqual(request['ratio'],'1536:1920');self.assertEqual(request['quality'],'high')

 def test_completed_job_reports_if_saved_brief_has_changed(self):
  first=self.api.start_job(self.con,self.payload,client=self.client,max_credits=20)
  self.con.execute("UPDATE runway_image_jobs SET status='completed',result_json='{}' WHERE id=?",(first['id'],));self.con.commit()
  saved=drafts.read_draft(self.con,self.payload['draftId']);doc=saved['document']
  doc['creatives'][0]['brief']+=' The new brief requires a different composition.'
  drafts.save_draft(self.con,{'id':self.payload['draftId'],'mutationId':'3'*32,'expectedRevision':1,'document':doc})
  result=self.api.refresh_job(self.con,first['id'],Path('/tmp/not-used'),client=self.client)
  self.assertFalse(result['currentBrief'])
  self.assertFalse(result['approved'])
 def test_changed_brief_cannot_bypass_the_no_paid_retry_rule(self):
  self.api.start_job(self.con,self.payload,client=self.client,max_credits=40)
  saved=drafts.read_draft(self.con,self.payload['draftId']);doc=saved['document']
  doc['creatives'][0]['brief']+=' Use different lighting.'
  drafts.save_draft(self.con,{'id':self.payload['draftId'],'mutationId':'4'*32,'expectedRevision':1,'document':doc})
  with self.assertRaises(self.api.RunwayError) as caught:
   self.api.start_job(self.con,{**self.payload,'expectedRevision':2},client=self.client,max_credits=40)
  self.assertEqual(caught.exception.code,'paid_retry_disabled')
  self.assertEqual(self.client.submissions,1)

if __name__=='__main__':unittest.main()
