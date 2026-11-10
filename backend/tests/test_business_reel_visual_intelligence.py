"""Synthetic videos only: explicit acknowledgement this is not semantic accuracy proof."""
import hashlib,subprocess,tempfile,unittest
from pathlib import Path
import business_reel_visual_intelligence as intelligence

class ReelVisualIntelligenceTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory(prefix='clippr-vision-fixture-')
  self.addCleanup(temp.cleanup)
  self.root=Path(temp.name)
 def create(self,name,expression):
  f=self.root/(name+'.mp4')
  subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i',expression,
   '-t','5','-c:v','libx264','-preset','ultrafast','-crf','30','-pix_fmt','yuv420p',str(f)],
   check=True,capture_output=True,timeout=30)
  return f
 def test_real_decoded_frames_spread_across_timeline_and_no_auto_acceptance(self):
  f=self.create('motion','testsrc2=size=720x1280:rate=12')
  report=intelligence.cheap_scan(f,expected_duration=5)
  self.assertEqual(report['stage'],'awaiting_visual_semantics')
  self.assertTrue(report['technicalMotionPass'])
  self.assertGreaterEqual(len(report['frameSamples']),5)
  self.assertGreater(report['frameSamples'][-1]['timeSeconds']-report['frameSamples'][0]['timeSeconds'],3.5)
  self.assertTrue(all(len(x['sha256'])==64 for x in report['frameSamples']))
  self.assertFalse(report['automaticVisualApproval'])
  self.assertFalse(report['published'])
 def test_near_black_movie_rejected_before_expensive_vision(self):
  f=self.create('black','color=c=black:size=720x1280:rate=12')
  calls=[]
  r=intelligence.run_staged_review(f,expected_duration=5,expected_brand='Example',vision_adapter=lambda *a:calls.append(a))
  self.assertEqual(r['finalDisposition'],'technical_rejected')
  self.assertEqual(r['visionCalls'],0)
  self.assertEqual(calls,[])
 def test_late_frozen_segment_detected_after_moving_opening(self):
  file=self.root/'moving-then-frozen.mp4'
  cmd=['ffmpeg','-y','-nostdin','-v','error','-f','lavfi','-t','1.6',
   '-i','testsrc2=size=720x1280:rate=12','-f','lavfi','-t','3.4',
   '-i','color=c=gray:size=720x1280:rate=12',
   '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
   '-map','[v]','-c:v','libx264','-preset','ultrafast',str(file)]
  subprocess.run(cmd,check=True,capture_output=True,timeout=40)
  result=intelligence.cheap_scan(file,expected_duration=5)
  self.assertEqual(result['stage'],'technical_rejected')
  self.assertTrue(any(x in result['issues'] for x in ('sustained_frozen_video_segment','static_or_insufficient_motion')))
  self.assertFalse(result['visualStageAllowed'])
 def test_default_does_not_call_vision_or_invent_hands_faces_or_food_certification(self):
  f=self.create('motion','testsrc2=size=720x1280:rate=12')
  report=intelligence.run_staged_review(f,expected_duration=5,expected_brand='Berenjak')
  self.assertEqual(report['finalDisposition'],'awaiting_semantic_visual_review')
  self.assertIsNone(report['visual'])
  self.assertEqual(report['visionCalls'],0)
 def test_advanced_adapter_needs_separate_approval_even_when_technically_healthy(self):
  f=self.create('motion','testsrc2=size=720x1280:rate=12')
  calls=[]
  def expensive(*a):
   calls.append(1);raise Exception('should not be called')
  report=intelligence.run_staged_review(f,expected_duration=5,expected_brand='Berenjak',vision_adapter=expensive,paid_vision_approved=False)
  self.assertEqual(report['finalDisposition'],'awaiting_paid_vision_approval')
  self.assertEqual(calls,[])
 def test_high_confidence_warped_hand_finding_forces_rejection_not_free_retry(self):
  f=self.create('motion','testsrc2=size=720x1280:rate=12')
  scanned=intelligence.cheap_scan(f,expected_duration=5)
  evidence={'videoSha256':scanned['videoSha256'],'model':'offline_vision_fixture',
   'findings':[{'category':'hands','severity':'critical','confidence':.99,
    'timeSeconds':scanned['frameSamples'][3]['timeSeconds'],
    'explanation':'Five fused fingers are clearly visible while gripping the skewer.'}]}
  outcome=intelligence.validate_vision_result(evidence,sample_report=scanned,expected_brand='Fixture Restaurant')
  self.assertEqual(outcome['stage'],'auto_rejected')
  self.assertEqual(len(outcome['criticalFindings']),1)
  self.assertFalse(outcome['automaticVisualApproval'])
 def test_aesthetic_uncertainty_needs_creative_director(self):
  f=self.create('motion','testsrc2=size=720x1280:rate=12')
  scanned=intelligence.cheap_scan(f,expected_duration=5)
  result=intelligence.validate_vision_result({'videoSha256':scanned['videoSha256'],
   'model':'offline_vision_fixture',
   'findings':[{'category':'cinematography','severity':'major','confidence':.8,
    'timeSeconds':scanned['frameSamples'][2]['timeSeconds'],
    'explanation':'The subject framing is visually weak and the pace feels repetitive.'}]},
    sample_report=scanned,expected_brand='Example')
  self.assertEqual(result['stage'],'awaiting_internal_creative_review')
  self.assertEqual(len(result['needsHumanAttention']),1)
 def test_bad_source_hash_time_and_model_are_rejected(self):
  f=self.create('motion','testsrc2=size=720x1280:rate=12')
  scanned=intelligence.cheap_scan(f,expected_duration=5)
  bad={'videoSha256':'a'*64,'model':'offline_vision_fixture','findings':[]}
  with self.assertRaises(intelligence.VisualReviewError):
   intelligence.validate_vision_result(bad,sample_report=scanned,expected_brand='Example')
  bad['videoSha256']=scanned['videoSha256'];bad['model']='unapproved_unknown_backend'
  with self.assertRaises(intelligence.VisualReviewError):
   intelligence.validate_vision_result(bad,sample_report=scanned,expected_brand='Example')
 def test_provider_failure_never_mints_approval_or_retries(self):
  f=self.create('motion','testsrc2=size=720x1280:rate=12')
  def broken(*args):raise TimeoutError('Provider unavailable')
  r=intelligence.run_staged_review(f,expected_duration=5,expected_brand='Example',
   vision_adapter=broken,paid_vision_approved=True)
  self.assertEqual(r['finalDisposition'],'vision_unavailable_needs_manual_review')
  self.assertEqual(r['visionCalls'],1)
  self.assertIsNone(r['visual'])
