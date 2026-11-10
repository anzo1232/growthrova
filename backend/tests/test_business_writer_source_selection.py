"""Actual Pimlico source replay; no paid inference or quality-pass simulation."""
import copy
import json
from pathlib import Path
import unittest

from business_growthrova_writer import provider_payload, provider_source_material, evaluate_writing


class WriterSourceSelectionTests(unittest.TestCase):
    def test_distinct_owner_details_qualifications_and_source_ids_are_preserved(self):
        facts = [
            {'id': 'fact-1', 'quote': 'Appointments are available for wheel building.',
             'status': 'owner_correction', 'sourceUrl': 'https://example.org/service'},
            {'id': 'brief-offer', 'quote': 'Appointments are available for wheel building.\nTouring bicycles only.',
             'status': 'owner_input', 'sourceUrl': ''},
            {'id': 'brief-positioning', 'quote': 'Do not imply same-day availability.',
             'status': 'owner_input', 'sourceUrl': ''},
            {'id': 'source-offer', 'quote': 'Unreviewed availability must not dilute the reviewed details.',
             'status': 'linked_website_claim_unconfirmed', 'sourceUrl': 'https://example.org/service'},
        ]
        material = {'business': 'Synthetic workshop', 'evidence': facts}
        before = copy.deepcopy(material)
        selected = provider_source_material(material)
        self.assertEqual(selected['evidence'], facts[:3])
        self.assertEqual(material, before)
        # Omission never creates an owner assertion or a substitute source id.
        for status in ('unknown', None):
            material['evidence'] = [{**facts[0], 'status': status}]
            self.assertEqual(provider_source_material(material)['evidence'], [])

    def test_actual_pimlico_brief_does_not_repeat_facts_as_another_offer(self):
        archived = json.loads((Path(__file__).parent / 'fixtures/growthrova-writing-pimlico-reviewed.json').read_text())
        material = archived['material']
        before = copy.deepcopy(material)
        # Config is deliberately synthetic; provider_payload never calls HTTP.
        from business_growthrova_writer import WriterConfig
        config = WriterConfig(model='synthetic-contract-model')
        payload, _ = provider_payload(config, material, 'warm and informative')
        sent = json.loads(payload['input'][0]['content'])['saved_business']
        ids = {item['id'] for item in sent['evidence']}
        self.assertNotIn('brief-offer', ids)
        self.assertIn('brief-positioning', ids)  # Preserve distinct owner wording, including qualifications.
        for ident in ('fact-2', 'fact-3', 'fact-8', 'brief-callToAction', 'brief-constraints'):
            self.assertIn(ident, ids)
        self.assertEqual(material, before)
        # Historical output is retained exactly, not silently rewritten or
        # newly called commercially accepted by input selection.
        issues = evaluate_writing(archived['sample'], material)
        self.assertTrue(any('Post 2: caption contains generic filler' in issue for issue in issues), issues)
        self.assertTrue(any('Post 3: caption contains generic filler' in issue for issue in issues), issues)
        self.assertFalse(any('call to action' in issue for issue in issues), issues)

