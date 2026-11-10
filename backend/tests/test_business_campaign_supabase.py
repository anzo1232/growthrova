import unittest
from unittest.mock import Mock
import requests
from business_campaign_supabase import (
    CampaignSupabase, StoreError,CampaignForbidden,CampaignStorageUnavailable
)
OWNER="11111111-1111-4111-8111-111111111111"
ORG="33333333-3333-4333-8333-333333333333"
BRAND="55555555-5555-4555-8555-555555555555"
CID="99999999-9999-4999-8999-999999999999"
SCENES=[{"source_id":"a"*32,"start_s":0,"end_s":12,"video_url":"r2://business/secret",
         "unknown_jwt":"jwt-private"}]

class Http:
    def __init__(self):self.calls=[];self.responses=[]
    def request(self,method,url,params=None,json=None,headers=None,timeout=None):
        self.calls.append({"method":method,"url":url,"params":params,
                           "json":json,"headers":headers,"timeout":timeout})
        if self.responses:
            return self.responses.pop(0)
        return self.response([])
    @staticmethod
    def response(payload,status=200):
        r=Mock()
        r.status_code=status
        r.content=b"x"
        r.json.return_value=payload
        return r

class CampaignRlsProxyTests(unittest.TestCase):
    def setUp(self):
        self.http=Http()
        self.repo=CampaignSupabase("https://staging.example.supabase.co",
                                   "public-anon-key","customer-jwt",http=self.http)
    def test_create_forwards_user_jwt_no_privileged_key_and_scrubs_source_urls(self):
        self.http.responses=[self.http.response([{"id":CID,"revision":1,"updated_at":"today"}],201)]
        saved=self.repo.save(OWNER,ORG,"Content ideas","awareness",BRAND,SCENES,"Review",create_id=CID)
        call=self.http.calls[0]
        self.assertEqual(saved["id"],CID)
        self.assertEqual(call["headers"]["Authorization"],"Bearer customer-jwt")
        self.assertEqual(call["headers"]["apikey"],"public-anon-key")
        self.assertEqual(call["params"],None)
        self.assertEqual(call["json"]["owner_id"],OWNER)
        self.assertEqual(call["json"]["organisation_id"],ORG)
        self.assertEqual(call["json"]["scenes"][0]["review_status"],"draft")
        self.assertNotIn("video_url",str(call["json"]))
        self.assertNotIn("unknown_jwt",str(call["json"]))
    def test_revision_cas_filters_previous_revision_at_db_not_client(self):
        self.http.responses=[self.http.response([{"id":CID,"revision":3,"updated_at":"later"}])]
        saved=self.repo.save(OWNER,ORG,"New caption","offers",BRAND,SCENES,id=CID,revision=2)
        self.assertEqual(saved["revision"],3)
        request=self.http.calls[0]
        self.assertEqual(request["method"],"PATCH")
        self.assertEqual(request["params"]["revision"],"eq.2")
        self.assertEqual(request["params"]["owner_id"],"eq."+OWNER)
        self.assertEqual(request["params"]["organisation_id"],"eq."+ORG)
        self.assertEqual(request["json"]["revision"],3)
    def test_revision_conflict_does_not_claim_save(self):
        self.http.responses=[self.http.response([])]
        with self.assertRaisesRegex(StoreError,"changed"):
            self.repo.save(OWNER,ORG,"New caption","offers",BRAND,SCENES,id=CID,revision=1)
    def test_lost_create_acknowledgement_replays_same_saved_campaign(self):
        expected={"id":CID,"organisation_id":ORG,"name":"Campaign idea",
                  "goal":"awareness","brand_id":BRAND,"notes":"",
                  "scenes":[{"source_id":"a"*32,"start_s":0.0,"end_s":12.0,
                             "review_status":"draft","note":""}],
                  "revision":1,"updated_at":"now"}
        self.http.responses=[self.http.response({"code":"23505"},409),
                             self.http.response([expected])]
        item=self.repo.save(OWNER,ORG,"Campaign idea","awareness",BRAND,
                            SCENES,create_id=CID)
        self.assertTrue(item["replayed"])
        self.assertEqual(item["id"],CID)
        self.assertEqual([x["method"] for x in self.http.calls],["POST","GET"])
        self.assertEqual(self.http.calls[0]["json"]["id"],CID)
    def test_reused_create_id_cannot_change_existing_payload(self):
        existing={"id":CID,"organisation_id":ORG,"name":"Someone else's draft",
                  "goal":"awareness","brand_id":BRAND,"notes":"",
                  "scenes":[],"revision":1,"updated_at":"now"}
        self.http.responses=[self.http.response({"code":"23505"},409),
                             self.http.response([existing])]
        with self.assertRaisesRegex(StoreError,"another campaign"):
            self.repo.save(OWNER,ORG,"Campaign idea","awareness",BRAND,
                           SCENES,create_id=CID)

    def test_read_for_other_user_returns_no_campaign(self):
        self.http.responses=[self.http.response([])]
        self.assertIsNone(self.repo.get(OWNER,CID))
        self.assertEqual(self.http.calls[0]["params"]["owner_id"],"eq."+OWNER)
    def test_owner_scoped_list_and_delete(self):
        self.repo.list(OWNER,ORG)
        self.repo.delete(OWNER,ORG,CID)
        self.assertEqual(self.http.calls[0]["params"]["organisation_id"],"eq."+ORG)
        self.assertEqual(self.http.calls[1]["params"]["owner_id"],"eq."+OWNER)
        self.assertEqual(self.http.calls[1]["method"],"DELETE")
    def test_request_failure_provides_safe_storage_error(self):
        self.http.responses=[self.http.response({"code":"42501"},403)]
        with self.assertRaises(CampaignForbidden):self.repo.list(OWNER,ORG)
        self.http.responses=[self.http.response({"code":"PGRST301"},503)]
        with self.assertRaises(CampaignStorageUnavailable):self.repo.list(OWNER,ORG)
    def test_malformed_success_payload_is_not_reported_as_saved(self):
        self.http.responses=[self.http.response([{"status":"unknown"}])]
        with self.assertRaises(CampaignStorageUnavailable):
            self.repo.save(OWNER,ORG,"Campaign idea","awareness",BRAND,SCENES,create_id=CID)
        self.http.responses=[self.http.response({"unexpected":"not an array"})]
        with self.assertRaises(CampaignStorageUnavailable):
            self.repo.list(OWNER,ORG)

    def test_validation_prevents_network_work(self):
        with self.assertRaises(StoreError):
            self.repo.save(OWNER,ORG,"x","awareness",BRAND,SCENES)
        with self.assertRaises(StoreError):
            self.repo.save(OWNER,ORG,"Good draft","awareness","wrong",SCENES)
        self.assertFalse(self.http.calls)
    def test_network_exception_fails_closed_not_retrying_unsafe_write(self):
        class Offline:
            calls=0
            def request(self,*a,**kw):
                self.calls+=1
                raise requests.ConnectionError("private endpoint secret")
        offline=Offline()
        repo=CampaignSupabase("https://staging.example.supabase.co","anon","jwt",http=offline)
        with self.assertRaises(CampaignStorageUnavailable) as exc:
            repo.save(OWNER,ORG,"Campaign","awareness",BRAND,SCENES,create_id=CID)
        self.assertNotIn("private endpoint",str(exc.exception))
        self.assertEqual(offline.calls,1)

if __name__=="__main__":unittest.main()
