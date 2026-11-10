"""Standalone visual worker: real FFmpeg, durable lease, isolation and fail closed."""
import os
import shutil
import subprocess
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from business_sources import reserve_source,confirm_source
from business_visual_jobs import (reserve_job,claim_next_visual,find_job,
                                  _stage,_finish,usage_candidates,TIMEOUT_SECONDS)
import business_visual_worker as worker

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER="isolated-owner"
NONCE="b"*32

class FakeR2:
    def __init__(self,video):
        self.data=Path(video).read_bytes()
        self.etag='"qa-confirmed-etag"'
        self.downloads=0
    def head_object(self,Bucket,Key):
        return {"ContentLength":len(self.data),"ContentType":"video/mp4",
                "ETag":self.etag}
    def download_file(self,bucket,key,destination):
        self.downloads+=1
        Path(destination).write_bytes(self.data)
    def head_bucket(self,Bucket):return {}

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"FFmpeg required")
class VisualWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp=tempfile.TemporaryDirectory(prefix="clippr-visual-worker-fixture-")
        cls.addClassCleanup(temp.cleanup)
        cls.video=Path(temp.name)/"synthetic.mp4"
        subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                        "-f","lavfi","-i","testsrc2=size=320x180:rate=12:duration=12",
                        "-c:v","libx264","-preset","ultrafast",str(cls.video)],
                       check=True,capture_output=True,timeout=35)
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="clippr-visual-worker-test-")
        self.addCleanup(temp.cleanup)
        self.sources=str(Path(temp.name)/"sources.db")
        self.visual=str(Path(temp.name)/"visual.db")
        self.fake=FakeR2(self.video)
        self.store=worker.R2Storage(env={"R2_BUCKET":"fake-bucket"},client=self.fake)
        video=reserve_source(OWNER,ORG,"synthetic.mp4","video/mp4",
                             len(self.fake.data),NONCE,path=self.sources)
        self.key=video["source_key"]
        self.source_id=video["source_id"]
        confirm_source(self.key,OWNER,len(self.fake.data),"video/mp4",
                       actual_etag=self.fake.etag,path=self.sources)
    def enqueue(self):
        return reserve_job(OWNER,ORG,self.source_id,self.key,path=self.visual)
    def runonce(self,identity="qa-worker"):
        return worker.once(self.store,identity,visual_path=self.visual,
                           source_path=self.sources)
    def test_api_queue_survives_restart_worker_scans_real_file(self):
        job=self.enqueue()
        self.assertEqual(job["status"],"queued")
        self.assertEqual(self.runonce(),job["job_id"])
        state=find_job(OWNER,job["job_id"],path=self.visual)
        self.assertEqual(state["status"],"done")
        self.assertGreater(len(state["result"]["scenes"]),0)
        assert state["result"]["duration_s"]>=10
        self.assertEqual(self.fake.downloads,1)
        self.assertEqual(len(usage_candidates(OWNER,path=self.visual)["events"]),1)
        self.assertIsNone(self.runonce("second-worker"))
    def test_worker_queue_cannot_be_claimed_twice(self):
        self.enqueue()
        gate=Barrier(8)
        def task(i):
            gate.wait(timeout=8)
            return claim_next_visual("worker-"+str(i),path=self.visual)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(task,range(8)))
        claimed=[x for x in results if x]
        self.assertEqual(len(claimed),1)
        self.assertEqual(claimed[0]["owner"],OWNER)
    def test_wrong_lease_cannot_mark_scanned_or_mint_billing(self):
        self.enqueue()
        claimed=claim_next_visual("worker-A",path=self.visual)
        self.assertFalse(_stage(claimed["job_id"],OWNER,"scanning",self.visual,
                                 lease_token="wrong"))
        self.assertFalse(_finish(claimed["job_id"],OWNER,"done",
                          {"duration_s":12,"scenes":[]},self.visual,
                          lease_token="wrong"))
        self.assertEqual(usage_candidates(OWNER,path=self.visual)["events"],[])
        self.assertFalse(_finish(claimed["job_id"],OWNER,"done",
                          {"duration_s":12,"scenes":[]},self.visual))
        self.assertTrue(_stage(claimed["job_id"],OWNER,"scanning",self.visual,
                               lease_token=claimed["lease_token"]))
    def test_object_replaced_after_confirmation_fails_without_usage(self):
        job=self.enqueue()
        self.fake.etag='"new-video-same-size"'
        self.runonce()
        self.assertEqual(find_job(OWNER,job["job_id"],path=self.visual)["status"],"error")
        self.assertEqual(self.fake.downloads,0)
        self.assertEqual(usage_candidates(OWNER,path=self.visual)["events"],[])
    def test_stale_completed_job_cannot_reenter_worker(self):
        item=self.enqueue()
        claim=claim_next_visual("worker-A",path=self.visual)
        self.assertTrue(_stage(claim["job_id"],OWNER,"scanning",self.visual,
                                lease_token=claim["lease_token"]))
        self.assertTrue(_finish(claim["job_id"],OWNER,"error",
                               {"error":"simulated crash"},self.visual,
                               lease_token=claim["lease_token"]))
        self.assertIsNone(self.runonce("another-worker"))
        self.assertEqual(self.fake.downloads,0)
    def test_crashed_worker_reaped_without_restart_or_usage(self):
        self.enqueue()
        import time
        base=time.time()
        # Claim near the reservation timestamp; then advance the logical clock
        # without sleeping or touching live service processes.
        claimed=claim_next_visual("worker-A",path=self.visual,now=base)
        stale=find_job(OWNER,claimed["job_id"],path=self.visual,
                       now=base+TIMEOUT_SECONDS+1)
        self.assertEqual(stale["status"],"interrupted")
        self.assertFalse(_stage(claimed["job_id"],OWNER,"finalizing",self.visual,
                                 lease_token=claimed["lease_token"]))
        self.assertFalse(_finish(claimed["job_id"],OWNER,"done",
                                  {"duration_s":12,"scenes":[]},self.visual,
                                  lease_token=claimed["lease_token"]))
        self.assertEqual(usage_candidates(OWNER,path=self.visual)["events"],[])
        self.assertIsNone(claim_next_visual("worker-B",path=self.visual,
                                            now=base+TIMEOUT_SECONDS+2))

    def test_storage_readiness_checks_and_flag_disabled(self):
        self.assertTrue(worker.readiness(self.store,visual_path=self.visual,
                                         source_path=self.sources,min_free_mb=0))
        with patch.dict(os.environ,{"CLIPPR_BUSINESS_VISUAL_WORKER":"0"}):
            with self.assertRaises(worker.WorkerUnavailable):
                worker.run_forever(storage=self.store)

if __name__=="__main__":unittest.main()
