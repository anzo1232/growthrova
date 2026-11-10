"""Premium-looking offline campaign artefacts from *saved* evidence and licensed imagery.

Not AI model generation: images are composites and MP4 is a motion edit. Never
treat generated backdrops as authentic photos of customer services or projects.
"""
from __future__ import annotations
import csv,hashlib,io,json,math,os,re,shutil,subprocess,tempfile,zipfile
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from business_landing_page import make_preview
from business_social_quality import campaign_report
from business_creative_delivery_gate import pack_delivery_status

W,H=1080,1350
NAVY=(18,34,49)
GOLD=(219,185,129)
CREAM=(249,243,231)
MOSS=(24,38,32)
FOOTER="ILLUSTRATIVE CREATIVE CONCEPT · SUBJECT TO BUSINESS REVIEW"
SERIF=['/System/Library/Fonts/Supplemental/Georgia.ttf','/Library/Fonts/Georgia.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf']
SANS=['/System/Library/Fonts/Avenir Next.ttc','/System/Library/Fonts/Supplemental/Arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']

def font(size,serif=False):
 for path in SERIF if serif else SANS:
  try:return ImageFont.truetype(path,size)
  except OSError:pass
 return ImageFont.load_default()

def wrap(draw,string,max_width,face):
 words=re.sub(r'\s+',' ',str(string)).strip().split(' ')
 lines=[];line=''
 for word in words:
  candidate=(line+' '+word).strip()
  if draw.textbbox((0,0),candidate,font=face)[2]>max_width and line:lines.append(line);line=word
  else:line=candidate
 if line:lines.append(line)
 return lines

def write_lines(draw,content,x,y,width,face,colour,spacing=14,max_lines=8):
 for line in wrap(draw,content,width,face)[:max_lines]:
  draw.text((x,y),line,font=face,fill=colour,stroke_width=0)
  y+=face.size+spacing
 return y

def crop_cover(source,size=(W,H),focus=(.5,.54)):
 iw,ih=source.size;tw,th=size
 scale=max(tw/iw,th/ih);nw,nh=math.ceil(iw*scale),math.ceil(ih*scale)
 res=source.resize((nw,nh),Image.Resampling.LANCZOS)
 ox=max(0,min(nw-tw,int((nw-tw)*focus[0])));oy=max(0,min(nh-th,int((nh-th)*focus[1])))
 return res.crop((ox,oy,ox+tw,oy+th)).convert('RGB')

def base_frame(source=None,size=(W,H),focus=(.5,.5)):
 if source:return crop_cover(source,size,focus)
 a=Image.new('RGB',size,NAVY);d=ImageDraw.Draw(a)
 w,h=size
 for yy in range(h):
  f=yy/h
  d.line((0,yy,w,yy),fill=(int(18+12*f),int(34+11*f),int(49+2*f)))
 for cx,cy,r in [(int(w*.7),int(h*.8),int(w*.8)),(int(w*.24),int(h*.4),int(w*.5))]:
  d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=(59,68,65),width=2)
 return a

def shade(image,opacity=.6):
 overlay=Image.new('RGBA',image.size,(0,0,0,0));pixels=overlay.load();w,h=image.size
 for y in range(h):
  # More contrast at top so editorial copy remains readable.
  a=int(min(245,255*(opacity*(.94-y/h*.42))))
  for x in range(w):pixels[x,y]=(5,14,26,a)
 return Image.alpha_composite(image.convert('RGBA'),overlay)

def footer(draw,w,h,light=True):
 draw.line((65,h-118,w-65,h-118),fill=GOLD,width=2)
 draw.text((65,h-91),FOOTER,font=font(16),fill=(219,218,206) if light else NAVY)

def hero(source,brand,headline,cta,path):
 img=shade(base_frame(source),.56);d=ImageDraw.Draw(img)
 d.text((65,86),brand.upper(),font=font(30),fill=CREAM)
 d.line((65,160,255,160),fill=GOLD,width=5)
 title_size=76 if len(headline)<40 else 63
 write_lines(d,headline,65,218,W-145,font(title_size,True),CREAM,19,4)
 d.rectangle((65,595,550,690),fill=(15,27,36,215),outline=GOLD,width=2)
 write_lines(d,cta.upper(),88,621,435,font(23),GOLD,9,2)
 footer(d,W,H);img.convert('RGB').save(path,'PNG',optimize=True)

def carousel_topics(observed):
 """Five genuine customer-question angles. Never pretend a graphic is a real job photo."""
 data=' '.join(str(x) for x in observed).lower()
 if re.search(r'roof|gutter|slate|flashing',data):
  return [
   ('IS IT TIME TO CHECK?', 'Is your roof trying to tell you something?', 'Spots you can notice safely from ground level.'),
   ('SIGN ONE', 'A tile out of place?', 'Missing or slipped tiles can leave your home exposed. Ask a roofer to check it.'),
   ('SIGN TWO', 'Gutters overflowing?', 'Overflowing water can be a sign that guttering needs professional attention.'),
   ('WHAT TO ASK', 'What is actually wrong?', 'Ask what needs fixing, what the work includes and what happens next.'),
   ('TAKE THE NEXT STEP', 'Get a clear roofing quote.', 'Tell the business what you have noticed and ask about an inspection.')
  ]
 if re.search(r'concierge|exclusive|premium access|curated|luxury',data):
  return [
   ('ACCESS UNRIVALED','One message. More possibilities.','Explore a memorable experience with Encore VIP concierge.'),
   ('PRIVATE DINING','A table worth planning for.','Share the date, guest count and preferences. Ask what can be arranged.'),
   ('TRAVEL & TRANSFERS','Arrive with the details handled.','Ask about private travel, ground transfers and confirmed availability.'),
   ('EXCLUSIVE EVENTS','Make an entrance.','Discover the available event access and the arrangements involved.'),
   ('REQUEST ACCESS','Ready to enquire about access?','Contact the concierge with the details of what you are looking for.')
  ]
 if re.search(r'restaurant|dining|menu|cafe|brunch',data):
  return [
   ('THE OCCASION', 'Planning somewhere to eat?', 'Choose the experience you want, from a quick lunch to a long evening.'),
   ('THE MENU', 'What is on the menu?', 'Check the current menu and ask about dietary requirements.'),
   ('THE ATMOSPHERE', 'Find your kind of table.', 'Look for genuine photos of the venue and ask about seating.'),
   ('BEFORE YOU VISIT', 'Know before you go.', 'Check opening times, bookings and other useful details.'),
   ('BOOK OR ENQUIRE', 'Make a plan.', 'Visit the official website for the current booking or enquiry route.')
  ]
 return [
  ('THE SERVICE', 'What are you looking for?', 'Start with the result you want, not a sales pitch.'),
  ('THE DETAILS', 'What really matters?', 'Think about timing, scope and what you want included.'),
  ('THE QUESTIONS', 'Ask before you choose.', 'Check the practical details and anything not explained online.'),
  ('THE EVIDENCE', 'Look for genuine proof.', 'Ask for real examples rather than assuming illustrative photos are actual work.'),
  ('THE NEXT STEP', 'Ready to enquire?', 'Use the business website to ask about the service and next steps.')
 ]

def _roof_drawing(draw,i,w=1080):
 """A distinct architecturally recognisable pictogram on each roofing slide."""
 ink=(20,48,60,255);tile=(58,98,107,255);hot=(213,134,58,255)
 if i in (1,2,4,5):
  peak=(540,280);left=(155,540);right=(930,540)
  draw.polygon([peak,left,right],fill=(49,90,102,255))
  draw.line([left,peak,right],fill=ink,width=24,joint='curve')
  draw.rectangle((275,540,815,680),fill=(240,243,236,255),outline=ink,width=9)
  for k in range(5):
   draw.line((245,557+k*20,835,557+k*20),fill=(108,145,141,255),width=3)
  if i==2:
   draw.polygon([(600,387),(677,407),(645,459),(570,439)],fill=hot)
   draw.line([(600,387),(677,407),(645,459),(570,439),(600,387)],fill=ink,width=6)
  if i==4:
   draw.ellipse((655,322,873,540),outline=hot,width=16)
   draw.line((829,506,951,620),fill=hot,width=24)
   draw.line((714,424,750,459,808,382),fill=hot,width=14,joint='curve')
  if i==5:
   draw.rounded_rectangle((710,452,947,675),radius=25,fill=(248,247,237,255),outline=hot,width=10)
   for n in range(3):
    yy=508+n*47
    draw.line((735,yy,760,yy+18,790,yy-16),fill=(50,122,102,255),width=10)
    draw.line((805,yy,900,yy),fill=ink,width=6)
 if i==3:
  # Actual gutter cross-section: pitched eaves, downpipe and pooled water.
  draw.polygon([(150,400),(660,295),(870,390),(425,507)],fill=(56,94,110,255))
  draw.line((135,490,910,490),fill=ink,width=22)
  draw.arc((310,455,935,760),0,180,fill=hot,width=25)
  draw.line((898,590,898,710),fill=ink,width=26)
  for x,y in [(510,360),(620,330),(750,380),(820,350)]:
   draw.ellipse((x,y,x+24,y+35),fill=(104,169,184,255))
  draw.arc((310,455,935,760),0,180,fill=(110,179,200,255),width=12)
 if i==1:
  draw.ellipse((824,250,980,406),fill=hot)
  draw.text((866,275),'!',font=font(88),fill=CREAM)

def _general_illustration(draw,i,accent=(209,168,107,255)):
 x,y=120,280
 if i==2:
  for n,label in enumerate(['01','02','03']):
   cx=220+310*n
   draw.rounded_rectangle((cx-93,395,cx+116,625),radius=29,fill=(34,56,64,255),outline=accent,width=7)
   draw.text((cx-46,434),label,font=font(65,True),fill=CREAM)
   draw.line((cx-40,556,cx+65,556),fill=accent,width=8)
 elif i==3:
  draw.rounded_rectangle((210,290,860,650),radius=38,fill=(40,70,79,255),outline=accent,width=10)
  for k in range(3):draw.line((285,375+90*k,745,375+90*k),fill=CREAM,width=14)
  draw.ellipse((690,340,790,440),fill=accent)
 elif i==4:
  for k in range(3):
   yy=342+k*118
   draw.ellipse((270,yy,337,yy+67),outline=accent,width=11)
   draw.line((292,yy+30,310,yy+48,333,yy+12),fill=accent,width=7)
   draw.rounded_rectangle((390,yy+14,808,yy+57),radius=16,fill=(60,90,95,255))
 elif i==5:
  draw.rounded_rectangle((262,342,817,622),radius=36,outline=accent,width=14,fill=(40,70,78,255))
  draw.line((294,390,548,490,790,390),fill=accent,width=14,joint='curve')
  draw.ellipse((508,454,557,501),fill=CREAM)
 else:
  draw.ellipse((320,290,780,670),outline=accent,width=20)
  draw.ellipse((395,365,705,596),outline=(74,110,118,255),width=9)

def _concierge_drawing(draw,slide):
    # Specific visual shorthand: dining, VIP event; not generic boxes.
    navy=(32,53,65,255);gold=(179,132,78,255);cream=(240,238,227,255)
    if slide==2:
        draw.ellipse((314,320,775,679),fill=(75,96,94,255),outline=gold,width=14)
        for x,y in [(355,357),(630,355),(350,555),(630,565)]:
            draw.ellipse((x,y,x+107,y+88),fill=cream,outline=navy,width=6)
        for x,y in [(525,295),(525,670)]:
            draw.ellipse((x-48,y-30,x+58,y+70),fill=(114,134,119,255),outline=gold,width=8)
        draw.ellipse((484,460,610,564),fill=cream,outline=gold,width=7)
    elif slide==4:
        draw.polygon([(470,315),(620,315),(784,655),(320,655)],fill=(222,204,158,255))
        draw.rounded_rectangle((375,395,705,690),radius=20,fill=navy,outline=gold,width=12)
        draw.rounded_rectangle((438,470,640,650),radius=12,fill=(106,132,139,255))
        for x in (300,770):
            draw.line((x,570,x,685),fill=gold,width=15)
            draw.ellipse((x-20,545,x+20,584),fill=gold)
        draw.arc((300,575,770,790),0,180,fill=gold,width=10)
    else:_general_illustration(draw,slide)

def carousel(source,brand,cta,path_prefix,observed,photo_sources=None):
 """Visual-led 5-frame design; never fabricates photos when source is absent."""
 items=carousel_topics(observed)
 is_roof=bool(re.search(r'roof|gutter|slate|flashing',' '.join(str(x) for x in observed).lower()))
 is_concierge=bool(re.search(r'concierge|private aviation|exclusive event|premium access',' '.join(str(x) for x in observed).lower()))
 tones=[(226,233,227),(239,232,219),(216,229,229),(226,232,221),(217,226,219)]
 paths=[]
 for i,(eyebrow,title,body) in enumerate(items,1):
  # Art direction varies between photo/illustration layouts.
  source_pool=([source] if source is not None else [])+list(photo_sources or [])
  candidate=source_pool[((i-1)//2)%len(source_pool)] if source_pool else None
  has_photo=candidate is not None and i in (1,3,5)
  if has_photo:
   canvas=Image.new('RGBA',(W,H),(23,40,45,255))
   frame=crop_cover(candidate,(W,730),focus=((i-1)/4,.45))
   canvas.paste(frame,(0,0))
   overlay=Image.new('RGBA',(W,730),(13,27,36,76+i*17))
   canvas.alpha_composite(overlay,(0,0))
   d=ImageDraw.Draw(canvas)
   d.rectangle((0,730,W,H),fill=(245,243,236,255))
   ink=(23,41,45,255)
   accent=(125,88,48,255)
  else:
   colour=tones[i-1]
   canvas=Image.new('RGBA',(W,H),(*colour,255))
   d=ImageDraw.Draw(canvas)
   d.rounded_rectangle((60,205,W-60,725),radius=35,fill=(245,244,235,255),outline=(198,209,203,255),width=4)
   if is_roof:_roof_drawing(d,i)
   elif is_concierge:_concierge_drawing(d,i)
   else:_general_illustration(d,i)
   ink=(22,49,57,255);accent=(156,92,43,255)
  d=ImageDraw.Draw(canvas)
  header_col=CREAM if has_photo else ink
  d.text((65,72),str(brand).upper()[:34],font=font(29),fill=header_col)
  d.text((873,82),f'{i:02d}/05',font=font(25),fill=header_col)
  d.line((65,148,1015,148),fill=(209,164,95,255) if has_photo else ink,width=3)
  # Keep the caption below the imagery and make it scannable in three seconds.
  d.text((65,777),eyebrow,font=font(23),fill=accent)
  y=write_lines(d,title,65,830,960,font(52,True),ink,10,3)
  write_lines(d,body,67,min(1080,y+25),928,font(27),ink,8,3)
  if i==5:
   d.rounded_rectangle((65,1177,610,1250),radius=15,fill=ink)
   write_lines(d,str(cta).upper(),88,1200,498,font(23),CREAM,4,1)
  else:d.text((65,1200),'SWIPE  →',font=font(23),fill=accent)
  file=path_prefix.with_name(f'carousel-{i:02d}.png')
  canvas.convert('RGB').save(file,'PNG',optimize=True);paths.append(file)
 return paths

def _is_roofing(observed):
 return bool(re.search(r'roof|gutter|slate|flashing|roofer',' '.join(str(x) for x in observed).lower()))

def checklist_topics(observed):
 if _is_roofing(observed):
  return [('01','Look at the roof safely','Describe visible roof problems from the ground. Never climb onto damaged roofing.'),
          ('02','Ask for a proper check','Ask a qualified roofer what the problem is and what repair they recommend.'),
          ('03','Get a clear written quote','Check materials, scope, timings and what is included before work starts.')]
 if re.search(r'beauty|clinic|salon|treatment',' '.join(str(x) for x in observed).lower()):
  return [('01','Check the treatment','Find out what the service involves and whether it suits your needs.'),
          ('02','Ask the specialist','Confirm qualifications, suitability, costs and any relevant aftercare.'),
          ('03','Arrange a consultation','Use the business website to discuss the next step before booking.')]
 if re.search(r'restaurant|dining|menu|brunch',' '.join(str(x) for x in observed).lower()):
  return [('01','Explore the menu','Check current food options, prices and dietary information.'),
          ('02','Pick your occasion','Ask about opening times and the tables or setting available.'),
          ('03','Enquire or book','Use the restaurant website to confirm availability and book.')]
 return [('01','Explain what you need','Share your priorities, dates and the details that matter to you.'),
         ('02','Check the options','Ask what is available and what is included.'),
         ('03','Make an enquiry','Visit the official website and ask about the next step.')]

def motion_script(observed):
 if _is_roofing(observed):
  return [('Roof problem?','Spotted a leak or missing tile? Stay safe.'),
          ('Get it checked.','Ask what needs fixing and what the work includes.'),
          ('Need a roofing quote?','Make an enquiry and explain the job.')]
 if re.search(r'beauty|clinic|salon|treatment',' '.join(str(x) for x in observed).lower()):
  return [('Looking for a treatment?','Explore the real service information.'),
          ('Know your options.','Ask about suitability and what to expect.'),
          ('Ready to enquire?','Ask for an appointment or consultation.')]
 if re.search(r'restaurant|dining|menu|brunch',' '.join(str(x) for x in observed).lower()):
  return [('Something good on the menu.','Check what is being served today.'),
          ('Plan your next visit.','Explore the setting and current opening times.'),
          ('Book your table.','Find out what is available and enquire.')]
 return [('An experience worth considering.','Begin with what matters to you.'),
         ('Tell us what you need.','Ask about the details and availability.'),
         ('Ready to explore?','Enquire through the official website.')]

def information_graphic(brand,source_info,cta,path):
 canvas=base_frame(None);d=ImageDraw.Draw(canvas)
 d.text((65,82),brand.upper(),font=font(29),fill=GOLD);d.line((65,154,W-65,154),fill=GOLD,width=2)
 write_lines(d,"The enquiry checklist",65,235,920,font(77,True),CREAM,12,2)
 blocks=checklist_topics([brand,source_info])
 for idx,(num,title,body) in enumerate(blocks):
  yy=490+idx*212
  d.text((65,yy),num,font=font(51,True),fill=GOLD)
  d.text((163,yy+7),title,font=font(36),fill=CREAM)
  write_lines(d,body,163,yy+69,800,font(23),CREAM,12,3)
  d.line((65,yy+189,1015,yy+189),fill=(73,85,80),width=2)
 d.text((65,1175),cta.upper(),font=font(25),fill=GOLD)
 footer(d,W,H)
 canvas.save(path,'PNG',optimize=True)

def motion_frame(source,brand,title,body,cta,size=(720,1280),focus=.5,roof_style=False,frame_number=0):
 w,h=size
 frame=shade(base_frame(source,size,focus=(focus,.5)),.68)
 if roof_style and source is None:
  panel=Image.new('RGBA',(1080,1350),(0,0,0,0))
  pd=ImageDraw.Draw(panel);_roof_drawing(pd,(frame_number%5)+1)
  panel=panel.crop((125,215,960,725)).resize((610,372),Image.Resampling.LANCZOS)
  frame.alpha_composite(panel,(52,228))
 d=ImageDraw.Draw(frame)
 d.text((52,95),brand.upper(),font=font(21),fill=GOLD)
 d.line((52,162,w-52,162),fill=GOLD,width=2)
 write_lines(d,title,52,720 if roof_style else 355,w-104,font(52 if roof_style else 58,True),CREAM,14,3)
 write_lines(d,body,55,900 if roof_style else 670,w-110,font(24),CREAM,10,4)
 d.line((52,h-208,164,h-208),fill=GOLD,width=3)
 d.text((52,h-174),cta.upper(),font=font(18),fill=GOLD)
 d.text((52,h-88),"ILLUSTRATIVE MOTION CONCEPT · NOT REAL VENUE FOOTAGE",font=font(11),fill=CREAM)
 return frame.convert('RGB')

def motion_video(source,brand,cta,path,observed=None):
 frames=motion_script(observed or [brand])
 roof_style=_is_roofing(observed or [brand])
 stills=[]
 for i,(title,body) in enumerate(frames):
  f=path.with_name(f'_motion-{i}.png')
  motion_frame(source,brand,title,body,cta,focus=.34+.16*i,roof_style=roof_style,frame_number=i).save(f,'PNG')
  stills.append(f)
 try:
  inputs=[]
  for f in stills:inputs+=['-loop','1','-framerate','15','-t','4','-i',str(f)]
  # Animate a very small diagonal pan on each scene while preserving a
  # 25-55px text safe margin; never claim this is source camera footage.
  pieces=[]
  for n in range(3):
   dx='n*0.42' if n%2==0 else '26-n*0.42'
   dy='n*0.78' if n%2==0 else '49-n*0.78'
   pieces.append(f'[{n}:v]scale=750:1334,crop=720:1280:x={dx}:y={dy},format=yuv420p[v{n}]')
  filters=';'.join(pieces)+';[v0][v1][v2]concat=n=3:v=1:a=0,format=yuv420p[v]'
  cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y',*inputs,
       '-filter_complex',filters,
       '-map','[v]','-c:v','libx264','-preset','veryfast','-crf','22',
       '-pix_fmt','yuv420p','-movflags','+faststart','-t','12',str(path)]
  subprocess.run(cmd,check=True,capture_output=True,timeout=90)
 finally:
  for f in stills:f.unlink(missing_ok=True)

def social_tile(source,brand,post,destination,roof_style=False):
 """Three feed-native visual directions, not 30 identical brochure tiles.

 Concept direction is deterministic and zero-cost. Photos are only supplied
 from the existing rights/technical-review pipeline; no provider call here.
 Captions remain separate from on-image hooks for legibility.
 """
 index=int(post['day'])
 headline=str(post.get('theme','A useful next step')).strip()[:92]
 body=str(post.get('copyDraft','')).strip()
 cta=str(post.get('callToAction','Explore the website')).strip()[:58]
 # Editorial photo, visual explain-it card, and typographic question alternate.
 # No photograph is implied to show a real client job or result.
 style=(index-1)%3
 have_photo=source is not None
 background=base_frame(source) if have_photo and style==0 else Image.new('RGBA',(W,H),
  [(231,237,231,255),(239,231,215,255),(25,48,53,255)][style])
 if have_photo and style==0:background=shade(background,.53)
 draw=ImageDraw.Draw(background)
 if style==0:
  ink=CREAM if have_photo else (26,53,61)
  draw.rounded_rectangle((56,70,550,132),radius=25,fill=(21,43,49,238) if have_photo else (255,255,255,255))
  draw.text((82,85),str(brand).upper()[:27],font=font(27),fill=CREAM if have_photo else (26,53,61))
  draw.line((76,585,230,585),fill=GOLD,width=9)
  write_lines(draw,headline,75,640,925,font(80,True),ink,20,4)
  draw.rounded_rectangle((67,1132,1000,1244),radius=20,fill=(17,35,39,235))
  write_lines(draw,cta.upper(),94,1165,855,font(30),CREAM,8,1)
 elif style==1:
  draw.text((65,64),str(brand).upper()[:35],font=font(30),fill=(26,53,61))
  draw.text((750,68),'EXPLAINED',font=font(23),fill=(117,85,48))
  draw.line((64,138,1015,138),fill=(172,152,112),width=4)
  write_lines(draw,headline,66,188,920,font(60,True),(25,49,53),12,3)
  graphic=Image.new('RGBA',(W,H),(0,0,0,0));ill=ImageDraw.Draw(graphic)
  ill.rounded_rectangle((65,475,1015,923),radius=27,fill=(255,253,246,255),outline=(197,192,175,255),width=4)
  topic=(str(brand)+' '+headline+' '+body).lower()
  if roof_style:_roof_drawing(ill,index%5+1)
  elif any(word in topic for word in ('restaurant','mezze','dining','brunch','food','menu')):
   # Distinct dining illustration: ceramic plate, small dishes, cutlery.
   ill.ellipse((366,520,743,897),fill=(226,223,210,255),outline=(73,91,82,255),width=9)
   ill.ellipse((411,565,698,852),fill=(252,248,237,255),outline=(190,175,147,255),width=8)
   for cx,cy in ((467,641),(596,685),(501,766)):
    ill.ellipse((cx-33,cy-28,cx+33,cy+28),fill=(145,112,66,255),outline=(82,106,70,255),width=5)
   ill.line((296,544,296,834),fill=(65,78,74,255),width=15)
   for x in (267,284,301,318):ill.line((x,539,x,627),fill=(65,78,74,255),width=7)
   ill.line((790,551,790,834),fill=(65,78,74,255),width=15)
  elif any(word in topic for word in ('beauty','salon','skin','treatment','facial','wellness')):
   # Treatment consultation: profile line art and botanical element, not a fake result.
   ill.ellipse((410,542,678,812),outline=(84,103,91,255),width=12)
   ill.arc((498,574,718,812),15,175,fill=(227,220,203,255),width=25)
   ill.line([(414,760),(468,833),(594,833)],fill=(84,103,91,255),width=12)
   ill.line((773,823,773,583),fill=(92,120,81,255),width=11)
   for y in (611,685,756):
    ill.ellipse((725,y-22,773,y+23),fill=(140,162,119,255))
    ill.ellipse((773,y-55,824,y-12),fill=(140,162,119,255))
  elif any(word in topic for word in ('construction','renovation','kitchen','bathroom','builder')):
   ill.polygon([(308,715),(537,543),(775,715)],fill=(204,214,206,255),outline=(43,69,70,255))
   ill.rectangle((352,718,726,857),fill=(227,222,203,255),outline=(43,69,70,255),width=9)
   ill.rectangle((480,755,572,857),fill=(162,182,174,255),outline=(43,69,70,255),width=7)
   ill.line((277,557,796,557),fill=(160,117,69,255),width=6)
  else:_general_illustration(ill,index%5+1)
  background.alpha_composite(graphic);draw=ImageDraw.Draw(background)
  # One useful explanatory thought, not a whole caption squeezed onto a poster.
  brief=body[:148].rsplit(' ',1)[0] if len(body)>148 else body
  draw.rounded_rectangle((60,957,1020,1162),radius=22,fill=(255,255,255,248))
  write_lines(draw,brief,92,989,892,font(32),(28,55,60),12,3)
  draw.text((74,1211),cta.upper()[:49],font=font(25),fill=(37,65,63))
 else:
  draw.text((72,78),str(brand).upper()[:35],font=font(29),fill=CREAM)
  draw.rounded_rectangle((72,241,440,305),radius=28,fill=(208,170,107,255))
  draw.text((99,255),'A QUESTION FOR YOU',font=font(23),fill=(23,45,49))
  draw.line((73,364,1005,364),fill=GOLD,width=5)
  heading=headline.rstrip('.!?')+'?'
  write_lines(draw,heading,70,424,950,font(90,True),CREAM,21,5)
  draw.rounded_rectangle((67,963,1009,1115),radius=22,fill=(234,227,211,255))
  brief=body[:133].rsplit(' ',1)[0] if len(body)>133 else body
  write_lines(draw,brief,96,991,884,font(29),(30,57,59),12,3)
  draw.text((78,1190),cta.upper()[:51]+'  →',font=font(29),fill=GOLD)
 footer(draw,W,H)
 background.convert('RGB').save(destination,'PNG',optimize=True)

def emails(brand,positioning):
 return f"""# {brand} — Three-email enquiry sequence (draft, not sent)
**Basis:** Website positioning only. Confirm offers, sender consent, recipients and contact links before use.

## Email 1 — Introduction
**Subject:** A considered approach to what comes next
**Preview:** The details are worth getting right.

Hello,

Looking into your options? {brand}'s website describes its positioning as: {positioning}

Before you make an enquiry, consider what matters most to you, what you're hoping to achieve and whether you have any specific dates or requirements.

If the service looks relevant, explore the current website information and ask for a conversation about the details.

**CTA:** Explore {brand}'s website and enquire.

## Email 2 — Helpful questions
**Subject:** Three questions worth asking before you decide
**Preview:** A simple checklist for your next enquiry.

Hello,

A strong enquiry often starts with a clear brief. Before choosing a service, consider:
1. What do I actually need, rather than what just looks impressive?
2. Which inclusions, conditions and timings need confirmation?
3. What information would help the team advise me properly?

Save the questions and use them in your next conversation. The answers should come from the business's current information rather than an illustrative advertising image.

**CTA:** Ask about the current service and process.

## Email 3 — Enquiry invitation
**Subject:** Ready to explore the options?
**Preview:** Begin with the details that matter to you.

Hello,

If you've been considering getting in touch with {brand}, a useful next step is to explain what you're looking for and any preferences or constraints.

Use the official website to submit a specific enquiry. Ask the team to clarify current availability, what's included and the next steps before committing.

**CTA:** Make a specific enquiry.

---
Compliance: Draft only. Do not send without lawful recipient consent, sender identification, an unsubscribe mechanism where required, verified service wording and owner approval.
"""

def seo(brand,description,headings,source_url):
 return f"""# {brand} — Website and search visibility opportunities
Source inspected: {source_url}

## What was actually observed
Page description supplied by the site: {description}
Detected headings: {', '.join(headings) or 'No headings detected'}.

## On-page improvements to review
1. **Clarity of the offer:** Check whether a first-time visitor can understand what {brand} does and who the service suits without scrolling excessively.
2. **Search intent:** Identify real search queries customers use for the underlying service before writing headings. Do not assume existing search traffic or rankings.
3. **Information architecture:** Ensure service descriptions, FAQs and the enquiry path are easy to find and consistently named across the site.
4. **Page title and meta description:** Review the actual title and description for readability and search intent; don't promise search positions.
5. **Trust and evidence:** Link to real, permissioned examples or factual service information. Avoid generic claims and unverifiable customer outcomes.
6. **Technical audit required:** Crawl status, indexing, Core Web Vitals, mobile accessibility, schema markup and broken links were NOT tested by this lightweight page extractor.

## Suggested content briefs (not published)
- An introduction to how the enquiry process works
- Questions to ask before choosing a provider
- What customers should prepare when requesting more details
- How to evaluate the current service information

## Measurement plan
Connect a consent-aware analytics tool and Google Search Console to review impressions, clicks, relevant landing pages and actual enquiries. No account data was accessed or invented.
"""

def ads(brand,cta,source_url):
 return f"""# {brand} — Paid advertising campaign proposal (not launched)
**Objective:** Qualified enquiries, with a verified conversion destination.
**Website reference:** {source_url}

## Three testable positioning angles
**A. Brand impression:** Communicate the business's observed positioning in a premium visual. Do not present an AI-rendered location as a genuine owned venue.
**B. Practical clarity:** Use an educational carousel that answers questions before customers enquire. A factual, useful angle can help reduce unsuitable clicks.
**C. Action-led:** Focus on one enquiry action with concise creative and a clear landing page.

## Creative assets prepared by this pack
- Instagram 4:5 image layout
- Five-slide carousel concept with careful disclosure
- Informational graphic
- Vertical MP4 motion concept assembled locally from the creative image and typography (not newly generated footage)

## Before launch
1. Verify the business owns or licenses the brand assets and approves the copy.
2. Confirm the CTA destination, privacy notice, cookie/consent setup and any industry advertising rules.
3. Define a separate test budget and obtain explicit approval for that spend.
4. Install and validate tracking; no conversion results can be claimed now.
5. Test headlines, audiences and placement formats using real results rather than presumed performance.

## Success metrics to capture
Verified enquiries, qualified enquiry rate, cost per qualified enquiry, landing-page conversion and creative-level performance. No performance or spend figures exist yet.

**CTA proposal:** {cta}

All campaigns remain proposals. Zero advertising spend and zero publishing were performed.
"""

def leads(brand,cta):
 return f"""# {brand} — Lead capture and follow-up workflow (design only)
## Intended customer journey
1. Visitor sees approved creative or an informative website page.
2. Visitor follows a verified CTA to the business-owned enquiry channel.
3. Customer submits a voluntary enquiry with the minimum required contact information.
4. Business reviews the enquiry and responds using its own secure, permissioned process.
5. Only genuine enquiries with lawful processing permissions reach the CRM.

## Proposed form fields
- Contact name
- Preferred contact method
- What the customer is interested in
- Preferred dates or relevant practical information
- Consent/privacy notice acknowledgement appropriate to the business and jurisdiction

Avoid asking for unnecessary sensitive personal information.

## Suggested lead stages
New enquiry → More information needed → Qualified → Consultation/quote requested → Customer → Closed without sale.

## Automated follow-up ideas (not active)
- Send the customer a neutral receipt of their submission.
- Alert the owner about a new enquiry.
- Ask for missing non-sensitive details.
- Invite a follow-up only where appropriate and permissioned.

## Operational safeguards
All messages, customer data retention and CRM writes need explicit account connections and controls. Avoid duplicate notifications, prevent cross-business leakage and allow deletion/access requests. No contacts were imported and no messages were sent.

**Recommended CTA wording:** {cta}
**Metrics to implement:** Enquiries received, response time, qualified leads and attributed conversions.
"""

def summary(doc,origin,video_origin="local_motion_concept"):
 return f"""# {doc['business']} — Clippr Business campaign kit
## Status: Internal draft — requires owner review
Source: {doc.get('sourceUrl') or 'business description'}.
Goal: {doc.get('goal') or 'enquiries'}.
Evidence: {', '.join(doc.get('observedFacts',[])[:8])}.
Source-image classification: {origin}.

## What has been produced
- One designed 4:5 hero image advert (locally composed)
- Five finished 4:5 carousel slides (locally composed)
- One branded information graphic (locally composed)
- Video status: {"Previous video rejected as insufficiently relevant or dynamic; a replacement is required before publication" if video_origin=="rejected_needs_new_motion" else "Real generated scene with locally designed CTA" if video_origin=="runway_generated_scene_with_local_cta" else "12-second local motion concept, not generated footage"}
- 30-day draft content calendar in CSV
- Three-email draft follow-up sequence
- Website and SEO opportunity memo (not a technical audit)
- Paid advertising proposal (not launched)
- Enquiry and lead follow-up design (not an active CRM)

## Before anything goes live
Confirm website information, actual services and availability. Review imagery rights, exact brand identity and claims. Approve specific final exported revisions. Connect the real social platforms, analytics and CRM with a separate explicit grant. Confirm each marketing action and any advertising spend.

This kit is an illustration of Clippr's creative production workflow. It is NOT certified agency output for publication, authentic service photography, proof of completed projects or a performance report.
"""

def build_pack(doc,source_image,destination,*,source_photos=None,generated_variants=None,hero_source_is_generated=False,generated_video=None,include_video=True):
 if not isinstance(doc,dict) or doc.get('version')!=1 or len(doc.get('posts',[]))!=30 or len(doc.get('creatives',[]))<4:
  raise ValueError('A complete saved 30-day campaign with four concepts is required')
 if not doc.get('business') or not doc.get('sourceUrl','').startswith('https://'):raise ValueError('Source-backed brand required')
 if source_image is not None:
  src=Path(source_image)
  if not src.is_file() or src.is_symlink():raise ValueError('Verified creative source image is unavailable')
  with Image.open(src) as pic:
   if pic.format not in ('PNG','JPEG','WEBP') or min(pic.size)<256 or pic.width*pic.height>20_000_000:raise ValueError('Unsafe creative source')
   pic.load();source=pic.convert('RGB')
 else:source=None
 photos=[]
 for photo in (source_photos or [])[:4]:
  path=Path(photo)
  if not path.is_file() or path.is_symlink():
   raise ValueError('Approved website photo is unavailable')
  with Image.open(path) as pic:
   if pic.format not in ('PNG','JPEG','WEBP') or min(pic.size)<240 or pic.width*pic.height>20_000_000:
    raise ValueError('Website photo is not suitable for rendering')
   pic.load();photos.append(pic.convert('RGB'))
 generated=[]
 for value in (generated_variants or [])[:3]:
  path=Path(value)
  if path.is_symlink() or not path.is_file():raise ValueError('Additional generated scene is unavailable')
  with Image.open(path) as pic:
   if pic.format not in ('PNG','JPEG','WEBP') or min(pic.size)<256 or pic.width*pic.height>20_000_000:
    raise ValueError('Additional generated scene is unsuitable')
   pic.load();generated.append(pic.convert('RGB'))
 dest=Path(destination);dest.parent.mkdir(parents=True,exist_ok=True)
 if dest.exists():raise ValueError('Do not overwrite a previously generated kit or its evidence')
 observed=doc.get('observedFacts',[])
 brand=str(doc['business']).strip()[:100]
 copy=doc['creatives'][0]
 headline=str(copy.get('copyDraft') or 'Explore what comes next')[:180]
 cta=str(copy.get('callToAction') or 'Make an enquiry')[:100]
 positioning=str(observed[1] if len(observed)>1 else 'Current service information requires confirmation')
 origin=('generated_scene_and_owner_declared_website_photos' if source and photos
         else 'generated_scene_and_local_composites' if source
         else 'owner_declared_website_photos' if photos
         else 'typography_only_concepts')
 primary=source if source is not None else (photos[0] if photos else None)
 with tempfile.TemporaryDirectory(prefix='agency-kit-',dir=dest.parent) as t:
  out=Path(t)
  hero(primary,brand,headline,cta,out/'hero-ad.png')
  carousel(primary,brand,cta,out/'carousel-01.png',observed,photo_sources=(photos+generated))
  information_graphic(brand,positioning,cta,out/'service-guide.png')
  roof_style=bool(re.search(r'roof|gutter|slate|flashing',' '.join(str(x) for x in observed).lower()))
  for post in doc['posts']:
   sources=photos+generated
   photo=(sources[(int(post['day'])-1)%len(sources)] if sources else primary)
   social_tile(photo,brand,post,out/('post-day-'+str(post['day']).zfill(2)+'.png'),roof_style=roof_style)
  if not include_video:
   video_origin='rejected_needs_new_motion'
  elif generated_video is None:
   motion_video((generated[-1] if generated else primary),brand,cta,out/'short-video-concept.mp4',observed)
   video_origin='local_motion_concept'
  else:
   source_video=Path(generated_video)
   if source_video.is_symlink() or not source_video.is_file() or source_video.stat().st_size>65*1024*1024:
    raise ValueError('Saved generated video not found')
   shutil.copyfile(source_video,out/'runway-video-original.mp4')
   endframe=out/'_end-frame.png'
   frame=motion_frame(None,brand,'Ready to explore?','Make your enquiry through the official website.',cta)
   frame.save(endframe)
   try:
    inputs=['-i',str(source_video),'-loop','1','-framerate','24','-t','3','-i',str(endframe)]
    filters='[0:v]fps=24,scale=720:1280,setsar=1,format=yuv420p[v0];[1:v]fps=24,scale=720:1280,setsar=1,format=yuv420p[v1];[v0][v1]concat=n=2:v=1:a=0,format=yuv420p[v]'
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y',*inputs,'-filter_complex',filters,'-map','[v]',
       '-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(out/'short-video-concept.mp4')],check=True,timeout=90,capture_output=True)
   finally:endframe.unlink(missing_ok=True)
   video_origin='runway_generated_scene_with_local_cta'

  landing_source=(Path(source_image) if source is not None else Path(source_photos[0]) if photos else None)
  make_preview(doc,landing_source,out/'website-landing-page.html',
    photo_origin=('owner_declared' if source is None and photos else 'generated'))
  with (out/'30-day-plan.csv').open('w',encoding='utf-8-sig',newline='') as f:
   writer=csv.writer(f)
   writer.writerow(['Day','Channel','Format','Theme','Objective','Copy','CTA','Status','Proof needed'])
   for p in doc['posts']:
    writer.writerow([p.get(x,'') for x in ('day','channel','format','theme','objective','copyDraft','callToAction','status','proofNeeded')])
  docs={'email-sequence.md':emails(brand,positioning),
        'seo-opportunities.md':(doc.get('websiteAuditText') or seo(brand,positioning,observed[2:],doc['sourceUrl'])),
        'paid-advertising-plan.md':ads(brand,cta,doc['sourceUrl']),
        'lead-capture-plan.md':leads(brand,cta),
        'campaign-summary.md':summary(doc,origin,video_origin)}
  for file,body in docs.items():(out/file).write_text(body,encoding='utf8')
  quality=campaign_report(doc['posts'],authentic_photo_count=len(photos),illustrative_photo_count=len(generated)+(1 if source is not None else 0))
  quality['creativeDelivery']=pack_delivery_status(doc,asset_origin=origin,video_origin=video_origin)
  (out/'creative-quality-report.json').write_text(json.dumps(quality,indent=2),encoding='utf8')
  manifest={'version':1,'business':brand,'motionScript':motion_script(observed),
    'adReady':False,'brandKitApproved':False,'creativeDeliveryBlockers':quality['creativeDelivery']['blockingReasons'],
    'socialQuality':{'screened':quality['reviewed'],'rejectedByPreflight':quality['rejected'],'humanReviewRequired':True},
    'websitePhotoCount':len(photos),'generatedImageVariations':len(generated),'videoOrigin':video_origin,
    'websitePhotoRightsStatus':'owner_declared_not_independently_verified' if photos else 'none','sourceUrl':doc['sourceUrl'],'assetOrigin':origin,
    'disclosure':'Generated scene is illustrative, not a real business location or customer outcome. All artwork and copy require approval.',
    'publishApproved':False,'clientMediaRightsVerified':False,
    'paidGenerationCount':0,'actualGeneratedModelImagesInThisPack':(1 if hero_source_is_generated and source is not None else 0)+len(generated),
    'renderType':'local_image_composite_and_ffmpeg_motion_concept',
    'files':sorted([x.name for x in out.iterdir() if x.is_file()])}
  manifest['fileSHA256']={file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in out.iterdir() if file.is_file()}
  (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
  with zipfile.ZipFile(out/'campaign-kit.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=7) as archive:
   for f in sorted(out.iterdir()):
    if f.name!='campaign-kit.zip':archive.write(f,arcname=f.name)
  # Keep the package privately on this machine; caller is responsible for auth and revision binding.
  os.replace(out,dest)
 return {'directory':str(dest),'files':sorted(x.name for x in dest.iterdir()),'manifest':manifest}
