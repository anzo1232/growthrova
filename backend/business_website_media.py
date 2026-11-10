"""Safe, opt-in photo intake from a business website into the private local pilot.

The owner must explicitly attest usage rights. That attestation is recorded,
not independently verified. Never republish unverified photo assets automatically.
"""
from __future__ import annotations
import hashlib,io,os,sqlite3,ssl,socket,http.client,tempfile,time
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image,UnidentifiedImageError
from business_website_analysis import validate_target,public_address,website_tls_context,WebsiteSafetyError
import business_marketing_drafts as drafts

MAX_INPUT=8*1024*1024
MAX_OUTPUT=8*1024*1024
MAX_PIXELS=18_000_000
class MediaError(ValueError):
 def __init__(self,message,code='media_unavailable',status=422):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 con.execute('''CREATE TABLE IF NOT EXISTS marketing_website_media(
 id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,source_url TEXT NOT NULL,
 image_sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,width INTEGER NOT NULL,
 height INTEGER NOT NULL,owner_declared_at REAL NOT NULL,
 UNIQUE(draft_id,source_url))''')

def _id(value):
 if not isinstance(value,str) or len(value)!=32 or any(x not in '0123456789abcdef' for x in value):
  raise MediaError('Invalid business reference','invalid_id',400)
 return value

def _public(row):
 return {'id':row['id'],'draftId':row['draft_id'],'sourceUrl':row['source_url'],
   'width':row['width'],'height':row['height'],'bytes':row['bytes'],
   'sha256':row['image_sha256'],'rightsStatus':'owner_declared','authenticityVerified':False}

def list_photos(con,draft_id):
 rows=con.execute('SELECT * FROM marketing_website_media WHERE draft_id=? ORDER BY owner_declared_at',(_id(draft_id),)).fetchall()
 return [_public(r) for r in rows]

def fetch_public_photo(url,ip):
 parsed=urlsplit(url)
 host=parsed.hostname
 if not host:raise MediaError('Invalid photo host')
 class PinnedHTTPS(http.client.HTTPSConnection):
  def connect(self):
   context=website_tls_context()
   sock=socket.create_connection((ip,443),timeout=8)
   try:self.sock=context.wrap_socket(sock,server_hostname=host)
   except BaseException:sock.close();raise
 conn=PinnedHTTPS(host,timeout=9)
 try:
  conn.request('GET',(parsed.path or '/')+('?' + parsed.query if parsed.query else ''),headers={
   'Host':host,'User-Agent':'ClipprBusinessOwnerPhotoImport/0.1',
   'Accept':'image/jpeg,image/png,image/webp','Accept-Encoding':'identity'})
  response=conn.getresponse()
  if response.status!=200:raise MediaError('Could not retrieve this website photo','source_unavailable',422)
  mime=response.getheader('Content-Type','').split(';')[0].lower().strip()
  if mime not in ('image/jpeg','image/png','image/webp'):raise MediaError('Website photo format unsupported','unsupported_type',422)
  length=response.getheader('Content-Length')
  if length:
   try:declared=int(length)
   except ValueError:raise MediaError('Invalid photo length','source_unavailable',422) from None
   if declared>MAX_INPUT or declared<1:raise MediaError('Website photo exceeds size limit','source_too_large',413)
  data=response.read(MAX_INPUT+1)
  if len(data)>MAX_INPUT:raise MediaError('Website photo exceeds size limit','source_too_large',413)
  return data,mime
 except (OSError,ssl.SSLError,http.client.HTTPException,WebsiteSafetyError) as exc:
  raise MediaError('Website photo could not be retrieved securely','fetch_failed',422) from exc
 finally:conn.close()

def import_photo(con,draft_id,url,root,*,owner_confirmed=False,fetch=fetch_public_photo,resolve=socket.getaddrinfo):
 _id(draft_id)
 if owner_confirmed is not True:
  raise MediaError('Confirm that you have permission to use this website photo','rights_confirmation_required',403)
 doc=drafts.read_draft(con,draft_id)['document']
 refs=doc.get('websiteImages',[])
 if not isinstance(url,str) or url not in {x.get('url') for x in refs if isinstance(x,dict)}:
  raise MediaError('Select a photograph actually found on this business website','photo_not_in_business',403)
 if len(url)>512:raise MediaError('Invalid source URL','invalid_url',400)
 source_host=urlsplit(doc['sourceUrl']).hostname
 try:
  host,_,_=validate_target(url)
  if host!=source_host:raise MediaError('Website photo belongs to another domain','different_domain',403)
  ip=public_address(host,resolve=resolve)
 except (WebsiteSafetyError,ValueError) as exc:
  raise MediaError('Website photo address is not safe to retrieve','unsafe_source',422) from exc
 existing=con.execute('SELECT * FROM marketing_website_media WHERE draft_id=? AND source_url=?',(draft_id,url)).fetchone()
 if existing:
  item=_public(existing)
  path=Path(root)/'website_photos'/draft_id/(item['id']+'.jpg')
  if not path.is_symlink() and path.is_file() and path.stat().st_size==item['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']:
   return item
  raise MediaError('Previously saved website photo is unavailable or has changed','source_changed',409)
 if con.execute('SELECT count(*) FROM marketing_website_media WHERE draft_id=?',(draft_id,)).fetchone()[0]>=4:
  raise MediaError('Four website photos can be selected per campaign','photo_limit',409)
 try:data,mime=fetch(url,ip)
 except MediaError:raise
 except Exception as exc:raise MediaError('Could not retrieve the website photo','fetch_failed',422) from exc
 if not isinstance(data,bytes) or not data or len(data)>MAX_INPUT or mime not in ('image/jpeg','image/png','image/webp'):
  raise MediaError('The website did not return a usable photo','invalid_image',422)
 try:
  with Image.open(io.BytesIO(data)) as image:
   if image.format not in ('PNG','JPEG','WEBP') or image.width<320 or image.height<240 or image.width*image.height>MAX_PIXELS:
    raise MediaError('Website image is unsuitable for a marketing design','image_dimensions',422)
   if image.get_format_mimetype()!=mime:
    raise MediaError('Website photo type does not match its content','invalid_image',422)
   image.load()
   clean=image.convert('RGB')
   output=io.BytesIO();clean.save(output,'JPEG',quality=87,optimize=True)
   pixels=(image.width,image.height)
 except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError) as exc:
  raise MediaError('Website photo cannot be safely decoded','invalid_image',422) from exc
 safe=output.getvalue()
 if len(safe)>MAX_OUTPUT:raise MediaError('Image exceeds processed size limit','source_too_large',413)
 digest=hashlib.sha256(safe).hexdigest()
 asset_id=hashlib.sha256((draft_id+'|'+url).encode('utf8')).hexdigest()[:32]
 destination=Path(root)/'website_photos'/draft_id
 if destination.is_symlink():raise MediaError('Invalid private photo destination','unsafe_destination',409)
 destination.mkdir(parents=True,exist_ok=True,mode=0o700)
 final=destination/(asset_id+'.jpg')
 if final.exists() or final.is_symlink():raise MediaError('Photo already exists unexpectedly','asset_conflict',409)
 tmp_path=None
 try:
  with tempfile.NamedTemporaryFile(prefix='.pending-',suffix='.jpg',dir=destination,delete=False) as f:
   tmp_path=Path(f.name);os.chmod(tmp_path,0o600);f.write(safe);f.flush();os.fsync(f.fileno())
  os.replace(tmp_path,final)
  con.execute('''INSERT INTO marketing_website_media
   (id,draft_id,source_url,image_sha256,bytes,width,height,owner_declared_at)
   VALUES(?,?,?,?,?,?,?,?)''',
   (asset_id,draft_id,url,digest,len(safe),pixels[0],pixels[1],time.time()))
  con.commit()
 except BaseException:
  if tmp_path:tmp_path.unlink(missing_ok=True)
  final.unlink(missing_ok=True)
  raise
 return _public(con.execute('SELECT * FROM marketing_website_media WHERE id=?',(asset_id,)).fetchone())

def photo_path(con,draft_id,photo_id,root):
 _id(draft_id);_id(photo_id)
 row=con.execute('SELECT * FROM marketing_website_media WHERE id=? AND draft_id=?',(photo_id,draft_id)).fetchone()
 if not row:raise MediaError('Website image not available to this business','not_found',404)
 target=Path(root)/'website_photos'/draft_id/(photo_id+'.jpg')
 if target.is_symlink() or not target.is_file() or target.stat().st_size!=row['bytes']:
  raise MediaError('Saved website photo is unavailable','source_changed',409)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=row['image_sha256']:
  raise MediaError('Saved website photo has changed','source_changed',409)
 return target
