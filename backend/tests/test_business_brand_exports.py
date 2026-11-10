"""Branded-export security, idempotency and real-video tests. No external services."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BRANDID="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SID="a"*32
ORIGINAL="b"*32
USER="user-one"
BRAND={
    "id":BRANDID,
    "name":"Clippr Test Company",
    "primary_color":"#121212","secondary_color":"#FFFFFF",
    "font_style":"modern","default_cta":"Enquire today",
}

class FakeApp:
    def __init__(self):self.endpoints={}
    def post(self,path):
        def wrapper(fn):self.endpoints[path]=fn;return fn
        return wrapper
    def get(self,path):
        def wrapper(fn):self.endpoints[path]=fn;return fn
        return wrapper

class FakeR2:
    def __init__(self,initial):self.files={"exports/original.mp4":Path(initial).read_bytes()};self.downloads=0
    def head_object(self,Bucket,Key):
        return {"ContentLength":len(self.files[Key])}
    def download_file(self,bucket,key,path):
        self.downloads+=1
        Path(path).write_bytes(self.files[key])

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"FFmpeg required")
class BrandedExportRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="business-brand-route-tests-")
        root=Path(cls.temp.name)
        cls.video=root/"video.mp4"
        result=subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error",
                "-f","lavfi","-i","testsrc2=size=360x640:rate=12",
                "-f","lavfi","-i","sine=frequency=500:sample_rate=22050",
                "-t","0.7","-c:v","libx264","-preset","ultrafast",
                "-c:a","aac",str(cls.video)],timeout=45,capture_output=True)
        if result.returncode:
            raise RuntimeError("Could not make test video")
        req=types.SimpleNamespace(get_json=lambda silent=True: {},headers={})
        cls.request=req
        with patch.dict(sys.modules,{"flask":types.SimpleNamespace(request=req,jsonify=lambda x:x)}):
            import importlib
            cls.module=importlib.import_module("business_brand_exports")

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        self.request.get_json=lambda silent=True:{"session_id":SID,"source_export_id":ORIGINAL,
                "organisation_id":ORG,"brand_id":BRANDID}
        self.current=USER
        self.brand=dict(BRAND)
        self.calls=[]
        self.db={ORIGINAL:{
            "export_id":ORIGINAL,"user_id":USER,"sid":SID,"status":"done",
            "r2_key":"exports/original.mp4","title":"Source title",
            "duration_s":0.7,"format":"9:16","captions":0,"video_url":"https://example.org/test",
            "start_s":0.0,"end_s":0.7,
        }}
        self.r2=FakeR2(self.video)
        def save(export_id,sid,key,title,duration,fmt,captions,user_id,**kw):
            if export_id in self.db:raise sqlite3.IntegrityError("duplicate export")
            self.db[export_id]={"export_id":export_id,"sid":sid,"r2_key":key,"title":title,
                                "duration_s":duration,"format":fmt,"captions":captions,
                                "user_id":user_id,"status":kw.get("status","done"),**kw}
            self.calls.append("save")
        def update(eid,status,r2_key=None,**kw):
            self.db[eid]["status"]=status
            if r2_key:self.db[eid]["r2_key"]=r2_key
            self.calls.append("update:"+status)
        def upload(path,key,filename=None):
            self.r2.files[key]=Path(path).read_bytes()
            self.calls.append("upload")
            return key
        self.deps=types.SimpleNamespace(
            get_export=lambda eid:self.db.get(eid),
            save_export=save,update_export_status=update,
            get_r2=lambda:self.r2,upload_to_r2=upload,
            r2_presigned_url=lambda key,**kw:"https://test.invalid/signed/"+key,
            r2_bucket="test",export_signing_key="private-test-secret-with-more-than-24",
            duplicate_error=sqlite3.IntegrityError,rate_limited=lambda *_:False
        )
        app=FakeApp()
        def owned_session(sid,user):
            if sid!=SID or user.get("id")!=USER:
                return None,({"code":"not_found"},404)
            return {"status":"done","user_id":USER},None
        def owner_org(oid,user):
            if oid!=ORG or user.get("id")!=USER:return None,({"code":"not_found"},404)
            return {"id":ORG},None
        def owner_brand(oid,bid):
            if oid!=ORG or bid!=BRANDID:return None,({"code":"not_found"},404)
            return dict(self.brand),None
        self.module.register_brand_export_routes(
            app,self.deps,
            lambda:({"id":self.current},None) if self.current else (None,({"code":"auth_required"},401)),
            owned_session,owner_org,owner_brand,lambda:None)
        self.start=app.endpoints["/api/business/exports/brand"]
        self.status=app.endpoints["/api/business/exports/brand/<export_id>"]

    def test_cross_account_source_export_is_never_downloaded(self):
        self.db[ORIGINAL]["user_id"]="another-user"
        body,code=self.start()
        self.assertEqual(code,404)
        self.assertEqual(body["code"],"not_found")
        self.assertEqual(self.r2.downloads,0)

    def test_no_unexported_source_bypasses_creator_paywall(self):
        self.db.pop(ORIGINAL)
        body,code=self.start()
        self.assertEqual(code,404)
        self.assertEqual(self.r2.downloads,0)

    def test_wait_until_real_original_is_done(self):
        self.db[ORIGINAL]["status"]="processing"
        body,code=self.start()
        self.assertEqual(code,409)
        self.assertEqual(body["code"],"export_not_ready")

    def test_no_saved_brand_is_not_faked(self):
        self.request.get_json=lambda silent=True:{
            "session_id":SID,"source_export_id":ORIGINAL,
            "organisation_id":ORG,"brand_id":None}
        body,code=self.start()
        self.assertEqual(code,400)
        self.assertEqual(body["code"],"brand_required")

    def test_repeated_submission_does_not_render_or_upload_twice(self):
        with patch.object(self.module,"_EXECUTOR") as executor:
            executor.submit.side_effect=lambda fn,*args:fn(*args)
            body,code=self.start()
            self.assertEqual(code,202)
            self.assertEqual(self.db[body["export_id"]]["status"],"done")
            self.assertEqual(self.r2.downloads,1)
            self.assertEqual(self.calls.count("upload"),1)
            replay,status=self.start()
            self.assertEqual(status,200)
            self.assertTrue(replay["replayed"])
            self.assertEqual(self.r2.downloads,1)
            self.assertEqual(self.calls.count("upload"),1)
            download=self.status(body["export_id"])
            self.assertEqual(download["status"],"done")
            self.assertTrue(download["url"].startswith("https://test.invalid/signed/business/exports/"))
            self.assertGreater(len(self.r2.files[self.db[body["export_id"]]["r2_key"]]),1500)

    def test_status_rejects_other_accounts_exports(self):
        with patch.object(self.module,"_EXECUTOR") as executor:
            executor.submit.side_effect=lambda fn,*args:fn(*args)
            data,_=self.start()
        self.current="attacker"
        body,status=self.status(data["export_id"])
        self.assertEqual(status,404)
        self.assertNotIn("url",body)

    def test_corrupt_source_fails_but_original_export_remains_done(self):
        self.r2.files["exports/original.mp4"]=b"not a video"
        with patch.object(self.module,"_EXECUTOR") as executor:
            executor.submit.side_effect=lambda fn,*args:fn(*args)
            body,_=self.start()
        self.assertEqual(self.db[body["export_id"]]["status"],"error")
        self.assertEqual(self.db[ORIGINAL]["status"],"done")
        self.assertEqual(self.calls.count("upload"),0)

    def test_rejected_owner_does_not_get_other_brands(self):
        self.current=None
        body,code=self.start()
        self.assertEqual(code,401)
        self.assertEqual(self.r2.downloads,0)

    def test_verified_logo_is_included_in_branded_video(self):
        from PIL import Image
        import io
        key=f"business/brands/{ORG}/{BRANDID}/"+("c"*32)+".png"
        picture=Image.new("RGBA",(100,40),(250,220,190,255))
        data=io.BytesIO()
        picture.save(data,format="PNG")
        self.r2.files[key]=data.getvalue()
        self.brand["logo_r2_key"]=key
        with patch.object(self.module,"_EXECUTOR") as executor:
            executor.submit.side_effect=lambda fn,*args:fn(*args)
            result,status=self.start()
        self.assertEqual(status,202)
        self.assertEqual(self.db[result["export_id"]]["status"],"done")
        self.assertEqual(self.r2.downloads,2)
        self.assertEqual(self.calls.count("upload"),1)

if __name__=="__main__":
    unittest.main()
