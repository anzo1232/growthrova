import importlib,sys,tempfile,types,os,unittest
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SID="b"*32
OWNER="paid-owner"
SCENES=[{"source_id":SID,"start_s":0,"end_s":6},
        {"source_id":SID,"start_s":6,"end_s":12}]
class App:
    def __init__(self):self.routes={}
    def post(self,path):
        def decorator(fn):self.routes[path]=fn;return fn
        return decorator
    get=post
class MontageRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.req=types.SimpleNamespace(get_json=lambda silent=True:{},headers={})
        cls.patcher=patch.dict(sys.modules,{
            "flask":types.SimpleNamespace(request=cls.req,jsonify=lambda x:x)})
        cls.patcher.start();cls.addClassCleanup(cls.patcher.stop)
        cls.module=importlib.import_module("business_montage_routes")
    def setUp(self):
        self.req.headers={"Authorization":"Bearer staging-test-jwt"}
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{
            "CLIPPR_BUSINESS_MONTAGE":"1","CLIPPR_BUSINESS_MONTAGE_DB":self.tmp.name+"/ledger.db",
            "CLIPPR_BUSINESS_SOURCES_DB":self.tmp.name+"/sources.db",
            "CLIPPR_BUSINESS_VISUAL_DB":self.tmp.name+"/visual.db"})
        self.env.start();self.addCleanup(self.env.stop)
        self.paid=False
        self.brand_primary="#111111"
        self.req.get_json=lambda silent=True:{
            "organisation_id":ORG,"brand_id":"brand-id","scenes":SCENES,
            "draft_id":"c"*8+"-"+"c"*4+"-4"+"c"*3+"-8"+"c"*3+"-"+"c"*12,
            "draft_revision":1}
        self.owner=OWNER
        app=App()
        deps=types.SimpleNamespace(
            has_paid_access=lambda user:self.paid,
            get_r2=lambda:None,r2_bucket="test",
            upload_to_r2=lambda *a,**k:None,r2_presigned_url=lambda *a,**k:None)
        self.module.register_montage_routes(app,deps,
            lambda:({"id":self.owner},None),
            lambda oid,user:({"id":ORG},None) if oid==ORG else (None,({"code":"not_found"},404)),
            lambda oid,bid:({"id":"brand-id","name":"Business Brand",
                 "primary_color":self.brand_primary,"secondary_color":"#FFFFFF",
                "font_style":"modern","default_cta":""},None),
            lambda:None)
        self.start=app.routes["/api/business/montages"]
        self.status=app.routes["/api/business/montages/<jid>"]
        self.usage=app.routes["/api/business/montages/usage"]
    @contextmanager
    def allowed(self):
        with patch.object(self.module,"_validated_scenes",return_value=[
            {**s,"key":"business/sources/"+ORG+"/"+SID+".mp4"} for s in SCENES]):
            with patch.object(self.module,"verify_approved_draft",return_value={
                "id":"cccccccc-cccc-4ccc-8ccc-cccccccccccc","revision":1}):
                yield
    def test_usage_is_owned_and_is_not_a_stripe_invoice(self):
        self.paid=True
        with self.allowed():
            first,status=self.start()
        self.assertEqual(status,202)
        from business_montage_ledger import update
        self.assertTrue(update(self.owner,first["montage_id"],"running"))
        self.assertTrue(update(self.owner,first["montage_id"],"done",
                 key=f"business/montages/{self.owner}/{first['montage_id']}.mp4"))
        owner=self.usage()
        self.assertEqual(owner["meter"]["completed_outputs"],1)
        self.assertEqual(owner["meter"]["output_seconds"],12)
        self.assertFalse(owner["billable"])
        self.owner="another-user"
        other=self.usage()
        self.assertEqual(other["meter"]["completed_outputs"],0)
        self.assertEqual(other["meter"]["output_seconds"],0)

    def test_montage_usage_is_protected_when_feature_off(self):
        with patch.dict(os.environ,{"CLIPPR_BUSINESS_MONTAGE":"0"}):
            body,status=self.usage()
        self.assertEqual(status,404)

    def test_feature_off_never_checks_customer_payment(self):
        with patch.dict(os.environ,{"CLIPPR_BUSINESS_MONTAGE":"0"}):
            output,code=self.start()
        self.assertEqual(code,404)
    def test_free_account_cannot_reserve_any_export(self):
        with self.allowed():
            body,code=self.start()
        self.assertEqual(code,402)
        self.assertEqual(body["code"],"paid_plan_required")
    def test_foreign_scene_cannot_make_any_storage_work(self):
        self.paid=True
        body,code=self.start()
        self.assertEqual(code,403)
        self.assertEqual(body["code"],"scenes_not_owned_or_unapproved")
    def test_paid_valid_scenes_create_single_durable_job(self):
        self.paid=True
        with self.allowed():
            with patch.object(self.module,"_worker") as worker:
                first,code=self.start()
                again,replay=self.start()
        self.assertEqual(code,202)
        self.assertEqual(replay,202)
        self.assertTrue(again["replayed"])
        self.assertEqual(first["montage_id"],again["montage_id"])
        worker.assert_not_called()
        from business_montage_ledger import claim_next
        item=claim_next("staging-worker",now=None)
        self.assertEqual(item["id"],first["montage_id"])
        self.assertEqual(item["payload"]["brand_id"],"brand-id")
        self.assertEqual(len(item["payload"]["scenes"]),2)
        self.assertEqual(self.status(first["montage_id"])["status"],"running")
    def test_same_scenes_with_changed_brand_colours_create_new_version(self):
        self.paid=True
        with self.allowed():
            with patch.object(self.module,"_worker") as worker:
                first,code=self.start()
                self.brand_primary="#223344"
                second,code2=self.start()
        self.assertEqual(code,202)
        self.assertEqual(code2,202)
        self.assertNotEqual(first["montage_id"],second["montage_id"])
        worker.assert_not_called()

    def test_montage_status_has_explicit_processing_phase(self):
        self.paid=True
        with self.allowed(),patch.object(self.module,"_worker"):
            started,_=self.start()
        status=self.status(started["montage_id"])
        self.assertEqual(status["status"],"queued")
        self.assertEqual(status["phase"],"queued")

    def test_export_requires_saved_campaign(self):
        self.paid=True
        self.req.get_json=lambda silent=True:{
            "organisation_id":ORG,"brand_id":"brand-id","scenes":SCENES}
        with self.allowed():
            with patch.object(self.module,"verify_approved_draft",
                              side_effect=self.module.MontageApprovalError(
                                  "draft_required","Save an approved campaign first")):
                body,status=self.start()
        self.assertEqual(status,400)
        self.assertEqual(body["code"],"draft_required")

    def test_stale_approval_blocks_paid_render(self):
        self.paid=True
        with self.allowed():
            with patch.object(self.module,"verify_approved_draft",
                              side_effect=self.module.MontageApprovalError(
                                  "revision_conflict","Refresh campaign")):
                with patch.object(self.module,"_worker") as worker:
                    body,status=self.start()
        self.assertEqual(status,409)
        self.assertEqual(body["code"],"revision_conflict")
        worker.assert_not_called()

    def test_unapproved_scene_rejected_even_for_paid_user(self):
        self.paid=True
        with self.allowed():
            with patch.object(self.module,"verify_approved_draft",
                              side_effect=self.module.MontageApprovalError(
                                  "scenes_unapproved","Needs human review")):
                with patch.object(self.module,"_worker") as worker:
                    body,status=self.start()
        self.assertEqual(status,409)
        self.assertEqual(body["code"],"scenes_unapproved")
        worker.assert_not_called()

    def test_campaign_storage_failure_never_starts_worker(self):
        self.paid=True
        with self.allowed():
            with patch.object(self.module,"verify_approved_draft",
                              side_effect=self.module.CampaignStorageUnavailable(
                                  "private storage error")):
                with patch.object(self.module,"_worker") as worker:
                    body,status=self.start()
        self.assertEqual(status,503)
        self.assertEqual(body["code"],"storage_unavailable")
        self.assertNotIn("private",str(body))
        worker.assert_not_called()

    def test_new_approval_revision_is_new_montage_version(self):
        self.paid=True
        with self.allowed(),patch.object(self.module,"_worker") as worker:
            original,_=self.start()
            with patch.object(self.module,"verify_approved_draft",return_value={
                "id":"cccccccc-cccc-4ccc-8ccc-cccccccccccc","revision":2}):
                new,status=self.start()
        self.assertEqual(status,202)
        self.assertNotEqual(original["montage_id"],new["montage_id"])
        worker.assert_not_called()

    def test_cannot_read_other_user_montage(self):
        self.paid=True
        with self.allowed(),patch.object(self.module,"_worker"):
            body,_=self.start()
        self.owner="attacker"
        result,code=self.status(body["montage_id"])
        self.assertEqual(code,404)
if __name__=="__main__":unittest.main()
