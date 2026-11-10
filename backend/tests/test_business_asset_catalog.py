"""Private business media catalogue: recorded rights never imply proof or approval."""
import sqlite3,tempfile,unittest,hashlib,subprocess
from PIL import Image
from pathlib import Path
import business_asset_catalog as catalog

class AssetTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
  catalog.initialise(self.db)
  self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
  self.path=Path(self.folder.name)/'photo.png';Image.new('RGB',(64,64)).save(self.path)
 def item(self,**updates):
  data={'organisationId':'org-A','businessId':'brand-A','assetId':'source-123',
   'mediaKind':'photo','mimeType':'image/png','sourceSha256':hashlib.sha256(self.path.read_bytes()).hexdigest(),
   'sourceBytes':self.path.stat().st_size,'rightsStatement':'Owner affirms rights to use this image in marketing',
   'consentStatus':'owner_asserted','originalName':'kitchen.png'}
  data.update(updates);return data
 def test_intake_is_private_versioned_and_not_approved(self):
  x=catalog.record(self.db,self.item(),self.path)
  self.assertEqual(x['businessId'],'brand-A');self.assertFalse(x['verifiedRights'])
  self.assertFalse(x['canPublish']);self.assertFalse(x['canSpend'])
  self.assertEqual(catalog.list_assets(self.db,'org-A','brand-A')[0]['assetId'],'source-123')
  self.assertEqual(catalog.list_assets(self.db,'org-B','brand-A'),[])
 def test_original_byte_change_rejected(self):
  with self.assertRaises(catalog.AssetError):catalog.record(self.db,self.item(sourceSha256='0'*64),self.path)
 def test_duplicate_is_idempotent_but_replacement_requires_new_asset_id(self):
  first=catalog.record(self.db,self.item(),self.path)
  self.assertEqual(first,catalog.record(self.db,self.item(),self.path))
  with self.assertRaises(catalog.AssetError):catalog.record(self.db,self.item(rightsStatement='Different statement with sufficient length'),self.path)
 def test_logos_photos_and_videos_are_supported_but_claims_remain_unverified(self):
  for n,mime,kind in [('logo','image/png','logo'),('movie','video/mp4','video')]:
   p=Path(self.folder.name)/(n+'.bin')
   if kind=='logo':Image.new('RGB',(64,64)).save(p,format='PNG')
   else:subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=black:s=320x320:r=1:d=1','-c:v','libx264','-pix_fmt','yuv420p','-y',str(p.with_suffix('.mp4'))],check=True,timeout=20);p=p.with_suffix('.mp4')
   asset=self.item(assetId=n,mediaKind=kind,mimeType=mime,sourceSha256=hashlib.sha256(p.read_bytes()).hexdigest(),sourceBytes=p.stat().st_size)
   r=catalog.record(self.db,asset,p)
   self.assertFalse(r['authenticityVerified'])
 def test_false_mime_and_invalid_media_are_rejected(self):
  corrupt=Path(self.folder.name)/'fake.png';corrupt.write_bytes(b'fake image bytes')
  item=self.item(assetId='fake-image',sourceSha256=hashlib.sha256(corrupt.read_bytes()).hexdigest(),sourceBytes=corrupt.stat().st_size)
  with self.assertRaises(catalog.AssetError):catalog.record(self.db,item,corrupt)
 def test_unconfirmed_rights_are_held(self):
  x=catalog.record(self.db,self.item(consentStatus='not_confirmed'),self.path)
  self.assertEqual(x['usageStatus'],'held_rights_unconfirmed')
 def test_unsupported_type_and_forged_permissions_rejected(self):
  for changes in [{'mimeType':'text/html'},{'canPublish':True},{'consentStatus':'verified_by_ai'}]:
   with self.subTest(changes=changes),self.assertRaises(catalog.AssetError):catalog.record(self.db,self.item(**changes),self.path)
if __name__=='__main__':unittest.main()
