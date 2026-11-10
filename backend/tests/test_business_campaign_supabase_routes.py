"""Isolated Flask adapter contracts for authenticated Supabase-backed drafts."""
import importlib,sys,types,unittest
from unittest.mock import Mock,patch
from business_campaign_supabase import CampaignStorageUnavailable,StoreError
ORG="33333333-3333-4333-8333-333333333333"
OWNER="11111111-1111-4111-8111-111111111111"
BRAND="55555555-5555-4555-8555-555555555555"
CID="99999999-9999-4999-8999-999999999999"
SID="a"*32
SCENES=[{"source_id":SID,"start_s":0,"end_s":8}]
class App:
    def __init__(self):self.routes={}
    def _register(self,method,path):
        def deco(fn):self.routes[(method,path)]=fn;return fn
        return deco
    def get(self,path):return self._register("GET",path)
    def post(self,path):return self._register("POST",path)
    def delete(self,path):return self._register("DELETE",path)
class AdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.req=types.SimpleNamespace(headers={"Authorization":"Bearer user-jwt"},
          args={"organisation_id":ORG},get_json=lambda silent=True:{})
        cls.flaskpatch=patch.dict(sys.modules,{
            "flask":types.SimpleNamespace(request=cls.req,jsonify=lambda v:v)
        });cls.flaskpatch.start();cls.addClassCleanup(cls.flaskpatch.stop)
        cls.module=importlib.import_module("business_campaign_store_routes")
    def setUp(self):
        self.req.headers={"Authorization":"Bearer user-jwt"}
        self.req.args={"organisation_id":ORG}
        self.req.get_json=lambda silent=True:{
            "organisation_id":ORG,"brand_id":BRAND,"name":"My campaign",
            "goal":"awareness","scenes":SCENES,"create_id":CID}
        self.owner={"id":OWNER}
        app=App()
        deps=types.SimpleNamespace(supabase_url="https://staging.example.supabase.co",
                                  supabase_anon_key="public")
        self.module.register_campaign_store_routes(app,
            lambda:(self.owner,None) if self.owner else (None,({"code":"auth_required"},401)),
            lambda id,user:({"id":ORG},None) if id==ORG else (None,({"code":"not_found"},404)),
            lambda org,brand:({"id":BRAND},None),
            lambda:None,deps)
        self.save=app.routes[("POST","/api/business/drafts")]
        self.get=app.routes[("GET","/api/business/drafts/<cid>")]
        self.list=app.routes[("GET","/api/business/drafts")]
        self.delete=app.routes[("DELETE","/api/business/drafts/<cid>")]
        self.storage=Mock()
        self.repository=patch.object(self.module,"CampaignSupabase",return_value=self.storage)
        self.repository.start();self.addCleanup(self.repository.stop)
    def test_save_requires_source_scan_and_does_not_consume_storage_if_foreign(self):
        with patch.object(self.module,"lookup_source_by_id",return_value=None):
            result,status=self.save()
        self.assertEqual(status,403)
        self.storage.save.assert_not_called()
    def test_source_storage_error_returns_retryable_503(self):
        with patch.object(self.module,"lookup_source_by_id",
                          side_effect=OSError("database locked")):
            result,status=self.save()
        self.assertEqual(status,503)
        self.assertEqual(result["code"],"source_status_unavailable")
        self.storage.save.assert_not_called()

    def test_authenticated_save_uses_owned_brand_and_verifiable_scene(self):
        self.storage.save.return_value={"id":CID,"revision":1,"updated":"now"}
        with patch.object(self.module,"lookup_source_by_id",return_value={
            "organisation_id":ORG,"status":"confirmed"}),patch.object(self.module,"find_job",return_value={
            "org_id":ORG,"status":"done","result":{"scenes":[{
                "timestamp_start":0,"timestamp_end":8
            }]}}):
            result=self.save()
        self.assertEqual(result["id"],CID)
        self.storage.save.assert_called_once()
        self.assertEqual(self.storage.save.call_args.args[0],OWNER)
    def test_failed_backend_does_not_claim_campaign_saved(self):
        self.storage.list.side_effect=CampaignStorageUnavailable("network secret")
        result,status=self.list()
        self.assertEqual(status,503)
        self.assertEqual(result["code"],"storage_unavailable")
        self.assertNotIn("network secret",str(result))
    def test_get_and_delete_cross_owner_are_not_found(self):
        self.storage.get.return_value=None
        result,status=self.get(CID)
        self.assertEqual(status,404)
        result,status=self.delete(CID)
        self.assertEqual(status,404)
        self.storage.delete.assert_not_called()
    def test_concurrent_edit_conflict_reported(self):
        self.storage.save.side_effect=StoreError("Campaign changed. Refresh before saving.")
        with patch.object(self.module,"lookup_source_by_id",return_value={
            "organisation_id":ORG,"status":"confirmed"}),patch.object(self.module,"find_job",return_value={
            "org_id":ORG,"status":"done","result":{"scenes":[{
                "timestamp_start":0,"timestamp_end":8
            }]}}):
            response,status=self.save()
        self.assertEqual(status,409)
        self.assertEqual(response["code"],"revision_conflict")
    def test_feature_off_blocks_before_any_query(self):
        app=App()
        deps=types.SimpleNamespace()
        self.module.register_campaign_store_routes(app,
            lambda: (_ for _ in ()).throw(Exception("auth should not execute")),
            lambda *_:None,lambda *_:None,lambda:({"code":"business_unavailable"},404),deps)
        result,status=app.routes[("GET","/api/business/drafts")]()
        self.assertEqual(status,404)

if __name__=="__main__":unittest.main()
