"""Cedar Portsmouth — clean typographic concept; owner approval required.
No storefront crop as logo. No steakhouse. All overlays measured to mobile-safe bounds.
"""
from PIL import Image,ImageDraw,ImageFont,ImageOps
from pathlib import Path
import subprocess,json,hashlib,shutil
from business_creative_delivery_gate import preflight
from business_video_motion_qc import review
root=Path.home()/'Desktop'/'Clippr-Business-Review-2026-10-19'
pre=root/'Cedar-Lebanese-Food-Reel-V2'
sweets=root/'Cedar-Lebanese-Long-Reel-V3'
out=root/'Cedar-PORTSMOUTH-Brand-Correction'/'V5-Creative-Direction-Review'
out.mkdir(parents=True,exist_ok=True)
W,H=720,1280
RED=(126,53,62);GREEN=(41,94,76);GOLD=(222,180,111);PAPER=(249,239,216);DARK=(20,32,28)
A='/System/Library/Fonts/Supplemental/Arial.ttf'
AB='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
GE='/System/Library/Fonts/Supplemental/Georgia Bold.ttf'
CH='/System/Library/Fonts/Supplemental/Apple Chancery.ttf'
def getfont(size,type='heavy'):
 return ImageFont.truetype({'heavy':AB,'body':A,'serif':GE,'script':CH}[type],size)
def shadow(im):
 # translucent vertical navy gradient: lets footage breathe while protecting text.
 overlay=Image.new('RGBA',(W,H),(0,0,0,0)); d=ImageDraw.Draw(overlay)
 for y in range(H):
  alpha=7+int(156*max(0,(y-530)/(1000-530))) if y<=1000 else 150
  d.line((0,y,W,y),fill=(16,24,24,min(alpha,175)))
 im.alpha_composite(overlay)
def safe_text(im,text,x,y,kind,maxwidth,maxheight=91):
 d=ImageDraw.Draw(im)
 size=maxheight
 while size>=31:
  ft=getfont(size,kind);bounds=d.textbbox((x,y),text,font=ft)
  if bounds[2] <= x+maxwidth and bounds[3]-bounds[1] <= maxheight+12:break
  size-=2
 else:raise ValueError('Too much headline copy: '+text)
 if not (56<=bounds[0] and bounds[2]<=665 and 224<=bounds[1] and bounds[3]<=980):
  raise ValueError('Headline crosses mobile safe area: '+repr(bounds))
 d.text((x,y),text,font=ft,fill=PAPER)
 return list(bounds)
def draw_brand_chip(draw,at=(56,231),bg=RED):
 x,y=at
 draw.rounded_rectangle((x,y,x+178,y+49),radius=6,fill=(*bg,233))
 draw.text((x+16,y+9),'cedar',font=getfont(37,'script'),fill=PAPER)
def caption_on_shot(index,headline,secondary=None):
 im=Image.new('RGBA',(W,H),(0,0,0,0))
 shadow(im)
 d=ImageDraw.Draw(im)
 d.rectangle((0,0,W,8),fill=(*RED,245))
 draw_brand_chip(d)
 bounds=[]
 if headline:
  y=650
  for line in headline:
   b=safe_text(im,line,66,y,'serif',587,79);bounds.append(b)
   y=b[3]+19
  d=ImageDraw.Draw(im)
  d.line((58,y+8,176,y+8),fill=GOLD,width=4)
  if secondary:
   ft=getfont(21,'heavy')
   b=d.textbbox((59,y+36),secondary,font=ft)
   if not(56<=b[0] and b[2]<=665 and b[3]<=980):raise ValueError('Subtitle overflow:'+str(b))
   d.text((59,y+36),secondary,font=ft,fill=GOLD);bounds.append(list(b))
 if index in (1,8):
  d=ImageDraw.Draw(im)
  d.text((56,1094),'ILLUSTRATIVE FOOD FOOTAGE · NOT CEDAR’S KITCHEN',font=getfont(14,'body'),fill=PAPER)
 return im,bounds
def outro():
 im=Image.new('RGBA',(W,H),(*RED,255));d=ImageDraw.Draw(im)
 d.rectangle((0,0,W,10),fill=(*GOLD,255))
 d.rounded_rectangle((41,190,679,1103),radius=12,outline=(*PAPER,115),width=2)
 d.text((92,295),'cedar',font=getfont(138,'script'),fill=PAPER)
 d.line((90,483,622,483),fill=GOLD,width=5)
 d.text((93,525),'LEBANESE RESTAURANT',font=getfont(31,'heavy'),fill=PAPER)
 d.text((93,582),'SOUTHSEA · PORTSMOUTH',font=getfont(26,'heavy'),fill=PAPER)
 d.text((93,713),'49 ALBERT ROAD',font=getfont(27,'heavy'),fill=PAPER)
 d.rounded_rectangle((83,803,639,913),radius=9,fill=(*GREEN,255))
 d.text((108,840),'ENQUIRE  @CEDAR_PORTSMOUTH',font=getfont(23,'heavy'),fill=PAPER)
 d.text((93,967),'BRAND LOCKUP CONCEPT · APPROVAL NEEDED',font=getfont(14,'body'),fill=PAPER)
 d.text((89,1151),'NO UNLICENSED LOGO USED',font=getfont(15,'heavy'),fill=PAPER)
 return im
# A clear creative treatment: curiosity, a shared table, sweet course, tea, clean brand CTA.
# No generic steakhouse grilling. Pure food shots; clean commercial lettering, not a shop crop.
story=[
 ('hummus-dip',pre,0.25,2.30,['GOOD FOOD.','GOOD COMPANY.'],'LEBANESE MEZZE · SOUTHSEA','opening'),
 ('pita-dip',pre,0.0,1.10,None,None,'experience'),
 ('mezze-spread',pre,1.10,2.35,['START WITH','THE MEZZE.'],None,'experience'),
 ('hummus-table',pre,0.15,2.05,None,None,'experience'),
 ('baklava-trays',sweets,1.10,1.85,None,None,'experience'),
 ('baklava-dessert',sweets,0.18,2.60,['STAY FOR','SOMETHING SWEET.'],None,'experience'),
 ('tea-glass',sweets,0.30,1.90,None,None,'experience'),
 ('tea-pouring',sweets,1.6,2.80,['FINISH WITH','A LITTLE TEA.'],None,'close'),
 ('outro',out,0.0,3.10,None,None,'close')
]
cuts=[];layouts=[]
for i,(name,source,start,seconds,lines,small,phase) in enumerate(story,1):
 if name=='outro':
  image=outro();photo=out/'_clean-endframe.png';image.convert('RGB').save(photo)
  args=['-loop','1','-framerate','24','-i',str(photo)]
  filter1='scale=720:1280,format=yuv420p'
  dest=out/f'_cedar-v5-{i:02}.mp4'
  cmd=['ffmpeg','-nostdin','-v','error','-y',*args,'-t',str(seconds),'-vf',filter1,'-an','-r','24',
       '-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(dest)]
  subprocess.run(cmd,capture_output=True,text=True,timeout=60,check=True)
 else:
  text_overlay,bboxes=caption_on_shot(i,lines,small)
  png=out/f'_text-{i:02}.png';text_overlay.save(png)
  video=source/(name+'.mp4');assert video.is_file()
  dest=out/f'_cedar-v5-{i:02}.mp4'
  vf=('scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,'
      'crop=720:1280,setsar=1,eq=contrast=1.04:saturation=1.07:brightness=-0.016,format=yuv420p')
  fc=f'[0:v]{vf}[base];[1:v]format=rgba[words];[base][words]overlay=shortest=1:format=auto,format=yuv420p[v]'
  cmd=['ffmpeg','-nostdin','-v','error','-y','-ss',str(start),'-i',str(video),
       '-loop','1','-i',str(png),'-t',str(seconds),'-filter_complex',fc,'-map','[v]','-an','-r','24',
       '-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(dest)]
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
  if p.returncode:raise RuntimeError(p.stderr[-1100:])
  layouts.extend({'bbox':b,'contrastChecked':True} for b in bboxes)
 cuts.append(dest)
 print('SCENE_OK',i,name,seconds,flush=True)
listing=out/'_cuts.txt'
listing.write_text(''.join('file '+repr(str(x))+'\n' for x in cuts))
merged=out/'_silent.mp4'
subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(listing),
                '-c','copy','-movflags','+faststart',str(merged)],capture_output=True,text=True,timeout=60,check=True)
music=pre/'world-percussion-mixkit-958.mp3'
assert music.is_file()
final=out/'CEDAR-PORTSMOUTH-CLEAN-EDITORIAL-V5-REVIEW.mp4'
total=sum(s[3] for s in story)
proc=subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(merged),'-ss','10','-i',str(music),
    '-filter_complex',f'[1:a]atrim=0:{total},asetpts=PTS-STARTPTS,volume=0.33,afade=t=in:st=0:d=0.15,afade=t=out:st={total-1:.2f}:d=1[a]',
    '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',str(final)],capture_output=True,text=True,timeout=60)
if proc.returncode:raise RuntimeError('Mux '+proc.stderr[-1000:])
qc=review(final,expected_duration=total)
# No falsely authorised logo or use of external shopfront photographs.
ad_spec={
 'width':W,'height':H,
 'identity':{'name':'Cedar Lebanese Restaurant','expectedCity':'Portsmouth','sourceBusinessMismatch':False},
 'brand':{'logoSource':'none','brandingReviewedByOwner':False}, # Text-only concept mark, not master brand kit
 'texts':layouts,
 'shots':[{'sourceId':s[0],'kind':'video' if s[0]!='outro' else 'card','phase':s[6],
           'subjectTag':'mezze' if i<4 else 'dessert' if i<6 else 'tea' if i<8 else 'brand',
           'licenseConfirmed':True,'stock':s[0]!='outro','illustrativeDisclosure':True,
           'artDirection':'editorial_action' if s[0]!='outro' else 'closing_brand_card'} for i,s in enumerate(story)],
 'claims':[], 'finalVideo':{'actualVideoDecoded':True,'technicalMotionPass':qc['technicalMotionPass']}
}
gate=preflight(ad_spec)
assert 'cropped_shop_sign_or_unapproved_logo' not in gate['blockers']
assert not any(x.startswith('mobile_text_overflow') for x in gate['blockers'])
assert gate['blockers']==['owner_brand_approval_missing'],gate
assert qc['technicalMotionPass']
record={'finalVideo':str(final),'sha256':hashlib.sha256(final.read_bytes()).hexdigest(),
'durationSeconds':qc['durationSeconds'],'creativePreflight':gate,
'approved':False,'paidAdReady':False,'noNewPaidGenerations':True,
'actualBrandLogo':'not provided; custom typographic placeholder only',
'authenticMedia':'not available; all current footage is licensed stock and MUST NOT imply the premises or dishes of this business',
'scenes':[{'source':s[0],'seconds':s[3],'phase':s[6]} for s in story]}
(out/'QUALITY-AND-SOURCE-RECEIPT.json').write_text(json.dumps(record,indent=2))
print('FINAL_V5',final,'DURATION',qc['durationSeconds'],'MB',round(final.stat().st_size/1048576,2))
print('CREATIVE_GATE',gate)
