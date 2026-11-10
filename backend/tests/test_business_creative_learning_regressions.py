"""Offline regression evidence, not tests of AI quality or real marketing success."""
import json,math,subprocess,tempfile,unittest
from pathlib import Path
from PIL import Image
import business_creative_preflight as gate
import business_niche_strategy as strategy
import business_visual_review_queue as queue

class PromptSafetyRegressionTests(unittest.TestCase):
 def inspect(self,text):
  return gate.inspect('roofing',text,evidence='The website offers roof repairs and local gutter services.',shot_purpose='Show a homeowner the cause of their leak',estimated_credits=96,cap=96)
 def test_no_people_in_background_does_not_allow_foreground_roofer(self):
  result=self.inspect('A realistic roofer repairs a clay tiled roof on camera with gloves, natural movement and coherent overlapping tiles. No people in the background.')
  self.assertFalse(result['ready'])
 def test_explicit_no_workers_does_not_allow_hands_elsewhere(self):
  result=self.inspect('No workers. A pair of gloved hands places tiles on a roof with a natural camera push and detailed realistic building materials and daylight.')
  self.assertFalse(result['ready'])
 def test_no_people_but_an_engineer_is_not_safe(self):
  result=self.inspect('No people, but an engineer points to a crack in a roof tile as the camera moves smoothly past the chimney showing the repair process.')
  self.assertFalse(result['ready'])
 def test_before_after_prohibition_is_not_a_fabricated_claim(self):
  result=self.inspect('Photorealistic empty roofline with natural rain moving on accurately overlapped clay tiles and matching lead flashing. No people, no hands, no before-after claims. Illustrative only.')
  self.assertTrue(result['ready'],result)
 def test_actual_before_after_claim_is_blocked(self):
  result=self.inspect('Show before and after roof repairs as the real company completed project, with a detailed camera move over correctly overlapping tiles. No people.')
  self.assertFalse(result['ready'])

class NicheBoundaryRegressionTests(unittest.TestCase):
 def test_proofreaders_are_not_roofers(self):
  p=strategy.profile('Acme',['Proofreading and manuscript corrections for independent writers.'])
  self.assertNotEqual(p['primaryTrait'],'local_service')
  self.assertNotIn('physical_accuracy',p['risks'])
 def test_barbers_are_not_hospitality(self):
  p=strategy.profile('Acme',['Barber appointments for haircuts and beard grooming.'])
  self.assertNotIn('hospitality',p['secondaryTraits'])
 def test_appliance_workshop_is_not_software_or_training(self):
  p=strategy.profile('Acme',['Appliance repairs carried out at our local workshop.'])
  self.assertEqual(p['primaryTrait'],'local_service')
  self.assertNotIn('software',p['secondaryTraits'])
  self.assertNotIn('training',p['secondaryTraits'])
 def test_lawn_service_is_not_legal(self):
  p=strategy.profile('Acme',['Lawn mowing and garden care for domestic properties.'])
  self.assertNotIn('regulated_or_high_trust_claims',p['risks'])
 def test_business_name_alone_cannot_claim_an_offering(self):
  p=strategy.profile('Roof Shop Medical Software Academy',['Handcrafted paper sculptures for display and gifting.'])
  self.assertEqual(p['primaryTrait'],'other')
 def test_unknown_niche_is_research_required(self):
  p=strategy.profile('Acme',['Specialist acoustic voicing for historic pipe organs.'])
  self.assertTrue(p.get('researchRequired'))
 def test_plan_has_reusable_lessons_not_auto_approval(self):
  b=strategy.blueprint(strategy.profile('Acme',['Local roof repairs and gutter repairs for homeowners.']))
  self.assertIn('learningPolicy',b)
  self.assertFalse(b['canSpend']);self.assertFalse(b['canPublish'])

class CompleteReviewEvidenceTests(unittest.TestCase):
 def test_twelve_frames_visible_and_hash_bound(self):
  with tempfile.TemporaryDirectory(prefix='clippr-contact-regression-') as folder:
   root=Path(folder);src=root/'test.mp4'
   subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=180x320:rate=30','-t','2','-c:v','libx264','-preset','ultrafast',str(src)],check=True,capture_output=True,timeout=20)
   result=queue.generate(src,root/'review',samples=12)
   with Image.open(result['contactSheet']) as im:
    self.assertEqual(im.height,3*520,'All three rows must actually be visible')
   self.assertEqual(len(result.get('frames',[])),12)
   self.assertTrue(all(len(f.get('sha256',''))==64 for f in result['frames']))
   self.assertGreater(result['frames'][-1]['timeSeconds'],1.8)
   self.assertFalse(result['automaticCreativeAcceptance'])
   self.assertFalse(result['approved'])

class DirectSubmissionRegressionTests(unittest.TestCase):
 def test_direct_cinematic_path_cannot_bypass_worker_preflight(self):
  import sqlite3,uuid
  from unittest.mock import patch
  import business_cinematic_video as cinema
  import business_marketing_drafts as drafts
  from tests.test_business_marketing_drafts import document
  con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
  drafts.initialise(con);cinema.initialise(con)
  doc=document();doc['business']='Roof test';doc['observedFacts']=['Local roof repairs and guttering for homeowners.']
  did=uuid.uuid4().hex
  drafts.save_draft(con,{'id':did,'mutationId':uuid.uuid4().hex,'expectedRevision':0,'document':doc})
  class Fake:
   calls=0
   def balance(self):self.calls+=1;return 500
   def submit_text_video(self,payload):self.calls+=1;return {'id':str(uuid.uuid4())}
  fake=Fake()
  prompt='A realistic roofer repairs clay tiles on a roof with gloved hands. The camera moves continuously around the chimney with realistic proportions. No people in the background.'
  with patch.dict(cinema.SHOTS,{'regression_worker':('roofing',prompt)}):
   with self.assertRaises(cinema.CinematicError):
    cinema.submit(con,did,1,'regression_worker',root='/tmp/unused-no-paid-test',client=fake,max_credits=96)
  self.assertEqual(fake.calls,0)
  self.assertEqual(con.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0],0)
