import sqlite3,unittest
import business_marketing_drafts as drafts
from tests.test_business_marketing_drafts import document
class EditorialShortlistStorageTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
  self.addCleanup(self.c.close);drafts.initialise(self.c)
 def sample(self):
  content=document()
  content['editorialShortlist']={
   'sector':'restaurant','status':'three_directions_ready_for_asset_intake','approved':True,'canGenerateAutomatically':True,
   'candidates':[{'id':n,'role':role,'media':media,'format':fmt,'direction':'Actual business-relevant visual direction',
     'hook':'One real grounded hook','evidence':{'kind':key,'label':'paragraph 1','quote':'Berenjak describes specific Persian food and cooking techniques.'},
     'spendApproved':True,'publishApproved':True} for n,role,media,fmt,key in (
    ('craft','Craft','Reel','9:16','method'),('discover','Discover','Carousel','4:5','dish'),
    ('insider','Insider','Image','4:5','bread'))]}
  return content
 def test_saved_shortlist_survives_but_all_fake_approval_flags_are_stripped(self):
  original=self.sample()
  did='a'*32
  saved=drafts.save_draft(self.c,{'id':did,'mutationId':'b'*32,'expectedRevision':0,'document':original})
  out=drafts.read_draft(self.c,did)['document']['editorialShortlist']
  self.assertEqual(len(out['candidates']),3)
  self.assertFalse(out['approved']);self.assertFalse(out['canGenerateAutomatically'])
  self.assertTrue(all(not p['spendApproved'] and not p['publishApproved'] and not p['ownerApproved'] for p in out['candidates']))
  self.assertEqual(out['candidates'][0]['evidence']['kind'],'method')
  self.assertEqual(saved['revision'],1)
 def test_bad_shortlist_without_evidence_or_duplicate_ids_is_rejected(self):
  bad=self.sample();bad['editorialShortlist']['candidates'][0]['evidence']['quote']=''
  with self.assertRaises(drafts.MarketingDraftError):
   drafts.normalise_document(bad)
  bad=self.sample();bad['editorialShortlist']['candidates'][1]['id']='craft'
  with self.assertRaises(drafts.MarketingDraftError):
   drafts.normalise_document(bad)
 def test_a_research_failure_can_store_zero_concepts_without_fake_creatives(self):
  d=document();d['editorialShortlist']={'status':'blocked_insufficient_unique_brand_evidence','candidates':[]}
  got=drafts.normalise_document(d)
  self.assertEqual(got['editorialShortlist']['candidates'],[])
  self.assertFalse(got['editorialShortlist']['canGenerateAutomatically'])
