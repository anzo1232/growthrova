"""Structured advert wording through the real writer/store contract; no inference."""
import copy
import json
import subprocess
import unittest
from tests import test_business_creative_plans as plans
from tests import test_business_complete_advert as adverts


class ConceptPropositionTests(unittest.TestCase):
    setUp = plans.CreativePlanTests.setUp
    create = plans.CreativePlanTests.create
    write = plans.CreativePlanTests.write
    plan = plans.CreativePlanTests.plan

    def test_supporting_only_alternative_is_saved_without_rewriting_siblings(self):
        self.provider.sample = plans.concepts()
        original = self.plan().json
        selected = original['concepts'][0]
        saved_choice = self.client.put(self.url+'/'+original['operationId']+'/concept-selection',
            headers=self.headers, json=dict(expectedRevision=1, expectedSelectionRevision=0,
                                            selectedConceptIds=[selected['id']]))
        self.assertEqual(saved_choice.status_code, 200, saved_choice.json)
        original = saved_choice.json
        self.provider.sample = {'concepts': [copy.deepcopy(plans.concepts()['concepts'][0])]}
        self.provider.sample['concepts'][0]['supportingLine'] = 'We offer bicycle servicing and brake adjustments.'
        self.assertNotEqual(self.provider.sample['concepts'][0]['supportingLine'], selected['supportingLine'])
        request = dict(mode='more_like_this', parentOperationId=original['operationId'],
                       conceptId=selected['id'],
                       instruction='Clarify the supporting proposition; preserve the headline, scene and CTA.')
        response = self.write(operationId='a'*32, creativePlan=request)
        self.assertEqual(response.status_code, 200, response.json)
        alternative = response.json
        self.assertEqual(alternative['state'], 'proposed', alternative)
        self.assertEqual(alternative['concepts'][1:], original['concepts'][1:])
        updated = alternative['concepts'][0]
        for key in ('headline', 'visualDirection', 'callToAction', 'buyerMotivation', 'evidence'):
            self.assertEqual(updated[key], selected[key])
        self.assertEqual(updated['supportingLine'], self.provider.sample['concepts'][0]['supportingLine'])
        self.assertEqual(updated['parentConceptId'], selected['id'])
        self.assertNotEqual(updated['id'], selected['id'])
        self.assertEqual(self.write(operationId='a'*32, creativePlan=request).json, alternative)
        reopened = self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans']
        self.assertEqual(reopened, [alternative, original])
        self.assertEqual(len(self.provider.calls), 2, 'Replay and reopen must not invoke the provider')

    def test_legacy_missing_proposition_and_empty_proposition_are_unchanged(self):
        from business_creative_plans import concept_issues
        from business_growthrova_writer import source_material
        item = {**plans.concepts()['concepts'][0], 'supportingLine': ''}
        legacy = {key: value for key, value in item.items() if key != 'supportingLine'}
        self.assertTrue(any('did not change' in issue for issue in
                            concept_issues([item], source_material(self.doc), selected=legacy)))
        self.assertTrue(any('did not change' in issue for issue in
                            concept_issues([{**item, 'supportingLine': '   '}], source_material(self.doc), selected=legacy)))
        nonempty = {**item, 'supportingLine': 'Bicycle servicing and brake adjustments.'}
        self.assertEqual(concept_issues([item], source_material(self.doc), selected=nonempty), [],
                         'Explicit removal changes requested artwork wording')
        self.assertTrue(any('did not change' in issue for issue in concept_issues(
            [{**nonempty, 'supportingLine': '  '+nonempty['supportingLine']+'  '}],
            source_material(self.doc), selected=nonempty)))
    def test_proposed_supporting_words_survive_replay_and_reopen(self):
        original = self.client.get(self.root+'/'+self.ident, headers=self.headers).json['document']
        self.provider.sample = plans.concepts()
        for concept in self.provider.sample['concepts']:
            concept['supportingLine'] = 'Bicycle servicing and brake adjustments.'
        result = self.plan()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'proposed', result.json)
        schema = self.provider.calls[0][1]['json']['text']['format']['schema']
        self.assertIn('supportingLine', schema['properties']['concepts']['items']['required'])
        self.assertEqual(result.json['concepts'][0]['supportingLine'], 'Bicycle servicing and brake adjustments.')
        self.assertEqual(self.plan().json, result.json)
        reopened = self.create().test_client().get(self.url, headers=self.headers).json
        self.assertEqual(reopened['conceptPlans'], [result.json])
        self.assertEqual(len(self.provider.calls), 1)

        # Actual frontend mutation -> real API validation/store -> advert words.
        script = '''
import {applyConceptDirection} from './src/lib/growthrovaCreativePlans.mjs';
let input='';for await (const chunk of process.stdin) input+=chunk;
const {document,plan}=JSON.parse(input);
const target=document.creatives.find(c=>c.format==='image_ad');
console.log(JSON.stringify(applyConceptDirection(document,plan,plan.concepts[0].id,target.id,plan.concepts[0],1)));
'''
        applied = subprocess.run(['node', '--input-type=module', '-e', script],
            input=json.dumps(dict(document=original, plan=result.json)), text=True,
            capture_output=True, check=True, timeout=20)
        document = json.loads(applied.stdout)
        saved = self.client.post(self.root, headers=self.headers, json={**self.payload,
            'expectedRevision': 1, 'mutationId': '4'*32, 'document': document})
        self.assertEqual(saved.status_code, 200, saved.json)
        retained = self.create().test_client().get(self.root+'/'+self.ident, headers=self.headers).json['document']
        self.assertEqual(retained['posts'][0]['supportingLine'], result.json['concepts'][0]['supportingLine'])
        self.assertEqual(retained['posts'][0]['copyDraft'], original['posts'][0]['copyDraft'])
        self.assertEqual(retained['posts'][1:], original['posts'][1:])
        from business_growthrova_images import advert_copy
        words = advert_copy(retained['posts'][0], {'name': retained['business']})
        self.assertEqual(words['supportingLine'], result.json['concepts'][0]['supportingLine'])
        self.assertEqual(len(self.provider.calls), 1, 'Apply/save/reopen cannot call the writer again')

    def test_placeholder_proposition_is_held_without_retry(self):
        self.provider.sample = plans.concepts()
        for concept in self.provider.sample['concepts']:
            concept['supportingLine'] = 'TODO: add a supporting proposition.'
        result = self.plan()
        self.assertEqual(result.json['state'], 'held', result.json)
        self.assertIn('placeholder', ' '.join(result.json['issues']))
        self.assertEqual(self.plan().json, result.json)
        self.assertEqual(len(self.provider.calls), 1)


class SelectedAdvertPropositionTests(unittest.TestCase):
    setUp = adverts.CompleteAdvertTests.setUp

    def test_selected_batch_uses_concept_words_and_preserves_original_on_reopen(self):
        import sqlite3
        from contextlib import closing
        from business_creative_plans import finish_plan
        from business_growthrova_writer import source_material, writing_context

        saved = self.flow.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json
        document = saved['document']
        proposal = plans.concepts(document['observedFacts'][0], count=3)
        proposal['concepts'][0]['supportingLine'] = document['observedFacts'][0]
        request = dict(mode='initial', parentOperationId='', conceptId='')
        candidates, issues = finish_plan(proposal, 'a'*32, request, source_material(document), None)
        self.assertEqual(issues, [])
        plan = dict(operationId='a'*32, state='proposed', creativePlan=request, concepts=candidates,
                    sourceContext=writing_context(document), brandKit=document['brandKit'])
        with closing(sqlite3.connect(self.base.path)) as con:
            con.execute('INSERT INTO growthrova_writing_requests VALUES(?,?,?,?,?,?,?,?)',
                (self.base.ident, 'a'*32, 2, '', 'a'*32, 'a'*32, 0, json.dumps(plan)))
            con.commit()
        prepared = self.flow.client.post(self.base.url+'/batches', headers=self.base.headers, json=dict(
            batchId='b'*32, planOperationId='a'*32, expectedRevision=2, day=1,
            size='square_2k', quality='standard', renderingMode='complete_advert',
            conceptIds=[candidates[0]['id']]))
        self.assertEqual(prepared.status_code, 200, prepared.json)
        url = self.base.url+'/batches/'+prepared.json['batchId']+'/slots/0'
        result = self.flow.client.post(url, headers=self.base.headers, json={'expectedRevision':2})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'held', result.json)
        prompt = self.flow.provider.calls[0][1]['json']['contents'][0]['parts'][0]['text']
        words = json.loads(prompt.split('SOURCE DATA:\n', 1)[1])['advertCopy']
        self.assertEqual(words['supportingLine'], candidates[0]['supportingLine'])
        self.assertEqual(result.json['advertCopy'], words)
        self.assertEqual(self.flow.client.post(url, headers=self.base.headers, json={'expectedRevision':2}).json, result.json)
        reopened = self.base.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        retained = reopened.get(self.base.url, headers=self.base.headers).json['candidates'][0]
        self.assertEqual(retained['advertCopy'], words)
        self.assertEqual(reopened.get(self.base.url+'/'+retained['operationId']+'/original', headers=self.base.headers).data, self.flow.png)
        self.assertEqual(reopened.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json, saved)
        self.assertEqual(len(self.flow.provider.calls), 1)
