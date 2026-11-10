"""Real localhost persistence tests for the editable marketing campaign board."""
import copy,json,tempfile,threading,unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import business_local_pilot as pilot

DRAFT_ID='1'*32
MUTATION='2'*32

def document():
    return {'version':1,'name':'First marketing campaign','business':'Example restaurant',
        'sourceUrl':'https://example.org/','goal':'enquiries','observedFacts':['Website says seasonal dining'],
        'posts':[{'day':i,'theme':'Day '+str(i),'channel':'Instagram','format':'Image advert',
          'objective':'awareness','copyDraft':'Original copy','callToAction':'Explore the menu','status':'draft'} for i in range(1,31)],
        'creatives':[{'id':'creative-1','format':'image_ad','title':'Hero image','ratio':'4:5',
          'brief':'Use authentic assets with an editorial composition','copyDraft':'Discover our restaurant',
          'callToAction':'Explore the menu','status':'draft'}]}

class MarketingDraftTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='clippr-marketing-save-');self.addCleanup(temp.cleanup)
        old=pilot.BASE;pilot.BASE=Path(temp.name);self.addCleanup(setattr,pilot,'BASE',old)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),pilot.Handler)
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def request(self,path,body=None,origin='http://127.0.0.1:4185'):
        req=Request(self.base+'/api/pilot/marketing-drafts'+path,
          data=json.dumps(body).encode() if body is not None else None,
          headers={'Content-Type':'application/json','X-Clippr-Pilot':'local-only','Origin':origin})
        try:
            with urlopen(req,timeout=5) as r:return r.status,json.loads(r.read())
        except HTTPError as e:
            with e:return e.code,json.loads(e.read())
    def save(self,doc=None,revision=0,mutation=MUTATION):
        return self.request('',{'id':DRAFT_ID,'expectedRevision':revision,'mutationId':mutation,'document':doc or document()})
    def test_owner_strategy_persists_replays_and_invalidates_on_context_changes(self):
        doc=document()
        strategy={k:'Owner supplied '+k for k in ('audience','offer','positioning','callToAction','constraints')}
        strategy['factDecisions']=[{'index':0,'observation':doc['observedFacts'][0],'decision':'confirmed','statement':''}]
        context={k:doc[k] for k in ('business','goal','sourceUrl','observedFacts')}
        strategy['confirmedContext']={**context,**strategy}
        doc['ownerStrategy']=strategy
        doc['calendarStartDate']='2026-11-01'
        code,saved=self.save(doc);self.assertEqual(code,200,saved)
        self.assertEqual(self.save(doc)[1]['revision'],1)
        _,restored=self.request('/'+DRAFT_ID)
        self.assertEqual(restored['document']['ownerStrategy'],strategy)
        self.assertEqual(restored['document']['calendarStartDate'],'2026-11-01')
        self.assertFalse(restored['document']['canPublish'])
        doc['observedFacts']=['Changed website context']
        code,saved=self.save(doc,1,'3'*32);self.assertEqual(code,200,saved)
        self.assertIsNone(saved['document']['ownerStrategy']['confirmedContext'])
        doc['ownerStrategy']['offer']='x'*501
        self.assertEqual(self.save(doc,2,'4'*32)[0],400)

    def test_full_30_day_plan_survives_independent_read(self):
        code,saved=self.save();self.assertEqual(code,200,saved)
        self.assertEqual(saved['revision'],1)
        code,reloaded=self.request('/'+DRAFT_ID);self.assertEqual(code,200,reloaded)
        self.assertEqual(len(reloaded['document']['posts']),30)
        self.assertEqual(reloaded['document']['creatives'][0]['copyDraft'],'Discover our restaurant')
        code,listing=self.request('');self.assertEqual(code,200)
        self.assertEqual(listing['drafts'][0]['id'],DRAFT_ID)
    def test_update_retains_individual_copy_and_detects_stale_revision(self):
        self.assertEqual(self.save()[0],200)
        doc=document();doc['posts'][7]['copyDraft']='Edited day eight';doc['creatives'][0]['copyDraft']='Edited creative'
        code,saved=self.save(doc,1,'3'*32);self.assertEqual(code,200,saved)
        self.assertEqual(saved['revision'],2)
        code,conflict=self.save(document(),1,'4'*32);self.assertEqual(code,409,conflict)
        self.assertEqual(conflict['code'],'revision_conflict')
        _,reloaded=self.request('/'+DRAFT_ID)
        self.assertEqual(reloaded['document']['posts'][7]['copyDraft'],'Edited day eight')
    def test_lost_acknowledgement_replays_once_without_new_revision(self):
        first=self.save();second=self.save()
        self.assertEqual(first[0],200,first);self.assertEqual(second[0],200,second)
        self.assertEqual(first[1]['revision'],second[1]['revision'])
        self.assertTrue(second[1]['replayed'])
        changed=document();changed['name']='Different content'
        self.assertEqual(self.save(changed)[0],409)
    def test_replayed_old_mutation_does_not_replace_a_newer_revision(self):
        self.assertEqual(self.save()[0],200)
        changed=document();changed['name']='Newer campaign'
        self.assertEqual(self.save(changed,1,'3'*32)[0],200)
        code,error=self.save();self.assertEqual(code,409,error)
        self.assertEqual(error['code'],'replay_superseded')
    def test_client_cannot_persist_publish_spend_or_fake_generation_permissions(self):
        doc=document();doc.update(canPublish=True,canSpend=True,published=True)
        doc['posts'][0].update(published=True,scheduled=True)
        doc['creatives'][0].update(assetUrl='https://unverified.example/a.png',approved=True,mediaStatus='completed')
        code,saved=self.save(doc);self.assertEqual(code,200,saved)
        d=saved['document'];self.assertFalse(d['canPublish']);self.assertFalse(d['canSpend'])
        self.assertFalse(d['posts'][0]['published']);self.assertFalse(d['posts'][0]['scheduled'])
        self.assertIsNone(d['creatives'][0]['assetUrl']);self.assertEqual(d['creatives'][0]['mediaStatus'],'not_generated')
    def test_editing_copy_invalidates_its_review(self):
        doc=document();doc['posts'][0]['status']='copy_reviewed';self.assertEqual(self.save(doc)[0],200)
        doc['posts'][0]['copyDraft']='Now a different claim'
        code,saved=self.save(doc,1,'3'*32);self.assertEqual(code,200,saved)
        self.assertEqual(saved['document']['posts'][0]['status'],'draft')
    def test_invalid_or_cross_origin_write_is_rejected(self):
        code,_=self.request('',{'id':DRAFT_ID,'expectedRevision':0,'mutationId':MUTATION,'document':document()},origin='https://evil.example')
        self.assertEqual(code,403)
        doc=document();doc['posts'][1]['day']=1
        self.assertEqual(self.save(doc)[0],400)
        doc=document();doc['sourceUrl']='javascript:alert(1)'
        self.assertEqual(self.save(doc)[0],400)
        code,_=self.request('',{'id':'../../elsewhere','expectedRevision':0,'mutationId':MUTATION,'document':document()})
        self.assertEqual(code,400)
        self.assertEqual(self.request('/'+'f'*32)[0],404)
    def test_two_editors_cannot_both_commit_the_same_base_revision(self):
        self.assertEqual(self.save()[0],200)
        barrier=threading.Barrier(2);results=[]
        def writer(n):
            doc=document();doc['name']='Editor '+str(n);barrier.wait()
            results.append(self.save(doc,1,str(n)*32)[0])
        threads=[threading.Thread(target=writer,args=(n,)) for n in [3,4]]
        for t in threads:t.start()
        for t in threads:t.join(6)
        self.assertEqual(sorted(results),[200,409])

if __name__=='__main__':unittest.main()

class WebsiteImagesPersistenceTests(unittest.TestCase):
 def test_images_are_saved_without_accepting_forged_rights_and_other_domains(self):
  import business_marketing_drafts as drafts
  doc=document()
  doc['websiteImages']=[{'url':'https://example.org/work/roof.jpg','alt':'Real roof photo','rights_confirmed':True,'authenticity_verified':True}]
  normalized=drafts.normalise_document(doc)
  self.assertEqual(normalized['websiteImages'][0]['url'],'https://example.org/work/roof.jpg')
  self.assertFalse(normalized['websiteImages'][0]['rights_confirmed'])
  self.assertFalse(normalized['websiteImages'][0]['authenticity_verified'])
  for bad in ['http://example.org/a.jpg','https://different.org/tracking.jpg','https://example.org@evil.org/roof.jpg','data:image/png;base64,AAAA']:
   altered=document();altered['websiteImages']=[{'url':bad,'alt':'Image'}]
   with self.assertRaises(drafts.MarketingDraftError):drafts.normalise_document(altered)

class CalendarDateValidationTests(unittest.TestCase):
 def test_valid_start_day_is_preserved_without_scheduling(self):
  import business_marketing_drafts as drafts
  d=document();d['calendarStartDate']='2026-11-02'
  clean=drafts.normalise_document(d)
  self.assertEqual(clean['calendarStartDate'],'2026-11-02')
  self.assertTrue(all(not p['scheduled'] for p in clean['posts']))
 def test_invalid_day_and_calendar_injection_blocked(self):
  import business_marketing_drafts as drafts
  for value in ('2026-02-30','2026-12-01\r\nBEGIN:VEVENT','12/1/2026','2026-14-01'):
   d=document();d['calendarStartDate']=value
   with self.assertRaises(drafts.MarketingDraftError):drafts.normalise_document(d)
