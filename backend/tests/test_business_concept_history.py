"""Saved exploration history and explicit recovery; synthetic text transport only."""
import copy
import json
import unittest
from pathlib import Path

from tests import test_business_creative_plans as plans


def different_set():
    return json.loads((Path(__file__).parent/'fixtures/growthrova-concept-recovery-synthetic.json').read_text())


class ConceptHistoryTests(unittest.TestCase):
    setUp = plans.CreativePlanTests.setUp
    create = plans.CreativePlanTests.create
    write = plans.CreativePlanTests.write
    plan = plans.CreativePlanTests.plan

    def more(self, parent, operation):
        return self.write(operationId=operation * 32, creativePlan={
            'mode': 'more_ideas', 'parentOperationId': parent['operationId'], 'conceptId': ''})

    def test_recycling_a_grandparent_is_held_and_preserves_every_saved_set(self):
        self.provider.sample = plans.concepts()
        original = self.plan().json
        self.provider.sample = different_set()
        second = self.more(original, 'a').json
        self.assertEqual(second['state'], 'proposed', second)
        self.provider.sample = plans.concepts()
        response = self.more(second, 'b')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['state'], 'held', response.json)
        self.assertIn('repeats saved concepts', ' '.join(response.json['issues']))
        sent = json.loads(self.provider.calls[-1][1]['json']['input'][0]['content'])
        self.assertTrue({c['id'] for c in original['concepts']} <= {c['id'] for c in sent['history']})
        reopened = self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans']
        self.assertEqual(reopened[1:], [second, original])
        self.assertEqual(self.more(second, 'b').json, response.json)
        self.assertEqual(len(self.provider.calls), 3, 'Reopen and replay cannot generate again')

    def test_a_held_complete_set_can_request_new_ideas_but_not_a_scoped_variant(self):
        self.provider.sample = plans.concepts()
        original = self.plan().json
        held = self.more(original, 'a').json
        self.assertEqual(held['state'], 'held', held)
        self.provider.sample = different_set()
        recovered = self.more(held, 'b')
        self.assertEqual(recovered.status_code, 200, recovered.json)
        self.assertEqual(recovered.json['state'], 'proposed', recovered.json)
        variant = self.write(operationId='c'*32, creativePlan={'mode': 'more_like_this',
            'parentOperationId': held['operationId'], 'conceptId': held['concepts'][0]['id']})
        self.assertEqual(variant.status_code, 400, variant.json)
        self.assertEqual(len(self.provider.calls), 3)
        reopened = self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans']
        self.assertEqual(reopened[1:], [held, original])

    def test_similar_history_scene_is_held_while_intentional_variant_stays_allowed(self):
        from business_creative_plans import concept_issues
        material = {'business': 'QA Workshop', 'evidence': [{'id': 'fact-0',
            'quote': plans.concepts()['concepts'][0]['evidence'][0]['quote'], 'status': 'owner_input'}]}
        original = plans.concepts()['concepts'][0]
        changed = copy.deepcopy(original)
        changed.update(headline='Make space for the coming journey',
            visualDirection=original['visualDirection'].replace('angled daylight', 'soft daylight'))
        self.assertTrue(any('repeats saved concepts' in issue for issue in
            concept_issues([changed], material, [original])))
        self.assertEqual(concept_issues([changed], material, [original], selected=original), [])

    def test_foreign_document_history_is_not_sent_or_used_to_hold_this_business(self):
        self.provider.sample = plans.concepts()
        original = self.plan().json
        foreign_id = '9' * 32
        saved = self.client.post(self.root, headers=self.headers, json={**self.payload,
            'id': foreign_id, 'mutationId': '8'*32})
        self.assertEqual(saved.status_code, 200, saved.json)
        self.provider.sample = different_set()
        foreign = self.client.post(self.root+'/'+foreign_id+'/writing', headers=self.headers,
            json={**self.request, 'operationId': '7'*32,
                  'creativePlan': {'mode': 'initial', 'parentOperationId': '', 'conceptId': ''}})
        self.assertEqual(foreign.json['state'], 'proposed', foreign.json)
        result = self.more(original, 'a')
        self.assertEqual(result.json['state'], 'proposed', result.json)
        sent = json.loads(self.provider.calls[-1][1]['json']['input'][0]['content'])
        self.assertEqual({c['id'] for c in sent['history']}, {c['id'] for c in original['concepts']})
        self.assertEqual(result.json['diversityReview']['comparedOperationIds'], [original['operationId']])

    def test_changed_brand_does_not_poison_new_history_or_allow_stale_held_recovery(self):
        self.provider.sample = plans.concepts()
        original = self.plan().json
        held = self.more(original, 'a').json
        changed = copy.deepcopy(self.doc)
        changed['brandKit'] = {'name': 'QA Workshop', 'primary_color': '#123456',
            'secondary_color': '#ffffff', 'font_style': 'modern'}
        saved = self.client.post(self.root, headers=self.headers, json={**self.payload,
            'document': changed, 'mutationId': '8'*32, 'expectedRevision': 1})
        self.assertEqual(saved.status_code, 200, saved.json)
        self.request['expectedRevision'] = 2
        self.assertEqual(self.more(held, 'b').status_code, 400)
        self.assertEqual(len(self.provider.calls), 2)
        self.provider.sample = different_set()
        current = self.plan(operationId='c'*32).json
        self.assertEqual(current['state'], 'proposed', current)
        self.provider.sample = plans.concepts()
        response = self.more(current, 'd')
        self.assertEqual(response.json['state'], 'proposed', response.json)
        self.assertEqual(response.json['diversityReview']['comparedOperationIds'], [current['operationId']])

    def test_history_window_is_bounded_and_excludes_stale_or_uncertain_sets(self):
        from business_creative_plans import comparison_history
        parent = {'operationId': 'parent', 'state': 'proposed', 'sourceContext': {'business':'QA'},
            'brandKit': None, 'concepts': [{**c, 'id': 'parent-'+str(i)} for i,c in enumerate(plans.concepts()['concepts'])]}
        def record(operation, **changes):
            return {**parent, 'operationId': operation,
                'concepts': [{**c, 'id': operation+'-'+str(i)} for i,c in enumerate(parent['concepts'])], **changes}
        recent = [record('uncertain', state='uncertain'), record('stale', sourceContext={'business':'Other'}),
                  record('brand', brandKit={'name':'Other'}), record('empty', concepts=[]),
                  record('recent'), record('older'), record('oldest')]
        concepts, operations = comparison_history(parent, recent, parent['sourceContext'], None)
        self.assertEqual(operations, ['parent', 'recent', 'older'])
        self.assertEqual(len(concepts), 18)
        self.assertEqual(len({c['id'] for c in concepts}), 18)
        self.assertEqual(comparison_history(parent, [recent[0]]*10+[recent[4]], parent['sourceContext'], None)[1], ['parent'])
