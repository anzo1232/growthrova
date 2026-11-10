"""Safe owner-authorised video selection from the existing local Business media library.

No internet, AI generation, or client publication. Accepted source media takes
priority over generation. Maintains original bytes and records a separate
portrait, full-frame export without zoom/cropping the subject.
"""
from __future__ import annotations
import hashlib,json,os,sqlite3,subprocess,tempfile,time,uuid
from pathlib import Path
import business_reel_visual_intelligence as vision
import business_reel_art_review as art
import business_marketing_drafts as drafts

MAX_INPUT=170*1024*1024
class OwnerMediaError(ValueError):
 def __init__(self,message,code='owner_media_blocked',status=409):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 con.execute('''CREATE TABLE IF NOT EXISTS business_reel_owner_media(
  id TEXT PRIMARY KEY,project_id TEXT NOT NULL,slot TEXT NOT NULL,
  source_id TEXT NOT NULL,original_sha256 TEXT NOT NULL,render_sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,source_width INTEGER NOT NULL,source_height INTEGER NOT NULL,
  qc_json TEXT NOT NULL,owner_rights_note TEXT NOT NULL,approval_status TEXT NOT NULL,
  reviewer TEXT,review_reason TEXT,created REAL NOT NULL,
  UNIQUE(project_id,slot),UNIQUE(project_id,source_id))''')
 con.execute('''CREATE TABLE IF NOT EXISTS business_reel_still_references(
  project_id TEXT NOT NULL,slot TEXT NOT NULL,photo_id TEXT NOT NULL,
  image_sha256 TEXT NOT NULL,owner_rights_recorded INTEGER NOT NULL,
  created REAL NOT NULL,PRIMARY KEY(project_id,slot))''')

def _probe(file):
 try:
  result=subprocess.run(['ffprobe','-v','error','-show_entries',
   'format=duration:stream=codec_type,width,height','-of','json',str(file)],
   check=True,capture_output=True,text=True,timeout=15)
  result=json.loads(result.stdout)
  streams=[x for x in result.get('streams',[]) if x.get('codec_type')=='video']
  sec=float(result['format']['duration'])
  if len(streams)!=1 or not 4<=sec<=240:raise ValueError()
  w,h=int(streams[0]['width']),int(streams[0]['height'])
  if w<320 or h<320 or w*h>3840*2160:raise ValueError()
  return w,h,sec
 except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError):
  raise OwnerMediaError('Owner video dimensions or duration are unsupported','invalid_media',422) from None

def _provider_attempt_blocks(con,project,project_id,slot):
 # Keep every provider receipt/cost row. Only reconciled terminal failures permit
 # a new owner-media fallback; attached shots are independently immutable.
 rows=con.execute('SELECT status,actual_credits FROM runway_cinematic_shots WHERE draft_id=? AND shot_key=?',
  (project['draft_id'],'workbench:'+project_id+':'+slot)).fetchall()
 return any(row['status'] not in ('failed','cancelled','rejected','rejected_quality')
  or row['actual_credits'] is None for row in rows)

def select(con,project_id,slot,source_id,root,*,owner_confirmed=False,rights_note=''):
 import business_reel_workbench as reel
 project=reel._project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise OwnerMediaError('Campaign changed: source must be reapproved','stale_revision')
 if slot not in reel.SLOTS[:3]:raise OwnerMediaError('End card is not a footage slot','bad_slot',400)
 if owner_confirmed is not True or not isinstance(rights_note,str) or not 25<=len(rights_note.strip())<=350:
  raise OwnerMediaError('Owner must confirm permission and original footage use','rights_unconfirmed',403)
 if not isinstance(source_id,str) or len(source_id)!=32 or any(c not in '0123456789abcdef' for c in source_id):
  raise OwnerMediaError('Invalid local media reference','bad_media_id',400)
 if _provider_attempt_blocks(con,project,project_id,slot):
  raise OwnerMediaError('First reconcile the original paid provider attempt and its cost','existing_provider_attempt',409)
 if con.execute('SELECT 1 FROM business_reel_owner_media WHERE project_id=? AND slot=?',(project_id,slot)).fetchone():
  raise OwnerMediaError('Earlier real media decision is immutable','already_selected')
 if con.execute('SELECT 1 FROM business_reel_shots WHERE project_id=? AND slot=?',(project_id,slot)).fetchone():
  raise OwnerMediaError('Original provider shot already exists; keep it','provider_source_exists')
 if con.execute('SELECT 1 FROM business_reel_owner_media WHERE project_id=? AND source_id=?',(project_id,source_id)).fetchone():
  raise OwnerMediaError('This original video is already used in another shot; choose another clip','source_already_used',409)
 src=con.execute('SELECT * FROM sources WHERE id=?',(source_id,)).fetchone()
 if not src or src['status']!='done' or src['mime'] not in ('video/mp4','video/quicktime','video/webm'):
  raise OwnerMediaError('Choose a scanned local video with verified source','source_unavailable',409)
 ext={'video/mp4':'.mp4','video/quicktime':'.mov','video/webm':'.webm'}[src['mime']]
 original=Path(root)/'files'/(source_id+ext)
 if original.is_symlink() or not original.is_file() or original.stat().st_size!=src['bytes'] or original.stat().st_size>MAX_INPUT:
  raise OwnerMediaError('Local video is missing, changed, or too large','source_changed')
 digest=hashlib.sha256(original.read_bytes()).hexdigest()
 w,h,duration=_probe(original)
 outfolder=Path(root)/'reel_workbench'/project_id
 if outfolder.is_symlink():raise OwnerMediaError('Unsafe reel folder','unsafe_path')
 outfolder.mkdir(parents=True,exist_ok=True,mode=0o700)
 target=outfolder/('real-'+slot+'.mp4')
 if target.exists() or target.is_symlink():raise OwnerMediaError('Preserve existing staged media','asset_exists')
 tmp=outfolder/('.real-'+slot+'-pending.mp4')
 length=min(12,duration)
 # No face/subject zoom or distortion: fit the entire owner's video in frame.
 filtergraph='scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=24'
 try:
  rendered=subprocess.run(['ffmpeg','-y','-nostdin','-v','error','-xerror','-i',str(original),'-t',str(length),'-vf',filtergraph,
   '-an','-c:v','libx264','-preset','veryfast','-crf','23','-movflags','+faststart',str(tmp)],
   capture_output=True,timeout=85)
  # A decoder may conceal broken frames and still return success. Never turn
  # damaged original footage into a seemingly valid owner-approved source.
  if rendered.returncode or rendered.stderr.strip():
   raise OwnerMediaError('Original footage contains damaged video data; upload an intact original','source_decode_failed',422)
  report=vision.run_staged_review(tmp,expected_duration=length,expected_brand=project['draft_id'])
  if tmp.stat().st_size>65*1024*1024:raise OwnerMediaError('Video segment too large','source_too_large')
  os.replace(tmp,target)
 except (OSError,subprocess.SubprocessError,vision.VisualReviewError,OwnerMediaError) as exc:
  if isinstance(exc,OwnerMediaError):raise
  raise OwnerMediaError('Could not securely prepare the approved source video','prepare_failed',422) from exc
 finally:tmp.unlink(missing_ok=True)
 filehash=hashlib.sha256(target.read_bytes()).hexdigest()
 status='awaiting_internal_review' if report['fast']['technicalMotionPass'] else 'technical_rejected'
 assetid=uuid.uuid4().hex
 try:
  if original.is_symlink() or hashlib.sha256(original.read_bytes()).hexdigest()!=digest:
   raise OwnerMediaError('Original video changed while its portrait copy was prepared','source_changed',409)
  if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
   raise OwnerMediaError('Campaign changed during footage preparation','stale_revision',409)
  con.execute('INSERT INTO business_reel_owner_media VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
   (assetid,project_id,slot,source_id,digest,filehash,target.stat().st_size,w,h,json.dumps(report),
    rights_note.strip(),status,None,None,time.time()))
  con.commit()
 except Exception as exc:
  con.rollback();target.unlink(missing_ok=True)
  if isinstance(exc,sqlite3.IntegrityError):
   raise OwnerMediaError('That original footage or shot was selected already; refresh the Reel','selection_conflict',409) from exc
  raise
 return {'id':assetid,'slot':slot,'sourceType':'owner_authorised_video',
  'originalSha256':digest,'preparedSha256':filehash,'originalDimensions':[w,h],
  'fullFrameRetained':True,'sourceTimeSeconds':round(length,2),
  'status':status,'newPaidCalls':0,'humanReviewRequired':True,'approvedForPosting':False}

def file_for(con,project_id,slot,root):
 row=con.execute('SELECT * FROM business_reel_owner_media WHERE project_id=? AND slot=?',(project_id,slot)).fetchone()
 if not row:raise OwnerMediaError('No approved business footage in this slot','no_source')
 path=Path(root)/'reel_workbench'/project_id/('real-'+slot+'.mp4')
 if path.is_symlink() or not path.is_file() or path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['render_sha256']:
  raise OwnerMediaError('Owner media cannot be changed after review','source_changed')
 return row,path

def internal_review(con,project_id,slot,decision,reason,reviewer):
 import business_reel_workbench as reel
 project=reel._project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise OwnerMediaError('This review belongs to an earlier campaign revision','stale_revision',409)
 if decision not in ('accepted','rejected') or not isinstance(reason,str) or len(reason.strip())<20:
  raise OwnerMediaError('Detailed internal verdict required','review_invalid',400)
 art.reviewer_id(reviewer)
 row=con.execute('SELECT * FROM business_reel_owner_media WHERE project_id=? AND slot=?',(project_id,slot)).fetchone()
 if not row or row['approval_status']!='awaiting_internal_review':
  raise OwnerMediaError('Only viable unreviewed owner media may be accepted','review_not_allowed')
 if decision=='accepted':
  assessment=con.execute('SELECT * FROM business_reel_visual_reviews WHERE project_id=? AND slot=? AND source_sha256=?',
   (project_id,slot,row['render_sha256'])).fetchone()
  if not assessment or not json.loads(assessment['report_json'])['allPassed']:
   raise OwnerMediaError('Source authenticity alone does not prove visual quality','visual_review_required')
 con.execute('UPDATE business_reel_owner_media SET approval_status=?,reviewer=?,review_reason=? WHERE id=?',
  (decision,reviewer,reason.strip()[:300],row['id']))
 con.commit()
 return {'status':decision,'slot':slot,'customerAllowanceCharged':0,'newPaidCalls':0}


def stage_approved_photo(con,project_id,slot,photo_id,root,*,owner_confirmed=False):
 """Reuse already owner-declared website imagery as a future shot reference.

 A still is NEVER counted as completed footage and has no paid provider call.
 Only separately approved image-to-video may turn it into a shot.
 """
 import business_reel_workbench as reel
 import business_website_media as website_media
 project=reel._project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise OwnerMediaError('Business campaign changed; reconfirm this photo on its latest version','stale_revision',409)
 if slot not in reel.SLOTS[:3]:raise OwnerMediaError('Cannot substitute a photo for the branded CTA','bad_slot',400)
 if _provider_attempt_blocks(con,project,project_id,slot):
  raise OwnerMediaError('Reconcile the original paid task before attaching a photo','existing_provider_attempt',409)
 if owner_confirmed is not True:raise OwnerMediaError('Owner must reconfirm image usage rights','rights_unconfirmed',403)
 if con.execute('SELECT 1 FROM business_reel_owner_media WHERE project_id=? AND slot=?',(project_id,slot)).fetchone():
  raise OwnerMediaError('Genuine footage has priority; do not overwrite it','video_source_exists',409)
 if con.execute('SELECT 1 FROM business_reel_shots WHERE project_id=? AND slot=?',(project_id,slot)).fetchone():
  raise OwnerMediaError('An original paid shot already exists','provider_source_exists',409)
 if con.execute('SELECT 1 FROM business_reel_still_references WHERE project_id=? AND slot=?',(project_id,slot)).fetchone():
  raise OwnerMediaError('Preserve the previous photo selection','photo_already_selected',409)
 try:
  path=website_media.photo_path(con,project['draft_id'],photo_id,root)
 except website_media.MediaError as exc:
  raise OwnerMediaError(str(exc),'photo_unavailable',409) from exc
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 con.execute('INSERT INTO business_reel_still_references VALUES(?,?,?,?,?,?)',
  (project_id,slot,photo_id,digest,1,time.time()))
 con.commit()
 return {'projectId':project_id,'slot':slot,'photoId':photo_id,
   'sourceType':'owner_declared_business_photo','sha256':digest,
   'status':'awaiting_separate_image_to_video_approval',
   'providerCreditsUsed':0,'countsAsAcceptedFootage':False,'autoGeneration':False}

def planned_photo(con,project_id,slot):
 row=con.execute('SELECT * FROM business_reel_still_references WHERE project_id=? AND slot=?',(project_id,slot)).fetchone()
 if not row:return None
 return {'photoId':row['photo_id'],'sha256':row['image_sha256'],
  'rightsReconfirmed':bool(row['owner_rights_recorded']),
  'status':'awaiting_separate_image_to_video_approval',
  'autoGeneration':False,'countsAsAcceptedFootage':False}
