import io,json,tempfile,threading,unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from PIL import Image
import business_local_pilot as pilot
import business_website_media as media
from tests.test_business_marketing_drafts import document

DID='a'*32
PHOTO='https://example.org/roofing.jpg'
class WebsiteMediaRouteTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
  old=pilot.BASE;pilot.BASE=self.root;self.addCleanup(setattr,pilot,'BASE',old)
  with pilot.session() as con:
   doc=document();doc['websiteImages']=[{'url':PHOTO,'alt':'Roof repair picture','rights_confirmed':False}]
   import business_marketing_drafts as drafts
   drafts.save_draft(con,{'id':DID,'mutationId':'b'*32,'expectedRevision':0,'document':doc})
  self.server=ThreadingHTTPServer(('127.0.0.1',0),pilot.Handler)
  self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
  threading.Thread(target=self.server.serve_forever,daemon=True).start()
  self.base='http://127.0.0.1:'+str(self.server.server_port)
 def request(self,path,body=None):
  req=Request(self.base+'/api/pilot/website-photos'+path,
    data=json.dumps(body).encode() if body is not None else None,
    headers={'Content-Type':'application/json','X-Clippr-Pilot':'local-only','Origin':'http://127.0.0.1:4185'})
  try:
   with urlopen(req,timeout=5) as r:return r.status,json.loads(r.read())
  except HTTPError as e:
   with e:return e.code,json.loads(e.read())
 def test_rights_are_explicit_and_photo_can_be_reused_as_a_local_asset(self):
  missing=self.request('/import',{'draftId':DID,'url':PHOTO,'ownerConfirmed':False})
  self.assertEqual(missing[0],403)
  raw=io.BytesIO();Image.new('RGB',(900,700),'#b99677').save(raw,'JPEG')
  real=media.import_photo
  def fake(*args,**kwargs):
   return real(*args,**{**kwargs,'fetch':lambda *a:(raw.getvalue(),'image/jpeg'),
       'resolve':lambda *a,**k:[(None,None,None,None,('93.184.215.14',443))]})
  with patch.object(pilot.website_media,'import_photo',side_effect=fake):
   ok=self.request('/import',{'draftId':DID,'url':PHOTO,'ownerConfirmed':True})
  self.assertEqual(ok[0],200,ok)
  self.assertEqual(ok[1]['rightsStatus'],'owner_declared')
  status,data=self.request('?draftId='+DID)
  self.assertEqual(status,200,data);self.assertEqual(len(data['photos']),1)
  self.assertEqual(data['photos'][0]['id'],ok[1]['id'])
 def test_cannot_import_unlisted_cross_business_url(self):
  status,data=self.request('/import',{'draftId':DID,'url':'https://evil.example/tracker.jpg','ownerConfirmed':True})
  self.assertEqual(status,403,data)
 def test_photo_preview_is_private_and_bound_to_its_business(self):
  raw=io.BytesIO();Image.new('RGB',(900,700),'#b99677').save(raw,'JPEG')
  real=media.import_photo
  def fake(*args,**kwargs):
   return real(*args,**{**kwargs,'fetch':lambda *a:(raw.getvalue(),'image/jpeg'),
       'resolve':lambda *a,**k:[(None,None,None,None,('93.184.215.14',443))]})
  with patch.object(pilot.website_media,'import_photo',side_effect=fake):
   code,saved=self.request('/import',{'draftId':DID,'url':PHOTO,'ownerConfirmed':True})
  self.assertEqual(code,200,saved)
  asset=saved['id']
  endpoint=self.base+'/api/pilot/website-photos/'+asset+'/image?draftId='+DID
  good=Request(endpoint,headers={'X-Clippr-Pilot':'local-only','Origin':'http://127.0.0.1:4185'})
  with urlopen(good,timeout=5) as r:
   self.assertEqual(r.headers['Content-Type'],'image/jpeg')
   content=r.read()
  self.assertEqual(Image.open(io.BytesIO(content)).size,(900,700))
  other=Request(self.base+'/api/pilot/website-photos/'+asset+'/image?draftId='+'f'*32,
     headers={'X-Clippr-Pilot':'local-only','Origin':'http://127.0.0.1:4185'})
  with self.assertRaises(HTTPError) as err:urlopen(other,timeout=5)
  self.assertEqual(err.exception.code,404)
