"""Offline owner-isolation and multi-source pack route tests."""
from __future__ import annotations
import importlib,os,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from business_visual_jobs import reserve_job,_finish

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ORG2="cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SRC1="a"*32
SRC2="b"*32

class FakeApp:
    def __init__(self):self.routes={}
    def get(self,path):
        def dec(fn):self.routes[path]=fn;return fn
        return dec
    post=get

class VisualRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.req=types.SimpleNamespace(get_json=lambda silent=True:{})
        cls.patch_flask=patch.dict(sys.modules,{
            "flask":types.SimpleNamespace(request=cls.req,jsonify=lambda x:x)
        })
        cls.patch_flask.start()
        cls.addClassCleanup(cls.patch_flask.stop)
        cls.module=importlib.import_module("business_visual_routes")

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{
            "CLIPPR_BUSINESS_VISUAL_DB":self.tmp.name+"/visual.db",
            "CLIPPR_BUSINESS_SOURCES_DB":self.tmp.name+"/sources.db",
            "CLIPPR_BUSINESS_VISUAL_DISPATCH":"1",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.user="owner"
        self.req.get_json=lambda silent=True:{
            "organisation_id":ORG,
            "visual_job_ids":[],
        }
        app=FakeApp()
        deps=types.SimpleNamespace(
            rate_limited=lambda *_:False, get_r2=lambda:None, r2_bucket="test"
        )
        self.module.register_visual_routes(
            app,deps,lambda:None,
            lambda:({"id":self.user},None),
            lambda org,user:({"id":org,"name":"Agency"},None) if org==ORG and user["id"]=="owner" else (None,({"code":"not_found"},404)),
            lambda org,brand:({"id":"brand","name":"Agency","primary_color":"#111111","secondary_color":"#FFFFFF"},None)
        )
        self.start=app.routes["/api/business/visual/start"]
        self.prepare=app.routes["/api/business/campaigns/prepare-visual"]
        self.status=app.routes["/api/business/visual/<job_id>"]
        self.usage=app.routes["/api/business/visual/usage"]

    def make_ready(self,source_id,organisation=ORG):
        key=f"business/sources/{organisation}/{source_id}.mp4"
        r=reserve_job("owner",organisation,source_id,key,
                      path=self.tmp.name+"/visual.db",now=1000)
        _finish(r["job_id"],"owner","done",{
            "duration_s":12,
            "scenes":[{
              "timestamp_start":0,"timestamp_end":10,
              "title":"Visual scene 1","review_required":True,
            }]
        },self.tmp.name+"/visual.db")
        return r["job_id"]

    def test_worker_unavailable_does_not_accept_unprocessable_jobs(self):
        self.req.get_json=lambda silent=True:{"organisation_id":ORG,"source_id":SRC1}
        with patch.object(self.module,"lookup_source_by_id",return_value={
            "status":"confirmed","organisation_id":ORG,"etag":'"v1"',
            "source_key":f"business/sources/{ORG}/{SRC1}.mp4"
        }),patch.object(self.module,"find_job",return_value=None),patch.dict(
            os.environ,{"CLIPPR_BUSINESS_VISUAL_DISPATCH":"0"}):
            response,status=self.start()
        self.assertEqual(status,503)
        self.assertEqual(response["code"],"worker_unavailable")

    def test_source_usage_meter_is_owned_and_never_a_charge(self):
        self.make_ready(SRC1)
        first=self.usage()
        self.assertFalse(first["billable"])
        self.assertEqual(len(first["events"]),1)
        self.assertEqual(first["events"][0]["processed_seconds"],12)
        self.user="foreign"
        second=self.usage()
        self.assertEqual(second["events"],[])

    def test_source_usage_database_outage_fails_closed(self):
        with patch.object(self.module,"usage_candidates",side_effect=OSError("db down")):
            body,status=self.usage()
        self.assertEqual(status,503)
        self.assertEqual(body["code"],"storage_unavailable")

    def test_multiple_owned_sources_combine_in_single_review_pack(self):
        a=self.make_ready(SRC1)
        b=self.make_ready(SRC2)
        self.req.get_json=lambda silent=True:{"organisation_id":ORG,"visual_job_ids":[a,b],"brand_id":"brand"}
        result=self.prepare()
        self.assertEqual(len(result["clips"]),2)
        self.assertNotEqual(result["clips"][0]["index"],result["clips"][1]["index"])
        self.assertEqual(result["ai"]["request_count"],0)
        self.assertTrue(all(x["review_required"] for x in result["clips"]))

    def test_other_users_cannot_read_or_combine_jobs(self):
        job=self.make_ready(SRC1)
        self.user="attacker"
        self.req.get_json=lambda silent=True:{"organisation_id":ORG,"visual_job_ids":[job]}
        result,code=self.prepare()
        self.assertEqual(code,404)
        response,code=self.status(job)
        self.assertEqual(code,404)

    def test_duplicate_or_many_sources_rejected(self):
        job=self.make_ready(SRC1)
        self.req.get_json=lambda silent=True:{"organisation_id":ORG,"visual_job_ids":[job,job]}
        result,code=self.prepare()
        self.assertEqual(code,400)
        self.req.get_json=lambda silent=True:{"organisation_id":ORG,"visual_job_ids":[SRC1]*9}
        result,code=self.prepare()
        self.assertEqual(code,400)

    def test_prepared_pack_contains_owned_private_source_url(self):
        job=self.make_ready(SRC1)
        self.req.get_json=lambda silent=True:{"organisation_id":ORG,"visual_job_ids":[job]}
        output=self.prepare()
        self.assertTrue(output["clips"][0]["video_url"].startswith("r2://business/sources/"+ORG+"/"))
    def test_full_queue_returns_retryable_429_without_starting_another_job(self):
        from business_visual_jobs import VisualQueueFull
        self.req.get_json=lambda silent=True:{"organisation_id":ORG,"source_id":SRC1}
        with patch("business_visual_routes.lookup_source_by_id",return_value={
            "status":"confirmed","organisation_id":ORG,"etag":'"etag-v1"',
            "source_key":f"business/sources/{ORG}/{SRC1}.mp4"}):
            with patch("business_visual_routes.find_job",return_value=None):
                with patch("business_visual_routes.reserve_job",side_effect=VisualQueueFull("busy")):
                    body,status=self.start()
        self.assertEqual(status,429)
        self.assertEqual(body["code"],"queue_full")
        self.assertGreater(body["retry_after_seconds"],0)

    def test_replayed_scan_not_reserved_or_charged_twice(self):
        self.req.get_json=lambda silent=True:{"organisation_id":ORG,"source_id":SRC1}
        with patch("business_visual_routes.lookup_source_by_id",return_value={
            "status":"confirmed","organisation_id":ORG,"etag":'"etag-v1"',
            "source_key":f"business/sources/{ORG}/{SRC1}.mp4"}):
            with patch("business_visual_routes.find_job",return_value={
                "job_id":SRC2,"status":"queued"}):
                with patch("business_visual_routes.reserve_job") as reserve:
                    body,status=self.start()
        self.assertEqual(status,202)
        self.assertTrue(body["replayed"])
        reserve.assert_not_called()

if __name__=="__main__":unittest.main()
