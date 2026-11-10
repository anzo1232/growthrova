"""Synthetic HTTP provider contract. Never a generated Hale quality sample."""
import copy
import base64
import io
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

import requests
from PIL import Image
from business_growthrova_preview import create_growthrova_preview
from business_growthrova_writer import WriterConfig, evaluate_writing, source_material, validate_structure
from tests.test_business_growthrova_preview import Transport, PROJECT, USER, OTHER, ORG
from tests.test_business_marketing_drafts import document

SAMPLE = json.loads((Path(__file__).parent/'fixtures/growthrova-writing-synthetic.json').read_text())


class ProviderResponse:
    status_code = 200
    def __init__(self, sample): self.sample = sample
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size):
        value = self.sample if isinstance(self.sample, dict) and 'output' in self.sample else {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(self.sample)}]}]}
        yield json.dumps(value).encode()


class Provider:
    def __init__(self): self.calls=[]; self.sample=copy.deepcopy(SAMPLE); self.failure=None; self.on_call=None
    def post(self,url,**options):
        self.calls.append((url,options))
        if self.on_call: self.on_call()
        if self.failure: raise self.failure
        return ProviderResponse(self.sample)


class GrowthrovaWriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'preview.db');self.auth=Transport();self.provider=Provider()
        self.config=WriterConfig(enabled=True,key='synthetic-not-a-provider-key',model='synthetic-contract-model',
            budget_microusd=1000000,call_cap_microusd=200000,
            input_rate_microusd_per_million=1000000,output_rate_microusd_per_million=1000000)
        self.headers={'Authorization':'Bearer synthetic-valid'}
        self.root=f'/api/growthrova/organisations/{ORG}/marketing-documents'
        self.ident='1'*32;self.url=self.root+'/'+self.ident+'/writing'
        self.doc=document();self.doc['business']='Synthetic workshop'
        self.doc['observedFacts']=['We offer bicycle servicing and brake adjustments.']
        strategy={'audience':'Proposed test audience: local bicycle owners','offer':'Bicycle servicing and brake adjustments.',
            'positioning':'Discuss your bicycle with the workshop.','callToAction':'Contact the workshop.',
            'constraints':'TEST INPUT ONLY. No prices, discounts, guarantees or invented results.'}
        strategy['factDecisions']=[{'index':0,'observation':self.doc['observedFacts'][0],'decision':'confirmed','statement':''}]
        context={k:self.doc[k] for k in ('business','goal','sourceUrl','observedFacts')}
        strategy['confirmedContext']={**context,**strategy};self.doc['ownerStrategy']=strategy
        self.app=self.create();self.client=self.app.test_client()
        self.payload={'id':self.ident,'mutationId':'2'*32,'expectedRevision':0,'document':self.doc}
        saved=self.client.post(self.root,headers=self.headers,json=self.payload)
        self.assertEqual(saved.status_code,200,saved.json)
        self.request={'operationId':'3'*32,'expectedRevision':1,'tone':'warm and informative','repairOf':''}

    def create(self, config=None):
        return create_growthrova_preview(database_path=self.path,project_url=PROJECT,auth_url=PROJECT,
            anon_key='sb_publishable_synthetic',http=self.auth,writer_config=config or self.config,writer_http=self.provider)
    def write(self, **changes):
        return self.client.post(self.url,headers=self.headers,json={**self.request,**changes})

    def test_owner_requested_post_revision_preserves_other_sample_items_and_replays(self):
        initial = self.write().json
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        revision = {'target': 'post-2', 'instruction':
            'Develop brake adjustments for commuters; remove general introductory padding.'}
        # Provider changes outside the requested item must never replace it.
        self.provider.sample['posts'][0]['caption'] = 'Unrequested replacement of the first post.'
        self.provider.sample['posts'][1]['caption'] = (
            'Commuting by bicycle? Our workshop offers brake adjustments and bicycle servicing. '
            'Tell us about your bicycle and ask about brake adjustments when you contact the workshop.')
        self.provider.sample['reel']['hook'] = 'An unrequested reel replacement'
        request = {'operationId': 'a'*32, 'repairOf': initial['operationId'], 'revision': revision}
        response = self.write(**request)
        self.assertEqual(response.status_code, 200, response.json)
        revised = response.json
        self.assertEqual(revised['state'], 'proposed', revised)
        self.assertEqual(revised['sample']['posts'][0], initial['sample']['posts'][0])
        self.assertEqual(revised['sample']['posts'][2], initial['sample']['posts'][2])
        self.assertEqual(revised['sample']['reel'], initial['sample']['reel'])
        self.assertEqual(revised['sample']['posts'][1], self.provider.sample['posts'][1])
        self.assertEqual(revised['revisionRequest'], revision)
        sent = json.loads(self.provider.calls[-1][1]['json']['input'][0]['content'])
        self.assertEqual(sent['requested_quality_repair']['revision'], revision)
        self.assertEqual(self.write(**request).json, revised)
        self.assertEqual(self.write(**{**request, 'operationId': 'b'*32}).json, revised)
        conflict = self.write(**{**request, 'operationId': 'c'*32,
            'revision': {**revision, 'instruction': 'A different editorial instruction for this post.'}})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json['code'], 'operation_conflict')
        self.assertEqual(len(self.provider.calls), 2)
        reopened = self.create().test_client().get(self.url, headers=self.headers).json['proposals']
        self.assertEqual(reopened[0], revised)
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)

    def test_editorial_revision_validates_before_reserving_or_calling_provider(self):
        initial = self.write().json
        for revision in (None, {}, {'target': 'all', 'instruction': 'Change the entire campaign.'},
                {'target': 'post-1', 'instruction': 'short'},
                {'target': 'reel', 'instruction': 'x'*601},
                {'target': 'reel', 'instruction': ' '*600+'Shorten the opening.'},
                {'target': 'reel', 'instruction': 'Change this script.\x00'},
                {'target': 'reel', 'instruction': 'Change this script.', 'extra': True}):
            response = self.write(operationId='a'*32, repairOf=initial['operationId'], revision=revision)
            self.assertEqual(response.status_code, 400, response.json)
        response = self.write(operationId='a'*32, revision={
            'target': 'reel', 'instruction': 'Develop the bicycle servicing story.'})
        self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(len(self.provider.calls), 1)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_writing_requests').fetchone()[0], 1)

    def test_reel_revision_accepts_paragraphs_but_keeps_evidence_hold_and_single_repair_limit(self):
        initial = self.write().json
        self.provider.sample['posts'][0]['caption'] = 'An unrelated change must not survive.'
        self.provider.sample['reel']['hook'] = 'Plan your bicycle service before your next ride'
        self.provider.sample['reel']['evidence'][0]['quote'] = 'This unsupported quote must hold the revision.'
        revision = {'target': 'reel', 'instruction':
            'Develop the servicing story.\nKeep a direct workshop enquiry as the final action.'}
        result = self.write(operationId='a'*32, repairOf=initial['operationId'], revision=revision)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'held')
        self.assertTrue(any('Reel: evidence' in issue for issue in result.json['issues']))
        self.assertEqual(result.json['sample']['posts'], initial['sample']['posts'])
        self.assertEqual(result.json['sample']['reel'], self.provider.sample['reel'])
        second = self.write(operationId='b'*32, repairOf='a'*32, revision=revision)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(len(self.provider.calls), 2)

    def test_unchanged_requested_words_are_held_even_if_internal_evidence_changes(self):
        initial = self.write().json
        self.provider.sample['posts'][1]['evidence'][0]['quote'] = 'bicycle servicing and brake adjustments.'
        result = self.write(operationId='a'*32, repairOf=initial['operationId'], revision={
            'target': 'post-2', 'instruction': 'Make the caption more direct for commuters.'})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'held', result.json)
        self.assertTrue(any('did not change' in issue for issue in result.json['issues']))
        reopened = self.create().test_client().get(self.url, headers=self.headers).json['proposals'][0]
        self.assertEqual(reopened, result.json)
        self.assertEqual(self.write(operationId='a'*32, repairOf=initial['operationId'], revision={
            'target': 'post-2', 'instruction': 'Make the caption more direct for commuters.'}).json, result.json)
        self.assertEqual(len(self.provider.calls), 2)

    def test_angle_only_revision_is_held_and_preserved_without_another_call(self):
        initial = self.write().json
        saved = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        self.provider.sample['posts'][1]['angle'] = 'Brake adjustments for the weekday commute'
        request = {'operationId': 'a'*32, 'repairOf': initial['operationId'], 'revision': {
            'target': 'post-2', 'instruction': 'Make the caption more direct for commuters.'}}
        response = self.write(**request)
        self.assertEqual(response.status_code, 200, response.json)
        result = response.json
        self.assertEqual(result['state'], 'held', result)
        self.assertTrue(any('did not change' in issue for issue in result['issues']))
        self.assertEqual(result['sample']['posts'][1], self.provider.sample['posts'][1])
        for key in ('hook', 'caption', 'callToAction'):
            self.assertEqual(result['sample']['posts'][1][key], initial['sample']['posts'][1][key])
        self.assertEqual(self.create().test_client().get(self.url, headers=self.headers).json['proposals'][0], result)
        self.assertEqual(self.write(**request).json, result)
        self.assertEqual(len(self.provider.calls), 2)
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, saved)

    def test_legacy_noop_revision_is_held_on_reopen_and_replay_without_mutating_history(self):
        initial = self.write().json
        saved_document = self.client.get(self.root+'/'+self.ident, headers=self.headers).json['document']
        self.provider.sample['posts'][1]['angle'] = 'A new label with unchanged customer words'
        request = {'operationId': 'a'*32, 'repairOf': initial['operationId'], 'revision': {
            'target': 'post-2', 'instruction': 'Make the caption more direct for commuters.'}}
        legacy = self.write(**request).json
        # Reproduce a row written before scoped no-op checks were introduced.
        legacy.update(state='proposed', issues=[])
        serialized = json.dumps(legacy)
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('UPDATE growthrova_writing_requests SET result_json=? WHERE operation_id=?',
                        (serialized, request['operationId']))
            con.commit()
            reservation = con.execute('SELECT SUM(reservation) FROM growthrova_writing_requests').fetchone()[0]
        reopened_client = self.create().test_client()
        reopened = reopened_client.get(self.url, headers=self.headers).json['proposals'][0]
        self.assertEqual(reopened['state'], 'held', reopened)
        self.assertTrue(any('did not change' in issue for issue in reopened['issues']))
        self.assertEqual(reopened['sample'], legacy['sample'])
        self.assertEqual(self.write(**request).json, reopened)
        self.assertEqual(self.write(**{**request, 'operationId': 'b'*32}).json, reopened)
        self.assertEqual(len(self.provider.calls), 2)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT result_json FROM growthrova_writing_requests WHERE operation_id=?',
                                        (request['operationId'],)).fetchone()[0], serialized)
            self.assertEqual(con.execute('SELECT SUM(reservation) FROM growthrova_writing_requests').fetchone()[0], reservation)
        self.assertEqual(reopened_client.get(self.root+'/'+self.ident, headers=self.headers).json['document'], saved_document)
        Path('/tmp/growthrova-legacy-revision-held.json').write_text(json.dumps(reopened, indent=2))

    def test_actual_rejected_hale_output_is_held_for_website_narration(self):
        archived = json.loads((Path(__file__).parent/'fixtures/growthrova-writing-hale-rejected.json').read_text())
        validate_structure(archived['sample'])
        issues = evaluate_writing(archived['sample'], archived['material'])
        self.assertTrue(any('Post 1: caption narrates website research' in issue for issue in issues), issues)
        self.assertTrue(any('Reel shot 2: voiceover narrates website research' in issue for issue in issues), issues)
        # The website CTA is legitimate; attribution/source quotes remain
        # inspectable in evidence, without being mistaken for publishable copy.
        self.assertFalse(any('call to action' in issue for issue in issues), issues)

    def test_generic_filler_is_reviewable_and_one_explicit_repair_preserves_owner_work(self):
        original = self.client.get(self.root+'/'+self.ident, headers=self.headers).json['document']
        caption = ('We offer bicycle servicing and brake adjustments for local bicycle owners. '
                   'Knowing who to contact is a useful first step. '
                   'Tell the workshop which service you need when booking.')
        self.provider.sample['posts'][0]['caption'] = caption
        response = self.write()
        self.assertEqual(response.json['state'], 'held', response.json)
        issue = next(issue for issue in response.json['issues'] if 'generic filler' in issue)
        self.assertIn('Post 1: caption', issue)
        self.assertEqual(response.json['sample']['posts'][0]['caption'], caption)
        self.assertEqual(self.create().test_client().get(self.url, headers=self.headers).json['proposals'][0], response.json)
        self.assertEqual(self.write().json, response.json)
        self.assertEqual(len(self.provider.calls), 1)
        self.provider.sample = copy.deepcopy(SAMPLE)
        repaired = self.write(operationId='a'*32, repairOf=self.request['operationId'])
        self.assertEqual(repaired.json['state'], 'proposed', repaired.json)
        sent = json.loads(self.provider.calls[-1][1]['json']['input'][0]['content'])
        self.assertIn(issue, sent['requested_quality_repair']['issues'])
        self.assertEqual(len(self.provider.calls), 2)
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json['document'], original)

    def test_specific_enquiry_wording_and_internal_evidence_are_not_generic_filler(self):
        sample = copy.deepcopy(SAMPLE)
        material = source_material(self.doc)
        sample['posts'][0]['caption'] = (
            'We offer bicycle servicing and brake adjustments for local bicycle owners. '
            'Contact the workshop about brake adjustments and tell us which bicycle needs servicing.')
        sample['posts'][0]['callToAction'] = 'Visit the workshop website to enquire about brake adjustments.'
        material['evidence'].append({'id': 'owner-note', 'status': 'owner_input',
            'quote': 'Avoid saying knowing who to contact is a useful first step.', 'sourceUrl': ''})
        self.assertEqual(evaluate_writing(sample, material), [])

    def test_research_narration_hold_survives_reopen_replay_and_explicit_repair(self):
        original = self.client.get(self.root+'/'+self.ident, headers=self.headers).json['document']
        self.provider.sample['posts'][0]['caption'] = (
            'Our website lists bicycle servicing and brake adjustments. '
            'Review the workshop website and use the details you find to decide what you want to ask about.')
        response = self.write()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['state'], 'held', response.json)
        self.assertIn('caption narrates website research', ' '.join(response.json['issues']))
        self.assertEqual(self.create().test_client().get(self.url, headers=self.headers).json['proposals'][0], response.json)
        self.assertEqual(self.write().json, response.json)
        self.assertEqual(len(self.provider.calls), 1)
        self.provider.sample = copy.deepcopy(SAMPLE)
        repaired = self.write(operationId='a'*32, repairOf=self.request['operationId'])
        self.assertEqual(repaired.json['state'], 'proposed', repaired.json)
        sent = json.loads(self.provider.calls[-1][1]['json']['input'][0]['content'])
        self.assertEqual(sent['requested_quality_repair']['issues'], response.json['issues'])
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json['document'], original)
        self.assertEqual(len(self.provider.calls), 2)

    def test_website_service_wording_and_website_cta_are_not_research_narration(self):
        sample = copy.deepcopy(SAMPLE)
        sample['posts'][0]['caption'] = (
            'A website design project starts with what your customers need to find. '
            'Bring your priorities to a conversation about website design and discuss which pages you want to work on.')
        sample['posts'][0]['callToAction'] = 'Visit our website to enquire.'
        self.assertEqual(evaluate_writing(sample, source_material(self.doc)), [])

    def test_overfull_voiceover_is_held_per_shot_and_repair_preserves_owner_work(self):
        original = self.client.get(self.root+'/'+self.ident, headers=self.headers).json['document']
        # Valid structure and overall duration, but 45 words cannot be a usable
        # seven-second spoken draft. Other quiet shots must not hide this shot.
        self.provider.sample['reel']['shots'][1]['voiceover'] = (
            'Discuss bicycle servicing and brake adjustments with the workshop. '
            'Tell us about your bicycle and the work you want to discuss. '
            'Include the type of bicycle you ride and what you have noticed. '
            'Contact the workshop to start a conversation about the service you need.')
        validate_structure(self.provider.sample)
        result = self.write()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'held', result.json)
        issue = result.json['issues'][0]
        self.assertIn('Reel shot 2: voiceover has 45 words for 7 seconds', issue)
        reopened = self.create().test_client().get(self.url, headers=self.headers).json['proposals'][0]
        self.assertEqual(reopened, result.json)
        self.assertEqual(self.write().json, reopened)
        self.assertEqual(len(self.provider.calls), 1)
        # Explicit bounded repair can return a shorter script, never overwrite
        # an owner's campaign or silently release the first reservation.
        self.provider.sample = copy.deepcopy(SAMPLE)
        repaired = self.write(operationId='a'*32, repairOf=self.request['operationId'])
        self.assertEqual(repaired.status_code, 200, repaired.json)
        self.assertEqual(repaired.json['state'], 'proposed', repaired.json)
        self.assertEqual(len(self.provider.calls), 2)
        sent = json.loads(self.provider.calls[1][1]['json']['input'][0]['content'])
        self.assertIn(issue, sent['requested_quality_repair']['issues'])
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json['document'], original)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT SUM(reservation) FROM growthrova_writing_requests').fetchone()[0],
                result.json['reservedMicrousd'] + repaired.json['reservedMicrousd'])
        Path('/tmp/growthrova-writer-pacing-held.json').write_text(json.dumps(reopened, indent=2))
        Path('/tmp/growthrova-writer-pacing-repaired.json').write_text(json.dumps(repaired.json, indent=2))

    def test_voiceover_planning_limit_checks_each_shot_at_boundary(self):
        material = source_material(self.doc)
        sample = copy.deepcopy(SAMPLE)
        sample['reel']['shots'][0]['seconds'] = 6
        sample['reel']['shots'][0]['voiceover'] = (
            'Discuss your bicycle with the workshop and ask about servicing or brake adjustments before planning your next ride.')
        self.assertEqual(evaluate_writing(sample, material), [])
        sample['reel']['shots'][0]['voiceover'] += ' More.'
        self.assertTrue(any('Reel shot 1: voiceover has 19 words for 6 seconds' in issue
                            for issue in evaluate_writing(sample, material)))

    def test_placeholders_in_cta_and_storyboard_are_held_with_field_locations(self):
        material = source_material(self.doc)
        self.assertEqual(evaluate_writing(SAMPLE, material), [])
        for index in range(4):
            bad = copy.deepcopy(SAMPLE)
            item = bad['posts'][index] if index < 3 else bad['reel']
            item['callToAction'] = 'Insert your booking link here.'
            label = f'Post {index + 1}' if index < 3 else 'Reel'
            with self.subTest(cta=label):
                self.assertIn(label + ': call to action contains placeholder wording.',
                              evaluate_writing(bad, material))
        for index in range(len(SAMPLE['reel']['shots'])):
            for field in ('visual', 'voiceover', 'onScreen'):
                bad = copy.deepcopy(SAMPLE)
                bad['reel']['shots'][index][field] = 'Insert here.'
                with self.subTest(shot=index + 1, field=field):
                    self.assertIn(f'Reel shot {index + 1}: {field} contains placeholder wording.',
                                  evaluate_writing(bad, material))

    def test_placeholder_storyboard_remains_inspectable_on_reopen_without_new_call(self):
        original = self.client.get(self.root+'/'+self.ident, headers=self.headers).json['document']
        self.provider.sample['reel']['shots'][1]['voiceover'] = 'Insert here.'
        response = self.write()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['state'], 'held', response.json)
        self.assertEqual(response.json['sample'], self.provider.sample)
        reopened = self.create().test_client().get(self.url, headers=self.headers).json['proposals'][0]
        self.assertEqual(reopened, response.json)
        self.assertEqual(self.write().json, reopened)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertFalse(reopened['canSpend'])
        self.assertFalse(reopened['canPublish'])
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json['document'],
                         original)
        script = """import fs from 'node:fs';
          import {applyWriting,writingText} from './src/lib/growthrovaWriting.mjs';
          const {doc,proposal}=JSON.parse(fs.readFileSync(0,'utf8'));
          try { applyWriting(doc,proposal,'reel',doc.creatives[0].id); process.exit(2); }
          catch(error) { if(!error.message.includes('Held writing')) throw error; }
          process.stdout.write(writingText(proposal));"""
        run = subprocess.run(['node','--input-type=module','-e',script],
            input=json.dumps({'doc':self.doc,'proposal':reopened}), text=True,
            capture_output=True, timeout=15, check=True)
        self.assertIn('Insert here.', run.stdout)
        self.assertIn('State: held', run.stdout)
        self.assertIn('Reel shot 2: voiceover contains placeholder wording.', run.stdout)
        Path('/tmp/growthrova-writer-storyboard-held.txt').write_text(run.stdout)

    def test_unconfigured_is_unavailable_and_generic_credentials_are_ignored(self):
        config=WriterConfig.from_environment({'OPENAI_API_KEY':'never-read','GROWTHROVA_WRITER_ENABLED':'true'})
        self.assertFalse(config.available());self.assertNotIn('synthetic-not-a-provider-key',repr(self.config))
        client=self.create(config).test_client()
        status=client.get(self.url,headers=self.headers)
        self.assertFalse(status.json['available'])
        result=client.post(self.url,headers=self.headers,json=self.request)
        self.assertEqual(result.status_code,503);self.assertEqual(result.json['code'],'writer_unavailable')
        self.assertFalse(self.provider.calls)

    def test_transport_durable_replay_reopen_and_actual_js_editor_save_download(self):
        # Reservation must already be durable when HTTP begins.
        def reserved():
            with closing(sqlite3.connect(self.path)) as con:
                row=con.execute('SELECT reservation,result_json FROM growthrova_writing_requests').fetchone()
                self.assertGreater(row[0],0);self.assertEqual(json.loads(row[1])['state'],'uncertain')
            duplicate=self.write(operationId='4'*32)
            self.assertEqual(duplicate.json['state'],'uncertain')
        self.provider.on_call=reserved
        result=self.write();self.assertEqual(result.status_code,200,result.json)
        proposal=result.json;self.assertEqual(proposal['state'],'proposed',proposal)
        url,options=self.provider.calls[0]
        self.assertEqual(url,'https://api.openai.com/v1/responses');self.assertFalse(options['allow_redirects'])
        self.assertEqual(options['timeout'],(5,45));self.assertTrue(options['stream'])
        payload=options['json'];self.assertFalse(payload['store']);self.assertTrue(payload['text']['format']['strict'])
        self.assertNotIn('tools',payload);self.assertNotIn(self.config.key,json.dumps(proposal))
        self.assertEqual(self.write().json,proposal)
        self.assertEqual(self.write(operationId='4'*32).json,proposal) # different retry ID still coalesces
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(self.write(tone='direct and practical').status_code,409)
        reopened=self.create().test_client().get(self.url,headers=self.headers).json
        self.assertEqual(reopened['proposals'][0],proposal)
        script="""import fs from 'node:fs';
          import {previewWritingReplacement,applyWritingReplacement,writingText} from './src/lib/growthrovaWriting.mjs';
          import {editMarketingPost,marketingPlanCsv} from './src/lib/businessMarketingDocument.mjs';
          const {doc,proposal}=JSON.parse(fs.readFileSync(0,'utf8'));
          const comparison=previewWritingReplacement(doc,proposal,'post',1,0);
          const applied=applyWritingReplacement(doc,proposal,comparison);
          const revised=editMarketingPost(applied,1,{callToAction:'Ask about a service visit'});
          process.stdout.write(JSON.stringify({document:revised,comparison,download:writingText(proposal),csv:marketingPlanCsv(revised)}));"""
        run=subprocess.run(['node','--experimental-json-modules','--input-type=module','-e',script],
            input=json.dumps({'doc':self.doc,'proposal':proposal}),text=True,capture_output=True,timeout=15,check=True)
        edited=json.loads(run.stdout);next_doc=edited['document']
        self.assertEqual(edited['comparison']['before'],self.doc['posts'][0])
        self.assertEqual(edited['comparison']['after']['copyDraft'],next_doc['posts'][0]['copyDraft'])
        Path('/tmp/growthrova-writer-comparison-output.json').write_text(json.dumps(edited,indent=2))
        self.assertEqual(next_doc['posts'][1:],self.doc['posts'][1:]);self.assertEqual(next_doc['creatives'],self.doc['creatives'])
        self.assertEqual(next_doc['posts'][0]['callToAction'],'Ask about a service visit')
        saved=self.client.post(self.root,headers=self.headers,json={**self.payload,'mutationId':'5'*32,'expectedRevision':1,'document':next_doc})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertTrue(self.client.post(self.root,headers=self.headers,json={**self.payload,'mutationId':'5'*32,'expectedRevision':1,'document':next_doc}).json['replayed'])
        read=self.create().test_client().get(self.root+'/'+self.ident,headers=self.headers).json['document']
        self.assertEqual(read['posts'][0]['copyDraft'],next_doc['posts'][0]['copyDraft'])
        self.assertFalse(read['canPublish']);self.assertFalse(read['canSpend'])
        self.assertEqual(self.write(operationId='c'*32,expectedRevision=2).json,proposal)
        self.assertEqual(len(self.provider.calls),1)
        self.assertIn(SAMPLE['posts'][0]['caption'],edited['download']);self.assertIn('INTERNAL EVIDENCE',edited['download'])
        self.assertIn('Ask about a service visit',edited['csv'])
        Path('/tmp/growthrova-writer-synthetic-download.txt').write_text(edited['download'])
        # The written post reaches the EXISTING genuine-media composition route.
        # Authored synthetic pixels prove integration, never Hale media/artistic acceptance.
        media=self.root+'/'+self.ident+'/media'
        png=io.BytesIO();Image.new('RGB',(96,64),'#225533').save(png,format='PNG')
        imported=self.client.post(media,data={'file':(io.BytesIO(png.getvalue()),'synthetic-local.png','image/png'),
            'rightsStatement':'Locally authored synthetic verification pixels only.', 'consentStatus':'owner_asserted'},headers=self.headers)
        self.assertEqual(imported.status_code,201,imported.json)
        asset=imported.json['assets'][0]['assetId']
        selection={'revision':2,'selectionVersion':0,'assetIds':[asset], 'postAssignments':[{'day':1,'assetIds':[asset],'photoCrops':[{'assetId':asset,'left':0,'top':0,'width':96,'height':64}]}]}
        selected=self.client.put(media+'/selection',headers=self.headers,json=selection)
        self.assertEqual(selected.status_code,200,selected.json)
        preview=self.client.get(media+f'/posts/1/{asset}/photo-preview?revision=2&selectionVersion=1',headers=self.headers)
        self.assertEqual(preview.status_code,200,preview.json)
        note={'revision':2,'selectionVersion':1,'reviewVersion':0,'receipt':preview.json['reviewReceipt'],
            'outcome':'usable_candidate','note':'Synthetic frame inspected for technical integration, no artistic approval.'}
        reviewed=self.client.put(media+f'/posts/1/{asset}/review-note',headers=self.headers,json=note)
        self.assertEqual(reviewed.status_code,200,reviewed.json)
        composition_url=media+'/posts/1/composition-preview?revision=2&selectionVersion=1&reviewVersion=1'
        composed=self.client.get(composition_url,headers=self.headers)
        self.assertEqual(composed.status_code,200,composed.json)
        self.assertEqual(composed.json['manifest']['post']['copyDraft'],next_doc['posts'][0]['copyDraft'])
        self.assertFalse(composed.json['manifest']['approved'])
        target=Path('/tmp/growthrova-writer-synthetic-composition.mp4')
        target.write_bytes(base64.b64decode(composed.json['previewBase64']))
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(target),'-frames:v','1','-y',
            '/tmp/growthrova-writer-synthetic-composition.png'],capture_output=True,check=True,timeout=15)
        with Image.open('/tmp/growthrova-writer-synthetic-composition.png') as frame:
            self.assertEqual(frame.size,(720,1280))
        self.auth.allowed=False
        self.assertEqual(self.client.get(composition_url,headers=self.headers).status_code,403)


    def test_foreign_revoked_stale_and_unconfirmed_never_call_provider(self):
        self.auth.owner=OTHER
        self.assertEqual(self.write().status_code,403)
        self.auth.owner=USER;self.auth.allowed=False
        self.assertEqual(self.write().status_code,403)
        self.auth.allowed=True
        self.assertEqual(self.write(expectedRevision=0).status_code,409)
        doc=copy.deepcopy(self.doc);doc['ownerStrategy']['confirmedContext']=None
        result=self.client.post(self.root,headers=self.headers,json={**self.payload,'document':doc,'mutationId':'6'*32,'expectedRevision':1})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.write(expectedRevision=2).status_code,400)
        self.assertFalse(self.provider.calls)

    def test_timeout_is_persisted_uncertain_without_retry_or_budget_release(self):
        self.provider.failure=requests.Timeout('synthetic transport uncertainty; must not appear in response')
        result=self.write();self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['state'],'uncertain');self.assertIsNone(result.json['sample'])
        self.assertNotIn('synthetic transport',json.dumps(result.json))
        self.assertEqual(self.create().test_client().post(self.url,headers=self.headers,json=self.request).json,result.json)
        self.assertEqual(len(self.provider.calls),1)
        with closing(sqlite3.connect(self.path)) as con:self.assertGreater(con.execute('SELECT SUM(reservation) FROM growthrova_writing_requests').fetchone()[0],0)

    def test_budget_blocks_before_transport(self):
        config=WriterConfig(**{**self.config.__dict__,'budget_microusd':1})
        client=self.create(config).test_client()
        response=client.post(self.url,headers=self.headers,json=self.request)
        self.assertEqual(response.status_code,409);self.assertEqual(response.json['code'],'writer_budget_held')
        self.assertFalse(self.provider.calls)

    def test_authorised_test_spending_ceilings_fail_closed_before_reservation(self):
        # An operator typo must not widen Dean's $10 lifetime / $0.50 call authority.
        for changes in ({'budget_microusd': 10000001}, {'call_cap_microusd': 500001}):
            with self.subTest(changes=changes):
                config = WriterConfig(**{**self.config.__dict__, **changes})
                client = self.create(config).test_client()
                status = client.get(self.url, headers=self.headers)
                self.assertFalse(status.json['available'], status.json)
                self.assertIn('$10', status.json['message'])
                self.assertIn('$0.50', status.json['message'])
                response = client.post(self.url, headers=self.headers, json=self.request)
                self.assertEqual(response.status_code, 503, response.json)
                self.assertEqual(response.json['code'], 'writer_unavailable')
                self.assertIn('$0.50', response.json['error'])
        self.assertFalse(self.provider.calls)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_writing_requests').fetchone()[0], 0)

    def test_authorised_ceiling_settings_and_disabled_replay_preserve_saved_proposals(self):
        config = WriterConfig(**{**self.config.__dict__, 'budget_microusd': 10000000,
            'call_cap_microusd': 500000})
        client = self.create(config).test_client()
        result = client.post(self.url, headers=self.headers, json=self.request)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'proposed', result.json)
        # Invalid later configuration blocks new spending, never inspection or replay.
        disabled = self.create(WriterConfig(**{**config.__dict__, 'call_cap_microusd': 500001})).test_client()
        reopened = disabled.get(self.url, headers=self.headers)
        self.assertFalse(reopened.json['available'])
        self.assertEqual(reopened.json['proposals'], [result.json])
        self.assertEqual(disabled.post(self.url, headers=self.headers, json=self.request).json, result.json)
        self.assertEqual(len(self.provider.calls), 1)

    def test_held_evidence_quality_and_one_explicit_repair(self):
        self.provider.sample['posts'][0]['evidence'][0]['quote']='An invented website claim'
        result=self.write();self.assertEqual(result.json['state'],'held',result.json)
        self.assertIn('exact saved source',str(result.json['issues']))
        self.provider.sample=copy.deepcopy(SAMPLE)
        repair=self.write(operationId='7'*32,repairOf='3'*32)
        self.assertEqual(repair.json['state'],'proposed',repair.json)
        self.assertEqual(self.write(operationId='8'*32,repairOf='3'*32).json,repair.json)
        self.assertEqual(self.write(operationId='9'*32,repairOf='7'*32).status_code,400)
        self.assertEqual(len(self.provider.calls),2)
        self.assertIn('requested_quality_repair',self.provider.calls[1][1]['json']['input'][0]['content'])

    def test_structured_refusal_incomplete_repetition_and_placeholder_are_held(self):
        bad=copy.deepcopy(SAMPLE);bad['posts'][1]['caption']=bad['posts'][0]['caption']
        bad['posts'][2]['caption']='Insert your placeholder here'
        issues=evaluate_writing(bad,source_material(self.doc))
        self.assertIn('repeated caption',str(issues));self.assertIn('placeholder',str(issues));self.assertIn('complete ending',str(issues))
        bad['extra']='not permitted'
        with self.assertRaises(ValueError):validate_structure(bad)
        self.provider.sample=bad
        result=self.write();self.assertEqual(result.json['state'],'held');self.assertIsNone(result.json['sample'])
        self.assertIn('not permitted',result.json['rawText'])

    def test_refusal_and_incomplete_envelopes_do_not_become_success(self):
        for envelope, state in [
            ({'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'Cannot provide writing.'}]}]}, 'held'),
            ({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]}, 'uncertain'),
        ]:
            with self.subTest(state=state):
                # Distinct saved revision, same private lifetime budget.
                revision=self.client.get(self.root+'/'+self.ident,headers=self.headers).json['revision']
                self.provider.sample=envelope
                result=self.write(expectedRevision=revision,operationId=('%032x'%revision))
                self.assertEqual(result.json['state'],state,result.json)
                self.assertIsNone(result.json['sample'])
                changed=copy.deepcopy(self.doc);changed['ownerStrategy']['constraints']+=' Changed source context.'
                context=changed['ownerStrategy']['confirmedContext'];context['constraints']=changed['ownerStrategy']['constraints']
                update=self.client.post(self.root,headers=self.headers,json={**self.payload,'document':changed,'mutationId':('%032x'%(revision+100)),'expectedRevision':revision})
                self.assertEqual(update.status_code,200,update.json)

    def test_budget_is_shared_across_new_revisions_and_documents(self):
        first=self.write().json
        for ident in (self.ident, 'a'*32):
            expected=1 if ident==self.ident else 0
            changed=copy.deepcopy(self.doc);changed['ownerStrategy']['constraints']+=' Changed source context.'
            changed['ownerStrategy']['confirmedContext']['constraints']=changed['ownerStrategy']['constraints']
            saved=self.client.post(self.root,headers=self.headers,json={**self.payload,'document':changed,'id':ident,'mutationId':'b'*32,'expectedRevision':expected})
            self.assertEqual(saved.status_code,200,saved.json)
            config=WriterConfig(**{**self.config.__dict__,'budget_microusd':first['reservedMicrousd']})
            client=self.create(config).test_client()
            result=client.post(self.root+'/'+ident+'/writing',headers=self.headers,json={**self.request,'operationId':'d'*32,'expectedRevision':expected+1})
            self.assertEqual(result.json['code'],'writer_budget_held',result.json)
        self.assertEqual(len(self.provider.calls),1)

    def test_saved_research_keeps_exact_secondary_url_and_uncertainty_separate(self):
        doc=copy.deepcopy(self.doc)
        doc['editorialShortlist']={'candidates':[{'id':'service-example','evidence':{
            'quote':'Workshop appointments are available on request.', 'sourceUrl':'https://example.org/services'}}]}
        material=source_material(doc)
        item=next(e for e in material['evidence'] if e['id']=='research-service-example')
        self.assertEqual(item['sourceUrl'],'https://example.org/services')
        self.assertEqual(item['quote'],'Workshop appointments are available on request.')
        self.assertEqual(item['status'],'website_claim_unconfirmed')
        self.assertIn('unknown',item['freshness'])
        self.assertEqual(material['goal']['status'],'owner_planning_input')

    def test_unconfirmed_research_cannot_support_editor_ready_writing(self):
        changed = copy.deepcopy(self.doc)
        quote = 'We offer bicycle servicing and brake adjustments.'
        changed['editorialShortlist'] = {
            'status': 'blocked_insufficient_unique_brand_evidence',
            'candidates': [{'id': 'unreviewed-service', 'role': 'Service detail',
                'media': 'image', 'format': '4:5', 'direction': 'Use authorised workshop media.',
                'hook': 'Workshop services', 'evidence': {'quote': quote,
                    'sourceUrl': 'https://example.org/services'}}]}
        saved = self.client.post(self.root, headers=self.headers, json={**self.payload,
            'document': changed, 'mutationId': 'a' * 32, 'expectedRevision': 1})
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertTrue(saved.json['document']['ownerStrategy']['confirmedContext'])
        # Exact matching text exists in both sources, but the model chose the
        # unreviewed website source. Matching bytes must not imply confirmation.
        self.provider.sample['posts'][0]['evidence'] = [
            {'id': 'research-unreviewed-service', 'quote': quote}]
        result = self.write(expectedRevision=2)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'held', result.json)
        sent = json.loads(self.provider.calls[0][1]['json']['input'][0]['content'])['saved_business']
        self.assertNotIn('research-unreviewed-service', [item['id'] for item in sent['evidence']])
        self.assertIn('fact-0', [item['id'] for item in sent['evidence']])
        self.assertIn('owner-reviewed', str(result.json['issues']))
        self.assertEqual(result.json['sample'], self.provider.sample)
        self.assertEqual(self.write(expectedRevision=2).json, result.json)
        self.assertEqual(self.create().test_client().get(self.url,
            headers=self.headers).json['proposals'][0], result.json)
        self.assertEqual(len(self.provider.calls), 1)
        # Retain an actual held export; no fixture is presented as model quality.
        Path('/tmp/growthrova-writer-unconfirmed-held.json').write_text(json.dumps(result.json, indent=2))

    def test_legacy_proposed_writing_is_rechecked_before_reopen_or_replay(self):
        result = self.write().json
        self.assertEqual(result['state'], 'proposed')
        # A prior release stored this exact shape without checking authority.
        result['material']['evidence'][0]['status'] = 'website_claim_unconfirmed'
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('UPDATE growthrova_writing_requests SET result_json=?', (json.dumps(result),))
            con.commit()
        client = self.create().test_client()
        reopened = client.get(self.url, headers=self.headers).json['proposals'][0]
        self.assertEqual(reopened['state'], 'held', reopened)
        self.assertIn('owner-reviewed', str(reopened['issues']))
        self.assertEqual(reopened['sample'], result['sample'])
        replay = client.post(self.url, headers=self.headers, json=self.request)
        self.assertEqual(replay.json, reopened)
        self.assertEqual(len(self.provider.calls), 1)

    def test_writing_evidence_authority_is_fail_closed_for_every_item(self):
        material = source_material(self.doc)
        for status in ('owner_reviewed_observation', 'owner_correction', 'owner_input'):
            with self.subTest(allowed=status):
                material['evidence'][0]['status'] = status
                self.assertEqual(evaluate_writing(SAMPLE, material), [])
        for status in ('website_claim_unconfirmed', 'linked_website_claim_unconfirmed', 'unknown', None):
            with self.subTest(held=status):
                material['evidence'][0]['status'] = status
                issues = evaluate_writing(SAMPLE, material)
                for label in ('Post 1', 'Post 2', 'Post 3', 'Reel'):
                    self.assertTrue(any(issue.startswith(label + ':') and 'owner-reviewed' in issue
                        for issue in issues), issues)

    def test_revocation_during_transport_denies_result_and_recovery(self):
        self.provider.on_call=lambda:setattr(self.auth,'allowed',False)
        self.assertEqual(self.write().status_code,403)
        self.assertEqual(self.client.get(self.url,headers=self.headers).status_code,403)
        self.assertEqual(len(self.provider.calls),1)


if __name__=='__main__':unittest.main()
