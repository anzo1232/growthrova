"""Ad agent coordinates existing real routes/ledgers; external HTTP is synthetic."""
import copy,unittest
from unittest.mock import patch
from dataclasses import replace
from business_growthrova_preview import create_growthrova_preview
from tests import test_business_growthrova_writer as w
from tests import test_business_nano_banana_pro as pro
from tests import test_business_creative_plans as plans
from tests import test_business_growthrova_runway_campaign as rw
from tests import test_business_complete_advert as complete

class BackgroundProvider(w.Provider):
 def post(self,url,**options):
  result=super().post(url,**options)
  if options['json'].get('background'):
   return w.ProviderResponse({'id':'resp_syntheticagent123456','status':'queued','output':[]})
  return result
 def get(self,url,**options):
  return w.ProviderResponse({'id':'resp_syntheticagent123456','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':__import__('json').dumps(self.sample)}]}]})

class AdAgentTests(unittest.TestCase):
 def setUp(self):
  self.flow=w.GrowthrovaWriterTests();self.flow.setUp();self.addCleanup(self.flow.doCleanups)
  self.pngflow=pro.NanoBananaProTests();self.pngflow.setUp();self.addCleanup(self.pngflow.doCleanups)
  self.image_config=replace(self.pngflow.config,model='gemini_image3_pro',key='synthetic-runway-secret-not-real',output_cost_microusd=200000)
  self.images=rw.RunwayHTTP()
  self.flow.provider=BackgroundProvider()
  brand=complete.CompleteAdvertTests();brand.setUp();self.addCleanup(brand.doCleanups)
  self.doc=copy.deepcopy(self.flow.doc)
  self.doc['brandKit']=brand.base.client.get(brand.base.root+'/'+brand.base.ident,headers=brand.base.headers).json['document']['brandKit']
  self.client=self.create()
  saved=self.client.post(self.flow.root,headers=self.flow.headers,json={'id':self.flow.ident,'mutationId':'8'*32,'expectedRevision':1,'document':self.doc})
  self.assertEqual(saved.status_code,200,saved.json)
  self.flow.provider.sample=plans.concepts()
  self.url=self.flow.root+'/'+self.flow.ident+'/ad-agent'
  self.request={'runId':'a'*32,'expectedRevision':2,'day':1,'count':1,'size':'square_2k','tone':'calm and professional'}
 def create(self):
  return create_growthrova_preview(database_path=self.flow.path,project_url=w.PROJECT,auth_url=w.PROJECT,
    anon_key='sb_publishable_synthetic',http=self.flow.auth,writer_config=self.flow.config,writer_http=self.flow.provider,
    image_config=self.image_config,image_http=self.images).test_client()
 def start(self):return self.client.post(self.url,headers=self.flow.headers,json=self.request)
 def advance(self):return self.client.post(self.url+'/'+self.request['runId']+'/advance',headers=self.flow.headers,json={})
 def test_agent_plans_generates_and_reopens_without_mutating_campaign_or_recharging(self):
  before=self.client.get(self.flow.root+'/'+self.flow.ident,headers=self.flow.headers).json
  start=self.start();self.assertEqual(start.status_code,200,start.json);self.assertEqual(start.json['state'],'planned')
  self.assertEqual(self.images.submissions,[])
  planning=self.advance();self.assertEqual(planning.status_code,200,planning.json);self.assertEqual(planning.json['state'],'planning')
  self.assertEqual(self.flow.provider.calls[0][1]['json'].get('background'),True)
  self.client=self.create()
  plan=self.advance();self.assertEqual(plan.status_code,200,plan.json);self.assertEqual(plan.json['state'],'ready')
  self.assertEqual(len(plan.json['concepts']),1);self.assertEqual(len(self.flow.provider.calls),1)
  generated=self.advance();self.assertEqual(generated.status_code,200,generated.json);self.assertEqual(generated.json['state'],'generating')
  self.assertEqual(len(self.images.submissions),1)
  prompt=self.images.submissions[0][1]['json']['promptText']
  self.assertIn('"selectedConcept"',prompt)
  self.assertIn(plan.json['concepts'][0]['headline'],prompt)
  self.assertIn('"creativeProfile"',prompt)
  self.client=self.create()
  with patch('business_growthrova_runway_images.download_image',return_value=self.pngflow.png):
   done=self.advance()
  self.assertEqual(done.status_code,200,done.json);self.assertEqual(done.json['state'],'review')
  self.assertEqual(done.json['artifacts'][0]['advertCopy']['headline'],plan.json['concepts'][0]['headline'])
  self.assertEqual(self.advance().json,done.json)
  replay=self.client.post(self.url,headers=self.flow.headers,json={**self.request,'runId':'b'*32})
  self.assertEqual(replay.json['runId'],self.request['runId'])
  self.assertEqual(len(self.images.submissions),1);self.assertEqual(len(self.flow.provider.calls),1)
  self.assertEqual(self.client.get(self.flow.root+'/'+self.flow.ident,headers=self.flow.headers).json,before)
  self.assertFalse(done.json['approved']);self.assertFalse(done.json['canPublish'])
 def test_held_concepts_stop_agent_before_image_spend(self):
  self.flow.provider.sample['concepts'][1]['visualDirection']=self.flow.provider.sample['concepts'][0]['visualDirection']
  self.assertEqual(self.start().status_code,200)
  self.assertEqual(self.advance().json['state'],'planning')
  result=self.advance();self.assertEqual(result.json['state'],'held')
  self.assertEqual(self.advance().json['state'],'held')
  self.assertEqual(len(self.flow.provider.calls),1);self.assertEqual(self.images.submissions,[])
 def test_owner_and_revision_changes_cannot_advance_or_submit(self):
  self.assertEqual(self.start().status_code,200)
  owner=self.flow.auth.owner;self.flow.auth.owner=w.OTHER
  self.assertEqual(self.advance().status_code,403)
  self.flow.auth.owner=owner
  self.doc['posts'][0]['graphicText']='Discuss your bicycle servicing'
  r=self.client.post(self.flow.root,headers=self.flow.headers,json={'id':self.flow.ident,'mutationId':'9'*32,'expectedRevision':2,'document':self.doc})
  self.assertEqual(r.status_code,200,r.json)
  held=self.advance();self.assertEqual(held.status_code,409,held.json)
  self.assertEqual(self.images.submissions,[]);self.assertEqual(self.flow.provider.calls,[])

 def test_provider_switch_cannot_substitute_a_different_image_model(self):
  self.assertEqual(self.start().status_code,200)
  self.image_config=replace(self.image_config,model='gemini-3-pro-image',output_cost_microusd=234000)
  self.client=self.create()
  result=self.advance()
  self.assertEqual(result.status_code,409,result.json)
  self.assertEqual(self.flow.provider.calls,[])
  self.assertEqual(self.images.submissions,[])

 def test_three_drafts_run_serially_and_keep_distinct_concept_copy(self):
  self.request['count']=3
  self.assertEqual(self.start().status_code,200)
  self.assertEqual(self.advance().json['state'],'planning')
  self.assertEqual(self.advance().json['state'],'ready')
  for index in range(3):
   pending=self.advance().json
   self.assertEqual(pending['state'],'generating',pending)
   self.assertEqual(pending['completedCount'],index)
   with patch('business_growthrova_runway_images.download_image',return_value=self.pngflow.png):
    done=self.advance().json
   self.assertEqual(done['completedCount'],index+1,done)
  self.assertEqual(done['state'],'review')
  self.assertEqual(len({a['advertCopy']['headline'] for a in done['artifacts']}),3)
  self.assertEqual(len(self.images.submissions),3)
  self.assertEqual(len(self.flow.provider.calls),1)

 def test_direct_google_agent_can_plan_and_generate_without_runway(self):
  self.image_config=self.pngflow.config
  self.images=self.pngflow.provider
  self.client=self.create()
  status=self.client.get(self.url,headers=self.flow.headers)
  self.assertTrue(status.json['available'],status.json)
  self.assertEqual(status.json['providerLabel'],'Google Gemini · Nano Banana Pro')
  self.assertEqual(self.start().status_code,200)
  self.assertEqual(self.advance().json['state'],'planning')
  self.assertEqual(self.advance().json['state'],'ready')
  result=self.advance()
  self.assertEqual(result.status_code,200,result.json)
  self.assertEqual(result.json['state'],'review')
  self.assertEqual(result.json['artifacts'][0]['model'],'gemini-3-pro-image')
  self.assertEqual(len(self.images.calls),1)
  self.assertTrue(self.images.calls[0][0].startswith('https://generativelanguage.googleapis.com/'))
  self.assertNotIn('Authorization',self.images.calls[0][1]['headers'])

 def change_memory(self):
  import sqlite3,json
  with sqlite3.connect(self.flow.path) as con:
   con.execute("INSERT OR REPLACE INTO growthrova_creative_references VALUES(?,?,?,?,?)",
    (self.flow.auth.owner,w.ORG,self.flow.ident,1,json.dumps([])))
 def test_new_memory_creates_new_agent_run_instead_of_replaying_old_plan(self):
  self.assertEqual(self.start().status_code,200)
  self.change_memory()
  self.request['runId']='c'*32
  result=self.start()
  self.assertEqual(result.status_code,200,result.json)
  self.assertEqual(result.json['runId'],'c'*32)
  self.assertEqual(self.flow.provider.calls,[])
 def test_memory_change_blocks_existing_run_before_provider_spend(self):
  self.assertEqual(self.start().status_code,200)
  self.change_memory()
  result=self.advance()
  self.assertEqual(result.status_code,409,result.json)
  self.assertEqual(result.json['code'],'creative_memory_changed')
  self.assertEqual(self.images.submissions,[])
  self.assertEqual(self.flow.provider.calls,[])
