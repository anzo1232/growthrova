"""Landing-page export must be useful offline, accessible and safe from source HTML."""
import tempfile,unittest,re
from pathlib import Path
from PIL import Image
import business_landing_page as landing

class LandingPageTests(unittest.TestCase):
 def setUp(self):
  root=tempfile.TemporaryDirectory();self.addCleanup(root.cleanup);self.root=Path(root.name)
  self.image=self.root/'cover.png';Image.new('RGB',(900,1125),(43,72,102)).save(self.image)
 def doc(self):
  return {'version':1,'name':'30-day marketing','business':'Harbour Roofing','sourceUrl':'https://harbour.example.org/',
   'observedFacts':['Harbour Roofing','Roof repairs, guttering and flat roofs for Portsmouth homes.','Roof repairs','Ask about a roofing quote'],
   'posts':[{'day':i} for i in range(1,31)],
   'creatives':[{'id':'creative-1','callToAction':'Get a roofing quote'}]}
 def test_creates_real_standalone_html_with_safe_official_action(self):
  generated=landing.make_preview(self.doc(),self.image,self.root/'website-landing-page.html')
  text=generated.read_text()
  self.assertIn('<!doctype html>',text.lower())
  self.assertIn('Harbour Roofing',text)
  self.assertIn('Roof repairs',text)
  self.assertIn('href="https://harbour.example.org/"',text)
  self.assertIn('meta name="robots" content="noindex, nofollow"',text)
  self.assertIn('DRAFT PREVIEW',text)
  self.assertNotIn('<form',text)
  self.assertNotIn('<script',text)
  self.assertTrue((self.root/'website-landing-page.html').stat().st_size<1500000)
  self.assertEqual(text.count('image/webp;base64,'),1)
 def test_website_evidence_is_escaped_and_no_injected_script(self):
  d=self.doc();d['business']='<img src=x onerror=alert(1)>'
  d['observedFacts'][1]='Roof repairs. <script>alert(1)</script>'
  d['creatives'][0]['callToAction']='Get quote" onclick="steal()'
  page=landing.make_preview(d,None,self.root/'safepage.html').read_text()
  self.assertNotIn('<script',page)
  self.assertNotIn('onerror=',page.replace('&lt;img',''))
  self.assertNotIn('onclick=',page.replace('&quot; onclick=&quot;',''))
  self.assertIn('&lt;script&gt;',page)
 def test_no_unverified_source_can_be_sent_to_external_lead_service(self):
  d=self.doc();d['sourceUrl']='javascript:alert(1)'
  with self.assertRaises(ValueError):landing.make_preview(d,self.image,self.root/'bad.html')
 def test_no_photo_yields_a_self_contained_editorial_layout(self):
  page=landing.make_preview(self.doc(),None,self.root/'no-photo.html').read_text()
  self.assertIn('background:',page)
  self.assertNotIn('image/webp;base64,',page)
  self.assertIn('We haven',page)
