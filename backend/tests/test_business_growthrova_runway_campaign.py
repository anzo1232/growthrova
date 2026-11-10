"""Runway HTTP fixtures exercise saved campaign routes; no paid calls."""
import copy, json, unittest
from dataclasses import replace
from unittest.mock import patch
from contextlib import closing
import sqlite3
from tests.test_business_nano_banana_pro import NanoBananaProTests

TASK='12345678-1234-1234-1234-123456789abc'
class Reply:
 def __init__(self,data,status=200):self.data=data;self.status_code=status
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def iter_content(self,size):yield json.dumps(self.data).encode()

class RunwayHTTP:
 def __init__(self):self.submissions=[];self.polls=[];self.state='SUCCEEDED'
 def post(self,url,**kw):
  self.submissions.append((url,kw));return Reply({'id':TASK})
 def get(self,url,**kw):
  self.polls.append((url,kw));return Reply({'id':TASK,'status':self.state,'output':['https://cdn.runwayml.com/output.png'],'cost':{'credits':20}})

class RunwayCampaignTests(unittest.TestCase):
 def setUp(self):
  self.base=NanoBananaProTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
  self.flow=self.base.flow;self.http=RunwayHTTP()
  from business_growthrova_images import ImageConfig
  self.config=ImageConfig.from_environment({'GROWTHROVA_IMAGE_ENABLED':'true','GROWTHROVA_IMAGE_MODEL':'gemini_image3_pro','RUNWAYML_API_SECRET':'synthetic-runway-secret-not-real','GROWTHROVA_IMAGE_BUDGET_MICROUSD':'2000000','GROWTHROVA_IMAGE_CALL_CAP_MICROUSD':'300000','GROWTHROVA_IMAGE_INPUT_RATE_MICROUSD_PER_MILLION':'1','GROWTHROVA_IMAGE_OUTPUT_COST_MICROUSD':'200000'})
  self.client=self.flow.create(image_config=self.config,image_http=self.http).test_client()
  doc=copy.deepcopy(self.flow.doc)
  doc['brandKit']={'name':'Synthetic workshop','colours':['#143c30','#f3ecdf'],'font':'editorial','logoText':'Synthetic workshop'}
  # Use the established complete-advert fixture's valid brand.
  from tests.test_business_complete_advert import CompleteAdvertTests
  f=CompleteAdvertTests();f.setUp();self.addCleanup(f.doCleanups)
  doc['brandKit']=copy.deepcopy(f.base.client.get(f.base.root+'/'+f.base.ident,headers=f.base.headers).json['document']['brandKit'])
  saved=self.client.post(self.flow.root,headers=self.flow.headers,json={'id':self.flow.ident,'mutationId':'8'*32,'expectedRevision':1,'document':doc})
  self.assertEqual(saved.status_code,200,saved.json)
  self.data={**self.flow.data,'expectedRevision':2,'size':'square_2k','quality':'standard','renderingMode':'complete_advert'}
 def submit(self):return self.client.post(self.flow.url,headers=self.flow.headers,json=self.data)
 def test_route_submits_once_and_refresh_retains_pixels_without_another_charge(self):
  status=self.client.get(self.flow.url,headers=self.flow.headers).json
  self.assertTrue(status['available'])
  self.assertEqual(status['modelLabel'],'Nano Banana Pro via Runway')
  result=self.submit();self.assertEqual(result.status_code,200,result.json)
  self.assertEqual(result.json['providerTaskId'],TASK);self.assertEqual(result.json['state'],'pending')
  self.assertEqual(result.json['reservedMicrousd'],200000)
  url,kw=self.http.submissions[0]
  self.assertEqual(url,'https://api.dev.runwayml.com/v1/text_to_image')
  self.assertEqual(kw['headers']['Authorization'],'Bearer synthetic-runway-secret-not-real')
  self.assertNotIn('x-goog-api-key',kw['headers'])
  self.assertEqual(kw['json']['model'],'gemini_image3_pro');self.assertEqual(kw['json']['ratio'],'2048:2048')
  self.assertLessEqual(len(kw['json']['promptText'].encode('utf-16-le'))//2,5500)
  prompt=kw['json']['promptText']
  self.assertIn('Bicycle servicing',prompt)
  self.assertIn('CAMPAIGN IDEA',prompt)
  self.assertIn('BRAND SYSTEM',prompt)
  self.assertIn('COPY HIERARCHY',prompt)
  self.assertIn('exact logo overlay',prompt)
  self.assertIn('Do not typeset the business name',prompt)
  self.assertNotIn('"creativeProfile"',prompt)
  self.assertNotIn('pending_pixel_review',prompt)
  self.assertEqual(self.submit().json['providerTaskId'],TASK)
  replay=self.client.post(self.flow.url,headers=self.flow.headers,json={**self.data,'operationId':'9'*32})
  self.assertEqual(replay.json['providerTaskId'],TASK)
  self.client=self.flow.create(image_config=self.config,image_http=self.http).test_client()
  refresh=self.flow.url+'/'+self.data['operationId']+'/refresh'
  with patch('business_growthrova_runway_images.download_image',return_value=self.base.png):
   done=self.client.post(refresh,headers=self.flow.headers)
  self.assertEqual(done.status_code,200,done.json);self.assertEqual(done.json['state'],'held')
  self.assertTrue(done.json['creativeReviewRequired'])
  self.assertEqual(done.json['actualProviderCredits'],20)
  self.assertEqual(self.client.get(self.flow.url+'/'+self.data['operationId']+'/original',headers=self.flow.headers).data,self.base.png)
  self.assertEqual(self.client.post(refresh,headers=self.flow.headers).json,done.json)
  self.assertEqual(len(self.http.submissions),1)
  with closing(sqlite3.connect(self.flow.path)) as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_image_requests').fetchone()[0],1)
 def test_prompt_uses_observed_website_identity_and_visual_first_structure(self):
  from business_growthrova_runway_images import request_body
  source={
   'business':{'business':'ExitFlow'},
   'visualDirection':'A single paper process physically unfolds into one clear signed handover, photographed overhead with directional light and tactile shadows.',
   'brandKit':{'name':'ExitFlow','primary_color':'#07130F','secondary_color':'#B7F5D5','font_style':'modern'},
   'advertCopy':{'businessName':'ExitFlow','headline':'Leave with everything in order','supportingLine':'Plan the handover before the final day.','callToAction':'Build your exit plan.'},
   'artDirectionBrief':{
    'proposition':{'quote':'Create a structured business exit plan.'},
    'creativeProfile':{
     'identity':{'typographicCharacter':'precise editorial'},
     'websiteVisualIdentity':{'roles':{'background':'#07130F','text':'#F4FFF8','accent':'#B7F5D5'},
      'colours':[{'hex':'#F4FFF8','count':20}],'fontFamilies':[{'family':'Inter','count':26}]},
     'antiGeneric':['No generic office props.']}},
   'channelCreativeBrief':{'channel':'instagram','format':'image_ad','platformRule':'One immediate focal idea for a mobile feed.'},
   'selectedConcept':{'buyerMotivation':'Reduce uncertainty before a business exit.',
    'heroVisual':'One continuous paper workflow physically resolves into a signed handover.',
    'conceptLogic':'The transformation makes an orderly exit visible without a dashboard.'}}
  prompt=request_body(source,'portrait_2k',True)['promptText']
  for expected in ('#07130F','#B7F5D5','#F4FFF8','Inter','One continuous paper workflow',
                   'Leave with everything in order','exact logo overlay'):
   self.assertIn(expected,prompt)
  self.assertNotIn('pending_pixel_review',prompt)
  self.assertNotIn('businessName',prompt)
  self.assertLess(len(prompt),4000)

 def test_missing_runway_key_cannot_borrow_google_credential(self):
  c=replace(self.config,key='')
  client=self.flow.create(image_config=c,image_http=self.http).test_client()
  self.assertEqual(client.post(self.flow.url,headers=self.flow.headers,json=self.data).status_code,503)
  self.assertEqual(self.http.submissions,[])
 def test_provider_failure_and_unauthorised_refresh_never_resubmit(self):
  result=self.submit();self.assertEqual(result.status_code,200,result.json)
  refresh=self.flow.url+'/'+self.data['operationId']+'/refresh'
  from tests.test_business_growthrova_preview import OTHER
  owner=self.flow.auth.owner;self.flow.auth.owner=OTHER
  self.assertEqual(self.client.post(refresh,headers=self.flow.headers).status_code,403)
  self.flow.auth.owner=owner;self.http.state='FAILED'
  done=self.client.post(refresh,headers=self.flow.headers)
  self.assertEqual(done.json['state'],'uncertain')
  self.assertEqual(done.json['providerDiagnostic']['providerStatus'],'FAILED')
  self.assertEqual(len(self.http.submissions),1)
  self.assertEqual(self.client.get(self.flow.url+'/'+self.data['operationId']+'/original',headers=self.flow.headers).status_code,409)

 def test_legacy_direct_transport_never_sends_runway_key_to_google(self):
  from business_growthrova_images import call_image_provider
  with self.assertRaises(ValueError):
   call_image_provider(self.config,{},self.http)
  self.assertEqual(self.http.submissions,[])
