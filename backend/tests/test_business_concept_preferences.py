"""Explicit business feedback through real preview HTTP/SQLite; no paid inference."""
import copy
import json
import unittest
import requests
from tests import test_business_creative_plans as plans
from tests.test_business_concept_history import different_set
from tests.test_business_growthrova_preview import OTHER, ORG


class ConceptPreferenceTests(unittest.TestCase):
    setUp = plans.CreativePlanTests.setUp
    create = plans.CreativePlanTests.create
    write = plans.CreativePlanTests.write
    plan = plans.CreativePlanTests.plan

    def initial(self):
        self.provider.sample = plans.concepts()
        result = self.plan()
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def feedback(self, result, selected, **extra):
        return self.client.put(self.url+'/'+result['operationId']+'/concept-selection', headers=self.headers,
            json={'expectedRevision':1, 'expectedSelectionRevision':result['selectionRevision'],
                  'selectedConceptIds':selected, **extra})

    def more(self, parent, operation='a'):
        self.provider.sample = different_set()
        return self.write(operationId=operation*32, creativePlan={'mode':'more_ideas',
            'parentOperationId':parent['operationId'], 'conceptId':''})

    def sent_preferences(self):
        sent = json.loads(self.provider.calls[-1][1]['json']['input'][0]['content'])
        return sent.get('explicit_preferences', {}).get('entries', [])

    def test_existing_favourite_influences_next_plan_and_snapshot_survives_reversal(self):
        original = self.initial()
        chosen = original['concepts'][0]
        saved = self.feedback(original, [chosen['id']])
        self.assertEqual(saved.status_code, 200, saved.json)
        result = self.more(original)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual([(e['conceptId'], e['decision']) for e in self.sent_preferences()], [(chosen['id'],'favourite')])
        snapshot = result.json['preferenceContext']
        self.assertEqual(snapshot['entries'][0]['headline'], chosen['headline'])
        reversed_result = self.feedback(saved.json, [])
        self.assertEqual(reversed_result.status_code, 200, reversed_result.json)
        # A fresh explicit operation observes the reversal, not an old replay.
        next_result = self.more(original, 'b')
        self.assertEqual(next_result.status_code, 200, next_result.json)
        self.assertEqual(self.sent_preferences(), [])
        reopened = self.create().test_client().get(self.url, headers=self.headers).json
        prior = next(p for p in reopened['conceptPlans'] if p['operationId']==result.json['operationId'])
        self.assertEqual(prior['preferenceContext'], snapshot)
        self.assertEqual(self.more(original).json, result.json, 'Lost acknowledgement replays original request and preference snapshot')
        self.assertEqual(len(self.provider.calls), 3)

    def test_reject_reason_reopen_reset_and_conflict_preserve_originals(self):
        original = self.initial()
        first, second = [c['id'] for c in original['concepts'][:2]]
        extra={'rejectedConceptIds':[second], 'preferenceNotes':{second:{'aspect':'imagery','reason':'Prefer scenes with fewer objects.'}}}
        response = self.feedback(original, [first], **extra)
        self.assertEqual(response.status_code, 200, response.json)
        saved = response.json
        self.assertEqual(self.feedback(original, [first], **extra).json, saved, 'Exact lost acknowledgement is idempotent')
        self.assertEqual(self.feedback(original, []).status_code, 409)
        reopened = self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans'][0]
        self.assertEqual(reopened, saved)
        self.assertEqual(saved['concepts'], original['concepts'])
        self.more(original)
        self.assertEqual([(e['decision'], e['aspect'], e['reason']) for e in self.sent_preferences()],
                         [('favourite','',''), ('reject','imagery','Prefer scenes with fewer objects.')])
        reset = self.feedback(saved, [], rejectedConceptIds=[], preferenceNotes={})
        self.assertEqual(reset.status_code, 200, reset.json)
        self.assertEqual(reset.json['concepts'], original['concepts'])
        self.assertEqual(reset.json['rejectedConceptIds'], [])
        self.more(original, 'b')
        self.assertEqual(self.sent_preferences(), [])
        self.assertEqual(len(self.provider.calls), 3, 'Feedback/reset never invoke an image or text provider')

    def test_unfavourite_removes_its_reason_and_malformed_selection_is_actionable(self):
        original=self.initial()
        chosen=original['concepts'][0]['id']
        saved=self.feedback(original,[chosen],preferenceNotes={chosen:{'aspect':'tone','reason':'Calm and direct.'}})
        self.assertEqual(saved.status_code,200,saved.json)
        malformed=self.feedback(saved.json,None)
        self.assertEqual(malformed.status_code,400,malformed.json)
        cleared=self.feedback(saved.json,[])
        self.assertEqual(cleared.status_code,200,cleared.json)
        self.assertEqual(cleared.json['preferenceNotes'],{})
        self.assertEqual(len(self.provider.calls),1)

    def test_invalid_foreign_and_stale_feedback_never_reaches_provider(self):
        original = self.initial()
        chosen = original['concepts'][0]['id']
        for extra in ({'rejectedConceptIds':[chosen]}, {'rejectedConceptIds':['foreign']},
                      {'preferenceNotes':{chosen:{'aspect':'performance','reason':'winner'}}},
                      {'preferenceNotes':{chosen:{'aspect':'tone','reason':'x'*301}}},
                      {'preferenceNotes':{chosen:{'aspect':'tone','reason':'bad\x00reason'}}}):
            response=self.feedback(original,[chosen],**extra)
            self.assertEqual(response.status_code,400,response.json)
        foreign=self.client.put(self.url.replace(ORG, OTHER)+'/'+original['operationId']+'/concept-selection',
            headers=self.headers,json={})
        self.assertEqual(foreign.status_code,403)
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(self.client.get(self.url,headers=self.headers).json['conceptPlans'][0],original)

    def test_other_document_and_changed_brand_choices_are_not_preference_authority(self):
        original=self.initial()
        self.feedback(original,[original['concepts'][0]['id']])
        foreign_id='9'*32
        saved=self.client.post(self.root,headers=self.headers,json={**self.payload,'id':foreign_id,'mutationId':'8'*32})
        self.assertEqual(saved.status_code,200,saved.json)
        self.provider.sample=plans.concepts()
        other=self.client.post(self.root+'/'+foreign_id+'/writing',headers=self.headers,json={**self.request,
            'creativePlan':{'mode':'initial','parentOperationId':'','conceptId':''}})
        self.assertEqual(other.status_code,200,other.json)
        self.assertEqual(self.sent_preferences(),[])

        changed=copy.deepcopy(self.doc)
        changed['brandKit']={'name':'Synthetic workshop','primary_color':'#123456','secondary_color':'#ffffff','font_style':'modern'}
        saved=self.client.post(self.root,headers=self.headers,json={**self.payload,'document':changed,'expectedRevision':1,'mutationId':'7'*32})
        self.assertEqual(saved.status_code,200,saved.json)
        result=self.write(operationId='b'*32,expectedRevision=2,creativePlan={'mode':'initial','parentOperationId':'','conceptId':''})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(self.sent_preferences(),[])

    def test_changed_preferences_cannot_retry_an_uncertain_same_parent_request(self):
        original=self.initial()
        chosen=original['concepts'][0]['id']
        saved=self.feedback(original,[chosen]).json
        self.provider.failure=requests.Timeout('Synthetic lost provider acknowledgement')
        uncertain=self.more(original)
        self.assertEqual(uncertain.json['state'],'uncertain',uncertain.json)
        self.feedback(saved,[])
        calls=len(self.provider.calls)
        self.provider.failure=None
        retry=self.more(original,'b')
        self.assertEqual(retry.status_code,409,retry.json)
        self.assertEqual(retry.json['code'],'operation_conflict')
        self.assertEqual(len(self.provider.calls),calls)
        self.assertEqual(self.more(original).json,uncertain.json)

    def variant(self, original):
        self.provider.sample = {'concepts': [copy.deepcopy(plans.concepts()['concepts'][0])]}
        self.provider.sample['concepts'][0].update(headline='Prepare for the ride ahead',
            visualDirection='Illustrative front wheel with a folded jacket and open upper space for words.')
        response = self.write(operationId='c'*32, creativePlan={'mode':'more_like_this',
            'parentOperationId':original['operationId'], 'conceptId':original['concepts'][0]['id']})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['state'], 'proposed', response.json)
        return response.json

    def test_clearing_a_shared_sibling_does_not_revive_an_older_favourite_after_reopen(self):
        original = self.initial()
        sibling = original['concepts'][1]['id']
        saved_original = self.feedback(original, [sibling]).json
        variant = self.variant(saved_original)
        selected = self.feedback(variant, [sibling]).json
        cleared = self.feedback(selected, []).json
        self.assertEqual(cleared['selectedConceptIds'], [])
        self.client = self.create().test_client()
        result = self.more(variant)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.sent_preferences(), [],
            'Cleared sibling feedback must not fall back to an older set favourite')
        history = self.client.get(self.url, headers=self.headers).json['conceptPlans']
        retained = next(p for p in history if p['operationId'] == original['operationId'])
        self.assertEqual(retained, saved_original, 'Guidance reversal must preserve the original set')
        self.assertEqual(len(self.provider.calls), 3, 'Choice/clear/reopen do not generate')

    def test_later_feedback_on_an_older_set_overrides_newer_set_choice_only_for_that_sibling(self):
        original = self.initial()
        sibling, other = [c['id'] for c in original['concepts'][1:3]]
        variant = self.variant(original)
        saved_variant = self.feedback(variant, [sibling, other]).json
        saved_original = self.feedback(original, [], rejectedConceptIds=[sibling],
            preferenceNotes={sibling:{'aspect':'imagery','reason':'This scene no longer suits us.'}}).json
        self.client = self.create().test_client()
        result = self.more(variant)
        self.assertEqual(result.status_code, 200, result.json)
        choices = {entry['conceptId']:entry for entry in self.sent_preferences()}
        self.assertEqual(choices[sibling]['decision'], 'reject',
            'Latest explicit feedback wins, not the set creation order')
        self.assertEqual(choices[sibling]['reason'], 'This scene no longer suits us.')
        self.assertEqual(choices[other]['decision'], 'favourite', 'Unrelated sibling choice is preserved')
        self.assertEqual(self.feedback(original, [sibling]).status_code, 409,
            'A conflict cannot change guidance or its ordering')
        history = self.client.get(self.url, headers=self.headers).json['conceptPlans']
        self.assertEqual(next(p for p in history if p['operationId']==variant['operationId']), saved_variant)
        self.assertEqual(next(p for p in history if p['operationId']==original['operationId']), saved_original)
        self.assertEqual(len(self.provider.calls), 3)
