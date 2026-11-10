"""Business picture import is owner-attested, SSRF-safe and privacy preserving."""
from __future__ import annotations
import io,sqlite3,tempfile,unittest
from pathlib import Path
from PIL import Image
import business_marketing_drafts as drafts
from tests.test_business_marketing_drafts import document

DID='b'*32
URL='https://example.org/photos/work.jpg'
def demo_photo():
    b=io.BytesIO()
    Image.new('RGB',(900,700),(72,99,124)).save(b,format='JPEG')
    return b.getvalue()

class WebsitePhotoTests(unittest.TestCase):
 def setUp(self):
    from business_website_media import initialise
    tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
    self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
    drafts.initialise(self.con);initialise(self.con)
    d=document();d['websiteImages']=[{'url':URL,'alt':'Roofer installing tiles','rights_confirmed':False}]
    drafts.save_draft(self.con,{'id':DID,'mutationId':'e'*32,'expectedRevision':0,'document':d})
    self.calls=0
 def fetch(self,url,ip):
    self.calls+=1
    self.assertEqual(url,URL)
    self.assertEqual(ip,'93.184.215.14')
    return demo_photo(),'image/jpeg'
 def resolver(self,*a,**k):
    return [(None,None,None,None,('93.184.215.14',443))]
 def test_requires_owner_attestation_and_exact_candidate_match(self):
    from business_website_media import import_photo,MediaError
    with self.assertRaises(MediaError):import_photo(self.con,DID,URL,self.root,owner_confirmed=False,fetch=self.fetch,resolve=self.resolver)
    with self.assertRaises(MediaError):import_photo(self.con,DID,'https://other-site.example/photos.jpg',self.root,owner_confirmed=True,fetch=self.fetch,resolve=self.resolver)
    self.assertEqual(self.calls,0)
 def test_upload_is_local_private_metadata_stripped_and_idempotent(self):
    from business_website_media import import_photo,list_photos
    a=import_photo(self.con,DID,URL,self.root,owner_confirmed=True,fetch=self.fetch,resolve=self.resolver)
    self.assertEqual(self.calls,1)
    self.assertEqual(a['rightsStatus'],'owner_declared')
    self.assertFalse(a['authenticityVerified'])
    path=self.root/'website_photos'/DID/(a['id']+'.jpg')
    self.assertTrue(path.is_file());self.assertEqual(path.stat().st_mode&0o777,0o600)
    with Image.open(path) as im:
      self.assertEqual(im.format,'JPEG');self.assertEqual(im.size,(900,700))
      self.assertNotIn('exif',im.info)
    b=import_photo(self.con,DID,URL,self.root,owner_confirmed=True,fetch=self.fetch,resolve=self.resolver)
    self.assertEqual(a,b);self.assertEqual(self.calls,1)
    self.assertEqual(len(list_photos(self.con,DID)),1)
 def test_rejects_invalid_or_oversized_media(self):
    from business_website_media import import_photo,MediaError
    for fake,mime in [(b'<svg><script>alert(1)</script></svg>','image/svg+xml'),(b'not an image','image/jpeg'),(b'x'*(9*1024*1024),'image/jpeg')]:
     with self.assertRaises(MediaError):
      import_photo(self.con,DID,URL,self.root,owner_confirmed=True,
        fetch=lambda *args:(fake,mime),resolve=self.resolver)
 def test_rejects_private_host_resolution_and_restricted_url(self):
    from business_website_media import import_photo,MediaError
    private=lambda *args,**kwargs:[(None,None,None,None,('127.0.0.1',443))]
    with self.assertRaises(MediaError):import_photo(self.con,DID,URL,self.root,owner_confirmed=True,fetch=self.fetch,resolve=private)
    self.assertEqual(self.calls,0)

if __name__=='__main__':unittest.main()
