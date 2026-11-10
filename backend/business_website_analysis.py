"""Fail-closed public business website extraction for an isolated preview.

DNS is pinned at each HTTPS redirect; HTML is streamed with byte and caller deadlines.
Findings are source-labelled and require the business owner's confirmation.
"""
from __future__ import annotations
import html,ipaddress,re,socket,urllib.parse,http.client,ssl,os,codecs,time,threading,queue,math
from html.parser import HTMLParser
from datetime import datetime, timezone

MAX_WEBSITE_PAGE_BYTES=100*1024*1024

class WebsiteSafetyError(ValueError):pass

def website_tls_context():
 """Preserve platform trust; supply public CA roots only if none were loaded.

 Python.org macOS installations can have an empty default trust store. This
 fallback does not turn off verification or bypass an explicitly configured CA.
 """
 try:
  context=ssl.create_default_context()
  if not context.cert_store_stats().get('x509_ca',0):
   if os.environ.get('SSL_CERT_FILE') or os.environ.get('SSL_CERT_DIR'):
    raise WebsiteSafetyError('Configured TLS trust store contains no trusted CA certificates')
   try:
    import certifi
   except ImportError as exc:
    raise WebsiteSafetyError('No TLS trust roots available; configure a CA bundle') from exc
   context.load_verify_locations(cafile=certifi.where())
  if (not context.cert_store_stats().get('x509_ca',0) or
      context.verify_mode!=ssl.CERT_REQUIRED or not context.check_hostname):
   raise WebsiteSafetyError('Verified TLS certificate trust is required')
  return context
 except (OSError,ssl.SSLError) as exc:
  raise WebsiteSafetyError('TLS trust configuration is unavailable') from exc

# Exclude recognisable consent notices before the evidence budget is consumed.
# Deliberately narrow: mentioning cookies, privacy or analytics alone is not
# enough, since these can be real products or professional services.
CONSENT_NOTICE = re.compile(
 r"^(?:(?:we|this (?:web)?site|our (?:web)?site) (?:use|uses) cookies "
 r"(?:on (?:our|this) (?:web)?site\b|to (?:ensure|improve|deliver|enhance|provide)\b"
 r"[^.!?]{0,100}\b(?:online|browsing|website|site)\b)"
 r"|(?:strictly )?necessary cookies enable core functionality\b"
 r"|we(?:['’]d| would) like to set (?:google analytics )?cookies\b"
 r"|we and our advertising (?:suppliers|partners) use these technologies\b"
 # Consent questions need both a tracking subject and an explicit choice/settings
 # explanation; an analytics service description alone is still business evidence.
 r"|allow\b[^?]{0,180}\b(?:analytics|tracking|cookies)\b[^?]{0,180}\?"
 r"(?=[^\n]{0,1000}\boptional\b)(?=[^\n]{0,1000}\bcookie settings\b))", re.I)

class Extractor(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True)
  self.title='';self.description='';self.headings=[]
  self.links=[];self.images=[];self.service_links=[]
  # Keep two bounded pools so early site-wide copy cannot exhaust the budget
  # before a later service description. Landmarks select evidence, not truth.
  self._primary_paragraphs=[];self._fallback_paragraphs=[]
  self._landmarks={tag:0 for tag in ('main','article','nav','footer','aside')}
  self._paragraph_primary=False
  self._tag=None;self.skip=0;self._paragraph=[];self._link=None
 @property
 def visible_paragraphs(self):
  return list(dict.fromkeys(self._primary_paragraphs+self._fallback_paragraphs))[:12]
 def handle_starttag(self,tag,attrs):
  a={str(key).lower():str(value or '') for key,value in attrs if key}
  if tag in ('script','style','noscript','svg'):self.skip+=1
  if self.skip:return
  if tag in self._landmarks:self._landmarks[tag]+=1
  if tag in ('title','h1','h2','h3'):self._tag=tag
  if tag=='p':
   self._paragraph_primary=bool(self._landmarks['main'] or self._landmarks['article']) and not any(self._landmarks[key] for key in ('nav','footer','aside'))
   self._paragraph=[];self._tag='p'
  if tag=='meta':
   if a.get('name','').lower()=='description':self.description=a.get('content','')[:500]
   if a.get('property','').lower() in ('og:image','og:image:url') and len(self.images)<64:
    self.images.insert(0,{'source':a.get('content',''),'alt':'Site preview image','placement':'social_preview'})
  if tag in ('img','source') and len(self.images)<64:
   # Metadata only: no image fetching or implied usage rights.
   # Explicit pixel dimensions/labels are not useful business photography.
   tiny=any(re.fullmatch(r'\s*[01](?:px)?\s*',a.get(key,''),re.I) for key in ('width','height'))
   if tiny or a.get('alt','').strip().lower() in ('tracking','tracking pixel','tracking beacon'):return
   parts=[part.strip().split() for part in (a.get('data-srcset') or a.get('srcset','')).split(',')[:16] if part.strip()]
   sources=[a.get('data-src') or a.get('data-lazy-src') or a.get('src','')]
   if parts:sources.append(parts[-1][0])
   for source in sources:
    if source and len(self.images)<64:self.images.append({'source':source,'alt':a.get('alt','')[:160],'placement':'page_image'})
  if tag=='a' and a.get('href') and len(self.links)<256:
   self.links.append((a['href'],a.get('aria-label','')))
   self._link={'source':a['href'],'text':[],'label':a.get('aria-label','')}
 def handle_endtag(self,tag):
  if tag in ('script','style','noscript','svg'):
   if self.skip:self.skip-=1
   return
  if self.skip:return
  if tag=='p' and self._tag=='p':
   # Match the existing research-import excerpt ceiling. Clipping at 280 hid
   # service details and seasonal caveats behind otherwise ordinary introductions.
   paragraph=' '.join(' '.join(self._paragraph).split())
   if len(paragraph)>1200:
    portion=paragraph[:1200]
    paragraph=(re.sub(r'\s+\S*$','',portion) if not paragraph[1200].isspace() else portion).rstrip()
   pool=self._primary_paragraphs if self._paragraph_primary else self._fallback_paragraphs
   if len(paragraph)>=24 and not CONSENT_NOTICE.search(paragraph) and len(pool)<12 and paragraph not in pool:
    pool.append(paragraph)
   self._paragraph=[];self._tag=None
  if tag=='a' and self._link:
   label=' '.join(' '.join(self._link['text']).split())[:110] or self._link['label'][:110]
   if label and len(self.service_links)<256:self.service_links.append({'source':self._link['source'],'label':label})
   self._link=None
  if tag==self._tag:self._tag=None
  if tag in self._landmarks and self._landmarks[tag]:self._landmarks[tag]-=1
 def handle_data(self,data):
  if self.skip:return
  t=' '.join(data.split())
  if not t:return
  if self._tag=='title':self.title=(self.title+' '+t).strip()[:200]
  elif self._tag in ('h1','h2','h3'):
   # This exact consent-control label is not a business heading. Filter before
   # the budget; broader analytics/cookie service headings remain evidence.
   if t.casefold()!='analytics cookies' and len(self.headings)<24:self.headings.append(t[:180])
  elif self._tag=='p' and len(self._paragraph)<45:self._paragraph.append(t)
  if self._link and len(self._link['text'])<14:self._link['text'].append(t)

class StreamingExtractor(Extractor):
 """Keep text-node boundaries intact while discarding large non-business payloads."""
 def __init__(self):
  super().__init__()
  self._text='';self._discarding=False;self._quote=None;self._resume=''
 def _flush_text(self):
  if self._text:
   super().handle_data(self._text);self._text=''
 def handle_data(self,data):
  if not self.skip:
   self._text=(self._text+data)[:1201]
 def handle_starttag(self,tag,attrs):
  self._flush_text();super().handle_starttag(tag,attrs)
 def handle_endtag(self,tag):
  self._flush_text();super().handle_endtag(tag)
 @staticmethod
 def _token_end(text,quote=None):
  for match in re.finditer(r"""["'>]""",text):
   char=match.group()
   if quote:
    if char==quote:quote=None
   elif char in ('"',"'"):quote=char
   elif char=='>':return match.end(),None
  return None,quote
 def feed(self,text):
  if self._discarding:
   end,self._quote=self._token_end(text,self._quote)
   if end is None:return
   self._discarding=False
   text=self._resume+text[end:];self._resume=''
  super().feed(text)
  if self.cdata_elem:
   # HTMLParser otherwise retains an entire script/style until its closing tag.
   self.rawdata=self.rawdata[-32:]
  elif self.rawdata.startswith('<!--') and len(self.rawdata)>32:
   self.rawdata='<!--'+self.rawdata[-4:]
  elif len(self.rawdata)>65536:
   # Oversized attributes (e.g. embedded base64 images) are not business facts.
   # Skip that token with quote-aware scanning, preserving meaningful tag state.
   match=re.match(r'<\s*(/?)\s*([a-zA-Z][\w:-]*)',self.rawdata)
   if match:
    _,self._quote=self._token_end(self.rawdata)
    tag=match.group(2).lower()
    self._resume=('<'+match.group(1)+tag+'>') if tag in ('script','style','noscript','svg','p','title','h1','h2','h3','a') else ''
    self._discarding=True
    self.rawdata=''
 def close(self):
  super().close();self._flush_text()

def safe_page_reference(raw,base_url):
 if not isinstance(raw,str) or not raw or len(raw)>500:return None
 try:
  url=urllib.parse.urljoin(base_url,raw.strip())
  u=urllib.parse.urlsplit(url)
  base=urllib.parse.urlsplit(base_url)
  if (u.scheme!='https' or u.hostname!=base.hostname or u.username or u.password or
      u.port not in (None,443) or not u.path or u.path.startswith('//')):
   return None
  return urllib.parse.urlunsplit((u.scheme,u.netloc,u.path,u.query,''))
 except (ValueError,TypeError):
  return None

def safe_image_metadata_reference(raw,base_url):
 # Metadata only. External CDN URLs are never fetched, imported or authorised.
 if not isinstance(raw,str) or not raw or len(raw)>500:return None
 try:
  url=urllib.parse.urljoin(base_url,raw.strip())
  validate_target(url)
  u=urllib.parse.urlsplit(url)
  return urllib.parse.urlunsplit((u.scheme,u.netloc,u.path or '/',u.query,''))
 except (ValueError,TypeError):return None

def validate_target(raw):
 if not isinstance(raw,str) or len(raw)>500 or any(ord(c)<32 or ord(c)==127 or c=='\\' for c in raw):raise WebsiteSafetyError('Invalid website URL')
 u=urllib.parse.urlsplit(raw.strip())
 if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):raise WebsiteSafetyError('Use a public HTTPS website URL')
 host=u.hostname.rstrip('.').lower()
 if len(host)>253 or '.' not in host or host.endswith(('.local','.internal','.localhost','.test')):raise WebsiteSafetyError('Website hostname is not public')
 try:ipaddress.ip_address(host);raise WebsiteSafetyError('IP address URLs are not allowed')
 except ValueError as e:
  if isinstance(e,WebsiteSafetyError):raise
 return host, u.path or '/',u.query

def public_address(host,resolve=socket.getaddrinfo):
 try:results=resolve(host,443,type=socket.SOCK_STREAM)
 except (OSError,ValueError) as exc:raise WebsiteSafetyError('Website cannot be resolved') from exc
 addresses={item[4][0] for item in results}
 if not addresses:raise WebsiteSafetyError('Website has no public address')
 for addr in addresses:
  ip=ipaddress.ip_address(addr)
  if not ip.is_global:raise WebsiteSafetyError('Website resolves to a restricted address')
 return sorted(addresses)[0]

_READER_SLOTS=threading.BoundedSemaphore(2)

def _remaining(deadline):
 remaining=deadline-time.monotonic()
 if remaining<=0:raise WebsiteSafetyError('Website fetch deadline exceeded')
 return remaining

def _parse_chunks(chunks,max_bytes,deadline):
 page=StreamingExtractor();decoder=codecs.getincrementaldecoder('utf-8')(errors='replace');total=0
 for chunk in chunks:
  _remaining(deadline)
  if not isinstance(chunk,bytes):raise WebsiteSafetyError('Invalid website response')
  total+=len(chunk)
  if total>max_bytes:raise WebsiteSafetyError('Page exceeds maximum size')
  page.feed(decoder.decode(chunk))
 page.feed(decoder.decode(b'',final=True));page.close()
 _remaining(deadline)
 return page

def has_business_evidence(page):
 # Metadata and navigation labels do not establish an actual business offering.
 paragraphs=[text for text in page.visible_paragraphs if len(text.strip())>=40]
 return bool(paragraphs and (page.headings or len(paragraphs)>=2 or sum(map(len,paragraphs))>=160))



def _sanitise_logo_svg(raw):
 import xml.etree.ElementTree as ET
 if not isinstance(raw,str) or not raw.lstrip().startswith('<svg') or len(raw.encode())>32768:return None
 try:root=ET.fromstring(raw)
 except ET.ParseError:return None
 allowed={'svg','g','path','rect','circle','ellipse','line','polyline','polygon','defs','clipPath',
          'linearGradient','radialGradient','stop','use','mask'}
 attributes={'viewBox','width','height','x','y','x1','y1','x2','y2','cx','cy','r','rx','ry','d','points',
             'fill','fill-rule','fill-opacity','stroke','stroke-width','stroke-linecap','stroke-linejoin',
             'stroke-opacity','opacity','transform','clip-path','clipPathUnits','gradientUnits','offset',
             'stop-color','stop-opacity','id','mask','preserveAspectRatio','href'}
 def local(name):return name.rsplit('}',1)[-1]
 for node in root.iter():
  if local(node.tag) not in allowed:return None
  node.tag=local(node.tag)
  clean={}
  for key,value in node.attrib.items():
   key=local(key)
   if key not in attributes or len(value)>4096 or any(ord(c)<32 for c in value):continue
   if key in ('href','clip-path','mask') and 'url(' in value and not re.fullmatch(r'url\(#[A-Za-z0-9_.:-]+\)',value):
    continue
   if key=='href' and not value.startswith('#'):continue
   clean[key]=value
  node.attrib.clear();node.attrib.update(clean)
  node.text=None;node.tail=None
 output=ET.tostring(root,encoding='unicode',short_empty_elements=True)
 return output if len(output.encode())<=32768 else None

def _clean_visual_identity(value):
 if not isinstance(value,dict) or value.get('status')!='website_observed_unconfirmed':return None
 def colour(raw):
  return raw.upper() if isinstance(raw,str) and re.fullmatch(r'#[0-9A-Fa-f]{6}',raw) else ''
 background=colour(value.get('background'));text=colour(value.get('text'))
 colours=[]
 for item in value.get('colours',[])[:12]:
  if not isinstance(item,dict):continue
  hex_value=colour(item.get('hex'));count=item.get('count')
  if hex_value and type(count) is int and 1<=count<=10000 and hex_value not in {x['hex'] for x in colours}:
   colours.append({'hex':hex_value,'count':count})
 fonts=[]
 for item in value.get('fontFamilies',[])[:6]:
  if not isinstance(item,dict):continue
  family=item.get('family');count=item.get('count')
  if (isinstance(family,str) and 1<=len(family.strip())<=80 and all(c.isprintable() for c in family)
      and type(count) is int and 1<=count<=10000):
   fonts.append({'family':family.strip(),'count':count})
 logos=[]
 for item in value.get('logoCandidates',[])[:4]:
  if not isinstance(item,dict):continue
  description=item.get('description')
  description=(description.strip()[:120] if isinstance(description,str) else 'Website logo candidate')
  if item.get('kind')=='image_url':
   url=item.get('url')
   try:validate_target(url)
   except (WebsiteSafetyError,TypeError):continue
   logos.append({'kind':'image_url','url':url,'description':description})
  elif item.get('kind')=='inline_svg':
   svg=_sanitise_logo_svg(item.get('svg'))
   if svg:
    import hashlib
    logos.append({'kind':'inline_svg','svg':svg,'sha256':hashlib.sha256(svg.encode()).hexdigest(),
                  'description':description})
 def luminance(hex_value):
  values=[int(hex_value[i:i+2],16)/255 for i in (1,3,5)]
  values=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in values]
  return values[0]*.2126+values[1]*.7152+values[2]*.0722
 def contrast(a,b):
  x,y=luminance(a),luminance(b);return (max(x,y)+.05)/(min(x,y)+.05)
 def saturation(hex_value):
  values=[int(hex_value[i:i+2],16)/255 for i in (1,3,5)]
  high,low=max(values),min(values)
  return 0 if high==low else (high-low)/(1-abs(high+low-1))
 accent=''
 for item in colours:
  candidate=item['hex']
  if candidate not in {background,text} and saturation(candidate)>=.35 and (not background or contrast(candidate,background)>=2.2):
   accent=candidate;break
 secondary=accent or text
 if not background and colours:background=colours[0]['hex']
 if not text:
  text=next((item['hex'] for item in colours if not background or contrast(item['hex'],background)>=4.5),'')
 if not secondary:secondary=text
 if not any((background,text,accent,fonts,logos)):return None
 return {'status':'website_observed_unconfirmed','method':'rendered_computed_styles',
         'roles':{'background':background,'text':text,'accent':accent},
         'colours':colours,'fontFamilies':fonts,'logoCandidates':logos,
         'suggestedBrandKit':{'primary_color':background,'secondary_color':secondary,
          'font_style':('classic' if fonts and re.search(r'serif',fonts[0]['family'],re.I)
                        and not re.search(r'sans',fonts[0]['family'],re.I) else 'modern')}}

def extract_website(raw,*,fetch=None,resolve=socket.getaddrinfo,max_bytes=MAX_WEBSITE_PAGE_BYTES,timeout_seconds=20,renderer=None):
 """Public caller deadline covers DNS, all redirect hops, transfer and parsing."""
 if type(max_bytes) is not int or not 1024<=max_bytes<=MAX_WEBSITE_PAGE_BYTES:
  raise WebsiteSafetyError('Invalid website page limit')
 if (type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds)
     or not 0<timeout_seconds<=20):
  raise WebsiteSafetyError('Invalid website deadline')
 validate_target(raw)
 if not _READER_SLOTS.acquire(blocking=False):raise WebsiteSafetyError('Website reader busy; retry shortly')
 result=queue.Queue(maxsize=1);deadline=time.monotonic()+timeout_seconds
 def work():
  try:result.put((True,_extract_website(raw,fetch,resolve,max_bytes,deadline,renderer,fetch is None)))
  except Exception as exc:result.put((False,exc))
  finally:_READER_SLOTS.release()
 threading.Thread(target=work,daemon=True,name='growthrova-website-reader').start()
 try:ok,value=result.get(timeout=_remaining(deadline))
 except queue.Empty:raise WebsiteSafetyError('Website fetch deadline exceeded') from None
 if not ok:raise value
 return value

def _extract_website(raw,fetch,resolve,max_bytes,deadline,renderer=None,allow_browser=False):
 requested_url=raw;redirects=[];seen=set()
 for hop in range(6):
  _remaining(deadline)
  host,path,query=validate_target(raw)
  url='https://'+host+path+('?'+query if query else '')
  if url in seen:raise WebsiteSafetyError('Website redirect loop')
  seen.add(url)
  ip=public_address(host,resolve)
  _remaining(deadline)
  if fetch is not None:
   data=fetch(url,ip)
   if not isinstance(data,bytes):raise WebsiteSafetyError('Invalid website response')
   page=_parse_chunks((data[i:i+65536] for i in range(0,len(data),65536)),max_bytes,deadline)
   break
  try:import urllib3
  except ImportError as exc:raise WebsiteSafetyError('Safe HTTPS transport unavailable') from exc
  transport=None;response=None
  try:
   remaining=_remaining(deadline)
   transport=urllib3.HTTPSConnectionPool(ip,port=443,
    assert_hostname=host,server_hostname=host,ssl_context=website_tls_context(),
    retries=False,timeout=urllib3.Timeout(total=remaining,connect=min(7,remaining),read=min(8,remaining)),maxsize=1,block=True)
   response=transport.urlopen('GET',path+('?' + query if query else ''),
    headers={'Host':host,'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15',
     'Accept':'text/html','Accept-Encoding':'identity'},redirect=False,preload_content=False)
   _remaining(deadline)
   if response.status in (301,302,303,307,308):
    location=response.headers.get('Location')
    if not location or hop==5:raise WebsiteSafetyError('Website redirect limit exceeded or missing destination')
    raw=urllib.parse.urljoin(url,location)
    validate_target(raw) # Revalidate scheme/credentials/port before following.
    redirects.append(url)
    continue
   if response.status!=200:raise WebsiteSafetyError('Website did not return a reviewable page')
   if 'text/html' not in response.headers.get('Content-Type','').lower():
    raise WebsiteSafetyError('Only HTML pages can be reviewed')
   length=response.headers.get('Content-Length')
   if length and int(length)>max_bytes:raise WebsiteSafetyError('Page exceeds maximum size')
   def chunks():
    while True:
     _remaining(deadline)
     chunk=response.read1(65536,decode_content=True)
     if not chunk:break
     yield chunk
   page=_parse_chunks(chunks(),max_bytes,deadline)
   break
  except (OSError,ssl.SSLError,http.client.HTTPException,ValueError,urllib3.exceptions.HTTPError) as exc:
   if isinstance(exc,WebsiteSafetyError):raise
   raise WebsiteSafetyError('Website could not be fetched safely') from exc
  finally:
   if response is not None:
    response.close()
    response.release_conn()
   if transport is not None:transport.close()
 else:raise WebsiteSafetyError('Website redirect limit exceeded')
 if any(flag in (page.title or '').lower() for flag in ('security checkpoint','attention required','just a moment')):
  raise WebsiteSafetyError('Website is showing a security checkpoint rather than the business content')
 rendering={'status':'not_needed'};visual_identity=None
 needs_content_render=not has_business_evidence(page)
 if renderer is None and allow_browser:
  from business_website_browser import render_website
  renderer=lambda source:render_website(source,deadline=deadline)
 if renderer is not None and (allow_browser or needs_content_render):
  try:
   rendered=renderer(url)
   if not isinstance(rendered,dict) or rendered.get('source_url')!=url or not isinstance(rendered.get('html'),str):
    raise WebsiteSafetyError('Invalid JavaScript renderer source')
   visual_identity=_clean_visual_identity(rendered.get('visual_identity'))
   if needs_content_render:
    body=rendered['html'].encode('utf-8')
    candidate=_parse_chunks([body],min(max_bytes,512*1024),deadline)
    if any(flag in candidate.title.lower() for flag in ('security checkpoint','attention required','just a moment')):
     raise WebsiteSafetyError('Website is showing a security checkpoint rather than business content')
    if has_business_evidence(candidate):page=candidate
   rendering={'status':'rendered','blocked_dependencies':rendered.get('blocked_dependencies',[])[:12],
              'visual_identity':('observed_unconfirmed' if visual_identity else 'unavailable')}
  except WebsiteSafetyError as exc:
   rendering={'status':'unavailable','reason':str(exc)[:200]}
 elif needs_content_render:
  rendering={'status':'unavailable','reason':'JavaScript renderer was not requested for an injected HTML transport'}
 evidence={'status':'sufficient_unconfirmed' if has_business_evidence(page) else 'insufficient',
           'basis':'Visible business text; metadata alone is insufficient. All claims require owner review.'}
 images=[]
 for media in page.images:
  candidate=safe_image_metadata_reference(media['source'],url)
  if candidate and candidate not in {x['url'] for x in images} and len(images)<8:
   images.append({'url':candidate,'alt':media['alt'],'placement':media['placement'],
     'rights_confirmed':False,'authenticity_verified':False})
 services=prioritised_links(page.service_links,url)
 seasonal=[value for value in [page.title,page.description,*page.headings,*page.visible_paragraphs] if re.search(r'\b(start the year|new year|christmas|summer|winter|spring|autumn|limited time|expires?|ends? on|20[0-9]{2})\b',value,re.I)][:8]
 return {'source_url':url,**({'requested_url':requested_url,'redirected_from':redirects} if redirects else {}),'observations':{'title':page.title,'meta_description':page.description,
  'headings':page.headings[:12],'visible_paragraphs':page.visible_paragraphs[:12],
  'service_links':services,'image_candidates':images,
  **({'visual_identity':visual_identity} if visual_identity else {}),
  'external_links':external_page_references(page.service_links,url)},
  'fetched_at':datetime.now(timezone.utc).isoformat(),
  'freshness':{'status':'unknown','seasonal_excerpts':seasonal,
    'warning':'Fetch time does not establish publication date or current availability. Confirm seasonal copy and offers with the owner.'},
  'suggested_actions':['Review the '+item['label']+' page and confirm current details' for item in services[:3]] or ['Confirm services and the enquiry route with the owner'],
  'status':'extracted_unconfirmed','confirmed':False,'evidence':evidence,'rendering':rendering,
  'warning':('Insufficient business evidence. JavaScript content could not be read completely; review supplied business details before planning. ' if evidence['status']=='insufficient' else '')+'Website content is unverified third-party data. Owner must confirm facts before marketing use.'}

# Categories prioritise coverage, never establish business facts or owner goals.
LINK_GROUPS=(('membership',r'member|join'),('dining',r'dining|food|drink|restaurant|menu'),
 ('spa',r'spa\b|treatment|wellness'),('fitness',r'fitness|gym|training|classes'),
 # Keep distinct trade offerings ahead of generic service/contact pages. Otherwise
 # /services/ swallows both plumbing and heating into one diversity slot.
 ('plumbing',r'plumb|drain|leak'),('heating',r'heat|boiler'),
 ('service',r'service|product|repair|roof|plumb|shop'),
 ('pricing',r'pricing|plans|prices'),
 ('booking',r'book|reserv|appointment|enquir|contact|quote'),
 ('story',r'story|about'),('venue',r'location|venue'))

def link_category(label,url):
 text=(label+' '+urllib.parse.urlsplit(url).path).lower()
 for category,pattern in LINK_GROUPS:
  if re.search(r'\b(?:'+pattern+r')',text):return category
 return 'other'

def external_page_references(links,root):
 """Unverified link metadata only; candidate pages are never fetched here."""
 result=[];seen=set()
 for item in links[:256]:
  if not isinstance(item,dict):continue
  raw=item.get('source',item.get('url',''));label=item.get('label','')
  if not isinstance(raw,str) or not isinstance(label,str) or not label.strip():continue
  try:
   candidate=urllib.parse.urljoin(root,raw)
   host,_,_=validate_target(candidate)
   if host==urllib.parse.urlsplit(root).hostname.rstrip('.').lower():continue
   parsed=urllib.parse.urlsplit(candidate)
   if (re.search(r'\.(pdf|jpg|jpeg|png|webp|mp4|zip)$',parsed.path,re.I)
       or re.search(r'privacy|cookie|terms|log[ -]?in|sign[ -]?in',label,re.I)):continue
   candidate=urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path or '/',parsed.query,''))
   if host in seen:continue
   seen.add(host);result.append({'url':candidate,'label':label[:110]})
   if len(result)>=20:break
  except (ValueError,TypeError):continue
 return result

def prioritised_links(links,root):
 choices={}
 for item in links:
  raw=item.get('source',item.get('url',''))
  if not isinstance(raw,str) or raw.strip().startswith('#'):continue
  candidate=safe_page_reference(raw,root)
  if not candidate or candidate.split('?')[0].rstrip('/')==root.split('?')[0].rstrip('/'):continue
  label=item.get('label','')
  if not isinstance(label,str) or not label.strip():continue
  path=urllib.parse.urlsplit(candidate).path
  if re.search(r'skip to|privacy|cookie|terms|accessibility|log[ -]?in|sign[ -]?in',label+' '+path,re.I):continue
  if re.search(r'\.(pdf|jpg|png|webp|mp4|zip)$',path,re.I):continue
  choices.setdefault(candidate,{'url':candidate,'label':label[:110]})
 order={key:i for i,(key,_) in enumerate(LINK_GROUPS)}
 ranked=sorted(choices.values(),key=lambda item:order.get(link_category(item['label'],item['url']),len(order)))
 diverse=[];seen=set()
 for item in ranked:
  category=link_category(item['label'],item['url'])
  if category not in seen:diverse.append(item);seen.add(category)
 return (diverse+[item for item in ranked if item not in diverse])[:10]

def expand_business_audit(report,*,reader=extract_website):
 """Read at most three additional same-domain pages; all facts remain unverified."""
 if not isinstance(report,dict) or report.get('status')!='extracted_unconfirmed':
  raise WebsiteSafetyError('Initial website audit required')
 root=report.get('source_url','')
 validate_target(root)
 observation=report.get('observations') or {}
 links=observation.get('service_links') or []
 if not isinstance(links,list):raise WebsiteSafetyError('Invalid website link collection')
 ranked=prioritised_links([item for item in links if isinstance(item,dict)],root)
 # Distinct kinds first; no recursive crawling and at most three additional reads.
 choices=[];categories=set()
 for link in ranked:
  category=link_category(link['label'],link['url'])
  if category not in categories:choices.append(link);categories.add(category)
 choices.extend(link for link in ranked if link not in choices)
 selected=choices[:3]
 headings=list(observation.get('headings') or [])
 paragraphs=list(observation.get('visible_paragraphs') or [])
 pages=[root];warnings=[]
 page_reports=[report]
 for link in selected:
  url=link['url'];category=link_category(link['label'],url)
  try:
   detail=reader(url)
   actual=detail.get('source_url','')
   validate_target(actual)
   if (detail.get('status')!='extracted_unconfirmed' or
       urllib.parse.urlsplit(actual).hostname.removeprefix('www.')!=urllib.parse.urlsplit(root).hostname.removeprefix('www.')):
    raise WebsiteSafetyError('Unverified secondary source')
   pages.append(actual)
   page_reports.append(detail)
   other=detail.get('observations') or {}
   headings.extend(other.get('headings') or [])
   paragraphs.extend(other.get('visible_paragraphs') or [])
  except WebsiteSafetyError as exc:warnings.append(category+': '+str(exc)[:110])
 for source in page_reports:
  rendering=source.get('rendering') or {}
  if rendering.get('status')=='unavailable' and source.get('evidence',{}).get('status')=='insufficient':
   warnings.append('JavaScript rendering unavailable: '+str(rendering.get('reason','insufficient page content'))[:160])
  warnings.extend(str(reason)[:180] for reason in rendering.get('blocked_dependencies',[])[:12])
 evidence=report.get('evidence')
 if evidence and any(item.get('evidence',{}).get('status')=='sufficient_unconfirmed' for item in page_reports):
  evidence={**evidence,'status':'sufficient_unconfirmed'}
 return {**report,**({'evidence':evidence} if evidence else {}),'observations':{**observation,
   'headings':list(dict.fromkeys(headings))[:48],
   'visible_paragraphs':list(dict.fromkeys(paragraphs))[:48]},
   'audited_page_urls':pages,'enrichment_warnings':warnings,'page_reports':page_reports,
   'coverage':{'status':'partial','max_additional_pages':3,'attempted_urls':[item['url'] for item in selected],
     'omitted_urls':[item['url'] for item in choices[3:]],
     'warning':'Bounded same-site research with sparse-page JavaScript fallback. Omitted, blocked, external and unsupported dependencies are not assessed.'}}
