import unittest
from PIL import Image,ImageDraw
from business_brand_render import compose_static_post

class ClassicEditorialTests(unittest.TestCase):
 def test_saved_multiline_brand_and_original_logo_fit_without_losing_copy(self):
  brand=dict(name='Harbour Plumbing and Heating Services',font_style='classic',primary_color='#103e2e',secondary_color='#f5f0e6')
  with Image.new('RGB',(1792,2400),'#916b43') as photo, Image.new('RGBA',(200,90),'#dd3020') as logo:
   for frame,height in [('portrait',1350),('square',1080),('story',1920)]:
    with self.subTest(frame=frame):
     image,meta=compose_static_post(photo,brand,'Help with your home plumbing.','Enquire about a repair.',logo=logo,frame=frame,layout='image-led')
     with image:
      self.assertEqual(image.size,(1080,height))
      name,headline,cta=meta['textBlocks']
      self.assertGreater(name['bottom']-name['top'],100,'Complete brand must wrap rather than truncate')
      self.assertLess(name['bottom'],headline['top'])
      x,y,w,h=meta['photoBox']
      self.assertLessEqual(headline['bottom'],y)
      self.assertGreaterEqual(cta['top'],y+h)
      self.assertGreaterEqual(name['fontSize'],48)
      self.assertEqual(meta['copy'],'Help with your home plumbing.')
      lx,ly,lw,lh=meta['logoBox']
      self.assertEqual(image.getpixel((lx+lw//2,ly+lh//2)),(221,48,32))
      self.assertAlmostEqual(w/h,1792/2400,delta=.004)

 def test_classic_generated_layout_uses_light_ground_and_readable_separate_words(self):
  brand=dict(name='Ledger Lane',font_style='classic',primary_color='#103e2e',secondary_color='#f5f0e6')
  with Image.new('RGB',(1792,2400),'#916b43') as photo:
   ImageDraw.Draw(photo).rectangle((0,0,1791,90),fill='#dd3020')
   for frame,h in [('portrait',1350),('square',1080),('story',1920)]:
    with self.subTest(frame=frame):
     image,meta=compose_static_post(photo,brand,'Your business is your thing. Bookkeeping can be ours.','Book a consultation.',frame=frame,layout='image-led')
     with image:
      self.assertEqual(image.size,(1080,h))
      self.assertEqual(image.getpixel((0,0)),(245,240,230))
      x,y,w,ph=meta['photoBox']
      self.assertAlmostEqual(w/ph,1792/2400,delta=.004)
      self.assertGreater(image.getpixel((x+w//2,y+3))[0],180)
      self.assertLessEqual(meta['textBlocks'][1]['bottom'],y)
      self.assertGreaterEqual(meta['textBlocks'][2]['top'],y+ph)
      self.assertGreaterEqual(meta['textBlocks'][1]['fontSize'],48)
      if frame=='portrait':self.assertGreater(w*ph/(1080*h),.25)
      self.assertEqual(meta['copy'],'Your business is your thing. Bookkeeping can be ours.')
