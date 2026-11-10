"""Real multi-source FFmpeg montage smoke tests: audio + silent, aspect, Brand Kit."""
import shutil,subprocess,tempfile,unittest
from pathlib import Path
from business_montage import build_montage,validate_segments,MontageError

BRAND={"name":"Clippr Coffee","primary_color":"#111111",
       "secondary_color":"#FFFFFF","default_cta":"Discover our menu",
       "font_style":"modern"}

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"FFmpeg required")
class MontageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="biz-montage-test-")
        cls.folder=Path(cls.tmp.name)
        cls.landscape=cls.folder/"landscape.mp4"
        cls.portrait=cls.folder/"portrait.mp4"
        for path,size,audio in [(cls.landscape,"320x180",True),(cls.portrait,"180x320",False)]:
            args=["ffmpeg","-hide_banner","-loglevel","error","-y",
                  "-f","lavfi","-i",f"testsrc2=size={size}:rate=15:duration=5"]
            if audio:
                args+=["-f","lavfi","-i","sine=frequency=450:sample_rate=48000:duration=5"]
            args+=["-c:v","libx264","-preset","ultrafast"]
            if audio:args+=["-c:a","aac"]
            args.append(str(path))
            subprocess.run(args,check=True,timeout=40,capture_output=True)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_montage_handles_silent_and_audio_sources_and_brand(self):
        result=build_montage([
            {"path":str(self.landscape),"start_s":0,"end_s":4},
            {"path":str(self.portrait),"start_s":0,"end_s":4}
        ],self.folder/"branded.mp4",brand=BRAND,width=360,height=640,timeout_per_clip=65)
        self.assertEqual(result["scene_count"],2)
        self.assertGreater(result["duration_s"],7)
        self.assertEqual(result["width"],360)
        output=subprocess.run(["ffprobe","-v","error","-show_entries",
                               "stream=codec_type","-of","csv=p=0",result["path"]],
                              capture_output=True,text=True,check=True)
        self.assertIn("video",output.stdout)
        self.assertIn("audio",output.stdout)

    def test_invalid_timings_not_accepted(self):
        cases=[[{"path":str(self.landscape),"start_s":0,"end_s":4}],
               [{"path":str(self.landscape),"start_s":0,"end_s":4},
                {"path":str(self.portrait),"start_s":0,"end_s":99}]]
        with self.assertRaises(MontageError):
            validate_segments(cases[0])
        with self.assertRaises(MontageError):
            build_montage(cases[1],self.folder/"invalid.mp4")
        self.assertFalse((self.folder/"invalid.mp4").exists())

    def test_per_scene_horizontal_framing_is_bounded(self):
        windows=[{"path":str(self.landscape),"start_s":0,"end_s":4,"focus_x":0},
                 {"path":str(self.portrait),"start_s":0,"end_s":4,"focus_x":1}]
        result=build_montage(windows,self.folder/"framed.mp4",width=360,height=640)
        self.assertGreater(result["duration_s"],7)
        for bad in (-0.1,1.01,float("nan"),"0.5",True):
            windows[0]["focus_x"]=bad
            with self.assertRaises(MontageError):validate_segments(windows)

    def test_source_is_never_overwritten(self):
        with self.assertRaises(MontageError):
            build_montage([
                {"path":str(self.landscape),"start_s":0,"end_s":4},
                {"path":str(self.portrait),"start_s":0,"end_s":4}
            ],self.landscape)
if __name__=="__main__":unittest.main()
