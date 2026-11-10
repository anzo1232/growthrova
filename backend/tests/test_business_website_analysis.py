import unittest
from business_website_analysis import extract_website,validate_target,public_address,WebsiteSafetyError
class WebsiteAnalysisTests(unittest.TestCase):
 def test_source_provenance_and_owner_review(self):
  dns=lambda *a,**k:[(None,None,None,None,('93.184.215.14',443))]
  result=extract_website('https://company.example/services',resolve=dns,fetch=lambda url,ip:b'<title>Example Services</title><meta name="description" content="Equipment maintenance"><h1>Industrial repairs</h1><script><h1>Fake offer</h1></script>')
  self.assertFalse(result['confirmed']);self.assertEqual(result['observations']['title'],'Example Services')
  self.assertNotIn('Fake offer',result['observations']['headings'])
 def test_blocks_private_dns_and_insecure_urls(self):
  for address in ['http://example.com','https://localhost','https://127.0.0.1','https://user:pass@example.com','https://example.com:8443']:
   with self.assertRaises(WebsiteSafetyError):validate_target(address)
  with self.assertRaises(WebsiteSafetyError):public_address('example.com',resolve=lambda *a,**k:[(None,None,None,None,('192.168.1.7',443))])
 def test_rejects_large_response(self):
  dns=lambda *a,**k:[(None,None,None,None,('93.184.215.14',443))]
  with self.assertRaises(WebsiteSafetyError):extract_website('https://example.com',resolve=dns,fetch=lambda *a:b'x'*512001,max_bytes=512000)
if __name__=='__main__':unittest.main()

class WebsiteEvidenceEnrichmentTests(unittest.TestCase):
 def extract(self,body):
  dns=lambda *a,**k:[(None,None,None,None,('93.184.215.14',443))]
  return extract_website('https://trades.example.org/',resolve=dns,fetch=lambda *a:body.encode())
 def test_real_service_copy_and_usable_visual_candidates(self):
  page=self.extract('''<html><title>Harbour Roofing Portsmouth</title>
  <meta property="og:image" content="/media/our-work.jpg">
  <p>Roof repairs, guttering, flat roofing and emergency leak inspections for local homeowners.</p>
  <a href="/services/roof-repairs">Roof repairs</a>
  <a href="/contact">Get a roof quote</a>
  <img src="/media/roof-tiling.webp" alt="Roof tiling on a Portsmouth home" width="1200" height="800">
  <img src="https://random-external.example/tracking.png" alt="Tracking">
  <img src="data:image/png;base64,AQAB" alt="unsafe">
  <script><p>We guarantee 100 percent free repairs</p></script></html>''')
  o=page['observations']
  self.assertIn('guttering',o['visible_paragraphs'][0]);self.assertEqual(len(o['visible_paragraphs']),1)
  self.assertEqual(o['service_links'][0]['label'],'Roof repairs')
  self.assertEqual(o['image_candidates'][0]['url'],'https://trades.example.org/media/our-work.jpg')
  self.assertEqual(o['image_candidates'][1]['alt'],'Roof tiling on a Portsmouth home')
  self.assertFalse(any('tracking.png' in x['url'] or x['url'].startswith('data:') for x in o['image_candidates']))
  self.assertFalse(any('guarantee' in x for x in o['visible_paragraphs']))
 def test_extraction_remains_bounded_for_spammy_websites(self):
  page=self.extract('<title>Business</title>'+''.join('<p>Really useful description '+str(i)+'</p>' for i in range(200))+''.join(f'<img src="/photos/{i}.jpg" alt="Photo {i}">' for i in range(200)))
  o=page['observations'];self.assertLessEqual(len(o['visible_paragraphs']),12);self.assertLessEqual(len(o['image_candidates']),8)
 def test_consent_boilerplate_does_not_crowd_out_service_evidence(self):
  notices=[
   'We use cookies on our website to deliver you the best online experience.',
   'This website uses cookies to ensure you get the best experience on our website.',
   'Necessary cookies enable core functionality such as security and accessibility.',
   'We’d like to set Google Analytics cookies to help us to improve our website.',
   'We and our advertising suppliers use these technologies to personalise the advertising you see.']
  details=[f'Our workshop service description number {i} is available for owner review.' for i in range(10)]
  detail='Boiler servicing includes an inspection by appointment; discuss the scope before booking.'
  page=self.extract('<title>Example Plumbing</title>'+''.join('<p>'+value+'</p>' for value in notices+details+[detail]))
  paragraphs=page['observations']['visible_paragraphs']
  self.assertEqual(paragraphs,details+[detail])
  self.assertFalse(page['confirmed'])
 def test_cookie_products_and_business_privacy_services_remain_evidence(self):
  products=['Our bakery makes chocolate cookies for collection by appointment.',
    'We use cookies in our ice cream sandwiches, made in our own kitchen.',
    'We use cookies to provide a crunchy base for our handmade desserts.',
    'Our services include privacy training and analytics consultancy for small businesses.']
  self.assertEqual(self.extract(''.join('<p>'+value+'</p>' for value in products))['observations']['visible_paragraphs'],products)
 def test_image_candidates_are_unverified_never_owner_approved(self):
  p=self.extract('<title>Business</title><meta property="og:image" content="/photo.jpg">')
  self.assertFalse(p['confirmed']);self.assertTrue(p['observations']['image_candidates'])
  self.assertTrue(all(x['rights_confirmed'] is False for x in p['observations']['image_candidates']))
 def test_long_paragraph_preserves_later_service_and_seasonal_evidence_with_bounds(self):
  detail='Membership options include a guided tour by appointment. Start the year with a visit.'
  paragraph='Discover our club and the spaces where you can spend your day. '*9+detail
  page=self.extract('<title>Example Country Club</title><p>'+paragraph+'</p><p>'+'Bounded source text '*200+'</p>')
  quotes=page['observations']['visible_paragraphs']
  self.assertEqual(quotes[0],paragraph)
  self.assertIn(quotes[0],page['freshness']['seasonal_excerpts'])
  self.assertEqual(page['freshness']['status'],'unknown')
  self.assertLessEqual(len(quotes[1]),1200)
  self.assertTrue(('Bounded source text '*200).startswith(quotes[1]+' '))
  self.assertFalse(page['confirmed'])

class MultipageBusinessSiteTests(unittest.TestCase):
 def test_only_three_expected_same_domain_pages_are_read(self):
  from business_website_analysis import expand_business_audit
  base={'source_url':'https://berenjak.com/','status':'extracted_unconfirmed',
        'observations':{'title':'Berenjak','headings':['A Persian Kababi'],
        'visible_paragraphs':['Our own restaurant and food story in the heart of Soho.'],
        'service_links':[{'url':'https://berenjak.com/story/','label':'Story'},
           {'url':'https://berenjak.com/food-and-drink/','label':'Food'},
           {'url':'https://berenjak.com/locations/soho/','label':'Soho'},
           {'url':'https://attacker.example/locations/london/','label':'Outside'},
           {'url':'http://berenjak.com/locations/other/','label':'Insecure'}]}}
  calls=[]
  def reader(url):
   calls.append(url)
   return {'source_url':url,'status':'extracted_unconfirmed','observations':{
     'headings':['Restaurant detail '+url.rsplit('/',2)[-2]],
     'visible_paragraphs':['Useful verified transport text for '+url]}}
  result=expand_business_audit(base,reader=reader)
  self.assertEqual(len(calls),3)
  self.assertTrue(all(url.startswith('https://berenjak.com/') for url in calls))
  self.assertEqual(len(result['audited_page_urls']),4)
  self.assertEqual(result['enrichment_warnings'],[])
 def test_secondary_page_error_keeps_first_page_without_inventing_facts(self):
  from business_website_analysis import expand_business_audit
  b={'source_url':'https://berenjak.com/','status':'extracted_unconfirmed',
     'observations':{'title':'Berenjak','headings':['Authentic Berenjak'],
       'visible_paragraphs':['Original source from an actual website page.'],
       'service_links':[{'url':'https://berenjak.com/story/','label':'Story'}]}}
  def blocked(url):raise WebsiteSafetyError('secondary read failed')
  result=expand_business_audit(b,reader=blocked)
  self.assertEqual(result['observations']['headings'],['Authentic Berenjak'])
  self.assertEqual(len(result['audited_page_urls']),1)
  self.assertTrue(result['enrichment_warnings'])

class WebsiteResearchExportTests(unittest.TestCase):
 def test_expansion_preserves_exact_per_page_excerpts_for_strategy_import(self):
  from business_website_analysis import expand_business_audit
  root={'source_url':'https://studio.example/','status':'extracted_unconfirmed',
        'observations':{'title':'Studio','headings':[],'visible_paragraphs':['Home copy'],
                        'service_links':[{'url':'https://studio.example/story/','label':'Story'}]}}
  detail={'source_url':'https://studio.example/story/','status':'extracted_unconfirmed',
          'observations':{'title':'Our story','headings':[],'visible_paragraphs':['Evening classes']}}
  report=expand_business_audit(root,reader=lambda url:detail)
  self.assertEqual(report['page_reports'],[root,detail])
  self.assertEqual(report['page_reports'][0]['observations']['visible_paragraphs'],['Home copy'])
  self.assertEqual(report['page_reports'][1]['source_url'],'https://studio.example/story/')
  self.assertNotIn('page_reports',root)

class PrioritisedResearchTests(unittest.TestCase):
 extract=WebsiteEvidenceEnrichmentTests.extract
 def test_trade_services_get_distinct_reads_before_contact_and_about(self):
  from business_website_analysis import expand_business_audit
  links=[('contact','Book now'),('about','About us')]
  links += [('services/plumbing/emergency','Plumbing emergency'),
            ('services/plumbing/leaks','Leak repairs'),
            ('services/heating/emergency','Heating emergency'),
            ('services/heating/boilers','Boiler servicing'),
            ('services/electrical','Electrical services')]
  root=self.extract('<title>Example Trades</title>'+''.join(
    f'<a href="/{path}/">{label}</a>' for path,label in links))
  calls=[]
  def reader(url):
   calls.append(url)
   if '/heating/' in url:raise WebsiteSafetyError('Page exceeds maximum size')
   return {**self.extract('<title>Service detail</title>'),'source_url':url}
  report=expand_business_audit(root,reader=reader)
  expected=['https://trades.example.org/services/'+path+'/' for path in
            ['plumbing/emergency','heating/emergency','electrical']]
  self.assertEqual(calls,expected)
  self.assertEqual(report['coverage']['attempted_urls'],expected)
  self.assertEqual(report['audited_page_urls'],[root['source_url'],expected[0],expected[2]])
  self.assertIn('heating: Page exceeds maximum size',report['enrichment_warnings'])
  self.assertIn('https://trades.example.org/contact/',report['coverage']['omitted_urls'])
  self.assertFalse(report['confirmed'])
 def test_late_business_links_beat_navigation_noise_and_fragments(self):
  body='<title>Club</title><a href="#main">Skip to main content</a>'
  body+=''.join(f'<a href="/legal/{i}">Privacy policy {i}</a>' for i in range(45))
  body+=''.join(f'<a href="/{p}/">{label}</a>' for p,label in [('membership','Membership'),('dining','Dining'),('spa','Spa'),('fitness','Fitness'),('book','Book a visit')])
  links=self.extract(body)['observations']['service_links']
  self.assertEqual([x['label'] for x in links[:5]],['Membership','Dining','Spa','Fitness','Book a visit'])
  self.assertFalse(any('Skip' in x['label'] or 'Privacy' in x['label'] for x in links))
 def test_lazy_responsive_image_metadata_and_freshness_are_unverified(self):
  report=self.extract('<title>Club</title><h1>Start the year with us</h1><img src="data:image/gif;base64,x" data-src="/club.jpg" alt="Club pool"><source srcset="/fitness.webp 800w, /fitness-large.webp 1600w"><p>Christmas membership offer available for a limited time.</p>')
  self.assertEqual([x['url'].rsplit('/',1)[-1] for x in report['observations']['image_candidates']],['club.jpg','fitness-large.webp'])
  self.assertEqual(report['freshness']['status'],'unknown')
  self.assertTrue(report['freshness']['seasonal_excerpts'])
  self.assertFalse(report['confirmed'])
 def test_diverse_detail_pages_are_bounded_with_explicit_omissions(self):
  from business_website_analysis import expand_business_audit
  root=self.extract('<title>Club</title>'+''.join(f'<a href="/{p}/">{p.title()}</a>' for p in ['membership','dining','spa','fitness']))
  calls=[]
  def reader(url):
   calls.append(url)
   return {**self.extract('<title>Detail</title><p>Current service descriptions require owner confirmation.</p>'),'source_url':url}
  result=expand_business_audit(root,reader=reader)
  self.assertEqual(len(calls),3)
  self.assertEqual(len(result['page_reports']),4)
  self.assertEqual(result['coverage']['omitted_urls'],['https://trades.example.org/fitness/'])
  self.assertEqual(result['coverage']['status'],'partial')
  self.assertIn('https://trades.example.org/membership/',calls)
  self.assertFalse(result['confirmed'])
 def test_repeated_membership_links_do_not_hide_other_services(self):
  body='<title>Club</title>'+''.join(f'<a href="/membership/{i}">Membership option {i}</a>' for i in range(20))
  body+='<a href="/dining/">Dining</a><a href="/spa/">Spa</a><a href="/fitness/">Fitness</a>'
  links=self.extract(body)['observations']['service_links']
  self.assertEqual([item['label'] for item in links[:4]],['Membership option 0','Dining','Spa','Fitness'])
 def test_detail_reads_retain_ssrf_denial_and_explicit_failure(self):
  from business_website_analysis import expand_business_audit
  root=self.extract('<title>Club</title><a href="https://outside.example/membership/">External</a><a href="/membership/">Membership</a>')
  def denied(url):
   return extract_website(url,resolve=lambda *a,**k:[(None,None,None,None,('127.0.0.1',443))],fetch=lambda *a:self.fail('Restricted address fetched'))
  report=expand_business_audit(root,reader=denied)
  self.assertEqual(report['audited_page_urls'],[root['source_url']])
  self.assertIn('restricted address',report['enrichment_warnings'][0])
  self.assertEqual(report['coverage']['attempted_urls'],['https://trades.example.org/membership/'])
