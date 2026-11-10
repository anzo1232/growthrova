import sys
import types
import unittest
from unittest.mock import patch
from PIL import Image
import io

ORG = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BRAND = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

class FakeApp:
    def __init__(self): self.routes = {}
    def post(self, path):
        def register(fn):
            self.routes[path] = fn
            return fn
        return register
    get = post

class FakeR2:
    def __init__(self): self.data = {}
    def head_object(self, Bucket, Key):
        return {"ContentLength": len(self.data[Key])}
    def download_file(self, bucket, key, path):
        from pathlib import Path
        Path(path).write_bytes(self.data[key])
    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return "https://signed.invalid/" + Params["Key"]

class LogoSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.req = types.SimpleNamespace(
            headers={"Authorization":"Bearer test"}, args={})
        cls.req.get_json = lambda silent=True: {}
        cls.stub = types.SimpleNamespace(request=cls.req, jsonify=lambda body:body)
        cls.flask_patch = patch.dict(sys.modules, {"flask":cls.stub})
        cls.flask_patch.start()
        cls.addClassCleanup(cls.flask_patch.stop)
        from business_brand_assets import register_brand_asset_routes
        cls.register = staticmethod(register_brand_asset_routes)

    def setUp(self):
        self.store = FakeR2()
        self.brand = {"id": BRAND, "logo_r2_key": None}
        app = FakeApp()
        dep = types.SimpleNamespace(
            get_r2=lambda:self.store, r2_bucket="test",
            r2_presigned_put=lambda key, content_type, expires: "https://put.invalid/" + key,
            rate_limited=lambda *a:False, supabase_url="https://example.supabase.co",
            supabase_anon_key="anon")
        self.register(app, dep, lambda:({"id":"owner"},None),
            lambda org,user: ({"id":ORG},None) if org==ORG else (None,({},404)),
            lambda org,brand: (self.brand,None) if brand==BRAND else (None,({},404)),
            lambda:None)
        self.init = app.routes["/api/business/brands/logo/init"]
        self.complete = app.routes["/api/business/brands/logo/complete"]
        self.logo = app.routes["/api/business/brands/logo"]
        self.req = self.__class__.req
        self.req.args = {"organisation_id":ORG,"brand_id":BRAND}
        self.req.get_json = lambda silent=True: {
            "organisation_id":ORG,"brand_id":BRAND,"content_type":"image/png","size":500}

    def test_private_upload_init_and_invalid_file(self):
        result = self.init()
        self.assertTrue(result["key"].startswith("business/brands/" + ORG + "/" + BRAND + "/"))
        self.req.get_json = lambda silent=True: {
            "organisation_id":ORG,"brand_id":BRAND,"size":800,
            "content_type":"image/svg+xml"}
        body,status = self.init()
        self.assertEqual(status,400)

    def test_completion_requires_valid_image(self):
        key = self.init()["key"]
        self.req.get_json = lambda silent=True: {
            "organisation_id":ORG,"brand_id":BRAND,"key":key}
        self.store.data[key] = b"not an image" * 40
        body,status = self.complete()
        self.assertEqual(status,400)

    def test_valid_png_is_verified_before_saving(self):
        key = self.init()["key"]
        self.req.get_json = lambda silent=True: {
            "organisation_id":ORG,"brand_id":BRAND,"key":key}
        picture=Image.new("RGBA",(80,80),(40,50,60,255))
        buffer=io.BytesIO()
        picture.save(buffer,format="PNG")
        self.store.data[key]=buffer.getvalue()
        class Response:
            status_code=200
            def json(self):return [{"id":BRAND}]
        import business_brand_assets
        with patch.object(business_brand_assets.requests,"patch",return_value=Response()) as update:
            result=self.complete()
        self.assertTrue(result["ok"])
        self.assertEqual(update.call_args.kwargs["json"]["logo_r2_key"],key)
        self.brand["logo_r2_key"]=key
        self.assertIn(key,self.logo()["url"])

    def test_foreign_logo_key_denied(self):
        self.req.get_json = lambda silent=True: {
            "organisation_id":ORG,"brand_id":BRAND,
            "key":"business/brands/other/user/logo.png"}
        result,status=self.complete()
        self.assertEqual(status,404)

    def test_logo_without_saved_key_not_downloadable(self):
        result,status=self.logo()
        self.assertEqual(status,404)

if __name__=="__main__":
    unittest.main()
