import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from business_visual import windows_from_cuts,scan_visual_scenes,VisualSourceError

class VisualSelectionTests(unittest.TestCase):
    def test_windows_are_clamped_non_overlapping_and_review_only(self):
        result=windows_from_cuts([1,6,6.1,17,29,53,1000],58,limit=12)
        self.assertTrue(result)
        for i,item in enumerate(result):
            self.assertGreater(item["timestamp_end"],item["timestamp_start"])
            self.assertLessEqual(item["timestamp_end"],58)
            self.assertTrue(item["review_required"])
            self.assertEqual(item["score"],0)
            if i:self.assertGreaterEqual(item["timestamp_start"],result[i-1]["timestamp_end"])
    def test_long_source_candidates_cover_entire_timeline(self):
        cuts=list(range(6,432,6))
        selections=windows_from_cuts(cuts,437,limit=12)
        self.assertEqual(len(selections),12)
        self.assertLess(selections[0]["timestamp_start"],10)
        self.assertGreater(selections[-1]["timestamp_start"],400)
        self.assertTrue(all(a["timestamp_end"]<=b["timestamp_start"]
                            for a,b in zip(selections,selections[1:])))

    def test_default_long_video_produces_more_than_a_dozen_candidates(self):
        out=windows_from_cuts(list(range(6,432,6)),437)
        self.assertGreater(len(out),12)
        self.assertLessEqual(len(out),36)
        self.assertGreater(out[-1]["timestamp_start"],400)

    def test_invalid_durations_rejected(self):
        self.assertEqual(windows_from_cuts([],float("nan")),[])
        self.assertEqual(windows_from_cuts([],0),[])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"ffmpeg required")
    def test_actual_silent_colour_cut_footage_yields_scene_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/"cuts.mp4"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                            "-f","lavfi","-i","color=red:size=320x180:rate=12:duration=7",
                            "-f","lavfi","-i","color=blue:size=320x180:rate=12:duration=7",
                            "-f","lavfi","-i","color=green:size=320x180:rate=12:duration=7",
                            "-filter_complex","[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                            "-map","[v]","-c:v","libx264","-preset","veryfast",str(f)],
                           check=True,timeout=30,stdout=subprocess.DEVNULL)
            output=scan_visual_scenes(f)
            self.assertEqual(output["method"],"ffmpeg_scene_boundaries")
            self.assertFalse(output["visual_ai_used"])
            self.assertGreaterEqual(len(output["scenes"]),1)
            self.assertLessEqual(output["duration_s"],23)
            self.assertTrue(all(x["review_required"] for x in output["scenes"]))
if __name__=="__main__":unittest.main()
