"""Real FFmpeg smoke tests for persistent worker dispatch and private R2 uploads."""
import os
import shutil
import subprocess
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

from business_montage_ledger import claim,lookup

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER="qa-account"
SID="a"*32
KEY=f"business/sources/{ORG}/{SID}.mp4"
SCENES=[
 {"source_id":SID,"key":KEY,"start_s":0,"end_s":6},
 {"source_id":SID,"key":KEY,"start_s":7,"end_s":13},
]
BRAND={"name":"Example Media","primary_color":"#141414",
       "secondary_color":"#FFFFFF","font_style":"modern","default_cta":"Book now"}

class FakeR2:
    def __init__(self,source):
        self.objects={KEY:Path(source).read_bytes()}
        self.puts=[]
    def head_object(self,Bucket,Key):
        return {"ContentLength":len(self.objects[Key]),"ETag":'"qa-etag-v1"'}
    def download_file(self,bucket,key,destination):
        Path(destination).write_bytes(self.objects[key])
    def upload_file(self,source,bucket,key,ExtraArgs):
        self.puts.append((key,ExtraArgs))
        self.objects[key]=Path(source).read_bytes()

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"FFmpeg required")
class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp=tempfile.TemporaryDirectory(prefix="clippr-runner-source-")
        cls.addClassCleanup(temp.cleanup)
        cls.source=Path(temp.name)/"qa.mp4"
        subprocess.run([
            "ffmpeg","-hide_banner","-loglevel","error","-y",
            "-f","lavfi","-i","testsrc2=size=180x320:rate=12:duration=14",
            "-c:v","libx264","-preset","ultrafast",str(cls.source)
        ],check=True,timeout=40,capture_output=True)

    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="clippr-runner-")
        self.addCleanup(temp.cleanup)
        self.path=str(Path(temp.name)/"jobs.db")
        self.env=patch.dict(os.environ,{"CLIPPR_BUSINESS_MONTAGE_DB":self.path})
        self.env.start();self.addCleanup(self.env.stop)
        self.r2=FakeR2(self.source)
        self.storage=runner.Storage(env={"R2_BUCKET":"sandbox"},client=self.r2)

    def admit(self):
        captured=[{**row,"etag":'"qa-etag-v1"',
                   "size":len(self.r2.objects[KEY])} for row in SCENES]
        return claim(OWNER,ORG,"brand-v1",captured,path=self.path,
                     brand_snapshot=BRAND,render_brand_id="brand")

    def test_separate_worker_recovers_queued_job_and_renders_private_media(self):
        item=self.admit()
        result=runner.once(self.storage,"worker-one",path=self.path)
        self.assertEqual(result,item["id"])
        saved=lookup(OWNER,item["id"],path=self.path)
        self.assertEqual(saved["status"],"done")
        self.assertEqual(saved["phase"],"finished")
        expected=f"business/montages/{OWNER}/{item['id']}.mp4"
        self.assertEqual(saved["output_key"],expected)
        self.assertGreater(len(self.r2.objects[expected]),1500)
        self.assertEqual(len(self.r2.puts),1)
        self.assertEqual(self.r2.puts[0][1]["ContentType"],"video/mp4")
        self.assertIsNone(runner.once(self.storage,"worker-two",path=self.path))

    def test_replaced_same_size_source_is_never_rendered(self):
        item=self.admit()
        original=self.r2.head_object
        def changed_head(Bucket,Key):
            response=original(Bucket=Bucket,Key=Key)
            if Key==KEY:return {**response,"ETag":'"different-etag"'}
            return response
        self.r2.head_object=changed_head
        runner.once(self.storage,"worker-one",path=self.path)
        self.assertEqual(lookup(OWNER,item["id"],path=self.path)["status"],"error")
        self.assertEqual(self.r2.puts,[])

    def test_source_changed_mid_download_rejected(self):
        item=self.admit()
        first=self.r2.head_object
        calls=[0]
        def change_after_first_head(Bucket,Key):
            response=first(Bucket=Bucket,Key=Key)
            if Key==KEY:
                calls[0]+=1
                if calls[0]>=3:
                    return {**response,"ETag":'"changed-during-download"'}
            return response
        self.r2.head_object=change_after_first_head
        runner.once(self.storage,"worker-one",path=self.path)
        self.assertEqual(lookup(OWNER,item["id"],path=self.path)["status"],"error")
        self.assertEqual(self.r2.puts,[])

    def test_incomplete_object_is_never_marked_ready(self):
        item=self.admit()
        original=self.r2.download_file
        self.r2.download_file=lambda bucket,key,destination:Path(destination).write_bytes(b"bad")
        runner.once(self.storage,"worker-one",path=self.path)
        self.assertEqual(lookup(OWNER,item["id"],path=self.path)["status"],"error")
        self.assertEqual(self.r2.puts,[])
        self.r2.download_file=original

    def test_upload_size_verification_denies_false_completion(self):
        original_head=self.r2.head_object
        def bad_head(Bucket,Key):
            if Key.startswith("business/montages/"):
                return {"ContentLength":0}
            return original_head(Bucket=Bucket,Key=Key)
        self.r2.head_object=bad_head
        item=self.admit()
        runner.once(self.storage,"worker-one",path=self.path)
        self.assertEqual(lookup(OWNER,item["id"],path=self.path)["status"],"error")
        self.assertEqual(len(self.r2.puts),1)

    def test_scoped_private_outputs_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"output.mp4"
            source.write_bytes(b"x"*2000)
            for key in ("exports/public.mp4","business/sources/abc.mp4",
                        "business/montages/private.mp4",
                        "business/montages/user/id.mov"):
                with self.subTest(key=key),self.assertRaises(ValueError):
                    self.storage.upload_to_r2(source,key)
            self.assertEqual(self.r2.puts,[])

    def test_missing_credentials_and_flag_disabled_are_safe(self):
        with self.assertRaises(runner.WorkerConfigurationError):
            runner.Storage(env={"R2_BUCKET":"sandbox"})
        with patch.dict(os.environ,{"CLIPPR_BUSINESS_MONTAGE_WORKER":"0"}):
            with self.assertRaises(runner.WorkerConfigurationError):
                runner.run_forever(storage=self.storage)

if __name__=="__main__":unittest.main()
