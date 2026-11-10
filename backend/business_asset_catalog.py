"""Private, immutable metadata for already received customer assets; no upload or approval."""
import hashlib,json,re,subprocess
from pathlib import Path
class AssetError(ValueError):pass
class AssetStorageLimit(AssetError):pass
class AssetIntakeConflict(AssetError):pass
FIELDS={'organisationId','businessId','assetId','mediaKind','mimeType','sourceSha256','sourceBytes','rightsStatement','consentStatus','originalName'}
MIMES={'logo':{'image/png','image/jpeg','image/webp'},'photo':{'image/png','image/jpeg','image/webp'},'video':{'video/mp4','video/quicktime','video/webm'}}
ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,79}\Z'); SHA=re.compile(r'[a-f0-9]{64}\Z')
def encode(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(x):return hashlib.sha256(x.encode()).hexdigest()
def initialise(con):
 con.execute('CREATE TABLE IF NOT EXISTS business_asset_catalog(organisation_id TEXT NOT NULL,business_id TEXT NOT NULL,asset_id TEXT NOT NULL,original_sha TEXT NOT NULL,record_json TEXT NOT NULL,record_sha TEXT NOT NULL,PRIMARY KEY(organisation_id,business_id,asset_id))')

def initialise_originals(con):
 """Offline original bytes in the existing catalogue database, never cloud storage."""
 initialise(con)
 con.execute('''CREATE TABLE IF NOT EXISTS business_asset_originals(
 organisation_id TEXT NOT NULL,business_id TEXT NOT NULL,asset_id TEXT NOT NULL,
 owner_id TEXT NOT NULL,original_bytes BLOB NOT NULL,
 PRIMARY KEY(organisation_id,business_id,asset_id))''')
 con.execute('''CREATE TABLE IF NOT EXISTS business_asset_withdrawals(
 organisation_id TEXT NOT NULL, business_id TEXT NOT NULL, asset_id TEXT NOT NULL,
 owner_id TEXT NOT NULL, reason TEXT NOT NULL, withdrawn_at TEXT NOT NULL,
 PRIMARY KEY(organisation_id,business_id,asset_id))''')
 con.execute('''CREATE TABLE IF NOT EXISTS business_asset_intake_receipts(
 organisation_id TEXT NOT NULL, owner_id TEXT NOT NULL, document_id TEXT NOT NULL,
 intake_id TEXT NOT NULL, fingerprint TEXT NOT NULL, asset_ids TEXT NOT NULL,
 PRIMARY KEY(organisation_id,owner_id,document_id,intake_id))''')

def receive_retryable_originals(con, *, owner_id, organisation_id, document_id,
                               intake_id, originals, rights_statement, consent_status):
 """Local receipt only, after caller-proven document ownership. No cached grants.

 The caller serialises writes and commits receipt and originals together. The
 ordered bytes, names, MIME and exact declaration must match on every retry.
 """
 if not isinstance(intake_id,str) or not re.fullmatch(r'[a-f0-9]{32}',intake_id):
  raise AssetError('A 32-character intake retry identifier is required')
 fingerprint=digest(encode(dict(originals=[dict(sha256=hashlib.sha256(x['content']).hexdigest(),
  size=len(x['content']),mime=x['mime'],name=x['name']) for x in originals],
  rightsStatement=rights_statement,consentStatus=consent_status)))
 scope=(organisation_id,owner_id,document_id,intake_id)
 receipt=con.execute('''SELECT fingerprint,asset_ids FROM business_asset_intake_receipts
 WHERE organisation_id=? AND owner_id=? AND document_id=? AND intake_id=?''',scope).fetchone()
 if receipt:
  if receipt['fingerprint']!=fingerprint:
   raise AssetIntakeConflict('This retry identifier belongs to different originals or permission. No originals imported')
  # Re-read original integrity and current withdrawals, never replay old rights.
  try:
   ids=json.loads(receipt['asset_ids'])
   if (not isinstance(ids,list) or len(ids)!=len(originals) or
       any(not isinstance(ident,str) for ident in ids) or len(set(ids))!=len(ids)):
    raise ValueError()
  except (ValueError,TypeError):raise AssetError('Invalid intake receipt; inspect the library')
  results=[original(con,organisation_id,owner_id,ident)[0] for ident in ids]
  for saved,submitted in zip(results,originals):
   if (saved['sourceSha256']!=hashlib.sha256(submitted['content']).hexdigest() or
       saved['sourceBytes']!=len(submitted['content']) or saved['mimeType']!=submitted['mime'] or
       saved['originalName']!=submitted['name'] or saved['rightsStatement']!=rights_statement or
       saved['consentStatus']!=consent_status):
    raise AssetError('Intake receipt originals changed; inspect the library')
  return results,True
 results=receive_originals(con,owner_id=owner_id,organisation_id=organisation_id,
  originals=originals,rights_statement=rights_statement,consent_status=consent_status)
 con.execute('INSERT INTO business_asset_intake_receipts VALUES(?,?,?,?,?,?)',
  (*scope,fingerprint,encode([x['assetId'] for x in results])))
 return results,False

def withdraw_permission(con, organisation_id, owner_id, asset_id, reason):
 """Permanent local hold; caller owns the transaction and authenticated scope.

 Keep the initial declaration and bytes intact. Reinstatement needs a separately
 reviewed policy; there is deliberately no restore or edit operation.
 """
 from datetime import datetime, timezone
 original(con, organisation_id, owner_id, asset_id)
 if not isinstance(reason,str) or not 20<=len(reason.strip())<=400 or any(ord(c)<32 for c in reason):
  raise AssetError('Explain the permission withdrawal in 20–400 characters')
 reason=reason.strip()
 old=con.execute('''SELECT reason FROM business_asset_withdrawals
 WHERE organisation_id=? AND business_id=? AND asset_id=?''',
                 (organisation_id,organisation_id,asset_id)).fetchone()
 if old:
  if old['reason']!=reason:raise AssetError('Permission was already withdrawn; its record cannot be edited')
 else:
  con.execute('INSERT INTO business_asset_withdrawals VALUES(?,?,?,?,?,?)',
              (organisation_id,organisation_id,asset_id,owner_id,reason,datetime.now(timezone.utc).isoformat()))
 return original(con,organisation_id,owner_id,asset_id)[0]

def receive_original(con, *, owner_id, organisation_id, asset_id, content, mime,
                  name, rights_statement, consent_status):
 """Caller must authenticate first. Atomically retain validated, unmodified bytes.

 Scope is derived by the offline repository; no submitted business/owner IDs.
 The enclosing transaction belongs to that repository.
 """
 import tempfile
 if not isinstance(owner_id,str) or not owner_id.strip():raise AssetError('Owner required')
 if not isinstance(content,bytes) or not 1<=len(content)<=10*1024*1024:
  raise AssetError('Original media must be at most 10 MB')
 item=dict(organisationId=organisation_id,businessId=organisation_id,assetId=asset_id,
           mediaKind='video' if mime=='video/mp4' else 'photo',mimeType=mime,sourceSha256=hashlib.sha256(content).hexdigest(),
           sourceBytes=len(content),rightsStatement=rights_statement,
           consentStatus=consent_status,originalName=name)
 with tempfile.NamedTemporaryFile() as source:
  source.write(content);source.flush()
  if item['mediaKind']=='video':validate_offline_video(source.name)
  record(con,item,source.name)
 con.execute('INSERT INTO business_asset_originals VALUES(?,?,?,?,?)',
             (organisation_id,organisation_id,asset_id,owner_id,content))
 # Reuploads of withdrawn bytes inherit the hold; the declaration stays intact.
 return original(con,organisation_id,owner_id,asset_id)[0]

def receive_photo(con, **kwargs):
 """Compatibility for existing image-only callers."""
 if kwargs.get('mime') not in MIMES['photo']:raise AssetError('Unsupported photo type')
 return receive_original(con, **kwargs)

def receive_originals(con, *, owner_id, organisation_id, originals,
                     rights_statement, consent_status):
 """Atomic bounded intake into the existing catalogue; scope is caller-proven.

 The declaration applies to every file. Originals are decoded sequentially and
 an invalid member rolls back the entire set, including catalogue metadata.
 The caller retains responsibility for the enclosing transaction and auth.
 """
 if not isinstance(originals,list) or not 1<=len(originals)<=5:
  raise AssetError('Choose one to five originals per import')
 fields={'asset_id','content','mime','name'}
 if any(not isinstance(item,dict) or set(item)!=fields or
        not isinstance(item['content'],bytes) or not 1<=len(item['content'])<=10*1024*1024
        for item in originals):
  raise AssetError('Each original must be at most 10 MB')
 size=sum(len(item['content']) for item in originals)
 if size>20*1024*1024:raise AssetError('Import at most 20 MB at once')
 count,total=con.execute('''SELECT count(*),coalesce(sum(length(original_bytes)),0)
 FROM business_asset_originals WHERE organisation_id=? AND owner_id=?''',
                       (organisation_id,owner_id)).fetchone()
 if count+len(originals)>100 or total+size>100*1024*1024:
  raise AssetStorageLimit('Offline media library is full; no originals imported')
 con.execute('SAVEPOINT media_intake')
 try:
  results=[]
  for index,item in enumerate(originals,1):
   try:
    results.append(receive_original(con,owner_id=owner_id,organisation_id=organisation_id,
                   rights_statement=rights_statement,consent_status=consent_status,**item))
   except AssetError as exc:
    raise AssetError(f'Original {index}: {exc}. No originals imported') from exc
 except Exception:
  con.execute('ROLLBACK TO media_intake')
  raise
 finally:
  con.execute('RELEASE media_intake')
 return results

def probe_offline_video(path):
 """Bounded local MP4 intake; no URL inputs, remote protocols or provider access.

 Validate container and stream metadata for intake/edit bounds. Full decode is
 performed separately at intake. Never infer authenticity, consent or quality.
 Keep legacy metadata catalogue validation unchanged for existing callers.
 """
 import math
 try:
  probe=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file','-format_whitelist','mov','-enable_drefs','0',
   '-show_streams','-show_format','-of','json',str(path)],
   capture_output=True,text=True,timeout=8,check=True)
  info=json.loads(probe.stdout);streams=info['streams'];fmt=info['format']
  video=[v for v in streams if v.get('codec_type')=='video']
  audio=[v for v in streams if v.get('codec_type')=='audio']
  duration=float(fmt['duration'])
  if (len(video)!=1 or len(audio)>1 or len(streams)!=len(video)+len(audio) or
      'mp4' not in fmt['format_name'].split(',') or
      fmt.get('tags',{}).get('major_brand','').strip() not in
       {'isom','iso2','iso3','iso4','iso5','iso6','mp41','mp42','avc1','M4V'} or
      not math.isfinite(duration) or not 0.25<=duration<=60):
   raise ValueError('Unsupported MP4 container or duration')
  v=video[0];num,den=map(int,v['r_frame_rate'].split('/'))
  if (v.get('codec_name')!='h264' or v.get('disposition',{}).get('attached_pic') or
      not 160<=int(v['width'])<=1920 or not 160<=int(v['height'])<=1920 or
      int(v['width'])*int(v['height'])>1920*1080 or den<=0 or not 0<num/den<=60 or
      any(a.get('codec_name')!='aac' or int(a.get('channels',0)) not in (1,2) for a in audio)):
   raise ValueError('Unsupported video or audio stream')
  return info
 except (OSError,ValueError,KeyError,TypeError,ZeroDivisionError,subprocess.SubprocessError) as exc:
  raise AssetError('Choose a decodable H.264 MP4, 0.25–60 seconds, at most 1080p and 60 fps, with optional mono/stereo AAC audio') from exc

def validate_offline_video(path):
 """Full bounded decode before intake; metadata alone cannot validate pixels."""
 probe_offline_video(path)
 try:
  subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-err_detect','explode',
   '-protocol_whitelist','file','-format_whitelist','mov','-enable_drefs','0','-threads','1','-i',str(path),
   '-map','0:v:0','-map','0:a?','-threads','1','-f','null','-'],
   capture_output=True,timeout=20,check=True)
 except (OSError,ValueError,KeyError,TypeError,ZeroDivisionError,subprocess.SubprocessError) as exc:
  raise AssetError('Choose a decodable H.264 MP4, 0.25–60 seconds, at most 1080p and 60 fps, with optional mono/stereo AAC audio') from exc

def original_video_duration_ms(con, organisation_id, owner_id, asset_id):
 """Derive edit bounds from scoped, hash-checked bytes, never client metadata."""
 import math,tempfile
 item,content=original(con,organisation_id,owner_id,asset_id)
 if item['mediaKind']!='video':raise AssetError('Video edits require an original video')
 with tempfile.NamedTemporaryFile() as source:
  source.write(content);source.flush()
  info=probe_offline_video(source.name)
 # Both container and video stream must cover the requested interval.
 try:
  stream=next(v for v in info['streams'] if v.get('codec_type')=='video')
  durations=[float(info['format']['duration']),float(stream['duration'])]
  if any(not math.isfinite(d) or d<=0 for d in durations):raise ValueError('Missing duration')
  return math.floor(min(durations)*1000)
 except (KeyError,TypeError,ValueError) as exc:
  raise AssetError('Original video duration unavailable; excerpt editing held') from exc

def original_photo(con, organisation_id, owner_id, asset_id):
 """Decode scoped immutable bytes in display orientation for crop coordinates."""
 import io
 from PIL import Image, ImageOps
 item,content=original(con,organisation_id,owner_id,asset_id)
 if item['mediaKind']!='photo':raise AssetError('Photo crops require an original photo')
 if item.get('permissionWithdrawn') or item['consentStatus']!='owner_asserted':
  raise AssetError('Photo permission is required before editing')
 try:
  with Image.open(io.BytesIO(content)) as source:
   source.load()
   image=ImageOps.exif_transpose(source).convert('RGBA')
  return item,image
 except (OSError,ValueError,Image.DecompressionBombError) as exc:
  raise AssetError('Invalid original photo') from exc

def validate_photo_crop(edit, size):
 if not isinstance(edit,dict) or set(edit)!={'assetId','left','top','width','height'}:
  raise AssetError('Photo asset and pixel crop rectangle required')
 left,top,width,height=(edit[k] for k in ('left','top','width','height'))
 if (any(type(v) is not int for v in (left,top,width,height)) or
     left<0 or top<0 or width<16 or height<16 or
     left+width>size[0] or top+height>size[1]):
  raise AssetError('Crop must fit the oriented original and be at least 16 pixels per side')
 return (left,top,left+width,top+height)

def original(con, organisation_id, owner_id, asset_id):
 row=con.execute('''SELECT original_bytes FROM business_asset_originals
 WHERE organisation_id=? AND business_id=? AND owner_id=? AND asset_id=?''',
                 (organisation_id,organisation_id,owner_id,asset_id)).fetchone()
 if row is None:raise AssetError('Asset unavailable')
 item=next((x for x in list_assets(con,organisation_id,organisation_id) if x['assetId']==asset_id),None)
 content=bytes(row['original_bytes'])
 if not item or len(content)!=item['sourceBytes'] or hashlib.sha256(content).hexdigest()!=item['sourceSha256']:
  raise AssetError('Original bytes changed')
 return item,content
def public(item):
 return {**item,'usageStatus':'held_rights_unconfirmed' if item['consentStatus']=='not_confirmed' else 'owner_rights_asserted_pending_review','verifiedRights':False,'authenticityVerified':False,'canSpend':False,'canPublish':False,'generationApproved':False}

def original_thumbnail(con, organisation_id, owner_id, asset_id):
 """Ephemeral visual discovery only. Never persist derivatives or review evidence."""
 import io,tempfile
 from PIL import Image,ImageOps
 item,content=original(con,organisation_id,owner_id,asset_id)
 if item.get('permissionWithdrawn'):raise AssetError('Permission withdrawn; thumbnail held')
 try:
  if item['mediaKind']=='photo':
   with Image.open(io.BytesIO(content)) as source:
    source.load()
    image=ImageOps.exif_transpose(source).convert('RGB')
  elif item['mediaKind']=='video':
   with tempfile.NamedTemporaryFile() as source:
    source.write(content);source.flush()
    frame=subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror',
     '-protocol_whitelist','file','-format_whitelist','mov','-enable_drefs','0',
     '-threads','1','-i',source.name,'-map','0:v:0','-frames:v','1','-an',
     '-vf','scale=320:320:force_original_aspect_ratio=decrease',
     '-threads','1','-f','image2pipe','-vcodec','png','pipe:1'],
     capture_output=True,timeout=5,check=True)
   if not 1<=len(frame.stdout)<=512*1024:raise ValueError('Frame unavailable')
   with Image.open(io.BytesIO(frame.stdout)) as source:
    source.load();image=source.convert('RGB')
  else:raise ValueError('Unsupported original')
  try:
   image.thumbnail((320,320))
   image.info.clear()  # Discovery copies need no embedded original metadata.
   output=io.BytesIO();image.save(output,format='PNG')
   width,height=image.size;preview=output.getvalue()
  finally:image.close()
  if not 1<=len(preview)<=512*1024:raise ValueError('Thumbnail too large')
 except (OSError,ValueError,Image.DecompressionBombError,subprocess.SubprocessError) as exc:
  raise AssetError('Thumbnail unavailable; inspect the original separately') from exc
 return preview,dict(assetId=asset_id,sourceSha256=item['sourceSha256'],
  previewSha256=hashlib.sha256(preview).hexdigest(),width=width,height=height,
  mimeType='image/png',mediaKind=item['mediaKind'],consentStatus=item['consentStatus'],
  permissionWithdrawn=False,approved=False,canSpend=False,canPublish=False,
  coverage='first_frame_only' if item['mediaKind']=='video' else 'whole_photo_scaled')
def validate_media(path,kind,mime):
 if kind in ('logo','photo'):
  try:
   from PIL import Image
   with Image.open(path) as im:
    if im.format != {'image/png':'PNG','image/jpeg':'JPEG','image/webp':'WEBP'}[mime] or not (16<=im.width<=6000 and 16<=im.height<=6000) or im.width*im.height>24000000:
     raise ValueError('Unsupported image dimensions or encoding')
    im.verify()
   # verify() alone can accept a JPEG header with missing pixel data.
   with Image.open(path) as im:
    if getattr(im,'n_frames',1)!=1:raise ValueError('Animated images are unsupported')
    im.load()
  except (OSError,ValueError,KeyError,Image.DecompressionBombError) as exc:raise AssetError('Invalid image bytes') from exc
 else:
  try:
   result=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height:format=duration','-of','json',str(path)],capture_output=True,text=True,timeout=12,check=True)
   info=json.loads(result.stdout)
   streams=[v for v in info['streams'] if v.get('codec_type')=='video']
   duration=float(info['format']['duration'])
   if len(streams)!=1 or not (0.25<=duration<=3600) or not (160<=int(streams[0]['width'])<=3840 and 160<=int(streams[0]['height'])<=2160):
    raise ValueError('Unsupported video stream')
  except (OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:raise AssetError('Invalid video bytes') from exc

def record(con,item,source):
 if not isinstance(item,dict) or set(item)!=FIELDS:raise AssetError('Complete asset provenance required')
 for k in ('organisationId','businessId','assetId'):
  if not isinstance(item[k],str) or not ID.fullmatch(item[k]):raise AssetError('Invalid asset identity')
 if item['mediaKind'] not in MIMES or item['mimeType'] not in MIMES[item['mediaKind']]:raise AssetError('Unsupported media type')
 if item['consentStatus'] not in ('not_confirmed','owner_asserted'):raise AssetError('Invalid rights status')
 for k,low,high in [('rightsStatement',20,400),('originalName',3,140)]:
  if not isinstance(item[k],str) or not low<=len(item[k].strip())<=high or any(ord(c)<32 for c in item[k]):raise AssetError('Invalid '+k)
 p=Path(source)
 if not isinstance(item['sourceSha256'],str) or not SHA.fullmatch(item['sourceSha256']) or p.is_symlink() or not p.is_file() or type(item['sourceBytes']) is not int or not 1<=item['sourceBytes']<=170*1024*1024:raise AssetError('Invalid source')
 if p.stat().st_size!=item['sourceBytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sourceSha256']:raise AssetError('Source bytes changed')
 validate_media(p,kind=item['mediaKind'],mime=item['mimeType'])
 payload=encode(item); sha=digest(payload);ids=(item['organisationId'],item['businessId'],item['assetId'])
 old=con.execute('SELECT record_sha FROM business_asset_catalog WHERE organisation_id=? AND business_id=? AND asset_id=?',ids).fetchone()
 if old and old['record_sha']!=sha:raise AssetError('Immutable asset already exists')
 if not old:con.execute('INSERT INTO business_asset_catalog VALUES(?,?,?,?,?,?)',(*ids,item['sourceSha256'],payload,sha))
 return public(item)
def list_assets(con,organisation_id,business_id):
 if any(not isinstance(v,str) or not ID.fullmatch(v) for v in (organisation_id,business_id)):raise AssetError('Business scope required')
 rows=con.execute('SELECT * FROM business_asset_catalog WHERE organisation_id=? AND business_id=? ORDER BY asset_id',(organisation_id,business_id)).fetchall();out=[]
 for row in rows:
  if digest(row['record_json'])!=row['record_sha']:raise AssetError('Tampered catalogue')
  item=json.loads(row['record_json'])
  if (item['sourceSha256']!=row['original_sha'] or
      (item['organisationId'],item['businessId'],item['assetId'])!=(organisation_id,business_id,row['asset_id'])):raise AssetError('Tampered source')
  # Legacy metadata-only catalogues may not have the offline rights ledger.
  withdrawal=None
  if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='business_asset_withdrawals'").fetchone():
   # Identical bytes cannot bypass a hold through a second catalogue ID.
   # Original ownership prevents another owner's declaration/reason leaking.
   withdrawal=con.execute('''SELECT w.reason,w.withdrawn_at
 FROM business_asset_withdrawals w
 JOIN business_asset_catalog c ON c.organisation_id=w.organisation_id
  AND c.business_id=w.business_id AND c.asset_id=w.asset_id
 JOIN business_asset_originals o ON o.organisation_id=w.organisation_id
  AND o.business_id=w.business_id AND o.asset_id=w.asset_id AND o.owner_id=w.owner_id
 JOIN business_asset_originals target ON target.organisation_id=o.organisation_id
  AND target.business_id=o.business_id AND target.owner_id=o.owner_id
 WHERE target.organisation_id=? AND target.business_id=? AND target.asset_id=?
  AND c.original_sha=? ORDER BY w.withdrawn_at,w.asset_id LIMIT 1''',
                          (organisation_id,business_id,item['assetId'],item['sourceSha256'])).fetchone()
  result=public(item)
  result['permissionWithdrawn']=bool(withdrawal)
  if withdrawal:
   result.update(usageStatus='held_permission_withdrawn',withdrawalReason=withdrawal['reason'],
                 withdrawnAt=withdrawal['withdrawn_at'])
  out.append(result)
 return out
