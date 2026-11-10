"""Shot-led Runway text-to-video, preserving spend receipts and usable motion tests.

Never automatically retries, publishes, or marks cinematic quality approved.
"""
from __future__ import annotations
import hashlib,json,math,sqlite3,time,uuid
from pathlib import Path
import business_marketing_drafts as drafts
import business_scene_contracts as scene_contracts
import business_runway as runway
import business_runway_video as vid
import business_video_motion_qc as motion_qc
import business_creative_preflight as creative_preflight

MODEL='gen4.5'
DURATION=8
CREDITS=96
SHOTS={
 'concierge_arrival':('concierge',
  'Premium hospitality commercial, 8-second continuous moving shot. Fictional city venue at blue hour in light rain. '
  'A sleek unbranded black executive car MOVES visibly into frame within the FIRST SECOND, '
  'travels along the wet stone driveway toward a warmly illuminated entrance, gradually brakes '
  'and comes to a stop under the entrance canopy by second 6. '
  'The tracking camera moves laterally alongside the car throughout, with clear foreground-to-background parallax, '
  'passing columns and realistic reflections sliding across glossy body panels and wet pavement. '
  'A subtle chauffeur silhouette approaches the car near the final second. '
  'Cinematic documentary realism, natural physics, believable wheels and architecture, high-end restrained grade, '
  'dusk cobalt atmosphere and warm amber lights. The emphasis is a tangible service moment, not a static property tour. '
  'No text, no signs, no logos, no trademarks, no readable phone screens, no celebrity, no fabricated real venue claim.'),
 'concierge_transfers':('concierge',
  'Premium private travel support campaign, an 8-second cinematic continuous action. '
  'A fictional private-airport arrival at twilight with no identifiable airline or airport. '
  'An unbranded chauffeur driven executive sedan MOVES visibly from distance on the airport access road, '
  'approaches the camera and smoothly turns to an arrival kerb, showing realistic wheel rotation. '
  'The camera dollies smoothly right while tracking the vehicle and reflections shift across the body. '
  'Natural dusk, amber terminal windows, plausible aviation environment. '
  'Show a recognisable transfer arriving, not a static glamour shot. No text, no marks, no logos, no celebrities.'),
 'roofing_issue':('roofing',
  '8-second realistic UK residential roofing documentary ad. At ground level a camera tracks '
  'around a house during light rain revealing overflowing gutter and water visibly pouring down, '
  'a tradesperson wearing safety gear checks the issue from the ground and gestures to the gutter. '
  'No unsafe climbing, no fabricated before-after repair, no business uniform, no text or logos.')
}
class CinematicError(ValueError):
 def __init__(self,message,code='cinematic_unavailable',status=422):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 scene_contracts.initialise(con)
 con.execute('''CREATE TABLE IF NOT EXISTS runway_cinematic_shots(
  id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,revision INTEGER NOT NULL,
  shot_key TEXT NOT NULL,fingerprint TEXT NOT NULL UNIQUE,status TEXT NOT NULL,
  provider_task TEXT,request_summary TEXT NOT NULL,reserved_credits INTEGER NOT NULL,
  actual_credits REAL,result_json TEXT,error_code TEXT,created REAL NOT NULL,updated REAL NOT NULL)''')

def get_job(con,jid):
 if not isinstance(jid,str) or len(jid)!=32 or any(c not in '0123456789abcdef' for c in jid):raise CinematicError('Invalid video ID')
 row=con.execute('SELECT * FROM runway_cinematic_shots WHERE id=?',(jid,)).fetchone()
 if not row:raise CinematicError('Unknown cinematic shot','not_found',404)
 return row

def public(row):
 meta=json.loads(row['result_json']) if row['result_json'] else None
 return {'id':row['id'],'draftId':row['draft_id'],'shotKey':row['shot_key'],
  'status':row['status'],'creditsReserved':row['reserved_credits'],'creditsCharged':row['actual_credits'],
  'duration':DURATION,'model':MODEL,'asset':meta,'errorCode':row['error_code'],
  'approvedForUse':False,'published':False,'retryAllowed':False}

def submit(con,draft_id,revision,key,*,root,client=None,max_credits=0):
 drafts._id(draft_id)
 if key not in SHOTS:raise CinematicError('Unknown prepared shot concept','invalid_shot',400)
 saved=drafts.read_draft(con,draft_id)
 if type(revision) is not int or saved['revision']!=revision:raise CinematicError('Saved business campaign changed','revision_conflict',409)
 category,prompt=SHOTS[key]
 context=' '.join(str(x) for x in saved['document'].get('observedFacts',[])[:15]).lower()
 if category=='concierge' and not any(x in context for x in ('concierge','premium access','private aviation','curated experience','exclusive event')):
  raise CinematicError('This cinematic scene is not based on this business','wrong_business',409)
 if category=='roofing' and not any(x in context for x in ('roof','gutter')):
  raise CinematicError('This roofing scene is not applicable','wrong_business',409)
 request={'model':MODEL,'duration':DURATION,'ratio':'720:1280','promptText':prompt}
 finger=hashlib.sha256(json.dumps([draft_id,revision,key,MODEL,DURATION,prompt],sort_keys=True).encode()).hexdigest()
 previous=con.execute('SELECT * FROM runway_cinematic_shots WHERE fingerprint=?',(finger,)).fetchone()
 if previous:return public(previous)
 if type(max_credits) is not int or max_credits<CREDITS or max_credits>300:
  raise CinematicError('Set an explicit credit cap for this shot','cap_required',403)
 try:
  creative_preflight.require(sector=category,prompt=prompt,evidence=context,
   shot_purpose='Show the specific business problem or service moment',estimated_credits=CREDITS,cap=max_credits)
 except creative_preflight.CreativePreflightError as exc:
  raise CinematicError(str(exc),'creative_preflight_failed',403) from exc
 try:scene_contracts.check(con,draft_id,revision,request,CREDITS)
 except scene_contracts.ContractError as exc:raise CinematicError(str(exc),exc.code,exc.status) from exc
 client=client or runway.RunwayClient()
 if client.balance()<CREDITS:raise CinematicError('Not enough developer credits','insufficient_credits',402)
 con.execute('BEGIN IMMEDIATE')
 try:
  old=con.execute('SELECT * FROM runway_cinematic_shots WHERE fingerprint=?',(finger,)).fetchone()
  if old:con.commit();return public(old)
  if con.execute('SELECT 1 FROM runway_cinematic_shots WHERE draft_id=? AND shot_key=?',(draft_id,key)).fetchone():
   raise CinematicError('This shot already has a paid attempt; no retries','retry_disabled',409)
  reserved=con.execute('SELECT COALESCE(SUM(reserved_credits),0) FROM runway_cinematic_shots WHERE draft_id=?',(draft_id,)).fetchone()[0]
  if reserved+CREDITS>max_credits:raise CinematicError('This test would exceed the allowed credits','budget_exceeded',403)
  if drafts.read_draft(con,draft_id)['revision']!=revision:raise CinematicError('Saved campaign changed','revision_conflict',409)
  jid=uuid.uuid4().hex;now=time.time()
  try:scene_contracts.reserve(con,draft_id,revision,request,CREDITS,jid)
  except scene_contracts.ContractError as exc:raise CinematicError(str(exc),exc.code,exc.status) from exc
  con.execute('INSERT INTO runway_cinematic_shots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
   (jid,draft_id,revision,key,finger,'submitting',None,json.dumps({'model':MODEL,'duration':DURATION,'ratio':'720:1280','promptText':prompt}),CREDITS,None,None,None,now,now))
  con.commit()
 except BaseException:con.rollback();raise
 try:
  response=client.submit_text_video(request)
  task=response.get('id')
  if not isinstance(task,str) or len(task)!=36:raise CinematicError('Provider did not return a usable video task ID')
  con.execute("UPDATE runway_cinematic_shots SET provider_task=?,status='queued',updated=? WHERE id=?",(task,time.time(),jid));con.commit()
 except Exception as exc:
  code=exc.code if isinstance(exc,runway.RunwayError) else type(exc).__name__
  definitive=isinstance(code,str) and code.startswith('provider_http_4')
  state='rejected' if definitive else 'submission_unknown'
  con.execute('UPDATE runway_cinematic_shots SET status=?,error_code=?,updated=? WHERE id=?',(state,code,time.time(),jid));con.commit()
 return public(get_job(con,jid))

def refresh(con,jid,root,*,client=None):
 row=get_job(con,jid)
 if row['status'] in ('completed','failed','cancelled','rejected','rejected_quality','submission_unknown','submitting'):return public(row)
 client=client or runway.RunwayClient()
 confirmed_provider_result=False
 try:
  result=client.task(row['provider_task'])
  confirmed_provider_result=True
  state=result.get('status')
  cost=(result.get('cost') or {}).get('credits')
  if type(cost) not in (int,float) or not math.isfinite(cost) or cost<0:cost=None
  if state=='SUCCEEDED':
   outputs=result.get('output')
   if not isinstance(outputs,list) or len(outputs)!=1:raise CinematicError('Provider returned unexpected video output')
   target=Path(root)/'cinematic_shots'/(row['id']+'.mp4')
   item=vid._store_video(outputs[0],target,expected_duration=DURATION)
   verdict=motion_qc.review(target,expected_duration=DURATION)
   item['motionReview']=verdict
   quality_state='completed' if verdict['technicalMotionPass'] else 'rejected_quality'
   con.execute("UPDATE runway_cinematic_shots SET status=?,result_json=?,actual_credits=?,error_code=?,updated=? WHERE id=?",
    (quality_state,json.dumps(item),cost,None if verdict['technicalMotionPass'] else 'insufficient_motion',time.time(),jid))
  elif state in ('FAILED','CANCELLED'):
   con.execute('UPDATE runway_cinematic_shots SET status=?,actual_credits=?,error_code=?,updated=? WHERE id=?',
    ('failed' if state=='FAILED' else 'cancelled',cost,'provider_'+state.lower(),time.time(),jid))
  elif state in ('RUNNING','PENDING','THROTTLED'):
   con.execute('UPDATE runway_cinematic_shots SET status=?,updated=? WHERE id=?',('running' if state=='RUNNING' else 'queued',time.time(),jid))
  else:raise CinematicError('Provider status unknown','unknown_status',409)
  con.commit()
 except Exception as exc:
  con.execute('UPDATE runway_cinematic_shots SET status=?,error_code=?,actual_credits=COALESCE(?,actual_credits),updated=? WHERE id=?',
    ('rejected_quality' if confirmed_provider_result else row['status'],
      'output_invalid_'+type(exc).__name__ if confirmed_provider_result else 'poll_unavailable_'+type(exc).__name__,
      locals().get('cost') if confirmed_provider_result else None,time.time(),jid));con.commit()
 return public(get_job(con,jid))
