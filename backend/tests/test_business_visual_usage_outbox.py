"""Billing safety: source-processing meter candidates are atomic and never charged."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from business_visual_jobs import reserve_job,_finish,usage_candidates,find_job

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SID="b"*32
KEY="business/sources/"+ORG+"/"+SID+".mp4"

class SourceUsageOutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=str(Path(self.tmp.name)/"jobs.db")
    def start(self,owner="owner",source_id=SID):
        return reserve_job(owner,ORG,source_id,KEY,path=self.db)
    def test_completed_source_is_recorded_once_no_stripe_charge(self):
        item=self.start()
        result={"duration_s":145.5,"scenes":[{"timestamp_start":0,"timestamp_end":8}]}
        self.assertTrue(_finish(item["job_id"],"owner","done",result,self.db))
        self.assertFalse(_finish(item["job_id"],"owner","done",result,self.db))
        meter=usage_candidates("owner",path=self.db)
        self.assertFalse(meter["billable"])
        self.assertEqual(len(meter["events"]),1)
        self.assertEqual(meter["events"][0]["processed_seconds"],145.5)
        self.assertEqual(meter["events"][0]["state"],"needs_billing_review")
        self.assertEqual(meter["events"][0]["source_id"],SID)
        self.assertEqual(meter["events"][0]["job_id"],item["job_id"])
    def test_failure_does_not_count_as_completed_work(self):
        item=self.start()
        self.assertTrue(_finish(item["job_id"],"owner","error",{"error":"scan failed"},self.db))
        self.assertFalse(_finish(item["job_id"],"owner","done",
                                 {"duration_s":120,"scenes":[]},self.db))
        self.assertEqual(usage_candidates("owner",path=self.db)["events"],[])
    def test_other_account_cannot_read_meter(self):
        item=self.start()
        _finish(item["job_id"],"owner","done",{"duration_s":48,"scenes":[]},self.db)
        self.assertEqual(usage_candidates("attacker",path=self.db)["events"],[])
    def test_missing_or_corrupt_duration_fails_before_success_record(self):
        for secs in (None,0,float("nan"),float("inf"),601,-8):
            with self.subTest(seconds=secs):
                tmp=tempfile.TemporaryDirectory()
                try:
                    path=str(Path(tmp.name)/"jobs.db")
                    job=reserve_job("owner",ORG,SID,KEY,path=path)
                    with self.assertRaises(ValueError):
                        _finish(job["job_id"],"owner","done",
                                {"scenes":[],"duration_s":secs},path)
                    self.assertEqual(find_job("owner",job["job_id"],path=path)["status"],"queued")
                    self.assertEqual(usage_candidates("owner",path=path)["events"],[])
                finally:tmp.cleanup()
    def test_independent_account_records_remain_separate(self):
        a=self.start("userA","a"*32)
        b=self.start("userB","c"*32)
        _finish(a["job_id"],"userA","done",{"duration_s":60,"scenes":[]},self.db)
        _finish(b["job_id"],"userB","done",{"duration_s":30,"scenes":[]},self.db)
        self.assertEqual(len(usage_candidates("userA",path=self.db)["events"]),1)
        self.assertEqual(len(usage_candidates("userB",path=self.db)["events"]),1)
    def test_outbox_is_created_as_part_of_existing_ledger_upgrade(self):
        item=self.start()
        _finish(item["job_id"],"owner","done",{"duration_s":3,"scenes":[]},self.db)
        self.assertEqual(usage_candidates("owner",path=self.db)["events"][0]["processed_seconds"],3)

if __name__=="__main__":unittest.main()
