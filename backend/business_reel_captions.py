"""Editable, owner-verified WebVTT sidecars bound to immutable video revisions."""
from __future__ import annotations
import hashlib,html,json,math,os,re,time,uuid
from pathlib import Path

class CaptionError(ValueError):
 def __init__(self,message,code='caption_invalid',status=400):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 con.execute('''CREATE TABLE IF NOT EXISTS business_reel_caption_tracks(
   id TEXT PRIMARY KEY,project_id TEXT NOT NULL,variant TEXT NOT NULL,
   edit_revision INTEGER NOT NULL,track_revision INTEGER NOT NULL,
   source TEXT NOT NULL,cues_json TEXT NOT NULL,brand_style_json TEXT NOT NULL,
   vtt_sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,owner_verified INTEGER NOT NULL,
   created REAL NOT NULL,UNIQUE(project_id,variant,edit_revision,track_revision))''')
 columns={row[1] for row in con.execute('PRAGMA table_info(business_reel_caption_tracks)')}
 if 'inherited_from' not in columns:
  con.execute('ALTER TABLE business_reel_caption_tracks ADD COLUMN inherited_from TEXT')

def _time(val):
 if type(val) not in (int,float) or not math.isfinite(val) or val<0:raise CaptionError('Timestamp must be positive finite seconds')
 return round(val,3)

def _fmt(seconds):
 millis=round(seconds*1000)
 hr,r=divmod(millis,3600000);mi,r=divmod(r,60000);ss,ms=divmod(r,1000)
 return f'{hr:02d}:{mi:02d}:{ss:02d}.{ms:03d}'

def _clean_cues(items,duration):
 if not isinstance(items,list) or not 1<=len(items)<=50:raise CaptionError('Provide 1–50 verified subtitle cues')
 output=[];prev=0
 for c in items:
  if not isinstance(c,dict) or set(c)!={'start','end','text'}:raise CaptionError('Use start, end and text for each cue')
  start=_time(c['start']);end=_time(c['end'])
  if end<=start+.22 or start<prev-.001 or end>duration+.05:
   raise CaptionError('Captions overlap, are too short or exceed actual footage')
  text=c['text']
  if not isinstance(text,str) or not 1<=len(text.strip())<=80 or '\n' in text or '\r' in text or re.search(r'[\x00-\x1f]',text):
   raise CaptionError('Captions must be a single legible line under 80 characters')
  output.append({'start':start,'end':end,'text':text.strip()});prev=end
 return output

def _current_project(con,project_id):
 import business_reel_workbench as reel
 import business_marketing_drafts as drafts
 project=reel._project(con,project_id)
 if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
  raise CaptionError('Campaign changed; captions belong to an archived revision','stale_revision',409)
 return project

def _track_path(root,project_id,variant,edit_revision,track_revision):
 folder=Path(root)/'reel_workbench'/project_id
 if folder.is_symlink() or not folder.is_dir():raise CaptionError('Real Reel output directory missing','missing_project',409)
 return folder/f'{variant}-edit{edit_revision}-captions{track_revision}.vtt'

def _verified_track(row,root):
 path=_track_path(root,row['project_id'],row['variant'],row['edit_revision'],row['track_revision'])
 if path.is_symlink() or not path.is_file() or path.stat().st_size!=row['bytes']:
  raise CaptionError('Saved subtitle text or timing was changed','changed_source',409)
 blob=path.read_bytes()
 if hashlib.sha256(blob).hexdigest()!=row['vtt_sha256']:
  raise CaptionError('Saved subtitle text or timing was changed','changed_source',409)
 return path,blob

def _insert(con,project_id,variant,edit_revision,track_revision,source,cues_json,style_json,blob,inherited_from=None,owner_verified=1):
 con.execute('''INSERT INTO business_reel_caption_tracks
  (id,project_id,variant,edit_revision,track_revision,source,cues_json,brand_style_json,
   vtt_sha256,bytes,owner_verified,created,inherited_from) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
  (uuid.uuid4().hex,project_id,variant,edit_revision,track_revision,source,cues_json,style_json,
   hashlib.sha256(blob).hexdigest(),len(blob),owner_verified,time.time(),inherited_from))

def save(con,project_id,variant,root,*,cues,source,expected_edit_revision,expected_caption_revision,owner_confirmed=False,style=None):
 import business_reel_workbench as reel
 import business_reel_brand_lock as brand
 if variant not in ('a','b','wip'):raise CaptionError('Unknown edit variant')
 if source not in ('owner_verified_transcript','owner_written_text') or owner_confirmed is not True:
  raise CaptionError('Never invent the transcription of unverified speech','transcript_unverified',403)
 if type(expected_edit_revision) is not int or expected_edit_revision<1 or type(expected_caption_revision) is not int or expected_caption_revision<0:
  raise CaptionError('Exact edit and caption revisions are required','stale_revision',409)
 if not isinstance(style,dict) or set(style)!={'typeface','weight','placement'}:
  raise CaptionError('Caption appearance must be explicit')
 if style['typeface'] not in ('editorial','modern','sans') or style['weight'] not in ('regular','bold') or style['placement'] not in ('bottom_safe','middle_safe'):
  raise CaptionError('Caption styling must use platform-safe templates')
 owned=not con.in_transaction
 if owned:con.execute('BEGIN IMMEDIATE')
 token='caption_save_'+uuid.uuid4().hex;con.execute('SAVEPOINT '+token)
 file=None;created=False;released=False
 try:
  _current_project(con,project_id)
  lock=brand.read(con,project_id,root)
  if lock['locked'] and style['typeface']!=('sans' if lock['style']=='minimal' else lock['style']):
   raise CaptionError('Verified brand typography is locked; captions may vary only within approved style','brand_style_locked',409)
  existing=con.execute('SELECT * FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',(project_id,variant)).fetchone()
  if not existing:raise CaptionError('Actual Reel edit must exist before captions are written','no_video',409)
  prior=con.execute('SELECT COALESCE(MAX(track_revision),0) FROM business_reel_caption_tracks WHERE project_id=? AND variant=? AND edit_revision=?',(project_id,variant,existing['revision_no'])).fetchone()[0]
  if existing['revision_no']!=expected_edit_revision or prior!=expected_caption_revision:
   raise CaptionError('The preview or caption track changed; reload before saving','stale_revision',409)
  try:reel.preview_file(con,project_id,variant,root)
  except reel.ReelError as exc:raise CaptionError('The actual preview media has changed','changed_source',409) from exc
  if prior:
   previous=con.execute('SELECT * FROM business_reel_caption_tracks WHERE project_id=? AND variant=? AND edit_revision=? AND track_revision=?',(project_id,variant,existing['revision_no'],prior)).fetchone()
   _verified_track(previous,root)
  data=_clean_cues(cues,reel._saved_edit_duration(existing['ordered_shots_json']))
  version=prior+1
  label='WEBVTT\n\n'+''.join(f'{i+1}\n{_fmt(x["start"])} --> {_fmt(x["end"])}\n{html.escape(x["text"],quote=False)}\n\n' for i,x in enumerate(data))
  blob=label.encode('utf8');file=_track_path(root,project_id,variant,existing['revision_no'],version)
  if file.exists() or file.is_symlink():raise CaptionError('Previous caption revision must be preserved','already_exists',409)
  with file.open('xb') as f:
   created=True;f.write(blob)
  os.chmod(file,0o600)
  _insert(con,project_id,variant,existing['revision_no'],version,source,json.dumps(data),json.dumps(style),blob)
  con.execute('RELEASE SAVEPOINT '+token);released=True
  if owned:con.commit()
 except Exception:
  try:
   if not released:
    con.execute('ROLLBACK TO SAVEPOINT '+token);con.execute('RELEASE SAVEPOINT '+token)
  finally:
   if owned:con.rollback()
   if created:file.unlink(missing_ok=True)
  raise
 return latest(con,project_id,variant)

def latest(con,project_id,variant):
 edit=con.execute('SELECT revision_no FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',(project_id,variant)).fetchone()
 if not edit:return None
 row=con.execute('SELECT * FROM business_reel_caption_tracks WHERE project_id=? AND variant=? AND edit_revision=? ORDER BY track_revision DESC LIMIT 1',(project_id,variant,edit['revision_no'])).fetchone()
 if not row:return None
 return {'variant':variant,'editRevision':row['edit_revision'],'captionRevision':row['track_revision'],
  'source':row['source'],'style':json.loads(row['brand_style_json']),'cues':json.loads(row['cues_json']),
  'sha256':row['vtt_sha256'],'inheritedFrom':row['inherited_from'],'externalSidecar':True,
  'bakedIntoVideo':False,'ownerVerifiedText':bool(row['owner_verified']),'published':False}

def file_for(con,project_id,variant,root):
 data=latest(con,project_id,variant)
 if data is None:raise CaptionError('No caption track saved','not_found',404)
 row=con.execute('SELECT * FROM business_reel_caption_tracks WHERE project_id=? AND variant=? AND edit_revision=? AND track_revision=?',(project_id,variant,data['editRevision'],data['captionRevision'])).fetchone()
 return _verified_track(row,root)[0]

def inherit_for_audio_edit(con,project_id,variant,root,*,from_edit_revision,to_edit_revision):
 """Carry verified text across a video-copy audio transform; caller owns commit."""
 import business_reel_workbench as reel
 if variant not in ('a','b','wip') or type(from_edit_revision) is not int or type(to_edit_revision) is not int or from_edit_revision<1 or to_edit_revision!=from_edit_revision+1:
  raise CaptionError('Caption inheritance requires consecutive exact edit revisions','stale_revision',409)
 _current_project(con,project_id)
 old=con.execute('SELECT * FROM business_reel_edits WHERE project_id=? AND variant=? AND revision_no=?',(project_id,variant,from_edit_revision)).fetchone()
 new=con.execute('SELECT * FROM business_reel_edits WHERE project_id=? AND variant=? ORDER BY revision_no DESC LIMIT 1',(project_id,variant)).fetchone()
 if not old or not new or new['revision_no']!=to_edit_revision or json.loads(old['ordered_shots_json'])!=json.loads(new['ordered_shots_json']):
  raise CaptionError('Visual timing changed; captions need a new owner review','visual_timing_changed',409)
 row=con.execute('SELECT * FROM business_reel_caption_tracks WHERE project_id=? AND variant=? AND edit_revision=? ORDER BY track_revision DESC LIMIT 1',(project_id,variant,from_edit_revision)).fetchone()
 if not row:return None
 if row['owner_verified']!=1:
  raise CaptionError('Only previously verified text may follow copied video','transcript_unverified',403)
 _,blob=_verified_track(row,root)
 _clean_cues(json.loads(row['cues_json']),reel._saved_edit_duration(new['ordered_shots_json']))
 folder=Path(root)/'reel_workbench'/project_id
 oldfile=folder/f'{variant}-{from_edit_revision}.mp4'
 if from_edit_revision==1 and not oldfile.exists() and not oldfile.is_symlink():oldfile=folder/f'{variant}.mp4'
 if oldfile.is_symlink() or not oldfile.is_file() or oldfile.stat().st_size!=old['bytes'] or hashlib.sha256(oldfile.read_bytes()).hexdigest()!=old['sha256']:
  raise CaptionError('The original captioned video has changed','changed_source',409)
 try:reel.preview_file(con,project_id,variant,root)
 except reel.ReelError as exc:raise CaptionError('The new audio preview has changed','changed_source',409) from exc
 if con.execute('SELECT 1 FROM business_reel_caption_tracks WHERE project_id=? AND variant=? AND edit_revision=?',(project_id,variant,to_edit_revision)).fetchone():
  raise CaptionError('Preserve the existing caption decision on this edit','already_exists',409)
 file=_track_path(root,project_id,variant,to_edit_revision,1)
 if file.exists() or file.is_symlink():raise CaptionError('Previous caption revision must be preserved','already_exists',409)
 # Never let RELEASE become an outermost commit; caller owns the transaction.
 if not con.in_transaction:con.execute('BEGIN')
 token='caption_inherit_'+uuid.uuid4().hex;con.execute('SAVEPOINT '+token)
 created=False
 try:
  with file.open('xb') as f:
   created=True;f.write(blob)
  os.chmod(file,0o600)
  _insert(con,project_id,variant,to_edit_revision,1,row['source'],row['cues_json'],row['brand_style_json'],blob,row['id'],row['owner_verified'])
  con.execute('RELEASE SAVEPOINT '+token)
 except Exception:
  try:
   con.execute('ROLLBACK TO SAVEPOINT '+token);con.execute('RELEASE SAVEPOINT '+token)
  finally:
   if created:file.unlink(missing_ok=True)
  raise
 return latest(con,project_id,variant)
