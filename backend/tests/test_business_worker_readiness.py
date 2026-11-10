"""Validate production worker boot readiness before any paid processing."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

with patch.dict(sys.modules,{
    "flask":types.SimpleNamespace(request=None,jsonify=lambda value:value)
}):
    import business_montage_worker as runner

class R2:
    def __init__(self):
        self.reads=[]
        self.should_fail=False
    def head_bucket(self,Bucket):
        self.reads.append(Bucket)
        if self.should_fail:raise ConnectionError("R2 unavailable")
        return {}
    def upload_file(self,*args,**kw):
        raise AssertionError("Readiness must never modify R2")

class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger=str(Path(self.tmp.name)/"jobs.db")
        self.r2=R2()
        self.storage=runner.Storage(env={"R2_BUCKET":"test-only-bucket"},client=self.r2)
    def ready(self,**kwargs):
        return runner.check_worker_readiness(self.storage,
           ledger_path=self.ledger,**kwargs)
    def test_successful_readonly_preflight(self):
        outcome=self.ready(min_free_mb=0)
        self.assertTrue(outcome["ready"])
        self.assertEqual(self.r2.reads,["test-only-bucket"])
        self.assertTrue(Path(self.ledger).exists())
    def test_missing_ffmpeg_blocks_worker_before_r2(self):
        original=runner.shutil.which
        def missing(program):
            return None if program=="ffmpeg" else original(program)
        with patch.object(runner.shutil,"which",side_effect=missing):
            with self.assertRaisesRegex(runner.WorkerConfigurationError,"ffmpeg"):
                self.ready(min_free_mb=0)
        self.assertEqual(self.r2.reads,[])
    def test_missing_pillow_blocks_before_accepting_jobs(self):
        actual=runner.importlib.import_module
        def missing(name):
            if name=="PIL.Image":raise ModuleNotFoundError("Pillow missing")
            return actual(name)
        with patch.object(runner.importlib,"import_module",side_effect=missing):
            with self.assertRaisesRegex(runner.WorkerConfigurationError,"Pillow"):
                self.ready(min_free_mb=0)
        self.assertEqual(self.r2.reads,[])
    def test_missing_brand_font_blocks_before_r2(self):
        with patch.object(runner,"FONT_REL",Path(self.tmp.name)/"absent.ttf"):
            with self.assertRaisesRegex(runner.WorkerConfigurationError,"font"):
                self.ready(min_free_mb=0)
        self.assertEqual(self.r2.reads,[])
    def test_bad_r2_access_blocks_worker_without_rendering(self):
        self.r2.should_fail=True
        with self.assertRaisesRegex(runner.WorkerConfigurationError,"R2 bucket"):
            self.ready(min_free_mb=0)
        self.assertEqual(self.r2.reads,["test-only-bucket"])
    def test_low_disk_prevents_media_download(self):
        free=types.SimpleNamespace(total=100,used=99,free=200*1024*1024)
        with patch.object(runner.shutil,"disk_usage",return_value=free):
            with self.assertRaisesRegex(runner.WorkerConfigurationError,
                                        "Insufficient free disk"):
                self.ready(min_free_mb=500)
        self.assertEqual(self.r2.reads,[])
    def test_readiness_feature_flag_does_not_start_background_work(self):
        # The separate --check-config path performs read-only checks even while
        # runtime feature flag remains OFF. No queued job can be processed.
        with patch.dict(os.environ,{"CLIPPR_BUSINESS_MONTAGE_WORKER":"0"}):
            with self.assertRaises(runner.WorkerConfigurationError):
                runner.run_forever(storage=self.storage)

if __name__=="__main__":unittest.main()
