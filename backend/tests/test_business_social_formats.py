"""Fastlane-inspired feed variety without false UGC, auto-publishing or paid generation."""
import tempfile, unittest
from pathlib import Path
from PIL import Image, ImageChops, ImageStat
import business_agency_pack as pack

class SocialFormatTests(unittest.TestCase):
 def test_three_visually_distinct_post_families_for_multiple_sectors(self):
  cases=[('Roofing','Overflowing gutters',True),('Restaurant','What makes a good dinner out',False),('Beauty','Choosing a suitable treatment',False)]
  with tempfile.TemporaryDirectory() as tmp:
   for business,topic,roof in cases:
    images=[]
    for day in range(1,4):
     dest=Path(tmp)/f'{business}-{day}.png'
     pack.social_tile(None,business,{'day':day,'theme':topic,'copyDraft':'Practical things to consider before booking. Ask the business for current details and availability.','callToAction':'Ask a question'},dest,roof_style=roof)
     with Image.open(dest) as picture:
      self.assertEqual(picture.size,(1080,1350))
      images.append(picture.convert('RGB'))
    for i in range(3):
     for j in range(i+1,3):
      stat=ImageStat.Stat(ImageChops.difference(images[i],images[j]))
      self.assertGreater(sum(stat.mean)/3,22,(business,i,j,stat.mean))
