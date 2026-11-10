"""Real route/store/worker tests; explicitly controlled adapter, no publication."""
import concurrent.futures
import hashlib
import unittest

from tests import test_business_social_drafts as draft_tests
from tests.test_business_growthrova_preview import ORG, OTHER, USER


class Adapter:
    def __init__(self):
        self.connected = True
        self.calls = []
        self.on_check = None
        self.failure = False
        self.receipt = None
        self.outcome = 'simulated'

    def check(self, snapshot):
        if self.on_check:
            self.on_check()
        return self.connected

    def deliver(self, snapshot, artwork, *, idempotency_key):
        self.calls.append((snapshot, artwork, idempotency_key))
        if self.failure:
            raise TimeoutError('Uncertain synthetic acknowledgement')
        return {'id': 'synthetic-' + idempotency_key, 'outcome': self.outcome}

    def reconcile(self, snapshot, *, idempotency_key):
        return self.receipt


class SocialDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.drafts = draft_tests.SocialDraftTests()
        self.drafts.setUp()
        self.addCleanup(self.drafts.doCleanups)
        self.flow = self.drafts.flow
        from business_social_accounts import SocialAccountConfig
        from tests.test_business_social_accounts import Provider
        accounts = Provider(dict(activeSocialAccounts=['instagram', 'facebook'], displayNames=[
            dict(platform='instagram', id='ig-test', displayName='Synthetic Workshop', type='business'),
            dict(platform='facebook', id='fb-test', displayName='Synthetic Workshop')]))
        self.flow.client = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider,
            social_account_config=SocialAccountConfig(enabled=True, api_key='synthetic-only',
                profile_key_for_org=lambda org: 'synthetic-profile'), social_account_http=accounts).test_client()
        self.draft = self.drafts.save(destinationAccounts={'instagram': 'ig-test', 'facebook': 'fb-test'}).json['draft']
        self.adapter = Adapter()
        self.allowed = True
        self.now = 1800000000.0  # Before the saved March 2027 time.
        self.configure()
        self.endpoint = self.drafts.url + '/' + self.draft['draftId'] + '/delivery'
        self.payload = {'expectedRevision': self.draft['revision'],
                        'artworkSha256': self.draft['artworkSha256']}

    def configure(self):
        from business_social_delivery import SocialDeliveryConfig
        self.config = SocialDeliveryConfig(adapter=self.adapter,
            authorised=lambda owner, org: self.allowed and owner == USER,
            clock=lambda: self.now, mode='simulation')
        self.app = self.flow.create(image_config=self.flow.config, image_http=self.flow.provider,
                                   social_delivery_config=self.config)
        self.client = self.app.test_client()
        self.worker = self.app.extensions['growthrova_social_delivery']

    def approve(self, **changes):
        return self.client.post(self.endpoint + '/approve', headers=self.flow.headers,
                                json={**self.payload, **changes})

    def jobs(self):
        response = self.client.get(self.endpoint, headers=self.flow.headers)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json['jobs']

    def due(self):
        self.now = 1816853401.0  # After March 2027.

    def test_approval_replay_reopen_freezes_exact_channels_caption_pixels_and_time(self):
        response = self.approve()
        self.assertEqual(response.status_code, 201, response.json)
        first = response.json['jobs']
        self.assertEqual(len(first), 2)
        self.assertEqual({j['channel'] for j in first}, {'instagram', 'facebook'})
        self.assertTrue(all(j['mode'] == 'simulation' and j['state'] == 'scheduled' for j in first))
        self.assertEqual(self.approve().status_code, 200)
        self.configure()  # New app and connections, same database.
        self.assertEqual(self.jobs(), first)
        self.due()
        self.assertTrue(self.worker.run_one())
        self.assertTrue(self.worker.run_one())
        self.assertFalse(self.worker.run_one())
        for snapshot, pixels, key in self.adapter.calls:
            self.assertEqual((snapshot['ownerId'], snapshot['organisationId']), (USER, ORG))
            self.assertEqual(snapshot['caption'], self.draft['channelCaptions'][snapshot['channel']])
            self.assertEqual(hashlib.sha256(pixels).hexdigest(), self.draft['artworkSha256'])
            self.assertEqual(snapshot['schedule'], self.draft['schedule'])
            self.assertIn(key, [j['jobId'] for j in first])
        self.assertTrue(all(j['state'] == 'simulated' and j['receipt']['id'] for j in self.jobs()))
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_accepted_queue_identity_does_not_mean_publication(self):
        from dataclasses import replace
        self.config = replace(self.config, mode='live')  # Synthetic adapter only, no real service.
        self.app = self.flow.create(social_delivery_config=self.config)
        self.client = self.app.test_client()
        self.worker = self.app.extensions['growthrova_social_delivery']
        self.adapter.outcome = 'accepted'
        self.approve()
        self.due()
        self.worker.run_one()
        job = next(j for j in self.jobs() if j['state'] == 'uncertain')
        self.assertEqual(job['receipt']['outcome'], 'accepted')
        self.assertNotIn('published', [j['state'] for j in self.jobs()])
        self.adapter.receipt = {'id': 'actual-synthetic-post-id', 'outcome': 'published'}
        self.worker.reconcile(job['jobId'])
        self.assertEqual(next(j for j in self.jobs() if j['jobId'] == job['jobId'])['state'], 'published')
        self.assertEqual(len(self.adapter.calls), 1)

    def test_default_disconnected_and_mismatched_artwork_cannot_approve(self):
        client = self.flow.create().test_client()
        denied = client.post(self.endpoint+'/approve', headers=self.flow.headers, json=self.payload)
        self.assertEqual(denied.status_code, 503)
        self.assertEqual(self.jobs(), [])
        self.assertEqual(self.approve(artworkSha256='0'*64).status_code, 409)
        self.assertEqual(self.jobs(), [])

    def test_auth_change_during_adapter_check_and_other_tenant_cannot_approve_or_read(self):
        self.adapter.on_check = lambda: setattr(self.flow.auth, 'owner', OTHER)
        self.assertEqual(self.approve().status_code, 403)
        self.assertEqual(self.client.get(self.endpoint, headers=self.flow.headers).status_code, 403)
        self.flow.auth.owner = USER
        self.assertEqual(self.jobs(), [])

    def test_campaign_edit_invalidates_pending_delivery_and_approval(self):
        self.assertEqual(self.approve().status_code, 201)
        doc = self.flow.doc.copy()
        doc['business'] = 'Changed business context requiring review'
        self.flow.save_document(doc, 2, 'a')
        self.due()
        self.worker.run_one()
        self.worker.run_one()
        self.assertEqual(self.adapter.calls, [])
        self.assertTrue(all(j['state'] == 'blocked' for j in self.jobs()))
        self.assertEqual(self.approve().status_code, 409)

    def test_cancel_and_pause_prevent_dispatch_without_erasing_frozen_art(self):
        self.approve()
        paused = self.client.post(self.endpoint+'/pause', headers=self.flow.headers, json={})
        self.assertEqual(paused.status_code, 200)
        self.due()
        self.assertFalse(self.worker.run_one())
        self.assertTrue(all(j['state'] == 'paused' for j in self.jobs()))
        cancelled = self.client.post(self.drafts.url+'/'+self.draft['draftId']+'/cancel',
                                     headers=self.flow.headers, json={})
        self.assertEqual(cancelled.status_code, 200)
        self.assertTrue(all(j['state'] == 'cancelled' for j in self.jobs()))
        self.assertFalse(self.worker.run_one())
        self.assertEqual(self.approve().status_code, 409)
        pixels = self.client.get(self.drafts.url+'/'+self.draft['draftId']+'/artwork', headers=self.flow.headers)
        self.assertEqual(hashlib.sha256(pixels.data).hexdigest(), self.draft['artworkSha256'])

    def test_concurrent_workers_claim_each_channel_once(self):
        self.approve()
        self.due()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.worker.run_one(), range(4)))
        self.assertEqual(sum(results), 2)
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertEqual(len(set(call[2] for call in self.adapter.calls)), 2)

    def test_disconnect_or_revoked_permission_blocks_before_dispatch(self):
        self.approve()
        self.adapter.connected = False
        self.due()
        self.worker.run_one()
        self.allowed = False
        self.worker.run_one()
        self.assertEqual(self.adapter.calls, [])
        self.assertTrue(all(j['state'] == 'blocked' for j in self.jobs()))

    def test_revocation_while_worker_checks_channel_prevents_send(self):
        self.approve()
        self.adapter.on_check = lambda: setattr(self, 'allowed', False)
        self.due()
        self.worker.run_one()
        self.assertEqual(self.adapter.calls, [])
        self.assertIn('blocked', [j['state'] for j in self.jobs()])

    def test_uncertain_dispatch_never_retries_and_read_only_reconciliation_retains_identity(self):
        self.approve()
        self.adapter.failure = True
        self.due()
        self.worker.run_one()
        first = next(j for j in self.jobs() if j['state'] == 'uncertain')
        self.configure()
        self.worker.run_one()  # Other channel only.
        self.assertFalse(self.worker.run_one())
        self.assertEqual(len(self.adapter.calls), 2)
        response = self.client.post(self.endpoint+'/reconcile', headers=self.flow.headers, json={})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(len(self.adapter.calls), 2)
        self.adapter.receipt = {'id': 'confirmed-synthetic-receipt', 'outcome': 'simulated'}
        response = self.client.post(self.endpoint+'/reconcile', headers=self.flow.headers, json={})
        self.assertEqual(response.status_code, 200, response.json)
        recovered = next(j for j in self.jobs() if j['jobId'] == first['jobId'])
        self.assertEqual(recovered['state'], 'simulated')
        self.assertEqual(recovered['receipt']['id'], self.adapter.receipt['id'])
        self.assertEqual(len(self.adapter.calls), 2)

    def test_crash_before_dispatch_can_reclaim_but_after_dispatch_is_held(self):
        self.approve()
        self.due()
        claim = self.worker.claim_due()
        self.now += 121
        self.configure()
        self.worker.run_one()
        self.assertEqual(len(self.adapter.calls), 1)
        claim = self.worker.claim_due()
        self.assertTrue(self.worker.begin_dispatch(claim))
        self.now += 121
        self.configure()
        self.assertFalse(self.worker.run_one())
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertIn('uncertain', [j['state'] for j in self.jobs()])

    def test_cancel_during_claim_prevents_send_and_dispatch_cannot_be_falsely_cancelled(self):
        self.approve()
        self.due()
        claim = self.worker.claim_due()
        self.client.post(self.endpoint+'/pause', headers=self.flow.headers, json={})
        self.assertFalse(self.worker.begin_dispatch(claim))
        self.assertEqual(self.adapter.calls, [])
        # Resumption is a fresh explicit approval with the same immutable identity.
        self.now = 1800000000.0
        self.assertEqual(self.approve().status_code, 200)
        self.due()
        claim = self.worker.claim_due()
        self.assertTrue(self.worker.begin_dispatch(claim))
        denied = self.client.post(self.drafts.url+'/'+self.draft['draftId']+'/cancel',
                                  headers=self.flow.headers, json={})
        self.assertEqual(denied.status_code, 200)
        self.assertEqual(denied.json['draft']['state'], 'cancellation_requested')
        self.assertEqual(sorted(j['state'] for j in self.jobs()), ['cancelled', 'dispatching'])
        self.assertFalse(self.worker.run_one(), 'Stop all channels that have not dispatched yet')
        self.assertEqual(self.approve().status_code, 409)


if __name__ == '__main__':
    unittest.main()
