import unittest
from business_website_analysis import safe_image_metadata_reference,safe_page_reference,extract_website
class ImageMetadataTests(unittest.TestCase):
 def test_cdn_metadata_does_not_expand_page_crawl_authority(self):
  url='https://cdn.example.org/club/pool.jpg'
  self.assertEqual(safe_image_metadata_reference(url,'https://club.example.org/'),url)
  self.assertIsNone(safe_page_reference(url,'https://club.example.org/'))
 def test_unsafe_metadata_rejected(self):
  for url in ('http://cdn.example.org/a.jpg','https://127.0.0.1/a.jpg','https://localhost/a.jpg','https://u:p@cdn.example.org/a.jpg','javascript:alert(1)'):
   self.assertIsNone(safe_image_metadata_reference(url,'https://club.example.org/'),url)
 def test_tracking_pixels_do_not_crowd_out_cdn_photographs(self):
  body=b'<title>Club</title><img src="https://cdn.example.org/track.gif" width="1" height="1"><img src="https://cdn.example.org/event.png" alt="Tracking"><img src="https://cdn.example.org/pool.jpg" alt="Club pool" width="1200" height="800">'
  report=extract_website('https://club.example.org/',fetch=lambda *a:body,
    resolve=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
  self.assertEqual([x['url'] for x in report['observations']['image_candidates']],['https://cdn.example.org/pool.jpg'])
  self.assertFalse(report['observations']['image_candidates'][0]['rights_confirmed'])
if __name__=='__main__':unittest.main()
