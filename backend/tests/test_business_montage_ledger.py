import tempfile,unittest
from pathlib import Path
from business_montage_ledger import (claim,lookup,update,heartbeat,MontageLimit,
    LIMIT_PER_USER_DAY,MAX_PROCESSING,QUEUE_STALE_SECONDS,RUNNING_STALE_SECONDS)
ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SOURCE="b"*32
WIN=[{"source_id":SOURCE,"key":"business/sources/"+ORG+"/"+SOURCE+".mp4",
      "start_s":0,"end_s":6},
     {"source_id":SOURCE,"key":"business/sources/"+ORG+"/"+SOURCE+".mp4",
      "start_s":6,"end_s":12}]
class MontageLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=str(Path(self.tmp.name)/"jobs.db")
    def reserve(self,owner="owner",windows=WIN,now=1800000000):
        return claim(owner,ORG,"brand",windows,path=self.db,now=now)
    def test_single_request_replay_and_owner_isolation(self):
        a=self.reserve()
        b=self.reserve()
        self.assertFalse(a["replayed"]);self.assertTrue(b["replayed"])
        self.assertEqual(a["id"],b["id"])
        self.assertIsNone(lookup("attacker",a["id"],path=self.db))
    def test_successful_terminal_status_is_not_overwritten(self):
        job=self.reserve()
        update("owner",job["id"],"running",path=self.db)
        update("owner",job["id"],"done",key="business/montages/owner/"+job["id"]+".mp4",path=self.db)
        update("owner",job["id"],"error",error="late",path=self.db)
        self.assertEqual(lookup("owner",job["id"],path=self.db)["status"],"done")
    def test_global_concurrency_limit(self):
        for i in range(MAX_PROCESSING):
            self.reserve(owner="owner"+str(i))
        with self.assertRaises(MontageLimit):
            self.reserve(owner="another")
    def test_daily_limit(self):
        for i in range(LIMIT_PER_USER_DAY):
            j=self.reserve(windows=[{**WIN[0],"start_s":i},WIN[1]])
            update("owner",j["id"],"running",path=self.db,now=1800000000)
            update("owner",j["id"],"done",key=f"business/montages/owner/{j['id']}.mp4",path=self.db,now=1800000000)
        with self.assertRaises(MontageLimit):
            self.reserve(windows=[{**WIN[0],"start_s":2.8},WIN[1]])
    def test_active_long_render_heartbeat_never_false_interrupted(self):
        now=1800000000
        job=self.reserve(now=now)
        self.assertTrue(update("owner",job["id"],"running",now=now+1,path=self.db))
        for seconds in (70,145,220,300,430,570,880,1100):
            self.assertTrue(heartbeat("owner",job["id"],"rendering",
                                      now=now+seconds,path=self.db))
            item=lookup("owner",job["id"],now=now+seconds+1,path=self.db)
            self.assertEqual(item["status"],"running")
            self.assertEqual(item["phase"],"rendering")
        self.assertTrue(update("owner",job["id"],"done",key=f"business/montages/owner/{job['id']}.mp4",path=self.db,now=now+1101))
        self.assertEqual(lookup("owner",job["id"],now=now+1102,path=self.db)["status"],"done")

    def test_dead_worker_reaped_and_late_result_cannot_reopen(self):
        now=1800000000
        job=self.reserve(now=now)
        self.assertTrue(update("owner",job["id"],"running",now=now+1,path=self.db))
        state=lookup("owner",job["id"],now=now+RUNNING_STALE_SECONDS+8,path=self.db)
        self.assertEqual(state["status"],"interrupted")
        self.assertEqual(state["error_code"],"worker_interrupted")
        self.assertFalse(heartbeat("owner",job["id"],"uploading",
                                   now=now+RUNNING_STALE_SECONDS+9,path=self.db))
        self.assertFalse(update("owner",job["id"],"done",
                                key="business/montages/owner/stale.mp4",
                                path=self.db,now=now+RUNNING_STALE_SECONDS+9))
        self.assertIsNone(lookup("owner",job["id"],path=self.db)["output_key"])
        self.assertTrue(self.reserve(now=now+RUNNING_STALE_SECONDS+10)["replayed"])

    def test_stale_queued_and_running_jobs_separate_thresholds(self):
        now=1800000000
        job=self.reserve(now=now)
        self.assertEqual(lookup("owner",job["id"],now=now+RUNNING_STALE_SECONDS+2,
                                path=self.db)["status"],"queued")
        self.assertEqual(lookup("owner",job["id"],now=now+QUEUE_STALE_SECONDS+2,
                                path=self.db)["status"],"interrupted")
        self.assertFalse(update("owner",job["id"],"running",path=self.db))
    def test_heartbeat_rejects_unauthorised_user_and_invalid_phases(self):
        job=self.reserve()
        self.assertTrue(update("owner",job["id"],"running",path=self.db))
        self.assertFalse(heartbeat("other",job["id"],"rendering",path=self.db))
        with self.assertRaises(ValueError):
            heartbeat("owner",job["id"],"done",path=self.db)
    def test_simultaneous_admission_respects_shared_global_limit(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        total=8
        gate=Barrier(total)
        def submit(index):
            gate.wait(timeout=8)
            try:
                r=self.reserve(owner="load-user-"+str(index))
                return ("admitted",r["id"])
            except MontageLimit:
                return ("limited",index)
        with ThreadPoolExecutor(max_workers=total) as pool:
            results=list(pool.map(submit,range(total)))
        self.assertEqual(sum(x[0]=="admitted" for x in results),MAX_PROCESSING)
        self.assertEqual(sum(x[0]=="limited" for x in results),total-MAX_PROCESSING)

    def test_simultaneous_duplicate_admission_is_exactly_one_job(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        total=8
        gate=Barrier(total)
        def submit(_):
            gate.wait(timeout=8)
            return self.reserve()
        with ThreadPoolExecutor(max_workers=total) as pool:
            items=list(pool.map(submit,range(total)))
        self.assertEqual(len({x["id"] for x in items}),1)
        self.assertEqual(sum(not x["replayed"] for x in items),1)

    def test_phase_schema_upgrades_existing_ledger_without_losing_job(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            db_path=str(Path(tmp)/"legacy.db")
            db=sqlite3.connect(db_path)
            db.execute("""CREATE TABLE montage_jobs (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, organisation TEXT NOT NULL,
              digest TEXT NOT NULL, status TEXT NOT NULL, source_json TEXT NOT NULL,
              output_key TEXT, error_code TEXT, created REAL NOT NULL, updated REAL NOT NULL,
              UNIQUE(owner,digest))""")
            db.commit();db.close()
            created=claim("owner",ORG,"brand",WIN,path=db_path,now=1800000000)
            self.assertEqual(created["phase"],"queued")
            state=lookup("owner",created["id"],now=1800000001,path=db_path)
            self.assertEqual(state["status"],"queued")

if __name__=="__main__":unittest.main()
