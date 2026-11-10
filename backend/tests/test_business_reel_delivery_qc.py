"""Final deliverable checks use actual synthetic 9:16 MP4s, not a dummy success flag."""
from pathlib import Path
import tempfile,subprocess,unittest
import business_reel_delivery_qc as qc
class CompleteReelQC(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
  self.root=Path(t.name)
  self.sample=self.root/'real-test-video.mp4'
  subprocess.run(['ffmpeg','-nostdin','-v','error','-y',
   '-f','lavfi','-i','testsrc2=size=720x1280:rate=12',
   '-f','lavfi','-i','sine=frequency=440:sample_rate=44100:duration=5',
   '-t','5','-c:v','libx264','-preset','ultrafast','-crf','34',
   '-c:a','aac','-b:a','160k',str(self.sample)],check=True,capture_output=True,timeout=35)
  self.attested={'brandAndCtaVerified':True,'claimsChecked':True,'allMediaRightsReviewed':True,
   'textBoxes':[{'subject':'brand','x':85,'y':450,'width':520,'height':76},
    {'subject':'cta','x':100,'y':650,'width':490,'height':50},
    {'subject':'contact','x':100,'y':880,'width':450,'height':35}]}
 def test_audio_crop_brand_claims_checks_then_human_signoff_required(self):
  report=qc.verify(self.sample,expected_duration=5,approval=self.attested,has_audio_evidence=True)
  self.assertTrue(report['technicalReelPass'])
  self.assertTrue(report['audioPresent'])
  self.assertFalse(report['automaticallyApproved'])
  self.assertTrue(report['semanticVisualReviewPending'])
  self.assertGreaterEqual(report['frameCount'],5)
 def test_no_soundtrack_rights_cannot_pass_even_with_audible_audio(self):
  with self.assertRaises(qc.DeliveryError):
   qc.verify(self.sample,expected_duration=5,approval=self.attested,has_audio_evidence=False)
 def test_missing_brand_and_claims_block_audible_video(self):
  for key in ('brandAndCtaVerified','claimsChecked','allMediaRightsReviewed'):
   with self.subTest(key=key):
    attested={**self.attested,key:False}
    with self.assertRaises(qc.DeliveryError):
     qc.verify(self.sample,expected_duration=5,approval=attested,has_audio_evidence=True)
 def test_platform_ui_safe_area_rejects_overflow(self):
  changed={**self.attested,'textBoxes':[{**x} for x in self.attested['textBoxes']]}
  changed['textBoxes'][0]['y']=1020
  with self.assertRaises(qc.DeliveryError):
   qc.verify(self.sample,expected_duration=5,approval=changed,has_audio_evidence=True)
 def test_audio_stream_required_not_just_owner_attestation(self):
  silent=self.root/'silent.mp4'
  subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(self.sample),
    '-an','-c:v','copy',str(silent)],check=True,capture_output=True,timeout=20)
  with self.assertRaises(qc.DeliveryError):
   qc.verify(silent,expected_duration=5,approval=self.attested,has_audio_evidence=True)
