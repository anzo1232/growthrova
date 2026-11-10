"""Disconnected social drafts: real private store/render, synthetic auth/pixels only."""
import copy
import hashlib
import unittest
from unittest.mock import patch

from tests import test_business_growthrova_images as images
from tests.test_business_growthrova_preview import ORG, OTHER


class SocialDraftTests(unittest.TestCase):
    def setUp(self):
        self.flow = images.GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.flow.configured()
        candidate = self.flow.generate().json
        doc = copy.deepcopy(self.flow.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='modern')
        self.flow.save_document(doc, 1, '6')
        self.operation = candidate['operationId']
        self.url = self.flow.root+'/'+self.flow.ident+'/social-drafts'
        self.preview = self.flow.client.get(self.flow.url+'/'+self.operation+
            '/static-preview?revision=2&frame=portrait', headers=self.flow.headers).json
        self.data = dict(draftId='9'*32, expectedRevision=2, operationId=self.operation,
            frame='portrait', artworkSha256=self.preview['manifest']['previewSha256'],
            channels=['instagram', 'facebook'], localTime='2027-03-28T09:30', timezone='Europe/London',
            utcOffsetMinutes=60)

    def save(self, **changes):
        return self.flow.client.post(self.url, headers=self.flow.headers, json={**self.data, **changes})

    def test_saved_reads_recheck_original_access_after_database_read(self):
        from business_marketing_offline import OfflineMarketingDocuments
        from tests.test_business_growthrova_preview import USER
        original = self.save().json['draft']
        connect = OfflineMarketingDocuments._connect
        artwork_url = self.url+'/'+original['draftId']+'/artwork'
        for url, query in ((self.url, 'SELECT draft_json FROM growthrova_social_drafts'),
                           (artwork_url, 'SELECT artwork FROM growthrova_social_drafts')):
            for change, status in ((dict(allowed=False), 403), (dict(status=503), 503),
                                   (dict(owner=OTHER), 403)):
                with self.subTest(url=url, change=change):
                    reads = []
                    def during_read(sql):
                        if sql.startswith(query):
                            reads.append(sql)
                            for key, value in change.items():
                                setattr(self.flow.auth, key, value)
                    def traced_connect(repo):
                        con = connect(repo)
                        con.set_trace_callback(during_read)
                        return con
                    try:
                        with patch.object(OfflineMarketingDocuments, '_connect', traced_connect):
                            response = self.flow.client.get(url, headers=self.flow.headers)
                    finally:
                        self.flow.auth.allowed = True
                        self.flow.auth.status = 200
                        self.flow.auth.owner = USER
                    self.assertTrue(reads)
                    self.assertEqual(response.status_code, status)
                    self.assertTrue(response.is_json, 'Denied reads must not release artwork bytes')
                    self.assertNotIn('drafts', response.json)
                    self.assertNotIn(original['artworkSha256'], response.get_data(as_text=True))
        # A fresh app can recover the unchanged snapshot after access returns.
        with patch('business_campaign_assets.render_static_candidate',
                   side_effect=AssertionError('Saved reads must not render artwork')):
            client = self.flow.create(image_config=self.flow.config,
                image_http=self.flow.provider).test_client()
            self.assertEqual(client.get(self.url, headers=self.flow.headers).json['drafts'], [original])
            pixels = client.get(artwork_url, headers=self.flow.headers)
        self.assertEqual(pixels.status_code, 200)
        self.assertEqual(hashlib.sha256(pixels.data).hexdigest(), original['artworkSha256'])
        self.assertEqual(len(self.flow.provider.calls), 1, 'Saved reads never regenerate artwork')

    def test_save_replay_rechecks_access_after_read_without_recreating_draft(self):
        from business_marketing_offline import OfflineMarketingDocuments
        from tests.test_business_growthrova_preview import USER
        original = self.save().json['draft']
        connect = OfflineMarketingDocuments._connect
        for change, status in ((dict(allowed=False), 403), (dict(status=503), 503),
                               (dict(owner=OTHER), 403)):
            with self.subTest(change=change):
                reads = []
                def during_read(sql):
                    if sql.startswith('SELECT * FROM growthrova_social_drafts'):
                        reads.append(sql)
                        for key, value in change.items():
                            setattr(self.flow.auth, key, value)
                def traced_connect(repo):
                    con = connect(repo)
                    con.set_trace_callback(during_read)
                    return con
                try:
                    with patch.object(OfflineMarketingDocuments, '_connect', traced_connect):
                        response = self.save()
                finally:
                    self.flow.auth.allowed = True
                    self.flow.auth.status = 200
                    self.flow.auth.owner = USER
                self.assertTrue(reads)
                self.assertEqual(response.status_code, status, response.json)
                self.assertNotIn('draft', response.json)
                client = self.flow.create(image_config=self.flow.config,
                    image_http=self.flow.provider).test_client()
                self.assertEqual(client.get(self.url, headers=self.flow.headers).json['drafts'], [original])
        with patch('business_campaign_assets.render_static_candidate',
                   side_effect=AssertionError('Replay must not render artwork')):
            recovered = self.save()
        self.assertEqual(recovered.status_code, 200, recovered.json)
        self.assertEqual(recovered.json['draft'], original)
        pixels = self.flow.client.get(self.url+'/'+original['draftId']+'/artwork', headers=self.flow.headers)
        self.assertEqual(hashlib.sha256(pixels.data).hexdigest(), original['artworkSha256'])
        self.assertEqual(len(self.flow.provider.calls), 1, 'Replay never regenerates artwork')

    def test_cancel_rechecks_access_after_transaction_wait_and_preserves_recoverable_draft(self):
        from business_marketing_offline import OfflineMarketingDocuments
        from tests.test_business_growthrova_preview import USER
        original = self.save().json['draft']
        connect = OfflineMarketingDocuments._connect
        cancel_url = self.url+'/'+original['draftId']+'/cancel'
        for change, status in ((dict(allowed=False), 403), (dict(status=503), 503),
                               (dict(owner=OTHER), 403)):
            with self.subTest(change=change):
                reached_transaction = []
                def during_transaction(sql):
                    if sql == 'BEGIN IMMEDIATE':
                        reached_transaction.append(True)
                        for key, value in change.items():
                            setattr(self.flow.auth, key, value)
                def traced_connect(repo):
                    con = connect(repo)
                    con.set_trace_callback(during_transaction)
                    return con
                try:
                    # Deterministically change access at SQLite's transaction
                    # boundary, after the route's initial authenticated read.
                    with patch.object(OfflineMarketingDocuments, '_connect', traced_connect):
                        response = self.flow.client.post(cancel_url, headers=self.flow.headers, json={})
                finally:
                    self.flow.auth.allowed = True
                    self.flow.auth.status = 200
                    self.flow.auth.owner = USER
                self.assertTrue(reached_transaction)
                self.assertEqual(response.status_code, status, response.json)
                self.assertNotIn('draft', response.json)
                client = self.flow.create(image_config=self.flow.config,
                    image_http=self.flow.provider).test_client()
                self.assertEqual(client.get(self.url, headers=self.flow.headers).json['drafts'], [original])
        recovered = self.flow.client.post(cancel_url, headers=self.flow.headers, json={})
        self.assertEqual(recovered.status_code, 200, recovered.json)
        self.assertEqual(recovered.json['draft'], {**original, 'state': 'cancelled'})
        self.assertEqual(self.flow.client.post(cancel_url, headers=self.flow.headers, json={}).json, recovered.json)
        pixels = self.flow.client.get(self.url+'/'+original['draftId']+'/artwork', headers=self.flow.headers)
        self.assertEqual(hashlib.sha256(pixels.data).hexdigest(), original['artworkSha256'])
        self.assertEqual(len(self.flow.provider.calls), 1, 'Cancellation never regenerates artwork')

    def test_access_changes_during_render_never_persist_or_release_posting_draft(self):
        import business_campaign_assets as assets
        from tests.test_business_growthrova_preview import USER
        render = assets.render_static_candidate
        for change, status in ((dict(allowed=False), 403), (dict(status=503), 503),
                               (dict(owner=OTHER), 403)):
            with self.subTest(change=change):
                def changed_access(*args, **kwargs):
                    result = render(*args, **kwargs)
                    for key, value in change.items():
                        setattr(self.flow.auth, key, value)
                    return result
                try:
                    with patch.object(assets, 'render_static_candidate', side_effect=changed_access):
                        response = self.save()
                finally:
                    self.flow.auth.allowed = True
                    self.flow.auth.status = 200
                    self.flow.auth.owner = USER
                self.assertEqual(response.status_code, status, response.json)
                self.assertNotIn('draft', response.json)
                # Reopen through the real route/store, rather than assuming an
                # error response means the transaction was rolled back.
                client = self.flow.create(image_config=self.flow.config,
                    image_http=self.flow.provider).test_client()
                self.assertEqual(client.get(self.url, headers=self.flow.headers).json['drafts'], [])
        recovered = self.save()
        self.assertEqual(recovered.status_code, 201, recovered.json)
        self.assertEqual(self.save().json['draft'], recovered.json['draft'])
        self.assertEqual(len(self.flow.provider.calls), 1, 'Only the original synthetic image call')

    def test_exact_saved_export_media_checks_survive_replay_reopen_and_cancel(self):
        draft = self.save(channels=['instagram', 'facebook', 'linkedin', 'tiktok', 'x']).json['draft']
        manifest = self.preview['manifest']
        for check in draft['channelChecks']:
            self.assertEqual(check['mediaCheck'], dict(width=manifest['width'], height=manifest['height'],
                bytes=manifest['previewBytes'], state='needs_rendition' if check['channel']=='tiktok' else 'validation_pending'))
            self.assertEqual(check['state'], 'blocked')
        self.assertEqual(self.save(channels=draft['channels']).json['draft'], draft)
        client = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        self.assertEqual(client.get(self.url, headers=self.flow.headers).json['drafts'][0], draft)
        pixels = client.get(self.url+'/'+draft['draftId']+'/artwork', headers=self.flow.headers).data
        self.assertEqual(len(pixels), manifest['previewBytes'])
        self.assertEqual(hashlib.sha256(pixels).hexdigest(), draft['artworkSha256'])
        cancelled = client.post(self.url+'/'+draft['draftId']+'/cancel', headers=self.flow.headers, json={}).json['draft']
        self.assertEqual(cancelled['channelChecks'], draft['channelChecks'])
        self.assertEqual(len(self.flow.provider.calls), 1, 'Media checks never generate or resize images')

    def test_exact_destination_is_server_checked_frozen_and_replayed_without_lookup(self):
        from business_social_accounts import SocialAccountConfig
        from tests.test_business_social_accounts import Provider
        provider = Provider(dict(activeSocialAccounts=['linkedin'], displayNames=[
            dict(platform='linkedin', id='company-42', displayName='Workshop Page', type='corporate')]))
        config = SocialAccountConfig(enabled=True, api_key='synthetic-master',
                                    profile_key_for_org=lambda org: 'synthetic-profile' if org == ORG else None)
        def reopen():
            return self.flow.create(image_config=self.flow.config, image_http=self.flow.provider,
                social_account_config=config, social_account_http=provider).test_client()
        self.flow.client = reopen()
        result = self.save(channels=['linkedin'], destinationAccounts={'linkedin': 'company-42'})
        self.assertEqual(result.status_code, 201, result.json)
        draft = result.json['draft']
        self.assertEqual(draft['destinationAccounts'], {'linkedin': dict(
            id='company-42', name='Workshop Page', accountType='company')})
        self.assertEqual(draft['channelChecks'][0]['destinationAccount'], draft['destinationAccounts']['linkedin'])
        self.assertFalse(draft['canPublish'])
        self.assertIsNone(draft['approval'])
        provider.payload = {}  # Relinking/disconnect cannot retarget an immutable snapshot.
        self.assertEqual(self.save(channels=['linkedin'], destinationAccounts={'linkedin': 'company-42'}).json['draft'], draft)
        self.assertEqual(len(provider.calls), 1, 'Acknowledgement replay never needs provider availability')
        self.flow.client = reopen()
        self.assertEqual(self.flow.client.get(self.url, headers=self.flow.headers).json['drafts'][0], draft)
        conflict = self.save(channels=['linkedin'], destinationAccounts={'linkedin': 'another-company'})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(len(provider.calls), 1)

    def test_stale_expired_unsupported_and_foreign_destinations_preserve_drafts(self):
        from business_social_accounts import SocialAccountConfig
        from tests.test_business_social_accounts import Provider
        provider = Provider({})
        config = SocialAccountConfig(enabled=True, api_key='synthetic-master',
                                    profile_key_for_org=lambda org: 'synthetic-profile')
        self.flow.client = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider,
            social_account_config=config, social_account_http=provider).test_client()
        original = self.save().json['draft']
        for channel, item in [('linkedin', dict(id='changed', type='corporate')),
                              ('linkedin', dict(id='wanted', type='corporate', refreshDaysRemaining=-1)),
                              ('instagram', dict(id='wanted', type='personal'))]:
            with self.subTest(channel=channel, item=item):
                provider.payload = dict(activeSocialAccounts=[channel], displayNames=[
                    dict(platform=channel, displayName='Current identity', **item)])
                response = self.save(draftId='8'*32, channels=[channel], destinationAccounts={channel: 'wanted'})
                self.assertEqual(response.status_code, 400, response.json)
                self.assertIn('destination', response.json['error'].lower())
        for destinations in ({'x': 'foreign'}, {'instagram': {'id': 'forged'}}, []):
            response = self.save(draftId='8'*32, destinationAccounts=destinations)
            self.assertEqual(response.status_code, 400, response.json)
        rows = self.flow.client.get(self.url, headers=self.flow.headers).json['drafts']
        self.assertEqual(rows, [original])
        calls = len(provider.calls)
        self.flow.auth.allowed = False
        self.assertEqual(self.save(draftId='8'*32, destinationAccounts={'instagram': 'wanted'}).status_code, 403)
        self.assertEqual(len(provider.calls), calls)

    def test_destination_lookup_failure_and_revocation_never_save_or_leak_identity(self):
        from business_social_accounts import SocialAccountConfig
        from tests.test_business_social_accounts import Provider
        provider = Provider(dict(activeSocialAccounts=['twitter'], displayNames=[
            dict(platform='twitter', id='x-42', displayName='Private destination')]))
        config = SocialAccountConfig(enabled=True, api_key='synthetic-master',
                                    profile_key_for_org=lambda org: 'synthetic-profile')
        self.flow.client = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider,
            social_account_config=config, social_account_http=provider).test_client()
        provider.status = 403
        result = self.save(channels=['x'], destinationAccounts={'x': 'x-42'})
        self.assertEqual(result.status_code, 503, result.json)
        self.assertNotIn('synthetic-profile', result.get_data(as_text=True))
        self.assertEqual(self.flow.client.get(self.url, headers=self.flow.headers).json['drafts'], [])
        provider.status = 200
        provider.on_read = lambda: setattr(self.flow.auth, 'allowed', False)
        result = self.save(channels=['x'], destinationAccounts={'x': 'x-42'})
        self.assertEqual(result.status_code, 403, result.json)
        self.assertNotIn('Private destination', result.get_data(as_text=True))
        self.flow.auth.allowed = True
        self.assertEqual(self.flow.client.get(self.url, headers=self.flow.headers).json['drafts'], [])
        provider.on_read = lambda: None
        result = self.save(channels=['x'], destinationAccounts={'x': 'x-42'})
        self.assertEqual(result.status_code, 201, result.json)
        self.assertFalse(result.json['draft']['canPublish'])

    def test_exact_artwork_caption_durable_replay_and_cancel_without_provider(self):
        result = self.save()
        self.assertEqual(result.status_code, 201, result.json)
        draft = result.json['draft']
        self.assertEqual(draft['state'], 'draft')
        self.assertFalse(draft['canPublish'])
        self.assertEqual(draft['schedule']['utcTime'], '2027-03-28T08:30:00Z')
        self.assertEqual(draft['caption'], self.flow.doc['posts'][0]['copyDraft'])
        self.assertEqual(draft['artworkSha256'], self.data['artworkSha256'])
        self.assertIsNone(draft['approval'])
        self.assertEqual(self.save().json['draft'], draft)
        client = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        reopened = client.get(self.url, headers=self.flow.headers).json['drafts'][0]
        self.assertEqual(reopened, draft)
        pixels = client.get(self.url+'/'+draft['draftId']+'/artwork', headers=self.flow.headers)
        self.assertEqual(hashlib.sha256(pixels.data).hexdigest(), draft['artworkSha256'])
        cancelled = client.post(self.url+'/'+draft['draftId']+'/cancel', headers=self.flow.headers, json={})
        self.assertEqual(cancelled.json['draft']['state'], 'cancelled')
        self.assertEqual(self.save().json['draft']['state'], 'cancelled', 'Replay cannot revive a cancelled draft')
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_caption_holds_preserve_long_draft_across_replay_reopen_and_cancel(self):
        doc = copy.deepcopy(self.flow.client.get(self.flow.root+'/'+self.flow.ident,
            headers=self.flow.headers).json['document'])
        caption = 'A' * 2200 + '\n'
        doc['posts'][0]['copyDraft'] = caption
        self.flow.save_document(doc, 2, '7')
        preview = self.flow.client.get(self.flow.url+'/'+self.operation+
            '/static-preview?revision=3&frame=portrait', headers=self.flow.headers).json
        self.data.update(expectedRevision=3, artworkSha256=preview['manifest']['previewSha256'])
        response = self.save(channels=['instagram', 'linkedin', 'tiktok', 'x', 'facebook'])
        self.assertEqual(response.status_code, 201, response.json)
        draft = response.json['draft']
        checks = {item['channel']: item for item in draft['channelChecks']}
        for channel in ('instagram', 'tiktok'):
            self.assertIn('caption_too_long', [r['code'] for r in checks[channel]['reasons']])
            self.assertEqual(checks[channel]['captionCheck']['characters'], 2201)
        self.assertNotIn('caption_too_long', [r['code'] for r in checks['linkedin']['reasons']])
        self.assertIn('line_breaks_unsupported', [r['code'] for r in checks['tiktok']['reasons']])
        self.assertEqual(draft['caption'], caption, 'Never trim or rewrite frozen caption')
        client = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        self.assertEqual(client.get(self.url, headers=self.flow.headers).json['drafts'][0], draft)
        self.assertEqual(self.save(channels=draft['channels']).json['draft'], draft)
        cancelled = client.post(self.url+'/'+draft['draftId']+'/cancel', headers=self.flow.headers, json={})
        self.assertEqual(cancelled.json['draft']['channelChecks'], draft['channelChecks'])
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_channel_captions_are_frozen_separately_replayed_and_reopened(self):
        captions = {'instagram': 'Book your workshop visit. 😀', 'facebook': 'Ask about a bicycle service.\nChoose your visit.'}
        result = self.save(channelCaptions=captions)
        self.assertEqual(result.status_code, 201, result.json)
        draft = result.json['draft']
        self.assertEqual(draft['channelCaptions'], captions)
        self.assertEqual(draft['caption'], self.preview['manifest']['post']['copyDraft'])
        self.assertEqual(draft['manifest'], self.preview['manifest'])
        for check in draft['channelChecks']:
            self.assertEqual(check['captionCheck']['characters'], len(captions[check['channel']]))
        self.assertEqual(self.save(channelCaptions=captions).json['draft'], draft)
        self.assertEqual(self.save(channelCaptions={**captions, 'instagram': 'Changed'}).status_code, 409)
        client = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        self.assertEqual(client.get(self.url, headers=self.flow.headers).json['drafts'][0], draft)
        cancelled = client.post(self.url+'/'+draft['draftId']+'/cancel', headers=self.flow.headers, json={}).json['draft']
        self.assertEqual(cancelled['channelCaptions'], captions)
        pixels = client.get(self.url+'/'+draft['draftId']+'/artwork', headers=self.flow.headers).data
        self.assertEqual(hashlib.sha256(pixels).hexdigest(), draft['artworkSha256'])
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_new_draft_can_correct_caption_and_time_preserving_original_and_pixels(self):
        original = self.save(channelCaptions={'instagram': 'a'*2201}).json['draft']
        changed = dict(draftId='8'*32, channelCaptions={'instagram': 'Book a bicycle service.',
                        'facebook': original['channelCaptions']['facebook']},
                       localTime='2027-10-31T01:30', utcOffsetMinutes=0)
        result = self.save(**changed)
        self.assertEqual(result.status_code, 201, result.json)
        revised = result.json['draft']
        self.assertEqual(revised['schedule']['utcTime'], '2027-10-31T01:30:00Z')
        self.assertEqual(revised['manifest'], original['manifest'])
        self.assertEqual(revised['artworkSha256'], original['artworkSha256'])
        self.assertNotIn('caption_too_long', [r['code'] for r in revised['channelChecks'][0]['reasons']])
        self.assertIsNone(revised['approval'])
        self.assertFalse(revised['canPublish'])
        self.assertEqual(self.save(**changed).json['draft'], revised)
        client = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        reopened = {d['draftId']: d for d in client.get(self.url, headers=self.flow.headers).json['drafts']}
        self.assertEqual(reopened[original['draftId']], original)
        self.assertEqual(reopened[revised['draftId']], revised)
        for draft in (original, revised):
            pixels = client.get(self.url+'/'+draft['draftId']+'/artwork', headers=self.flow.headers).data
            self.assertEqual(hashlib.sha256(pixels).hexdigest(), original['artworkSha256'])
        self.assertEqual(len(self.flow.provider.calls), 1, 'Only the initial synthetic image request')

    def test_revision_lineage_survives_replay_reopen_and_parent_cancellation(self):
        original = self.save().json['draft']
        changes = dict(draftId='8'*32, sourceDraftId=original['draftId'],
                       channelCaptions={'instagram': 'Corrected workshop caption.'})
        response = self.save(**changes)
        self.assertEqual(response.status_code, 201, response.json)
        revised = response.json['draft']
        self.assertEqual(revised['sourceDraftId'], original['draftId'])
        self.flow.client.post(self.url+'/'+original['draftId']+'/cancel', headers=self.flow.headers, json={})
        self.assertEqual(self.save(**changes).json['draft'], revised)
        self.assertEqual(self.save(**{**changes, 'sourceDraftId': '7'*32}).status_code, 409)
        client = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        reopened = {d['draftId']: d for d in client.get(self.url, headers=self.flow.headers).json['drafts']}
        self.assertEqual(reopened[revised['draftId']], revised)
        self.assertEqual(reopened[original['draftId']]['state'], 'cancelled')
        self.assertEqual(reopened[original['draftId']]['caption'], original['caption'])
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_revision_source_must_be_existing_same_document_and_exact_artwork(self):
        self.save()
        for source, status in (('7'*32, 404), ('bad', 400), (None, 400), ('8'*32, 400)):
            with self.subTest(source=source):
                result = self.save(draftId='8'*32, sourceDraftId=source)
                self.assertEqual(result.status_code, status, result.json)
        # A legitimate saved draft cannot be used as lineage for a different frame.
        square = self.flow.client.get(self.flow.url+'/'+self.operation+
            '/static-preview?revision=2&frame=square', headers=self.flow.headers).json
        result = self.save(draftId='8'*32, sourceDraftId='9'*32, frame='square',
                           artworkSha256=square['manifest']['previewSha256'])
        self.assertEqual(result.status_code, 409, result.json)
        self.assertEqual(len(self.flow.client.get(self.url, headers=self.flow.headers).json['drafts']), 1)
        # A source ID from another campaign is not a valid history link, even for the same owner.
        other_id = '5'*32
        created = self.flow.client.post(self.flow.root, headers=self.flow.headers, json={
            'id': other_id, 'mutationId': '4'*32, 'expectedRevision': 0, 'document': self.flow.doc})
        self.assertEqual(created.status_code, 200, created.json)
        foreign = self.flow.client.post(self.url.replace(self.flow.ident, other_id), headers=self.flow.headers,
            json={**self.data, 'draftId': '8'*32, 'expectedRevision': 1, 'sourceDraftId': '9'*32})
        self.assertEqual(foreign.status_code, 404, foreign.json)
        doc = copy.deepcopy(self.flow.client.get(self.flow.root+'/'+self.flow.ident,
            headers=self.flow.headers).json['document'])
        doc['posts'][0]['copyDraft'] = 'New campaign caption requiring review.'
        self.flow.save_document(doc, 2, '7')
        stale = self.save(draftId='8'*32, sourceDraftId='9'*32, expectedRevision=3)
        self.assertEqual(stale.status_code, 409, stale.json)

    def test_channel_caption_validation_and_legacy_defaults(self):
        for captions in (None, [], {'x': 'Unselected'}, {'instagram': 3},
                         {'instagram': ''}, {'instagram': 'a'*3001}):
            with self.subTest(captions=captions):
                self.assertEqual(self.save(channelCaptions=captions).status_code, 400)
        result = self.save(channelCaptions={'instagram': 'a'*2201})
        self.assertEqual(result.status_code, 201, result.json)
        draft = result.json['draft']
        self.assertEqual(draft['channelCaptions']['facebook'], draft['caption'])
        checks = {c['channel']: c for c in draft['channelChecks']}
        self.assertIn('caption_too_long', [r['code'] for r in checks['instagram']['reasons']])
        self.assertEqual(checks['facebook']['captionCheck']['characters'], len(draft['caption']))
        legacy = self.save(draftId='8'*32).json['draft']
        self.assertEqual(legacy['channelCaptions'], {c: legacy['caption'] for c in legacy['channels']})

    def test_legacy_stored_caption_defaults_do_not_rewrite_snapshot(self):
        import json
        import sqlite3
        from contextlib import closing
        self.save()
        with closing(sqlite3.connect(self.flow.path)) as con:
            original = json.loads(con.execute('SELECT draft_json FROM growthrova_social_drafts').fetchone()[0])
            original.pop('channelCaptions')
            encoded = json.dumps(original)
            con.execute('UPDATE growthrova_social_drafts SET draft_json=?', (encoded,))
            con.commit()
        read = self.flow.client.get(self.url, headers=self.flow.headers).json['drafts'][0]
        self.assertEqual(read['channelCaptions'], {c: original['caption'] for c in original['channels']})
        with closing(sqlite3.connect(self.flow.path)) as con:
            self.assertEqual(con.execute('SELECT draft_json FROM growthrova_social_drafts').fetchone()[0], encoded)
        cancelled = self.flow.client.post(self.url+'/'+'9'*32+'/cancel', headers=self.flow.headers, json={}).json['draft']
        self.assertEqual(cancelled['channelCaptions'], read['channelCaptions'])
        self.assertEqual(cancelled['caption'], original['caption'])

    def test_gap_and_repeated_hour_require_explicit_valid_offset(self):
        for changes in [dict(localTime='2027-03-28T01:30', utcOffsetMinutes=0),
                        dict(localTime='2027-10-31T01:30', utcOffsetMinutes=None),
                        dict(utcOffsetMinutes=0), dict(timezone='Not/AZone')]:
            with self.subTest(changes=changes):
                self.assertEqual(self.save(**changes).status_code, 400)
        first = self.save(localTime='2027-10-31T01:30', utcOffsetMinutes=60)
        second = self.save(draftId='8'*32, localTime='2027-10-31T01:30', utcOffsetMinutes=0)
        self.assertEqual(first.status_code, 201, first.json)
        self.assertEqual(second.status_code, 201, second.json)
        self.assertNotEqual(first.json['draft']['schedule']['utcTime'], second.json['draft']['schedule']['utcTime'])

    def test_reject_substitution_conflict_unknown_fields_and_foreign_access(self):
        self.assertEqual(self.save(artworkSha256='0'*64).status_code, 409)
        self.assertEqual(self.save(approval=True).status_code, 400)
        self.assertEqual(self.save(channels=['youtube']).status_code, 400)
        self.assertEqual(self.save().status_code, 201)
        self.assertEqual(self.save(localTime='2027-03-28T10:30').status_code, 409)
        for url in (self.url, self.url+'/'+'9'*32+'/artwork'):
            denied = self.flow.client.get(url.replace(ORG, OTHER), headers=self.flow.headers)
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(self.flow.client.get(url).status_code, 401)
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_expired_and_revoked_scope_denied_for_history_artwork_and_cancel(self):
        self.assertEqual(self.save().status_code, 201)
        paths = (self.url, self.url+'/'+'9'*32+'/artwork')
        self.flow.auth.status = 401
        for path in paths:
            self.assertEqual(self.flow.client.get(path, headers=self.flow.headers).status_code, 403)
        self.flow.auth.status = 200
        self.flow.auth.allowed = False
        self.assertEqual(self.save().status_code, 403)
        self.assertEqual(self.flow.client.post(self.url+'/'+'9'*32+'/cancel',
            headers=self.flow.headers, json={}).status_code, 403)
        self.flow.auth.allowed = True
        self.flow.auth.owner = OTHER
        for path in paths:
            self.assertEqual(self.flow.client.get(path, headers=self.flow.headers).status_code, 403)
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_changed_saved_context_marks_old_draft_stale_preserving_bytes(self):
        self.assertEqual(self.save().status_code, 201)
        doc = copy.deepcopy(self.flow.client.get(self.flow.root+'/'+self.flow.ident,
            headers=self.flow.headers).json['document'])
        doc['posts'][0]['copyDraft'] = 'Book a bicycle service with our workshop today.'
        self.flow.save_document(doc, 2, '7')
        result = self.flow.client.get(self.url, headers=self.flow.headers).json['drafts'][0]
        self.assertFalse(result['current'])
        self.assertEqual(result['caption'], self.flow.doc['posts'][0]['copyDraft'])
        self.assertEqual(result['state'], 'draft')
        self.assertEqual(self.save(draftId='8'*32).status_code, 409)

    def test_all_five_planned_channels_survive_reopen_with_individual_delivery_holds(self):
        channels = ['instagram', 'facebook', 'linkedin', 'tiktok', 'x']
        result = self.save(channels=channels)
        self.assertEqual(result.status_code, 201, result.json)
        draft = result.json['draft']
        client = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider).test_client()
        reopened = client.get(self.url, headers=self.flow.headers).json['drafts'][0]
        self.assertEqual(reopened, draft)
        self.assertEqual(draft['channels'], channels)
        self.assertEqual([item['channel'] for item in draft['channelChecks']], channels)
        for item in draft['channelChecks']:
            self.assertEqual(item['state'], 'blocked')
            self.assertIsNone(item['destinationAccount'])
            self.assertEqual(item['format'], 'single_image')
            self.assertEqual(item['mediaType'], 'image/png')
            self.assertIn('account_not_connected', [reason['code'] for reason in item['reasons']])
        self.assertFalse(draft['canPublish'])
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_tiktok_png_hold_preserves_exact_artwork_and_caption_and_other_channels(self):
        result = self.save(channels=['tiktok', 'linkedin'])
        self.assertEqual(result.status_code, 201, result.json)
        draft = result.json['draft']
        reasons = {item['channel']: [r['code'] for r in item['reasons']] for item in draft['channelChecks']}
        self.assertIn('rendition_required', reasons['tiktok'])
        self.assertNotIn('rendition_required', reasons['linkedin'])
        self.assertEqual(draft['caption'], self.preview['manifest']['post']['copyDraft'])
        pixels = self.flow.client.get(self.url+'/'+draft['draftId']+'/artwork', headers=self.flow.headers)
        self.assertEqual(hashlib.sha256(pixels.data).hexdigest(), self.data['artworkSha256'])
        self.assertEqual(self.save(channels=['tiktok', 'tiktok']).status_code, 400)
        self.assertEqual(self.save(channels=['x', {}]).status_code, 400)
        self.assertEqual(len(self.flow.provider.calls), 1)


class CaptionCheckTests(unittest.TestCase):
    def test_exact_limits_unicode_and_unimplemented_weighted_rules(self):
        from business_social_drafts import channel_checks
        for channel, limit in [('instagram', 2200), ('linkedin', 3000), ('tiktok', 2200)]:
            with self.subTest(channel=channel):
                at_limit = channel_checks([channel], '😀' * limit)[0]
                self.assertEqual(at_limit['captionCheck']['characters'], limit)
                self.assertNotIn('caption_too_long', [r['code'] for r in at_limit['reasons']])
                above = channel_checks([channel], '😀' * limit + 'a')[0]
                self.assertIn('caption_too_long', [r['code'] for r in above['reasons']])
                self.assertEqual(above['state'], 'blocked')
        for channel in ('facebook', 'x'):
            check = channel_checks([channel], 'https://example.test/' + 'a' * 2900)[0]
            self.assertIsNone(check['captionCheck']['preliminaryLimit'])
            self.assertIn('validation_pending', [r['code'] for r in check['reasons']])
        legacy = channel_checks(['instagram'])[0]
        self.assertIsNone(legacy['captionCheck']['characters'])


class MediaCheckTests(unittest.TestCase):
    def test_instagram_original_width_and_size_holds_are_separate_from_other_channels(self):
        from business_social_drafts import channel_checks
        artwork = dict(width=1792, height=2400, previewBytes=8_000_001)
        original = copy.deepcopy(artwork)
        checks = {c['channel']: c for c in channel_checks(
            ['instagram', 'facebook', 'linkedin', 'tiktok', 'x'], 'Saved words', artwork=artwork)}
        self.assertEqual(artwork, original)
        ig = checks['instagram']
        self.assertEqual(ig['mediaCheck']['state'], 'needs_rendition')
        self.assertIn('image_width_unsupported', [r['code'] for r in ig['reasons']])
        self.assertIn('image_too_large', [r['code'] for r in ig['reasons']])
        self.assertIn('1792', ' '.join(r['message'] for r in ig['reasons']))
        for channel in ('facebook', 'linkedin', 'tiktok', 'x'):
            self.assertNotIn('image_width_unsupported', [r['code'] for r in checks[channel]['reasons']])
            self.assertNotIn('image_too_large', [r['code'] for r in checks[channel]['reasons']])
            self.assertEqual(checks[channel]['state'], 'blocked')

    def test_instagram_boundaries_and_unknown_legacy_dimensions_never_grant_eligibility(self):
        from business_social_drafts import channel_checks
        for width in (320, 1080, 1440):
            check = channel_checks(['instagram'], artwork=dict(width=width, height=1350, previewBytes=8_000_000))[0]
            self.assertEqual(check['mediaCheck']['state'], 'validation_pending')
            self.assertEqual(check['state'], 'blocked', 'Known media bounds are not permission or complete validation')
        for width in (319, 1441):
            check = channel_checks(['instagram'], artwork=dict(width=width, height=1350, previewBytes=200))[0]
            self.assertIn('image_width_unsupported', [r['code'] for r in check['reasons']])
        for artwork in (None, {}, dict(width=True, height=-1, previewBytes='200')):
            check = channel_checks(['instagram'], artwork=artwork)[0]
            self.assertEqual(check['mediaCheck'], dict(width=None, height=None, bytes=None, state='validation_pending'))
            self.assertEqual(check['state'], 'blocked')


if __name__ == '__main__':
    unittest.main()
