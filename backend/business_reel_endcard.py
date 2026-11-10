"""Private native branded CTA card; generates no paid AI content.

Requires an explicit owner attestation for contact details. The generated
typography is not presented as a licensed or authentic master brand logo.
"""
from __future__ import annotations
from pathlib import Path
from io import BytesIO
from urllib.parse import urlsplit
import tempfile,os,subprocess,hashlib,re
from PIL import Image,ImageDraw,ImageFont

WIDTH,HEIGHT=720,1280
FRAME_RATE=12
DURATION=4
# One explicit DejaVu set, with no platform discovery or silent substitution.
# Other hosts provision these same faces and set BUSINESS_ENDCARD_FONT_DIR.
DEFAULT_FONT_DIR=Path('/usr/share/fonts/truetype/dejavu')
FONT_FACES={
 ('editorial',False):'DejaVuSerif.ttf',
 ('editorial',True):'DejaVuSerif-Bold.ttf',
 ('sans',False):'DejaVuSans.ttf',
 ('sans',True):'DejaVuSans-Bold.ttf',
}

class EndcardError(ValueError):
 def __init__(self,message,code='endcard_blocked',status=409):
  super().__init__(message);self.code=code;self.status=status

def check_details(name,cta,contact_url,source_url,owner_confirmed):
 if owner_confirmed is not True:raise EndcardError('Owner must confirm brand and contact details','brand_approval_required',403)
 for item,label,low,high in ((name,'business name',3,65),(cta,'call to action',6,80)):
  if not isinstance(item,str) or not low<=len(item.strip())<=high or any(ord(c)<32 for c in item):
   raise EndcardError('Invalid '+label,'invalid_copy',400)
 try:
  url=urlsplit(contact_url);source=urlsplit(source_url)
  if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment or url.hostname!=source.hostname:
   raise ValueError()
 except (ValueError,AttributeError,TypeError):
  raise EndcardError('CTA must use the business’s own verified HTTPS website','invalid_cta',400)
 return name.strip(),cta.strip(),contact_url

def _load_fonts():
 """Snapshot configured font bytes once per render so every frame agrees."""
 folder=Path(os.environ.get('BUSINESS_ENDCARD_FONT_DIR',str(DEFAULT_FONT_DIR)))
 if not folder.is_absolute():
  raise EndcardError('BUSINESS_ENDCARD_FONT_DIR must be an absolute directory','font_unavailable')
 fonts={}
 try:
  for face in FONT_FACES.values():
   path=folder/face
   if path.is_symlink() or not path.is_file():raise OSError('Missing configured font')
   data=path.read_bytes()
   ImageFont.truetype(BytesIO(data),24)
   fonts[face]=data
 except (OSError,ValueError) as exc:
  raise EndcardError('Configured end-card DejaVu fonts are missing or invalid; provision BUSINESS_ENDCARD_FONT_DIR','font_unavailable') from exc
 return fonts

def _font(size,bold=False,style='editorial',fonts=None):
 fonts=_load_fonts() if fonts is None else fonts
 face=FONT_FACES[('editorial' if style=='editorial' else 'sans',bold)]
 return ImageFont.truetype(BytesIO(fonts[face]),size)

def _copy_colour(background):
 # Black or white copy always provides at least 4.5:1 contrast against a solid
 # sRGB brand colour. Decorative accents keep the exact owner-supplied value.
 channels=[v/255 for v in background]
 linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in channels]
 luminance=sum(v*w for v,w in zip(linear,(.2126,.7152,.0722)))
 return (0,0,0) if (luminance+.05)/.05>=1.05/(luminance+.05) else (255,255,255)

def _wrap(draw,text,font,width):
 """Wrap whole words where possible and long identifiers without dropping text."""
 def fits(label):
  box=draw.textbbox((0,0),label,font=font)
  return box[2]-box[0]<=width
 lines=[];line=''
 for word in text.split(' '):
  candidate=(line+' '+word) if line else word
  if fits(candidate):
   line=candidate;continue
  if line:lines.append(line);line=''
  # A long domain or unspaced business name may need character-level wrapping.
  for char in word:
   candidate=line+char
   if line and not fits(candidate):
    # Prefer a visible domain/name boundary over splitting a readable label.
    cut=max(line.rfind('.'),line.rfind('-'))+1
    if cut>=len(line)/2:
     lines.append(line[:cut]);line=line[cut:]+char
    else:lines.append(line);line=char
   else:line=candidate
 if line:lines.append(line)
 return lines

def _text_block(draw,text,box,*,maximum,minimum=24,max_lines=3,bold=False,style='editorial',fill,fonts=None):
 left,top,right,bottom=box;width=right-left
 for size in range(maximum,minimum-1,-2):
  font=_font(size,bold,style,fonts);lines=_wrap(draw,text,font,width)
  bounds=[draw.textbbox((0,0),line,font=font) for line in lines]
  gap=max(6,round(size*.22))
  height=sum(b[3]-b[1] for b in bounds)+gap*(len(lines)-1)
  if not lines or len(lines)>max_lines or height>bottom-top:continue
  y=top+(bottom-top-height)/2
  for line,b in zip(lines,bounds):
   x=left+(width-(b[2]-b[0]))/2-b[0]
   draw.text((round(x),round(y-b[1])),line,font=font,fill=fill)
   y+=b[3]-b[1]+gap
  return
 raise EndcardError('Confirmed text is too long for the safe mobile crop','text_overflow',400)

def _frame(name,cta,contact_url,progress,*,logo=None,primary=None,accent=None,style='editorial',fonts=None):
 if primary and not re.fullmatch('#[0-9A-Fa-f]{6}',primary):raise EndcardError('Unsafe brand colour','invalid_brand')
 if accent and not re.fullmatch('#[0-9A-Fa-f]{6}',accent):raise EndcardError('Unsafe brand colour','invalid_brand')
 if style not in ('editorial','modern','minimal'):raise EndcardError('Unsafe brand title style','invalid_brand')
 fonts=_load_fonts() if fonts is None else fonts
 base=tuple(int(primary[i:i+2],16) for i in (1,3,5)) if primary else (16,35,30)
 accent_rgb=tuple(int(accent[i:i+2],16) for i in (1,3,5)) if accent else (221,174,117)
 copy=_copy_colour(base)
 im=Image.new('RGB',(WIDTH,HEIGHT),base)
 d=ImageDraw.Draw(im)
 # The artwork contains only customer copy. Audit/provenance labels belong in
 # the review interface, never stamped across the finished brand card.
 border=tuple(round(base[i]*.78+copy[i]*.22) for i in range(3))
 d.rounded_rectangle((47,242,673,1049),radius=25,outline=border,width=2)
 progress=max(0,min(1,progress))
 d.line((85,281,85+int(550*progress),281),fill=accent_rgb,width=5)
 fade=max(0,min(1,(progress-.07)/.3))
 if logo is not None:
  # Resize a copy without stretching, cropping, recolouring or changing the
  # immutable owner asset. Wide wordmarks retain their original aspect ratio.
  actual=logo.copy().convert('RGBA')
  actual.thumbnail((320,145),Image.Resampling.LANCZOS)
  x=(WIDTH-actual.width)//2;y=325+(145-actual.height)//2
  actual.putalpha(actual.getchannel('A').point(lambda a:int(a*fade)))
  im=im.convert('RGBA')
  im.alpha_composite(actual,(x,y));im=im.convert('RGB');d=ImageDraw.Draw(im)
 # Each block has a bounded rectangle inside the mobile safe area. Wrapping
 # preserves the owner's exact words, including long names and contact hosts.
 _text_block(d,name,(85,500 if logo is not None else 410,635,635 if logo is not None else 590),
   maximum=68,minimum=24,max_lines=4,bold=True,style=style,fill=copy,fonts=fonts)
 d.line((125,650,595,650),fill=accent_rgb,width=2)
 _text_block(d,cta,(90,685,630,815),maximum=42,minimum=24,max_lines=4,style=style,fill=copy,fonts=fonts)
 display=urlsplit(contact_url).hostname or ''
 _text_block(d,display,(85,855,635,975),maximum=26,minimum=18,max_lines=4,style='minimal',fill=copy,fonts=fonts)
 return im

def render(name,cta,contact_url,source_url,owner_confirmed,output,*,brand=None,logo_path=None):
 name,cta,contact=check_details(name,cta,contact_url,source_url,owner_confirmed)
 output=Path(output)
 if output.exists() or output.is_symlink():raise EndcardError('End card already exists; preserve previous versions','asset_exists',409)
 if output.parent.is_symlink():raise EndcardError('Unsafe private output folder','unsafe_path',409)
 fonts=_load_fonts()
 output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 owner_logo=None
 if brand is not None:
  if not isinstance(brand,dict) or brand.get('locked') is not True or not logo_path:
   raise EndcardError('Genuine verified owner logo required','brand_not_locked',403)
  src=Path(logo_path)
  if src.is_symlink() or not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest()!=brand.get('logoSha256'):
   raise EndcardError('Logo differs from the locked owner asset','brand_source_changed',409)
  with Image.open(src) as img:
   img.load();owner_logo=img.convert('RGBA')
 with tempfile.TemporaryDirectory(prefix='endcard-frames-',dir=output.parent) as folder:
  base=Path(folder)
  for index in range(FRAME_RATE*DURATION):
   image=_frame(name,cta,contact,index/(FRAME_RATE*DURATION-1),logo=owner_logo,primary=brand.get('primary') if brand else None,accent=brand.get('accent') if brand else None,style=brand.get('style','editorial') if brand else 'editorial',fonts=fonts)
   image.save(base/('frame-%03d.png'%index),optimize=False)
  tmp=output.parent/('.pending-'+output.stem+'.mp4')
  try:
   cmd=['ffmpeg','-nostdin','-y','-v','error','-framerate',str(FRAME_RATE),'-i',str(base/'frame-%03d.png'),
    '-vf','fps=24,format=yuv420p','-an','-c:v','libx264','-preset','veryfast','-crf','23',
    '-movflags','+faststart',str(tmp)]
   subprocess.run(cmd,check=True,capture_output=True,timeout=60)
   if not tmp.is_file() or not 3000<tmp.stat().st_size<15*1024*1024:
    raise EndcardError('Native end-card rendering did not produce a valid video','render_failed')
   os.replace(tmp,output)
  except (OSError,subprocess.SubprocessError) as exc:
   raise EndcardError('Could not render native end-card','render_failed') from exc
  finally:tmp.unlink(missing_ok=True)
 data=output.read_bytes()
 return {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'durationSeconds':DURATION,
  'verifiedByOwner':True,'logoProvided':bool(owner_logo),'providerCredits':0,'approvedForPublication':False,
  'fonts':[{'name':face,'sha256':hashlib.sha256(data).hexdigest()} for face,data in fonts.items()]}
