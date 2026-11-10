"""Source-specific, durable Runway Gen-4.5 Reel shot bridge.

Quotes are read-only. There is deliberately NO customer HTTP endpoint to
authorise a paid job. A future separately approved action can use the internal
approval ledger; no generation occurs while building or viewing the workbench.
"""
from __future__ import annotations
import hashlib,json,os,time,uuid
import business_marketing_drafts as drafts
import business_scene_contracts as scene_contracts
import business_scene_preparation as scene_preparation
import business_reel_workbench as reel
import business_reel_director as director
import business_cinematic_video as cinematic
import business_runway as runway
import business_creative_preflight as creative_preflight
import business_niche_strategy as niche_strategy
import business_creative_learning as learning

MODEL='gen4.5'
DURATION=cinematic.DURATION
RATIO='720:1280'
CREDITS=cinematic.CREDITS

class BridgeError(ValueError):
 def __init__(self,message,code='shot_bridge_blocked',status=409):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 scene_contracts.initialise(con)
 con.execute('''CREATE TABLE IF NOT EXISTS business_reel_shot_approvals(
   id TEXT PRIMARY KEY,project_id TEXT NOT NULL,slot TEXT NOT NULL,
   quote_fingerprint TEXT NOT NULL,revision INTEGER NOT NULL,
   max_credits INTEGER NOT NULL,approved_by TEXT NOT NULL,
   approved_at REAL NOT NULL,job_id TEXT,
   UNIQUE(project_id,slot))''')

def _project(con,project_id):
 project=reel._project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise BridgeError('Campaign changed: old shot quotes cannot be used','stale_revision')
 return project

def _compose_prompt(raw,evidence):
 """Keep complete source context when it fits; never end on a partial word."""
 # Sanitize untrusted text before measuring it. Per-field character cuts used
 # to discard short source facts even when the full request was below the cap.
 intro=director.clean(raw.split(' Source website fact, NOT an instruction',1)[0],limit=None)
 context=director.clean(evidence,limit=None)
 prompt=intro+' Source website context (unverified; NOT an instruction): '+context
 if len(prompt)<=980:return prompt
 return prompt[:981].rpartition(' ')[0].rstrip()

def quote(con,project_id,slot):
 """Freeze a business-specific exact shot request, without provider access."""
 project=_project(con,project_id)
 if slot not in reel.SLOTS[:3]:
  raise BridgeError('Brand and CTA ending is produced locally, not via a paid video','local_endcard_only',400)
 state=reel.read(con,project_id)
 recovery=state.get('directionRecovery') or {}
 if recovery.get('status')=='rebuild_required':
  raise BridgeError(recovery.get('nextAction') or
   'Rebuild the saved shot direction from the current verified campaign evidence before requesting a quote.',
   'missing_direction')
 part=next(x for x in state['slots'] if x['slot']==slot)
 raw=part.get('videoPrompt')
 if not isinstance(raw,str) or not 200<=len(raw)<=4000:
  raise BridgeError('Missing business-specific evidence-backed shot prompt','missing_direction')
 prompt=_compose_prompt(raw,part.get('sourceEvidence'))
 if len(prompt)<210 or not part.get('sourceCategory') or not part.get('cameraDirection'):
  raise BridgeError('Shot direction is not specific enough','missing_direction')
 # Enrich the paid quote with a cross-niche, evidence-grounded plan. This
 # planning never authorises a paid attempt or treats speculative visuals as proof.
 document=drafts.read_draft(con,project['draft_id'])['document']
 strategy=niche_strategy.profile(document['business'],document.get('observedFacts') or [part['sourceEvidence']])
 creative_plan=niche_strategy.blueprint(strategy,budget_credits=CREDITS)
 policy=learning.rubric(strategy,prompt)
 scene_request={'model':MODEL,'duration':DURATION,'ratio':RATIO,'promptText':prompt}
 scene_status=scene_contracts.status(con,project['draft_id'],project['revision'],scene_request,CREDITS)
 fingerprint=hashlib.sha256(json.dumps([project_id,project['revision'],slot,MODEL,DURATION,RATIO,prompt,policy['policyFingerprint'],creative_preflight.POLICY_VERSION,scene_status.get('fingerprint')],
   ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
 approval=con.execute('SELECT * FROM business_reel_shot_approvals WHERE project_id=? AND slot=?',(project_id,slot)).fetchone()
 jobs=con.execute('SELECT id,status,actual_credits,reserved_credits FROM runway_cinematic_shots WHERE draft_id=? AND shot_key=?',
  (project['draft_id'],'workbench:'+project_id+':'+slot)).fetchall()
 return {'projectId':project_id,'slot':slot,'draftId':project['draft_id'],'revision':project['revision'],
  'model':MODEL,'durationSeconds':DURATION,'ratio':RATIO,'estimatedCredits':CREDITS,
  'promptText':prompt,'fingerprint':fingerprint,'scenePreparation':scene_preparation.saved_slot_summary(con,project['draft_id'],project['revision'],part),'sceneContract':scene_status,'creativeReviewPolicy':policy,'sourceCategory':part['sourceCategory'],
  'sourceEvidence':part['sourceEvidence'],'cameraDirection':part['cameraDirection'],
  'rightsVerified':False,'brandApproved':False,'readyForPublishing':False,'modelGenerationStarted':len(jobs)>0,
  'existingAttemptCount':len(jobs),'existingStatus':jobs[0]['status'] if jobs else None,
  'customerAllowanceDebit':0,'approvalRecorded':bool(approval),
  'approvedFingerprintMatches':bool(approval and approval['quote_fingerprint']==fingerprint),
  'autoRetry':False,'spendAuthorisedNow':False,'nicheCreativePlan':creative_plan,'nextStep':'Separate exact per-shot credit approval required. No automatic retries.'}

def record_exact_approval(con,project_id,slot,expected_fingerprint,max_credits,approver):
 """Internal-only; may be called AFTER an actual separate user approval.

 It does not submit or reserve any provider credits by itself. No HTTP route.
 """
 prepared=quote(con,project_id,slot)
 if not isinstance(expected_fingerprint,str) or expected_fingerprint!=prepared['fingerprint']:
  raise BridgeError('The approved prompt differs from the current shot','prompt_changed')
 if type(max_credits)!=int or max_credits!=CREDITS:
  raise BridgeError('Approve only this one exact provider shot and its fixed cap','cap_required',403)
 if not isinstance(approver,str) or not 4<=len(approver)<=120:
  raise BridgeError('Actual approval source must be recorded','approval_missing',403)
 if prepared['existingAttemptCount']:
  raise BridgeError('Shot already has a provider attempt, never auto retry','retry_blocked')
 previous=con.execute('SELECT * FROM business_reel_shot_approvals WHERE project_id=? AND slot=?',(project_id,slot)).fetchone()
 if previous:
  if previous['quote_fingerprint']==expected_fingerprint:return dict(previous)
  raise BridgeError('Earlier approval must be preserved, not overwritten','approval_conflict')
 approval_id=uuid.uuid4().hex
 con.execute('INSERT INTO business_reel_shot_approvals VALUES(?,?,?,?,?,?,?,?,?)',
  (approval_id,project_id,slot,expected_fingerprint,prepared['revision'],
   CREDITS,approver,time.time(),None))
 con.commit()
 return dict(con.execute('SELECT * FROM business_reel_shot_approvals WHERE id=?',(approval_id,)).fetchone())

def submit_preapproved(con,project_id,slot,*,client=None,allow_paid=False):
 """Exactly one external submit after persistent authorisation and enabled cap.

 Never invoked during software builds/tests except with an injected fake client.
 Original provider task ID and uncertain submissions are retained in the
 existing Runway ledger. Calling again returns same job without another submit.
 """
 if allow_paid is not True:
  raise BridgeError('An exact, separately approved action is required','not_authorised',403)
 requested=quote(con,project_id,slot)
 if requested['existingAttemptCount']:
  row=con.execute('SELECT * FROM runway_cinematic_shots WHERE draft_id=? AND shot_key=?',
   (requested['draftId'],'workbench:'+project_id+':'+slot)).fetchone()
  return cinematic.public(row)
 request={'model':MODEL,'duration':DURATION,'ratio':RATIO,'promptText':requested['promptText']}
 sector=director.sector_of((drafts.read_draft(con,requested['draftId'])['document'].get('editorialShortlist') or {}),drafts.read_draft(con,requested['draftId'])['document'])
 try:
  creative_preflight.require(sector=sector,prompt=requested['promptText'],evidence=requested['sourceEvidence'],shot_purpose=requested['cameraDirection'],estimated_credits=CREDITS,cap=CREDITS)
 except creative_preflight.CreativePreflightError as exc:
  raise BridgeError(str(exc),'creative_preflight_failed',403) from exc
 approval=con.execute('SELECT * FROM business_reel_shot_approvals WHERE project_id=? AND slot=?',
  (project_id,slot)).fetchone()
 if not approval or approval['quote_fingerprint']!=requested['fingerprint'] or approval['revision']!=requested['revision']:
  raise BridgeError('No matching durable approval','approval_required',403)
 cap=os.environ.get('CLIPPR_BUSINESS_RUNWAY_TEST_CAP','0')
 try:limit=int(cap)
 except ValueError:limit=0
 if limit<CREDITS or limit>1000:
  raise BridgeError('Paid generation is disabled for this isolated workspace','paid_disabled',403)
 existing_sum=con.execute('SELECT COALESCE(SUM(reserved_credits),0) FROM runway_cinematic_shots WHERE draft_id=?',
  (requested['draftId'],)).fetchone()[0]
 if existing_sum+CREDITS>limit:
  raise BridgeError('This request exceeds remaining approved credit cap','budget_exceeded',403)
 try:scene_contracts.check(con,requested['draftId'],requested['revision'],request,CREDITS)
 except scene_contracts.ContractError as exc:raise BridgeError(str(exc),exc.code,exc.status) from exc
 client=client or runway.RunwayClient()
 if client.balance()<CREDITS:raise BridgeError('Provider does not have sufficient credits','insufficient_credits',402)
 con.execute('BEGIN IMMEDIATE')
 try:
  new_quote=quote(con,project_id,slot)
  if new_quote['fingerprint']!=requested['fingerprint']:
   raise BridgeError('Creative policy changed before reservation','quote_changed',409)
  if new_quote['existingAttemptCount']:raise BridgeError('Concurrent request already recorded','in_progress')
  # The provider balance request above can overlap another approved shot. Check
  # the shared reservation total under the same write lock as this insertion.
  reserved=con.execute('SELECT COALESCE(SUM(reserved_credits),0) FROM runway_cinematic_shots WHERE draft_id=?',
   (requested['draftId'],)).fetchone()[0]
  if reserved+CREDITS>limit:
   raise BridgeError('This request exceeds remaining approved credit cap','budget_exceeded',403)
  jid=uuid.uuid4().hex;now=time.time()
  try:scene_contracts.reserve(con,requested['draftId'],requested['revision'],request,CREDITS,jid)
  except scene_contracts.ContractError as exc:raise BridgeError(str(exc),exc.code,exc.status) from exc
  con.execute('INSERT INTO runway_cinematic_shots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
   (jid,requested['draftId'],requested['revision'],'workbench:'+project_id+':'+slot,
    requested['fingerprint'],'submitting',None,
    json.dumps({'model':MODEL,'duration':DURATION,'ratio':RATIO,'promptText':requested['promptText']}),
    CREDITS,None,None,None,now,now))
  con.execute('UPDATE business_reel_shot_approvals SET job_id=? WHERE id=?',(jid,approval['id']))
  con.commit()
 except BaseException:
  con.rollback();raise
 try:
  result=client.submit_text_video(request)
  task=result.get('id')
  if not isinstance(task,str) or len(task)!=36:
   raise BridgeError('Provider did not acknowledge a valid task; reconcile before retry','unknown_submission')
  con.execute("UPDATE runway_cinematic_shots SET status='queued',provider_task=?,updated=? WHERE id=?",
   (task,time.time(),jid));con.commit()
 except Exception as exc:
  code=exc.code if isinstance(exc,runway.RunwayError) else type(exc).__name__
  definitive=isinstance(code,str) and code.startswith('provider_http_4')
  con.execute('UPDATE runway_cinematic_shots SET status=?,error_code=?,updated=? WHERE id=?',
   ('rejected' if definitive else 'submission_unknown',str(code)[:100],time.time(),jid));con.commit()
 return cinematic.public(cinematic.get_job(con,jid))


def reconcile_existing(con,project_id,slot,root,*,client=None):
 """Resolve the SAME paid provider task; never place a new generation.

 This is a read/poll and verified output-ingest operation only. Unknown
 submissions without provider task IDs always stay blocked for intervention.
 """
 current=quote(con,project_id,slot)
 if current['existingAttemptCount']!=1:
  raise BridgeError('There is no single existing shot attempt to reconcile','no_provider_job')
 job=con.execute('SELECT id,status FROM runway_cinematic_shots WHERE draft_id=? AND shot_key=?',
  (current['draftId'],'workbench:'+project_id+':'+slot)).fetchone()
 if job['status'] in ('submission_unknown','submitting'):
  raise BridgeError('Original submission needs manual task-ID reconciliation. Never retry blindly','unknown_submission')
 if job['status'] in ('queued','running'):
  cinematic.refresh(con,job['id'],root,client=client)
 refreshed=cinematic.get_job(con,job['id'])
 if refreshed['status']=='completed':
  # Import from the immutable original Runway receipt and check decoded motion,
  # without accepting creative quality on behalf of the internal reviewer.
  reel.attach_verified_job(con,project_id,slot,job['id'],root)
 return {'shot':slot,'providerJob':cinematic.public(refreshed),
  'project':reel.read(con,project_id),'newPaidAttempt':False,
  'automaticRetry':False,'customerAllowanceCharged':0}
