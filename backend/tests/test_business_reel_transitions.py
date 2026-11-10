"""Actual local render verification; colours are synthetic test signals, not client footage."""
import json,subprocess,tempfile,unittest
from pathlib import Path
import business_reel_workbench as reel

class ReelTransitionTests(unittest.TestCase):
 def test_soft_transitions_change_boundary_frames_without_changing_runtime(self):
  with tempfile.TemporaryDirectory(prefix='clippr-transition-fixture-') as folder:
   root=Path(folder);sources=[]
   for slot,color in [('hook','red'),('craft','blue')]:
    path=root/(slot+'.mp4')
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
     f'color={color}:size=360x640:rate=24:duration=2','-c:v','libx264','-preset','ultrafast',
     '-pix_fmt','yuv420p',str(path)],check=True,capture_output=True,timeout=20)
    sources.append((slot,path,2))
   cut=reel._render_cut(sources,root/'cut.mp4')
   fade=reel._render_cut(sources,root/'fade.mp4',soft_transitions=True)
   def brightness(file,seconds):
    data=subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(seconds),'-i',str(file),
     '-frames:v','1','-vf','scale=8:8','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],
     check=True,capture_output=True,timeout=15).stdout
    self.assertEqual(len(data),192)
    return sum(data)/len(data)
   self.assertLess(brightness(fade,1.95),brightness(cut,1.95)*.35)
   self.assertAlmostEqual(brightness(fade,1),brightness(cut,1),delta=2)
   for path in (cut,fade):
    data=json.loads(subprocess.run(['ffprobe','-v','error','-show_entries',
     'format=duration:stream=width,height','-of','json',str(path)],
     check=True,capture_output=True,text=True,timeout=15).stdout)
    self.assertAlmostEqual(float(data['format']['duration']),4,delta=.05)
    self.assertEqual((data['streams'][0]['width'],data['streams'][0]['height']),(720,1280))
