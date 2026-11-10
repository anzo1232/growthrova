"""Offline HTTP adapter tests for owner-verified business uploads."""
from __future__ import annotations
import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NONCE="1"*32

class Routes:
    def __init__(self):self.handlers={}
    def post(self,path):
        def decorator(fn):self.handlers[path]=fn;return fn
        return decorator
    get=post

class R2:
    def __init__(self):self.objects={}
    def head_object(self,Bucket,Key):
        if Key not in self.objects:
            error=ValueError("not found")
            error.response={"Error":{"Code":"NoSuchKey"}}
            raise error
        return self.objects[Key]

class UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request=types.SimpleNamespace()
        cls.request.get_json=lambda silent=True:{}
        cls.flask_patch=patch.dict(sys.modules,{
            "flask":types.SimpleNamespace(request=cls.request,jsonify=lambda x:x)
        })
        cls.flask_patch.start()
        cls.addClassCleanup(cls.flask_patch.stop)
        cls.module=importlib.import_module("business_source_routes")

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.environ=patch.dict(os.environ,{
            "CLIPPR_BUSINESS_SOURCES_DB":self.tmp.name+"/registry.db"
        })
        self.environ.start()
        self.addCleanup(self.environ.stop)
        self.owner="customer-A"
        self.org=ORG
        self.r2=R2()
        self.body={
            "organisation_id":ORG,"filename":"footage.mp4",
            "content_type":"video/mp4","size":50_000,"client_nonce":NONCE
        }
        self.request.get_json=lambda silent=True:self.body
        self.request.args={}
        deps=types.SimpleNamespace(
            rate_limited=lambda *_:False,worker_enabled=lambda:False,
            r2_presigned_put=lambda key,mime,expires:"https://upload.example/"+key,
            get_r2=lambda:self.r2,r2_bucket="test-bucket",
            worker_upload_token=lambda key:(999999,"sig"),upload_base="https://uploads.example",
            upload_part_size=90*1024*1024
        )
        app=Routes()
        self.module.register_source_routes(app,deps,lambda:None,
           lambda:({"id":self.owner},None) if self.owner else (None,({"code":"auth_required"},401)),
           lambda org,user:({"id":ORG},None) if org==ORG and user["id"]==self.owner else (None,({"code":"not_found"},404)))
        self.init=app.handlers["/api/business/sources/init"]
        self.confirm=app.handlers["/api/business/sources/confirm"]
        self.recover=app.handlers["/api/business/sources/recover"]

    def test_init_is_owned_and_idempotent(self):
        first=self.init()
        self.assertEqual(first["mode"],"single")
        second=self.init()
        self.assertEqual(first["key"],second["key"])
        self.assertIn("/"+ORG+"/",first["key"])

    def test_lost_upload_response_reconciles_existing_object_without_new_put(self):
        first=self.init()
        self.r2.objects[first["key"]]={"ContentLength":50_000,"ContentType":"video/mp4","ETag":'"etag-v1"'}
        replay=self.init()
        self.assertEqual(replay["status"],"confirmed")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["key"],first["key"])
        self.assertNotIn("upload_url",replay)

    def test_upload_without_storage_etag_cannot_be_confirmed(self):
        booked=self.init()
        self.body={"organisation_id":ORG,"key":booked["key"]}
        self.r2.objects[booked["key"]]={"ContentLength":50_000,"ContentType":"video/mp4"}
        response,status=self.confirm()
        self.assertEqual(status,503)
        self.assertEqual(response["code"],"storage_unavailable")
        from business_sources import source_for_owner
        record=source_for_owner(booked["key"],self.owner)
        self.assertEqual(record["status"],"pending")

    def test_unknown_storage_error_does_not_issue_another_upload_token(self):
        first=self.init()
        def offline(**kwargs):raise ConnectionError("storage temporarily down")
        self.r2.head_object=offline
        response,status=self.init()
        self.assertEqual(status,503)
        self.assertEqual(response["code"],"upload_verification_unavailable")
        self.assertNotIn("upload_url",response)

    def test_pending_upload_is_recovered_from_saved_source_after_refresh(self):
        init=self.init()
        sid=init["source_id"]
        self.body={"organisation_id":ORG,"source_id":sid}
        self.r2.objects[init["key"]]={"ContentLength":50_000,"ContentType":"video/mp4","ETag":'"etag-v1"'}
        response=self.recover()
        self.assertTrue(response["ok"])
        self.assertEqual(response["status"],"confirmed")
        self.assertTrue(response["replayed"])
        from business_sources import list_sources_for_owner
        rows=list_sources_for_owner(self.owner,ORG)
        self.assertEqual(rows[0]["client_nonce"],NONCE)
        self.assertEqual(rows[0]["content_type"],"video/mp4")

    def test_pending_recovery_rejects_foreign_user_and_missing_file(self):
        init=self.init()
        self.body={"organisation_id":ORG,"source_id":init["source_id"]}
        body,status=self.recover()
        self.assertEqual(status,409)
        self.assertEqual(body["code"],"upload_still_pending")
        self.owner="customer-B"
        body,status=self.recover()
        self.assertEqual(status,404)

    def test_cannot_confirm_other_accounts_key(self):
        init=self.init()
        self.body={"organisation_id":ORG,"key":init["key"]}
        self.owner="customer-B"
        body,code=self.confirm()
        self.assertEqual(code,404)

    def test_bad_size_or_type_rejected_before_presigning(self):
        self.body={**self.body,"size":2_000_000_000}
        body,code=self.init()
        self.assertEqual(code,400)
        self.body={**self.body,"size":50_000,"content_type":"image/png"}
        body,code=self.init()
        self.assertEqual(code,400)

    def test_verification_requires_exact_storage_size_and_content_type(self):
        init=self.init()
        self.body={"organisation_id":ORG,"key":init["key"]}
        self.r2.objects[init["key"]]={"ContentLength":50_002,"ContentType":"video/mp4","ETag":'"etag-v1"'}
        body,code=self.confirm()
        self.assertEqual(code,400)
        self.r2.objects[init["key"]]={"ContentLength":50_000,"ContentType":"video/mp4","ETag":'"etag-v1"'}
        ready=self.confirm()
        self.assertTrue(ready["ok"])

    def test_business_api_disabled_returns_404_before_storage(self):
        # A preflight feature flag gates the route before any owner/DB access.
        app=Routes()
        deps=types.SimpleNamespace()
        self.module.register_source_routes(app,deps,lambda:({"code":"business_unavailable"},404),
             lambda:(_ for _ in ()).throw(AssertionError("auth reached")),
             lambda *_:None)
        self.assertEqual(app.handlers["/api/business/sources/init"]()[1],404)

if __name__=="__main__":unittest.main()
