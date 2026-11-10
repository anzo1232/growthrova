"""Durable visual job recovery, idempotency and cross-account isolation."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from business_visual_jobs import (reserve_job,find_job,_finish,_stage,
    TIMEOUT_SECONDS,QUEUE_TIMEOUT_SECONDS,MAX_PENDING_JOBS,VisualQueueFull)

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SRC="a"*32
KEY=f"business/sources/{ORG}/{SRC}.mp4"

class VisualJobPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=str(Path(self.tmp.name)/"jobs.db")

    def test_parallel_admission_reuses_job_and_denies_foreign_user(self):
        a=reserve_job("A",ORG,SRC,KEY,path=self.db,now=1000)
        b=reserve_job("A",ORG,SRC,KEY,path=self.db,now=1000)
        self.assertFalse(a["replayed"])
        self.assertTrue(b["replayed"])
        self.assertEqual(a["job_id"],b["job_id"])
        self.assertIsNone(find_job("B",a["job_id"],path=self.db,now=1002))

    def test_worker_result_persists_across_connections(self):
        job=reserve_job("A",ORG,SRC,KEY,path=self.db,now=1000)
        result={"scenes":[{"timestamp_start":1,"timestamp_end":15,"title":"Visual scene 1"}],"duration_s":90}
        _finish(job["job_id"],"A","done",result,self.db)
        found=find_job("A",job["job_id"],path=self.db)
        self.assertEqual(found["status"],"done")
        self.assertEqual(found["result"],result)

    def test_restart_or_stall_reports_interrupted_not_fake_progress(self):
        start=1000
        job=reserve_job("A",ORG,SRC,KEY,path=self.db,now=start)
        later=find_job("A",job["job_id"],path=self.db,now=start+QUEUE_TIMEOUT_SECONDS+10)
        self.assertEqual(later["status"],"interrupted")
        replay=reserve_job("A",ORG,SRC,KEY,path=self.db,now=start+QUEUE_TIMEOUT_SECONDS+12)
        self.assertEqual(replay["status"],"interrupted")
        self.assertTrue(replay["replayed"])
    def test_active_job_heartbeat_prevents_false_interrupt(self):
        start=1000
        job=reserve_job("A",ORG,SRC,KEY,path=self.db,now=start)
        _stage(job["job_id"],"A","running",self.db,now=start+10)
        _stage(job["job_id"],"A","scanning",self.db,now=start+110)
        alive=find_job("A",job["job_id"],path=self.db,now=start+180)
        self.assertEqual(alive["status"],"scanning")
        interrupted=find_job("A",job["job_id"],path=self.db,now=start+240)
        self.assertEqual(interrupted["status"],"interrupted")

    def test_queue_capacity_rejects_new_work_without_creating_job(self):
        for i in range(MAX_PENDING_JOBS):
            reserve_job("user"+str(i),ORG,str(i).zfill(32),KEY,
                        path=self.db,now=1000)
        with self.assertRaises(VisualQueueFull):
            reserve_job("extra",ORG,"x"*32,KEY,path=self.db,now=1001)
        self.assertIsNone(find_job("extra",self._new_id("extra","x"*32),path=self.db,now=1001))

    def _new_id(self,owner,source):
        import hashlib
        return hashlib.sha256((owner+":"+source).encode()).hexdigest()[:32]

    def test_terminal_result_is_never_overwritten_by_late_status_update(self):
        job=reserve_job("A",ORG,SRC,KEY,path=self.db,now=1000)
        _finish(job["job_id"],"A","done",{"scenes":[],"duration_s":12},self.db)
        _stage(job["job_id"],"A","running",self.db)
        after=find_job("A",job["job_id"],path=self.db)
        self.assertEqual(after["status"],"done")

if __name__=="__main__": unittest.main()
