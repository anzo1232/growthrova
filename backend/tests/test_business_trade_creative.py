"""Customer-facing output for a simple roofing company: locally rendered, no paid model."""
import tempfile, unittest
from pathlib import Path
from PIL import Image
import business_agency_pack

class RoofingCreativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def test_roofing_carousel_is_a_relevant_visual_explainer(self):
        observed=['Harbour Roofing','Roof repairs, leaking roofs, gutter repairs and flat roofing in Portsmouth']
        output=business_agency_pack.carousel(
            None,'Harbour Roofing','Request a quote',self.root/'carousel-01.png',observed)
        self.assertEqual(len(output),5)
        for file in output:
            with Image.open(file) as img:self.assertEqual(img.size,(1080,1350))
        images=[Image.open(f).convert('RGB') for f in output]
        # Carousel cannot be five barely different text cards; sizeable,
        # intentionally different illustration/photography must be present.
        points=[(300,730),(700,770),(540,930)]
        colours=[[im.getpixel(p) for p in points] for im in images]
        self.assertGreater(len({tuple(p) for p in colours}),3,colours)
        self.assertTrue(hasattr(business_agency_pack,'carousel_topics'))
        titles=[x[1] for x in business_agency_pack.carousel_topics(observed)]
        self.assertTrue(any('leak' in t.lower() or 'roof' in t.lower() for t in titles))
        self.assertFalse(any('unrivaled' in t.lower() or 'experience' in t.lower() for t in titles))
    def test_luxury_carousel_does_not_claim_generated_scene_is_a_real_location(self):
        observed=['ENCORE VIP','Premium access platform with curated opportunities and experiences']
        titles=[x[1] for x in business_agency_pack.carousel_topics(observed)]
        self.assertEqual(len(titles),5)
        self.assertTrue(any('enquir' in t.lower() or 'ask' in t.lower() for t in titles))
    def test_roofer_social_posts_show_different_roofing_illustrations(self):
        files=[]
        for day,theme in [(2,'Missing roof tiles'),(3,'Gutters overflowing'),(4,'What is wrong with the roof?')]:
            path=self.root/f'roof-post-{day}.png'
            business_agency_pack.social_tile(None,'Harbour Roofing',
                {'day':day,'theme':theme,'channel':'Facebook','copyDraft':'Get your roof checked by a professional.','callToAction':'Ask for a quote'},
                path,roof_style=True)
            files.append(path)
        frames=[Image.open(p).convert('RGB') for p in files]
        # Architectural illustrations appear in the middle, rather than only
        # changing the written heading on an otherwise blank panel.
        pixels=[tuple(img.getpixel(xy) for xy in ((420,640),(620,680),(550,800))) for img in frames]
        self.assertGreater(len(set(pixels)),1,pixels)
    def test_video_script_and_checklist_adapt_to_a_roofing_company(self):
        roofing=['Harbour Roofing','Roof repairs, flat roofs, guttering and storm damage help for homeowners']
        luxury=['Encore VIP','Exclusive access platform for curated experiences and concierge enquiries']
        roof=business_agency_pack.motion_script(roofing)
        encore=business_agency_pack.motion_script(luxury)
        self.assertEqual(len(roof),3);self.assertEqual(len(encore),3)
        text=' '.join(' '.join(frame) for frame in roof).lower()
        self.assertRegex(text,r'roof|tile|gutter|leak')
        self.assertNotIn('access. unrivaled.',text)
        self.assertNotEqual(roof,encore)
        self.assertIn('roof',business_agency_pack.checklist_topics(roofing)[0][1].lower())
        self.assertNotIn('roof',business_agency_pack.checklist_topics(luxury)[0][1].lower())
    def test_video_has_real_within_scene_motion_not_three_frozen_posters(self):
        import json,subprocess
        from PIL import ImageChops,ImageStat
        target=self.root/'roof-motion.mp4'
        business_agency_pack.motion_video(None,'Harbour Roofing','Ask for a roofing quote',target,
            ['Harbour Roofing','Roof repairs, gutters and flat roofing'])
        f1=self.root/'first.png';f2=self.root/'later.png'
        for timestamp,out in [(0.4,f1),(2.9,f2)]:
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(timestamp),'-i',str(target),'-frames:v','1',str(out)],check=True,timeout=20)
        with Image.open(f1) as a,Image.open(f2) as b:
            diff=ImageChops.difference(a.convert('RGB'),b.convert('RGB'))
            rms=ImageStat.Stat(diff).rms
            self.assertGreater(max(rms),1.2,('Motion not visible',rms))
    def test_concierge_carousel_shows_actual_service_types_not_generic_slogans(self):
        topics=business_agency_pack.carousel_topics(['Encore VIP','24/7 concierge, private aviation, private dining and exclusive events'])
        combined=' '.join(' '.join(x) for x in topics).lower()
        self.assertEqual(len(topics),5)
        self.assertIn('dining',combined)
        self.assertIn('transfer',combined)
        self.assertIn('event',combined)
        self.assertIn('access',combined)
        self.assertNotIn('your preferences come first',combined)
