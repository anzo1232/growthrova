"""Runway Nano Banana Pro transport for saved Growthrova campaigns.
One submission, durable provider task, explicit refresh. Never auto-retry a charge.
"""
import io,json,re,tempfile
from pathlib import Path
from PIL import Image
import requests
from business_runway import _store_output, RunwayError
MODEL='gemini_image3_pro'
API='https://api.dev.runwayml.com/v1'
RATIOS={'square_2k':'2048:2048','portrait_2k':'1792:2400','landscape_2k':'2400:1792',
        '1024x1024':'2048:2048','1024x1536':'1696:2528','1536x1024':'2528:1696'}
MAX_BYTES=16*1024*1024
class RunwayImageError(ValueError):
 def __init__(self,stage,**details):
  self.diagnostic={'stage':stage,**details}
  super().__init__('Runway image request requires inspection')
def _plain(value, limit=1200):
 text=' '.join(str(value or '').split())
 return text[:limit]

def _quoted(value):
 return '“'+_plain(value,240).replace('“','"').replace('”','"')+'”'

def _brand_lines(source):
 brief=source.get('artDirectionBrief',{})
 profile=brief.get('creativeProfile',{})
 website=profile.get('websiteVisualIdentity') or source.get('business',{}).get('brandIdentity') or {}
 brand=source.get('brandKit',{})
 roles=website.get('roles') or {}
 palette=[]
 for colour in (brand.get('primary_color'),brand.get('secondary_color'),
                roles.get('background'),roles.get('text'),roles.get('accent')):
  if isinstance(colour,str) and colour and colour not in palette:palette.append(colour)
 for item in website.get('colours',[])[:4]:
  colour=item.get('hex') if isinstance(item,dict) else item
  if isinstance(colour,str) and colour and colour not in palette:palette.append(colour)
 fonts=[item.get('family') for item in website.get('fontFamilies',[])[:3]
        if isinstance(item,dict) and item.get('family')]
 identity=profile.get('identity',{})
 lines=['Palette: '+', '.join(palette[:6]) if palette else 'Use the saved brand palette exactly.']
 if roles:lines.append('Colour roles: '+'; '.join(f'{key} {value}' for key,value in roles.items() if value))
 if fonts:lines.append('Observed website type: '+', '.join(fonts)+'. Preserve this family character.')
 elif identity.get('typographicCharacter'):lines.append('Type character: '+_plain(identity['typographicCharacter'],180)+'.')
 return lines

def _memory_lines(source):
 memory=source.get('brandCreativeMemory') or {}
 lines=[]
 references=memory.get('references') or []
 for item in references[:3]:
  if isinstance(item,dict):
   lines.append(f"{_plain(item.get('tag'),40)} is a {_plain(item.get('role'),80)} reference: {_plain(item.get('direction'),220)}")
 results=memory.get('observedResults') or []
 for item in results[:2]:
  if not isinstance(item,dict):continue
  metrics=', '.join(f'{key} {item[key]}' for key in
    ('ctr','cpc','cpl','roas') if item.get(key) not in (None,''))
  line='Observed prior creative signal'
  if item.get('platform'):line+=' on '+_plain(item['platform'],40)
  if item.get('headline'):line+=' for headline '+_quoted(item['headline'])
  if item.get('buyerMotivation'):line+=' and buyer angle '+_quoted(item['buyerMotivation'])
  if metrics:line+=': '+metrics
  lines.append(line+'.')
 if results:
  lines.append('Use these associations only to choose emphasis. Do not print performance figures, imply causation or turn them into claims.')
 return lines

def request_body(source,frame,complete):
 """Compile one concise visual production brief, not an evidence dump."""
 visual=_plain(source.get('visualDirection'),1200)
 business=_plain(source.get('business',{}).get('business'),120)
 if complete:
  copy=source.get('advertCopy',{})
  concept=source.get('selectedConcept') or {}
  brief=source.get('artDirectionBrief',{})
  profile=brief.get('creativeProfile',{})
  channel=source.get('channelCreativeBrief') or {}
  proposition=brief.get('proposition') or {}
  proposition=_plain(proposition.get('quote') if isinstance(proposition,dict) else proposition,320)
  hero=_plain(concept.get('heroVisual'),500) or visual
  logic=_plain(concept.get('conceptLogic'),420)
  motivation=_plain(concept.get('buyerMotivation'),260)
  lines=[
   f'Create one premium, finished {channel.get("channel") or "social"} advertisement in {RATIOS[frame]} format.',
   'CAMPAIGN IDEA',
   'Hero visual: '+hero,
  ]
  if logic:lines.append('Visual meaning: '+logic)
  if motivation:lines.append('Buyer tension: '+motivation)
  if proposition:lines.append('Reviewed proposition: '+proposition)
  lines.extend([
   'COMMERCIAL CLARITY',
   'A cold viewer must understand the core product or service, the relevant customer or asset category and the intended next action within seconds. Keep those commercial nouns and verbs explicit in the exact supplied copy. The visual should dramatise that transaction rather than lead with a secondary benefit, abstract reassurance or generic business metaphor.',
   'ART DIRECTION',
   visual,
   'The hero visual is the dominant focal point. The scene, crop, light, material detail, negative space and typography form one cohesive composition. The offer is understandable from the image before the copy is read.',
   'BRAND SYSTEM',
   *_brand_lines(source),
   'Use the accent colour with restraint for emphasis, preserving clear background, text and accent roles.',
   'COPY HIERARCHY',
   'Render the headline exactly: '+_quoted(copy.get('headline')),
  ])
  if _plain(copy.get('supportingLine')):lines.append('Render the supporting line exactly: '+_quoted(copy['supportingLine']))
  lines.extend([
   'Render the CTA exactly: '+_quoted(copy.get('callToAction')),
   'Use a dominant headline, clearly subordinate supporting line and a separate readable CTA with generous phone-safe margins.',
   'Leave a naturally quiet top-right area for the exact logo overlay. Do not typeset the business name or invent a logo, emblem, interface, metric, offer or additional wording.',
  ])
  platform=_plain(channel.get('platformRule'),320)
  if platform:lines.extend(['PLACEMENT',platform])
  memory_lines=_memory_lines(source)
  if memory_lines:lines.extend(['REFERENCE AND LEARNING SIGNALS',*memory_lines])
  rules=profile.get('antiGeneric',[])[:3]
  if rules:lines.extend(['SPECIFICITY',' '.join(_plain(rule,260) for rule in rules)])
  lines.append(f'The finished visual is unmistakably for {business}; replacing the brand name would not make it suitable for an unrelated company.')
 else:
  lines=[
   f'Create one premium commercial campaign background in {RATIOS[frame]} format for {business}.',
   'ART DIRECTION',visual,
   'Use one dominant focal subject, purposeful crop, believable light, material texture and deliberate negative space for separately composed copy.',
   *_brand_lines(source),
   'Create imagery only. Keep all lettering, logos, UI, metrics and CTA elements outside the image.',
  ]
 prompt='\n'.join(line for line in lines if _plain(line))
 if len(prompt.encode('utf-16-le'))//2>5500:raise ValueError('Runway brief exceeds 5500 characters; narrow the saved context')
 return {'model':MODEL,'promptText':prompt,'ratio':RATIOS[frame],'outputCount':1}
def _json(config,method,path,payload=None,http=None):
 with requests.Session() as session:
  session.trust_env=False
  transport=http or session
  options={'headers':{'Authorization':'Bearer '+config.key,'X-Runway-Version':'2024-11-06','Accept':'application/json'},
           'timeout':(5,25),'allow_redirects':False,'stream':True}
  if payload is not None:options['json']=payload
  with getattr(transport,method)(API+path,**options) as response:
   if response.status_code not in (200,201,202):raise RunwayImageError('http',httpStatus=response.status_code)
   body=bytearray()
   for chunk in response.iter_content(65536):
    body.extend(chunk)
    if len(body)>2*1024*1024:raise RunwayImageError('response_bounds')
   try:return json.loads(body)
   except (ValueError,TypeError):raise RunwayImageError('invalid_json') from None
def submit(config,payload,http=None):
 result=_json(config,'post','/text_to_image',payload,http)
 ident=result.get('id')
 if not isinstance(ident,str) or not re.fullmatch(r'[0-9a-fA-F-]{36}',ident):raise RunwayImageError('task_identity')
 return ident
def poll(config,task,http=None):
 if not isinstance(task,str) or not re.fullmatch(r'[0-9a-fA-F-]{36}',task):raise RunwayImageError('task_identity')
 result=_json(config,'get','/tasks/'+task,http=http)
 if result.get('id')!=task:raise RunwayImageError('task_identity')
 return result
def download_image(url):
 # Existing downloader pins public DNS, validates TLS and rejects redirects,
 # private networks, oversized media and invalid pixels. Normalize to PNG.
 with tempfile.TemporaryDirectory() as temp:
  p=Path(temp)/'output.png'
  try:_store_output(url,p)
  except RunwayError:raise RunwayImageError('output_download') from None
  data=p.read_bytes()
 if len(data)>MAX_BYTES:raise RunwayImageError('output_bounds')
 return data
def validate_dimensions(size,frame):
 expected=tuple(map(int,RATIOS[frame].split(':')))
 if size!=expected:raise RunwayImageError('dimensions',width=size[0],height=size[1])
