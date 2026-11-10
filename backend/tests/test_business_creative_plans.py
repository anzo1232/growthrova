"""Nonbillable provider-contract evidence; these are fictional QA businesses."""
import copy
import json
import sqlite3
from pathlib import Path
from contextlib import closing
import unittest
import requests
from tests import test_business_growthrova_writer as writer_tests
from tests.test_business_growthrova_preview import ORG, OTHER


def concepts(quote='We offer bicycle servicing and brake adjustments.', count=6):
    sample = json.loads((Path(__file__).parent/'fixtures/growthrova-concepts-synthetic.json').read_text())
    for concept in sample['concepts']:
        concept['evidence'] = [{'id':'fact-0','quote':quote}]
    if count == 3:  # Existing saved three-card plans remain readable.
        sample['concepts'] = sample['concepts'][:3]
        sample.pop('recommendations')
    return sample


class CreativePlanTests(unittest.TestCase):
    setUp = writer_tests.GrowthrovaWriterTests.setUp
    create = writer_tests.GrowthrovaWriterTests.create
    write = writer_tests.GrowthrovaWriterTests.write

    def plan(self, **changes):
        return self.write(creativePlan={'mode': 'initial', 'parentOperationId': '', 'conceptId': ''}, **changes)

    def test_empty_library_six_concepts_reserve_replay_and_reopen_without_touching_owner_work(self):
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        self.provider.sample = concepts()
        response = self.plan()
        self.assertEqual(response.status_code, 200, response.json)
        result = response.json
        self.assertEqual(result['state'], 'proposed', result)
        self.assertEqual(len(result['concepts']), 6)
        self.assertEqual(len({c['id'] for c in result['concepts']}), 6)
        self.assertEqual(result['selectedConceptIds'], [])
        self.assertEqual(result['independentReview'], 'pending')
        self.assertEqual(self.plan().json, result)
        self.assertEqual(len(self.provider.calls), 1)
        reopened = self.create().test_client().get(self.url, headers=self.headers).json
        self.assertEqual(reopened['conceptPlans'], [result])
        self.assertEqual(reopened['proposals'], [])
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)
        sent = json.loads(self.provider.calls[0][1]['json']['input'][0]['content'])
        self.assertEqual(sent['saved_business']['business'], self.doc['business'])
        self.assertEqual(sent['saved_brand'], None)
        self.assertTrue(all(c['heroVisual'] and c['conceptLogic'] for c in result['concepts']))
        schema = self.provider.calls[0][1]['json']['text']['format']['schema']
        required = schema['properties']['concepts']['items']['required']
        self.assertIn('heroVisual', required)
        self.assertIn('conceptLogic', required)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_writing_requests').fetchone()[0], 1)

    def test_more_like_this_preserves_siblings_original_and_multiselection_is_durable(self):
        self.provider.sample = concepts()
        initial = self.plan().json
        self.assertEqual(initial.get('state'), 'proposed', initial)
        selected = [c['id'] for c in initial['concepts'][:2]]
        selection_url = self.url+'/'+initial['operationId']+'/concept-selection'
        payload = {'expectedRevision': 1, 'expectedSelectionRevision': 0, 'selectedConceptIds': selected}
        saved = self.client.put(selection_url, headers=self.headers, json=payload)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json['selectedConceptIds'], selected)
        self.assertEqual(self.client.put(selection_url, headers=self.headers, json=payload).json, saved.json)
        conflict = self.client.put(selection_url, headers=self.headers, json={**payload, 'selectedConceptIds': []})
        self.assertEqual(conflict.status_code, 409)
        self.provider.sample = {'concepts': [copy.deepcopy(concepts()['concepts'][0])]}
        self.provider.sample['concepts'][0].update(headline='Prepare for the ride ahead',
            visualDirection='Illustrative bicycle front wheel with a folded commuter jacket; preserve open upper space for exact copy.')
        request = {'mode': 'more_like_this', 'parentOperationId': initial['operationId'], 'conceptId': selected[0]}
        variant = self.write(operationId='a'*32, creativePlan=request)
        self.assertEqual(variant.status_code, 200, variant.json)
        alternative = variant.json
        self.assertEqual(alternative['state'], 'proposed', alternative)
        self.assertEqual(alternative['concepts'][1:], initial['concepts'][1:])
        self.assertEqual(alternative['concepts'][0]['parentConceptId'], selected[0])
        self.assertNotEqual(alternative['concepts'][0]['id'], selected[0])
        self.assertEqual(alternative['selectedConceptIds'], [])
        history = self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans']
        self.assertEqual(history[1], saved.json)
        self.assertEqual(history[0], alternative)
        self.assertEqual(len(self.provider.calls), 2)

    def test_repeated_directions_unreviewed_evidence_and_unchanged_alternatives_are_held(self):
        self.provider.sample = concepts()
        self.provider.sample['concepts'][1]['visualDirection'] = self.provider.sample['concepts'][0]['visualDirection']
        self.provider.sample['concepts'][2]['evidence'] = [{'id': 'unknown', 'quote': 'Unsupported service claim.'}]
        result = self.plan()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'held', result.json)
        self.assertIn('distinct visual directions', ' '.join(result.json['issues']))
        self.assertIn('reviewed source', ' '.join(result.json['issues']))
        self.assertEqual(len(result.json['concepts']), 6)
        self.assertEqual(self.plan().json, result.json)
        self.assertEqual(len(self.provider.calls), 1)

    def test_uncertainty_and_foreign_scope_never_retry_or_call_provider(self):
        self.provider.failure = requests.Timeout('synthetic lost acknowledgement')
        result = self.plan()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'uncertain')
        self.assertEqual(self.plan().json, result.json)
        self.auth.owner = OTHER
        self.assertEqual(self.plan(operationId='a'*32).status_code, 403)
        self.assertEqual(len(self.provider.calls), 1)

    def test_requested_variant_direction_is_validated_and_delivered_without_sibling_edits(self):
        self.provider.sample = concepts()
        initial = self.plan().json
        self.assertEqual(initial.get('state'), 'proposed', initial)
        self.provider.sample = {'concepts': [copy.deepcopy(concepts()['concepts'][0])]}
        self.provider.sample['concepts'][0]['headline'] = 'Ready for the next ride'
        direction = {'mode': 'more_like_this', 'parentOperationId': initial['operationId'],
                     'conceptId': initial['concepts'][0]['id'],
                     'instruction': 'Make the illustration more editorial with a quieter background.'}
        response = self.write(operationId='a'*32, creativePlan=direction)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['state'], 'proposed', response.json)
        sent = json.loads(self.provider.calls[-1][1]['json']['input'][0]['content'])
        self.assertEqual(sent['creativePlan']['instruction'], direction['instruction'])
        self.assertEqual(response.json['concepts'][1:], initial['concepts'][1:])
        invalid = self.write(operationId='b'*32, creativePlan={**direction, 'instruction': 'short'})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(len(self.provider.calls), 2)

    def test_more_ideas_compares_prior_set_and_repeated_output_is_held_without_overwriting(self):
        self.provider.sample = concepts()
        initial = self.plan().json
        request = {'mode': 'more_ideas', 'parentOperationId': initial['operationId'], 'conceptId': ''}
        response = self.write(operationId='a'*32, creativePlan=request)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['state'], 'held', response.json)
        self.assertIn('repeats saved concepts', ' '.join(response.json['issues']))
        history = self.client.get(self.url, headers=self.headers).json['conceptPlans']
        self.assertEqual(history[1], initial)
        self.assertEqual(len(self.provider.calls), 2)

    def test_no_photo_signal_nest_and_local_service_use_their_own_reviewed_briefs(self):
        fixtures = [
            ('Signal Nest AI', 'A prelaunch email-draft assistant for small support teams; drafts replies grounded in their own help articles for human review.',
             'Request early access', ['Keep a person in the reply loop', 'Ground a reply in help articles', 'Make space for human review'],
             ['Review an email draft', 'Work from your help articles', 'Keep control of the final reply']),
            ('Harbour Plumbing', 'Plumbing and heating enquiries for local homes; no emergency availability or certifications claimed.',
             'Enquire about plumbing', ['Discuss a leaking pipe', 'Ask about heating support', 'Plan plumbing enquiries'],
             ['A leak needs attention', 'Heating questions start here', 'Plumbing for your home'])]
        for index, (name, offer, cta, motivations, headlines) in enumerate(fixtures, 5):
            with self.subTest(business=name):
                doc = copy.deepcopy(self.doc)
                doc.update(business=name, observedFacts=[offer])
                strategy = doc['ownerStrategy']
                strategy.update(offer=offer, positioning='', callToAction=cta,
                    audience='INTERNAL QA proposed audience: small support teams' if index == 5 else 'INTERNAL QA proposed audience: local homeowners',
                    constraints='Fictional QA business. No photos. No fabricated customers, integrations, metrics, results or availability.')
                strategy['factDecisions'] = [{'index': 0, 'observation': offer, 'decision': 'confirmed', 'statement': ''}]
                strategy['confirmedContext'] = {**{k: doc[k] for k in ('business','goal','sourceUrl','observedFacts')},
                    **{k: v for k, v in strategy.items() if k != 'confirmedContext'}}
                ident = str(index)*32
                saved = self.client.post(self.root, headers=self.headers, json={**self.payload, 'id': ident,
                    'mutationId': str(index+2)*32, 'document': doc})
                self.assertEqual(saved.status_code, 200, saved.json)
                sample = concepts(offer)
                for item, motivation, headline in zip(sample['concepts'], motivations, headlines):
                    item.update(buyerMotivation=motivation, headline=headline, callToAction=cta,
                        heroVisual=f'{name} visualises {motivation.lower()} through one concrete transformation.',
                        conceptLogic=f'The transformation is grounded in this reviewed offer: {offer}')
                more = ([('Start a help-article-grounded draft', 'Begin with what your team knows', 'Editorial overlapping paper shapes link a help article to a draft, open lower copy area.'),
                         ('Explore early access for a small team', 'Meet Signal Nest AI', 'Typographic prelaunch proposition with a warm quiet field and one contrasting paper form.'),
                         ('Keep an email reply personal', 'Leave room for your own words', 'Illustrative handwritten mark beside an abstract email envelope, clear upper headline area.')]
                        if index == 5 else
                        [('Describe a home plumbing need', 'Tell us about the plumbing', 'An illustrative kitchen tap and quiet water droplet, lower editorial headline space.'),
                         ('Discuss heating in the home', 'A conversation about heating', 'A warm geometric home cross-section with blank left-side copy space, not real premises.'),
                         ('Find a next step for local service', 'Start your plumbing enquiry', 'An abstract pipe bend leading to an open paper form with upper headline space.')])
                for item, (motivation, headline, scene) in zip(sample['concepts'][3:], more):
                    item.update(buyerMotivation=motivation, headline=headline, visualDirection=scene, callToAction=cta,
                        heroVisual=f'{name} visualises {motivation.lower()} through one concrete transformation.',
                        conceptLogic=f'The transformation is grounded in this reviewed offer: {offer}')
                headlines = headlines + [item[1] for item in more]
                sample['recommendations'] = [{'conceptIndex':i,'reason':'Connects the reviewed offer to this proposed buyer need: '+c['buyerMotivation']} for i,c in enumerate(sample['concepts'][:3])]
                # Synthetic transport shape only; no claim these scenes were model-written.
                sample['concepts'][0]['visualDirection'] = 'Editorial abstract knowledge-to-answer metaphor with separate source and draft forms; open upper text zone.' if index == 5 else 'Illustrative pipe and water droplet with uncluttered upper space for editable headline; no documentary job claim.'
                sample['concepts'][1]['visualDirection'] = 'Clearly illustrative human review workflow, no live product interface or invented integrations; generous left copy zone.' if index == 5 else 'Illustrative heating control context on a quiet wall with generous left copy zone; not the business premises.'
                sample['concepts'][2]['visualDirection'] = 'Typographic proposition layout with abstract paper forms and lower supporting shape; do not render text into the background.'
                self.provider.sample = sample
                response = self.client.post(self.root+'/'+ident+'/writing', headers=self.headers,
                    json={**self.request, 'creativePlan': {'mode':'initial','parentOperationId':'','conceptId':''}})
                self.assertEqual(response.status_code, 200, response.json)
                self.assertEqual(response.json['state'], 'proposed', response.json)
                sent = json.loads(self.provider.calls[-1][1]['json']['input'][0]['content'])
                self.assertEqual(sent['saved_business']['business'], name)
                self.assertIn(offer, [e['quote'] for e in sent['saved_business']['evidence']])
                self.assertEqual([c['headline'] for c in response.json['concepts']], headlines)
                self.assertFalse(response.json['canPublish'])
                artifact = Path('/tmp/growthrova-concepts-qa') / ('signalnest' if index == 5 else 'harbour')
                artifact.mkdir(parents=True, exist_ok=True)
                (artifact/'synthetic-plan.json').write_text(json.dumps(response.json, indent=2))
                (artifact/'saved-brief.json').write_text(json.dumps(saved.json, indent=2))

    def test_question_headline_is_a_proposal_without_independent_approval(self):
        self.provider.sample = concepts()
        self.provider.sample['concepts'][0]['headline'] = 'Is servicing still on your list?'
        response = self.plan()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['state'], 'proposed', response.json)
        self.assertEqual(response.json['independentReview'], 'pending')
        self.assertFalse(response.json['canPublish'])

    def test_brand_change_holds_stale_plan_selection_and_shared_budget_covers_planning(self):
        from dataclasses import replace
        self.provider.sample = concepts()
        plan = self.plan().json
        budget_client = self.create(replace(self.config, budget_microusd=plan['reservedMicrousd'])).test_client()
        before = len(self.provider.calls)
        budget = budget_client.post(self.url, headers=self.headers, json={**self.request, 'operationId': 'a'*32})
        self.assertEqual(budget.status_code, 409, budget.json)
        self.assertEqual(budget.json['code'], 'writer_budget_held')
        self.assertEqual(len(self.provider.calls), before)
        doc = copy.deepcopy(self.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
            secondary_color='#FFFFFF', font_style='modern')
        saved = self.client.post(self.root, headers=self.headers, json={**self.payload,
            'mutationId':'b'*32, 'expectedRevision':1, 'document':doc})
        self.assertEqual(saved.status_code, 200, saved.json)
        selection = self.client.put(self.url+'/'+plan['operationId']+'/concept-selection', headers=self.headers,
            json={'expectedRevision':2,'expectedSelectionRevision':0,'selectedConceptIds':[plan['concepts'][0]['id']]})
        self.assertEqual(selection.status_code, 400, selection.json)
        self.assertEqual(len(self.provider.calls), before)

    def test_placeholder_customer_words_are_held_without_discarding_provider_output(self):
        self.provider.sample = concepts()
        self.provider.sample['concepts'][0]['headline'] = '[Insert your headline]'
        result = self.plan()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'held', result.json)
        self.assertIn('placeholder', ' '.join(result.json['issues']))
        self.assertEqual(result.json['concepts'][0]['headline'], '[Insert your headline]')

    def test_variant_cannot_duplicate_unchanged_sibling_direction(self):
        self.provider.sample = concepts()
        initial = self.plan().json
        self.provider.sample = {'concepts': [copy.deepcopy(concepts()['concepts'][1])]}
        response = self.write(operationId='a'*32, creativePlan={'mode':'more_like_this',
            'parentOperationId':initial['operationId'],'conceptId':initial['concepts'][0]['id']})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['state'], 'held', response.json)
        self.assertEqual(response.json['concepts'][1:], initial['concepts'][1:])

    def test_concept_history_does_not_displace_saved_writing_versions(self):
        original = self.write().json
        self.provider.sample = concepts()
        initial = self.plan(operationId='a'*32).json
        self.assertEqual(initial.get('state'), 'proposed', initial)
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute('SELECT * FROM growthrova_writing_requests WHERE operation_id=?', ('a'*32,)).fetchone()
            for number in range(10):
                result = copy.deepcopy(initial)
                operation = format(number+20, '032x')
                result['operationId'] = operation
                con.execute('INSERT INTO growthrova_writing_requests VALUES(?,?,?,?,?,?,?,?)',
                    (row[0],operation,row[2],row[3],operation,operation,row[6],json.dumps(result)))
            con.commit()
        status = self.client.get(self.url, headers=self.headers).json
        self.assertIn(original, status['proposals'])
        self.assertEqual(len(status['conceptPlans']), 10)

    def test_type_only_or_ungrounded_hero_visual_is_held_before_image_spend(self):
        sample = concepts()
        sample['concepts'][0].update(
            heroVisual='Typography-led brackets on an empty colour field with reserved copy space.',
            conceptLogic='A decorative layout creates a clean modern advertisement.')
        sample['concepts'][1].update(
            heroVisual='A tropical fruit sculpture opens under a theatre spotlight.',
            conceptLogic='The unexpected sculpture creates intrigue for an unrelated audience.')
        self.provider.sample = sample
        result = self.plan().json
        self.assertEqual(result['state'], 'held', result)
        issues = ' '.join(result['issues'])
        self.assertIn('not a campaign idea', issues)
        self.assertIn('not grounded', issues)

    def test_repeated_generic_material_is_held_as_a_visual_crutch(self):
        sample = concepts()
        sample['concepts'][0].update(
            heroVisual='A paper bicycle wheel unfolds to reveal a completed service path.',
            conceptLogic='The unfolding bicycle service path makes workshop care visible.')
        sample['concepts'][1].update(
            heroVisual='A paper bicycle receipt opens into a repaired wheel.',
            conceptLogic='The paper transformation connects bicycle servicing with the repaired result.')
        self.provider.sample = sample
        result = self.plan().json
        self.assertEqual(result['state'], 'held', result)
        self.assertIn('repeat paper as a visual crutch', ' '.join(result['issues']))
