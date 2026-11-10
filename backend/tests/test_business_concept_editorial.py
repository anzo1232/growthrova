"""Editorial feedback is scoped input, not facts, and ad questions are not captions."""
import copy
import json
import unittest
from tests import test_business_creative_plans as plans
from tests import test_business_growthrova_images as images
from business_marketing_drafts import marketing_copy_issue

class ConceptEditorialTests(unittest.TestCase):
    setUp=plans.CreativePlanTests.setUp
    create=plans.CreativePlanTests.create
    write=plans.CreativePlanTests.write
    plan=plans.CreativePlanTests.plan

    def test_question_headline_remains_a_proposal_with_reviewed_evidence(self):
        self.provider.sample=plans.concepts()
        self.provider.sample['concepts'][0]['headline']='Still on your to-do list?'
        result=self.plan()
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['state'],'proposed',result.json)
        self.assertEqual(result.json['concepts'][0]['headline'],'Still on your to-do list?')
        self.assertEqual(result.json['independentReview'],'pending')
        self.assertFalse(result.json['canPublish'])
        self.assertTrue(marketing_copy_issue({'copyDraft':'Still on your to-do list?','callToAction':'Enquire'},'Example'))
        self.assertTrue(marketing_copy_issue({'copyDraft':'A complete customer-facing caption.','graphicText':'Visual direction: add a receipt','callToAction':'Enquire'},'Example'))

    def test_corrective_more_ideas_feedback_is_grounded_and_replayed_without_overwriting(self):
        self.provider.sample=plans.concepts()
        original=self.plan().json
        sample=plans.concepts()
        headlines=['Make time for your bicycle','A closer look at your brakes','Ready for the next journey','Room to discuss your ride','Back to the bicycle','A moment for bicycle care']
        scenes=['An illustrative folded commuter jacket and bicycle lamp on a bench with room for exact headline.',
                'Editorial abstract brake cable curve with a geometric copper accent and quiet left text area.',
                'An illustrated route map and bicycle wheel shadow, overhead composition with a lower CTA zone.',
                'An editorial conversation represented by two folded paper forms, generous right text area.',
                'A bicycle resting beside a quiet doorway, soft afternoon light and a broad upper text space.',
                'A calm abstract wheel diagram beside a blank diary, wide margin for exact editable words.']
        for c,h,s in zip(sample['concepts'],headlines,scenes):c.update(headline=h,visualDirection=s)
        self.provider.sample=sample
        instruction='The first and third ideas repeat the same motivation. Explore different buyer needs and compositions using only the reviewed services.'
        request={'mode':'more_ideas','parentOperationId':original['operationId'],'conceptId':'','instruction':instruction}
        result=self.write(operationId='a'*32,creativePlan=request)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['state'],'proposed',result.json)
        sent=json.loads(self.provider.calls[-1][1]['json']['input'][0]['content'])
        self.assertEqual(sent['creativePlan']['instruction'],instruction)
        self.assertNotIn(instruction,[e['quote'] for e in sent['saved_business']['evidence']])
        self.assertEqual(sent['history'],original['concepts'])
        self.assertEqual(self.client.get(self.url,headers=self.headers).json['conceptPlans'][1],original)
        self.assertEqual(self.write(operationId='a'*32,creativePlan=request).json,result.json)
        self.assertEqual(len(self.provider.calls),2)
        for bad in ['short','x'*601,False,'Review this\x00 direction.']:
            invalid=self.write(operationId='b'*32,creativePlan={**request,'instruction':bad})
            self.assertEqual(invalid.status_code,400,invalid.json)
        self.assertEqual(len(self.provider.calls),2)
        self.assertEqual(self.write(operationId='c'*32,creativePlan={**request,'mode':'initial','parentOperationId':''}).status_code,400)

    def test_ordinary_your_business_headline_is_not_a_template_placeholder(self):
        from business_creative_plans import concept_issues
        quote='Bookkeeping for small businesses.'
        item=plans.concepts(quote)['concepts'][0]
        item.update(headline='Your business is your thing. Bookkeeping can be ours.',callToAction='Book a consultation')
        material={'business':'Ledger Lane','evidence':[{'id':'fact-0','quote':quote,'status':'owner_input'}]}
        self.assertEqual(concept_issues([item],material),[])
        for text in ['Your business','[Insert your headline]','Placeholder headline']:
            with self.subTest(text=text):
                self.assertTrue(any('placeholder' in issue for issue in concept_issues([{**item,'headline':text}],material)))


class QuestionGraphicCompositionTests(unittest.TestCase):
    def test_saved_question_graphic_composes_with_full_caption_and_cta_separate(self):
        flow=images.GrowthrovaImageTests();flow.setUp();self.addCleanup(flow.doCleanups);flow.configured()
        doc=copy.deepcopy(flow.doc)
        doc['brandKit']={'name':'QA Workshop','primary_color':'#123456','secondary_color':'#ffffff','font_style':'modern'}
        doc['posts'][0]['graphicText']='Still on your to-do list?'
        saved=flow.save_document(doc,1,'6')
        result=flow.generate(expectedRevision=2)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['state'],'proposed',result.json)
        composed=flow.client.get(flow.url+'/'+result.json['operationId']+'/static-preview?revision=2',headers=flow.headers)
        self.assertEqual(composed.status_code,200,composed.json)
        self.assertEqual(composed.json['manifest']['layout']['copy'],'Still on your to-do list?')
        self.assertEqual(composed.json['manifest']['post']['copyDraft'],doc['posts'][0]['copyDraft'])
        self.assertFalse(composed.json['manifest']['approved'])
        self.assertEqual(len(flow.provider.calls),1)
