"""Adversarial logical-negation regressions for actual pre-provider prompt gates.

These offline authored phrases are not a creative or visual-quality benchmark.
"""
import unittest

import business_creative_preflight as preflight


class NegationScopeSafetyTests(unittest.TestCase):
    def assert_mentions_people(self, phrase):
        self.assertTrue(preflight.positive_mentions(phrase, preflight.HUMANS), phrase)

    def assert_excludes_people(self, phrase):
        self.assertFalse(preflight.positive_mentions(phrase, preflight.HUMANS), phrase)

    def test_double_negative_no_people_is_not_a_ban(self):
        self.assert_mentions_people("Show a roof and not no people in the camera frame.")

    def test_do_not_avoid_is_not_an_exclusion(self):
        self.assert_mentions_people("Camera follows a roof; do not avoid workers in the shot.")

    def test_never_exclude_is_not_an_exclusion(self):
        self.assert_mentions_people("Never exclude technicians as they climb onto the roof.")

    def test_not_without_is_not_an_exclusion(self):
        self.assert_mentions_people("The video is not without people operating the ladder.")

    def test_do_not_want_without_is_not_an_exclusion(self):
        self.assert_mentions_people("We do not want a roof scene without workers inspecting the leak.")

    def test_positive_coordinated_worker_cannot_be_swallowed_by_negative_list(self):
        self.assert_mentions_people("No people and worker walks toward a roof leak with tools.")

    def test_positive_coordinated_hands_after_negation(self):
        self.assert_mentions_people("No workers or hands appear and move the camera across the roof.")

    def test_explicit_negative_list_is_safe_only_as_a_negative(self):
        self.assert_excludes_people("No people, hands or faces in the roof repair scene.")

    def test_separate_explicit_exclusions_remain_safe(self):
        self.assert_excludes_people("No people and no hands; avoid faces in the picture.")

    def test_background_exclusion_does_not_hide_foreground_worker(self):
        self.assert_mentions_people("No people in background, but a worker lifts tiles near the gutter.")

    def test_double_negative_is_enforced_in_roofing_preflight(self):
        prompt = ("Natural close view of a damaged roof with chimney flashing, "
                  "not without workers checking the tiles and gutter. "
                  "The camera moves smoothly as rain runs down the surface.")
        verdict = preflight.inspect(
            "roofing", prompt, evidence="The business website offers local roof inspections.",
            shot_purpose="Illustrate a roof-leak customer problem",
            estimated_credits=96, cap=96,
        )
        self.assertIn("synthetic_worker_or_hands", verdict["issues"])
        self.assertFalse(verdict["ready"])

    def test_synthetic_proof_double_negative_is_not_silently_cleared(self):
        pattern = r"(?:actual|real|genuine)\s+(?:customers?|clients?)"
        self.assertTrue(
            preflight.positive_mentions("We do not avoid actual customers in the advert.", pattern)
        )


class ContractNegationIntegrationTests(unittest.TestCase):
    def setUp(self):
        import sqlite3
        import uuid
        import business_scene_contracts as contracts
        import business_marketing_drafts as drafts
        from tests.test_business_marketing_drafts import document
        self.contracts=contracts
        self.con=sqlite3.connect(":memory:")
        self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        drafts.initialise(self.con)
        contracts.initialise(self.con)
        self.did="9"*32
        drafts.save_draft(self.con, {
            "id":self.did, "expectedRevision":0, "mutationId":uuid.uuid4().hex,
            "document":document(),
        })
        contracts.open_envelope(self.con,self.did,maximum_credits=100,
                                approval_reference="offline-fixture-authority")

    def test_actual_scene_contract_rejects_coordinated_positive_worker(self):
        from tests.test_business_scene_contracts import scene, request
        text=("No people and worker walks onto the roof to inspect chimney flashing. "
              "The camera follows the worker examining damaged tiles in a realistic "
              "close view with consistent scale, natural daylight and steady movement.")
        with self.assertRaises(self.contracts.ContractError) as failed:
            self.contracts.record(self.con,self.did,1,scene(),request(text),96,
                                  reviewer_reference="synthetic-offline-test")
        self.assertEqual(failed.exception.code,"scene_people_conflict")
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM business_scene_contracts").fetchone()[0],0)

    def test_policy_fingerprint_invalidates_existing_negative_prompt_review(self):
        from unittest.mock import patch
        from tests.test_business_scene_contracts import scene, request
        with patch.object(preflight,"POLICY_VERSION",3):
            self.contracts.record(self.con,self.did,1,scene(),request(),96,
                                  reviewer_reference="synthetic-offline-test")
        with self.assertRaises(self.contracts.ContractError) as failed:
            self.contracts.check(self.con,self.did,1,request(),96)
        self.assertEqual(failed.exception.code,"scene_contract_changed")


if __name__ == "__main__":
    unittest.main()
