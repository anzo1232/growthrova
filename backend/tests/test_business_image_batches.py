"""Three saved directions execute individually; an uncertain slot never retries."""
import copy
import json
import sqlite3
import unittest
from contextlib import closing
import requests
from business_growthrova_writer import writing_context, source_material
from business_creative_plans import finish_plan
from tests.test_business_creative_plans import concepts
from tests import test_business_growthrova_images as fixtures
from tests.test_business_growthrova_preview import OTHER


class ImageBatchTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.GrowthrovaImageTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.configured()
        saved = self.f.client.get(self.f.root+'/'+self.f.ident, headers=self.f.headers).json
        doc = saved['document']
        material = source_material(doc)
        self.plan_id = 'a'*32
        plan = dict(mode='initial', parentOperationId='', conceptId='')
        candidates, issues = finish_plan(concepts(doc['observedFacts'][0], count=3), self.plan_id, plan, material, None)
        self.assertEqual(issues, [])
        self.plan = dict(operationId=self.plan_id, state='proposed', creativePlan=plan, concepts=candidates,
                         sourceContext=writing_context(doc), brandKit=doc.get('brandKit'))
        with closing(sqlite3.connect(self.f.path)) as con:
            con.execute('INSERT INTO growthrova_writing_requests VALUES(?,?,?,?,?,?,?,?)',
                (self.f.ident,self.plan_id,1,'',self.plan_id,self.plan_id,0,json.dumps(self.plan)))
            con.commit()
        self.data = dict(batchId='b'*32, planOperationId=self.plan_id, expectedRevision=1,
                         day=1, size='1024x1024', quality='low')

    def prepare(self, **changes):
        return self.f.client.post(self.f.url+'/batches', headers=self.f.headers, json={**self.data, **changes})

    def slot(self, index, batch=None):
        return self.f.client.post(self.f.url+'/batches/'+(batch or self.data['batchId'])+'/slots/'+str(index),
                                  headers=self.f.headers, json={'expectedRevision':1})

    def test_three_durable_no_photo_slots_reopen_execute_and_replay_without_overwrite(self):
        f = self.f
        before = f.client.get(f.root+'/'+f.ident, headers=f.headers).json
        response = self.prepare()
        self.assertEqual(response.status_code, 200, response.json)
        batch = response.json
        self.assertEqual(len(batch['slots']), 3)
        self.assertEqual(len({s['operationId'] for s in batch['slots']}), 3)
        self.assertEqual([s['concept']['id'] for s in batch['slots']], [c['id'] for c in self.plan['concepts']])
        self.assertTrue(all(s['state']=='planned' for s in batch['slots']))
        self.assertEqual(len(f.provider.calls), 0, 'Planning cannot bill for images')
        self.assertEqual(self.prepare().json, batch)
        self.assertEqual(self.prepare(batchId='c'*32).json, batch, 'Same inputs recover same batch')
        for index in range(3):
            result = self.slot(index)
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(result.json['batchId'], batch['batchId'])
            self.assertEqual(result.json['conceptId'], batch['slots'][index]['concept']['id'])
            self.assertEqual(result.json['state'], 'proposed')
            self.assertEqual(self.slot(index).json, result.json)
        self.assertEqual(len(f.provider.calls), 3)
        reopened = f.create().test_client().get(f.url, headers=f.headers).json['batches'][0]
        self.assertTrue(all(s['state']=='proposed' for s in reopened['slots']))
        self.assertEqual(reopened['state'], 'complete_drafts')
        self.assertEqual(f.client.get(f.root+'/'+f.ident, headers=f.headers).json, before)
        self.assertFalse(reopened['approved'])
        self.assertEqual(len(f.provider.calls), 3)

    def test_concept_snapshot_survives_reopen_and_composition_without_caption_changes(self):
        f = self.f
        self.assertEqual(self.prepare().status_code, 200)
        candidate = self.slot(0).json
        self.assertEqual(candidate.get('conceptBinding', {}).get('concept'), self.plan['concepts'][0])
        self.assertEqual(candidate['conceptBinding']['planOperationId'], self.plan_id)
        self.assertEqual(candidate['conceptBinding']['sourceContext'], self.plan['sourceContext'])
        doc = copy.deepcopy(f.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='modern')
        post_before = copy.deepcopy(doc['posts'][0])
        doc['posts'][0].update(graphicText=candidate['conceptBinding']['concept']['headline'],
                               callToAction=candidate['conceptBinding']['concept']['callToAction'])
        f.save_document(doc, 1, '6')
        client = f.create().test_client()
        reopened = client.get(f.url, headers=f.headers).json['candidates'][0]
        self.assertEqual(reopened['conceptBinding'], candidate['conceptBinding'])
        result = client.get(f.url+'/'+candidate['operationId']+'/static-preview?revision=2', headers=f.headers)
        self.assertEqual(result.status_code, 200, result.json)
        manifest = result.json['manifest']
        self.assertEqual(manifest.get('conceptBinding'), candidate['conceptBinding'])
        self.assertEqual(manifest['layout']['copy'], self.plan['concepts'][0]['headline'])
        self.assertEqual(manifest['layout']['callToAction'], self.plan['concepts'][0]['callToAction'])
        self.assertEqual(manifest['post']['copyDraft'], post_before['copyDraft'])
        self.assertEqual(manifest['backgroundSha256'], candidate['sha256'])
        self.assertEqual(len(f.provider.calls), 1)

    def test_active_request_refresh_and_replay_never_misreport_timeout_or_duplicate_calls(self):
        f = self.f
        self.assertEqual(self.prepare().status_code, 200)
        self.assertEqual(self.slot(0).status_code, 200)
        sibling = f.client.get(f.url, headers=f.headers).json['candidates'][0]
        during = []

        def while_provider_runs():
            status = f.create(image_config=f.config, image_http=f.provider).test_client().get(
                f.url, headers=f.headers).json
            batch = status['batches'][0]
            self.assertEqual(batch['state'], 'generating')
            self.assertEqual(batch['slots'][1]['state'], 'pending')
            active = next(c for c in status['candidates'] if c['operationId'] == batch['slots'][1]['operationId'])
            self.assertEqual(active['state'], 'pending')
            self.assertGreater(active['outcomeCheckAfter'], active['requestedAt'])
            self.assertEqual(self.slot(1).json['state'], 'pending', 'Replay reads the active reservation')
            held = self.slot(2)
            self.assertEqual(held.status_code, 409, held.json)
            self.assertEqual(held.json['code'], 'image_batch_pending')
            during.append(status)

        f.provider.on_call = while_provider_runs
        result = self.slot(1)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'proposed')
        self.assertEqual(len(during), 1)
        self.assertEqual(len(f.provider.calls), 2)
        reopened = f.create(image_config=f.config, image_http=f.provider).test_client().get(f.url, headers=f.headers).json
        self.assertEqual(reopened['batches'][0]['state'], 'partial')
        self.assertEqual(next(c for c in reopened['candidates'] if c['operationId']==sibling['operationId']), sibling)
        self.assertEqual(self.slot(1).json['state'], 'proposed')
        self.assertEqual(len(f.provider.calls), 2)

    def test_interrupted_pending_request_reopens_uncertain_without_releasing_cash_or_retrying(self):
        f = self.f
        self.assertEqual(self.prepare().status_code, 200)
        original = self.slot(0).json
        # Persist the exact reservation snapshot that would survive worker exit.
        def interrupt_snapshot():
            with closing(sqlite3.connect(f.path)) as con:
                row = con.execute('SELECT operation_id,result_json,reservation FROM growthrova_image_requests '
                                  'ORDER BY rowid DESC LIMIT 1').fetchone()
                candidate = json.loads(row[1])
                self.assertEqual(candidate['state'], 'pending')
                candidate.update(requestedAt=1, outcomeCheckAfter=2)
                con.execute('UPDATE growthrova_image_requests SET result_json=? WHERE operation_id=?',
                            (json.dumps(candidate), row[0]))
                con.commit()
            status = f.create(image_config=f.config, image_http=f.provider).test_client().get(f.url, headers=f.headers).json
            self.assertEqual(status['batches'][0]['state'], 'reconciliation_required')
            self.assertEqual(status['batches'][0]['slots'][1]['state'], 'uncertain')
            unknown = next(c for c in status['candidates'] if c['operationId']==row[0])
            self.assertEqual(unknown['state'], 'uncertain')
            self.assertEqual(unknown['reservedMicrousd'], row[2])
            self.assertEqual(self.slot(1).json['state'], 'uncertain')
            self.assertEqual(self.slot(2).status_code, 409)
            self.assertEqual(f.client.get(f.url+'/'+original['operationId']+'/original', headers=f.headers).data, f.provider.png)
            with closing(sqlite3.connect(f.path)) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_image_requests').fetchone()[0], 2)
        f.provider.on_call = interrupt_snapshot
        # The eventual validated response can still resolve the same operation.
        self.assertEqual(self.slot(1).json['state'], 'proposed')
        self.assertEqual(len(f.provider.calls), 2)

    def test_partial_uncertainty_blocks_remaining_calls_and_survives_restart(self):
        self.assertEqual(self.prepare().status_code, 200)
        self.assertEqual(self.slot(0).status_code, 200)
        self.f.provider.failure = requests.Timeout('fixture lost response')
        uncertain = self.slot(1)
        self.assertEqual(uncertain.status_code, 200, uncertain.json)
        self.assertEqual(uncertain.json['state'], 'uncertain')
        self.assertEqual(self.slot(1).json, uncertain.json)
        self.assertEqual(self.slot(2).status_code, 409)
        status = self.f.create().test_client().get(self.f.url, headers=self.f.headers).json
        self.assertEqual(status['batches'][0]['state'], 'reconciliation_required')
        self.assertEqual([s['state'] for s in status['batches'][0]['slots']], ['proposed','uncertain','planned'])
        self.assertEqual(len(self.f.provider.calls), 2)
        with closing(sqlite3.connect(self.f.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_image_requests').fetchone()[0], 2)

    def test_scoped_alternative_retains_concept_binding_through_reopen_and_export(self):
        import base64
        import hashlib
        import io
        from PIL import Image, ImageDraw

        f = self.f
        self.assertEqual(self.prepare().status_code, 200)
        original = self.slot(0).json
        sibling = self.slot(1).json
        original_bytes = f.provider.png
        observed = f.client.post(f.url+'/'+original['operationId']+'/observations', headers=f.headers,
            json=dict(reviewId='e'*32, expectedRevision=1, expectedReviewVersion=0, sha256=original['sha256'],
                      checks=dict(visual='checked', factual='not_reviewed', brand='not_reviewed', commercial='not_reviewed'),
                      note='Synthetic original inspected; this observation applies only to its exact pixels.'))
        self.assertEqual(observed.status_code, 200, observed.json)
        # A different fixture image makes accidental parent-pixel export visible.
        with Image.open(io.BytesIO(original_bytes)) as image:
            ImageDraw.Draw(image).rectangle((0, 0, 500, 500), fill='#884422')
            output = io.BytesIO()
            image.save(output, 'PNG')
        alternative_bytes = output.getvalue()
        f.provider.envelope = {'data': [{'b64_json': base64.b64encode(alternative_bytes).decode()}]}
        inputs = {**self.prepare().json['slots'][0]['inputs'], 'operationId': 'd'*32,
                  'parentOperationId': original['operationId'],
                  'visualBrief': 'Illustrative bicycle wheel close-up with warm accents and open space for the saved headline.'}
        result = f.client.post(f.url, headers=f.headers, json=inputs)
        self.assertEqual(result.status_code, 200, result.json)
        alternative = result.json
        self.assertEqual(alternative.get('conceptBinding'), original['conceptBinding'],
                         'Refining the background must retain the selected concept and its exact source context')
        self.assertEqual(alternative['conceptId'], original['conceptId'])
        self.assertEqual(alternative['parentSha256'], original['sha256'])
        self.assertEqual(alternative['sha256'], hashlib.sha256(alternative_bytes).hexdigest())
        self.assertNotEqual(alternative['sha256'], original['sha256'])
        self.assertEqual(alternative['independentReview'], 'pending')
        self.assertNotIn('observations', alternative, 'A new image cannot inherit parent observations')
        self.assertEqual(f.client.post(f.url, headers=f.headers, json=inputs).json, alternative)

        doc = copy.deepcopy(f.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='modern')
        concept = original['conceptBinding']['concept']
        doc['posts'][0].update(graphicText=concept['headline'], callToAction=concept['callToAction'])
        f.save_document(doc, 1, '6')
        client = f.create().test_client()
        reopened = client.get(f.url, headers=f.headers).json
        candidates = {c['operationId']: c for c in reopened['candidates']}
        self.assertEqual(candidates[alternative['operationId']]['conceptBinding'], original['conceptBinding'])
        self.assertEqual(candidates[sibling['operationId']]['sha256'], sibling['sha256'])
        self.assertEqual(candidates[original['operationId']]['observations'][0]['note'], observed.json['observations'][0]['note'])
        self.assertNotIn('observations', candidates[alternative['operationId']])
        with closing(sqlite3.connect(f.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_image_observations '
                'WHERE document_id=? AND operation_id=?', (f.ident, alternative['operationId'])).fetchone()[0], 0)
        self.assertEqual(client.get(f.url+'/'+original['operationId']+'/original', headers=f.headers).data, original_bytes)
        preview = client.get(f.url+'/'+alternative['operationId']+'/static-preview?revision=2', headers=f.headers)
        self.assertEqual(preview.status_code, 200, preview.json)
        manifest = preview.json['manifest']
        self.assertEqual(manifest['conceptBinding'], original['conceptBinding'])
        self.assertEqual(manifest['backgroundSha256'], alternative['sha256'])
        self.assertEqual(manifest['layout']['copy'], concept['headline'])
        self.assertEqual(manifest['layout']['callToAction'], concept['callToAction'])
        self.assertEqual(manifest['post']['copyDraft'], f.doc['posts'][0]['copyDraft'])
        self.assertFalse(manifest['approved'])
        self.assertEqual(len(f.provider.calls), 3, 'Replay, reopen and composition must not regenerate')

    def test_funding_preview_is_read_only_and_tracks_partial_reservations(self):
        from business_growthrova_images import image_request, provider_payload
        batch = self.prepare().json
        self.assertIn('funding', batch, 'Owner must see cash availability before requesting images')
        saved = self.f.client.get(self.f.root+'/'+self.f.ident, headers=self.f.headers).json
        reserves = []
        for slot in batch['slots']:
            post, material = image_request(slot['inputs'], saved, self.f.config)
            reserves.append(provider_payload(self.f.config, slot['inputs'], post, material)[1])
        self.assertEqual(batch['funding']['plannedReservationMicrousd'], sum(reserves))
        self.assertEqual(batch['funding']['state'], 'available')
        self.assertEqual([s['funding']['reservationMicrousd'] for s in batch['slots']], reserves)
        self.assertEqual(len(self.f.provider.calls), 0)
        with closing(sqlite3.connect(self.f.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_image_requests').fetchone()[0], 0)
        self.assertEqual(self.slot(0).status_code, 200)
        self.f.provider.failure = requests.Timeout('synthetic unknown outcome')
        self.assertEqual(self.slot(1).status_code, 200)
        status = self.f.client.get(self.f.url, headers=self.f.headers).json['batches'][0]
        self.assertEqual(status['funding']['reservedMicrousd'], sum(reserves[:2]))
        self.assertEqual(status['funding']['plannedReservationMicrousd'], reserves[2])
        self.assertEqual(status['slots'][2]['funding']['state'], 'reconciliation_required')
        self.assertEqual(status['funding']['state'], 'reconciliation_required')
        self.assertEqual(len(self.f.provider.calls), 2, 'Status cannot retry an uncertain call')

    def test_funding_preview_reports_caps_unavailable_and_stale_without_reserving(self):
        from dataclasses import replace
        self.assertEqual(self.prepare().status_code, 200)
        tight = replace(self.f.config, budget_microusd=1)
        client = self.f.create(image_config=tight, image_http=self.f.provider).test_client()
        batch = client.get(self.f.url, headers=self.f.headers).json['batches'][0]
        self.assertEqual(batch['funding']['state'], 'budget_held')
        self.assertTrue(all(s['funding']['state'] == 'budget_held' for s in batch['slots']))
        unavailable = self.f.create().test_client().get(self.f.url, headers=self.f.headers).json['batches'][0]
        self.assertEqual(unavailable['funding']['state'], 'unavailable')
        self.assertIsNone(unavailable['funding']['plannedReservationMicrousd'])
        self.f.save_document(copy.deepcopy(self.f.doc), 1, 'e')
        stale = self.f.client.get(self.f.url, headers=self.f.headers).json['batches'][0]
        self.assertEqual(stale['funding']['state'], 'context_changed')
        self.assertEqual(len(self.f.provider.calls), 0)

    def test_preview_handles_model_change_and_partial_set_affordability(self):
        from dataclasses import replace
        batch = self.prepare().json
        reserves = [s['funding']['reservationMicrousd'] for s in batch['slots']]
        limited = replace(self.f.config, budget_microusd=max(reserves))
        client = self.f.create(image_config=limited, image_http=self.f.provider).test_client()
        preview = client.get(self.f.url, headers=self.f.headers).json['batches'][0]
        self.assertEqual(preview['funding']['state'], 'partial_budget')
        self.assertTrue(all(s['funding']['state'] == 'available' for s in preview['slots']))
        # A saved native Google frame remains readable after an explicit model
        # switch to the compatible legacy adapter. It cannot be submitted there.
        with closing(sqlite3.connect(self.f.path)) as con:
            batch['slots'][0]['inputs']['size'] = 'portrait_2k'
            con.execute('UPDATE growthrova_image_batches SET batch_json=?', (json.dumps(batch),))
            con.commit()
        response = client.get(self.f.url, headers=self.f.headers)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['batches'][0]['slots'][0]['funding']['state'], 'settings_changed')
        self.assertEqual(len(self.f.provider.calls), 0)

    def test_disabled_provider_keeps_planning_but_cannot_execute_or_charge(self):
        f=self.f
        f.client=f.create().test_client()
        self.assertEqual(self.prepare().status_code, 200)
        self.assertEqual(self.slot(0).status_code, 503)
        self.assertEqual(f.client.get(f.url,headers=f.headers).json['batches'][0]['slots'][0]['state'], 'planned')
        self.assertEqual(len(f.provider.calls), 0)

    def test_saved_set_pins_model_and_holds_unstarted_slots_after_provider_change(self):
        from dataclasses import replace
        from unittest.mock import patch
        import business_nano_banana_pro as google_images

        f = self.f
        batch = self.prepare().json
        candidate = self.slot(0).json
        changed = replace(f.config, model=google_images.MODEL, budget_microusd=1000000,
                          call_cap_microusd=500000, output_cost_microusd=234000)
        with patch('business_growthrova_images.AUTHORISED_IMAGE_CALL_MICROUSD', 500000):
            self.assertTrue(changed.available(), 'Both configurations must be usable to reproduce silent substitution')
            client = f.create(image_config=changed, image_http=f.provider).test_client()
            status = client.get(f.url, headers=f.headers)
            self.assertEqual(status.status_code, 200, status.json)
            reopened = status.json['batches'][0]
            self.assertEqual(reopened['funding']['state'], 'settings_changed')
            self.assertEqual(reopened['model'], f.config.model)
            self.assertEqual(reopened['slots'][0]['state'], 'proposed')
            self.assertEqual(reopened['slots'][0]['funding']['state'], 'retained')
            self.assertTrue(all(s['funding']['state'] == 'settings_changed' for s in reopened['slots'][1:]))
            denied = client.post(f.url+'/batches/'+batch['batchId']+'/slots/1',
                                 headers=f.headers, json={'expectedRevision': 1})
            self.assertEqual(denied.status_code, 409, denied.json)
            self.assertEqual(denied.json['code'], 'image_batch_settings_changed')
            replay = client.post(f.url+'/batches/'+batch['batchId']+'/slots/0',
                                 headers=f.headers, json={'expectedRevision': 1})
            self.assertEqual(replay.json, candidate, 'A model change must not erase a completed sibling')
            self.assertEqual(client.get(f.url+'/'+candidate['operationId']+'/original', headers=f.headers).data,
                             f.provider.png)
            replacement = client.post(f.url+'/batches', headers=f.headers,
                                      json={**self.data, 'batchId': 'c'*32})
            self.assertEqual(replacement.status_code, 200, replacement.json)
            self.assertNotEqual(replacement.json['batchId'], batch['batchId'])
            self.assertEqual(replacement.json['model'], google_images.MODEL)
            self.assertEqual(replacement.json['funding']['state'], 'available')
            self.assertEqual(len(client.get(f.url, headers=f.headers).json['batches']), 2)
        self.assertEqual(len(f.provider.calls), 1, 'Neither status, replay nor a held slot may invoke another provider')

    def test_legacy_unbound_set_is_readable_but_cannot_silently_adopt_current_model(self):
        import hashlib
        f = self.f
        batch = self.prepare().json
        candidate = self.slot(0).json
        batch.pop('model', None)
        legacy_fingerprint = hashlib.sha256(json.dumps([f.client.get(f.root+'/'+f.ident, headers=f.headers).json['document'],
            batch['sourceChoice'], {k: v for k, v in self.data.items() if k != 'batchId'}], sort_keys=True).encode()).hexdigest()
        with closing(sqlite3.connect(f.path)) as con:
            con.execute('UPDATE growthrova_image_batches SET batch_json=?,fingerprint=?', (json.dumps(batch), legacy_fingerprint))
            con.commit()
        reopened = f.create(image_config=f.config, image_http=f.provider).test_client()
        status = reopened.get(f.url, headers=f.headers)
        self.assertEqual(status.status_code, 200, status.json)
        self.assertEqual(status.json['batches'][0]['slots'][1]['funding']['state'], 'settings_changed')
        self.assertEqual(self.prepare().status_code, 200, 'Exact historical planning acknowledgement stays recoverable')
        self.assertNotIn('model', self.prepare().json, 'Recovery cannot silently bind a historical set')
        denied = reopened.post(f.url+'/batches/'+batch['batchId']+'/slots/1',
                               headers=f.headers, json={'expectedRevision': 1})
        self.assertEqual(denied.status_code, 409, denied.json)
        self.assertEqual(self.slot(0).json, candidate)
        self.assertEqual(len(f.provider.calls), 1)

    def test_native_frame_set_reports_model_hold_instead_of_requesting_canvas_edits(self):
        from dataclasses import replace
        import business_nano_banana_pro as google_images

        client = self.f.create(image_config=replace(self.f.config, model=google_images.MODEL),
                               image_http=self.f.provider).test_client()
        planned = client.post(self.f.url+'/batches', headers=self.f.headers,
                              json={**self.data, 'size': 'portrait_2k', 'quality': 'standard'})
        self.assertEqual(planned.status_code, 200, planned.json)
        denied = self.slot(0)
        self.assertEqual(denied.status_code, 409, denied.json)
        self.assertEqual(denied.json['code'], 'image_batch_settings_changed')
        self.assertEqual(self.f.provider.calls, [])

    def test_completed_set_images_stay_inspectable_beyond_recent_candidate_window(self):
        f=self.f
        batch=self.prepare().json
        self.assertEqual(self.slot(0).status_code,200)
        candidate=f.client.get(f.url,headers=f.headers).json['candidates'][0]
        with closing(sqlite3.connect(f.path)) as con:
            for i in range(21):
                operation=format(i+100,'032x')
                con.execute('INSERT INTO growthrova_image_requests VALUES(?,?,?,?,?,?)',
                    (f.ident,operation,operation,0,json.dumps({**candidate,'operationId':operation}),f.provider.png))
            con.commit()
        reopened=f.client.get(f.url,headers=f.headers).json
        self.assertIn(candidate,reopened['candidates'])
        self.assertEqual(reopened['batches'][0]['slots'][0]['operationId'],batch['slots'][0]['operationId'])
        self.assertEqual(len(f.provider.calls),1)

    def test_source_change_can_plan_new_set_without_overwriting_old_snapshot(self):
        f=self.f
        first=self.prepare().json
        f.client.put(f.url+'/source-choice',headers=f.headers,json={'route':'mix','expectedRevision':1,'expectedSourceVersion':0})
        response=self.prepare(batchId='c'*32)
        self.assertEqual(response.status_code,200,response.json)
        self.assertNotEqual(response.json['batchId'],first['batchId'])
        self.assertEqual(response.json['sourceChoice'],{'route':'mix','version':1})
        self.assertEqual(len(f.client.get(f.url,headers=f.headers).json['batches']),2)
        self.assertEqual(len(f.provider.calls),0)

    def test_untrusted_plan_scope_revision_source_and_operation_conflicts_fail_before_calls(self):
        f=self.f
        self.assertEqual(self.prepare().status_code, 200)
        self.assertEqual(self.prepare(day=2).status_code, 409)
        self.assertEqual(self.slot(3).status_code, 400)
        f.auth.owner=OTHER
        self.assertEqual(self.prepare().status_code, 403)
        self.assertEqual(self.slot(0).status_code, 403)
        f.auth.owner='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        f.client.put(f.url+'/source-choice',headers=f.headers,json={'route':'website','expectedRevision':1,'expectedSourceVersion':0})
        self.assertEqual(self.slot(0).status_code, 409)
        f.client.put(f.url+'/source-choice',headers=f.headers,json={'route':'create','expectedRevision':1,'expectedSourceVersion':1})
        self.assertEqual(self.slot(0).status_code, 409, 'Source snapshot changed even after returning to create')
        self.assertEqual(len(f.provider.calls), 0)
        with closing(sqlite3.connect(f.path)) as con:
            held={**self.plan,'state':'held'}
            con.execute('UPDATE growthrova_writing_requests SET result_json=?', (json.dumps(held),))
            con.commit()
        self.assertEqual(self.prepare(batchId='d'*32,day=2).status_code, 409)
        f.save_document(copy.deepcopy(f.doc),1,'e')
        self.assertEqual(self.slot(0).status_code, 409)
