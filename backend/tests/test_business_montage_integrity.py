"""Montage admission freezes the verified visual source version and bandwidth."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER="user"
SID1="a"*32
SID2="b"*32
SID3="c"*32
def scene(source,start,end):
    return {"source_id":source,"start_s":start,"end_s":end}
def job():
    return {"org_id":ORG,"status":"done","result":{"scenes":[
      {"timestamp_start":0,"timestamp_end":6},
      {"timestamp_start":7,"timestamp_end":13}
    ]}}

class VersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(sys.modules,{"flask":types.SimpleNamespace(
            request=None,jsonify=lambda x:x)}):
            cls.routes=importlib.import_module("business_montage_routes")
    def run_candidates(self,rows,source_fn):
        with patch.object(self.routes,"lookup_source_by_id",side_effect=source_fn):
            with patch.object(self.routes,"find_job",return_value=job()):
                return self.routes._validated_scenes(OWNER,ORG,rows)
    def source(self,sid,size=100_000,etag='"v1"'):
        return {"source_key":f"business/sources/{ORG}/{sid}.mp4",
                "organisation_id":ORG,"declared_size":size,
                "etag":etag,"status":"confirmed"}
    def test_approved_version_and_size_enter_immutable_worker_payload(self):
        rows=[scene(SID1,0,6),scene(SID1,7,13)]
        result=self.run_candidates(rows,lambda sid,who:self.source(sid))
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]["etag"],'"v1"')
        self.assertEqual(result[0]["size"],100_000)
        self.assertEqual(result[1]["key"],result[0]["key"])
    def test_missing_storage_etag_blocks_render_before_enqueuing(self):
        result=self.run_candidates([scene(SID1,0,6),scene(SID1,7,13)],
                                    lambda sid,who:self.source(sid,etag=None))
        self.assertIsNone(result)
    def test_per_render_download_budget_counts_each_unique_video_once(self):
        huge=512*1024*1024
        same=[scene(SID1,0,6),scene(SID1,7,13)]
        self.assertIsNotNone(self.run_candidates(same,
                                lambda sid,who:self.source(sid,size=huge)))
        three=[scene(SID1,0,6),scene(SID2,0,6),scene(SID3,0,6)]
        self.assertIsNone(self.run_candidates(three,
                               lambda sid,who:self.source(sid,size=huge)))
    def test_cross_org_or_unconfirmed_video_never_renders(self):
        owner=self.source(SID1)
        owner["organisation_id"]="different-org"
        self.assertIsNone(self.run_candidates([scene(SID1,0,6),scene(SID1,7,13)],
                                              lambda sid,who:owner))
        owner["organisation_id"]=ORG;owner["status"]="pending"
        self.assertIsNone(self.run_candidates([scene(SID1,0,6),scene(SID1,7,13)],
                                              lambda sid,who:owner))
if __name__=="__main__":unittest.main()
