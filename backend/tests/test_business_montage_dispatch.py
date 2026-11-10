"""Durable montage execution across requests, server restarts and worker leases."""
import os
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from business_montage_ledger import claim,claim_next,heartbeat,lookup,update,MontageLimit

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER="user-A"
SID="c"*32
KEY=f"business/sources/{ORG}/{SID}.mp4"
SCENES=[{"source_id":SID,"key":KEY,"start_s":0,"end_s":6},
        {"source_id":SID,"key":KEY,"start_s":7,"end_s":13}]
BRAND={"name":"Clippr Brand","primary_color":"#121212",
       "secondary_color":"#FFFFFF","font_style":"modern"}

class LedgerTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="clippr-durable-montage-")
        self.addCleanup(tmp.cleanup)
        self.path=str(Path(tmp.name)/"ledger.db")

    def enqueue(self,owner=OWNER,brand=None):
        return claim(owner,ORG,"brand:approved-revision",SCENES,
                     brand_snapshot=brand or BRAND,render_brand_id="brand",
                     path=self.path)

    def test_job_is_durable_and_claimed_after_api_restart(self):
        request=self.enqueue()
        self.assertEqual(request["status"],"queued")
        runner=claim_next("worker-A",path=self.path)
        self.assertEqual(runner["id"],request["id"])
        self.assertEqual(runner["payload"]["scenes"],SCENES)
        self.assertEqual(runner["payload"]["brand"],BRAND)
        self.assertEqual(runner["payload"]["brand_id"],"brand")
        self.assertIsNone(claim_next("worker-B",path=self.path))
        self.assertEqual(lookup(OWNER,runner["id"],path=self.path)["status"],"running")

    def test_stale_worker_token_cannot_write_or_complete(self):
        request=self.enqueue()
        item=claim_next("worker-A",path=self.path)
        self.assertFalse(heartbeat(OWNER,request["id"],"rendering",path=self.path))
        self.assertFalse(heartbeat(OWNER,request["id"],"rendering",
                                   lease_token="not-the-token",path=self.path))
        self.assertFalse(update(OWNER,request["id"],"done",key="unsafe.mp4",path=self.path))
        self.assertTrue(heartbeat(OWNER,request["id"],"rendering",
                                  lease_token=item["lease_token"],path=self.path))
        self.assertTrue(update(OWNER,request["id"],"done",
                               key=f"business/montages/{OWNER}/{request['id']}.mp4",
                               lease_token=item["lease_token"],path=self.path))
        self.assertFalse(update(OWNER,request["id"],"error",error="late",
                                lease_token=item["lease_token"],path=self.path))
        self.assertEqual(lookup(OWNER,request["id"],path=self.path)["status"],"done")

    def test_dead_worker_reported_interrupted_no_replay_or_extra_render(self):
        start=1800000000
        pending=claim(OWNER,ORG,"brand",SCENES,brand_snapshot=BRAND,
                      render_brand_id="brand",path=self.path,now=start)
        item=claim_next("worker-A",path=self.path,now=start+1)
        old=lookup(OWNER,pending["id"],path=self.path,
                   now=start+4*60)
        self.assertEqual(old["status"],"interrupted")
        self.assertFalse(heartbeat(OWNER,pending["id"],"uploading",
                    lease_token=item["lease_token"],path=self.path))
        self.assertIsNone(claim_next("worker-B",path=self.path,now=start+4*60))
        again=claim(OWNER,ORG,"brand",SCENES,brand_snapshot=BRAND,
                    render_brand_id="brand",path=self.path,now=start+4*60)
        self.assertEqual(again["status"],"interrupted")
        self.assertTrue(again["replayed"])

    def test_simultaneous_worker_claims_are_at_most_once(self):
        self.enqueue()
        start=threading.Barrier(9)
        def run(i):
            start.wait(timeout=8)
            return claim_next("worker-"+str(i),path=self.path)
        with ThreadPoolExecutor(max_workers=9) as pool:
            jobs=list(pool.map(run,range(9)))
        admitted=[j for j in jobs if j]
        self.assertEqual(len(admitted),1)
        self.assertEqual(admitted[0]["owner"],OWNER)

    def test_payload_is_unchanged_when_replayed(self):
        original=self.enqueue()
        replay=self.enqueue(brand={"name":"Different artwork"})
        self.assertEqual(original["id"],replay["id"])
        self.assertTrue(replay["replayed"])
        claimed=claim_next("worker-A",path=self.path)
        self.assertEqual(claimed["payload"]["brand"]["name"],"Clippr Brand")

    def test_previous_schema_upgrades_without_losing_queued_records(self):
        import sqlite3
        db=sqlite3.connect(self.path)
        db.execute("""CREATE TABLE montage_jobs(
          id TEXT PRIMARY KEY,owner TEXT NOT NULL,organisation TEXT NOT NULL,
          digest TEXT NOT NULL,status TEXT NOT NULL,source_json TEXT NOT NULL,
          output_key TEXT,error_code TEXT,created REAL NOT NULL,updated REAL NOT NULL,
          UNIQUE(owner,digest))""")
        db.commit();db.close()
        item=self.enqueue()
        claimed=claim_next("worker-A",path=self.path)
        self.assertEqual(item["id"],claimed["id"])

if __name__=="__main__":unittest.main()
