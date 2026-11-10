"""Isolated Business Reel resilience pipeline. No paid provider submit, retry, or publish.

Human creative review is a back-office-only operation, never customer self-attestation.
Provider credits and customer allowances are accounted for separately.
"""
from __future__ import annotations
import hashlib,json,os,re,sqlite3,subprocess,time,uuid
from pathlib import Path
import business_marketing_drafts as drafts
import business_cinematic_video as cinematic
import business_video_motion_qc as motion
import business_reel_director as director
import business_reel_endcard as native_endcard
import business_reel_visual_intelligence as visual_engine
import business_reel_art_review as art_review
import business_reel_delivery_qc as delivery_qc
import business_reel_owner_media as owner_media
import business_reel_brand_lock as brand_lock
import business_reel_captions as captions
import business_reel_caption_exports as caption_exports
import business_reel_build7_triage as triage
import business_reel_build7_readiness as readiness

SLOTS=('hook','craft','experience','payoff')
PROVIDERS=('Runway','Google Veo','Kling')
class ReelError(ValueError):
 def __init__(self,message,code='reel_unavailable',status=422):
  super().__init__(message);self.code=code;self.status=status

def _id(value):
 if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{32}',value):raise ReelError('Invalid project or draft identifier','invalid_id',400)
 return value

def initialise(con):
 con.executescript('''
 CREATE TABLE IF NOT EXISTS business_reel_projects(
  id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,revision INTEGER NOT NULL,
  status TEXT NOT NULL,brief_json TEXT NOT NULL,created REAL NOT NULL,
  UNIQUE(draft_id,revision));
 CREATE TABLE IF NOT EXISTS business_reel_shots(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,slot TEXT NOT NULL,
  provider_job_id TEXT NOT NULL UNIQUE,sha256 TEXT NOT NULL,
  qc_json TEXT NOT NULL,internal_verdict TEXT NOT NULL,review_reason TEXT,
  reviewer TEXT,reviewed_at REAL,created REAL NOT NULL,UNIQUE(project_id,slot));
 CREATE TABLE IF NOT EXISTS business_reel_edits(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,variant TEXT NOT NULL,
  ordered_shots_json TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,
  status TEXT NOT NULL,created REAL NOT NULL,revision_no INTEGER NOT NULL,
  UNIQUE(project_id,variant,revision_no));
 CREATE TABLE IF NOT EXISTS business_reel_feedback(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,variant TEXT NOT NULL,
  message TEXT NOT NULL,created REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS business_reel_visual_reviews(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,slot TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,report_json TEXT NOT NULL,
  reviewer TEXT NOT NULL,created REAL NOT NULL,
  UNIQUE(project_id,slot,source_sha256));
 CREATE TABLE IF NOT EXISTS business_reel_machine_findings(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,slot TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,model TEXT NOT NULL,result_json TEXT NOT NULL,
  approved_vision_request INTEGER NOT NULL,created REAL NOT NULL,
  UNIQUE(project_id,slot,source_sha256));
 CREATE TABLE IF NOT EXISTS business_reel_audio_evidence(
  edit_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,
  original_sha256 TEXT NOT NULL,track_sha256 TEXT NOT NULL,
  rights_attestation TEXT NOT NULL,owner_confirmed INTEGER NOT NULL,
  created REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS business_reel_final_reviews(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,variant TEXT NOT NULL,
  edit_revision INTEGER NOT NULL,verdict TEXT NOT NULL,
  review_notes TEXT NOT NULL,reviewer TEXT NOT NULL,created REAL NOT NULL,
  UNIQUE(project_id,variant,edit_revision));
 CREATE TABLE IF NOT EXISTS business_reel_review_receipts(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,variant TEXT NOT NULL,
  edit_revision INTEGER NOT NULL,content_sha256 TEXT NOT NULL,
  verdict TEXT NOT NULL,review_notes TEXT NOT NULL,reviewer TEXT NOT NULL,
  created REAL NOT NULL,UNIQUE(project_id,variant,content_sha256));
 CREATE TABLE IF NOT EXISTS business_reel_owner_choice_receipts(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,variant TEXT NOT NULL,
  edit_revision INTEGER NOT NULL,content_sha256 TEXT NOT NULL,
  review_set_sha256 TEXT NOT NULL,brand_sha256 TEXT NOT NULL,
  approval_note TEXT NOT NULL,owner_reference TEXT NOT NULL,
  approved_at REAL NOT NULL,UNIQUE(project_id,review_set_sha256));
 CREATE TABLE IF NOT EXISTS business_reel_allowances(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL UNIQUE,
  units INTEGER NOT NULL,reason TEXT NOT NULL,created REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS business_reel_owner_approvals(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,variant TEXT NOT NULL,
  edit_revision INTEGER NOT NULL,brand_sha256 TEXT NOT NULL,
  approval_note TEXT NOT NULL,owner_reference TEXT NOT NULL,
  approved_at REAL NOT NULL,UNIQUE(project_id,edit_revision,variant));
 CREATE TABLE IF NOT EXISTS business_reel_endcard_history(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,sha256 TEXT NOT NULL,
  file_name TEXT NOT NULL,record_json TEXT NOT NULL,archived_at REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS business_reel_local_endcards(
  project_id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,
  brand_name TEXT NOT NULL,cta TEXT NOT NULL,contact_url TEXT NOT NULL,
  status TEXT NOT NULL,review_reason TEXT,reviewer TEXT,created REAL NOT NULL);
 ''')
 audio_columns={c['name'] for c in con.execute('PRAGMA table_info(business_reel_audio_evidence)')}
 for column in ('voice_sha256','voice_rights_attestation'):
  if column not in audio_columns:
   con.execute('ALTER TABLE business_reel_audio_evidence ADD COLUMN '+column+' TEXT')
 owner_media.initialise(con)
 brand_lock.initialise(con)
 captions.initialise(con)
 caption_exports.initialise(con)
 endcard_columns={c['name'] for c in con.execute('PRAGMA table_info(business_reel_local_endcards)')}
 if 'brand_logo_sha256' not in endcard_columns:
  con.execute('ALTER TABLE business_reel_local_endcards ADD COLUMN brand_logo_sha256 TEXT')
 if 'file_name' not in endcard_columns:
  con.execute('ALTER TABLE business_reel_local_endcards ADD COLUMN file_name TEXT')
 # Backwards-compatible migration for older private Reel prototypes. Preserve
 # the old table as an immutable ledger rather than dropping historical edits.
 columns={x['name'] for x in con.execute('PRAGMA table_info(business_reel_edits)')}
 if 'revision_no' not in columns:
  con.executescript('''
   ALTER TABLE business_reel_edits RENAME TO business_reel_edits_legacy_20261021;
   CREATE TABLE business_reel_edits(
    id TEXT PRIMARY KEY,project_id TEXT NOT NULL,variant TEXT NOT NULL,
    ordered_shots_json TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,
    status TEXT NOT NULL,created REAL NOT NULL,revision_no INTEGER NOT NULL,
    UNIQUE(project_id,variant,revision_no));
   INSERT INTO business_reel_edits
    SELECT id,project_id,variant,ordered_shots_json,sha256,bytes,status,created,1
    FROM business_reel_edits_legacy_20261021;
  ''')

def create(con,draft_id,revision):
 did=_id(draft_id)
 saved=drafts.read_draft(con,did)
 if type(revision)!=int or saved['revision']!=revision:raise ReelError('Save or refresh the campaign first','stale_revision',409)
 previous=con.execute('SELECT id FROM business_reel_projects WHERE draft_id=? AND revision=?',(did,revision)).fetchone()
 if previous:return read(con,previous['id'])
 doc=saved['document'];short=doc.get('editorialShortlist') or {}
 ideas=short.get('candidates') or []
 if short.get('status')!='three_directions_ready_for_asset_intake' or len(ideas)!=3:
  raise ReelError('Research at least three grounded creative directions first','research_incomplete',409)
 # Creative direction comes from the business-specific verified-source
 # shortlist, not a generic hard-coded restaurant intro or repeated placeholder.
 try:production=director.build(doc)
 except director.DirectionError as exc:raise ReelError(str(exc),'specific_direction_required',409) from exc
 source_slots=[{
    'slot':scene['slot'],'sourceDirection':scene['headline'],
    'sourceEvidence':scene['source'],
    'sourceCategory':scene['sourceCategory'],'cameraDirection':scene['camera'],
    'shotBrief':scene['visualDirection'],'videoPrompt':scene['prompt'],
    'reviewRequirements':scene['technicalReview'],
    'purpose':scene['purpose'],
    'productionStatus':('awaiting_authorised_brand_assets' if scene['slot']=='payoff' else 'not_generated')
  } for scene in production['shots']]
 brief={'business':doc['business'],'sourceUrl':doc.get('sourceUrl'),'slots':source_slots,
  'directionAudit':{'distinctCategories':production['distinctSourceCategories'],'status':production['creativeStatus'],'sector':production['sector']},
  'style':'photorealistic, brand-specific short-form video; footage must match actual services',
  'spendApproval':False,'publishingApproval':False,'betaHumanReviewRequired':True}
 uid=uuid.uuid4().hex;now=time.time()
 con.execute('INSERT INTO business_reel_projects VALUES(?,?,?,?,?,?)',
  (uid,did,revision,'awaiting_approved_media',json.dumps(brief),now));con.commit()
 return read(con,uid)

def read_for_draft(con,draft_id):
 did=_id(draft_id)
 rows=con.execute('SELECT id FROM business_reel_projects WHERE draft_id=? ORDER BY revision DESC,created DESC LIMIT 1',(did,)).fetchall()
 return read(con,rows[0]['id']) if rows else None

def _project(con,project_id):
 row=con.execute('SELECT * FROM business_reel_projects WHERE id=?',(_id(project_id),)).fetchone()
 if not row:raise ReelError('Reel project not found','not_found',404)
 return row

def _verified_file(con,job_id,root):
 job=cinematic.get_job(con,_id(job_id))
 if job['status']!='completed' or not job['provider_task'] or not job['result_json']:
  raise ReelError('Only completed and reconciled provider videos can enter the review','source_not_verified',409)
 info=json.loads(job['result_json']);path=Path(root)/'cinematic_shots'/(job_id+'.mp4')
 digest=info.get('sha256')
 if not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest):
  raise ReelError('Missing provider output digest','missing_digest',409)
 if path.is_symlink() or not path.is_file() or path.stat().st_size!=info.get('bytes') or path.stat().st_size>65*1024*1024:
  raise ReelError('Provider media is unavailable or altered','source_changed',409)
 if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
  raise ReelError('Provider media integrity failed','source_changed',409)
 return job,path,digest

def attach_verified_job(con,project_id,slot,job_id,root):
 """Internal adapter after original paid task reconciliation; no provider request."""
 project=_project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise ReelError('This Reel uses an earlier campaign version; prepare a new Reel to continue','stale_revision',409)
 if slot not in SLOTS:raise ReelError('Unknown Reel shot position','invalid_slot',400)
 job,path,digest=_verified_file(con,job_id,root)
 if job['draft_id']!=project['draft_id'] or job['revision']!=project['revision']:
  raise ReelError('Paid job belongs to another campaign or revision','wrong_source',409)
 if job['shot_key'].startswith('workbench:') and job['shot_key']!='workbench:'+project_id+':'+slot:
  raise ReelError('Provider output belongs to a different planned shot','shot_identity_mismatch',409)
 if con.execute('SELECT 1 FROM business_reel_owner_media WHERE project_id=? AND slot=?',(project_id,slot)).fetchone():
  raise ReelError('Approved original business footage takes precedence','owner_source_exists',409)
 old=con.execute('SELECT id,provider_job_id FROM business_reel_shots WHERE project_id=? AND slot=?',(project_id,slot)).fetchone()
 if old:
  if old['provider_job_id']==job_id:return read(con,project_id)
  raise ReelError('Existing shot cannot be overwritten; preserve review history','shot_conflict',409)
 staged=visual_engine.run_staged_review(path,
  expected_duration=cinematic.DURATION,expected_brand=json.loads(project['brief_json'])['business'])
 fast=staged['fast']
 state='awaiting_internal_review' if fast['technicalMotionPass'] else 'technical_rejected'
 con.execute('INSERT INTO business_reel_shots VALUES(?,?,?,?,?,?,?,?,?,?,?)',
  (uuid.uuid4().hex,project_id,slot,job_id,digest,json.dumps({
     'technicalMotionPass':fast['technicalMotionPass'],
     'visualStage':staged['finalDisposition'],
     'qualityStatus':state,'frameSamples':fast['frameSamples'],
     'cheapVisualReview':fast,'visionCallCount':0,
     'manualArtReviewPending':True,'approved':False}),state,
   None if fast['technicalMotionPass'] else 'Failed staged mechanical quality review',None,None,time.time()))
 con.commit()
 return read(con,project_id)

def internal_review(con,project_id,slot,decision,reason,reviewer):
 """Back-office-only human acceptance. Intentionally not exposed as customer HTTP action."""
 project=_project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise ReelError('The campaign changed; review the new version','stale_revision',409)
 if decision not in ('accepted','rejected') or slot not in SLOTS or not isinstance(reason,str) or len(reason.strip())<12:
  raise ReelError('A meaningful internal creative-direction decision is required','review_invalid',400)
 if not isinstance(reviewer,str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,64}',reviewer):
  raise ReelError('Internal reviewer identity required','reviewer_required',403)
 if slot!='payoff' and con.execute('SELECT 1 FROM business_reel_owner_media WHERE project_id=? AND slot=?',(project_id,slot)).fetchone():
  try:owner_media.internal_review(con,project_id,slot,decision,reason,reviewer)
  except owner_media.OwnerMediaError as exc:raise ReelError(str(exc),exc.code,exc.status) from exc
  return read(con,project_id)
 if slot=='payoff':
  local=con.execute('SELECT status FROM business_reel_local_endcards WHERE project_id=?',(project_id,)).fetchone()
  if not local or local['status']!='awaiting_internal_review':
   raise ReelError('Only a real, owner-confirmed end-card can be reviewed','review_not_allowed',409)
  con.execute('UPDATE business_reel_local_endcards SET status=?,review_reason=?,reviewer=? WHERE project_id=?',
   (decision,reason.strip()[:300],reviewer,project_id))
  con.commit()
  return read(con,project_id)
 row=con.execute('SELECT * FROM business_reel_shots WHERE project_id=? AND slot=?',(project_id,slot)).fetchone()
 if not row or row['internal_verdict']!='awaiting_internal_review':
  raise ReelError('Only QC-passing shots awaiting human review are reviewable','review_not_allowed',409)
 if decision=='accepted':
  model_result=con.execute('SELECT result_json FROM business_reel_machine_findings WHERE project_id=? AND slot=? AND source_sha256=?',
    (project_id,slot,row['sha256'])).fetchone()
  if model_result and json.loads(model_result['result_json'])['stage']=='auto_rejected':
   raise ReelError('A recorded critical visual failure cannot be manually bypassed','semantic_rejected',409)
  reviewed=con.execute('SELECT report_json,reviewer FROM business_reel_visual_reviews WHERE project_id=? AND slot=? AND source_sha256=?',
    (project_id,slot,row['sha256'])).fetchone()
  if not reviewed or reviewed['reviewer']!=reviewer or not json.loads(reviewed['report_json']).get('allPassed'):
   raise ReelError('Visual anatomy, factual accuracy and cinematography review required before acceptance','visual_review_required',409)
 con.execute('UPDATE business_reel_shots SET internal_verdict=?,review_reason=?,reviewer=?,reviewed_at=? WHERE id=?',
  (decision,reason.strip()[:300],reviewer,time.time(),row['id']))
 con.commit()
 return read(con,project_id)

def record_external_visual_findings(con,project_id,slot,model_result,*,vision_spend_approved=False):
 """Back-office only. Accepts a validated result from a separately approved
 model adapter or an explicitly labelled synthetic QA fixture. It cannot
 generate footage, bill a customer, approve visuals, or publish.
 """
 _project(con,project_id)
 if slot not in SLOTS[:3]:raise ReelError('Only footage shots may be semantically scanned','invalid_slot',400)
 shot=con.execute('SELECT * FROM business_reel_shots WHERE project_id=? AND slot=?',(project_id,slot)).fetchone()
 if not shot or shot['internal_verdict']!='awaiting_internal_review':
  raise ReelError('Only technically valid footage can receive a model report','review_not_allowed',409)
 if not isinstance(model_result,dict):
  raise ReelError('A verified visual evidence report is required','invalid_vision_result',400)
 model=model_result.get('model')
 if model!='offline_vision_fixture' and vision_spend_approved is not True:
  raise ReelError('Separate approval is required for a paid semantic video review','vision_spend_blocked',403)
 fast=json.loads(shot['qc_json'])['cheapVisualReview']
 try:result=visual_engine.validate_vision_result(model_result,sample_report=fast,
   expected_brand=json.loads(_project(con,project_id)['brief_json'])['business'])
 except visual_engine.VisualReviewError as exc:
  raise ReelError(str(exc),'invalid_vision_result',400) from exc
 if con.execute('SELECT 1 FROM business_reel_machine_findings WHERE project_id=? AND slot=? AND source_sha256=?',
  (project_id,slot,shot['sha256'])).fetchone():
  raise ReelError('Preserve the first visual model assessment and its cost record','already_reviewed',409)
 con.execute('INSERT INTO business_reel_machine_findings VALUES(?,?,?,?,?,?,?,?)',
  (uuid.uuid4().hex,project_id,slot,shot['sha256'],model,json.dumps(result),int(vision_spend_approved),time.time()))
 if result['stage']=='auto_rejected':
  con.execute('UPDATE business_reel_shots SET internal_verdict=?,review_reason=? WHERE id=?',
   ('semantic_rejected','High-confidence documented visual/factual failure; paid retry disabled',shot['id']))
 con.commit()
 return {'model':model,'report':result,'newPaidVideoGeneration':False,
  'humanReviewStillNeeded':result['stage']!='auto_rejected'}

def record_manual_visual_review(con,project_id,slot,checks,reviewer):
 """Back-office only: save evidence before accepting. No customer API route."""
 _project(con,project_id)
 try:art_review.reviewer_id(reviewer)
 except art_review.ArtReviewError as exc:raise ReelError(str(exc),'reviewer_required',403) from exc
 if slot not in SLOTS[:3]:raise ReelError('Video art review only applies to generated footage','invalid_slot',400)
 row=con.execute('SELECT * FROM business_reel_shots WHERE project_id=? AND slot=?',(project_id,slot)).fetchone()
 sourced=con.execute('SELECT * FROM business_reel_owner_media WHERE project_id=? AND slot=?',(project_id,slot)).fetchone()
 if row:
  if row['internal_verdict']!='awaiting_internal_review':
   raise ReelError('No technically healthy real footage is awaiting art review','review_not_allowed',409)
  digest=row["sha256"]
  qc=json.loads(row['qc_json'])
 elif sourced:
  if sourced['approval_status']!='awaiting_internal_review':
   raise ReelError('No viable owner footage awaiting art review','review_not_allowed',409)
  digest=sourced['render_sha256']
  stored=json.loads(sourced['qc_json'])
  qc={'visualStage':stored['finalDisposition'],'cheapVisualReview':stored['fast']}
 else:
  raise ReelError('No genuine video source ready for review','review_not_allowed',409)
 if qc.get('visualStage')!='awaiting_semantic_visual_review':
  raise ReelError('The shot did not clear the low-cost visual stage','visual_gate_blocked',409)
 profile=json.loads(_project(con,project_id)['brief_json'])
 part=next(x for x in profile['slots'] if x['slot']==slot)
 sector=profile.get('directionAudit',{}).get('sector','')
 food_related=any(x in (part.get('sourceEvidence','')+' '+part.get('shotBrief','')).lower()
   for x in ('food','bread','kabab','grill','meal','sangak','koobideh','mezze'))
 required=('food_accuracy',) if food_related else ()
 try:assessment=art_review.check_categories(checks,qc['cheapVisualReview'],required_categories=required)
 except art_review.ArtReviewError as exc:raise ReelError(str(exc),'invalid_visual_evidence',400) from exc
 if con.execute('SELECT 1 FROM business_reel_visual_reviews WHERE project_id=? AND slot=? AND source_sha256=?',
   (project_id,slot,digest)).fetchone():
  raise ReelError('An earlier visual review cannot be replaced silently','review_already_recorded',409)
 con.execute('INSERT INTO business_reel_visual_reviews VALUES(?,?,?,?,?,?,?)',
  (uuid.uuid4().hex,project_id,slot,digest,json.dumps(assessment),reviewer,time.time()))
 con.commit()
 return {'sourceSha256':digest,'assessment':assessment,'approved':False,
  'humanCreativeDecisionStillRequired':True,'newPaidGenerations':0}

def _shots(con,project_id):
 return con.execute('SELECT * FROM business_reel_shots WHERE project_id=? ORDER BY created,id',(project_id,)).fetchall()

def _content_sha256(con,project_id,edit,root=None,*,include_export=True):
 """Bind approval to the exact saved rendition, text and owner brand.

 Old revision-only approvals stay in their original tables as history. They
 cannot establish approval for media/text they never identified.
 """
 project=_project(con,project_id)
 try:
  locked=brand_lock.read(con,project_id,root)
  track=captions.latest(con,project_id,edit['variant'])
  if root is not None:
   path=preview_file(con,project_id,edit['variant'],root)
   if hashlib.sha256(path.read_bytes()).hexdigest()!=edit['sha256']:
    raise ReelError('The preview changed while it was being reviewed','stale_review',409)
   if track:captions.file_for(con,project_id,edit['variant'],root)
 except (brand_lock.BrandLockError,captions.CaptionError) as exc:
  raise ReelError(str(exc),exc.code,exc.status) from exc
 # Include typography and placement as well as VTT bytes: identical wording
 # rendered in a different place still needs a new final-layout review.
 caption=None
 if track:
  row=con.execute('SELECT vtt_sha256 FROM business_reel_caption_tracks WHERE project_id=? AND variant=? AND edit_revision=? AND track_revision=?',
   (project_id,edit['variant'],edit['revision_no'],track['captionRevision'])).fetchone()
  if not row:raise ReelError('Caption version changed during review','stale_review',409)
  caption={key:track[key] for key in ('editRevision','captionRevision','source','style','cues')}
  caption['sha256']=row['vtt_sha256']
 endcard=con.execute('SELECT sha256,brand_logo_sha256 FROM business_reel_local_endcards WHERE project_id=?',(project_id,)).fetchone()
 record={'schema':1,'projectId':project_id,'campaignRevision':project['revision'],
  'variant':edit['variant'],'editRevision':edit['revision_no'],'videoSha256':edit['sha256'],
  'shotManifest':json.loads(edit['ordered_shots_json']),
  'captions':caption,'brand':locked,'endcard':dict(endcard) if endcard else None}
 base_sha=hashlib.sha256(json.dumps(record,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 if include_export:
  try:export=caption_exports.current(con,project_id,edit['variant'],base_sha,root)
  except caption_exports.CaptionExportError as exc:raise ReelError(str(exc),exc.code,exc.status) from exc
  if export:
   bound={'schema':2,'inputContentSha256':base_sha,
    'captionedVideo':{key:export[key] for key in ('id','sha256','bytes')}}
   return hashlib.sha256(json.dumps(bound,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 return base_sha

def _review_set_sha256(contents):
 if not all(v in contents for v in ('a','b')):return None
 return hashlib.sha256(json.dumps({v:contents[v] for v in ('a','b')},sort_keys=True).encode()).hexdigest()

def read(con,project_id):
 row=_project(con,project_id)
 shots=_shots(con,project_id);by_slot={s['slot']:s for s in shots}
 saved=drafts.read_draft(con,row['draft_id'])
 current_revision=saved['revision']
 profile=director.enrich_legacy_brief(json.loads(row['brief_json']),saved['document'],
  same_revision=current_revision==row['revision'])
 local=con.execute('SELECT * FROM business_reel_local_endcards WHERE project_id=?',(project_id,)).fetchone()
 details=[]
 for item in profile['slots']:
  shot=by_slot.get(item['slot']);part=dict(item)
  if item['slot']!='payoff':
   part['plannedBusinessPhoto']=owner_media.planned_photo(con,project_id,item['slot'])
  authentic=con.execute('SELECT * FROM business_reel_owner_media WHERE project_id=? AND slot=?',
    (project_id,item['slot'])).fetchone() if item['slot']!='payoff' else None
  part['ownerMediaSelectionAllowed']=bool(item['slot'] in SLOTS[:3] and current_revision==row['revision'] and
   not shot and not authentic and not owner_media._provider_attempt_blocks(con,row,project_id,item['slot']))
  if authentic:
   q=json.loads(authentic['qc_json'])
   visual=con.execute('SELECT report_json FROM business_reel_visual_reviews WHERE project_id=? AND slot=? AND source_sha256=?',
    (project_id,item['slot'],authentic['render_sha256'])).fetchone()
   part.update({'productionStatus':authentic['approval_status'],'sourceType':'owner_authorised_video',
    'originalMediaPreserved':True,'originalSourceId':authentic['source_id'],
    'ownerRightsConfirmed':True,'providerCreditsDebitedToCustomer':0,
    'technicalQC':{'technicalMotionPass':q['fast']['technicalMotionPass'],'cheapVisualReview':q['fast']},
    'creativeReviewTriage':triage.summarise(q['fast']),
    'manualVisualReviewRecorded':bool(visual),
    'visualCategoriesReviewed':list(json.loads(visual['report_json'])['categories']) if visual else [],
    'reviewReason':authentic['review_reason'],'reviewer':authentic['reviewer'],
    'automaticVisualReviewStatus':'not_run'})
  if item['slot']=='payoff' and local:
   part.update({'productionStatus':local['status'],'reviewReason':local['review_reason'],
    'providerCreditsDebitedToCustomer':0,'reviewer':local['reviewer'],
    'localGraphic':True,'masterLogoUsed':bool(local['brand_logo_sha256'])})
  if shot:
   visual=con.execute('SELECT report_json FROM business_reel_visual_reviews WHERE project_id=? AND slot=? AND source_sha256=?',
     (project_id,item['slot'],shot['sha256'])).fetchone()
   part['manualVisualReviewRecorded']=bool(visual)
   part['visualCategoriesReviewed']=list(json.loads(visual['report_json'])['categories']) if visual else []
   machine=con.execute('SELECT result_json FROM business_reel_machine_findings WHERE project_id=? AND slot=? AND source_sha256=?',
     (project_id,item['slot'],shot['sha256'])).fetchone()
   part['automaticVisualReviewStatus']=json.loads(machine['result_json'])['stage'] if machine else 'not_run'
   part.update({'productionStatus':shot['internal_verdict'],'providerJobId':shot['provider_job_id'],
     'technicalQC':json.loads(shot['qc_json']),
     'creativeReviewTriage':triage.summarise(json.loads(shot['qc_json']).get('cheapVisualReview') or {'technicalMotionPass':False,'issues':['legacy_visual_scan_missing']}),
     'reviewReason':shot['review_reason'],
     'providerCreditsDebitedToCustomer':0,'reviewer':shot['reviewer']})
  elif item['slot']!='payoff' and not authentic:
   if part.get('plannedBusinessPhoto'):
    part['productionStatus']='awaiting_image_to_video_approval'
    part['sourceType']='owner_declared_business_photo'
   paid=con.execute('SELECT id,status,actual_credits,error_code FROM runway_cinematic_shots WHERE draft_id=? AND shot_key=? ORDER BY created DESC LIMIT 1',
    (row['draft_id'],'workbench:'+project_id+':'+item['slot'])).fetchone()
   if paid:
    mapping={'submitting':'reconcile_required','submission_unknown':'reconcile_required',
     'queued':'provider_queued','running':'provider_running',
     'completed':'awaiting_internal_import','failed':'provider_failed',
     'cancelled':'provider_cancelled','rejected':'provider_rejected',
     'rejected_quality':'technical_rejected'}
    part.update({'productionStatus':mapping.get(paid['status'],'reconcile_required'),
     'providerJobId':paid['id'],'providerCreditsDebitedToCustomer':0,
     'providerCreditsObserved':paid['actual_credits'],'providerErrorCode':paid['error_code']})
  details.append(part)
 good=sum(x['productionStatus']=='accepted' for x in details)
 rejected=sum(x['productionStatus'] in ('rejected','technical_rejected','provider_failed','provider_cancelled','provider_rejected','semantic_rejected') for x in details)
 uncertain=con.execute("SELECT COUNT(*) FROM runway_cinematic_shots WHERE draft_id=? AND status IN ('submission_unknown','submitting')",(row['draft_id'],)).fetchone()[0]
 scoped_credits=con.execute('''SELECT COALESCE(SUM(actual_credits),0)
  FROM runway_cinematic_shots WHERE draft_id=?
   AND (shot_key LIKE ? OR id IN
     (SELECT provider_job_id FROM business_reel_shots WHERE project_id=?))''',
     (row['draft_id'],'workbench:'+project_id+':%',project_id)).fetchone()[0]
 charged=con.execute('SELECT SUM(actual_credits) FROM runway_cinematic_shots WHERE draft_id=?',(row['draft_id'],)).fetchone()[0]
 charged_jobs=con.execute('SELECT COUNT(*) FROM runway_cinematic_shots WHERE draft_id=? AND actual_credits IS NOT NULL',(row['draft_id'],)).fetchone()[0]
 unknown_jobs=con.execute("SELECT COUNT(*) FROM runway_cinematic_shots WHERE draft_id=? AND actual_credits IS NULL AND status NOT IN ('submitting','queued','running')",(row['draft_id'],)).fetchone()[0]
 allowance=con.execute('SELECT COALESCE(SUM(units),0) FROM business_reel_allowances WHERE project_id=?',(project_id,)).fetchone()[0]
 final_rows=con.execute('SELECT variant,edit_revision,content_sha256,verdict,review_notes FROM business_reel_review_receipts WHERE project_id=? ORDER BY created DESC',(project_id,)).fetchall()
 edits=con.execute('SELECT * FROM business_reel_edits WHERE project_id=? ORDER BY variant,revision_no DESC',(project_id,)).fetchall()
 seen_edits=set();current_edits=[]
 for e in edits:
  if e['variant'] not in seen_edits:current_edits.append(e);seen_edits.add(e['variant'])
 contents={e['variant']:_content_sha256(con,project_id,e) for e in current_edits}
 current_exports={e['variant']:caption_exports.current(con,project_id,e['variant'],
  _content_sha256(con,project_id,e,include_export=False)) for e in current_edits}
 review_set=_review_set_sha256(contents)
 current=current_revision==row['revision']
 def verified_final(receipt):
  if not current or receipt['verdict']!='accepted' or receipt['content_sha256']!=contents.get(receipt['variant']):return False
  try:proof=json.loads(receipt['review_notes']).get('verifiedQc',{})
  except (TypeError,ValueError):return False
  return bool(proof.get('technicalReelPass') and proof.get('audioPresent') and
    proof.get('mobileSafeTextPass') and proof.get('ownerBrandDetailsReviewed'))
 reviewed_variants={r['variant'] for r in final_rows if verified_final(r)}
 final_review_accepted=good==len(SLOTS) and all(name in reviewed_variants for name in ('a','b'))
 local_approval=con.execute('SELECT variant,content_sha256,review_set_sha256 FROM business_reel_owner_choice_receipts WHERE project_id=? ORDER BY approved_at DESC LIMIT 1',(project_id,)).fetchone()
 owner_choice=next((x for x in current_edits if current and final_review_accepted and local_approval and
   x['variant']==local_approval['variant'] and contents[x['variant']]==local_approval['content_sha256'] and
   review_set==local_approval['review_set_sha256']),None)
 messages=con.execute('SELECT variant,message,created FROM business_reel_feedback WHERE project_id=? ORDER BY created DESC LIMIT 12',(project_id,)).fetchall()
 state=('archived_earlier_revision' if current_revision!=row['revision'] else
  ('owner_selected_awaiting_schedule_permission' if owner_choice else 'ready_for_owner_review' if final_review_accepted else 'awaiting_internal_edit_review') if good==len(SLOTS) else 'internal_review' if good else
  'blocked_or_in_production' if rejected else 'awaiting_approved_media')
 state_payload={'id':row['id'],'draftId':row['draft_id'],'revision':row['revision'],
  'business':profile['business'],'status':state,'isCurrentRevision':current_revision==row['revision'],'slots':details,'totalSlots':len(SLOTS),
  'acceptedShots':good,'rejectedShots':rejected,
  'privateWorkInProgress':any(x['productionStatus']=='accepted' and x['slot']!='payoff' for x in details),'internallyReviewedFinalEdit':final_review_accepted,
  'publiclyComplete':False,'customerCanPublish':False,
  'customerAllowanceConsumed':allowance,'providerCreditsObserved':charged or 0,
  'providerCreditsForThisReel':scoped_credits or 0,
  'generationCostOptions':director.cost_options(),
  'creativeDirectionAudit':profile.get('directionAudit',{'status':'legacy_no_source_direction_audit'}),
  'directionRecovery':profile.get('directionRecovery'),
  'providerChargedJobCount':charged_jobs,'providerCostUnreconciledJobs':unknown_jobs,
  'providerSubmissionUnknownJobs':uncertain,'providerCostMayDifferFromAllowance':True,
  'autoPaidRetry':False,'retryPerformed':False,'paidGenerationAllowed':False,
  'internalCreativeReviewRequired':True,'ownerApprovalRequired':True,
  'edits':[{'variant':e['variant'],'status':e['status'],'revision':e['revision_no'],
    'previewAvailable':True,'contentSha256':contents[e['variant']],
    'captionsBakedIntoVideo':bool(current_exports[e['variant']]),
    'captionExport':current_exports[e['variant']],'style':{'wip':'Work in progress','a':'Social-first cut','b':'Cinematic cut'}[e['variant']],
    'estimatedSeconds':_saved_edit_duration(e['ordered_shots_json'])} for e in current_edits],
  'editHistoryCount':len(edits),'feedback':[dict(x) for x in messages],
  'brandLock':brand_lock.read(con,project_id),
  'captionTracks':{v:captions.latest(con,project_id,v) for v in ('a','b','wip')},
  'completeEditsPassedInternalReview':sorted(reviewed_variants),
  'bothEditsQualityChecked':final_review_accepted,'reviewSetSha256':review_set,
  'localOwnerChoiceRecorded':bool(owner_choice),
  'locallySelectedVariant':owner_choice['variant'] if owner_choice else None,
  'scheduled':False,'schedulePermitted':False,
  'recovery':{'preserveAcceptedShots':True,'freeTimelineEdits':True,'alternatives':2,
    'providerChoices':[{'provider':x,'pricingVerified':False,'extraPaidApprovalRequired':True} for x in PROVIDERS],
    'reconcileUnknownJobBeforeNewSpend':True,
    'notice':'A failed or poor shot uses no customer allowance. Provider charges are accounted separately and may still be incurred.'}}
 state_payload['build7Readiness']=readiness.assess(state_payload)
 return state_payload

def _saved_edit_duration(encoded):
 """Old single-version previews had no per-shot timing; retain compatibility."""
 try:
  items=json.loads(encoded)
  if not isinstance(items,list):raise ValueError()
  return round(sum(float(item.get('seconds',3)) if isinstance(item,dict) else 3 for item in items),1)
 except (TypeError,ValueError,OverflowError):
  raise ReelError('Saved edit timings are invalid','invalid_edit_manifest',409) from None

def _endcard_path(project_id,record,root):
 name=record['file_name'] or 'endcard-local.mp4'
 if not re.fullmatch(r'endcard-(?:local|brand-[a-f0-9]{12})\.mp4',name):
  raise ReelError('Invalid end card version path','unsafe_path',409)
 folder=Path(root)/'reel_workbench'/project_id
 if folder.is_symlink():raise ReelError('Invalid end card directory','unsafe_path',409)
 return folder/name

def _accepted_paths(con,project_id,root):
 result=[]
 for slot in SLOTS:
  item=con.execute('SELECT * FROM business_reel_shots WHERE project_id=? AND slot=? AND internal_verdict=?',
   (project_id,slot,'accepted')).fetchone()
  if item:
   _,path,digest=_verified_file(con,item['provider_job_id'],root)
   if digest!=item['sha256']:raise ReelError('Source changed after creative review','source_changed',409)
   result.append((slot,path))
  else:
   owner=con.execute('SELECT * FROM business_reel_owner_media WHERE project_id=? AND slot=? AND approval_status=?',
     (project_id,slot,'accepted')).fetchone()
   if owner:
    try:_,path=owner_media.file_for(con,project_id,slot,root)
    except owner_media.OwnerMediaError as exc:raise ReelError(str(exc),exc.code,exc.status) from exc
    result.append((slot,path))
 if any(slot=='payoff' for slot in SLOTS):
  local=con.execute('SELECT * FROM business_reel_local_endcards WHERE project_id=? AND status=?',
   (project_id,'accepted')).fetchone()
  if local:
   path=_endcard_path(project_id,local,root)
   if path.is_symlink() or not path.is_file() or path.stat().st_size!=local['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=local['sha256']:
    raise ReelError('Verified brand endcard has changed since review','source_changed',409)
   result.append(('payoff',path))
 return result

def _edit_recipe(paths,variant):
 """Three genuinely distinct local editing rhythms. No generation cost.

 Keep a recognisable hook at the front; contrast punchy social pacing against
 slower editorial pacing. Durations are deterministic and included in the
 immutable edit signature so existing approved versions are never overwritten.
 """
 if variant=='wip':return [(slot,path,2.5) for slot,path in paths]
 if variant=='a':
  timing={'hook':1.8,'craft':2.5,'experience':3.1,'payoff':2.0}
  return [(slot,path,timing[slot]) for slot,path in paths]
 if variant=='b':
  timing={'hook':2.7,'experience':3.3,'craft':3.5,'payoff':2.6}
  order=sorted(paths,key=lambda entry:('hook','experience','craft','payoff').index(entry[0]))
  return [(slot,path,timing[slot]) for slot,path in order]
 raise ReelError('Unknown editing rhythm','bad_edit_recipe',400)

def _render_cut(paths,output,*,soft_transitions=False,catalogue_review=False,catalogue_audio=None):
 # Catalogue callers prove scope separately and pass only private, verified
 # temporary files. This rendering option grants no workbench review authority.
 if not paths or len(paths)>(5 if catalogue_review else 4):raise ReelError('No accepted footage for this preview','no_usable_shots',409)
 if catalogue_review and (soft_transitions or any(not 0<float(s)<=30 for _,_,s in paths) or sum(float(s) for _,_,s in paths)>30):
  raise ReelError('Catalogue preview exceeds 30 seconds','invalid_edit_manifest',409)
 if output.is_symlink():raise ReelError('Unsafe output path','unsafe_path',409)
 if catalogue_audio is not None and (not catalogue_review or not isinstance(catalogue_audio,list) or
   len(catalogue_audio)!=len(paths) or any(type(a) is not bool for a in catalogue_audio)):
  raise ReelError('Invalid catalogue audio settings','invalid_edit_manifest',409)
 with_audio=bool(catalogue_audio and any(catalogue_audio))
 inputs=[];chains=[]
 for i,(_,f,seconds) in enumerate(paths):
  if catalogue_review:
   inputs+=['-protocol_whitelist','file','-format_whitelist','mov,image2,png_pipe',
     '-threads','1','-err_detect','explode',
     *(['-loop','1','-t',str(seconds)] if f.suffix=='.png' else ['-enable_drefs','0']),'-i',str(f)]
  else:inputs+=['-i',str(f)]
  fit=('scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2'
       if catalogue_review else 'scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280')
  filters=f'[{i}:v]trim=duration={seconds},setpts=PTS-STARTPTS,{fit},setsar=1,fps=24,format=yuv420p'
  # Brief fades through black soften B's slower editorial rhythm without
  # overlapping footage or silently changing subtitle/audio timestamps.
  if soft_transitions:
   if i>0:filters+=',fade=t=in:st=0:d=0.18'
   if i<len(paths)-1:filters+=f',fade=t=out:st={max(0,seconds-.18):.3f}:d=0.18'
  chains.append(filters+f'[v{i}]')
  if with_audio:
   if catalogue_audio[i]:
    import math
    import business_asset_catalog as catalog
    # FFmpeg subtracts the container start from input timestamps. Align audio
    # with the first video frame, retaining stream delay and filling its gap.
    # Resetting audio to STARTPTS would move speech/music ahead of the picture.
    try:
     info=catalog.probe_offline_video(f)
     video=next(s for s in info['streams'] if s['codec_type']=='video')
     origin=float(video['start_time'])-float(info['format']['start_time'])
    except (ValueError,KeyError,TypeError,StopIteration) as exc:
     raise ReelError('Cannot align saved audio with video','invalid_edit_manifest',409) from exc
    if not math.isfinite(origin) or not 0<=origin<=60:
     raise ReelError('Cannot align saved audio with video','invalid_edit_manifest',409)
    audio=(f'[{i}:a:0]asetpts=PTS-({origin})/TB,aresample=48000:async=1:first_pts=0,'
           'aformat=sample_fmts=fltp:channel_layouts=stereo,apad')
   else:audio='anullsrc=r=48000:cl=stereo'
   chains.append(audio+f',atrim=duration={seconds},asetpts=PTS-STARTPTS[a{i}]')
 filtergraph=';'.join(chains)+';' + ''.join(
  f'[v{i}][a{i}]' if with_audio else f'[v{i}]' for i in range(len(paths)))+f'concat=n={len(paths)}:v=1:a={int(with_audio)}[out]'+('[audio]' if with_audio else '')
 tmp=output.with_name('.'+output.stem+'-pending.mp4')
 try:
  result=subprocess.run(['ffmpeg','-y','-nostdin','-v','error',*inputs,
   *(['-filter_complex_threads','1'] if catalogue_review else []),'-filter_complex',filtergraph,
   '-map','[out]','-r','24',*(['-map','[audio]','-c:a','aac','-b:a','128k'] if with_audio else ['-an']),'-c:v','libx264','-preset','veryfast','-crf','23',
   *(['-threads','1','-map_metadata','-1','-map_chapters','-1','-fs',str(10*1024*1024)] if catalogue_review else []),
   '-movflags','+faststart',str(tmp)],check=True,capture_output=True,timeout=75)
  if catalogue_review and result.stderr.strip():raise ReelError('Catalogue preview decode failed','render_failed',422)
  if not tmp.is_file() or tmp.stat().st_size>65*1024*1024:raise ReelError('Local preview render unavailable','render_failed',422)
  os.replace(tmp,output)
 except (subprocess.SubprocessError,OSError) as exc:
  raise ReelError('Local non-paid preview failed safely','render_failed',422) from exc
 finally:tmp.unlink(missing_ok=True)
 return output

def prepare_edits(con,project_id,root):
 project=_project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise ReelError('An old campaign version is read-only; prepare a new Reel plan','stale_revision',409)
 paths=_accepted_paths(con,project_id,root)
 if not paths or not any(slot!='payoff' for slot,_ in paths):
  raise ReelError('A branded ending alone is not a usable Reel. Accept actual footage first','no_usable_shots',409)
 directory=Path(root)/'reel_workbench'/project_id
 if directory.is_symlink():raise ReelError('Invalid private Reel location','unsafe_path',409)
 directory.mkdir(parents=True,exist_ok=True,mode=0o700)
 variants={'wip':_edit_recipe(paths,'wip')}
 if len(paths)>=3:
  variants['a']=_edit_recipe(paths,'a')
  variants['b']=_edit_recipe(paths,'b')
 for variant,order in variants.items():
  signature=json.dumps([{'slot':slot,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
    'seconds':seconds,'recipeVersion':3,'transition':('soft_fade' if variant=='b' else 'cut')} for slot,file,seconds in order],sort_keys=True)
  existing=con.execute('SELECT * FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',(project_id,variant)).fetchone()
  if existing and existing['ordered_shots_json']==signature:continue
  revision=1 if not existing else existing['revision_no']+1
  path=directory/(variant+'-'+str(revision)+'.mp4')
  _render_cut(order,path,soft_transitions=variant=='b')
  payload=path.read_bytes()
  con.execute('INSERT INTO business_reel_edits VALUES(?,?,?,?,?,?,?,?,?)',
    (uuid.uuid4().hex,project_id,variant,signature,
      hashlib.sha256(payload).hexdigest(),len(payload),'internal_preview_only',time.time(),revision))
 con.commit()
 return read(con,project_id)

def preview_file(con,project_id,variant,root):
 _project(con,project_id)
 if variant not in ('wip','a','b'):raise ReelError('Unknown edit','invalid_variant',400)
 row=con.execute('SELECT * FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',(project_id,variant)).fetchone()
 if not row:raise ReelError('No preview ready','not_ready',404)
 file=Path(root)/'reel_workbench'/project_id/(variant+'-'+str(row['revision_no'])+'.mp4')
 if not file.exists() and row['revision_no']==1:
  # Earlier prototype used variant.mp4. Keep its bytes unchanged and verify.
  file=Path(root)/'reel_workbench'/project_id/(variant+'.mp4')
 if file.is_symlink() or not file.is_file() or file.stat().st_size!=row['bytes'] or hashlib.sha256(file.read_bytes()).hexdigest()!=row['sha256']:
  raise ReelError('Private preview integrity could not be verified','asset_changed',409)
 return file

def allowance_status(con,project_id):
 return read(con,project_id)['customerAllowanceConsumed']


def save_feedback(con,project_id,variant,message):
 """Free owner editing feedback; never triggers a model call or overwrites footage."""
 project=_project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise ReelError('An earlier campaign is read only','stale_revision',409)
 if variant not in ('wip','a','b') or not isinstance(message,str) or not 10<=len(message.strip())<=500:
  raise ReelError('Describe the edit you want in 10 to 500 characters','bad_feedback',400)
 if not con.execute('SELECT 1 FROM business_reel_edits WHERE project_id=? AND variant=?',(project_id,variant)).fetchone():
  raise ReelError('There is no footage to request an edit for','no_usable_shots',409)
 con.execute('INSERT INTO business_reel_feedback VALUES(?,?,?,?,?)',
  (uuid.uuid4().hex,project_id,variant,message.strip(),time.time()))
 con.commit()
 return read(con,project_id)


def internal_review_final_edit(con,project_id,variant,verdict,review_notes,reviewer,root,*,quality_approval=None):
 """Staff-only review of complete assembled edit. No customer-facing HTTP action."""
 state=read(con,project_id)
 if not state['isCurrentRevision'] or state['acceptedShots']!=len(SLOTS):
  raise ReelError('Every shot must pass internal creative review first','unfinished_reel',409)
 if variant not in ('a','b') or verdict not in ('accepted','rejected'):
  raise ReelError('Review one of the two actual complete cuts','invalid_final_review',400)
 if not isinstance(review_notes,str) or len(review_notes.strip())<20 or not isinstance(reviewer,str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,64}',reviewer):
  raise ReelError('A substantive internal creative-director verdict and identity are required','invalid_final_review',400)
 item=con.execute('SELECT * FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',(project_id,variant)).fetchone()
 if not item:raise ReelError('Assemble the real Reel before reviewing it','cut_not_ready',409)
 content_sha=_content_sha256(con,project_id,item,root)
 try:path=caption_exports.preview_file(con,project_id,variant,root)
 except caption_exports.CaptionExportError as exc:raise ReelError(str(exc),exc.code,exc.status) from exc
 expected_seconds=_saved_edit_duration(item['ordered_shots_json'])
 audio_row=con.execute('SELECT * FROM business_reel_audio_evidence WHERE edit_id=?',(item['id'],)).fetchone()
 try:locked_brand=brand_lock.read(con,project_id,root)
 except brand_lock.BrandLockError as exc:raise ReelError(str(exc),exc.code,exc.status) from exc
 if not locked_brand['locked']:
  raise ReelError('Final cut requires actual owner-confirmed logo and locked brand details','brand_not_locked',409)
 endcard=con.execute('SELECT sha256,brand_logo_sha256,status FROM business_reel_local_endcards WHERE project_id=?',(project_id,)).fetchone()
 if not endcard or endcard['brand_logo_sha256']!=locked_brand['logoSha256'] or endcard['status']!='accepted':
  raise ReelError('End card must render the real locked owner logo and pass internal review','endcard_brand_mismatch',409)
 manifest=json.loads(item['ordered_shots_json'])
 if not isinstance(manifest,list) or len(manifest)!=len(SLOTS) or any(not isinstance(part,dict) for part in manifest) or {part.get('slot') for part in manifest}!=set(SLOTS):
  raise ReelError('Rebuild both full edits with every accepted shot before final review','incomplete_cut',409)
 accepted={row['slot']:row['sha256'] for row in _shots(con,project_id) if row['internal_verdict']=='accepted'}
 for source in con.execute('SELECT slot,render_sha256 FROM business_reel_owner_media WHERE project_id=? AND approval_status=?',(project_id,'accepted')):
  if source['slot'] in accepted:raise ReelError('Multiple sources claim the same shot','source_conflict',409)
  accepted[source['slot']]=source['render_sha256']
 accepted['payoff']=endcard['sha256']
 if any(part.get('sha256')!=accepted.get(part['slot']) for part in manifest):
  raise ReelError('Rebuild using the current accepted footage and branded ending','stale_cut_source',409)
 # Explicit final-layout and brand/claims approval is required. Earlier private
 # WIPs have no audio proof and cannot be described as customer-ready.
 if not isinstance(quality_approval,dict):
  raise ReelError('Full Reel audio, branding and mobile-crop review required','final_quality_missing',409)
 track=captions.latest(con,project_id,variant)
 if track and track['style']['typeface']!=('sans' if locked_brand['style']=='minimal' else locked_brand['style']):
  raise ReelError('Save captions using the locked brand typography before final review','caption_brand_mismatch',409)
 if track and not all(quality_approval.get(key) is True for key in ('captionTextAndTimingVerified','captionLayoutReviewed')):
  raise ReelError('Review the exact subtitle words, timing and mobile placement before signing off','caption_review_missing',409)
 try:
  verdict_qc=delivery_qc.verify(path,expected_duration=expected_seconds,
    approval=quality_approval,has_audio_evidence=bool(audio_row))
 except delivery_qc.DeliveryError as exc:
  raise ReelError(str(exc),'final_quality_failed',409) from exc
 current_item=con.execute('SELECT * FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',(project_id,variant)).fetchone()
 if _content_sha256(con,project_id,current_item,root)!=content_sha or not read(con,project_id)['isCurrentRevision']:
  raise ReelError('Content changed while final quality checks were running','stale_review',409)
 if con.execute('SELECT 1 FROM business_reel_review_receipts WHERE project_id=? AND variant=? AND content_sha256=?',
   (project_id,variant,content_sha)).fetchone():
  raise ReelError('A verdict for this exact content is already recorded; preserve its history','review_already_recorded',409)
 con.execute('INSERT INTO business_reel_review_receipts VALUES(?,?,?,?,?,?,?,?,?)',
  (uuid.uuid4().hex,project_id,variant,item['revision_no'],content_sha,verdict,
   json.dumps({'reviewNotes':review_notes.strip()[:400],'verifiedQc':verdict_qc,
     'reviewer':reviewer}),reviewer,time.time()))
 con.commit()
 return read(con,project_id)


def prepare_local_endcard(con,project_id,root,*,name,cta,contact_url,owner_confirmed=False):
 """Generate a real 4-second branded ending locally, at zero provider cost.

 This does not approve the finished edit or claim the official master logo.
 Existing versions cannot be silently overwritten.
 """
 project=_project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise ReelError('Old campaign version is read only','stale_revision',409)
 existing=con.execute('SELECT * FROM business_reel_local_endcards WHERE project_id=?',(project_id,)).fetchone()
 locked=brand_lock.read(con,project_id,root)
 # An explicit brand upgrade gets a new file and a fresh review. The original
 # text-only asset and its evidence remain intact and recoverable.
 upgrade=bool(existing and not existing['brand_logo_sha256'] and locked['locked'])
 if existing and not upgrade:
  raise ReelError('Existing branded endcard and review cannot be overwritten','endcard_exists',409)
 brief=json.loads(project['brief_json'])
 try:
  name,cta,contact=native_endcard.check_details(name,cta,contact_url,brief['sourceUrl'],owner_confirmed)
 except native_endcard.EndcardError as e:
  raise ReelError(str(e),e.code,e.status) from e
 file_name=('endcard-brand-'+locked['logoSha256'][:12]+'.mp4') if upgrade else 'endcard-local.mp4'
 target=Path(root)/'reel_workbench'/project_id/file_name
 if target.exists() or target.is_symlink():
  raise ReelError('Existing ending bytes must be preserved','asset_exists',409)
 if locked['locked'] and (locked['brandName']!=name or locked['contactUrl']!=contact):
  raise ReelError('End card details must match the locked owner brand','brand_mismatch',409)
 try:meta=native_endcard.render(name,cta,contact,brief['sourceUrl'],owner_confirmed,target,
   brand=locked if locked['locked'] else None,
   logo_path=(Path(root)/'reel_workbench'/project_id/'owner-verified-brand.png') if locked['locked'] else None)
 except native_endcard.EndcardError as e:raise ReelError(str(e),e.code,e.status) from e
 values=(meta['sha256'],meta['bytes'],name,cta,contact,'awaiting_internal_review',None,None,time.time(),
  locked['logoSha256'] if locked['locked'] else None,file_name)
 if upgrade:
  original=_endcard_path(project_id,existing,root)
  if original.is_symlink() or not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest()!=existing['sha256']:
   target.unlink(missing_ok=True)
   raise ReelError('Original ending integrity could not be verified','source_changed',409)
  con.execute('INSERT INTO business_reel_endcard_history VALUES(?,?,?,?,?,?)',
   (uuid.uuid4().hex,project_id,existing['sha256'],original.name,json.dumps(dict(existing)),time.time()))
  con.execute('UPDATE business_reel_local_endcards SET sha256=?,bytes=?,brand_name=?,cta=?,contact_url=?,status=?,review_reason=?,reviewer=?,created=?,brand_logo_sha256=?,file_name=? WHERE project_id=?',
   (*values,project_id))
 else:
  con.execute('INSERT INTO business_reel_local_endcards (project_id,sha256,bytes,brand_name,cta,contact_url,status,review_reason,reviewer,created,brand_logo_sha256,file_name) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
   (project_id,*values))
 con.commit()
 return read(con,project_id)


def attach_authorised_audio(con,project_id,variant,root,audio_path,*,rights_attestation,owner_confirmed=False,voiceover_path=None,voice_rights_attestation=None):
 """Create a new immutable audio-backed edit revision, never alter a WIP.

 This is an internal production action. It does not approve social publication.
 """
 project=_project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise ReelError('Source business version changed','stale_revision',409)
 if variant not in ('a','b'):
  raise ReelError('Only a complete alternative can receive final sound','invalid_variant',400)
 if owner_confirmed is not True or not isinstance(rights_attestation,str) or len(rights_attestation.strip())<25 or len(rights_attestation)>400:
  raise ReelError('A genuine owner media-rights attestation is required','audio_rights_missing',403)
 previous=con.execute('SELECT * FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',
  (project_id,variant)).fetchone()
 if not previous:raise ReelError('Assemble the full source footage before mixing audio','no_edit',409)
 if con.execute('SELECT 1 FROM business_reel_audio_evidence WHERE edit_id=?',(previous['id'],)).fetchone():
  raise ReelError('Soundtrack has already been fitted to this edit; preserve its history','already_soundtracked',409)
 audio=Path(audio_path)
 if audio.is_symlink() or not audio.is_file() or not 1000<audio.stat().st_size<=15*1024*1024:
  raise ReelError('Unsafe or missing rights-checked audio','unsafe_audio',409)
 audio_digest=hashlib.sha256(audio.read_bytes()).hexdigest()
 voice=None;voice_digest=None
 if voiceover_path is not None:
  if not isinstance(voice_rights_attestation,str) or not 25<=len(voice_rights_attestation.strip())<=400:
   raise ReelError('Speech must have separate audio rights confirmation','voice_rights_missing',403)
  voice=Path(voiceover_path)
  if voice.is_symlink() or not voice.is_file() or not 1000<voice.stat().st_size<=15*1024*1024:
   raise ReelError('No verifiable rights-cleared voiceover file','unsafe_voice',409)
  voice_digest=hashlib.sha256(voice.read_bytes()).hexdigest()
 video=preview_file(con,project_id,variant,root)
 prior_captions=captions.latest(con,project_id,variant)
 if prior_captions:
  try:captions.file_for(con,project_id,variant,root)
  except captions.CaptionError as exc:raise ReelError(str(exc),exc.code,exc.status) from exc
 length=_saved_edit_duration(previous['ordered_shots_json'])
 next_version=previous['revision_no']+1
 out=Path(root)/'reel_workbench'/project_id/(variant+'-'+str(next_version)+'.mp4')
 if out.exists() or out.is_symlink():raise ReelError('This version already exists','asset_exists',409)
 tmp=out.with_name('.'+out.stem+'-pending.mp4')
 try:
  cmd=['ffmpeg','-y','-nostdin','-v','error','-i',str(video),
    '-stream_loop','-1','-i',str(audio)]
  if voice is not None:
   cmd+=['-i',str(voice)]
   # Compressor keys off the real voiceover: music ducks when speech appears,
   # without guessing a transcript or permanently baking visual subtitles.
   audio_filter=(f'[1:a]volume=0.28,atrim=duration={length:.3f},'
     f'aresample=44100[m];[2:a]atrim=duration={length:.3f},aresample=44100,'
     'apad=whole_dur='+f'{length:.3f}'+',asplit=2[v][side];'
     '[m][side]sidechaincompress=threshold=0.02:ratio=8:attack=18:release=260[duck];'
     '[duck][v]amix=inputs=2:duration=first:dropout_transition=0,'
     'alimiter=limit=0.95,'
     f'afade=t=in:st=0:d=0.2,afade=t=out:st={max(.2,length-.65):.3f}:d=0.65[a]')
  else:
   audio_filter=(f'[1:a]volume=0.58,atrim=duration={length:.3f},'
     'apad=whole_dur='+f'{length:.3f},'
     f'afade=t=in:st=0:d=0.2,afade=t=out:st={max(.2,length-.65):.3f}:d=0.65[a]')
  cmd+=['-t',str(length),'-filter_complex',audio_filter,'-map','0:v:0',
    '-map','[a]','-c:v','copy','-c:a','aac','-b:a','160k',
    '-movflags','+faststart',str(tmp)]
  subprocess.run(cmd,check=True,capture_output=True,timeout=75)
  if not tmp.is_file() or not 5000<tmp.stat().st_size<=65*1024*1024:
   raise ReelError('The private audio mix was not completed','audio_mix_failed',409)
  # Decode/probe output before writing it into the version ledger.
  probe=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type',
   '-of','json',str(tmp)],check=True,capture_output=True,text=True,timeout=15)
  streams=[x['codec_type'] for x in json.loads(probe.stdout)['streams']]
  if streams.count('video')!=1 or streams.count('audio')!=1:
   raise ReelError('Final audio mix has incorrect media streams','audio_mix_failed',409)
  if audio.is_symlink() or hashlib.sha256(audio.read_bytes()).hexdigest()!=audio_digest or (
    voice is not None and (voice.is_symlink() or hashlib.sha256(voice.read_bytes()).hexdigest()!=voice_digest)):
   raise ReelError('Audio source changed during the mix; original approval is stale','audio_source_changed',409)
  os.replace(tmp,out)
 except (OSError,subprocess.SubprocessError) as exc:
  raise ReelError('Local audio mix could not be produced','audio_mix_failed',409) from exc
 finally:tmp.unlink(missing_ok=True)
 payload=out.read_bytes()
 edit_id=uuid.uuid4().hex
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  out.unlink(missing_ok=True)
  raise ReelError('Campaign changed during audio mixing','stale_revision',409)
 inherited_caption=None
 try:
  con.execute('INSERT INTO business_reel_edits VALUES(?,?,?,?,?,?,?,?,?)',
   (edit_id,project_id,variant,previous['ordered_shots_json'],
    hashlib.sha256(payload).hexdigest(),len(payload),'internal_audio_review_only',time.time(),next_version))
  con.execute('INSERT INTO business_reel_audio_evidence (edit_id,project_id,original_sha256,track_sha256,rights_attestation,owner_confirmed,created,voice_sha256,voice_rights_attestation) VALUES(?,?,?,?,?,?,?,?,?)',
   (edit_id,project_id,previous['sha256'],audio_digest,rights_attestation.strip(),1,time.time(),
    voice_digest,voice_rights_attestation.strip() if voice is not None else None))
  # Pick up even a first caption track saved while the local mix was running.
  inherited_caption=captions.inherit_for_audio_edit(con,project_id,variant,root,
   from_edit_revision=previous['revision_no'],to_edit_revision=next_version)
  con.commit()
 except Exception as exc:
  con.rollback();out.unlink(missing_ok=True)
  if inherited_caption:
   # Only the sidecar successfully created by this attempt may be removed.
   (out.parent/f'{variant}-edit{next_version}-captions{inherited_caption["captionRevision"]}.vtt').unlink(missing_ok=True)
  if isinstance(exc,captions.CaptionError):raise ReelError(str(exc),exc.code,exc.status) from exc
  raise
 return read(con,project_id)


def record_local_owner_choice(con,project_id,variant,root,*,owner_reference,approval_note,owner_confirmed=False,
expected_content_sha256=None,expected_review_set_sha256=None):
 """Record consent for the exact two quality-checked local renditions shown.

 This local record is not production-authenticated consent or permission to
 schedule, publish, charge an allowance or generate more footage.
 """
 state=read(con,project_id)
 if not state['isCurrentRevision']:
  raise ReelError('An earlier campaign is read only','stale_revision',409)
 if owner_confirmed is not True or not isinstance(owner_reference,str) or not 5<=len(owner_reference.strip())<=80 or not isinstance(approval_note,str) or not 18<=len(approval_note.strip())<=350:
  raise ReelError('Explicit owner selection with meaningful feedback required','owner_consent_missing',403)
 if variant not in ('a','b') or not state['bothEditsQualityChecked'] or not state['brandLock']['locked']:
  raise ReelError('Both complete edits must pass internal QC and use the locked owner brand','not_ready_for_owner',409)
 selected=next((x for x in state['edits'] if x['variant']==variant),None)
 if not selected or expected_content_sha256!=selected['contentSha256'] or expected_review_set_sha256!=state['reviewSetSha256']:
  raise ReelError('Refresh and review the current two edits before choosing','stale_review',409)
 if state['localOwnerChoiceRecorded']:
  raise ReelError('Earlier owner selection must be preserved, not overwritten','choice_exists',409)
 verified={}
 for name in ('a','b'):
  record=con.execute('SELECT * FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',
   (project_id,name)).fetchone()
  verified[name]=_content_sha256(con,project_id,record,root)
 if verified.get(variant)!=expected_content_sha256 or _review_set_sha256(verified)!=expected_review_set_sha256:
  raise ReelError('Content changed during owner review; refresh both edits','stale_review',409)
 try:
  con.execute('INSERT INTO business_reel_owner_choice_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
   (uuid.uuid4().hex,project_id,variant,selected['revision'],expected_content_sha256,
     expected_review_set_sha256,state['brandLock']['logoSha256'],
     approval_note.strip(),owner_reference.strip(),time.time()))
 except sqlite3.IntegrityError as exc:
  raise ReelError('A choice for these exact edits is already preserved','choice_exists',409) from exc
 con.commit()
 return read(con,project_id)
