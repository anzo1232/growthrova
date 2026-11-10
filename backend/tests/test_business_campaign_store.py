import tempfile,unittest
from pathlib import Path
from business_campaign_store import save,get,list_for,delete,StoreError
ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SCENES=[{"source_id":"b"*32,"start_s":0,"end_s":12,"note":"Review before publish"},
        {"source_id":"c"*32,"start_s":15,"end_s":26}]
class CampaignPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=str(Path(self.tmp.name)/"draft.db")
    def save(self,owner="userA",**kw):
        return save(owner,ORG,kw.pop("name","My marketing campaign"),
                    kw.pop("goal","awareness"),None,kw.pop("scenes",SCENES),
                    path=self.db,**kw)
    def test_create_load_list_and_delete_are_owner_scoped(self):
        row=self.save()
        loaded=get("userA",row["id"],path=self.db)
        self.assertEqual(loaded["name"],"My marketing campaign")
        self.assertEqual(loaded["revision"],1)
        self.assertEqual(len(loaded["scenes"]),2)
        self.assertIsNone(get("userB",row["id"],path=self.db))
        self.assertEqual(list_for("userB",ORG,path=self.db),[])
        self.assertFalse(delete("userB",ORG,row["id"],path=self.db))
        self.assertTrue(delete("userA",ORG,row["id"],path=self.db))
        self.assertIsNone(get("userA",row["id"],path=self.db))
    def test_concurrent_revision_rejects_stale_update(self):
        row=self.save()
        saved=self.save(name="Updated title",campaign_id=row["id"],revision=1)
        self.assertEqual(saved["revision"],2)
        with self.assertRaisesRegex(StoreError,"changed"):
            self.save(name="Stale title",campaign_id=row["id"],revision=1)
        self.assertEqual(get("userA",row["id"],path=self.db)["name"],"Updated title")
    def test_cross_owner_update_and_nonexistent_id_denied(self):
        row=self.save()
        with self.assertRaisesRegex(StoreError,"not found"):
            self.save(owner="userB",campaign_id=row["id"],revision=1)
        self.assertEqual(get("userA",row["id"],path=self.db)["revision"],1)
        with self.assertRaisesRegex(StoreError,"not found"):
            self.save(campaign_id="a"*32,revision=1)
    def test_no_signed_url_or_private_secret_can_enter_scene_fields(self):
        payload={**SCENES[0],"video_url":"r2://private","session_token":"jwt",
                 "notes":"Review only"}
        row=self.save(scenes=[payload])
        seen=get("userA",row["id"],path=self.db)
        self.assertNotIn("video_url",str(seen))
        self.assertNotIn("session_token",str(seen))
        self.assertEqual(seen["scenes"][0]["review_status"],"draft")
    def test_invalid_scene_or_status_is_not_persisted(self):
        with self.assertRaises(StoreError):
            self.save(scenes=[{"source_id":"bad","start_s":0,"end_s":12}])
        with self.assertRaises(StoreError):
            self.save(scenes=[{"source_id":"b"*32,"start_s":12,"end_s":12}])
        row=self.save(scenes=[{"source_id":"b"*32,"start_s":0,"end_s":10,
                               "review_status":"unapproved"}])
        self.assertEqual(get("userA",row["id"],path=self.db)["scenes"][0]["review_status"],"draft")
if __name__=="__main__":unittest.main()
