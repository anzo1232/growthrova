"""Sparse-shell fallback is evidence, not a successful metadata-only scan."""
import unittest
from unittest.mock import Mock
from business_website_analysis import extract_website, WebsiteSafetyError

DNS=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))]
SHELL=b'<title>Example</title><meta name="description" content="An amazing business"><div id="root"></div><script type="module" src="/assets/main.js"></script>'
BODY='<h1>Repair appointments</h1><p>Book a workshop inspection for your bicycle with our repair team.</p><a href="/pricing">Repair pricing</a>'

class RenderingFallbackTests(unittest.TestCase):
 def read(self,body=SHELL,**kwargs):
  return extract_website('https://example.org/',fetch=lambda *a:body,resolve=DNS,**kwargs)
 def test_shell_uses_rendered_business_evidence_and_preserves_source(self):
  renderer=Mock(return_value={'html':BODY,'source_url':'https://example.org/','blocked_dependencies':[]})
  result=self.read(renderer=renderer)
  self.assertEqual(renderer.call_count,1)
  self.assertEqual(result['observations']['headings'],['Repair appointments'])
  self.assertEqual(result['observations']['service_links'][0]['url'],'https://example.org/pricing')
  self.assertEqual(result['evidence']['status'],'sufficient_unconfirmed')
  self.assertEqual(result['rendering']['status'],'rendered')
  self.assertFalse(result['confirmed'])
 def test_ssr_skips_browser(self):
  renderer=Mock(side_effect=AssertionError('SSR must not launch Chromium'))
  result=self.read(BODY.encode(),renderer=renderer)
  self.assertEqual(result['rendering']['status'],'not_needed')
  renderer.assert_not_called()

 def test_rendered_identity_is_bounded_role_aware_and_keeps_logo_provenance(self):
  visual={'status':'website_observed_unconfirmed','background':'#0c0c0f','text':'#ffffff',
   'colours':[{'hex':'#FFFFFF','count':20},{'hex':'#02FFB2','count':4},{'hex':'#0C0C0F','count':1}],
   'fontFamilies':[{'family':'Inter','count':12}],
   'logoCandidates':[{'kind':'inline_svg','svg':'<svg><path d="M0 0"/></svg>','description':'Visible inline website logo'},
    {'kind':'image_url','url':'https://cdn.example.org/logo.png','description':'Organisation logo'}]}
  result=self.read(renderer=Mock(return_value={'html':BODY,'source_url':'https://example.org/',
   'blocked_dependencies':[],'visual_identity':visual}))
  identity=result['observations']['visual_identity']
  self.assertEqual(identity['roles'],{'background':'#0C0C0F','text':'#FFFFFF','accent':'#02FFB2'})
  self.assertEqual(identity['fontFamilies'],[{'family':'Inter','count':12}])
  self.assertEqual(identity['suggestedBrandKit'],{'primary_color':'#0C0C0F','secondary_color':'#02FFB2','font_style':'modern'})
  self.assertEqual(identity['logoCandidates'][0]['kind'],'inline_svg')
  self.assertTrue(identity['logoCandidates'][0]['svg'].startswith('<svg'))
  self.assertNotIn('script',identity['logoCandidates'][0]['svg'])
  self.assertEqual(identity['logoCandidates'][1]['url'],'https://cdn.example.org/logo.png')
 def test_metadata_does_not_count_as_business_evidence(self):
  result=self.read(renderer=Mock(return_value={'html':'<title>Example</title>','source_url':'https://example.org/','blocked_dependencies':[]}))
  self.assertEqual(result['evidence']['status'],'insufficient')
  self.assertIn('insufficient business evidence',result['warning'].lower())
 def test_renderer_failure_is_explicit_without_losing_metadata(self):
  result=self.read(renderer=Mock(side_effect=WebsiteSafetyError('JavaScript renderer unavailable')))
  self.assertEqual(result['observations']['title'],'Example')
  self.assertEqual(result['rendering']['status'],'unavailable')
  self.assertEqual(result['evidence']['status'],'insufficient')
 def test_foreign_renderer_source_is_rejected(self):
  result=self.read(renderer=Mock(return_value={'html':BODY,'source_url':'https://foreign.org/','blocked_dependencies':[]}))
  self.assertEqual(result['evidence']['status'],'insufficient')
  self.assertEqual(result['rendering']['status'],'unavailable')
 def test_unsupported_dependency_is_reported_even_when_rendered(self):
  result=self.read(renderer=Mock(return_value={'html':BODY,'source_url':'https://example.org/','blocked_dependencies':['external script: cdn.example.net']}))
  self.assertEqual(result['rendering']['blocked_dependencies'],['external script: cdn.example.net'])

class ConsentEvidenceTests(unittest.TestCase):
 # Exact public-reader observation retained in the controller's Clippr receipt.
 notice=("Allow Clippr signup analytics, Google Analytics and Meta Pixel? They help us understand product use "
         "and whether our ads lead to sign-ups or purchases. It's optional. You can change your choice in Cookie settings. Privacy policy")
 def read(self,html,rendered=False):
  return extract_website('https://example.org/',resolve=DNS,
   fetch=lambda *a:SHELL if rendered else html.encode(),
   **({'renderer':Mock(return_value={'html':html,'source_url':'https://example.org/'})} if rendered else {}))
 def test_consent_question_does_not_consume_static_or_rendered_evidence_budget(self):
  details=[f'Workshop service {i} includes bicycle inspections by appointment with our team.' for i in range(12)]
  html='<h1>Workshop repairs</h1><p>'+self.notice+'</p>'+''.join('<p>'+value+'</p>' for value in details)
  for rendered in (False,True):
   with self.subTest(rendered=rendered):
    result=self.read(html,rendered)
    self.assertEqual(result['observations']['visible_paragraphs'],details)
    self.assertEqual(result['evidence']['status'],'sufficient_unconfirmed')
    self.assertFalse(result['confirmed'])
 def test_consent_alone_cannot_make_an_empty_business_scan_sufficient(self):
  for rendered in (False,True):
   with self.subTest(rendered=rendered):
    result=self.read('<h1>Analytics cookies</h1><p>'+self.notice+'</p>',rendered)
    self.assertEqual(result['evidence']['status'],'insufficient')
 def test_actual_analytics_services_are_retained(self):
  copy='Allow your team to understand product use with our analytics consultancy and consent management training.'
  result=self.read('<h1>Analytics consultancy</h1><p>'+copy+'</p>',True)
  self.assertEqual(result['observations']['visible_paragraphs'],[copy])
 def test_consent_headings_do_not_displace_business_headings(self):
  headings=['Repair appointments','Workshop pricing','Bicycle maintenance']
  html=('<h2>Analytics cookies</h2>'*24+''.join('<h2>'+value+'</h2>' for value in headings)
        +'<p>Book a workshop inspection for your bicycle with our repair team.</p>')
  for rendered in (False,True):
   with self.subTest(rendered=rendered):
    result=self.read(html,rendered)
    self.assertEqual(result['observations']['headings'],headings)
    self.assertEqual(result['evidence']['status'],'sufficient_unconfirmed')
    self.assertFalse(result['confirmed'])
 def test_service_headings_about_analytics_and_cookies_are_retained(self):
  headings=['Analytics consultancy','Cookie consent management training','Cookies for special occasions']
  html=''.join('<h2>'+value+'</h2>' for value in headings)+'<p>Explore our services and arrange a consultation with our team.</p>'
  for rendered in (False,True):
   with self.subTest(rendered=rendered):
    self.assertEqual(self.read(html,rendered)['observations']['headings'],headings)

class SparseResearchRouteTests(unittest.TestCase):
 def test_authenticated_metadata_only_research_is_actionable_failure(self):
  import tempfile
  from pathlib import Path
  from unittest.mock import patch
  from tests.test_business_growthrova_preview import Transport, PROJECT, ORG
  from business_growthrova_preview import create_growthrova_preview
  sparse=extract_website('https://example.org/',fetch=lambda *a:SHELL,resolve=DNS)
  with tempfile.TemporaryDirectory() as directory:
   app=create_growthrova_preview(database_path=str(Path(directory)/'preview.db'),project_url=PROJECT,
     auth_url=PROJECT,anon_key='sb_publishable_synthetic',http=Transport())
   with patch('business_growthrova_preview.extract_website',return_value=sparse):
    response=app.test_client().post('/api/growthrova/organisations/'+ORG+'/research',json={},headers={'Authorization':'Bearer synthetic-valid'})
  self.assertEqual(response.status_code,400)
  self.assertEqual(response.json['code'],'research_unavailable')
  self.assertIn('insufficient business evidence',response.json['error'].lower())
  self.assertEqual(response.json['evidence']['status'],'insufficient')
  self.assertEqual(response.json['rendering']['status'],'unavailable')

class ExpandedEvidenceTests(unittest.TestCase):
 def test_sparse_home_can_recover_from_a_sufficient_linked_service_page(self):
  from business_website_analysis import expand_business_audit
  home=extract_website('https://example.org/',fetch=lambda *a:SHELL+b'<a href="/services">Services</a>',resolve=DNS)
  detail=extract_website('https://example.org/services',fetch=lambda *a:BODY.encode(),resolve=DNS)
  report=expand_business_audit(home,reader=lambda url:detail)
  self.assertEqual(report['evidence']['status'],'sufficient_unconfirmed')
  self.assertEqual(report['page_reports'][0]['evidence']['status'],'insufficient')
 def test_unsupported_external_dependencies_are_visible_in_coverage_warnings(self):
  from business_website_analysis import expand_business_audit
  home=extract_website('https://example.org/',fetch=lambda *a:SHELL,resolve=DNS,renderer=Mock(return_value={
   'html':BODY.replace('<a href="/pricing">Repair pricing</a>',''),'source_url':'https://example.org/',
   'blocked_dependencies':['Unsupported external-render dependency: cdn.example.net']}))
  report=expand_business_audit(home)
  self.assertTrue(any('cdn.example.net' in warning for warning in report['enrichment_warnings']))

class RenderedPricingCoverageTests(unittest.TestCase):
 def test_linked_pricing_survives_navigation_budget_after_hydration(self):
  from business_website_analysis import expand_business_audit
  html=BODY.replace('<a href="/pricing">Repair pricing</a>',
    '<a href="/features">Features</a><a href="/pricing">Pricing</a><a href="/about">About</a><a href="/contact">Contact</a>')
  home=extract_website('https://example.org/',fetch=lambda *a:SHELL,resolve=DNS,
    renderer=Mock(return_value={'source_url':'https://example.org/','html':html}))
  visited=[]
  def reader(url):
   visited.append(url)
   return extract_website(url,fetch=lambda *a:BODY.encode(),resolve=DNS)
  report=expand_business_audit(home,reader=reader)
  self.assertIn('https://example.org/pricing',visited)
  self.assertIn('https://example.org/pricing',report['audited_page_urls'])
  self.assertLessEqual(len(visited),3)

class ResearchScopeBeforeRenderingTests(unittest.TestCase):
 def test_foreign_or_missing_identity_never_reads_or_renders_website(self):
  import tempfile
  from pathlib import Path
  from unittest.mock import patch
  from tests.test_business_growthrova_preview import Transport, PROJECT, ORG
  from business_growthrova_preview import create_growthrova_preview
  transport=Transport();transport.allowed=False
  with tempfile.TemporaryDirectory() as directory:
   app=create_growthrova_preview(database_path=str(Path(directory)/'preview.db'),project_url=PROJECT,
     auth_url=PROJECT,anon_key='sb_publishable_synthetic',http=transport)
   with patch('business_growthrova_preview.extract_website') as reader:
    url='/api/growthrova/organisations/'+ORG+'/research'
    self.assertEqual(app.test_client().post(url,json={}).status_code,401)
    self.assertEqual(app.test_client().post(url,json={},headers={'Authorization':'Bearer synthetic-valid'}).status_code,403)
    reader.assert_not_called()
