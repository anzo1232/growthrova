"""Final post acceptance binds exactly the copy, saved draft and rendered bytes."""
import hashlib,json,tempfile,unittest,sqlite3
from pathlib import Path
import business_marketing_drafts as drafts
import business_agency_pack_jobs as packs
import business_post_approvals as approval
from tests.test_business_agency_pack import AgencyPackTests

DID='a'*32
class PostApprovalTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
  drafts.initialise(self.con);packs.initialise(self.con);approval.initialise(self.con)
  demo=AgencyPackTests();demo.setUp();self.addCleanup(demo.doCleanups)
  self.doc=demo.doc;self.source=demo.image
  drafts.save_draft(self.con,{'id':DID,'mutationId':'b'*32,'expectedRevision':0,'document':self.doc})
 def save_review(self):
  prior=drafts.read_draft(self.con,DID)
  doc=prior['document'];doc['posts'][0]['status']='copy_reviewed'
  saved=drafts.save_draft(self.con,{'id':DID,'mutationId':'c'*32,'expectedRevision':prior['revision'],'document':doc})
  return saved['revision']
 def pack(self,revision):
  job=packs.enqueue_pack(self.con,DID,revision,self.root)
  packs.render_pack(self.con,job['id'],self.root,source_image=self.source)
  return job['id']
 def accept(self,revision,kit):
  return approval.approve_post(self.con,DID,revision,kit,1,self.root,
   claims_checked=True,visuals_checked=True,rights_checked=True)
 def test_unreviewed_draft_cannot_be_approved(self):
  kit=self.pack(1)
  with self.assertRaises(approval.ApprovalError):self.accept(1,kit)
 def test_verifiable_review_creates_one_receipt_but_no_publish_permission(self):
  revision=self.save_review();kit=self.pack(revision)
  one=self.accept(revision,kit)
  two=self.accept(revision,kit)
  self.assertEqual(one['id'],two['id'])
  self.assertEqual(one['status'],'approved_for_manual_use')
  self.assertFalse(one['published']);self.assertFalse(one['publishAuthorized'])
  self.assertEqual(len(approval.list_approvals(self.con,DID,kit,self.root)),1)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_post_approvals').fetchone()[0],1)
 def test_requires_explicit_three_consents_and_prevents_forged_kit(self):
  revision=self.save_review();kit=self.pack(revision)
  with self.assertRaises(approval.ApprovalError):
   approval.approve_post(self.con,DID,revision,kit,1,self.root,claims_checked=True,visuals_checked=True,rights_checked=False)
  with self.assertRaises(approval.ApprovalError):
   self.accept(revision,'b'*32)
 def test_edit_revokes_previous_approval_without_erasing_audit(self):
  revision=self.save_review();kit=self.pack(revision);self.accept(revision,kit)
  saved=drafts.read_draft(self.con,DID);doc=saved['document']
  doc['posts'][0]['copyDraft']+=' Changed words requiring new approval.'
  updated=drafts.save_draft(self.con,{'id':DID,'mutationId':'d'*32,'expectedRevision':revision,'document':doc})
  self.assertEqual(updated['document']['posts'][0]['status'],'draft')
  self.assertEqual(approval.list_approvals(self.con,DID,kit,self.root),[])
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_post_approvals').fetchone()[0],1)
 def test_changed_image_invalidates_existing_approval(self):
  revision=self.save_review();kit=self.pack(revision);self.accept(revision,kit)
  path=self.root/'marketing_packs'/kit/'post-day-01.png'
  path.write_bytes(path.read_bytes()+b'changed')
  self.assertEqual(approval.list_approvals(self.con,DID,kit,self.root),[])
  with self.assertRaises(approval.ApprovalError):self.accept(revision,kit)

 def test_video_plan_cannot_be_approved_using_its_static_preview(self):
  saved=drafts.read_draft(self.con,DID)
  doc=saved['document'];doc['posts'][0]['format']='Reel concept'
  drafts.save_draft(self.con,{'id':DID,'mutationId':'e'*32,'expectedRevision':saved['revision'],'document':doc})
  revision=self.save_review();kit=self.pack(revision)
  report=json.loads((self.root/'marketing_packs'/kit/'creative-quality-report.json').read_text())
  self.assertEqual(report['posts'][0]['status'],'rejected_by_preflight')
  with self.assertRaises(approval.ApprovalError):self.accept(revision,kit)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_post_approvals').fetchone()[0],0)

 def test_missing_quality_report_cannot_be_approved(self):
  revision=self.save_review();kit=self.pack(revision)
  (self.root/'marketing_packs'/kit/'creative-quality-report.json').unlink()
  with self.assertRaises(approval.ApprovalError):self.accept(revision,kit)

 def test_changed_quality_report_expires_previous_manual_approval(self):
  revision=self.save_review();kit=self.pack(revision);self.accept(revision,kit)
  path=self.root/'marketing_packs'/kit/'creative-quality-report.json'
  path.write_bytes(path.read_bytes()+b' ')
  self.assertEqual(approval.list_approvals(self.con,DID,kit,self.root),[])
  with self.assertRaises(approval.ApprovalError):self.accept(revision,kit)

 def test_current_report_must_have_one_matching_passing_post(self):
  revision=self.save_review();kit=self.pack(revision)
  folder=self.root/'marketing_packs'/kit
  report=json.loads((folder/'creative-quality-report.json').read_text())
  manifest=json.loads((folder/'manifest.json').read_text())
  cases={
   'missing_day':[row for row in report['posts'] if row['day']!=1],
   'duplicate_day':report['posts']+[report['posts'][0]],
   'rejected_day':[{**row,'status':'rejected_by_preflight','issues':['weak_or_generic_hook']} if row['day']==1 else row for row in report['posts']],
   'unknown_status':[{**row,'status':'not_checked'} if row['day']==1 else row for row in report['posts']],
   'different_format':[{**row,'format':'Carousel'} if row['day']==1 else row for row in report['posts']],
   'different_channel':[{**row,'channel':'TikTok'} if row['day']==1 else row for row in report['posts']],
  }
  for name,rows in cases.items():
   with self.subTest(name=name):
    blob=json.dumps({**report,'posts':rows}).encode()
    (folder/'creative-quality-report.json').write_bytes(blob)
    manifest['fileSHA256']['creative-quality-report.json']=hashlib.sha256(blob).hexdigest()
    (folder/'manifest.json').write_text(json.dumps(manifest))
    with self.assertRaises(approval.ApprovalError):self.accept(revision,kit)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_post_approvals').fetchone()[0],0)

 def test_static_preview_cannot_stand_in_for_multi_asset_or_unknown_formats(self):
  for index,fmt in enumerate(('Carousel','Story','Unknown format')):
   with self.subTest(format=fmt):
    saved=drafts.read_draft(self.con,DID)
    doc=saved['document'];doc['posts'][0]['format']=fmt
    doc['posts'][0]['status']='copy_reviewed'
    revision=drafts.save_draft(self.con,{'id':DID,'mutationId':format(index+12,'032x'),
      'expectedRevision':saved['revision'],'document':doc})['revision']
    # A changed format resets copy review; record review on its saved version.
    prior=drafts.read_draft(self.con,DID);doc=prior['document'];doc['posts'][0]['status']='copy_reviewed'
    revision=drafts.save_draft(self.con,{'id':DID,'mutationId':format(index+22,'032x'),
      'expectedRevision':revision,'document':doc})['revision']
    kit=self.pack(revision)
    with self.assertRaises(approval.ApprovalError):self.accept(revision,kit)
