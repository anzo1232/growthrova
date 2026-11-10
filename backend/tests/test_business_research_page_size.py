import unittest
from business_website_analysis import extract_website,WebsiteSafetyError
class BoundedResearchPageTests(unittest.TestCase):
 def test_normal_service_page_just_above_half_megabyte_remains_reviewable(self):
  # Real Pimlico service HTML measured 534330 bytes; its service text must
  # not disappear merely because the template is larger than the homepage.
  words='We repair leaking pipework and provide plumbing inspections for homes.'
  html=('<title>Example plumbing services</title><!--'+'x'*534000+'--><p>'+words+'</p>').encode()
  report=extract_website('https://example.org/',fetch=lambda *a:html,
   resolve=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
  self.assertIn(words,report['observations']['visible_paragraphs'])
 def test_oversized_site_still_fails_closed(self):
  html=b'<p>Services</p>'+b'x'*104857601
  with self.assertRaises(WebsiteSafetyError):
   extract_website('https://example.org/',fetch=lambda *a:html,
    resolve=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])

 def test_modern_business_page_with_large_template_is_reviewable_with_bounded_output(self):
  # Dishoom's public homepage returned 1,183,533 bytes during diagnosis.
  # Large template data is not itself evidence or a reason to drop visible text.
  words='Our restaurant serves lunch and dinner. Contact us to discuss a table.'
  body=('<title>Example restaurant</title><script>'+'x'*1183533+'</script><p>'+words+'</p>').encode()
  report=extract_website('https://example.org/',fetch=lambda *a:body,
   resolve=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
  self.assertEqual(report['observations']['visible_paragraphs'],[words])
  self.assertFalse(report['confirmed'])
  self.assertEqual(len(report['observations']['image_candidates']),0)
 def test_explicit_smaller_budget_remains_enforced(self):
  body=b'<title>Example</title>'+b'x'*900000
  with self.assertRaises(WebsiteSafetyError):
   extract_website('https://example.org/',fetch=lambda *a:body,max_bytes=786432,
    resolve=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
 def test_hundred_mebibyte_ceiling_cannot_be_overridden(self):
  for value in [104857601,1000000000]:
   with self.assertRaises(WebsiteSafetyError):
    extract_website('https://example.org/',fetch=lambda *a:b'<title>Example</title>',max_bytes=value,
     resolve=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])

 def test_five_mebibyte_business_page_is_accepted_by_default(self):
  words='Our workshop offers inspections by appointment. Contact us to discuss your requirements.'
  body=('<title>Example workshop</title><script>'+'x'*(5*1024*1024)+'</script><p>'+words+'</p>').encode()
  report=extract_website('https://example.org/',fetch=lambda *a:body,
   resolve=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
  self.assertEqual(report['observations']['visible_paragraphs'],[words])
  self.assertFalse(report['confirmed'])

 def test_twenty_five_mebibyte_html_is_accepted_by_default(self):
  words='Our business provides workshop appointments. Contact the team to discuss the service.'
  body=('<title>Example business</title><script>'+'x'*(25*1024*1024)+'</script><p>'+words+'</p>').encode()
  report=extract_website('https://example.org/',fetch=lambda *a:body,
   resolve=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
  self.assertEqual(report['observations']['visible_paragraphs'],[words])
  self.assertFalse(report['confirmed'])
