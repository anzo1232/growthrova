"""One exact owner-authorised Cedar benchmark via Runway developer API.

The persisted ledger is written BEFORE the only paid API submission.
Read-only task refresh is permitted. No retries, no automatic publication.
"""
from __future__ import annotations
import hashlib,json,math,re,time,uuid
from pathlib import Path
import business_marketing_drafts as drafts
import business_scene_contracts as scene_contracts
import business_runway as runway
import business_runway_video as downloaded_video
import business_video_motion_qc as motion_qc
from business_social_video_plan import DIRECTIONS,GUARD

MODEL='gen4.5'
DURATION=5
RATIO='720:1280'
CREDITS=60
AUTHORIZATION='owner_approved_cedar_restaurant_gen45_one_5s_60credit_attempt_2026_10_19'
APPROVED_DRAFT_ID='a2849edfbf9bb83c51c6ddb9502b61b5'
PROMPT=(DIRECTIONS['restaurant'][0]+' '+GUARD)
assert len(PROMPT)<1000

class SingleVideoTestError(ValueError):
 def __init__(self,message,code='restaurant_test_blocked',status=409):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 scene_contracts.initialise(con)
 con.execute('''CREATE TABLE IF NOT EXISTS business_paid_video_tests(
  id TEXT PRIMARY KEY,draft_id TEXT NOT NULL UNIQUE,
  authorization_id TEXT NOT NULL UNIQUE, request_fingerprint TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,provider_task TEXT,
  request_summary TEXT NOT NULL,reserved_credits INTEGER NOT NULL,
  actual_credits REAL,result_json TEXT,error_code TEXT,
  balance_before REAL,balance_after REAL,created REAL NOT NULL,updated REAL NOT NULL
 )''')

def public(row):
 result=json.loads(row['result_json']) if row['result_json'] else None
 return {'id':row['id'],'draftId':row['draft_id'],'providerTask':row['provider_task'],
  'status':row['status'],'model':MODEL,'duration':DURATION,'ratio':RATIO,
  'creditsReserved':row['reserved_credits'],'creditsCharged':row['actual_credits'],
  'balanceBefore':row['balance_before'],'balanceAfter':row['balance_after'],
  'errorCode':row['error_code'],'asset':result,
  'retryAllowed':False,'approved':False,'published':False,'additionalSpendAllowed':False}

def read(con,job_id):
 if not isinstance(job_id,str) or not re.fullmatch(r'[a-f0-9]{32}',job_id):
  raise SingleVideoTestError('Invalid paid job identifier')
 row=con.execute('SELECT * FROM business_paid_video_tests WHERE id=?',(job_id,)).fetchone()
 if not row:raise SingleVideoTestError('Paid test job not found','not_found',404)
 return public(row)

def submit(con,draft_id,*,approval,max_credits,root,client=None):
 if approval!=AUTHORIZATION or draft_id!=APPROVED_DRAFT_ID or type(max_credits) is not int or max_credits!=CREDITS:
  raise SingleVideoTestError('Separate owner approval required for this single 60-credit Cedar video test','not_authorised',403)
 saved=drafts.read_draft(con,draft_id)
 doc=saved['document']
 if saved['revision']!=1 or 'Cedar Restaurant' not in doc['business'] or not doc['sourceUrl'].startswith('https://www.thecedarrestaurant.co.uk/'):
  raise SingleVideoTestError('Test target or facts have changed; authorisation does not transfer','revision_or_source_changed',409)
 prepared={'model':MODEL,'duration':DURATION,'ratio':RATIO,'promptText':PROMPT}
 finger=hashlib.sha256(json.dumps((draft_id,saved['revision'],prepared),sort_keys=True).encode()).hexdigest()
 old=con.execute('SELECT * FROM business_paid_video_tests WHERE draft_id=?',(draft_id,)).fetchone()
 if old:
  if old['request_fingerprint']!=finger:raise SingleVideoTestError('Other video attempt already exists','no_paid_retry',409)
  return public(old)
 # No earlier paid video for this Cedar campaign, including other legacy ledgers.
 for table in ('runway_video_jobs','runway_cinematic_shots'):
  if con.execute(f'SELECT 1 FROM {table} WHERE draft_id=?',(draft_id,)).fetchone():
   raise SingleVideoTestError('Video was previously attempted under another ledger','no_paid_retry',409)
 try:scene_contracts.check(con,draft_id,saved['revision'],prepared,CREDITS)
 except scene_contracts.ContractError as exc:raise SingleVideoTestError(str(exc),exc.code,exc.status) from exc
 client=client or runway.RunwayClient()
 before=client.balance()
 if before<CREDITS:raise SingleVideoTestError('Runway credits below authorised maximum','insufficient_credits',402)
 con.execute('BEGIN IMMEDIATE')
 try:
  existing=con.execute('SELECT * FROM business_paid_video_tests WHERE draft_id=?',(draft_id,)).fetchone()
  if existing:
   con.commit();return public(existing)
  if drafts.read_draft(con,draft_id)['revision']!=1:raise SingleVideoTestError('Campaign changed after preflight','revision_changed',409)
  for table in ('runway_video_jobs','runway_cinematic_shots'):
   if con.execute(f'SELECT 1 FROM {table} WHERE draft_id=?',(draft_id,)).fetchone():
    raise SingleVideoTestError('Paid video attempt already exists','no_paid_retry',409)
  jid=uuid.uuid4().hex
  now=time.time()
  try:scene_contracts.reserve(con,draft_id,saved['revision'],prepared,CREDITS,jid)
  except scene_contracts.ContractError as exc:raise SingleVideoTestError(str(exc),exc.code,exc.status) from exc
  con.execute('INSERT INTO business_paid_video_tests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
   (jid,draft_id,AUTHORIZATION,finger,'submitting',None,json.dumps(prepared,ensure_ascii=False),
    CREDITS,None,None,None,before,None,now,now))
  con.commit()
 except BaseException:
  con.rollback();raise
 try:
  # This is the only paid call. No exception path calls submit again.
  reply=client.submit_text_video(prepared)
  task=reply.get('id')
  if not isinstance(task,str) or not re.fullmatch('[0-9a-fA-F-]{36}',task):
   raise SingleVideoTestError('Provider did not return a verifiable task ID','submission_unknown',502)
  con.execute("UPDATE business_paid_video_tests SET status='queued',provider_task=?,updated=? WHERE id=?",
   (task,time.time(),jid));con.commit()
 except Exception as exc:
  error=exc.code if isinstance(exc,(runway.RunwayError,SingleVideoTestError)) else type(exc).__name__
  definitive=isinstance(error,str) and error.startswith('provider_http_4')
  con.execute("UPDATE business_paid_video_tests SET status=?,error_code=?,updated=? WHERE id=?",
   ('rejected' if definitive else 'submission_unknown',error,time.time(),jid));con.commit()
 return read(con,jid)

def refresh(con,job_id,root,*,client=None):
 row=con.execute('SELECT * FROM business_paid_video_tests WHERE id=?',(job_id,)).fetchone()
 if not row:raise SingleVideoTestError('Unknown video job','not_found',404)
 if row['status'] in ('completed','rejected_quality','rejected','failed','cancelled','submission_unknown','submitting'):
  return public(row)
 if not row['provider_task']:return public(row)
 client=client or runway.RunwayClient()
 try:
  state=client.task(row['provider_task'])
  provider_status=state.get('status')
  cost=(state.get('cost') or {}).get('credits')
  if type(cost) not in (int,float) or not math.isfinite(cost) or cost<0:cost=None
  if provider_status in ('PENDING','RUNNING','THROTTLED'):
   con.execute("UPDATE business_paid_video_tests SET status=?,updated=? WHERE id=?",
    ('running' if provider_status=='RUNNING' else 'queued',time.time(),job_id))
  elif provider_status in ('FAILED','CANCELLED'):
   con.execute("UPDATE business_paid_video_tests SET status=?,actual_credits=?,error_code=?,updated=? WHERE id=?",
    ('failed' if provider_status=='FAILED' else 'cancelled',cost,'provider_'+provider_status.lower(),time.time(),job_id))
  elif provider_status=='SUCCEEDED':
   output=state.get('output')
   if not isinstance(output,list) or len(output)!=1 or not isinstance(output[0],str):
    raise SingleVideoTestError('Provider returned unexpected video output','invalid_provider_result',502)
   path=Path(root)/'restaurant_video_paid_test'/(job_id+'.mp4')
   if path.exists() or path.is_symlink():
    raise SingleVideoTestError('Private video destination already exists','asset_collision',409)
   receipt=downloaded_video._store_video(output[0],path,expected_duration=DURATION)
   qc=motion_qc.review(path,expected_duration=DURATION)
   receipt['motionReview']=qc
   status='completed' if qc['technicalMotionPass'] else 'rejected_quality'
   after=None
   try:after=client.balance()
   except Exception:pass
   con.execute("UPDATE business_paid_video_tests SET status=?,actual_credits=?,result_json=?,error_code=?,balance_after=?,updated=? WHERE id=?",
    (status,cost,json.dumps(receipt),None if qc['technicalMotionPass'] else 'insufficient_motion',after,time.time(),job_id))
  else:raise SingleVideoTestError('Provider returned an unsupported task state','unknown_provider_status',502)
  con.commit()
 except Exception as exc:
  # Never retry paid generation even if output download or validation fails.
  error=exc.code if isinstance(exc,(runway.RunwayError,SingleVideoTestError)) else type(exc).__name__
  charge=locals().get('cost')
  con.execute("UPDATE business_paid_video_tests SET status='rejected_quality',error_code=?,actual_credits=COALESCE(?,actual_credits),updated=? WHERE id=?",
   (error,charge,time.time(),job_id));con.commit()
 return read(con,job_id)
