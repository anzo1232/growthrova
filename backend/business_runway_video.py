"""Durable one-attempt Runway image-to-video for local Business QA.

Private saved media only. Explicit credit ceiling. Never auto retry, publish or buy credits.
"""
from __future__ import annotations
import base64,hashlib,io,json,os,re,sqlite3,time,uuid,socket,ssl,http.client,subprocess,math
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image
import business_marketing_drafts as drafts
import business_scene_contracts as scene_contracts
import business_runway as runway
import business_video_motion_qc as motion_qc
from business_website_analysis import validate_target,public_address,website_tls_context

CREDITS=25
class VideoError(ValueError):
 def __init__(self,message,code='video_unavailable',status=422):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 scene_contracts.initialise(con)
 con.execute('''CREATE TABLE IF NOT EXISTS runway_video_jobs(
  id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,revision INTEGER NOT NULL,
  fingerprint TEXT UNIQUE NOT NULL,status TEXT NOT NULL,
  provider_task TEXT,source_digest TEXT NOT NULL,request_summary TEXT NOT NULL,
  reserved_credits INTEGER NOT NULL,actual_credits REAL,
  result_json TEXT,error_code TEXT,created REAL NOT NULL,updated REAL NOT NULL)''')

def _id(value):
 if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise VideoError('Invalid video reference','invalid_id',400)
 return value

def _source(path):
 file=Path(path)
 if not file.is_file() or file.is_symlink() or file.stat().st_size>20_000_000:raise VideoError('A saved source image is required')
 try:
  raw=file.read_bytes();digest=hashlib.sha256(raw).hexdigest()
  with Image.open(io.BytesIO(raw)) as im:
   if im.format not in ('PNG','JPEG','WEBP') or min(im.size)<256 or im.width*im.height>20_000_000:raise ValueError()
   im.load();src=im.convert('RGB')
   # Centre-crop to an approved portrait output; keep composition within safe bounds.
   w,h=src.size;aspect=720/1280
   if w/h>aspect:
    nw=round(h*aspect);left=(w-nw)//2;src=src.crop((left,0,left+nw,h))
   else:
    nh=round(w/aspect);top=(h-nh)//2;src=src.crop((0,top,w,top+nh))
   src=src.resize((720,1280),Image.Resampling.LANCZOS)
   b=io.BytesIO();src.save(b,'JPEG',quality=84,optimize=True)
 except (ValueError,OSError,Image.DecompressionBombError) as e:raise VideoError('Cannot use source image safely','invalid_image',422) from e
 if len(b.getvalue())>3_000_000:raise VideoError('Source image too large for the verified API request')
 return digest,'data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode('ascii')

def public(row):
 result=json.loads(row['result_json']) if row['result_json'] else None
 return {'id':row['id'],'draftId':row['draft_id'],'status':row['status'],
  'reservedCredits':row['reserved_credits'],'actualCredits':row['actual_credits'],
  'model':'gen4_turbo','duration':5,'sourceDigest':row['source_digest'],
  'asset':result,'errorCode':row['error_code'],'publishApproved':False,'retryAllowed':False}

def get_job(con,jid):
 row=con.execute('SELECT * FROM runway_video_jobs WHERE id=?',(_id(jid),)).fetchone()
 if not row:raise VideoError('Video job not found','not_found',404)
 return row

def prepare_request(source_file):
 """Exact provider-ready reference and parameters, without provider access."""
 digest,reference=_source(source_file)
 prompt=('A five-second vertical cinematic movement from the provided illustrative luxury-advert still. '
         'Slow stable forward camera dolly, believable parallax, subtle lighting changes and natural reflections. '
         'Preserve the architecture and object identities, avoid warping or new objects. '
         'No text, people, logos, cuts, fake claims or sudden zooms. Premium editorial mood.')
 request={'model':'gen4_turbo','ratio':'720:1280','duration':5,'promptImage':reference,'promptText':prompt}
 return digest,request

def start_job(con,draft_id,expected_revision,source_file,root,*,client=None,max_credits=0,scene_request=None):
 _id(draft_id)
 doc=drafts.read_draft(con,draft_id)
 if type(expected_revision) is not int or expected_revision!=doc['revision']:raise VideoError('Save the current campaign first','revision_conflict',409)
 digest,request=prepare_request(source_file)
 # An internal director can pass a reviewed tailored scene. The browser cannot
 # override this through its existing API payload, and the contract/cap remains
 # mandatory. Reference bytes must be the exact normalised source being sent.
 if scene_request is not None:
  if (not isinstance(scene_request,dict) or set(scene_request)!=set(request) or
      scene_request.get('model')!='gen4_turbo' or scene_request.get('ratio')!='720:1280' or
      type(scene_request.get('duration')) is not int or scene_request['duration']!=5 or
      scene_request.get('promptImage')!=request['promptImage']):
   raise VideoError('Prepared scene settings or reference differ from the reviewed source','scene_request_changed',409)
  request=dict(scene_request)
  try:scene_contracts._request(request)
  except scene_contracts.ContractError as exc:raise VideoError(str(exc),exc.code,exc.status) from exc
 signature_data=([draft_id,expected_revision,digest,request] if scene_request is not None else
                 [draft_id,expected_revision,digest,'gen4_turbo',5])
 signature=hashlib.sha256(json.dumps(signature_data,sort_keys=True).encode()).hexdigest()
 prior=con.execute('SELECT * FROM runway_video_jobs WHERE fingerprint=?',(signature,)).fetchone()
 if prior:return public(prior)
 if con.execute('SELECT 1 FROM runway_video_jobs WHERE draft_id=?',(draft_id,)).fetchone():
  raise VideoError('A paid video attempt already exists. No automatic retries.','paid_retry_disabled',409)
 if type(max_credits) is not int or not CREDITS<=max_credits<=200:raise VideoError('Video credit allowance disabled or too low','spend_disabled',403)
 try:scene_contracts.check(con,draft_id,expected_revision,request,CREDITS)
 except scene_contracts.ContractError as exc:raise VideoError(str(exc),exc.code,exc.status) from exc
 client=client or runway.RunwayClient()
 if client.balance()<CREDITS:raise VideoError('Not enough developer credits','insufficient_credits',402)
 con.execute('BEGIN IMMEDIATE')
 try:
  prior=con.execute('SELECT * FROM runway_video_jobs WHERE fingerprint=?',(signature,)).fetchone()
  if prior:con.commit();return public(prior)
  if con.execute('SELECT 1 FROM runway_video_jobs WHERE draft_id=?',(draft_id,)).fetchone():
   raise VideoError('This business already has a paid video attempt','paid_retry_disabled',409)
  reserved=con.execute('SELECT COALESCE(SUM(reserved_credits),0) FROM runway_video_jobs').fetchone()[0]
  if reserved+CREDITS>max_credits:raise VideoError('Video test budget exceeded','budget_exhausted',403)
  if drafts.read_draft(con,draft_id)['revision']!=expected_revision:raise VideoError('Campaign changed while preparing video','revision_conflict',409)
  jid=uuid.uuid4().hex;now=time.time()
  try:scene_contracts.reserve(con,draft_id,expected_revision,request,CREDITS,jid)
  except scene_contracts.ContractError as exc:raise VideoError(str(exc),exc.code,exc.status) from exc
  con.execute('INSERT INTO runway_video_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,draft_id,expected_revision,signature,'submitting',None,digest,
    json.dumps({'model':'gen4_turbo','duration':5,'ratio':'720:1280','promptText':request['promptText']}),CREDITS,None,None,None,now,now))
  con.commit()
 except BaseException:con.rollback();raise
 try:
  if not hasattr(client,'submit_video'):raise VideoError('Runway video API adapter not available','adapter_missing',503)
  response=client.submit_video(request)
  task=response.get('id')
  if not isinstance(task,str) or not re.fullmatch('[0-9a-fA-F-]{36}',task):raise VideoError('Provider video task not reconciled','unknown_task')
  con.execute("UPDATE runway_video_jobs SET status='queued',provider_task=?,updated=? WHERE id=?",(task,time.time(),jid));con.commit()
 except Exception as exc:
  code=exc.code if isinstance(exc,VideoError) else 'submission_unknown'
  con.execute("UPDATE runway_video_jobs SET status='submission_unknown',error_code=?,updated=? WHERE id=?",(code,time.time(),jid));con.commit()
 return public(get_job(con,jid))

def _store_video(url,destination,*,expected_duration=5):
 if not isinstance(url,str) or len(url)>16384 or any(ord(c)<33 for c in url):raise VideoError('Invalid provider video URL')
 parsed=urlsplit(url)
 if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None,443):raise VideoError('Unsafe provider video URL')
 host,_,_=validate_target('https://'+parsed.hostname);ip=public_address(host)
 class Pinned(http.client.HTTPSConnection):
  def connect(self):
   context=website_tls_context();sock=socket.create_connection((ip,443),timeout=12)
   try:self.sock=context.wrap_socket(sock,server_hostname=host)
   except BaseException:sock.close();raise
 conn=Pinned(host,timeout=20)
 try:
  conn.request('GET',(parsed.path or '/')+('?' + parsed.query if parsed.query else ''),headers={'Host':host,'Accept':'video/mp4'})
  res=conn.getresponse()
  if res.status!=200 or res.getheader('Content-Type','').split(';')[0] not in ('video/mp4','video/quicktime'):
   raise VideoError('Provider output is not a verified video')
  content=res.read(65*1024*1024+1)
  if not 10000<len(content)<=65*1024*1024:raise VideoError('Provider output size invalid')
 finally:conn.close()
 destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 tmp=destination.with_name('.pending-'+uuid.uuid4().hex+'.mp4')
 try:
  with tmp.open('xb') as f:f.write(content)
  os.chmod(tmp,0o600)
  try:
   result=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(tmp)],capture_output=True,text=True,timeout=18,check=True)
   parsed=json.loads(result.stdout);streams=[s for s in parsed['streams'] if s.get('codec_type')=='video']
   duration=float(parsed['format']['duration'])
   if len(streams)!=1 or not expected_duration-0.5<=duration<=expected_duration+0.6 or streams[0].get('height',0)<900 or streams[0].get('width',0)<500:
    raise VideoError('Generated video did not meet expected duration or format')
  except (subprocess.SubprocessError,ValueError,KeyError,json.JSONDecodeError) as exc:
   raise VideoError('Invalid provider video container') from exc
  tmp.replace(destination)
 finally:tmp.unlink(missing_ok=True)
 return {'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'duration':duration,
  'width':streams[0]['width'],'height':streams[0]['height'],'mediaType':'video/mp4','qualityStatus':'pending_human_review'}

def refresh_job(con,jid,root,*,client=None):
 row=get_job(con,jid)
 if row['status'] in ('completed','failed','cancelled','rejected','rejected_quality','submission_unknown','submitting'):return public(row)
 client=client or runway.RunwayClient()
 confirmed_provider_result=False
 try:
  response=client.task(row['provider_task']);confirmed_provider_result=True;status=response.get('status')
  credits=(response.get('cost') or {}).get('credits')
  if type(credits) not in (int,float) or not math.isfinite(credits) or credits<0:credits=None
  if status=='SUCCEEDED':
   outputs=response.get('output')
   if not isinstance(outputs,list) or len(outputs)!=1:raise VideoError('Unexpected provider video outputs')
   target=Path(root)/'generated_videos'/(_id(jid)+'.mp4')
   info=_store_video(outputs[0],target)
   verdict=motion_qc.review(target,expected_duration=5)
   info['motionReview']=verdict
   state='completed' if verdict['technicalMotionPass'] else 'rejected_quality'
   con.execute("UPDATE runway_video_jobs SET status=?,result_json=?,actual_credits=?,error_code=?,updated=? WHERE id=?",
     (state,json.dumps(info),credits,None if state=='completed' else 'insufficient_motion',time.time(),jid))
  elif status in ('FAILED','CANCELLED'):
   con.execute("UPDATE runway_video_jobs SET status=?,error_code=?,actual_credits=?,updated=? WHERE id=?",('failed' if status=='FAILED' else 'cancelled','provider_'+status.lower(),credits,time.time(),jid))
  elif status in ('RUNNING','PENDING','THROTTLED'):
   con.execute("UPDATE runway_video_jobs SET status=?,updated=? WHERE id=?",('running' if status=='RUNNING' else 'queued',time.time(),jid))
  else:raise VideoError('Unknown Runway video status')
  con.commit()
 except Exception as exc:
  con.execute("UPDATE runway_video_jobs SET status=?,error_code=?,actual_credits=COALESCE(?,actual_credits),updated=? WHERE id=?",
   ('rejected_quality' if confirmed_provider_result else row['status'],
    'output_invalid_'+type(exc).__name__ if confirmed_provider_result else 'poll_unavailable_'+type(exc).__name__,
    locals().get('credits') if confirmed_provider_result else None,time.time(),jid));con.commit()
 return public(get_job(con,jid))
