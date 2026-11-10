"""Real ffmpeg video, not mocked success booleans."""
import subprocess,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
import business_video_motion_qc as qc
class MotionTechnicalTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
 def video(self,content,path):
  subprocess.run(['ffmpeg','-v','error','-nostdin','-y',
   '-f','lavfi','-i',content,'-t','5','-c:v','libx264','-preset','ultrafast',
   '-pix_fmt','yuv420p',str(path)],capture_output=True,timeout=40,check=True)
 def test_real_moving_source_passes_technical_motion_not_creative_approval(self):
  f=self.root/'motion.mp4';self.video('testsrc2=size=720x1280:rate=12',f)
  got=qc.review(f)
  self.assertTrue(got['technicalMotionPass'])
  self.assertFalse(got['approved']);self.assertFalse(got['physicalMotionAuthenticityVerified'])
 def test_frozen_portrait_is_rejected(self):
  f=self.root/'static.mp4';self.video('color=c=gray:size=720x1280:rate=12',f)
  got=qc.review(f)
  self.assertFalse(got['technicalMotionPass'])
  self.assertEqual(got['qualityStatus'],'rejected_static_or_insufficient_motion')
 def test_moving_but_nearly_black_video_still_fails_auto_qc(self):
  for i in range(5):
   image=Image.new('RGB',(720,1280),(0,0,0))
   draw=ImageDraw.Draw(image)
   x=30+145*i;draw.rectangle((x,420,x+115,535),fill='white')
   image.save(self.root/('slide-%02d.png'%i))
  file=self.root/'too-dark.mp4'
  subprocess.run(['ffmpeg','-y','-nostdin','-v','error','-framerate','1','-i',str(self.root/'slide-%02d.png'),
   '-vf','fps=12','-t','5','-c:v','libx264','-preset','ultrafast',str(file)],check=True,capture_output=True,timeout=25)
  status=qc.review(file)
  self.assertFalse(status['technicalMotionPass'])
  self.assertIn('near_black_or_blown_out_frames',status['automaticQcIssues'])
  self.assertEqual(status['qualityStatus'],'rejected_exposure_or_black_frames')
 def test_landscape_is_rejected(self):
  f=self.root/'wide.mp4';self.video('testsrc2=size=1280x720:rate=12',f)
  with self.assertRaises(qc.MotionReviewError):qc.review(f)
 def test_rejects_symlinks_and_missing(self):
  target=self.root/'missing.mp4'
  with self.assertRaises(qc.MotionReviewError):qc.review(target)
  symlink=self.root/'link.mp4';symlink.symlink_to(target)
  with self.assertRaises(qc.MotionReviewError):qc.review(symlink)
