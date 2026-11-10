"""Restaurant-first short video proposals: verified state, no paid generation."""
from __future__ import annotations
import sqlite3,unittest,uuid,urllib.parse
import business_marketing_drafts as drafts
import business_hero_history as history
import business_social_video_plan as videos
from tests.test_business_marketing_drafts import document

class VideoPlanTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
  drafts.initialise(self.db);history.initialise(self.db);videos.initialise(self.db)
  self.did='c'*32
  doc=document();doc['business']='The Cedar Restaurant'
  drafts.save_draft(self.db,{'id':self.did,'mutationId':'a'*32,'expectedRevision':0,'document':doc})
  self.hero=history.mutate(self.db,{'action':'start','draftId':self.did,'operationId':'b'*32,'expectedRevision':1,
    'sector':'restaurant','offer':'Confirmed restaurant dining','audience':'Local people looking for dinner','ownerConfirmed':True})
 def test_one_nocharge_vertical_video_proposal_from_current_saved_direction(self):
  proposal=videos.propose(self.db,{'draftId':self.did,'heroRound':0,'variant':'a'})
  self.assertEqual(proposal['creditsEstimated'],60)
  self.assertEqual(proposal['ratio'],'720:1280')
  self.assertEqual(len(proposal['storyboard']),3)
  self.assertEqual([b['time'] for b in proposal['storyboard']],['0–1s','1–3s','3–5s'])
  self.assertIn('First second',proposal['prompt'])
  self.assertIn('natural',proposal['prompt'].lower())
  self.assertTrue(proposal['status'].startswith('awaiting_exact_'))
  self.assertFalse(proposal['spendAuthorised']);self.assertFalse(proposal['generated']);self.assertFalse(proposal['publishApproved'])
  self.assertEqual(videos.propose(self.db,{'draftId':self.did,'heroRound':0,'variant':'a'})['id'],proposal['id'])
  self.assertEqual(len(videos.list_plans(self.db,self.did)),1)
 def test_rejected_or_stale_creatives_fail_closed(self):
  history.mutate(self.db,{'action':'reject','draftId':self.did,'operationId':'d'*32,
      'slot':'social','expectedRound':0,'reviewRound':0,'variant':'a',
      'reason':'Too static and not representative of a real restaurant experience'})
  with self.assertRaises(videos.VideoPlanError):videos.propose(self.db,{'draftId':self.did,'heroRound':0,'variant':'a'})
  history.mutate(self.db,{'action':'revise','draftId':self.did,'operationId':'e'*32,
      'slot':'social','expectedRound':0,'feedback':'Show convincing human motion within the first second'})
  with self.assertRaises(videos.VideoPlanError):videos.propose(self.db,{'draftId':self.did,'heroRound':0,'variant':'b'})
  new=videos.propose(self.db,{'draftId':self.did,'heroRound':1,'variant':'b'})
  self.assertEqual(new['heroRound'],1)
 def test_campaign_edit_invalidates_new_video_preflight(self):
  doc=document();doc['business']='An Edited Restaurant'
  drafts.save_draft(self.db,{'id':self.did,'mutationId':'1'*32,'expectedRevision':1,'document':doc})
  with self.assertRaises(videos.VideoPlanError) as caught:videos.propose(self.db,{'draftId':self.did,'heroRound':0,'variant':'a'})
  self.assertEqual(caught.exception.code,'stale_business_facts')
 def test_other_sectors_are_not_generic_reused_restaurant_photography(self):
  shots=[videos.DIRECTIONS[s][0] for s in ('restaurant','beauty','construction','concierge')]
  self.assertEqual(len(set(shots)),4)
  for shot in shots:self.assertIn('First second:',shot)
 def test_invalid_payloads_no_write_and_no_video_submissions(self):
  for bad in ({'draftId':self.did,'heroRound':'0','variant':'a'},
              {'draftId':self.did,'heroRound':0,'variant':'c'},
              {'draftId':self.did,'heroRound':0,'variant':'a','approved':True}):
   with self.assertRaises(videos.VideoPlanError):videos.propose(self.db,bad)
  self.assertEqual(len(videos.list_plans(self.db,self.did)),0)
  self.assertFalse(videos.current_quote()['purchaseAuthorised'])

class VideoPlanHTTPTests(unittest.TestCase):
 def test_local_endpoint_enforces_auth_and_records_only_proposal(self):
  from tests.test_business_local_pilot import LocalPilotTests
  import business_local_pilot as pilot
  helper=LocalPilotTests(methodName='test_only_allowed_local_origin_and_header');helper.setUp()
  try:
   did='f'*32
   with pilot.session() as db:
    doc=document()
    drafts.save_draft(db,{'id':did,'mutationId':'b'*32,'expectedRevision':0,'document':doc})
    history.mutate(db,{'action':'start','draftId':did,'operationId':'c'*32,
     'expectedRevision':1,'sector':'restaurant','offer':'Restaurant dining','audience':'Local diners',
     'ownerConfirmed':True})
   path='/api/pilot/social-video-proposals'
   status,p=helper.api(path,method='POST',body={'draftId':did,'heroRound':0,'variant':'a'})
   self.assertEqual(status,200,p);self.assertEqual(p['creditsEstimated'],60)
   status,out=helper.api(path+'?draftId='+did)
   self.assertEqual(status,200,out);self.assertEqual(len(out['proposals']),1)
   status,denied=helper.api(path,method='POST',body={'draftId':did,'heroRound':0,'variant':'b'},origin='https://malicious.example')
   self.assertEqual(status,403)
   with pilot.session() as db:
    self.assertEqual(db.execute('SELECT COUNT(*) FROM runway_image_jobs').fetchone()[0],0)
    self.assertEqual(db.execute('SELECT COUNT(*) FROM runway_video_jobs').fetchone()[0],0)
  finally:helper.doCleanups()
if __name__=='__main__':unittest.main()
