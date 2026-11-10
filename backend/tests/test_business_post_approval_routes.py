"""The actual loopback HTTP API must enforce final post review, not frontend flags."""
import json,tempfile,threading,unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from PIL import Image
import business_local_pilot as pilot
import business_marketing_drafts as drafts
import business_agency_pack_jobs as packs
from tests.test_business_agency_pack import AgencyPackTests

ID='f'*32
class ApprovalHttpTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
  old=pilot.BASE;pilot.BASE=Path(temp.name);self.addCleanup(setattr,pilot,'BASE',old)
  case=AgencyPackTests();case.setUp();self.addCleanup(case.doCleanups)
  with pilot.session() as con:
   doc=case.doc;doc['posts'][0]['status']='copy_reviewed'
   drafts.save_draft(con,{'id':ID,'expectedRevision':0,'mutationId':'e'*32,'document':doc})
   job=packs.enqueue_pack(con,ID,1,pilot.BASE)
   packs.render_pack(con,job['id'],pilot.BASE,source_image=case.image)
   self.kit=job['id']
  server=ThreadingHTTPServer(('127.0.0.1',0),pilot.Handler)
  self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  threading.Thread(target=server.serve_forever,daemon=True).start()
  self.base='http://127.0.0.1:'+str(server.server_port)+'/api/pilot/post-approvals'
 def api(self,body=None):
  url=self.base if body is not None else self.base+'?draftId='+ID+'&kitId='+self.kit
  req=Request(url,data=json.dumps(body).encode() if body is not None else None,
    headers={'Origin':'http://127.0.0.1:4185','X-Clippr-Pilot':'local-only','Content-Type':'application/json'})
  try:
   with urlopen(req,timeout=15) as res:return res.status,json.loads(res.read())
  except HTTPError as e:
   with e:return e.code,json.loads(e.read())
 def request(self,**overrides):
  return {'draftId':ID,'expectedRevision':1,'kitId':self.kit,'day':1,
   'claimsChecked':True,'visualsChecked':True,'rightsChecked':True}|overrides
 def test_cannot_approve_without_explicit_checkboxes(self):
  status,result=self.api(self.request(rightsChecked=False))
  self.assertEqual(status,403,result)
  self.assertEqual(self.api()[1]['approvals'],[])
 def test_checked_post_receipt_is_readable_and_cannot_publish(self):
  status,result=self.api(self.request())
  self.assertEqual(status,200,result)
  self.assertEqual(result['status'],'approved_for_manual_use')
  self.assertFalse(result['published'])
  self.assertFalse(result['publishAuthorized'])
  self.assertEqual(self.api()[1]['approvals'][0]['id'],result['id'])
  self.assertEqual(self.api(self.request())[1]['id'],result['id'])
 def test_current_quality_report_and_manifest_are_readable_as_json(self):
  assets=self.base.rsplit('/',1)[0]+'/agency-packs/'+self.kit+'/assets/'
  for name in ('manifest.json','creative-quality-report.json'):
   with self.subTest(asset=name):
    req=Request(assets+name,headers={'Origin':'http://127.0.0.1:4185','X-Clippr-Pilot':'local-only'})
    with urlopen(req,timeout=15) as res:
     self.assertEqual(res.status,200)
     self.assertEqual(res.headers.get_content_type(),'application/json')
     result=json.loads(res.read())
    expected=json.loads((pilot.BASE/'marketing_packs'/self.kit/name).read_text())
    self.assertEqual(result,expected)
    if name=='creative-quality-report.json':
     self.assertEqual(result['posts'][0]['status'],'awaiting_human_creative_review')
 def test_media_mutation_cannot_reuse_approval(self):
  code,data=self.api(self.request());self.assertEqual(code,200,data)
  path=pilot.BASE/'marketing_packs'/self.kit/'post-day-01.png'
  path.write_bytes(path.read_bytes()+b'bad')
  self.assertEqual(self.api()[1]['approvals'],[])
  code,data=self.api(self.request());self.assertEqual(code,409,data)
