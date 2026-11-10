"""Six-card planning and explicit one-to-three image sets, synthetic provider only."""
import copy
import json
import sqlite3
import unittest
from contextlib import closing
from tests import test_business_creative_plans as plans
from tests import test_business_image_batches as batches


six_concepts = plans.concepts


class SixConceptTests(unittest.TestCase):
    setUp=plans.CreativePlanTests.setUp
    create=plans.CreativePlanTests.create
    write=plans.CreativePlanTests.write

    def test_six_cards_three_explained_recommendations_replay_and_scoped_variant(self):
        self.provider.sample=six_concepts()
        request={'mode':'initial','parentOperationId':'','conceptId':'','conceptCount':6}
        response=self.write(creativePlan=request)
        self.assertEqual(response.status_code,200,response.json)
        initial=response.json
        self.assertEqual(initial['state'],'proposed',initial)
        self.assertEqual(len(initial['concepts']),6)
        self.assertEqual(len(initial['recommendations']),3)
        self.assertEqual([r['conceptId'] for r in initial['recommendations']], [c['id'] for c in initial['concepts'][:3]])
        self.assertEqual(initial['selectedConceptIds'],[], 'Editorial suggestions must not select favourites')
        self.assertEqual(self.write(creativePlan=request).json,initial)
        self.provider.sample={'concepts':[copy.deepcopy(initial['concepts'][0])]}
        for key in ('id','parentConceptId'):self.provider.sample['concepts'][0].pop(key)
        self.provider.sample['concepts'][0].update(headline='Prepare for the journey ahead',visualDirection='An illustrated bicycle lamp and folded route map with clear upper text space and warm directional light.')
        variant=self.write(operationId='a'*32,creativePlan={'mode':'more_like_this','parentOperationId':initial['operationId'],
            'conceptId':initial['concepts'][0]['id'],'instruction':'Develop the commuter idea with a map and directional light.'})
        self.assertEqual(variant.status_code,200,variant.json)
        self.assertEqual(variant.json['concepts'][1:],initial['concepts'][1:])
        self.assertNotIn(initial['concepts'][0]['id'],[r['conceptId'] for r in variant.json['recommendations']])
        self.assertEqual(self.create().test_client().get(self.url,headers=self.headers).json['conceptPlans'][1],initial)
        self.assertEqual(len(self.provider.calls),2)

    def test_favourites_can_keep_all_six_without_selecting_a_billable_batch(self):
        self.provider.sample=six_concepts()
        initial=self.write(creativePlan={'mode':'initial','parentOperationId':'','conceptId':'','conceptCount':6}).json
        ids=[c['id'] for c in initial['concepts']]
        response=self.client.put(self.url+'/'+initial['operationId']+'/concept-selection',headers=self.headers,
            json={'expectedRevision':1,'expectedSelectionRevision':0,'selectedConceptIds':ids})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['selectedConceptIds'],ids)
        self.assertEqual(len(self.provider.calls),1,'Favouriting cannot invoke a provider')

    def test_new_request_defaults_to_six_even_without_count_hint(self):
        self.provider.sample=six_concepts()
        result=self.write(creativePlan={'mode':'initial','parentOperationId':'','conceptId':''})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['state'],'proposed',result.json)
        self.assertEqual(len(result.json['concepts']),6)

    def test_duplicate_editorial_recommendation_is_held_without_retry(self):
        self.provider.sample=six_concepts()
        self.provider.sample['recommendations'][2]['conceptIndex']=0
        result=self.write(creativePlan={'mode':'initial','parentOperationId':'','conceptId':'','conceptCount':6})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['state'],'held',result.json)
        self.assertIn('recommendations',' '.join(result.json['issues']))
        self.assertEqual(len(self.provider.calls),1)


class SelectedBatchTests(unittest.TestCase):
    setUp=batches.ImageBatchTests.setUp
    prepare=batches.ImageBatchTests.prepare
    slot=batches.ImageBatchTests.slot
    def test_six_plan_requires_explicit_one_to_three_selection_and_retains_exact_subset(self):
        extra=copy.deepcopy(self.plan['concepts'])
        for i,c in enumerate(extra,4):c['id']=self.plan_id+'-'+str(i)
        self.plan['concepts']+=extra
        with closing(sqlite3.connect(self.f.path)) as con:
            con.execute('UPDATE growthrova_writing_requests SET result_json=?',(json.dumps(self.plan),));con.commit()
        self.assertEqual(self.prepare().status_code,400,'A six-card set must never silently generate every card')
        for ids in ([],[c['id'] for c in self.plan['concepts'][:4]],['foreign'],[extra[0]['id']]*2):
            result=self.prepare(conceptIds=ids)
            self.assertEqual(result.status_code,400,result.json)
        selected=[extra[2]['id'],self.plan['concepts'][0]['id']]
        response=self.prepare(conceptIds=selected)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual([s['concept']['id'] for s in response.json['slots']],selected)
        self.assertEqual(response.json['creditEstimate'],2)
        self.assertEqual(self.prepare(conceptIds=selected).json,response.json)
        self.assertEqual(self.prepare(conceptIds=selected[::-1]).status_code,409)
        self.assertEqual(self.slot(2).status_code,400)
        self.assertEqual(len(self.f.provider.calls),0)
        self.assertEqual(self.slot(0).status_code,200)
        reopened=self.f.create().test_client().get(self.f.url,headers=self.f.headers).json['batches'][0]
        self.assertEqual(len(reopened['slots']),2)
        self.assertEqual(reopened['slots'][0]['state'],'proposed')
        single=self.prepare(batchId='e'*32,conceptIds=[extra[0]['id']])
        self.assertEqual(single.status_code,200,single.json)
        self.assertEqual(single.json['creditEstimate'],1)
        self.assertEqual(len(self.f.provider.calls),1)
