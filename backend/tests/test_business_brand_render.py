"""Real FFmpeg smoke tests and security tests for Clippr Business brand render."""
from __future__ import annotations
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from business_brand_render import (
    BrandRenderError, validate_brand, contrast_ratio, compose_brand_overlay, render_branded_clip,
)

BRAND={
    "name":"Medical Wellness Academy",
    "font_style":"modern",
    "primary_color":"#161616",
    "secondary_color":"#FFFFFF",
    "default_cta":"Learn about our courses",
}


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg and FFprobe are required")
class BrandRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp=tempfile.TemporaryDirectory(prefix="clippr-business-render-tests-")
        cls.root=Path(cls._temp.name)
        cls.source=cls.root/"sample.mp4"
        # Authorised synthetic footage only (no customer uploads / external media).
        subprocess.run(
            ["ffmpeg","-hide_banner","-loglevel","error","-y",
             "-f","lavfi","-i","testsrc2=size=360x640:rate=15",
             "-f","lavfi","-i","sine=frequency=500:sample_rate=22050",
             "-t","0.85","-c:v","libx264","-preset","ultrafast","-c:a","aac",
             str(cls.source)],check=True,timeout=60,
             stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
        )

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def test_owner_brand_contrast_and_color_validation(self):
        self.assertGreater(contrast_ratio("#111111","#FFFFFF"),16)
        with self.assertRaises(BrandRenderError):
            validate_brand({**BRAND,"secondary_color":"#181818"})
        with self.assertRaises(BrandRenderError):
            validate_brand({**BRAND,"primary_color":"red;rm"})
        with self.assertRaises(BrandRenderError):
            validate_brand({**BRAND,"font_style":"shell"})

    def test_four_creative_directions_render_playable_audio_video(self):
        for style in ("modern","classic","bold","minimal"):
            with self.subTest(style=style):
                output=self.root/("test-"+style+".mp4")
                meta=render_branded_clip(self.source,output,{**BRAND,"font_style":style},
                                         timeout=80)
                self.assertEqual(meta["style"],style)
                self.assertTrue(output.exists())
                result=subprocess.run(["ffprobe","-v","error","-show_entries","stream=codec_type",
                                       "-of","csv=p=0",str(output)],capture_output=True,
                                      text=True,timeout=10,check=True)
                self.assertIn("video",result.stdout)
                self.assertIn("audio",result.stdout)
                self.assertEqual(meta["width"],360)
                self.assertEqual(meta["height"],640)

    def test_logo_must_be_in_owner_approved_asset_directory(self):
        approved=self.root/"approved"
        approved.mkdir()
        outside=self.root/"external.png"
        outside.write_bytes(b"not-real-image")
        with self.assertRaises(BrandRenderError):
            render_branded_clip(self.source,self.root/"bad-logo.mp4",BRAND,
                                logo_path=outside,logo_root=approved)
        self.assertFalse((self.root/"bad-logo.mp4").exists())
        with self.assertRaises(BrandRenderError):
            render_branded_clip(self.source,self.root/"bad-logo2.mp4",BRAND,
                                logo_path=outside)

    def test_source_can_never_be_overwritten(self):
        before=self.source.stat().st_size
        with self.assertRaises(BrandRenderError):
            render_branded_clip(self.source,self.source,BRAND)
        self.assertEqual(self.source.stat().st_size,before)

    def test_untrusted_text_is_rasterised_not_added_to_ffmpeg_arguments(self):
        dangerous={**BRAND,"name":"Brand:hello\n,drawtext=inject",
                   "default_cta":"Book now; delete records?"}
        img=compose_brand_overlay(360,640,dangerous)
        self.assertEqual(img.mode,"RGBA")
        self.assertEqual(img.size,(360,640))
        self.assertEqual(img.getpixel((180,320))[3],0)


if __name__=="__main__":
    unittest.main()
