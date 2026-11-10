"""Real FFmpeg scene scans use the exact owner-confirmed R2 object version."""
import os
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from business_sources import reserve_source,confirm_source
from business_visual_jobs import reserve_job,scan_job,find_job

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER="test-owner"

class FakeStorage:
    def __init__(self,source,etag):
        self.bytes=Path(source).read_bytes()
        self.etag=etag
        self.downloads=0
        self.on_download=None
    def head_object(self,Bucket,Key):
        return {"ContentLength":len(self.bytes),"ETag":self.etag}
    def download_file(self,bucket,key,filename):
        self.downloads+=1
        Path(filename).write_bytes(self.bytes)
        if self.on_download:self.on_download()

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"ffmpeg required")
class SourceIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp=tempfile.TemporaryDirectory(prefix="clippr-source-integrity-")
        cls.addClassCleanup(tmp.cleanup)
        cls.video=Path(tmp.name)/"test.mp4"
        subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                        "-f","lavfi","-i","testsrc2=size=320x180:rate=12:duration=12",
                        "-c:v","libx264","-preset","ultrafast",str(cls.video)],
                       check=True,timeout=40,capture_output=True)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source_db=str(Path(self.tmp.name)/"sources.db")
        self.visual_db=str(Path(self.tmp.name)/"scans.db")
        self.env=patch.dict(os.environ,{"CLIPPR_BUSINESS_SOURCES_DB":self.source_db,
                                        "CLIPPR_BUSINESS_VISUAL_DB":self.visual_db})
        self.env.start();self.addCleanup(self.env.stop)
        self.r2=FakeStorage(self.video,'"confirmed-v1"')
        self.deps=types.SimpleNamespace(get_r2=lambda:self.r2,r2_bucket="fake-bucket")
        record=reserve_source(OWNER,ORG,"test.mp4","video/mp4",len(self.r2.bytes),
                              "a"*32,path=self.source_db)
        self.key=record["source_key"]
        confirm_source(self.key,OWNER,len(self.r2.bytes),"video/mp4",
                       actual_etag=self.r2.etag,path=self.source_db)
        self.job=reserve_job(OWNER,ORG,record["source_id"],self.key,path=self.visual_db)
    def run_scan(self):
        scan_job(self.deps,self.job["job_id"],OWNER,self.key,path=self.visual_db)
        return find_job(OWNER,self.job["job_id"],path=self.visual_db)
    def test_confirmed_object_can_be_scanned_and_saved(self):
        done=self.run_scan()
        self.assertEqual(done["status"],"done")
        self.assertTrue(done["result"]["scenes"])
        self.assertEqual(self.r2.downloads,1)
    def test_replacement_same_size_rejected_before_bandwidth(self):
        self.r2.etag='"new-object-same-length"'
        result=self.run_scan()
        self.assertEqual(result["status"],"error")
        self.assertEqual(self.r2.downloads,0)
    def test_version_changed_while_downloading_rejected_before_scoring(self):
        self.r2.on_download=lambda:setattr(self.r2,"etag",'"overwritten-mid-read"')
        result=self.run_scan()
        self.assertEqual(result["status"],"error")
        self.assertEqual(self.r2.downloads,1)

if __name__=="__main__":unittest.main()
