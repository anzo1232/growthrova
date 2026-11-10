"""Durable montage metering, duplicate protection and compute safety caps.

No financial charge is created by this ledger. It tracks completed output
seconds once per montage and caps processing admission under concurrent load.
"""
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from business_montage_ledger import (
    claim,update,usage_summary,MontageLimit,MAX_USER_OUTPUT_SECONDS_DAY,
    MAX_GLOBAL_OUTPUT_SECONDS_DAY,MAX_PROCESSING
)
ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SID="b"*32
def scenes(length):
    assert length>=6 and length<=60
    return [{"source_id":SID,"key":f"business/sources/{ORG}/{SID}.mp4",
             "start_s":0,"end_s":length/2},
            {"source_id":SID,"key":f"business/sources/{ORG}/{SID}.mp4",
             "start_s":30,"end_s":30+length/2}]

class UsageTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db=str(Path(tmp.name)/"ledger.db")
    def admit(self,owner="user",length=30,version="v1",now=1800000000):
        return claim(owner,ORG,version,scenes(length),path=self.db,now=now)
    def settle(self,owner,job,now=1800000000):
        started=update(owner,job["id"],"running",path=self.db,now=now)
        assert started
        return update(owner,job["id"],"done",
                      key=f"business/montages/{owner}/{job['id']}.mp4",
                      path=self.db,now=now+1)
    def test_completed_output_counted_once_on_same_transaction(self):
        item=self.admit()
        self.assertTrue(self.settle("user",item))
        self.assertFalse(update("user",item["id"],"done",key="duplicate.mp4",
                                path=self.db))
        metered=usage_summary("user",path=self.db,now=1800000001)
        self.assertEqual(metered["completed_outputs"],1)
        self.assertEqual(metered["output_seconds"],30.0)
        self.assertEqual(metered["reserved_seconds_24h"],30.0)
        self.assertEqual(usage_summary("other",path=self.db)["completed_outputs"],0)
    def test_wrong_customer_or_unscoped_output_key_can_never_be_settled(self):
        item=self.admit()
        self.assertTrue(update("user",item["id"],"running",path=self.db))
        for key in ("exports/free.mp4","business/montages/other/foreign.mp4",
                    "business/montages/user/fake.mp4"):
            with self.assertRaises(ValueError):
                update("user",item["id"],"done",key=key,path=self.db)
        self.assertEqual(usage_summary("user",path=self.db)["completed_outputs"],0)

    def test_failed_jobs_consume_admission_but_never_count_completed_usage(self):
        item=self.admit()
        self.assertTrue(update("user",item["id"],"error",error="render_fail",
                               path=self.db,now=1800000001))
        stats=usage_summary("user",path=self.db,now=1800000001)
        self.assertEqual(stats["completed_outputs"],0)
        self.assertEqual(stats["output_seconds"],0)
        self.assertEqual(stats["reserved_seconds_24h"],30)
    def test_invalid_render_completion_rolls_back_without_false_usage_event(self):
        item=self.admit()
        self.assertTrue(update("user",item["id"],"running",path=self.db))
        with self.assertRaisesRegex(ValueError,"verified owner-scoped"):
            update("user",item["id"],"done",key=None,path=self.db)
        self.assertEqual(usage_summary("user",path=self.db)["completed_outputs"],0)
        self.assertTrue(update("user",item["id"],"done",
            key=f"business/montages/user/{item['id']}.mp4",path=self.db))
    def test_each_user_has_duration_quota_even_if_many_jobs_short(self):
        for i in range(3):
            job=self.admit(version="version"+str(i),length=60)
            self.assertTrue(self.settle("user",job))
        self.assertLessEqual(usage_summary("user",path=self.db,now=1800000001)["reserved_seconds_24h"],
                             MAX_USER_OUTPUT_SECONDS_DAY)
        with self.assertRaises(MontageLimit):
            self.admit(version="fourth",length=60)
    def test_quota_is_atomic_under_multiple_workers(self):
        count=8
        gate=Barrier(count)
        def run(i):
            gate.wait(timeout=8)
            try:
                return self.admit(owner="user"+str(i),version="v1",length=60)
            except MontageLimit:return None
        with ThreadPoolExecutor(max_workers=count) as pool:
            results=list(pool.map(run,range(count)))
        self.assertEqual(sum(x is not None for x in results),MAX_PROCESSING)
    def test_montage_scene_durations_must_be_finite_positive_and_bounded(self):
        for samples in (
          [{"source_id":SID,"start_s":0,"end_s":99}]*2,
          [{"source_id":SID,"start_s":0,"end_s":float("nan")}]*2,
          [{"source_id":SID,"start_s":3,"end_s":2}]*2,
        ):
            with self.subTest(samples=samples),self.assertRaises(ValueError):
                claim("user",ORG,"v",samples,path=self.db)
    def test_existing_ledger_is_migrated_and_usage_is_queryable(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("""CREATE TABLE montage_jobs(
                id TEXT PRIMARY KEY,owner TEXT,organisation TEXT,digest TEXT,
                status TEXT,source_json TEXT,output_key TEXT,error_code TEXT,
                created REAL,updated REAL,UNIQUE(owner,digest))""")
        item=self.admit()
        self.assertTrue(self.settle("user",item))
        self.assertEqual(usage_summary("user",path=self.db)["completed_outputs"],1)
if __name__=="__main__":unittest.main()
