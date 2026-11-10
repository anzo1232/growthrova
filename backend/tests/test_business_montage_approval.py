"""Human approval and campaign revision checks for montage admission."""
import unittest
import types
from business_montage_approval import verify_approved_draft, MontageApprovalError

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER="paid-owner"
BRAND="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DRAFT="cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SID="d"*32
SCENES=[
 {"source_id":SID,"key":"business/sources/"+ORG+"/"+SID+".mp4","start_s":0,"end_s":6},
 {"source_id":SID,"key":"business/sources/"+ORG+"/"+SID+".mp4","start_s":6,"end_s":12},
]

class Storage:
    record=None
    calls=[]
    def __init__(self,base,key,bearer):
        self.calls.append((base,key,bearer))
    def get(self,owner,id):
        self.calls.append((owner,id))
        return self.record

class TestHumanApproval(unittest.TestCase):
    def setUp(self):
        self.deps=types.SimpleNamespace(
            supabase_url="https://staging.example.invalid",
            supabase_anon_key="public-placeholder")
        Storage.calls=[]
        Storage.record={
          "id":DRAFT,"organisation_id":ORG,"revision":3,"brand_id":BRAND,
          "scenes":[{"source_id":s["source_id"],"start_s":s["start_s"],
                     "end_s":s["end_s"],"review_status":"approved"} for s in SCENES]
        }
    def check(self,**kw):
        args={"deps":self.deps,"bearer":"owner-jwt","owner":OWNER,
              "org":ORG,"brand_id":BRAND,"draft_id":DRAFT,
              "draft_revision":3,"requested":SCENES,"repo_class":Storage}
        args.update(kw)
        return verify_approved_draft(**args)
    def test_approved_exact_revision_succeeds(self):
        self.assertEqual(self.check(),{"id":DRAFT,"revision":3})
        self.assertIn((OWNER,DRAFT),Storage.calls)
    def test_missing_draft_or_auth_denied(self):
        with self.assertRaises(MontageApprovalError):
            self.check(draft_id=None)
        with self.assertRaises(MontageApprovalError):
            self.check(bearer="")
    def test_stale_revision_denied(self):
        with self.assertRaises(MontageApprovalError) as context:
            self.check(draft_revision=2)
        self.assertEqual(context.exception.code,"revision_conflict")
    def test_wrong_organisation_and_brand_denied(self):
        with self.assertRaises(MontageApprovalError):
            self.check(org="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
        with self.assertRaises(MontageApprovalError) as context:
            self.check(brand_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
        self.assertEqual(context.exception.code,"brand_mismatch")
    def test_unapproved_scene_denied(self):
        Storage.record["scenes"][1]["review_status"]="draft"
        with self.assertRaises(MontageApprovalError) as context:
            self.check()
        self.assertEqual(context.exception.code,"scenes_unapproved")
    def test_forged_timestamps_and_duplicate_scenes_denied(self):
        forged=[SCENES[0],{**SCENES[1],"start_s":5}]
        with self.assertRaises(MontageApprovalError):
            self.check(requested=forged)
        with self.assertRaises(MontageApprovalError):
            self.check(requested=[SCENES[0],SCENES[0]])
    def test_cross_owner_hidden_record_denied(self):
        Storage.record=None
        with self.assertRaises(MontageApprovalError) as context:
            self.check()
        self.assertEqual(context.exception.code,"not_found")
    def test_bool_revision_is_invalid(self):
        with self.assertRaises(MontageApprovalError):
            self.check(draft_revision=True)

if __name__=="__main__":unittest.main()
