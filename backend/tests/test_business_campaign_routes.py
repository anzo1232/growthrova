"""No-network access-control test for the Business Flask adapter.

Runs without Flask installed by stubbing only the route decorator + request object;
all business logic and route closure code is executed for real.
"""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

SID = "0123456789abcdef0123456789abcdef"
ORG = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BRAND = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SOURCE = {
    "user_id":"user-1", "status":"done", "url":"https://example.com/source",
    "progress":100,
    "clips":[{"timestamp_start":12,"timestamp_end":44,"title":"A useful explanation", "score":83}],
}
class FakeApp:
    def __init__(self): self.routes = {}
    def get(self,path):
        def wrap(func):
            self.routes[path]=func
            return func
        return wrap
    def post(self,path):
        def wrap(func):
            self.routes[path]=func
            return func
        return wrap

FakeApp.delete = FakeApp.post

class Response:
    def __init__(self,status_code,body):
        self.status_code=status_code
        self.body=body
    def json(self): return self.body

class RouteSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.req=types.SimpleNamespace(headers={"Authorization":"Bearer fake-jwt"},get_json=lambda silent=True:{})
        fake_flask=types.SimpleNamespace(request=cls.req,jsonify=lambda item:item)
        cls.flask_patch=patch.dict(sys.modules,{"flask":fake_flask})
        cls.flask_patch.start()
        cls.addClassCleanup(cls.flask_patch.stop)
        cls.module=importlib.import_module("business_campaign_routes")

    def setUp(self):
        self.req=self.__class__.req
        self.req.headers={"Authorization":"Bearer fake-jwt"}
        self.req.get_json=lambda silent=True:{
            "session_id":SID,"organisation_id":ORG,"brand_id":BRAND,"goal":"education"
        }
        self.owner={"id":"user-1"}
        self.source=dict(SOURCE)
        self.rate=False
        app=FakeApp()
        deps=types.SimpleNamespace(
            get_user=lambda strict=True:self.owner,
            get_session=lambda sid:self.source if sid==SID else None,
            rate_limited=lambda *_:self.rate,
            supabase_url="https://example.supabase.co",
            auth_supabase_url="https://example.supabase.co",
            supabase_anon_key="public-placeholder",
        )
        self.deps=deps
        self.module.register_business_routes(app,deps)
        self.status=app.routes["/api/business/sessions/<sid>"]
        self.prepare=app.routes["/api/business/campaigns/prepare"]

    def test_disabled_flag_does_not_expose_session_or_customer_info(self):
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"0"}):
            body, status=self.status(SID)
        self.assertEqual(status,404)
        self.assertEqual(body["code"],"business_unavailable")

    def test_staging_data_with_live_auth_project_fails_closed_before_access(self):
        self.deps.auth_supabase_url="https://uxfvagyhnstwncbclgaf.supabase.co"
        self.deps.supabase_url="https://zbncuxizmjinexifcshe.supabase.co"
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"1"}):
            body,status=self.status(SID)
        self.assertEqual(status,503)
        self.assertEqual(body["code"],"business_auth_config_mismatch")
        self.assertNotIn("clips",body)

    def test_missing_auth_denied_before_session_read(self):
        self.owner=None
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"1"}):
            body,status=self.status(SID)
        self.assertEqual(status,401)
        self.assertEqual(body["code"],"auth_required")

    def test_another_users_session_is_a_404_without_content(self):
        self.source["user_id"]="user-2"
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"1"}):
            body,status=self.status(SID)
        self.assertEqual(status,404)
        self.assertNotIn("clips",body)

    def test_unowned_session_is_never_business_visible(self):
        self.source["user_id"]=None
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"1"}):
            _,status=self.prepare()
        self.assertEqual(status,404)

    def test_owner_gets_only_status_and_candidate_metadata(self):
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"1"}):
            body=self.status(SID)
        self.assertEqual(body["status"],"done")
        self.assertEqual(len(body["clips"]),1)
        self.assertEqual(body["video_url"],SOURCE["url"])

    def test_incomplete_session_cannot_trigger_business_ai(self):
        self.source["status"]="running"
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"1"}):
            body,status=self.prepare()
        self.assertEqual(status,409)
        self.assertEqual(body["code"],"source_not_ready")

    def test_rate_limit_before_any_provider_request(self):
        self.rate=True
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"1"}):
            body,status=self.prepare()
        self.assertEqual(status,429)

    def test_organisation_owner_routed_through_caller_jwt(self):
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"1","CLIPPR_BUSINESS_AI":"0"}):
            with patch.object(self.module.requests,"get",side_effect=[
                Response(200,[{"id":ORG,"name":"Local Experts","industry":"consulting","primary_goal":"education"}]),
                Response(200,[{"id":BRAND,"name":"Main Brand","font_style":"modern","default_cta":"Learn more",
                               "primary_color":"#111111","secondary_color":"#FFFFFF"}])
            ]) as lookup:
                result=self.prepare()
        self.assertEqual(result["ai"]["status"],"disabled")
        self.assertEqual(len(result["clips"]),1)
        self.assertTrue(result["review_required"])
        self.assertTrue(result["clips"][0]["review_required"])
        self.assertEqual(lookup.call_args_list[0].kwargs["headers"]["Authorization"],"Bearer fake-jwt")
        self.assertNotIn("service_role",repr(lookup.call_args_list))

    def test_non_owned_organisation_returns_404_not_data(self):
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"1"}):
            with patch.object(self.module.requests,"get",return_value=Response(200,[])):
                body,status=self.prepare()
        self.assertEqual(status,404)
        self.assertEqual(body["code"],"not_found")

    def test_missing_schema_is_not_silently_faked(self):
        with patch.dict("os.environ",{"CLIPPR_BUSINESS_API":"1"}):
            with patch.object(self.module.requests,"get",return_value=Response(404,{"message":"table missing"})):
                body,status=self.prepare()
        self.assertEqual(status,503)
        self.assertEqual(body["code"],"storage_unavailable")

if __name__=="__main__": unittest.main()
