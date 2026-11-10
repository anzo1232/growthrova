"""Final local post approvals: exact saved words + exact rendered image, audit-only.

Approvals certify owner review for *manual* use, never social publishing,
advertising budget, video use or customer account permissions.
"""
from __future__ import annotations
import hashlib,json,re,sqlite3,time,uuid
from pathlib import Path
import business_marketing_drafts as drafts
import business_agency_pack_jobs as packs

class ApprovalError(ValueError):
 def __init__(self,message,code='not_ready_for_review',status=422):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 con.execute('''CREATE TABLE IF NOT EXISTS business_post_approvals(
 id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,revision INTEGER NOT NULL,
 kit_id TEXT NOT NULL,day INTEGER NOT NULL,
 copy_sha256 TEXT NOT NULL,image_sha256 TEXT NOT NULL,
 claims_checked INTEGER NOT NULL,visuals_checked INTEGER NOT NULL,
 rights_checked INTEGER NOT NULL,approved_at REAL NOT NULL,
 UNIQUE(draft_id,revision,kit_id,day,copy_sha256,image_sha256))''')

def _digest(value):
 return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()

def _post(doc,day):
 if type(day) is not int or not 1<=day<=30:raise ApprovalError('Choose an actual post','invalid_post',400)
 item=next((p for p in doc.get('posts',[]) if p.get('day')==day),None)
 if item is None:raise ApprovalError('Post was not found','not_found',404)
 return item

def _copy_digest(item):
 return _digest({k:item.get(k,'') for k in ('day','theme','channel','format','objective','copyDraft','callToAction')})

STATIC_PICTURE_FORMATS=frozenset({
 'image advert','image ad','image post','static image','static post','single image',
 'photo','photo post','graphic','static graphic','educational graphic',
 'promotional graphic','text and image post'})

def _verified_post_quality(item,manifest,folder):
 """A saved PNG cannot stand in for a video, Story or complete carousel.

 The hashed report belongs to the current kit checked by _snapshot. A missing,
 changed or rejected review cannot be replaced with client-side checkboxes.
 """
 fmt=re.sub(r'\s+',' ',str(item.get('format','')).strip().casefold())
 if fmt not in STATIC_PICTURE_FORMATS:
  raise ApprovalError('This format needs its complete matching media, not a single picture preview','post_format_not_supported',409)
 checksums=manifest.get('fileSHA256') if isinstance(manifest,dict) else None
 expected=checksums.get('creative-quality-report.json') if isinstance(checksums,dict) else None
 path=folder/'creative-quality-report.json'
 if (not isinstance(expected,str) or not re.fullmatch(r'[a-f0-9]{64}',expected) or
     path.is_symlink() or not path.is_file() or not 1<=path.stat().st_size<=128*1024):
  raise ApprovalError('The saved quality review is missing. Prepare and review the current picture first','quality_evidence_missing',409)
 blob=path.read_bytes()
 if hashlib.sha256(blob).hexdigest()!=expected:
  raise ApprovalError('The quality review changed. Review a new export before approving','quality_evidence_changed',409)
 try:report=json.loads(blob)
 except (ValueError,UnicodeDecodeError):
  raise ApprovalError('The saved quality review is invalid','quality_evidence_missing',409) from None
 rows=report.get('posts') if isinstance(report,dict) else None
 if not isinstance(rows,list):
  raise ApprovalError('The saved post quality review is missing','quality_evidence_missing',409)
 matches=[row for row in rows if isinstance(row,dict) and type(row.get('day')) is int and row['day']==item['day']]
 if (len(matches)!=1 or matches[0].get('channel')!=item.get('channel') or
     matches[0].get('format')!=item.get('format')):
  raise ApprovalError('The quality review does not match this saved post','quality_evidence_missing',409)
 review=matches[0]
 if (review.get('status')!='awaiting_human_creative_review' or
     not isinstance(review.get('issues'),list) or review['issues']):
  raise ApprovalError('This post has not passed its quality checks. Resolve the issues before approving','quality_rejected',409)

def _snapshot(con,draft_id,revision,kit_id,day,root,require_review=True):
 drafts._id(draft_id);packs.valid(kit_id)
 draft=drafts.read_draft(con,draft_id)
 if revision!=draft['revision']:raise ApprovalError('Post changed after you opened it; review the new version','revision_conflict',409)
 current=[k for k in packs.latest_pack(con,draft_id,root) if k['id']==kit_id and k['status']=='done']
 if not current:raise ApprovalError('Images changed or a newer pack is being prepared','pack_stale',409)
 item=_post(draft['document'],day)
 if require_review and item['status']!='copy_reviewed':raise ApprovalError('Check the words of this post first','copy_review_required',409)
 filename=f'post-day-{day:02d}.png'
 try:media=packs.asset_path(con,kit_id,root,filename)
 except packs.PackError:raise ApprovalError('The post image is not ready','image_not_ready',409) from None
 info=Path(root)/'marketing_packs'/kit_id/'manifest.json'
 if info.is_symlink() or not info.is_file():raise ApprovalError('Image verification manifest is missing','integrity_missing',409)
 try:manifest=json.loads(info.read_text(encoding='utf-8'))
 except (OSError,ValueError):raise ApprovalError('Image verification manifest is invalid','integrity_missing',409) from None
 if not isinstance(manifest,dict) or not isinstance(manifest.get('fileSHA256'),dict):
  raise ApprovalError('Image verification manifest is invalid','integrity_missing',409)
 expected=manifest['fileSHA256'].get(filename)
 actual=hashlib.sha256(media.read_bytes()).hexdigest()
 if not isinstance(expected,str) or actual!=expected:raise ApprovalError('Post picture changed; review a new export','image_changed',409)
 _verified_post_quality(item,manifest,info.parent)
 return item,_copy_digest(item),actual

def _public(row):
 return {'id':row['id'],'day':row['day'],'revision':row['revision'],'kitId':row['kit_id'],
  'status':'approved_for_manual_use','approvedAt':row['approved_at'],
  'copyDigest':row['copy_sha256'],'imageDigest':row['image_sha256'],
  'published':False,'publishAuthorized':False,'adSpendAuthorized':False}

def approve_post(con,draft_id,revision,kit_id,day,root,*,claims_checked=False,visuals_checked=False,rights_checked=False):
 if (claims_checked,visuals_checked,rights_checked)!=(True,True,True):
  raise ApprovalError('Check the words, actual picture and rights before approval','confirmations_required',403)
 if type(revision) is not int:raise ApprovalError('Saved campaign revision required','invalid_revision',400)
 con.execute('BEGIN IMMEDIATE')
 try:
  item,copy_digest,image_digest=_snapshot(con,draft_id,revision,kit_id,day,root)
  previous=con.execute('''SELECT * FROM business_post_approvals WHERE draft_id=? AND revision=? AND kit_id=?
   AND day=? AND copy_sha256=?''',(draft_id,revision,kit_id,day,copy_digest)).fetchone()
  if previous:
   if previous['image_sha256']!=image_digest:
    raise ApprovalError('Approved image has changed; cannot reuse the old approval','image_changed',409)
   con.commit();return _public(previous)
  aid=uuid.uuid4().hex
  con.execute('INSERT INTO business_post_approvals VALUES(?,?,?,?,?,?,?,?,?,?,?)',
   (aid,draft_id,revision,kit_id,day,copy_digest,image_digest,1,1,1,time.time()))
  result=con.execute('SELECT * FROM business_post_approvals WHERE id=?',(aid,)).fetchone()
  con.commit();return _public(result)
 except BaseException:
  con.rollback();raise

def list_approvals(con,draft_id,kit_id,root):
 drafts._id(draft_id);packs.valid(kit_id)
 try:doc=drafts.read_draft(con,draft_id)
 except drafts.MarketingDraftError:return []
 if not any(x['id']==kit_id and x['status']=='done' for x in packs.latest_pack(con,draft_id,root)):return []
 rows=con.execute('''SELECT * FROM business_post_approvals WHERE draft_id=? AND revision=? AND kit_id=?''',
  (draft_id,doc['revision'],kit_id)).fetchall()
 result=[]
 for row in rows:
  try:
   _,copy_digest,image_digest=_snapshot(con,draft_id,row['revision'],kit_id,row['day'],root)
   if row['copy_sha256']==copy_digest and row['image_sha256']==image_digest:result.append(_public(row))
  except (ApprovalError,packs.PackError,OSError):pass
 return sorted(result,key=lambda x:x['day'])
