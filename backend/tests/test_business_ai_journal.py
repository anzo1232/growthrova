"""Offline tests for paid Business AI request admission and replay."""
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from business_ai_journal import guarded_generate

BRIEF={"goal":"education","industry":"consulting","brand_name":"Clippr Example",
       "style":"modern","cta":"Find out more","approved_offer":"","audience":""}
CLIPS=[{"timestamp_start":3,"timestamp_end":24,"title":"Why planning matters",
        "score":88,"llm_reason":"Useful explanation"}]
def success(clips,brief):
    return ({clips[0]["index"]:{"headline":"Planning matters",
              "caption":"Why planning matters","why":"Useful explanation",
              "creative_angle":"Education"}},
            {"provider":"deepseek","model":"deepseek-flash",
             "request_count":1,"input_tokens":35,"output_tokens":15})

class GuardedAITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/"business_ai.db")

    def call(self,user="user-one",clips=None,fn=success,day=None,limit=10,global_limit=100):
        return guarded_generate(user,CLIPS if clips is None else clips,BRIEF,
            path=self.path,ai_fn=fn,now=1_800_000_000 if day is None else day,
            per_user_limit=limit,global_limit=global_limit)

    def test_replay_uses_cached_answer_without_another_call(self):
        counts=[]
        def make(*args):
            counts.append(1)
            return success(*args)
        first=self.call(fn=make)
        second=self.call(fn=make)
        self.assertEqual(first["clips"][0]["headline"],"Planning matters")
        self.assertEqual(second["clips"][0]["headline"],"Planning matters")
        self.assertEqual(len(counts),1)

    def test_timeout_response_must_never_be_auto_retried(self):
        calls=[]
        def broken(*args):
            calls.append(1)
            raise TimeoutError("unknown provider delivery")
        first=self.call(fn=broken)
        second=self.call(fn=broken)
        self.assertEqual(len(calls),1)
        self.assertEqual(first["ai"]["status"],"unavailable")
        self.assertEqual(second["ai"]["status"],"unknown")

    def test_per_user_daily_quota(self):
        counts=[]
        def make(*args):
            counts.append(1)
            return success(*args)
        self.call(fn=make,limit=1)
        updated=[{**CLIPS[0],"title":"New material"}]
        second=self.call(clips=updated,fn=make,limit=1)
        self.assertEqual(second["ai"]["status"],"quota_exhausted")
        self.assertEqual(len(counts),1)

    def test_global_daily_quota(self):
        self.call(user="alice",global_limit=1)
        result=self.call(user="bob",global_limit=1)
        self.assertEqual(result["ai"]["status"],"quota_exhausted")

    def test_parallel_same_content_claims_only_one_paid_call(self):
        barrier=threading.Event()
        entered=threading.Event()
        counter=[]
        def slow(*args):
            counter.append(1)
            entered.set()
            barrier.wait(timeout=4)
            return success(*args)
        results=[]
        def submit():
            results.append(self.call(fn=slow))
        t=threading.Thread(target=submit)
        t.start()
        self.assertTrue(entered.wait(timeout=3))
        second=self.call(fn=slow)
        self.assertEqual(second["ai"]["status"],"pending")
        barrier.set()
        t.join(timeout=5)
        self.assertEqual(len(counter),1)
        self.assertEqual(results[0]["ai"]["status"],"ready")

    def test_source_without_clips_never_calls_paid_api(self):
        result=self.call(clips=[],fn=lambda *a: self.fail("must not charge"))
        self.assertEqual(result["ai"]["status"],"no_candidates")

if __name__=="__main__":
    unittest.main()
