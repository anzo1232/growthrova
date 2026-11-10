import unittest
from PIL import Image
import business_image_quality as quality

class ImageQualityTests(unittest.TestCase):
 def test_flat_image_needs_review(self):
  result=quality.inspect_image(Image.new('RGB',(800,1000),(17,28,38)))
  self.assertEqual(result['qualityStatus'],'technical_review_required')
  self.assertIn('low_visual_detail',result['flags'])
  self.assertFalse(result['ownerApproved'])
 def test_pattern_passes_basic_preflight_without_auto_approval(self):
  image=Image.new('RGB',(800,1000));pixels=image.load()
  for y in range(1000):
   for x in range(800):pixels[x,y]=((19*x+11*y)%256,(11*x+5*y)%256,(7*x+13*y)%256)
  result=quality.inspect_image(image)
  self.assertEqual(result['qualityStatus'],'awaiting_visual_and_brand_review')
  self.assertFalse(result['ownerApproved'])
  self.assertFalse(result['claimsVerified'])
 def test_tiny_input_rejected(self):
  with self.assertRaises(ValueError):quality.inspect_image(Image.new('RGB',(30,40)))
 def test_sparse_word_led_layout_is_held_before_delivery(self):
  image=Image.new('RGB',(800,1000),(12,12,15))
  from PIL import ImageDraw
  draw=ImageDraw.Draw(image)
  for y,width in ((120,430),(190,520),(300,610),(370,560),(810,390)):
   draw.rectangle((70,y,70+width,y+36),fill=(255,255,255))
  draw.rectangle((70,470,125,720),fill=(2,255,178))
  draw.rectangle((675,470,730,720),fill=(2,255,178))
  result=quality.inspect_image(image,detect_sparse=True)
  self.assertIn('sparse_visual_field',result['flags'])
  self.assertEqual(result['qualityStatus'],'technical_review_required')
