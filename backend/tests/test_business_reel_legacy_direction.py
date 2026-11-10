"""Read-only legacy Reel recovery. Every provider client in these tests is fake."""
import copy
import json
import os
import unittest
import uuid
from unittest.mock import patch

import business_reel_director as director


def historical_fixture():
    cards = [
        {'id': 'craft', 'hook': 'The mangal: how Berenjak grills koobideh',
         'evidence': {'kind': 'method', 'quote': 'Koobideh lamb is shaped around a skewer and grilled over the mangal.'}},
        {'id': 'discover', 'hook': "Inspired by Tehran's kabab houses",
         'evidence': {'kind': 'heritage', 'quote': 'Tehran kababi traditions inspire warm Persian hospitality and shared tables.'}},
        {'id': 'insider', 'hook': 'Sangak: bread baked on hot river stones',
         'evidence': {'kind': 'bread', 'quote': 'Baked on a bed of hot river stones, sangak has a distinctive uneven texture.'}},
    ]
    doc = {'business': 'Berenjak', 'sourceUrl': 'https://berenjak.com/',
           'observedFacts': ['A Persian kababi restaurant'],
           'editorialShortlist': {'status': 'three_directions_ready_for_asset_intake', 'candidates': cards}}
    brief = {'business': doc['business'], 'sourceUrl': doc['sourceUrl'], 'slots': [
        {'slot': slot, 'sourceDirection': card['hook'], 'sourceEvidence': card['evidence']['quote'],
         'productionStatus': 'not_generated'} for slot, card in zip(director.SLOTS, cards)] + [
        {'slot': 'payoff', 'sourceDirection': 'Keep the original verified brand ending',
         'sourceEvidence': 'Confirm current logo and actual booking route before output.',
         'productionStatus': 'awaiting_authorised_brand_assets'}],
         'spendApproval': False, 'publishingApproval': False}
    return doc, brief


class LegacyDirectionPureTests(unittest.TestCase):
    def test_actual_saved_ground_lamb_quote_never_proposes_chicken(self):
        doc, brief = historical_fixture()
        actual = ('Most popular and loved Iranian kabab - an absolutely staple of Persian cuisine. '
                  'Onion and black pepper complement ground lamb, which is then shaped around a skewer '
                  'in its distinctive shape, and grilled over the mangal.')
        doc['editorialShortlist']['candidates'][0]['evidence']['quote'] = actual
        brief['slots'][0]['sourceEvidence'] = actual
        recovered = director.enrich_legacy_brief(brief, doc)
        prompt = recovered['slots'][0]['videoPrompt'].lower()
        self.assertIn('lamb koobideh', prompt)
        self.assertIn('ground lamb shaped around a skewer', prompt)
        self.assertNotIn('chicken', prompt)
        self.assertNotIn('saffron', prompt)
        self.assertEqual(recovered['slots'][0]['sourceEvidence'], actual)

    def test_chicken_direction_requires_its_own_evidence_and_no_invented_saffron(self):
        for evidence, expected in [
                ('Jujeh chicken skewers are cooked over the mangal.', 'jujeh chicken'),
                ('Our saffron chicken is prepared to order.', 'saffron chicken')]:
            with self.subTest(evidence=evidence):
                direction = director._direction('hook', 'method', evidence, 'Example', 'restaurant').lower()
                self.assertIn(expected, direction)
                self.assertNotIn('lamb', direction)
                self.assertNotIn('koobideh', direction)
                if 'saffron' not in evidence.lower():
                    self.assertNotIn('saffron', direction)

    def test_unspecified_kabab_does_not_invent_meat_or_ingredients(self):
        direction = director._direction('hook', 'method', 'Our kababs are grilled over the mangal.',
                                        'Example', 'restaurant').lower()
        for unsupported in ('lamb', 'chicken', 'saffron', 'koobideh'):
            self.assertNotIn(unsupported, direction)

    def test_exact_saved_pairs_recover_without_reordering_or_mutation(self):
        doc, brief = historical_fixture()
        original_doc, original_brief = copy.deepcopy(doc), copy.deepcopy(brief)
        recovered = director.enrich_legacy_brief(brief, doc)
        self.assertEqual(doc, original_doc)
        self.assertEqual(brief, original_brief)
        self.assertEqual([s['sourceCategory'] for s in recovered['slots'][:3]], ['method', 'heritage', 'bread'])
        self.assertIn('tehran', recovered['slots'][1]['videoPrompt'].lower())
        self.assertIn('sangak', recovered['slots'][2]['videoPrompt'].lower())
        for original, current in zip(brief['slots'], recovered['slots']):
            for key, value in original.items():
                self.assertEqual(current[key], value)
        self.assertEqual(recovered['slots'][3], brief['slots'][3])
        self.assertEqual(recovered['directionRecovery']['status'], 'derived_from_saved_evidence')
        self.assertFalse(recovered['spendApproval'])
        self.assertEqual(director.enrich_legacy_brief(brief, doc), recovered)

    def test_modern_plan_and_partial_existing_fields_are_never_replaced(self):
        doc, brief = historical_fixture()
        modern = director.enrich_legacy_brief(brief, doc)
        self.assertEqual(director.enrich_legacy_brief(modern, doc), modern)
        brief['slots'][1]['videoPrompt'] = 'Preserve this existing direction exactly.'
        recovered = director.enrich_legacy_brief(brief, doc)
        self.assertEqual(recovered['slots'], brief['slots'])
        self.assertEqual(recovered['directionRecovery']['reason'], 'partial_direction_requires_review')

    def test_missing_changed_or_ambiguous_evidence_stays_blocked(self):
        for kind in ('changed_quote', 'changed_hook', 'duplicate_pair', 'different_business', 'different_url', 'no_research'):
            doc, brief = historical_fixture()
            if kind == 'changed_quote': doc['editorialShortlist']['candidates'][1]['evidence']['quote'] += ' Changed'
            elif kind == 'changed_hook': doc['editorialShortlist']['candidates'][1]['hook'] += ' Changed'
            elif kind == 'duplicate_pair': doc['editorialShortlist']['candidates'][2] = copy.deepcopy(doc['editorialShortlist']['candidates'][1])
            elif kind == 'different_business': doc['business'] = 'Another restaurant'
            elif kind == 'different_url': doc['sourceUrl'] = 'https://another.example/'
            else: doc['editorialShortlist'] = {}
            original = copy.deepcopy(brief)
            with self.subTest(kind=kind):
                recovered = director.enrich_legacy_brief(brief, doc)
                self.assertEqual(recovered['slots'], original['slots'])
                self.assertEqual(recovered['directionRecovery']['status'], 'rebuild_required')
                self.assertIn('new campaign revision', recovered['directionRecovery']['nextAction'])
                self.assertEqual(brief, original)

    def test_archived_revision_never_uses_new_campaign_evidence(self):
        doc, brief = historical_fixture()
        recovered = director.enrich_legacy_brief(brief, doc, same_revision=False)
        self.assertEqual(recovered['slots'], brief['slots'])
        self.assertEqual(recovered['directionRecovery']['reason'], 'campaign_revision_changed')


class LegacyDirectionWorkbenchTests(unittest.TestCase):
    def setUp(self):
        from tests.test_business_reel_provider_bridge import BridgeTests
        import business_marketing_drafts as drafts
        import business_reel_provider_bridge as bridge
        import business_reel_workbench as reel
        BridgeTests.setUp(self)
        self.bridge, self.reel, self.drafts = bridge, reel, drafts
        saved = drafts.read_draft(self.con, self.did)
        doc = saved['document']
        original = json.loads(reel._project(self.con, self.project)['brief_json'])
        cards = doc['editorialShortlist']['candidates']
        original['slots'] = [
            {'slot': slot, 'sourceDirection': card['hook'], 'sourceEvidence': card['evidence']['quote'],
             'productionStatus': 'not_generated'}
            for slot, category in zip(director.SLOTS, ('method', 'heritage', 'bread'))
            for card in cards if card['evidence']['kind'] == category
        ] + [{key: original['slots'][3][key] for key in ('slot', 'sourceDirection', 'sourceEvidence', 'productionStatus')}]
        original.pop('directionAudit', None)
        self.original_brief = json.dumps(original, ensure_ascii=False)
        self.con.execute('UPDATE business_reel_projects SET brief_json=? WHERE id=?', (self.original_brief, self.project))
        self.con.commit()

    def assert_original_unchanged(self):
        self.assertEqual(self.reel._project(self.con, self.project)['brief_json'], self.original_brief)

    def test_actual_workbench_read_and_all_three_quotes_are_read_only(self):
        before = self.con.total_changes
        state = self.reel.read(self.con, self.project)
        self.assertEqual([s['sourceCategory'] for s in state['slots'][:3]], ['method', 'heritage', 'bread'])
        for slot, category in zip(director.SLOTS, ('method', 'heritage', 'bread')):
            quote = self.bridge.quote(self.con, self.project, slot)
            self.assertEqual(quote['sourceCategory'], category)
            self.assertGreaterEqual(len(quote['promptText']), 210)
            self.assertFalse(quote['spendAuthorisedNow'])
            self.assertEqual(quote['existingAttemptCount'], 0)
        self.assertEqual(before, self.con.total_changes)
        self.assertEqual(self.fake.calls, 0)
        self.assert_original_unchanged()

    def test_exact_approval_keeps_derived_fingerprint_and_retry_guards(self):
        quote = self.bridge.quote(self.con, self.project, 'hook')
        self.bridge.record_exact_approval(self.con, self.project, 'hook', quote['fingerprint'],
                                         self.bridge.CREDITS, 'synthetic_test_approval_only')
        approved = self.bridge.quote(self.con, self.project, 'hook')
        self.assertEqual(approved['fingerprint'], quote['fingerprint'])
        self.assertTrue(approved['approvedFingerprintMatches'])
        with self.assertRaises(self.bridge.BridgeError):
            self.bridge.record_exact_approval(self.con, self.project, 'hook', '0' * 64,
                                             self.bridge.CREDITS, 'synthetic_test_approval_only')
        with patch.dict(os.environ, {'CLIPPR_BUSINESS_RUNWAY_TEST_CAP': str(self.bridge.CREDITS)}):
            first = self.bridge.submit_preapproved(self.con, self.project, 'hook', client=self.fake, allow_paid=True)
            second = self.bridge.submit_preapproved(self.con, self.project, 'hook', client=self.fake, allow_paid=True)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.fake.calls, 1)
        self.assertEqual(self.bridge.quote(self.con, self.project, 'hook')['fingerprint'], quote['fingerprint'])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0], 1)
        self.assert_original_unchanged()

    def test_archived_campaign_remains_blocked_without_rewriting_history(self):
        saved = self.drafts.read_draft(self.con, self.did)
        self.drafts.save_draft(self.con, {'id': self.did, 'expectedRevision': 1,
            'mutationId': uuid.uuid4().hex, 'document': saved['document']})
        state = self.reel.read(self.con, self.project)
        self.assertEqual(state['directionRecovery']['reason'], 'campaign_revision_changed')
        with self.assertRaises(self.bridge.BridgeError):
            self.bridge.quote(self.con, self.project, 'hook')
        self.assertEqual(self.fake.calls, 0)
        self.assert_original_unchanged()

    def test_partial_modern_legacy_mix_keeps_fields_but_blocks_all_shot_quotes(self):
        current = self.reel.read(self.con, self.project)
        mixed = json.loads(self.original_brief)
        # One modern slot must not hide the unresolved source assignments in
        # the remaining legacy plan, or have its existing words overwritten.
        for key in ('videoPrompt', 'sourceCategory', 'cameraDirection'):
            mixed['slots'][0][key] = current['slots'][0][key]
        self.original_brief = json.dumps(mixed, ensure_ascii=False)
        self.con.execute('UPDATE business_reel_projects SET brief_json=? WHERE id=?',
                         (self.original_brief, self.project))
        self.con.commit()
        state = self.reel.read(self.con, self.project)
        self.assertEqual(state['directionRecovery']['status'], 'rebuild_required')
        self.assertEqual(state['slots'][0]['videoPrompt'], mixed['slots'][0]['videoPrompt'])
        for slot in director.SLOTS:
            with self.assertRaises(self.bridge.BridgeError) as denied:
                self.bridge.quote(self.con, self.project, slot)
            self.assertEqual(denied.exception.code, 'missing_direction')
            self.assertIn('new campaign revision', str(denied.exception))
        self.assertEqual(self.fake.calls, 0)
        self.assert_original_unchanged()


if __name__ == '__main__':
    unittest.main()
