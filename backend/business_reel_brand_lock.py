"""Immutable owner-confirmed brand assets with separate original-byte provenance."""
from __future__ import annotations
import hashlib,io,json,os,re,tempfile,time,uuid
from pathlib import Path
from PIL import Image,UnidentifiedImageError
from urllib.parse import urlsplit

class BrandLockError(ValueError):
 def __init__(self,message,code='brand_lock_blocked',status=409):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 con.execute('''CREATE TABLE IF NOT EXISTS business_reel_brand_locks(
  project_id TEXT PRIMARY KEY,brand_name TEXT NOT NULL,primary_hex TEXT NOT NULL,
  accent_hex TEXT NOT NULL,contact_url TEXT NOT NULL,logo_sha256 TEXT NOT NULL,
  logo_bytes INTEGER NOT NULL,logo_width INTEGER NOT NULL,logo_height INTEGER NOT NULL,
  style TEXT NOT NULL,owner_attestation TEXT NOT NULL,created REAL NOT NULL)''')
 columns={row[1] for row in con.execute('PRAGMA table_info(business_reel_brand_locks)')}
 for name,typ in (('original_logo_sha256','TEXT'),('original_logo_bytes','INTEGER'),('original_logo_format','TEXT')):
  if name not in columns:con.execute(f'ALTER TABLE business_reel_brand_locks ADD COLUMN {name} {typ}')

def _url(contact,source):
 try:
  if not isinstance(contact,str):raise ValueError()
  a=urlsplit(contact);b=urlsplit(source)
  if a.scheme!='https' or not a.hostname or a.hostname!=b.hostname or a.port!=b.port or a.username or a.password or a.fragment:raise ValueError()
 except (ValueError,TypeError):
  raise BrandLockError('Only an owner-confirmed HTTPS page on the saved website is permitted','url_not_verified',400) from None
 return contact

def lock(con,project_id,root,*,brand_name,primary,accent,contact_url,style,logo_path,owner_attestation,owner_confirmed=False):
 import business_reel_workbench as workbench
 import business_marketing_drafts as drafts
 if owner_confirmed is not True or not isinstance(owner_attestation,str) or not 35<=len(owner_attestation.strip())<=400:
  raise BrandLockError('Explicit brand asset authority and provenance required','rights_missing',403)
 for color in (primary,accent):
  if not isinstance(color,str) or not re.fullmatch('#[0-9a-fA-F]{6}',color):
   raise BrandLockError('Use exact hex colour values','bad_colour',400)
 if style not in ('editorial','modern','minimal'):
  raise BrandLockError('Unsupported brand title style','invalid_style',400)
 owned=not con.in_transaction
 if owned:con.execute('BEGIN IMMEDIATE')
 token='brand_lock_'+uuid.uuid4().hex;con.execute('SAVEPOINT '+token)
 created=[];released=False
 try:
  project=workbench._project(con,project_id);brief=json.loads(project['brief_json'])
  if drafts.read_draft(con,project['draft_id'])['revision']!=project['revision']:
   raise BrandLockError('Campaign changed; confirm branding on its current revision','stale_revision',409)
  if brand_name!=brief['business']:
   raise BrandLockError('Locked business name must match the saved brand identity','wrong_brand',409)
  if con.execute('SELECT 1 FROM business_reel_brand_locks WHERE project_id=?',(project_id,)).fetchone():
   raise BrandLockError('Verified brand lock cannot be silently replaced','immutable_brand')
  _url(contact_url,brief['sourceUrl'])
  source=Path(logo_path)
  if source.is_symlink() or not source.is_file() or not 300<=source.stat().st_size<=2_000_000:
   raise BrandLockError('A genuine owner-supplied logo under 2MB is required','no_owned_logo',403)
  original=source.read_bytes()
  if not 300<=len(original)<=2_000_000:
   raise BrandLockError('The source logo changed during upload','unsafe_logo',409)
  try:
   with Image.open(io.BytesIO(original)) as image:
    if image.format not in ('PNG','JPEG','WEBP') or not 64<=image.width<=4000 or not 64<=image.height<=4000 or image.width*image.height>8_000_000:raise ValueError()
    image.load();width,height=image.size;original_format=image.format
    buffer=io.BytesIO();image.convert('RGBA').save(buffer,'PNG');data=buffer.getvalue()
  except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):
   raise BrandLockError('Brand mark could not be safely decoded','unsafe_logo',400) from None
  folder=Path(root)/'reel_workbench'/project_id
  if folder.is_symlink():raise BrandLockError('Unsafe logo output directory','unsafe_path',409)
  folder.mkdir(parents=True,exist_ok=True,mode=0o700)
  outfile=folder/'owner-verified-brand.png'
  suffix={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}[original_format]
  originalfile=folder/('owner-verified-brand-original'+suffix)
  for file in (outfile,originalfile):
   if file.exists() or file.is_symlink():raise BrandLockError('Logo already locked; do not overwrite','asset_exists',409)
  for file,blob in ((originalfile,original),(outfile,data)):
   with file.open('xb') as f:
    created.append(file);f.write(blob)
   os.chmod(file,0o600)
  con.execute('''INSERT INTO business_reel_brand_locks
   (project_id,brand_name,primary_hex,accent_hex,contact_url,logo_sha256,logo_bytes,
    logo_width,logo_height,style,owner_attestation,created,
    original_logo_sha256,original_logo_bytes,original_logo_format)
   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
   (project_id,brand_name,primary.upper(),accent.upper(),contact_url,
    hashlib.sha256(data).hexdigest(),len(data),width,height,style,owner_attestation.strip(),time.time(),
    hashlib.sha256(original).hexdigest(),len(original),original_format))
  con.execute('RELEASE SAVEPOINT '+token);released=True
  if owned:con.commit()
 except Exception:
  try:
   if not released:
    con.execute('ROLLBACK TO SAVEPOINT '+token);con.execute('RELEASE SAVEPOINT '+token)
  finally:
   if owned:con.rollback()
   for file in created:file.unlink(missing_ok=True)
  raise
 return read(con,project_id,root)

def read(con,project_id,root=None):
 record=con.execute('SELECT * FROM business_reel_brand_locks WHERE project_id=?',(project_id,)).fetchone()
 if not record:return {'locked':False,'missing':['owner-supplied logo','brand colours','business contact approval']}
 original_sha=record['original_logo_sha256']
 if root is not None:
  folder=Path(root)/'reel_workbench'/project_id
  if folder.is_symlink():raise BrandLockError('Locked brand directory has been changed','logo_changed',409)
  p=folder/'owner-verified-brand.png'
  if p.is_symlink() or not p.is_file() or p.stat().st_size!=record['logo_bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=record['logo_sha256']:
   raise BrandLockError('Locked brand asset has been changed','logo_changed',409)
  if original_sha is not None:
   suffix={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}.get(record['original_logo_format'])
   if suffix is None:raise BrandLockError('Original logo provenance has been changed','logo_changed',409)
   p=folder/('owner-verified-brand-original'+suffix)
   if p.is_symlink() or not p.is_file() or p.stat().st_size!=record['original_logo_bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=original_sha:
    raise BrandLockError('The original owner-supplied logo has been changed','logo_changed',409)
 return {'locked':True,'brandName':record['brand_name'],'primary':record['primary_hex'],
  'accent':record['accent_hex'],'style':record['style'],'contactUrl':record['contact_url'],
  'logoSha256':record['logo_sha256'],'originalLogoSha256':original_sha,
  'originalLogoFormat':record['original_logo_format'],'originalBytesPreserved':original_sha is not None,
  'verifiedByOwner':True,'published':False,'immutable':True}

def lock_uploaded(con,project_id,root,*,logo_base64,mime,**details):
 """Local pilot upload. Preserve original bytes before temporary upload cleanup."""
 import base64,binascii
 if mime not in ('image/png','image/jpeg','image/webp') or not isinstance(logo_base64,str) or len(logo_base64)>2_700_000:
  raise BrandLockError('Use PNG, JPG or WebP under 2 MB','invalid_upload',400)
 try:data=base64.b64decode(logo_base64,validate=True)
 except (binascii.Error,ValueError):
  raise BrandLockError('Invalid image transfer','invalid_upload',400) from None
 if not 300<=len(data)<=2_000_000:raise BrandLockError('Logo exceeds the upload limit','invalid_upload',400)
 typ={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[mime]
 with tempfile.TemporaryDirectory(prefix='owner-logo-',dir=Path(root)) as folder:
  file=Path(folder)/('logo'+typ);file.write_bytes(data)
  return lock(con,project_id,root,logo_path=file,**details)
