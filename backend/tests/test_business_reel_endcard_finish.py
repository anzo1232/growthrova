"""Synthetic artwork fixtures only; no customer creative or provider calls."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
import business_reel_endcard as endcard


def luminance(rgb):
 values=[v/255 for v in rgb[:3]]
 channels=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
 return sum(v*w for v,w in zip(channels,(.2126,.7152,.0722)))


def contrast(a,b):
 x,y=sorted((luminance(a),luminance(b)))
 return (y+.05)/(x+.05)


class EndcardFinishTests(unittest.TestCase):
 def test_explicit_linux_font_directory_renders_real_copy_and_video(self):
  # These are real FreeType faces, not a mocked font loader or bitmap fallback.
  with patch.dict(os.environ,{'BUSINESS_ENDCARD_FONT_DIR':'/usr/share/fonts/truetype/dejavu'}):
   image,drawn=self.frame()
   self.assertEqual(image.size,(720,1280))
   self.assertTrue(all(item['bounds'][2]>item['bounds'][0] for item in drawn))
   with tempfile.TemporaryDirectory() as folder:
    output=Path(folder)/'synthetic.mp4'
    meta=endcard.render('Synthetic Local Studio','Explore our services',
      'https://example.org/','https://example.org/',True,output)
    probe=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams',
      '-show_format','-of','json',str(output)],check=True,capture_output=True,timeout=15).stdout)
    video=[s for s in probe['streams'] if s['codec_type']=='video']
    self.assertEqual(len(video),1)
    self.assertFalse(any(s['codec_type']=='audio' for s in probe['streams']))
    self.assertEqual((video[0]['width'],video[0]['height']),(720,1280))
    self.assertEqual(int(video[0]['nb_frames']),96)
    self.assertAlmostEqual(float(probe['format']['duration']),4,places=2)
    decoded=subprocess.run(['ffmpeg','-nostdin','-v','error','-ss','3.9','-i',str(output),
      '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],
      check=True,capture_output=True,timeout=15).stdout
    actual=Image.frombytes('RGB',image.size,decoded)
    # Verify encoded copy in each block, beyond successful file creation.
    for box in ((85,410,635,590),(90,685,630,815),(85,855,635,975)):
     crop=actual.crop(box)
     pixels=list(crop.get_flattened_data() if hasattr(crop,'get_flattened_data') else crop.getdata())
     self.assertGreater(sum(min(p)>220 for p in pixels),100)
    self.assertEqual(meta['sha256'],hashlib.sha256(output.read_bytes()).hexdigest())
    self.assertFalse(meta['approvedForPublication'])
    expected={face:hashlib.sha256((Path('/usr/share/fonts/truetype/dejavu')/face).read_bytes()).hexdigest()
      for face in endcard.FONT_FACES.values()}
    self.assertEqual({f['name']:f['sha256'] for f in meta['fonts']},expected)

 def test_invalid_explicit_font_configuration_blocks_before_render_without_fallback(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   corrupt=root/'corrupt';corrupt.mkdir()
   for face in endcard.FONT_FACES.values():(corrupt/face).write_bytes(b'not a font')
   for configured in (str(root/'missing'),str(corrupt),'relative-fonts',''):
    with self.subTest(configured=configured),patch.dict(os.environ,{'BUSINESS_ENDCARD_FONT_DIR':configured}),patch.object(endcard.subprocess,'run') as run:
     output=root/'uncreated'/'card.mp4'
     with self.assertRaises(endcard.EndcardError) as caught:
      endcard.render('Synthetic Local Studio','Explore our services',
       'https://example.org/','https://example.org/',True,output)
     self.assertEqual(caught.exception.code,'font_unavailable')
     self.assertFalse(output.parent.exists())
     run.assert_not_called()

 def test_provisioned_font_directory_supports_each_style_and_preserves_snapshot(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   for face in endcard.FONT_FACES.values():
    shutil.copyfile(Path('/usr/share/fonts/truetype/dejavu')/face,root/face)
   with patch.dict(os.environ,{'BUSINESS_ENDCARD_FONT_DIR':folder}):
    fonts=endcard._load_fonts()
    # Frames use the captured bytes even if host files change mid-render.
    for face in endcard.FONT_FACES.values():(root/face).unlink()
    for style in ('editorial','modern','minimal'):
     image,drawn=self.frame(style=style,fonts=fonts)
     self.assertEqual(image.size,(720,1280))
     self.assertIn('example.org',' '.join(d['text'] for d in drawn))

 def frame(self,name='Synthetic Local Studio',cta='Explore our services',contact='https://example.org/',**kwargs):
  drawn=[]
  original=ImageDraw.ImageDraw.text
  def capture(draw,xy,text,*args,**options):
   font=options.get('font')
   drawn.append({'text':text,'bounds':draw.textbbox(xy,text,font=font),
     'fill':options.get('fill')})
   return original(draw,xy,text,*args,**options)
  with patch.object(ImageDraw.ImageDraw,'text',capture):
   image=endcard._frame(name,cta,contact,1,**kwargs)
  return image,drawn

 def test_customer_artwork_has_no_internal_review_labels(self):
  for logo in (None,Image.new('RGBA',(160,80),(245,0,245,255))):
   with self.subTest(with_logo=logo is not None):
    _,drawn=self.frame(logo=logo)
    text=' '.join(x['text'] for x in drawn)
    self.assertNotIn('OWNER-APPROVED',text)
    self.assertNotIn('MASTER LOGO',text)
    self.assertNotIn('OWNER LOGO',text)
    self.assertIn('Synthetic Local Studio',text)
    self.assertIn('Explore our services',text)
    self.assertIn('example.org',text)

 def test_all_copy_has_readable_contrast_on_light_and_dark_brand_colours(self):
  for primary in ('#FFFFFF','#F5ECD8','#172832','#000000','#858585'):
   with self.subTest(primary=primary):
    image,drawn=self.frame(primary=primary,accent='#CC8844')
    for item in drawn:
     background=image.getpixel((20,min(1279,max(0,item['bounds'][1]))))
     self.assertGreaterEqual(contrast(item['fill'],background),4.5,item['text'])

 def test_long_exact_copy_wraps_inside_mobile_safe_area(self):
  name='W'*65
  cta='Explore authentic local experiences and reserve your next visit with our studio'
  domain='long-local-studio-name-for-real-owner-contact.example.org'
  _,drawn=self.frame(name,cta,'https://'+domain+'/',logo=Image.new('RGBA',(160,80),(245,0,245,255)))
  for item in drawn:
   left,top,right,bottom=item['bounds']
   self.assertGreaterEqual(left,55,item['text'])
   self.assertGreaterEqual(top,220,item['text'])
   self.assertLessEqual(right,665,item['text'])
   self.assertLessEqual(bottom,1000,item['text'])
  joined=''.join(x['text'].replace(' ','') for x in drawn)
  self.assertIn(name,joined)
  self.assertIn(cta.replace(' ',''),joined)
  self.assertIn(domain,joined)

 def test_logo_aspect_and_source_pixels_are_preserved(self):
  logo=Image.new('RGBA',(256,128),(245,0,245,255))
  before=hashlib.sha256(logo.tobytes()).hexdigest()
  image,_=self.frame(logo=logo)
  self.assertEqual(hashlib.sha256(logo.tobytes()).hexdigest(),before)
  mask=image.point(lambda _:0).convert('L')
  pixels=image.get_flattened_data() if hasattr(image,'get_flattened_data') else image.getdata()
  mask.putdata([255 if pixel==(245,0,245) else 0 for pixel in pixels])
  left,top,right,bottom=mask.getbbox()
  self.assertAlmostEqual((right-left)/(bottom-top),2,places=2)
  self.assertGreaterEqual(left,55)
  self.assertLessEqual(right,665)
  self.assertGreaterEqual(top,220)
  self.assertLessEqual(bottom,1000)


if __name__=='__main__':unittest.main()
