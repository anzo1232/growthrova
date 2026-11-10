import tempfile
import threading
import unittest
from pathlib import Path

from business_sources import (
    reserve_source,source_for_owner,confirm_source,may_analyse_source,
    validate_file,list_sources_for_owner,MAX_SOURCES_PER_DAY,
    verified_source_object,SourceStorageUnavailable
)

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER="owner-A"
NONCE="b"*32

class TestBusinessSourceOwnership(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=str(Path(self.temp.name)/"sources.db")

    def reserve(self,**overrides):
        options={"path":self.db,"now":1_800_000_000}
        options.update(overrides)
        return reserve_source(OWNER,ORG,"footage.mp4","video/mp4",50_000,NONCE,**options)

    def test_upload_reserved_by_owner_cannot_be_analysed_before_verify(self):
        source=self.reserve()
        self.assertTrue(source["source_key"].startswith("business/sources/"+ORG+"/"))
        self.assertFalse(may_analyse_source(source["source_key"],OWNER,path=self.db))
        self.assertIsNone(source_for_owner(source["source_key"],"other-account",path=self.db))
        with self.assertRaises(ValueError):
            confirm_source(source["source_key"],"other-account",50_000,"video/mp4",path=self.db)
        confirmed=confirm_source(source["source_key"],OWNER,50_000,"video/mp4",
                                 path=self.db,now=1_800_000_005)
        self.assertEqual(confirmed["status"],"confirmed")
        self.assertTrue(may_analyse_source(source["source_key"],OWNER,path=self.db))
        self.assertFalse(may_analyse_source(source["source_key"],"other",path=self.db))

    def test_confirmed_file_version_is_immutable_across_reverification(self):
        source=self.reserve()
        first=confirm_source(source["source_key"],OWNER,50_000,"video/mp4",
                             actual_etag='"version-one"',path=self.db,
                             now=1_800_000_005)
        self.assertEqual(first["etag"],'"version-one"')
        self.assertEqual(source_for_owner(source["source_key"],OWNER,
                                         path=self.db)["etag"],'"version-one"')
        with self.assertRaisesRegex(ValueError,"has changed"):
            confirm_source(source["source_key"],OWNER,50_000,"video/mp4",
                           actual_etag='"version-two"',path=self.db)
        self.assertEqual(source_for_owner(source["source_key"],OWNER,
                                         path=self.db)["etag"],'"version-one"')

    def test_r2_version_guard_is_owner_checked_and_fails_closed(self):
        source=self.reserve()
        confirm_source(source["source_key"],OWNER,50_000,"video/mp4",
                       actual_etag='"expected-etag"',path=self.db,now=1_800_000_005)
        class R2:
            etag='"expected-etag"'
            def head_object(self,Bucket,Key):
                return {"ContentLength":50_000,"ContentType":"video/mp4",
                        "ETag":self.etag}
        store=R2()
        self.assertTrue(verified_source_object(source["source_key"],OWNER,store,
                                              "test",path=self.db))
        store.etag='"different-data-same-length"'
        self.assertFalse(verified_source_object(source["source_key"],OWNER,store,
                                               "test",path=self.db))
        self.assertFalse(verified_source_object(source["source_key"],"other",store,
                                               "test",path=self.db))
        with self.assertRaises(SourceStorageUnavailable):
            verified_source_object(source["source_key"],OWNER,None,"test",path=self.db)

    def test_file_size_type_and_key_rejection(self):
        for name,mime,size in [
            ("test.svg","image/svg+xml",2000),
            ("sample.mp4","video/mp4",900_000_000),
            ("sample.mov","video/mp4",2000),
            ("sample.exe","application/octet-stream",2000),
        ]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):validate_file(name,mime,size)
        self.assertFalse(may_analyse_source("uploads/unowned.mp4",OWNER,path=self.db))
        self.assertFalse(may_analyse_source("../evil",OWNER,path=self.db))

    def test_reservations_are_idempotent_and_cannot_change_file(self):
        first=self.reserve()
        replay=self.reserve()
        self.assertEqual(first["source_id"],replay["source_id"])
        with self.assertRaises(ValueError):
            self.reserve_source_different()
    def reserve_source_different(self):
        return reserve_source(OWNER,ORG,"changed.mp4","video/mp4",60_000,NONCE,
                              path=self.db,now=1_800_000_010)

    def test_restore_list_keeps_filename_private_to_owner(self):
        source=self.reserve()
        mine=list_sources_for_owner(OWNER,ORG,path=self.db)
        self.assertEqual(len(mine),1)
        self.assertEqual(mine[0]["source_id"],source["source_id"])
        self.assertEqual(mine[0]["filename"],"footage.mp4")
        self.assertEqual(list_sources_for_owner("another",ORG,path=self.db),[])

    def test_mismatch_and_expiration_never_mark_confirmed(self):
        first=self.reserve()
        with self.assertRaises(ValueError):
            confirm_source(first["source_key"],OWNER,50_001,"video/mp4",path=self.db)
        with self.assertRaises(ValueError):
            confirm_source(first["source_key"],OWNER,50_000,"video/quicktime",path=self.db)
        with self.assertRaises(ValueError):
            confirm_source(first["source_key"],OWNER,50_000,"video/mp4",path=self.db,
                           now=1_800_000_000+49*3600)
        self.assertFalse(may_analyse_source(first["source_key"],OWNER,path=self.db))

    def test_concurrent_init_allocates_one_key(self):
        seen=[]
        def claim():
            seen.append(self.reserve()["source_key"])
        t1,t2=threading.Thread(target=claim),threading.Thread(target=claim)
        t1.start();t2.start();t1.join();t2.join()
        self.assertEqual(len(seen),2)
        self.assertEqual(seen[0],seen[1])

if __name__=="__main__":
    unittest.main()
