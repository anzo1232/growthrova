"""Complete-advert contracts; synthetic Google pixels prove no artistic quality."""
import copy
import unittest

from tests import test_business_nano_banana_pro as pro


class CompleteAdvertTests(unittest.TestCase):
    def test_logo_export_identifies_original_words_after_post_words_change(self):
        import io
        from PIL import Image

        candidate = self.generate().json
        doc = self.base.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json['document']
        doc['posts'][0].update(graphicText='Discuss your bicycle service',
                               supportingLine='Bicycle servicing at our workshop.',
                               callToAction='Enquire about servicing')
        self.base.save_document(doc, 2, '7')
        media = self.base.root+'/'+self.base.ident+'/media'
        pixels = io.BytesIO()
        Image.new('RGBA', (200, 100), (250, 60, 20, 255)).save(pixels, 'PNG')
        imported = self.flow.client.post(media, headers=self.base.headers, data={
            'file': (io.BytesIO(pixels.getvalue()), 'synthetic-logo.png', 'image/png'),
            'rightsStatement': 'Authored synthetic QA logo with marketing permission.',
            'consentStatus': 'owner_asserted'}, content_type='multipart/form-data')
        self.assertEqual(imported.status_code, 201, imported.json)
        logo = imported.json['asset']['assetId']
        selected = self.flow.client.put(media+'/selection', headers=self.base.headers, json=dict(
            revision=3, selectionVersion=0, assetIds=[logo],
            postAssignments=[dict(day=1, assetIds=[logo], staticLogoAssetId=logo)]))
        self.assertEqual(selected.status_code, 200, selected.json)
        preview = self.flow.client.get(media+'/posts/1/'+logo+'/original-review?revision=3&selectionVersion=1', headers=self.base.headers)
        self.assertEqual(preview.status_code, 200, preview.json)
        noted = self.flow.client.put(media+'/posts/1/'+logo+'/review-note', headers=self.base.headers, json=dict(
            revision=3, selectionVersion=1, reviewVersion=0, receipt=preview.json['reviewReceipt'],
            outcome='usable_candidate', note='Synthetic whole logo inspected for retained advert export.'))
        self.assertEqual(noted.status_code, 200, noted.json)
        url = self.base.url+'/'+candidate['operationId']+'/static-preview?revision=3&frame=original'
        result = self.flow.client.get(url, headers=self.base.headers)
        self.assertEqual(result.status_code, 200, result.json)
        manifest = result.json['manifest']
        self.assertEqual(manifest.get('advertCopy'), candidate['advertCopy'],
                         'Export must distinguish retained image wording from later post edits')
        self.assertEqual(manifest['post'], doc['posts'][0], 'Current owner words stay separate and intact')
        self.assertNotEqual(manifest['advertCopy']['headline'], manifest['post']['graphicText'])
        self.assertEqual(manifest['advertCopy']['supportingLine'], '')
        reopened = self.base.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        again = reopened.get(url, headers=self.base.headers)
        self.assertEqual(again.json, result.json)
        self.assertEqual(reopened.get(self.base.url+'/'+candidate['operationId']+'/original', headers=self.base.headers).data, self.flow.png)
        self.assertEqual(len(self.flow.provider.calls), 1, 'Logo export and reopen cannot generate images')

    def test_exact_logo_export_preserves_native_advert_and_permission_holds(self):
        import base64
        import io
        from PIL import Image, ImageChops

        candidate = self.generate().json
        media = self.base.root+'/'+self.base.ident+'/media'
        logo_bytes = io.BytesIO()
        Image.new('RGBA', (200, 100), (250, 60, 20, 255)).save(logo_bytes, 'PNG')
        imported = self.flow.client.post(media, headers=self.base.headers, data={
            'file': (io.BytesIO(logo_bytes.getvalue()), 'synthetic-logo.png', 'image/png'),
            'rightsStatement': 'Authored synthetic QA logo with marketing permission.',
            'consentStatus': 'owner_asserted'}, content_type='multipart/form-data')
        self.assertEqual(imported.status_code, 201, imported.json)
        logo = imported.json['asset']['assetId']
        selected = self.flow.client.put(media+'/selection', headers=self.base.headers, json=dict(
            revision=2, selectionVersion=0, assetIds=[logo],
            postAssignments=[dict(day=1, assetIds=[logo], staticLogoAssetId=logo)]))
        self.assertEqual(selected.status_code, 200, selected.json)
        url = self.base.url+'/'+candidate['operationId']+'/static-preview?revision=2&frame=original'
        held = self.flow.client.get(url, headers=self.base.headers)
        self.assertIn(held.status_code, (400, 409))
        preview = self.flow.client.get(media+'/posts/1/'+logo+'/original-review?revision=2&selectionVersion=1', headers=self.base.headers)
        self.assertEqual(preview.status_code, 200, preview.json)
        noted = self.flow.client.put(media+'/posts/1/'+logo+'/review-note', headers=self.base.headers, json=dict(
            revision=2, selectionVersion=1, reviewVersion=0, receipt=preview.json['reviewReceipt'],
            outcome='usable_candidate', note='Synthetic whole logo inspected for exact advert use.'))
        self.assertEqual(noted.status_code, 200, noted.json)
        result = self.flow.client.get(url, headers=self.base.headers)
        self.assertEqual(result.status_code, 200, result.json)
        manifest = result.json['manifest']
        self.assertEqual(manifest['frameFit'], 'original')
        self.assertEqual(manifest['logoCandidate']['assetId'], logo)
        self.assertEqual(manifest['layout']['copy'], candidate['advertCopy']['headline'])
        self.assertFalse(manifest['approved'])
        with Image.open(io.BytesIO(self.flow.png)) as original, Image.open(io.BytesIO(base64.b64decode(result.json['previewBase64']))) as output:
            self.assertEqual(output.size, original.size)
            x, y, w, h = manifest['layout']['logoBox']
            self.assertEqual(w/h, 2)
            self.assertEqual(output.getpixel((x+w//2, y+h//2)), (250, 60, 20))
            difference = ImageChops.difference(original.convert('RGB'), output.convert('RGB'))
            bounds = difference.getbbox()
            self.assertIsNotNone(bounds)
            self.assertTrue(x <= bounds[0] < bounds[2] <= x+w)
            self.assertTrue(y <= bounds[1] < bounds[3] <= y+h)
        reopened = self.base.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        self.assertEqual(reopened.get(url, headers=self.base.headers).json['previewBase64'], result.json['previewBase64'])
        self.assertEqual(reopened.get(self.base.url+'/'+candidate['operationId']+'/original', headers=self.base.headers).data, self.flow.png)
        review_url = self.base.url+'/'+candidate['operationId']+'/static-observations'
        observed = reopened.post(review_url, headers=self.base.headers, json=dict(
            reviewId='d'*32, expectedRevision=2, expectedReviewVersion=0, exportFrame='original',
            sha256=manifest['previewSha256'], note='Synthetic logo placement inspected, not independent approval.',
            checks={**dict.fromkeys(('visual','factual','brand','commercial','legibility','crop','cta'), 'not_reviewed'),
                    'brand':'checked', 'legibility':'checked', 'wording':'needs_changes'}))
        self.assertEqual(observed.status_code, 200, observed.json)
        self.assertEqual(observed.json['observations'][0]['sha256'], manifest['previewSha256'])
        self.assertFalse(observed.json['approved'])
        self.assertTrue(observed.json['needsChanges'])
        self.assertEqual(observed.json['observations'][0]['checks']['wording'], 'needs_changes')
        # Legacy clients can still record legibility. They cannot clear an
        # explicit wording rejection on the exact final exported bytes.
        legacy = dict(reviewId='e'*32, expectedRevision=2, expectedReviewVersion=1,
            exportFrame='original', sha256=manifest['previewSha256'],
            note='Synthetic lettering readable; wording has not been rechecked.',
            checks={**dict.fromkeys(('visual','factual','brand','commercial','legibility','crop','cta'),
                                   'not_reviewed'), 'legibility':'checked'})
        second = reopened.post(review_url, headers=self.base.headers, json=legacy)
        self.assertEqual(second.status_code, 200, second.json)
        self.assertTrue(second.json['needsChanges'])
        self.assertEqual(reopened.post(review_url, headers=self.base.headers, json=legacy).json, second.json)
        fresh = self.base.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        retained = fresh.get(url, headers=self.base.headers).json
        self.assertEqual(retained['previewBase64'], result.json['previewBase64'])
        self.assertTrue(retained['artworkReview']['needsChanges'])
        self.assertEqual(retained['artworkReview']['observations'], second.json['observations'])
        self.assertTrue(retained['artworkReview']['observations'][0]['current'])
        # Only an explicit word check clears the hold, without artistic or
        # publication approval, another image request, or changed image bytes.
        resolved = fresh.post(review_url, headers=self.base.headers, json={**legacy,
            'reviewId':'f'*32, 'expectedReviewVersion':2,
            'checks':{**legacy['checks'], 'wording':'checked'}})
        self.assertEqual(resolved.status_code, 200, resolved.json)
        self.assertFalse(resolved.json['needsChanges'])
        self.assertFalse(resolved.json['approved'])
        self.assertFalse(resolved.json['canPublish'])
        invalid = fresh.post(review_url, headers=self.base.headers, json={**legacy,
            'reviewId':'8'*32, 'expectedReviewVersion':3,
            'checks':{**legacy['checks'], 'wording':'automatically_verified'}})
        self.assertEqual(invalid.status_code, 400, invalid.json)
        self.assertEqual(fresh.get(url, headers=self.base.headers).json['previewBase64'], result.json['previewBase64'])
        from tests.test_business_growthrova_preview import OTHER
        owner = self.base.auth.owner
        self.base.auth.owner = OTHER
        self.assertEqual(reopened.get(url, headers=self.base.headers).status_code, 403)
        self.base.auth.owner = owner
        withdrawn = reopened.post(media+'/'+logo+'/withdraw-permission', headers=self.base.headers,
                                 json={'reason': 'Withdraw synthetic logo permission.'})
        self.assertEqual(withdrawn.status_code, 200, withdrawn.json)
        self.assertIn(reopened.get(url, headers=self.base.headers).status_code, (400, 409))
        doc = reopened.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json['document']
        doc['brandKit']['name'] = 'Changed synthetic brand'
        self.base.save_document(doc, 2, '7')
        stale = reopened.get(url.replace('revision=2', 'revision=3'), headers=self.base.headers)
        self.assertEqual(stale.status_code, 409, stale.json)
        self.assertEqual(stale.json['code'], 'image_context_changed')
        self.assertEqual(len(self.flow.provider.calls), 1, 'Logo exports must never call an image provider')

    def setUp(self):
        self.flow = pro.NanoBananaProTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.base = self.flow.flow
        doc = copy.deepcopy(self.base.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='classic')
        self.base.save_document(doc, 1, '6')

    def generate(self, **changes):
        return self.flow.generate(**{'expectedRevision': 2, 'renderingMode': 'complete_advert', **changes})

    def test_saved_advert_replay_survives_provider_change_without_new_reservation(self):
        import sqlite3
        from contextlib import closing
        from dataclasses import replace
        import requests

        completed = self.generate().json
        self.flow.provider.failure = requests.Timeout('Synthetic lost acknowledgement')
        changed_brief = 'A closer illustrative wheel detail with quiet space for the headline.'
        uncertain = self.generate(operationId='4'*32, visualBrief=changed_brief).json
        self.assertEqual(completed['state'], 'held')
        self.assertTrue(completed['creativeReviewRequired'])
        self.assertEqual(uncertain['state'], 'uncertain')
        with closing(sqlite3.connect(self.base.path)) as con:
            before = con.execute('SELECT * FROM growthrova_image_requests').fetchall()
        client = self.base.create(image_config=replace(self.flow.config, model='gpt-image-1.5'),
                                  image_http=self.flow.provider).test_client()
        data = {**self.base.data, 'expectedRevision':2, 'renderingMode':'complete_advert',
                'size':'square_2k', 'quality':'standard'}
        for candidate, brief in ((completed, data['visualBrief']), (uncertain, changed_brief)):
            for operation in (candidate['operationId'], '8'*32):
                with self.subTest(state=candidate['state'], operation=operation):
                    response = client.post(self.base.url, headers=self.base.headers,
                                           json={**data, 'operationId':operation, 'visualBrief':brief})
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertEqual(response.json, candidate)
        conflict = client.post(self.base.url, headers=self.base.headers,
                               json={**data, 'visualBrief':changed_brief})
        self.assertEqual(conflict.status_code, 409, conflict.json)
        self.assertEqual(conflict.json['code'], 'operation_conflict')
        new_request = client.post(self.base.url, headers=self.base.headers,
                                 json={**data, 'operationId':'9'*32, 'visualBrief':changed_brief+' A new scene.'})
        self.assertEqual(new_request.status_code, 400, 'A new advert still requires the Pro provider')
        from tests.test_business_growthrova_preview import OTHER
        owner = self.base.auth.owner
        self.base.auth.owner = OTHER
        self.assertEqual(client.post(self.base.url, headers=self.base.headers, json=data).status_code, 403)
        self.base.auth.owner = owner
        saved = client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json
        doc = copy.deepcopy(saved['document'])
        doc['posts'][0]['graphicText'] = 'Time for bicycle servicing'
        self.base.save_document(doc, 2, '7')
        stale = client.post(self.base.url, headers=self.base.headers, json=data)
        self.assertEqual(stale.status_code, 409, stale.json)
        self.assertEqual(stale.json['code'], 'operation_conflict')
        with closing(sqlite3.connect(self.base.path)) as con:
            self.assertEqual(con.execute('SELECT * FROM growthrova_image_requests').fetchall(), before)
        self.assertEqual(len(self.flow.provider.calls), 2)
        self.assertEqual(client.get(self.base.url+'/'+completed['operationId']+'/original',
                                    headers=self.base.headers).data, self.flow.png)

    def test_complete_design_retains_wording_brand_original_and_replay_without_recomposition(self):
        result = self.generate()
        self.assertEqual(result.status_code, 200, result.json)
        candidate = result.json
        self.assertEqual(candidate['renderingMode'], 'complete_advert')
        wording = candidate['advertCopy']
        self.assertEqual(wording['headline'], self.base.doc['posts'][0]['graphicText'])
        self.assertEqual(wording['callToAction'], self.base.doc['posts'][0]['callToAction'])
        self.assertEqual(wording['wordingReview'], 'pending_pixel_review')
        prompt = self.flow.provider.calls[0][1]['json']['contents'][0]['parts'][0]['text']
        # Inspect structured source inputs, not an exact prompt-string mirror.
        import json
        source = json.loads(prompt.split('SOURCE DATA:\n', 1)[1])
        self.assertEqual(source['advertCopy'], wording)
        self.assertEqual(source['brandKit']['primary_color'], '#123456')
        self.assertNotIn('copyDraft', source['post'], 'Long captions must not become tiny artwork text')
        self.assertEqual(self.generate().json, candidate)
        fresh = self.base.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        original = fresh.get(self.base.url+'/'+candidate['operationId']+'/original', headers=self.base.headers)
        self.assertEqual(original.data, self.flow.png)
        held = fresh.get(self.base.url+'/'+candidate['operationId']+'/static-preview?revision=2', headers=self.base.headers)
        self.assertEqual(held.status_code, 409, 'Existing composer must not redraw the complete provider design')
        self.assertEqual(held.json['code'], 'complete_advert_preserved')
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_selected_concepts_keep_distinct_wording_in_durable_complete_advert_slots(self):
        import json
        import sqlite3
        from contextlib import closing
        from business_growthrova_writer import source_material, writing_context
        from business_creative_plans import finish_plan
        from tests.test_business_creative_plans import concepts
        saved = self.flow.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json
        doc = saved['document']
        plan_id = 'a'*32
        plan_input = dict(mode='initial', parentOperationId='', conceptId='')
        cards, issues = finish_plan(concepts(doc['observedFacts'][0], count=3), plan_id,
                                   plan_input, source_material(doc), None)
        self.assertEqual(issues, [])
        plan = dict(operationId=plan_id, state='proposed', creativePlan=plan_input, concepts=cards,
                    sourceContext=writing_context(doc), brandKit=doc['brandKit'])
        with closing(sqlite3.connect(self.base.path)) as con:
            con.execute('INSERT INTO growthrova_writing_requests VALUES(?,?,?,?,?,?,?,?)',
                        (self.base.ident, plan_id, 2, '', plan_id, plan_id, 0, json.dumps(plan)))
            con.commit()
        data = dict(batchId='b'*32, planOperationId=plan_id, expectedRevision=2, day=1,
                    size='square_2k', quality='standard', renderingMode='complete_advert',
                    conceptIds=[c['id'] for c in cards][:2])
        prepared = self.flow.client.post(self.base.url+'/batches', headers=self.base.headers, json=data)
        self.assertEqual(prepared.status_code, 200, prepared.json)
        self.assertEqual(len(self.flow.provider.calls), 0)
        for index in range(2):
            url = self.base.url+'/batches/'+data['batchId']+'/slots/'+str(index)
            result = self.flow.client.post(url, headers=self.base.headers, json={'expectedRevision':2})
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(result.json['advertCopy']['headline'], cards[index]['headline'])
            self.assertEqual(result.json['advertCopy']['callToAction'], cards[index]['callToAction'])
            self.assertEqual(result.json['conceptId'], cards[index]['id'])
            prompt = self.flow.provider.calls[-1][1]['json']['contents'][0]['parts'][0]['text']
            source = json.loads(prompt.split('SOURCE DATA:\n', 1)[1])
            self.assertNotIn('graphicText', source['post'], 'Do not send a conflicting post headline alongside the selected concept')
            self.assertIn('selectedConcept', source, 'Selected buyer motivation must reach the image provider')
            self.assertEqual(source['selectedConcept']['buyerMotivation'], cards[index]['buyerMotivation'])
            self.assertEqual(source['selectedConcept']['heroVisual'], cards[index]['heroVisual'])
            self.assertEqual(source['selectedConcept']['conceptLogic'], cards[index]['conceptLogic'])
            self.assertEqual(source['visualDirection'], cards[index]['visualDirection'])
            self.assertNotIn('visualDirection', source['selectedConcept'])
            self.assertNotIn('evidence', source['selectedConcept'])
            kept = {item['id'] for item in source['business']['evidence']}
            self.assertTrue(kept <= {'fact-0', 'brief-offer', 'brief-callToAction',
                                     'brief-constraints', 'brief-positioning'})
            self.assertEqual(self.flow.client.post(url, headers=self.base.headers,
                                                  json={'expectedRevision':2}).json, result.json)
        alternative = dict(operationId='e'*32, expectedRevision=2, renderingMode='complete_advert',
                           parentOperationId=prepared.json['slots'][0]['operationId'], day=1,
                           size='square_2k', quality='standard',
                           visualBrief='An alternative illustrative bicycle detail with an editorial visual hierarchy.')
        estimate = self.flow.client.post(self.base.url+'/estimate', headers=self.base.headers, json=alternative)
        child = self.flow.client.post(self.base.url, headers=self.base.headers, json=alternative)
        self.assertEqual(child.status_code, 200, child.json)
        self.assertEqual(child.json['advertCopy']['headline'], cards[0]['headline'])
        self.assertEqual(child.json['reservedMicrousd'], estimate.json['reservationMicrousd'])
        self.assertEqual(len(self.flow.provider.calls), 3)
        self.assertEqual(self.flow.client.get(self.base.root+'/'+self.base.ident,
                                             headers=self.base.headers).json, saved)

    def test_complete_advert_review_records_legibility_and_cta_against_exact_original(self):
        candidate = self.generate().json
        url = self.base.url+'/'+candidate['operationId']+'/observations'
        data = dict(reviewId='d'*32, expectedRevision=2, expectedReviewVersion=0,
                    sha256=candidate['sha256'], note='Synthetic pixels only; headline has not been inspected.',
                    checks={key:'not_reviewed' for key in
                            ('visual','factual','brand','commercial','legibility','crop','cta')})
        data['checks']['legibility'] = 'needs_changes'
        result = self.flow.client.post(url, headers=self.base.headers, json=data)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['observations'][0]['checks'], data['checks'])
        self.assertEqual(result.json['observations'][0]['sha256'], candidate['sha256'])
        self.assertFalse(result.json['observations'][0]['independentApproval'])
        self.assertTrue(result.json['compositionHeld'])
        self.assertEqual(self.flow.client.post(url, headers=self.base.headers, json=data).json, result.json)
        self.assertEqual(len(self.flow.provider.calls), 1)
        doc = self.base.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json['document']
        doc['posts'][0]['supportingLine'] = 'Bicycle servicing at our workshop.'
        self.base.save_document(doc, 2, '8')
        current = self.flow.client.get(self.base.url, headers=self.base.headers).json['candidates'][0]
        self.assertFalse(current['observations'][0]['current'], 'Changed requested words must stale the exact-pixel observation')
        self.assertEqual(current['advertCopy']['supportingLine'], '', 'Original requested words must stay unchanged')

    def test_word_accuracy_is_separate_from_legibility_and_survives_reopen(self):
        candidate = self.generate().json
        url = self.base.url+'/'+candidate['operationId']+'/observations'
        checks = dict.fromkeys(('visual', 'factual', 'brand', 'commercial',
                                'legibility', 'crop', 'cta', 'wording'), 'not_reviewed')
        checks.update(legibility='checked', wording='needs_changes')
        data = dict(reviewId='c'*32, expectedRevision=2, expectedReviewVersion=0,
                    sha256=candidate['sha256'], checks=checks,
                    note='Readable synthetic text still omits the requested supporting words.')
        result = self.flow.client.post(url, headers=self.base.headers, json=data)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertTrue(result.json['compositionHeld'])
        self.assertEqual(result.json['observations'][-1]['checks']['wording'], 'needs_changes')
        # Legacy clients remain compatible, but legibility cannot clear a word rejection.
        legacy = copy.deepcopy(data)
        legacy.update(reviewId='d'*32, expectedReviewVersion=1)
        legacy['checks'].pop('wording')
        second = self.flow.client.post(url, headers=self.base.headers, json=legacy)
        self.assertEqual(second.status_code, 200, second.json)
        self.assertTrue(second.json['compositionHeld'])
        self.assertEqual(self.flow.client.post(url, headers=self.base.headers, json=legacy).json, second.json)
        fresh = self.base.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        reopened = fresh.get(self.base.url, headers=self.base.headers).json['candidates'][0]
        self.assertEqual(reopened, second.json)
        self.assertEqual(fresh.get(self.base.url+'/'+candidate['operationId']+'/original',
                                   headers=self.base.headers).data, self.flow.png)
        data.update(reviewId='e'*32, expectedReviewVersion=2)
        data['checks'] = dict.fromkeys(('visual', 'factual', 'brand', 'commercial',
                                       'legibility', 'crop', 'cta', 'wording'), 'checked')
        resolved = fresh.post(url, headers=self.base.headers, json=data)
        self.assertEqual(resolved.status_code, 200, resolved.json)
        self.assertFalse(resolved.json['compositionHeld'])
        self.assertFalse(resolved.json['observations'][-1]['independentApproval'])
        self.assertFalse(resolved.json['canPublish'])
        self.assertEqual(len(self.flow.provider.calls), 1)
        invalid = copy.deepcopy(data)
        invalid.update(reviewId='f'*32, expectedReviewVersion=3)
        invalid['checks']['wording'] = 'automatically_verified'
        self.assertEqual(fresh.post(url, headers=self.base.headers, json=invalid).status_code, 400)

    def test_invalid_mode_and_missing_brand_never_reserve_or_call(self):
        bad = self.generate(renderingMode='auto_publish')
        self.assertEqual(bad.status_code, 400)
        doc = copy.deepcopy(self.base.doc)
        self.base.save_document(doc, 2, '7')
        result = self.flow.generate(expectedRevision=3, renderingMode='complete_advert')
        self.assertEqual(result.status_code, 400)
        self.assertIn('brand', result.json['error'].lower())
        self.assertEqual(self.flow.provider.calls, [])

    def test_advert_cta_review_stales_on_destination_or_objective_change_without_new_pixels(self):
        candidate = self.generate().json
        root = self.base.url+'/'+candidate['operationId']
        data = dict(reviewId='d'*32, expectedRevision=2, expectedReviewVersion=0,
                    sha256=candidate['sha256'],
                    note='Checked this synthetic original against the saved customer action only.',
                    checks=dict.fromkeys(('visual','factual','brand','commercial','legibility','crop','cta'),
                                         'not_reviewed'))
        data['checks']['cta'] = 'checked'
        client = self.flow.client
        observed = client.post(root+'/observations', headers=self.base.headers, json=data)
        self.assertEqual(observed.status_code, 200, observed.json)
        self.assertTrue(observed.json['observations'][0]['current'])
        doc = client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json['document']
        doc['posts'][1]['destinationUrl'] = 'https://example.org/another-post'
        self.base.save_document(doc, 2, '7')
        def status():
            return client.get(self.base.url, headers=self.base.headers).json['candidates'][0]
        self.assertTrue(status()['observations'][0]['current'], 'Sibling destination is outside this review')
        for revision, field, value, mutation in (
                (3, 'destinationUrl', 'https://example.org/book-a-service', '8'),
                (4, 'objective', 'Build awareness', '9'),
                (5, 'destinationUrl', '', 'a')):
            with self.subTest(field=field, value=value):
                doc['posts'][0][field] = value
                self.base.save_document(doc, revision, mutation)
                stale = status()
                self.assertFalse(stale['observations'][-1]['current'],
                                 'CTA review cannot remain current after its destination or objective changes')
                self.assertTrue(stale['compositionHeld'])
                data.update(reviewId=mutation*32, expectedRevision=revision+1,
                            expectedReviewVersion=stale['reviewVersion'])
                reviewed = client.post(root+'/observations', headers=self.base.headers, json=data)
                self.assertEqual(reviewed.status_code, 200, reviewed.json)
                self.assertTrue(reviewed.json['observations'][-1]['current'])
                self.assertFalse(reviewed.json['observations'][0]['current'])
        reopened = self.base.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        retained = reopened.get(self.base.url, headers=self.base.headers).json['candidates'][0]
        self.assertEqual(retained, status())
        self.assertEqual(retained['advertCopy'], candidate['advertCopy'])
        self.assertEqual(reopened.get(root+'/original', headers=self.base.headers).data, self.flow.png)
        self.assertFalse(retained['canPublish'])
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_legacy_background_remains_readable_and_mode_changes_conflict(self):
        legacy = self.flow.generate(expectedRevision=2)
        self.assertEqual(legacy.status_code, 200, legacy.json)
        self.assertNotIn('advertCopy', legacy.json)
        self.assertEqual(self.generate().status_code, 409)
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_saved_supporting_line_reaches_quote_original_and_alternative_without_caption(self):
        import json
        doc = copy.deepcopy(self.base.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='classic')
        line = 'Bicycle servicing at our workshop.'
        doc['posts'][0]['supportingLine'] = line
        saved = self.base.save_document(doc, 2, '8')
        self.assertEqual(saved['document']['posts'][0].get('supportingLine'), line)
        data = dict(self.flow.flow.data, expectedRevision=3, renderingMode='complete_advert',
                    size='square_2k', quality='standard')
        quote = self.flow.client.post(self.base.url+'/estimate', headers=self.base.headers, json=data)
        result = self.flow.client.post(self.base.url, headers=self.base.headers, json=data)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['advertCopy']['supportingLine'], line)
        self.assertEqual(result.json['reservedMicrousd'], quote.json['reservationMicrousd'])
        source = json.loads(self.flow.provider.calls[0][1]['json']['contents'][0]['parts'][0]['text'].split('SOURCE DATA:\n', 1)[1])
        self.assertEqual(source['advertCopy']['supportingLine'], line)
        self.assertNotIn('textSafeInsetPercent', source['artworkLayout'])
        self.assertTrue(source['artworkLayout'].get('spacing'))
        self.assertNotIn('copyDraft', source['post'])
        child = self.flow.client.post(self.base.url, headers=self.base.headers, json={**data,
            'operationId':'e'*32, 'parentOperationId':result.json['operationId'],
            'visualBrief':'An alternative illustrative workshop scene with a deliberately different composition.'})
        self.assertEqual(child.status_code, 200, child.json)
        self.assertEqual(child.json['advertCopy'], result.json['advertCopy'])
        fresh = self.base.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        reopened = fresh.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json
        self.assertEqual(reopened['document'], saved['document'])
        self.assertEqual(reopened['revision'], saved['revision'])
        self.assertEqual(len(self.flow.provider.calls), 2)

    def test_supporting_line_limit_is_enforced_before_save_or_provider(self):
        doc = copy.deepcopy(self.base.doc)
        doc['posts'][0]['supportingLine'] = 'x'*181
        result = self.base.client.post(self.base.root, headers=self.base.headers, json={
            'id':self.base.ident, 'mutationId':'8'*32, 'expectedRevision':2, 'document':doc})
        self.assertEqual(result.status_code, 400, result.json)
        self.assertEqual(self.flow.provider.calls, [])

    def test_alternative_holds_when_saved_artwork_words_changed(self):
        candidate = self.generate().json
        saved = self.base.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json
        doc = saved['document']
        doc['posts'][0]['supportingLine'] = 'Bicycle servicing at our workshop.'
        self.base.save_document(doc, 2, '8')
        result = self.generate(expectedRevision=3, operationId='e'*32,
            parentOperationId=candidate['operationId'],
            visualBrief='An alternative illustrative workshop scene with a deliberately different composition.')
        self.assertEqual(result.status_code, 409, result.json)
        self.assertEqual(result.json['code'], 'image_context_changed')
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_alternative_holds_changed_action_before_quote_or_reservation(self):
        import sqlite3
        from contextlib import closing

        doc = self.base.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json['document']
        doc['posts'][0]['destinationUrl'] = 'https://example.org/service-enquiry'
        self.base.save_document(doc, 2, '8')
        parent = self.generate(expectedRevision=3).json
        with closing(sqlite3.connect(self.base.path)) as con:
            before = con.execute('SELECT * FROM growthrova_image_requests').fetchall()
        revision = 3
        for index, change in enumerate((
                {'destinationUrl': 'https://example.org/shop'},
                {'destinationUrl': ''},
                {'objective': 'Book a workshop visit'}), start=9):
            with self.subTest(change=change):
                changed = copy.deepcopy(doc)
                changed['posts'][0].update(change)
                saved = self.base.save_document(changed, revision, format(index, 'x'))
                revision += 1
                data = dict(self.base.data, expectedRevision=revision, operationId='e'*32,
                    parentOperationId=parent['operationId'], renderingMode='complete_advert',
                    size='square_2k', quality='standard',
                    visualBrief='An alternative illustrative workshop scene with a deliberately different composition.')
                for suffix in ('/estimate', ''):
                    result = self.flow.client.post(self.base.url+suffix, headers=self.base.headers, json=data)
                    self.assertEqual(result.status_code, 409, result.json)
                    self.assertEqual(result.json['code'], 'image_context_changed')
                    self.assertIn('destination', result.json['error'].lower())
                self.assertEqual(len(self.flow.provider.calls), 1)
                with closing(sqlite3.connect(self.base.path)) as con:
                    self.assertEqual(con.execute('SELECT * FROM growthrova_image_requests').fetchall(), before)
                self.assertEqual(self.flow.client.get(self.base.url+'/'+parent['operationId']+'/original',
                                 headers=self.base.headers).data, self.flow.png)
                reopened = self.flow.client.get(self.base.root+'/'+self.base.ident,
                                               headers=self.base.headers).json
                self.assertEqual(reopened['document'], saved['document'])
                self.assertEqual(reopened['revision'], saved['revision'])

        # A caption-only edit keeps the requested advert words and action.
        # Do not block an unrelated saved owner edit or silently restore it.
        doc['posts'][0]['copyDraft'] = 'Arrange a bicycle service with our workshop. Contact us to discuss the work your bicycle needs.'
        self.base.save_document(doc, revision, 'f')
        data['expectedRevision'] = revision + 1
        quote = self.flow.client.post(self.base.url+'/estimate', headers=self.base.headers, json=data)
        self.assertEqual(quote.status_code, 200, quote.json)
        child = self.flow.client.post(self.base.url, headers=self.base.headers, json=data)
        self.assertEqual(child.status_code, 200, child.json)
        self.assertEqual(child.json['reservedMicrousd'], quote.json['reservationMicrousd'])
        self.assertEqual(child.json['advertCopy'], parent['advertCopy'])
        self.assertEqual(len(self.flow.provider.calls), 2)

    def test_internal_supporting_notes_are_saved_but_held_before_generation(self):
        doc = self.base.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json['document']
        doc['posts'][0]['supportingLine'] = 'Draft direction: add an offer here'
        saved = self.base.save_document(doc, 2, '8')
        self.assertEqual(saved['document']['posts'][0]['supportingLine'], doc['posts'][0]['supportingLine'])
        result = self.generate(expectedRevision=3)
        self.assertEqual(result.status_code, 400, result.json)
        self.assertEqual(self.flow.provider.calls, [])

    def test_omitting_a_previous_supporting_line_invalidates_word_review(self):
        from business_marketing_drafts import normalise_document
        doc = self.base.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json['document']
        doc['posts'][0].update(supportingLine='Bicycle servicing at our workshop.', status='copy_reviewed')
        previous = normalise_document(doc)
        self.assertEqual(previous['posts'][0]['status'], 'copy_reviewed')
        del doc['posts'][0]['supportingLine']
        changed = normalise_document(doc, previous)
        self.assertEqual(changed['posts'][0]['status'], 'draft')


if __name__ == '__main__':
    unittest.main()
