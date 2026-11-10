"""No-network tests for staging Auth and R2 canaries."""
from __future__ import annotations
import hashlib
import io
from contextlib import redirect_stdout
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import business_staging_auth_live as auth
import business_staging_r2_live as r2

STAGING=auth.URL

class StagingAuthSafetyTests(unittest.TestCase):
    def test_staging_url_must_be_exact(self):
        auth.check_target(STAGING)
        for url in ("https://uxfvagyhnstwncbclgaf.supabase.co",
                    "https://another.supabase.co",
                    STAGING+"/rest/v1", "http://"+auth.STAGING+".supabase.co"):
            with self.subTest(url=url),self.assertRaises(ValueError):
                auth.check_target(url)
    def test_canary_requires_two_distinct_genuine_accounts(self):
        fake=[{"id":"same","token":"token"},{"id":"same","token":"other"}]
        with self.assertRaisesRegex(RuntimeError,"distinct"):
            auth.write_canary(STAGING,"pub",fake)
    def test_login_must_verify_actual_supabase_user_endpoint(self):
        class Result:
            status_code=200
            def __init__(self,obj):self.obj=obj
            def json(self):return self.obj
        fake=[Result({"access_token":"fake-token","user":{"id":"alice"}}),
              Result({"id":"alice"})]
        with patch.object(auth,"req",side_effect=fake) as request:
            identity=auth.login(STAGING,"public","qa@example.invalid","fake-secret")
        self.assertEqual(identity["id"],"alice")
        self.assertEqual(identity["token"],"fake-token")
        self.assertEqual(request.call_count,2)
        self.assertEqual(request.call_args_list[1].args[2],"/auth/v1/user")
    def test_foreign_data_exposure_fails_and_fixtures_cleanup(self):
        users=[{"id":"userA","token":"A"},{"id":"userB","token":"B"}]
        db={}
        changes=[]
        def api(method,base,key,user,table,*,payload=None,params=None):
            ident=(payload or {}).get("id") or (params or {}).get("id","").removeprefix("eq.")
            if method=="POST":
                db[(table,ident)]={"owner":user["id"]}
                changes.append(("create",table,ident))
                return [{"id":ident}]
            if method=="PATCH":
                current=db.get((table,ident))
                return [{"id":ident}] if current and current["owner"]==user["id"] else []
            if method=="DELETE":
                current=db.get((table,ident))
                if current and current["owner"]==user["id"]:
                    del db[(table,ident)]
                    changes.append(("delete",table,ident))
                    return [{"id":ident}]
                return []
            if method=="GET":
                current=db.get((table,ident))
                return [{"id":ident}] if current and current["owner"]==user["id"] else []
            raise AssertionError("unexpected HTTP call")
        with patch.object(auth,"api",side_effect=api),redirect_stdout(io.StringIO()):
            auth.write_canary(STAGING,"pub",users)
        self.assertEqual(db,{})
        self.assertEqual(sum(i[0]=="create" for i in changes),6)
        self.assertEqual(sum(i[0]=="delete" for i in changes),6)

    def test_lost_create_acknowledgement_still_cleans_up_qa_data(self):
        people=[{"id":"userA","token":"A"},{"id":"userB","token":"B"}]
        rows={}
        def api(method,base,key,user,table,*,payload=None,params=None):
            sid=(payload or {}).get("id") or (params or {}).get("id","").removeprefix("eq.")
            index=(table,sid)
            if method=="POST":
                rows[index]=user["id"]
                raise RuntimeError("network lost after staging committed organisation")
            if method=="GET":
                return [{"id":sid}] if rows.get(index)==user["id"] else []
            if method=="DELETE":
                if rows.get(index)==user["id"]:
                    del rows[index]
                    return [{"id":sid}]
                return []
            return []
        with patch.object(auth,"api",side_effect=api),redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,"network lost"):
                auth.write_canary(STAGING,"pub",people)
        self.assertEqual(rows,{})

class StageR2SafetyTests(unittest.TestCase):
    def test_bucket_must_be_explicitly_staging_not_production(self):
        r2.validate_target("clippr-business-staging-qa")
        for name in (None,"clippr","other-bucket","clippr-business-staging-",
                     "clippr-business-staging-../bad"):
            with self.subTest(name=name),self.assertRaises(r2.StagingR2Blocked):
                r2.validate_target(name)
        with self.assertRaises(r2.StagingR2Blocked):
            r2.validate_target("clippr-business-staging-qa",
                               production_bucket="clippr-business-staging-qa")
    def test_synthetic_canary_upload_get_and_cleanup_limited_key(self):
        class FakeR2:
            objects={}
            key=None
            deleted=[]
            def put_object(self,**kw):
                self.key=kw["Key"]
                self.objects[self.key]=kw["Body"]
            def head_object(self,**kw):
                return {"ContentLength":len(self.objects[kw["Key"]]),"ETag":'"canary"'}
            def generate_presigned_url(self,*args,**kw):
                self.key=kw["Params"]["Key"]
                return "https://staging.invalid/"+self.key
            def delete_object(self,**kw):
                self.deleted.append(kw["Key"])
                self.objects.pop(kw["Key"],None)
        fake=FakeR2()
        media=b"x"*4000
        class Response:
            status_code=200
            content=media
        with patch("requests.get",return_value=Response()):
            outcome=r2.put_get_delete_canary(fake,"clippr-business-staging-qa",media)
        self.assertEqual(outcome["private_signed_get"],"PASS")
        self.assertTrue(fake.key.startswith(r2.OBJECT_ROOT))
        self.assertEqual(fake.objects,{})
        self.assertEqual(fake.deleted,[fake.key])
    def test_upload_failure_still_attempts_cleanup(self):
        class Broken:
            deleted=[]
            def put_object(self,**kw):self.key=kw["Key"];raise OSError("R2 unavailable")
            def delete_object(self,**kw):self.deleted.append(kw["Key"])
        fake=Broken()
        with self.assertRaises(OSError):
            r2.put_get_delete_canary(fake,"clippr-business-staging-qa",b"x"*4000)
        self.assertEqual(len(fake.deleted),1)
        self.assertTrue(fake.deleted[0].startswith(r2.OBJECT_ROOT))
    def test_non_synthetic_prefix_and_unsafe_size_rejected(self):
        class NeverCalled:
            def put_object(self,**kw):raise AssertionError("must not upload")
        for prefix in ("business/sources/","other-prefix"):
            with self.assertRaises(r2.StagingR2Blocked):
                r2.put_get_delete_canary(NeverCalled(),"test",b"x"*4000,prefix=prefix)
        with self.assertRaises(r2.StagingR2Blocked):
            r2.put_get_delete_canary(NeverCalled(),"test",b"x"*2)

if __name__=="__main__":unittest.main()
