"""Local agency-pack job ledger: revision-safe, no external AI calls or ad spend."""
from __future__ import annotations
import hashlib,json,os,re,time,uuid
from pathlib import Path
from business_agency_pack import build_pack
import business_marketing_drafts as drafts
import business_website_media as website_media
import business_runway as runway
import business_runway_video as runway_video
import business_creative_review as creative_review

class PackError(ValueError):
 def __init__(self,message,code='agency_pack_unavailable',status=422):
  super().__init__(message);self.code=code;self.status=status

PACK_FORMAT_VERSION=10  # New QC receipts; older export archives remain immutable.
FILE_NAMES=frozenset(['hero-ad.png',*[f'carousel-{i:02d}.png' for i in range(1,6)],
 *[f'post-day-{i:02d}.png' for i in range(1,31)],
 'service-guide.png','short-video-concept.mp4','runway-video-original.mp4','website-landing-page.html','30-day-plan.csv','email-sequence.md',
 'seo-opportunities.md','paid-advertising-plan.md','lead-capture-plan.md','campaign-summary.md',
 'manifest.json','creative-quality-report.json','campaign-kit.zip'])
def valid(value):
 if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise PackError('Invalid campaign or export identifier','invalid_id',400)
 return value

def initialise(con):
 website_media.initialise(con)
 runway.initialise(con)
 runway_video.initialise(con)
 creative_review.initialise(con)
 con.executescript('''CREATE TABLE IF NOT EXISTS marketing_pack_jobs(
   id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,revision INTEGER NOT NULL,
   fingerprint TEXT UNIQUE NOT NULL,status TEXT NOT NULL,error_code TEXT,
   created REAL NOT NULL,updated REAL NOT NULL);''')

def _row(con,jid):
 row=con.execute('SELECT * FROM marketing_pack_jobs WHERE id=?',(valid(jid),)).fetchone()
 if not row:raise PackError('Marketing kit not found','not_found',404)
 return row

def read_pack(con,jid,root=None):
 row=_row(con,jid)
 return {'id':row['id'],'draftId':row['draft_id'],'revision':row['revision'],'status':row['status'],
         'errorCode':row['error_code'],'files':(sorted(x.name for x in (Path(root)/'marketing_packs'/jid).iterdir() if x.is_file()) if root is not None and row['status']=='done' else sorted(FILE_NAMES-{'runway-video-original.mp4'}) if row['status']=='done' else []),
         'source':'locally_composed_assets','paidGeneration':False,'publishApproved':False}

def _photo_ids(con,draft_id):
 return [(item['id'],item['sha256']) for item in website_media.list_photos(con,draft_id)]

def _runway_assets(con,draft_id,root):
 '''Return only completed, current, hash-verified media; no model requests.'''
 assets={}
 banned=creative_review.excluded(con,draft_id,'image')
 for job in runway.list_jobs(con,draft_id):
  if job['id'] in banned:continue
  if job['status']!='completed' or job['currentBrief'] is not True or not job.get('asset'):
   continue
  if job.get('qualityStatus')=='technical_review_required':continue
  path=Path(root)/'generated'/(job['id']+'.png')
  metadata=job['asset'];checksum=metadata.get('sha256')
  if path.is_symlink() or not path.is_file() or not isinstance(checksum,str):continue
  if path.stat().st_size>runway.MAX_IMAGE_BYTES or path.stat().st_size!=metadata.get('bytes'):continue
  if hashlib.sha256(path.read_bytes()).hexdigest()!=checksum:continue
  assets[job['creativeId']]={'id':job['id'],'sha256':checksum,'path':path}
 return assets

def _video_asset(con,draft_id,root):
 if root is None:return None
 images=_runway_assets(con,draft_id,root)
 hero=images.get('creative-1')
 if not hero:return None
 source_digest=hashlib.sha256(hero['path'].read_bytes()).hexdigest()
 rows=con.execute('SELECT * FROM runway_video_jobs WHERE draft_id=? AND status=?',(draft_id,'completed')).fetchall()
 banned=creative_review.excluded(con,draft_id,'video')
 for row in rows:
  if row['id'] in banned:continue
  if row['source_digest']!=source_digest or not row['result_json']:continue
  meta=json.loads(row['result_json']);path=Path(root)/'generated_videos'/(row['id']+'.mp4')
  if path.is_symlink() or not path.is_file() or path.stat().st_size!=meta.get('bytes'):continue
  if hashlib.sha256(path.read_bytes()).hexdigest()!=meta.get('sha256'):continue
  return {'id':row['id'],'sha256':meta['sha256'],'path':path}
 return None

def _asset_ids(con,draft_id,root):
 if root is None:return []
 image_ids=sorted((cid,asset['sha256']) for cid,asset in _runway_assets(con,draft_id,root).items())
 video=_video_asset(con,draft_id,root)
 if video:image_ids.append(('video',video['sha256']))
 for kind in ('image','video'):
  for mid in sorted(creative_review.excluded(con,draft_id,kind)):
   image_ids.append(('rejected-'+kind,mid))
 return image_ids

def _fingerprint(doc,draft_id,revision,photos,generated):
 content=json.dumps(doc,sort_keys=True)
 material=json.dumps([draft_id,revision,PACK_FORMAT_VERSION,content,photos,generated],sort_keys=True)
 return hashlib.sha256(material.encode('utf8')).hexdigest()

def _photo_paths(con,draft_id,root):
 ret=[]
 for media in website_media.list_photos(con,draft_id):
  p=Path(root)/'website_photos'/draft_id/(media['id']+'.jpg')
  if p.is_symlink() or not p.is_file() or p.stat().st_size!=media['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=media['sha256']:
   raise PackError('A website photo changed or is missing; review it before generating new designs','website_photo_unavailable',409)
  ret.append(p)
 return ret

def latest_pack(con,draft_id,root=None):
 valid(draft_id)
 saved=drafts.read_draft(con,draft_id)
 expected=_fingerprint(saved['document'],draft_id,saved['revision'],_photo_ids(con,draft_id),_asset_ids(con,draft_id,root))
 rows=con.execute('SELECT * FROM marketing_pack_jobs WHERE draft_id=? ORDER BY created DESC LIMIT 15',(draft_id,)).fetchall()
 return [read_pack(con,row['id'],root) for row in rows if row['fingerprint']==expected]

def enqueue_pack(con,draft_id,revision,root):
 valid(draft_id)
 if type(revision)!=int or revision<1:raise PackError('Save your current campaign before creating a kit','invalid_revision',400)
 draft=drafts.read_draft(con,draft_id)
 if draft['revision']!=revision:raise PackError('The campaign has changed; reload the latest saved version','revision_conflict',409)
 document=draft['document']
 if len(document.get('posts',[]))!=30 or len(document.get('creatives',[]))<4:raise PackError('A complete campaign is required')
 fingerprint=_fingerprint(document,draft_id,revision,_photo_ids(con,draft_id),_asset_ids(con,draft_id,root))
 con.execute('BEGIN IMMEDIATE')
 try:
  previous=con.execute('SELECT * FROM marketing_pack_jobs WHERE fingerprint=?',(fingerprint,)).fetchone()
  if previous:con.commit();return read_pack(con,previous['id'])
  current=drafts.read_draft(con,draft_id)
  if current['revision']!=revision:raise PackError('The campaign changed before the render was reserved','revision_conflict',409)
  jid=uuid.uuid4().hex;now=time.time()
  con.execute('INSERT INTO marketing_pack_jobs VALUES(?,?,?,?,?,?,?,?)',(jid,draft_id,revision,fingerprint,'queued',None,now,now))
  con.commit()
 except BaseException:con.rollback();raise
 return read_pack(con,jid)

def render_pack(con,jid,root,source_image=None):
 row=_row(con,jid)
 if row['status']=='done':return read_pack(con,jid)
 if row['status'] not in ('queued','failed'):raise PackError('Marketing kit is processing','render_busy',409)
 # Bound a render to the exact submitted document revision, not a later edit.
 draft=drafts.read_draft(con,row['draft_id'])
 if draft['revision']!=row['revision']:
  con.execute("UPDATE marketing_pack_jobs SET status='failed',error_code='revision_changed',updated=? WHERE id=?",(time.time(),jid));con.commit()
  raise PackError('Campaign changed during pack generation','revision_conflict',409)
 doc=draft['document']
 expected=_fingerprint(doc,row['draft_id'],row['revision'],_photo_ids(con,row['draft_id']),_asset_ids(con,row['draft_id'],root))
 if row['fingerprint']!=expected:raise PackError('Campaign contents differ from reserved render','source_changed',409)
 con.execute("UPDATE marketing_pack_jobs SET status='rendering',updated=? WHERE id=?",(time.time(),jid));con.commit()
 try:
  photos=_photo_paths(con,row['draft_id'],root)
  generated=_runway_assets(con,row['draft_id'],root)
  anchor=generated.get('creative-1',{}).get('path') or source_image
  variants=[generated[k]['path'] for k in ('creative-5','creative-6','creative-7') if k in generated]
  video=_video_asset(con,row['draft_id'],root)
  has_rejected_video=bool(creative_review.excluded(con,row['draft_id'],'video'))
  result=build_pack(doc,anchor,Path(root)/'marketing_packs'/jid,source_photos=photos,generated_video=(video['path'] if video else None),
    include_video=(not has_rejected_video or video is not None),
    generated_variants=variants,hero_source_is_generated=('creative-1' in generated))
  con.execute("UPDATE marketing_pack_jobs SET status='done',error_code=NULL,updated=? WHERE id=?",(time.time(),jid));con.commit()
 except Exception as exc:
  con.execute("UPDATE marketing_pack_jobs SET status='failed',error_code=?,updated=? WHERE id=?",('render_failed',time.time(),jid));con.commit()
  raise PackError('Local campaign export failed: '+type(exc).__name__,'render_failed',503) from exc
 return read_pack(con,jid)

def asset_path(con,jid,root,name):
 row=_row(con,jid)
 if row['status']!='done':raise PackError('Marketing kit is not ready','not_ready',409)
 if not isinstance(name,str) or name not in FILE_NAMES:raise PackError('File not found in this kit','invalid_file',404)
 dest=Path(root)/'marketing_packs'/row['id']/name
 if dest.is_symlink() or not dest.is_file():raise PackError('Export file not available','asset_missing',404)
 if dest.stat().st_size>80*1024*1024:raise PackError('Export file exceeds size limit','asset_too_large',413)
 return dest
