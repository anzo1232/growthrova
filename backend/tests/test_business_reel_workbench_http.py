"""HTTP integration: no paid media, no customer bypass of internal QC."""
import unittest,uuid
from tests import test_business_local_pilot as local_pilot_tests
from tests.test_business_marketing_drafts import document
import business_local_pilot as pilot
import business_marketing_drafts as drafts

class WorkbenchHTTPTests(unittest.TestCase):
 def setUp(self):local_pilot_tests.LocalPilotTests.setUp(self)
 def api(self,*a,**kw):return local_pilot_tests.LocalPilotTests.api(self,*a,**kw)
 def test_create_is_idempotent_readable_and_never_creates_paid_jobs(self):
  did=uuid.uuid4().hex;doc=document()
  doc['editorialShortlist']={'status':'three_directions_ready_for_asset_intake','candidates':[
   {'id':f'idea{i}','role':'Craft','media':'Reel','format':'9:16','direction':'Food craft',
    'hook':'Authentic craft '+str(i),'evidence':{'kind':('method','heritage','bread')[i],'label':'paragraph 1',
     'quote':'Actual business website statement about the featured food.'}}
   for i in range(3)]}
  with pilot.session() as db:
   drafts.save_draft(db,{'id':did,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':doc})
  status,empty=self.api('/api/pilot/reel-workbench?draftId='+did)
  self.assertEqual(status,200);self.assertIsNone(empty['project'])
  action={'draftId':did,'expectedRevision':1}
  code,one=self.api('/api/pilot/reel-workbench',method='POST',body=action)
  self.assertEqual(code,200,one)
  project=one['project'];self.assertEqual(project['totalSlots'],4)
  self.assertEqual(project['customerAllowanceConsumed'],0)
  self.assertFalse(project['publiclyComplete'])
  self.assertEqual(project['providerSubmissionUnknownJobs'],0)
  # Semantic vision cannot be quoted until an actual original video passes
  # the cheaper technical stage; no paid vision job may be minted by GET.
  http_status,no_footage=self.api('/api/pilot/reel-vision-quotes/'+project['id']+'/hook')
  self.assertEqual(http_status,409,no_footage)
  self.assertEqual(no_footage['code'],'not_ready')
  http_status,no_footage=self.api('/api/pilot/reel-vision-quotes/'+project['id']+'/payoff')
  self.assertEqual(http_status,409,no_footage)
  # A real quote is readable but does not insert a paid provider request.
  code,proposal=self.api('/api/pilot/reel-shot-quotes/'+project['id']+'/hook')
  self.assertEqual(code,200,proposal)
  self.assertEqual(proposal['quote']['estimatedCredits'],96)
  self.assertEqual(proposal['quote']['model'],'gen4.5')
  self.assertEqual(proposal['quote']['existingAttemptCount'],0)
  self.assertFalse(proposal['quote']['spendAuthorisedNow'])
  self.assertFalse(proposal['quote']['modelGenerationStarted'])
  code,denied=self.api('/api/pilot/reel-shot-quotes/'+project['id']+'/payoff')
  self.assertEqual(code,400)
  code,repeated=self.api('/api/pilot/reel-workbench',method='POST',body=action)
  self.assertEqual(code,200);self.assertEqual(repeated['project']['id'],project['id'])
  code,read=self.api('/api/pilot/reel-workbench?draftId='+did)
  self.assertEqual(code,200);self.assertEqual(read['project']['id'],project['id'])
  code,denied=self.api('/api/pilot/reel-workbench/'+project['id']+'/edits',method='POST',body={})
  self.assertEqual(code,409)
  code,denied=self.api('/api/pilot/reel-workbench/'+project['id']+'/feedback',method='POST',body={'variant':'a','message':'Please keep the good shots and edit it cleanly'})
  self.assertEqual(code,409)
  code,denied=self.api('/api/pilot/reel-workbench',method='POST',body={**action,'spendCredits':96})
  self.assertEqual(code,400)
  code,denied=self.api('/api/pilot/reel-workbench/'+project['id']+'/endcard',method='POST',
    body={'name':'Example restaurant','cta':'Explore the menu','contactUrl':'https://example.org/','ownerConfirmed':False})
  self.assertEqual(code,403)
  code,denied=self.api('/api/pilot/reel-workbench/'+project['id']+'/endcard',method='POST',
    body={'name':'Example restaurant','cta':'Explore the menu','contactUrl':'https://other.example/','ownerConfirmed':True})
  self.assertEqual(code,400)
  code,endcard=self.api('/api/pilot/reel-workbench/'+project['id']+'/endcard',method='POST',
    body={'name':'Example restaurant','cta':'Explore the menu','contactUrl':'https://example.org/','ownerConfirmed':True})
  self.assertEqual(code,200,endcard)
  self.assertEqual(endcard['project']['slots'][3]['productionStatus'],'awaiting_internal_review')
  self.assertEqual(endcard['project']['providerCreditsObserved'],0)
  self.assertEqual(endcard['project']['customerAllowanceConsumed'],0)
  code,duplicate=self.api('/api/pilot/reel-workbench/'+project['id']+'/endcard',method='POST',
    body={'name':'Example restaurant','cta':'Explore the menu','contactUrl':'https://example.org/','ownerConfirmed':True})
  self.assertEqual(code,409)
  # Browser owner workflows reject unapproved brand logos, absent real footage,
  # unsupported automatic transcriptions and unauthorised publishing.
  import base64,io
  from PIL import Image
  buf=io.BytesIO();Image.new('RGB',(128,128),(35,56,64)).save(buf,'PNG')
  media=base64.b64encode(buf.getvalue()).decode('ascii')
  kit={'brandName':'Example restaurant','primary':'#132D28','accent':'#D4AE84',
    'contactUrl':'https://example.org/','style':'editorial',
    'mime':'image/png','logoBase64':media,
    'ownerAttestation':'I have authority to use this original locally created logo for the business.',
    'ownerConfirmed':False}
  code,forbidden=self.api('/api/pilot/reel-workbench/'+project['id']+'/owner-photo',method='POST',
    body={'slot':'hook','photoId':'f'*32,'ownerConfirmed':False})
  self.assertEqual(code,403,forbidden)
  code,bad=self.api('/api/pilot/reel-workbench/'+project['id']+'/brand',method='POST',body=kit)
  self.assertEqual(code,403,bad)
  code,locked=self.api('/api/pilot/reel-workbench/'+project['id']+'/brand',method='POST',
    body={**kit,'ownerConfirmed':True})
  self.assertEqual(code,200,locked)
  self.assertTrue(locked['project']['brandLock']['locked'])
  code,bad=self.api('/api/pilot/reel-workbench/'+project['id']+'/brand',method='POST',
    body={**kit,'ownerConfirmed':True})
  self.assertEqual(code,409,bad)
  code,bad=self.api('/api/pilot/reel-workbench/'+project['id']+'/owner-video',method='POST',
    body={'slot':'hook','sourceId':'a'*32,'rightsNote':'I own this original real video and approve its use','ownerConfirmed':True})
  self.assertEqual(code,409,bad)
  code,bad=self.api('/api/pilot/reel-workbench/'+project['id']+'/captions',method='POST',
    body={'variant':'a','source':'auto_transcript','ownerConfirmed':True,'expectedEditRevision':1,'expectedCaptionRevision':0,
      'style':{'typeface':'editorial','weight':'bold','placement':'bottom_safe'},
      'cues':[{'start':0,'end':1,'text':'Invented words'}]})
  self.assertEqual(code,403 if bad.get('code')=='transcript_unverified' else 409,bad)
  code,bad=self.api('/api/pilot/reel-workbench/'+project['id']+'/owner-choice',method='POST',
    body={'variant':'a','ownerReference':'test_local_owner','approvalNote':'I have reviewed the complete result',
      'expectedContentSha256':'0'*64,'expectedReviewSetSha256':'0'*64,
      'ownerConfirmed':True})
  self.assertEqual(code,409,bad)
  # HTTP contract fixture only: byte integrity and version pinning, not video quality.
  import hashlib,json,time
  from urllib.request import Request,urlopen
  folder=pilot.BASE/'reel_workbench'/project['id'];folder.mkdir(parents=True,exist_ok=True)
  file=folder/'a-1.mp4';file.write_bytes(b'HTTP-only synthetic media bytes')
  with pilot.session() as db:
   db.execute('INSERT INTO business_reel_edits VALUES(?,?,?,?,?,?,?,?,?)',
    (uuid.uuid4().hex,project['id'],'a',json.dumps([{'slot':'hook','seconds':5}]),
     hashlib.sha256(file.read_bytes()).hexdigest(),file.stat().st_size,'internal_preview_only',time.time(),1))
  code,before=self.api('/api/pilot/reel-workbench/'+project['id'])
  prior_hash=before['project']['edits'][0]['contentSha256']
  caption={'variant':'a','source':'owner_written_text','ownerConfirmed':True,
   'expectedEditRevision':1,'expectedCaptionRevision':0,
   'style':{'typeface':'editorial','weight':'bold','placement':'bottom_safe'},
   'cues':[{'start':0,'end':2,'text':'Fresh <bread> & service'}]}
  code,saved=self.api('/api/pilot/reel-workbench/'+project['id']+'/captions',method='POST',body=caption)
  self.assertEqual(code,200,saved)
  current_hash=saved['project']['edits'][0]['contentSha256']
  self.assertNotEqual(current_hash,prior_hash)
  url=self.url+'/api/pilot/reel-workbench/'+project['id']+'/captions/a?contentSha256='+current_hash
  with urlopen(Request(url,headers={'Origin':'http://127.0.0.1:4185','X-Clippr-Pilot':'local-only'}),timeout=8) as response:
   self.assertTrue(response.headers['Content-Type'].startswith('text/vtt'))
   self.assertIn('Fresh &lt;bread&gt; &amp; service',response.read().decode())
  code,stale=self.api('/api/pilot/reel-workbench/'+project['id']+'/previews/a?contentSha256='+prior_hash)
  self.assertEqual(code,409,stale);self.assertEqual(stale['code'],'stale_review')
  code,stale=self.api('/api/pilot/reel-workbench/'+project['id']+'/captions',method='POST',body=caption)
  self.assertEqual(code,409,stale)
  from concurrent.futures import ThreadPoolExecutor
  def competing_save(text):
   data={**caption,'expectedCaptionRevision':1,'cues':[{'start':0,'end':2,'text':text}]}
   return self.api('/api/pilot/reel-workbench/'+project['id']+'/captions',method='POST',body=data)[0]
  with ThreadPoolExecutor(max_workers=2) as workers:
   outcomes=list(workers.map(competing_save,['First browser edit','Second browser edit']))
  self.assertEqual(sorted(outcomes),[200,409])
  code,denied=self.api('/api/pilot/reel-workbench?draftId='+did,origin='https://attacker.example')
  self.assertEqual(code,403)
  with pilot.session() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM runway_video_jobs').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM business_reel_allowances').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM business_reel_vision_jobs').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM business_reel_vision_approvals').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM business_reel_projects').fetchone()[0],1)
