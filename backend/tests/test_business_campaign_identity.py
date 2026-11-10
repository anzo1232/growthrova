"""Identity references are immutable, revision-sensitive and cannot be inferred from names."""
import sqlite3,unittest,uuid,copy
import business_marketing_drafts as drafts
import business_campaign_identity as identity
from tests.test_business_marketing_drafts import document
class IdentityTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
  drafts.initialise(self.db);identity.initialise(self.db)
  self.did=uuid.uuid4().hex;self.doc=document()
  drafts.save_draft(self.db,{'id':self.did,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':self.doc})
 def bind(self):return identity.bind_internal(self.db,self.did,1,'org-123','brand-123',verified_owner_reference='authenticated-fixture-owner')
 def test_missing_binding_denies_access(self):
  with self.assertRaises(identity.BindingError):identity.require(self.db,self.did,1,'org-123','brand-123')
 def test_correct_binding_and_foreign_scope(self):
  self.assertFalse(self.bind()['canSpend']);self.assertTrue(identity.require(self.db,self.did,1,'org-123','brand-123'))
  with self.assertRaises(identity.BindingError):identity.require(self.db,self.did,1,'org-456','brand-123')
  with self.assertRaises(identity.BindingError):identity.require(self.db,self.did,1,'org-123','brand-456')
 def test_immutable_owner_binding(self):
  self.bind();self.assertEqual(self.bind()['businessId'],'brand-123')
  with self.assertRaises(identity.BindingError):identity.bind_internal(self.db,self.did,1,'org-123','brand-456',verified_owner_reference='authenticated-fixture-owner')
 def test_revision_change_invalidates_binding(self):
  self.bind();self.db.commit();new=copy.deepcopy(self.doc);new['goal']='bookings'
  drafts.save_draft(self.db,{'id':self.did,'expectedRevision':1,'mutationId':uuid.uuid4().hex,'document':new})
  with self.assertRaises(identity.BindingError):identity.require(self.db,self.did,2,'org-123','brand-123')
 def test_same_verified_owner_can_revalidate_new_campaign_revision(self):
  self.bind();self.db.commit();new=copy.deepcopy(self.doc);new['goal']='bookings'
  drafts.save_draft(self.db,{'id':self.did,'expectedRevision':1,'mutationId':uuid.uuid4().hex,'document':new})
  with self.assertRaises(identity.BindingError):identity.require(self.db,self.did,2,'org-123','brand-123')
  updated=identity.bind_internal(self.db,self.did,2,'org-123','brand-123',verified_owner_reference='authenticated-fixture-owner')
  self.assertEqual(updated['businessId'],'brand-123')
  self.assertTrue(identity.require(self.db,self.did,2,'org-123','brand-123'))
 def test_no_empty_owner_evidence(self):
  with self.assertRaises(identity.BindingError):identity.bind_internal(self.db,self.did,1,'org-123','brand-123',verified_owner_reference='')
if __name__=='__main__':unittest.main()
