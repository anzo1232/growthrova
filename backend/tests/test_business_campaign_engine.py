"""Business campaign validation and provider-failure regression tests."""
import json
import unittest
from unittest.mock import patch
import requests

from business_campaign_engine import (
    BusinessCampaignError, validate_brief, normalize_candidates, generate_campaign,
    _ask_deepseek, _validate_ai_output
)

BRIEF = {
    "goal":"education","industry":"consulting","brand_name":"Local Experts",
    "style":"modern","cta":"Learn more", "approved_offer":"", "audience":"Business owners"
}
SOURCE = [
    {"timestamp_start":15,"timestamp_end":43,"title":"Why planning matters",
     "llm_reason":"Explains three tips", "score":89},
    {"timestamp_start":50,"timestamp_end":92,"title":"Common mistakes","hook":"Avoid this trap","score":85},
]


class CampaignGenerationTest(unittest.TestCase):
    def test_invalid_goals_offer_and_claims_fail_closed(self):
        with self.assertRaises(BusinessCampaignError):
            validate_brief({**BRIEF,"goal":"viral"})
        with self.assertRaises(BusinessCampaignError):
            validate_brief({**BRIEF,"goal":"offers","approved_offer":""})
        with self.assertRaises(BusinessCampaignError):
            validate_brief({**BRIEF,"cta":"Guaranteed 100% results"})
        with self.assertRaises(BusinessCampaignError):
            validate_brief({**BRIEF,"approved_offer":"Limited spots"})

    def test_invalid_timestamps_and_nan_rejected(self):
        clips=normalize_candidates(SOURCE+[
            {"timestamp_start":-1,"timestamp_end":7,"title":"bad"},
            {"timestamp_start":3,"timestamp_end":float("nan"),"title":"nan"},
            {"timestamp_start":1,"timestamp_end":400,"title":"long"},
            {"timestamp_start":60,"timestamp_end":61,"title":"okay","score":"nan"},
        ])
        self.assertEqual(len(clips),3)
        self.assertEqual(clips[-1]["score"],0)

    def test_disabled_ai_never_invokes_provider(self):
        def paid(*_): self.fail("A paid provider was called")
        result=generate_campaign(SOURCE,BRIEF,use_ai=False,ai_fn=paid)
        self.assertEqual(result["ai"]["request_count"],0)
        self.assertEqual(len(result["clips"]),2)
        self.assertTrue(all(c["review_required"] for c in result["clips"]))

    def test_no_candidate_never_invokes_provider(self):
        result=generate_campaign([],BRIEF,use_ai=True,ai_fn=lambda *_: self.fail("paid request"))
        self.assertEqual(result["ai"]["status"],"no_candidates")

    def test_ai_output_rejects_unknown_indices_and_unverified_guarantees(self):
        normalized=normalize_candidates(SOURCE)
        ideas=_validate_ai_output({"ideas":[
            {"index":99,"headline":"Foreign data","caption":"Cross customer data"},
            {"index":0,"headline":"Guaranteed results","caption":"Miracle returns"},
            {"index":1,"headline":"Common mistakes to avoid","caption":"Three common mistakes worth noting",
             "why":"Grounded explanation","creative_angle":"Education"}
        ]},normalized,BRIEF)
        self.assertEqual(set(ideas),{1})

    def test_provider_timeout_does_not_initiate_second_billable_call(self):
        calls=[]
        def failed(*args,**kwargs):
            calls.append(kwargs)
            raise requests.Timeout("unknown delivery")
        with patch.dict("os.environ",{"DEEPSEEK_API_KEY":"TEST_KEY","CLIPPR_BUSINESS_DEEPSEEK_MODEL":"deepseek-flash"}):
            response=generate_campaign(SOURCE,BRIEF,use_ai=True,
                    ai_fn=lambda c,b:_ask_deepseek(c,b,post=failed))
        self.assertEqual(len(calls),1)
        self.assertEqual(response["ai"]["status"],"unavailable")
        self.assertEqual(response["ai"]["fallback_used"],False)
        self.assertTrue(all(x["ai_status"]=="unavailable" for x in response["clips"]))

    def test_json_mode_and_bounded_provider_payload(self):
        calls=[]
        class Resp:
            status_code=200
            def json(self):
                return {
                    "choices":[{"finish_reason":"stop","message":{"content":json.dumps({"ideas":[
                        {"index":0,"headline":"Plan smarter","caption":"Why planning matters",
                         "why":"Transcript explains planning","creative_angle":"Education"}
                    ]})}}],
                    "usage":{"prompt_tokens":90,"completion_tokens":42}}
        def ok(url,**kwargs):
            calls.append((url,kwargs))
            return Resp()
        with patch.dict("os.environ",{"DEEPSEEK_API_KEY":"TEST_KEY","CLIPPR_BUSINESS_DEEPSEEK_MODEL":"deepseek-flash"}):
            data=generate_campaign(SOURCE,BRIEF,use_ai=True,ai_fn=lambda c,b:_ask_deepseek(c,b,post=ok))
        self.assertEqual(data["clips"][0]["headline"],"Plan smarter")
        self.assertEqual(data["clips"][1]["ai_status"],"not_requested")
        self.assertEqual(data["ai"]["provider"],"deepseek")
        self.assertEqual(data["ai"]["request_count"],1)
        self.assertEqual(len(calls),1)
        payload=calls[0][1]["json"]
        self.assertEqual(payload["response_format"]["type"],"json_object")
        self.assertEqual(payload["thinking"]["type"],"disabled")
        self.assertEqual(calls[0][1]["timeout"],18)

    def test_incomplete_provider_output_is_not_published(self):
        class Resp:
            status_code=200
            def json(self):
                return {"choices":[{"finish_reason":"length","message":{"content":'{"ideas":[]}'}}]}
        with patch.dict("os.environ",{"DEEPSEEK_API_KEY":"TEST_KEY"}):
            data=generate_campaign(SOURCE,BRIEF,use_ai=True,ai_fn=lambda c,b:_ask_deepseek(c,b,post=lambda *a,**kw:Resp()))
        self.assertEqual(data["ai"]["status"],"unavailable")
        self.assertTrue(all(c["review_required"] for c in data["clips"]))


if __name__=="__main__":
    unittest.main()
