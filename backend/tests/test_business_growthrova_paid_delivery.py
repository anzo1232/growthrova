"""Narrow paused-job regressions with real private routes/SQLite, no network."""
import tempfile
import unittest
import uuid
from pathlib import Path
from business_marketing_offline import create_offline_document_app, OfflineMarketingDocuments
from business_growthrova_paid_delivery import PaidDeliveryConfig, register_paid_delivery_routes
from tests.test_business_marketing_drafts import document


class Adapter:
    mode = 'live'

    def __init__(self):
        self.calls = 0
        self.version = '1'
        self.unknown = False
        self.foreign = False

    def account(self, owner, organisation):
        return dict(platform='google', ownerId='foreign' if self.foreign else owner,
                    organisationId=organisation, accountId='dedicated-account', label='Business Ads',
                    connectionVersion=self.version, currency='GBP')

    def check(self, snapshot):
        snapshot['plan']['dailyBudget'] = '999'  # Checks cannot mutate frozen intent.
        return True

    def create_paused(self, snapshot, **kwargs):
        self.calls += 1
        assert snapshot['plan']['dailyBudget'] == '10'
        return None if self.unknown else dict(id='operation-1', outcome='paused', resources={'campaignId':'campaign-1'})

    def lookup(self, snapshot, **kwargs):
        return dict(id='operation-1', outcome='paused', resources={'campaignId':'campaign-1'})


class PaidDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = str(Path(temp.name)/'private.db')
        self.user = 'owner'
        self.auth = lambda: ({'id':self.user}, None)
        self.org = lambda ident, user: ({'id':ident}, None)
        self.app = create_offline_document_app(self.path, current_user=self.auth, load_org=self.org)
        self.client = self.app.test_client()
        self.repo = OfflineMarketingDocuments(self.path, self.auth, self.org)
        self.adapter = Adapter()
        self.delivery = register_paid_delivery_routes(self.app, self.repo,
            '/offline/organisations/<organisation_id>/marketing-documents',
            config=PaidDeliveryConfig(adapters={'google':self.adapter}, authorised=lambda *args:True, mode='live'))
        doc = document()
        doc['googleCampaign'] = dict(objective='leads', audience='People seeking a meal',
            location='London', language='English', destinationUrl='https://example.org/contact',
            currency='GBP', dailyBudget='10', durationDays=7, keywordMatch='phrase',
            headlines=['Book a table','See our menu','Plan a visit'],
            descriptions=['View our menu online.','Ask about a table.'],keywords=['restaurant'],negativeKeywords=[])
        self.ident = '1'*32
        self.repo.save('org', dict(id=self.ident, mutationId='2'*32, expectedRevision=0, document=doc))
        self.url = '/offline/organisations/org/marketing-documents/'+self.ident+'/paid-provisioning/google'
        review = self.client.get(self.url).json
        self.approval = dict(mutationId=uuid.uuid4().hex, expectedRevision=1, expectedMode=review['mode'], expectedAccount=review['review']['account'])

    def action(self, action, data=None):
        payload = self.approval if action=='approve' and data is None else data or dict(
            mutationId=uuid.uuid4().hex, jobIds=[job['jobId'] for job in self.client.get(self.url).json['jobs']])
        return self.client.post(self.url+'/'+action, json=payload)

    def test_created_paused_is_terminal_on_reapproval_and_restart(self):
        self.assertEqual(self.action('approve').status_code, 200)
        self.assertTrue(self.delivery.run_one())
        self.assertEqual(self.action('approve').json['jobs'][0]['state'], 'created_paused')
        self.assertFalse(self.delivery.run_one())
        self.assertEqual(self.adapter.calls, 1)
        reopened = OfflineMarketingDocuments(self.path, self.auth, self.org)
        self.assertEqual(reopened.read('org', self.ident)['revision'], 1)
        self.user = 'other'
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_uncertain_outcome_looks_up_without_another_create(self):
        self.adapter.unknown = True
        self.action('approve'); self.delivery.run_one()
        self.assertEqual(self.action('approve', {**self.approval, 'mutationId':uuid.uuid4().hex}).status_code, 409)
        self.assertFalse(self.delivery.run_one())
        self.assertEqual(self.action('reconcile').json['jobs'][0]['state'], 'created_paused')
        self.assertEqual(self.adapter.calls, 1)

    def test_account_drift_and_pause_cannot_dispatch(self):
        self.adapter.version = '2'
        self.assertEqual(self.action('approve').status_code, 409)
        self.adapter.version = '1'
        self.action('approve'); self.action('pause')
        self.assertFalse(self.delivery.run_one())
        # A replay of the old approval cannot undo a later pause.
        self.action('approve')
        self.assertFalse(self.delivery.run_one())
        self.approval['mutationId'] = uuid.uuid4().hex
        self.action('approve'); self.adapter.foreign = True
        self.delivery.run_one()
        self.assertEqual(self.client.get(self.url).json['jobs'][0]['state'], 'blocked')
        self.assertEqual(self.adapter.calls, 0)

    def test_partial_resources_survive_incomplete_lookup(self):
        self.adapter.create_paused = lambda *args, **kwargs: dict(
            id='operation-1', outcome='partial', resources={'campaignId':'partial-1'})
        self.action('approve'); self.delivery.run_one()
        self.adapter.lookup = lambda *args, **kwargs: dict(id='operation-1', outcome='failed')
        response = self.action('reconcile')
        job = response.json['jobs'][0]
        self.assertEqual(job['state'], 'uncertain')
        self.assertEqual(job['receipt']['resources'], {'campaignId':'partial-1'})
        self.assertEqual(self.action('approve', {**self.approval, 'mutationId':uuid.uuid4().hex}).status_code, 409)
