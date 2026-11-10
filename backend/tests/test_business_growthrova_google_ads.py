"""Offline Google wire/approval checks; not platform or connected acceptance."""
from copy import deepcopy
from dataclasses import replace
import unittest

from business_growthrova_google_ads import GoogleAdsBinding, GoogleSearchPausedAdapter
from business_social_delivery import _hash
from tests import test_business_growthrova_paid_delivery as fixture


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return deepcopy(self.payload)


class GoogleTransportTests(unittest.TestCase):
    action = fixture.PaidDeliveryTests.action

    def setUp(self):
        fixture.PaidDeliveryTests.setUp(self)
        plan = self.repo.read('org', self.ident)['document']['googleCampaign']
        self.binding = GoogleAdsBinding('owner', 'org', '1234567890', 'Dedicated Ads', '1',
            'GBP', _hash(plan), 'London', 'English', location_ids=('1006886',),
            language_id='1000', cpc_bid_micros=500000, non_political_confirmed=True,
            verified=True, enabled=True, access_token='synthetic-token')
        self.calls = []
        self.lose_ack = False
        self.adapter = GoogleSearchPausedAdapter(lambda *args: self.binding, lambda snap: True, http=self)
        self.delivery.config.adapters['google'] = self.adapter
        status = self.client.get(self.url).json
        self.approval.update(expectedAccount=status['review']['account'], expectedExecution=status['review']['execution'])

    def request(self, method, url, **options):
        self.calls.append((url, options['json']))
        self.assertFalse(options['allow_redirects'])
        if url.endswith(':searchStream'):
            return Response([{'results':[{'customer':dict(id='1234567890', currencyCode='GBP', status='ENABLED', manager=False)}]}])
        self.assertTrue(url.endswith(':mutate'))
        body = options['json']
        self.assertFalse(body['partialFailure'])
        self.assertFalse(body['validateOnly'])
        self.assertNotIn('Idempotency-Key', options['headers'])
        root = 'customers/1234567890/'
        collections = dict(campaignBudget='campaignBudgets/11', campaign='campaigns/22',
            adGroup='adGroups/33', adGroupAd='adGroupAds/33~44',
            campaignCriterion='campaignCriteria/22~55', adGroupCriterion='adGroupCriteria/33~66')
        results = []
        for operation in body['mutateOperations']:
            kind = next(iter(operation)).removesuffix('Operation')
            value = operation[kind+'Operation']['create']
            if kind in ('campaign','adGroup','adGroupAd'):
                self.assertEqual(value['status'], 'PAUSED')
            results.append({kind+'Result':{'resourceName':root+collections[kind]}})
        if self.lose_ack:
            raise TimeoutError('Response identity unavailable')
        return Response({'mutateOperationResponses': results})

    def test_exact_settings_approval_atomic_request_and_terminal_replay(self):
        stale = deepcopy(self.approval)
        self.binding = replace(self.binding, cpc_bid_micros=700000)
        self.assertEqual(self.action('approve', stale).status_code, 409)
        self.assertEqual(self.calls, [])
        self.binding = replace(self.binding, cpc_bid_micros=500000)
        self.assertEqual(self.action('approve').status_code, 200)
        self.assertTrue(self.delivery.run_one())
        job = self.client.get(self.url).json['jobs'][0]
        self.assertEqual(job['state'], 'created_paused')
        self.assertEqual(job['snapshot']['execution']['cpcBidMicros'], '500000')
        self.action('approve')
        self.assertFalse(self.delivery.run_one())
        self.assertEqual(sum(url.endswith(':mutate') for url, body in self.calls), 1)
        self.binding = replace(self.binding, owner_id='foreign')
        self.assertIsNone(self.adapter.account('owner','org'))

    def test_lost_ack_is_held_without_remote_retry_and_disabled_setup_blocks(self):
        self.lose_ack = True
        self.action('approve'); self.delivery.run_one()
        self.assertEqual(self.action('reconcile').json['jobs'][0]['state'], 'uncertain')
        self.assertFalse(self.delivery.run_one())
        self.assertEqual(sum(url.endswith(':mutate') for url, body in self.calls), 1)
        self.binding = replace(self.binding, enabled=False)
        snap = self.client.get(self.url).json['review']
        self.assertFalse(self.adapter.check(snap))
        self.assertTrue(self.adapter.blockers(snap))


if __name__ == '__main__':
    unittest.main()
