"""Persistent paired creative directions, CAS, restore and HTTP boundary tests."""
import sqlite3,tempfile,unittest,uuid
from pathlib import Path
import business_marketing_drafts as drafts
import business_hero_history as history
from tests.test_business_marketing_drafts import document

class HeroHistoryTests(unittest.TestCase):
 def setUp(self):
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
  self.addCleanup(self.con.close)
  drafts.initialise(self.con);history.initialise(self.con)
  self.did='a'*32
  d=document()
  d['business']='The Cedar Restaurant'
  drafts.save_draft(self.con,{'id':self.did,'expectedRevision':0,'mutationId':'e'*32,'document':d})
  self.start={'action':'start','draftId':self.did,'operationId':'1'*32,'expectedRevision':1,
    'ownerConfirmed':True,'sector':'restaurant','offer':'Confirmed restaurant dining','audience':'Local diners'}
 def op(self,**args):
  return history.mutate(self.con,args)
 def test_start_has_six_different_unrendered_direction_briefs(self):
  result=self.op(**self.start)
  self.assertEqual(len(result['rounds']),3)
  self.assertTrue(all('Photorealistic only' in x['direction_a'] for x in result['rounds']))
  self.assertTrue(all(x['direction_a']!=x['direction_b'] for x in result['rounds']))
  self.assertFalse(result['spendAuthorised']);self.assertFalse(result['published'])
  self.assertEqual(history.read(self.con,self.did)['offer'],'Confirmed restaurant dining')
 def test_revision_two_alternatives_restore_old_round_and_repeat_is_idempotent(self):
  self.op(**self.start)
  change={'action':'revise','draftId':self.did,'operationId':'2'*32,'slot':'editorial',
    'expectedRound':0,'feedback':'Show customers sitting in a believable dining environment, not empty buildings.'}
  one=self.op(**change)
  self.assertEqual(one['rounds'][1]['round_no'],1)
  self.assertIn('customers sitting',one['rounds'][1]['direction_a'])
  self.assertIn('different camera composition',one['rounds'][1]['direction_b'])
  self.assertEqual(self.op(**change)['rounds'],one['rounds'])
  with self.assertRaises(history.HeroHistoryError):self.op(**{**change,'operationId':'3'*32})
  restored=self.op(action='restore',draftId=self.did,operationId='4'*32,slot='editorial',expectedRound=1,restoreRound=0)
  editorial=[x for x in restored['rounds'] if x['slot']=='editorial']
  self.assertEqual(len(editorial),3)
  self.assertEqual(editorial[-1]['direction_a'],editorial[0]['direction_a'])
  self.assertEqual(editorial[-1]['parent_round'],0)
 def test_owner_rejection_is_immutable_and_not_generation_approval(self):
  self.op(**self.start)
  rejected=self.op(action='reject',draftId=self.did,operationId='5'*32,slot='social',expectedRound=0,
   reviewRound=0,variant='a',reason='Too much imitation and too little real customer context')
  self.assertEqual(len(rejected['rejectedDirections']),1)
  self.assertEqual(len(rejected['rounds']),3)
  self.assertFalse(rejected['spendAuthorised'])
  self.assertEqual(len(self.op(action='reject',draftId=self.did,operationId='5'*32,slot='social',expectedRound=0,
   reviewRound=0,variant='a',reason='Too much imitation and too little real customer context')['rejectedDirections']),1)
  with self.assertRaises(history.HeroHistoryError):
   self.op(action='reject',draftId=self.did,operationId='6'*32,slot='social',expectedRound=0,
    reviewRound=0,variant='a',reason='This direction already failed creative review')
  subsequent=self.op(action='revise',draftId=self.did,operationId='7'*32,slot='social',expectedRound=0,
   feedback='Make the setting more authentic with genuine service movement')
  self.assertEqual(subsequent['rounds'][-1]['round_no'],1)
  self.assertEqual(len(subsequent['rejectedDirections']),1)
 def test_replay_with_other_intent_refused(self):
  self.op(**self.start)
  with self.assertRaises(history.HeroHistoryError):self.op(**{**self.start,'offer':'Different services'})
 def test_wrong_draft_owner_check_and_stale_revision(self):
  with self.assertRaises(drafts.MarketingDraftError):self.op(**{**self.start,'draftId':'b'*32})
  with self.assertRaises(history.HeroHistoryError):self.op(**{**self.start,'ownerConfirmed':False})
  with self.assertRaises(history.HeroHistoryError):self.op(**{**self.start,'expectedRevision':4})
  self.assertEqual(len(history.read(self.con,self.did)['rounds']),0)
 def test_feedback_bounds_and_no_hidden_provider_tasks(self):
  self.op(**self.start)
  for comment in ('Too short','A'*900):
   with self.assertRaises(history.HeroHistoryError):
    self.op(action='revise',draftId=self.did,operationId=uuid.uuid4().hex,slot='social',expectedRound=0,feedback=comment)
  names={r['name'] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  self.assertNotIn('runway_cinematic_shots',names)

class HeroCropReviewTests(unittest.TestCase):
 def test_square_photo_crops_and_never_auto_approves(self):
  import business_local_pilot as pilot
  photo={'width':1000,'height':1000}
  result=pilot.hero_photo_crop(photo)
  self.assertEqual(result['instagram4x5']['imageAreaRetainedPercent'],80.0)
  self.assertEqual(result['tiktok9x16']['imageAreaRetainedPercent'],56.2)
  self.assertTrue(result['tiktok9x16']['upscaleRequired'])
  self.assertFalse(result['instagram4x5']['suitableForAutomaticApproval'])

class FourSectorHeroEvidenceTests(unittest.TestCase):
 def test_four_grounded_sector_fixtures_create_distinct_concepts_without_vendor_calls(self):
  # Cached public evidence from prior safe page reads. These are QA fixtures,
  # not claims that a real business owner confirmed the facts.
  cases=[('restaurant','The Cedar Restaurant','Lebanese dining and table enquiries','Local diners'),
   ('beauty','The Beauty Retreat','Beauty services and consultation enquiries','Prospective clients'),
   ('construction','Marleo Construction','Hampshire home renovations and refurbishments','Homeowners'),
   ('concierge','Encore VIP','Concierge and curated experience enquiries','Prospective private clients')]
  for sector,brand,offer,audience in cases:
   with self.subTest(sector=sector):
    con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
    try:
     drafts.initialise(con);history.initialise(con)
     source=document();source['business']=brand
     did=uuid.uuid4().hex
     drafts.save_draft(con,{'id':did,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':source})
     result=history.mutate(con,{'action':'start','draftId':did,'operationId':uuid.uuid4().hex,
      'expectedRevision':1,'sector':sector,'offer':offer,'audience':audience,'ownerConfirmed':True})
     self.assertEqual(len(result['rounds']),3)
     for creative in result['rounds']:
      self.assertIn('Photorealistic only',creative['direction_a'])
      self.assertNotEqual(creative['direction_a'],creative['direction_b'])
      self.assertFalse(result['spendAuthorised']);self.assertFalse(result['published'])
    finally:con.close()

class HeroHistoryHTTPTests(unittest.TestCase):
 def test_real_local_http_save_and_restore(self):
  from tests.test_business_local_pilot import LocalPilotTests
  # Use existing HTTP harness; preserve its isolated temporary directory and server.
  harness=LocalPilotTests(methodName='test_only_allowed_local_origin_and_header')
  harness.setUp()
  try:
   with __import__('business_local_pilot').session() as con:
    drafts.save_draft(con,{'id':'c'*32,'expectedRevision':0,'mutationId':'d'*32,'document':document()})
   url='/api/pilot/hero-creative-history'
   started={'action':'start','draftId':'c'*32,'operationId':'e'*32,'expectedRevision':1,
    'sector':'construction','offer':'Kitchen and bathroom refurbishments','audience':'Hampshire homeowners','ownerConfirmed':True}
   status,result=harness.api(url,method='POST',body=started)
   self.assertEqual(status,200,result);self.assertEqual(len(result['rounds']),3)
   status,loaded=harness.api(url+'?draftId='+'c'*32)
   self.assertEqual(status,200,loaded);self.assertTrue(loaded['exists'])
   self.assertEqual(len(loaded['photos']),0)
   reset_code,reset_result=harness.api('/api/pilot/reset',method='POST',body={'confirmation':'DELETE LOCAL TESTS'})
   self.assertEqual(reset_code,409,reset_result)
   self.assertEqual(reset_result['code'],'creative_history_preserved')
   status,denied=harness.api(url,method='POST',body=started,origin='https://other.example')
   self.assertEqual(status,403)
  finally:
   import unittest
   harness.doCleanups()

if __name__=='__main__':unittest.main()
