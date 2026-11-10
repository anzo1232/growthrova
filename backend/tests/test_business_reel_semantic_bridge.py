"""Pure local Gemini wire-format fixtures; no Google calls, spend or uploads."""
import json,sqlite3,subprocess,tempfile,time,uuid,hashlib,unittest
from pathlib import Path
import business_marketing_drafts as drafts
import business_cinematic_video as cinematic
import business_reel_workbench as reel
import business_reel_semantic_bridge as bridge
import business_reel_review_queue as queue
from tests.test_business_marketing_drafts import document

class GeminiBridgeTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory(prefix='clippr-gemini-qa-');self.addCleanup(temp.cleanup);self.root=Path(temp.name)
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
  drafts.initialise(self.c);cinematic.initialise(self.c);reel.initialise(self.c);bridge.initialise(self.c)
  self.did=uuid.uuid4().hex
  doc=document();doc['business']='Berenjak Persian Restaurant'
  doc['observedFacts']=['Koobideh minced lamb grilled over mangal','Sangak baked on hot stones']
  doc['editorialShortlist']={'sector':'restaurant','status':'three_directions_ready_for_asset_intake','candidates':[
   {'id':'method','role':'Food craft','media':'Reel','format':'9:16','direction':'Visible flame',
    'hook':'The mangal: koobideh cooking','evidence':{'kind':'method','label':'source website',
     'quote':'Berenjak describes koobideh lamb skewers over traditional mangal charcoal.'}},
   {'id':'bread','role':'The food story','media':'Carousel','format':'4:5','direction':'Traditional bread',
    'hook':'Sangak bread baked on stones','evidence':{'kind':'bread','label':'source website',
     'quote':'Sangak bread has uneven texture from baking on hot stones.'}},
   {'id':'heritage','role':'Persian atmosphere','media':'Image','format':'4:5','direction':'Diners',
    'hook':'Tehran kababi atmosphere','evidence':{'kind':'heritage','label':'source website',
     'quote':'The Persian kababi atmosphere is inspired by traditional Tehran venues.'}}]}
  drafts.save_draft(self.c,{'id':self.did,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':doc})
  self.project=reel.create(self.c,self.did,1)['id']
 def attach(self):
  jobid=uuid.uuid4().hex
  video=self.root/'cinematic_shots'/(jobid+'.mp4');video.parent.mkdir()
  subprocess.run(['ffmpeg','-y','-nostdin','-v','error','-f','lavfi',
    '-i','testsrc2=size=540x960:rate=12','-t','8','-c:v','libx264','-preset','ultrafast',
    '-crf','36',str(video)],check=True,capture_output=True,timeout=30)
  meta={'sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'bytes':video.stat().st_size}
  self.c.execute('INSERT INTO runway_cinematic_shots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
   (jobid,self.did,1,'synthetic_'+jobid,'fingerprint_'+jobid,'completed',str(uuid.uuid4()),
    json.dumps({'model':'offline_synthetic_fixture'}),96,96,json.dumps(meta),None,time.time(),time.time()))
  self.c.commit()
  reel.attach_verified_job(self.c,self.project,'hook',jobid,self.root)
  return video
 def test_readonly_quote_has_real_clip_timestamps_and_business_references(self):
  self.attach()
  q=bridge.prepare(self.c,self.project,'hook')
  self.assertEqual(q['model'],'gemini-2.5-flash')
  self.assertGreaterEqual(q['estimatedCalls'],1)
  self.assertLessEqual(q['estimatedCalls'],2)
  self.assertIn('koobideh',q['context']['sourceEvidence'].lower())
  self.assertFalse(q['context']['brand']['ownerApprovedKit'])
  self.assertFalse(q['providerPriceVerified'])
  self.assertFalse(q['approved'])
  self.assertFalse(q['generationIsPaid'] is False)
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_vision_jobs').fetchone()[0],0)
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_vision_approvals').fetchone()[0],0)
  self.assertTrue(all(x['durationSeconds']==1.7 for x in q['windows']))
 def test_no_approved_quote_or_enabled_cap_never_calls_google(self):
  self.attach();quote=bridge.prepare(self.c,self.project,'hook')
  class HTTPFake:
   calls=0
   def post(self,*args,**kwargs):self.calls+=1;raise AssertionError('No paid call allowed')
  fake=HTTPFake()
  with self.assertRaises(bridge.SemanticError):
   bridge.run_approved(self.c,self.project,'hook',self.root/'nonexistent',session=fake,paid_allowed=False)
  with self.assertRaises(bridge.SemanticError):
   bridge.approve_exact_review(self.c,self.project,'hook','bad',len(quote['windows']),
     'source-provider-rate-page-v1','owner-per-shot-approved-v1')
  with self.assertRaises(bridge.SemanticError):
   bridge.approve_exact_review(self.c,self.project,'hook',quote['requestHash'],len(quote['windows']),
     '','owner-per-shot-approved-v1')
  approved=bridge.approve_exact_review(self.c,self.project,'hook',quote['requestHash'],len(quote['windows']),
    'verified-provider-price-document-v1','explicit-owner-consent-test-v1')
  with self.assertRaises(bridge.SemanticError):
   bridge.run_approved(self.c,self.project,'hook',self.root/'nonexistent',session=fake,
     paid_allowed=True,approval_id=approved['id'],environ={'CLIPPR_BUSINESS_PAID_VISION_ENABLED':'no'})
  self.assertEqual(fake.calls,0)
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_vision_jobs').fetchone()[0],0)
 def test_fake_gemini_wire_format_and_one_execution_ledger_never_auto_retries(self):
  video=self.attach()
  proposal=bridge.prepare(self.c,self.project,'hook')
  record=bridge.approve_exact_review(self.c,self.project,'hook',proposal['requestHash'],len(proposal['windows']),
    'verified-provider-price-document-v1','explicit-owner-consent-test-v1')
  class StubResult:
   status_code=200
   def json(self):return {'candidates':[{'content':{'parts':[{'text':'{"findings":[]}' }]}}]}
  class StubSession:
   def __init__(self):self.requests=[]
   def post(self,url,headers,json,timeout,allow_redirects):
    self.requests.append((url,headers,json,timeout,allow_redirects))
    return StubResult()
  stub=StubSession()
  env={'CLIPPR_BUSINESS_PAID_VISION_ENABLED':'yes','GEMINI_API_KEY':'test-key-only',
   'CLIPPR_BUSINESS_VISION_MAX_CALLS':str(len(proposal['windows']))}
  response=bridge.run_approved(self.c,self.project,'hook',video,session=stub,
    approval_id=record['id'],paid_allowed=True,environ=env)
  self.assertEqual(response['requestsMade'],len(proposal['windows']))
  self.assertEqual(len(stub.requests),len(proposal['windows']))
  for url,headers,body,timeout,redirect in stub.requests:
   self.assertEqual(url,bridge.ENDPOINT)
   self.assertEqual(headers['x-goog-api-key'],'test-key-only')
   self.assertFalse(redirect)
   self.assertEqual(body['contents'][0]['parts'][1]['inlineData']['mimeType'],'video/mp4')
   self.assertTrue(len(body['contents'][0]['parts'][1]['inlineData']['data'])>1000)
   self.assertEqual(body['generationConfig']['responseMimeType'],'application/json')
  self.assertEqual(self.c.execute('SELECT status FROM business_reel_vision_jobs').fetchone()[0],'completed')
  self.assertEqual(reel.read(self.c,self.project)['slots'][0]['automaticVisualReviewStatus'],'awaiting_internal_creative_review')
  self.assertEqual(reel.read(self.c,self.project)['customerAllowanceConsumed'],0)
  with self.assertRaises(bridge.SemanticError):
   bridge.run_approved(self.c,self.project,'hook',video,session=stub,
     approval_id=record['id'],paid_allowed=True,environ=env)
  self.assertEqual(len(stub.requests),len(proposal['windows']))
 def test_timeout_is_durable_unknown_no_retry_and_human_review_available(self):
  video=self.attach()
  proposal=bridge.prepare(self.c,self.project,'hook')
  record=bridge.approve_exact_review(self.c,self.project,'hook',proposal['requestHash'],len(proposal['windows']),
   'verified-provider-price-document-v1','explicit-owner-consent-test-v1')
  class Bad:
   calls=0
   def post(self,*args,**kwargs):
    self.calls+=1;raise RuntimeError('read timed out after provider may have accepted')
  fake=Bad()
  env={'CLIPPR_BUSINESS_PAID_VISION_ENABLED':'yes','GEMINI_API_KEY':'fake-key',
   'CLIPPR_BUSINESS_VISION_MAX_CALLS':str(len(proposal['windows']))}
  with self.assertRaises(bridge.SemanticError):
   bridge.run_approved(self.c,self.project,'hook',video,session=fake,
     approval_id=record['id'],paid_allowed=True,environ=env)
  self.assertEqual(self.c.execute('SELECT status FROM business_reel_vision_jobs').fetchone()[0],
   'requires_manual_reconciliation')
  with self.assertRaises(bridge.SemanticError):
   bridge.run_approved(self.c,self.project,'hook',video,session=fake,
     approval_id=record['id'],paid_allowed=True,environ=env)
  self.assertEqual(fake.calls,1)
  item=next(x for x in queue.queue(self.c)['pending'] if x['slot']=='hook')
  self.assertEqual(item['status'],'awaiting_internal_review')
  self.assertFalse(item['newPaidGenerationApproved'])
 def test_spend_attempt_never_created_for_unsuitable_media(self):
  with self.assertRaises(bridge.SemanticError):bridge.prepare(self.c,self.project,'hook')
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM business_reel_vision_jobs').fetchone()[0],0)
