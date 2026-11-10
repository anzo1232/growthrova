"""Offline deliverable proof: actual images, 4:5 carousel, motion MP4 and written agency pack."""
import io,json,tempfile,unittest,zipfile,subprocess
from pathlib import Path
from PIL import Image
import importlib.util

class AgencyPackTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.image=self.root/'source.png';Image.new('RGB',(840,1050),'#203349').save(self.image)
  self.doc={'version':1,'business':'ENCORE VIP','name':'30-day campaign','goal':'enquiries','sourceUrl':'https://encorevip.uk/',
    'observedFacts':['ENCORE VIP','EncoreVIP is a premium access platform built around exclusivity, ease, and experience. Members enjoy curated opportunities.','Access','Unrivaled.','One','Message.','Consider','It Done.','Three Steps. Zero Stress.'],
    'posts':[{'day':i,'theme':'Post topic '+str(i),'channel':'Instagram','format':'Image advert','objective':'enquiries',
    'copyDraft':'This is a unique and useful draft for day '+str(i),'callToAction':'Enquire with Encore','status':'draft'} for i in range(1,31)],
    'creatives':[{'id':'creative-'+str(i),'format':fmt,'title':name,'ratio':'4:5','brief':'Source-grounded art direction','copyDraft':'Access. Unrivaled.','callToAction':'Enquire with Encore','status':'draft'}
      for i,(fmt,name) in enumerate([('image_ad','Hero advert'),('video_ad','Video concept'),('carousel','Carousel'),('graphic','Info graphic')],1)],
    'canPublish':False,'canSpend':False}
 def test_produces_real_four_format_media_and_complete_agency_exports(self):
  module=importlib.import_module('business_agency_pack')
  result=module.build_pack(self.doc,self.image,self.root/'export')
  base=Path(result['directory'])
  expected=['hero-ad.png','carousel-01.png','carousel-02.png','carousel-03.png','carousel-04.png','carousel-05.png','service-guide.png','short-video-concept.mp4','30-day-plan.csv','email-sequence.md','seo-opportunities.md','paid-advertising-plan.md','lead-capture-plan.md','campaign-summary.md','website-landing-page.html','manifest.json','campaign-kit.zip']
  for file in expected:self.assertTrue((base/file).is_file(),file)
  for file in expected[:7]:
   with Image.open(base/file) as pic:self.assertEqual(pic.size,(1080,1350),file)
  social=list(sorted(base.glob('post-day-*.png')))
  self.assertEqual(len(social),30)
  self.assertEqual(len({f.read_bytes() for f in social}),30)
  for file in social:
   with Image.open(file) as pic:self.assertEqual(pic.size,(1080,1350))
  probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(base/'short-video-concept.mp4')],text=True))
  duration=float(probe['format']['duration']);self.assertTrue(9<=duration<=18,duration)
  video=next(x for x in probe['streams'] if x['codec_type']=='video')
  self.assertEqual((video['width'],video['height']),(720,1280))
  page=(base/'website-landing-page.html').read_text()
  self.assertIn('noindex, nofollow',page)
  self.assertIn('DRAFT PREVIEW',page)
  self.assertNotIn('<form',page)
  with zipfile.ZipFile(base/'campaign-kit.zip') as archive:
   self.assertTrue(set(expected[:-1]).issubset(set(archive.namelist())))
   self.assertEqual(len([x for x in archive.namelist() if x.startswith('post-day-')]),30)
  manifest=json.loads((base/'manifest.json').read_text())
  self.assertFalse(manifest['publishApproved'])
  self.assertFalse(manifest['adReady'])
  self.assertFalse(manifest['brandKitApproved'])
  self.assertIn('brand_identity_and_logo_not_owner_approved',manifest['creativeDeliveryBlockers'])
  quality=json.loads((base/'creative-quality-report.json').read_text())
  self.assertFalse(quality['creativeDelivery']['paidAdReady'])
  self.assertTrue(quality['creativeDelivery']['autoPublishBlocked'])
  self.assertFalse(manifest['clientMediaRightsVerified'])
  self.assertEqual(manifest['assetOrigin'],'generated_scene_and_local_composites')
  self.assertIn('illustrative',manifest['disclosure'].lower())
  for item in ('email-sequence.md','seo-opportunities.md','paid-advertising-plan.md','lead-capture-plan.md'):
   text=(base/item).read_text()
   self.assertGreater(len(text),450,item)
   self.assertNotIn('guaranteed',text.lower(),item)
 def test_missing_source_image_uses_graphic_only_fallback_not_fake_photo(self):
  module=importlib.import_module('business_agency_pack')
  result=module.build_pack(self.doc,None,self.root/'fallback')
  manifest=json.loads((Path(result['directory'])/'manifest.json').read_text())
  self.assertEqual(manifest['assetOrigin'],'typography_only_concepts')
  self.assertTrue((Path(result['directory'])/'hero-ad.png').exists())
 def test_wrong_image_is_rejected_without_partial_approved_pack(self):
  module=importlib.import_module('business_agency_pack')
  with self.assertRaises(ValueError):module.build_pack(self.doc,self.root/'missing.png',self.root/'bad')
 def test_supporting_generated_scene_appears_in_pack_and_is_counted_accurately(self):
  from PIL import Image
  hero_image=self.root/'master-scene.png';support_image=self.root/'detail-scene.png'
  Image.new('RGB',(800,1000),(20,65,95)).save(hero_image)
  Image.new('RGB',(800,1000),(205,145,85)).save(support_image)
  result=__import__('business_agency_pack').build_pack(self.doc,hero_image,self.root/'multiscene',generated_variants=[support_image])
  root=Path(result['directory']);meta=json.loads((root/'manifest.json').read_text())
  self.assertEqual(meta['generatedImageVariations'],1)
  self.assertEqual(meta['paidGenerationCount'],0,'Local rendering must not claim it charged for provider images')
  # Demonstrate different outputs; no new model requests.
  self.assertNotEqual((root/'hero-ad.png').read_bytes(),(root/'carousel-01.png').read_bytes())
  self.assertTrue((root/'short-video-concept.mp4').stat().st_size>10000)
 def test_real_video_is_reused_and_branded_without_claiming_it_is_locally_generated(self):
  import subprocess,json
  source=self.root/'ai-source.mp4'
  subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i','testsrc2=size=720x1280:rate=24:duration=5',
    '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(source)],check=True,capture_output=True,timeout=30)
  result=__import__('business_agency_pack').build_pack(self.doc,self.image,self.root/'video-pack',generated_video=source)
  base=Path(result['directory']);manifest=json.loads((base/'manifest.json').read_text())
  self.assertEqual(manifest['videoOrigin'],'runway_generated_scene_with_local_cta')
  original=base/'runway-video-original.mp4'
  self.assertTrue(original.is_file());self.assertEqual(original.read_bytes(),source.read_bytes())
  output=base/'short-video-concept.mp4'
  probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(output)],text=True))
  self.assertGreater(float(probe['format']['duration']),7)
  self.assertLess(float(probe['format']['duration']),10)
  self.assertIn('runway-video-original.mp4',result['files'])
 def test_excluded_failed_video_does_not_get_replaced_by_misleading_static_video(self):
  from business_agency_pack import build_pack
  result=build_pack(self.doc,self.image,self.root/'no-rejected-video',include_video=False)
  directory=Path(result['directory'])
  self.assertFalse((directory/'short-video-concept.mp4').exists())
  manifest=json.loads((directory/'manifest.json').read_text())
  self.assertEqual(manifest['videoOrigin'],'rejected_needs_new_motion')
  self.assertFalse(any('short-video-concept.mp4'==x for x in manifest['files']))
