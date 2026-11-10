"""Offline auth boundary plus real document/revision persistence; no sockets."""
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from business_marketing_offline import OfflineMarketingDocuments, OfflineDocumentAccessError
from business_marketing_drafts import MarketingDraftError, initialise
from tests.test_business_marketing_drafts import document


class OfflineContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'offline.db')
        self.user = {'id': 'verified-user'}
        self.allowed = {'org-a', 'org-b'}
        self.auth = lambda: (self.user, None) if self.user else (None, 'unauthenticated')
        self.org = lambda ident, user: ({'id': ident}, None) if ident in self.allowed else (None, 'denied')
        self.repo = OfflineMarketingDocuments(self.path, self.auth, self.org)
        self.payload = {'id': '1'*32, 'mutationId': '2'*32, 'expectedRevision': 0, 'document': document()}

    def test_save_reload_edit_retry_and_stale_rejection(self):
        doc = self.payload['document']
        strategy = {k: 'Owner supplied '+k for k in ('audience','offer','positioning','callToAction','constraints')}
        strategy['factDecisions'] = [{'index':0,'observation':doc['observedFacts'][0],'decision':'confirmed','statement':''}]
        strategy['confirmedContext'] = {**{k:doc[k] for k in ('business','goal','sourceUrl','observedFacts')}, **strategy}
        doc['ownerStrategy'] = strategy
        doc['calendarStartDate'] = '2026-11-01'
        first = self.repo.save('org-a', self.payload)
        self.assertEqual(first['revision'], 1)
        self.assertTrue(self.repo.save('org-a', self.payload)['replayed'])
        reopened = OfflineMarketingDocuments(self.path, self.auth, self.org)
        saved = reopened.read('org-a', self.payload['id'])
        self.assertEqual(len(saved['document']['posts']), 30)
        self.assertEqual(saved['document']['ownerStrategy'], strategy)
        edited = copy.deepcopy(saved['document'])
        edited['posts'][7]['copyDraft'] = 'Owner edited day eight'
        result = reopened.save('org-a', {**self.payload, 'expectedRevision':1, 'mutationId':'3'*32, 'document':edited})
        self.assertEqual(result['revision'], 2)
        for mutation in ('2'*32, '4'*32):
            with self.assertRaises(MarketingDraftError):
                reopened.save('org-a', {**self.payload, 'mutationId':mutation})
        restored = reopened.list('org-a')[0]['document']
        self.assertEqual(restored['posts'][7]['copyDraft'], 'Owner edited day eight')
        self.assertFalse(restored['canSpend']); self.assertFalse(restored['canPublish'])

    def test_cross_tenant_and_cross_owner_denied_even_on_replay(self):
        self.repo.save('org-a', self.payload)
        for org, user in [('org-b', {'id':'verified-user'}), ('org-a', {'id':'other-user'})]:
            self.user = user
            with self.assertRaises(OfflineDocumentAccessError): self.repo.read(org, self.payload['id'])
            with self.assertRaises(OfflineDocumentAccessError): self.repo.save(org, self.payload)
            self.assertEqual(self.repo.list(org), [])
        self.user = {'id':'verified-user'}
        self.assertEqual(self.repo.read('org-a', self.payload['id'])['revision'],1)

    def test_auth_revocation_and_submitted_identity_are_not_proof(self):
        self.payload.update(owner_id='verified-user', organisation_id='org-a', verified_owner_reference='claimed-owner')
        self.user = None
        for action in (lambda:self.repo.save('org-a',self.payload),lambda:self.repo.read('org-a','1'*32),lambda:self.repo.list('org-a')):
            with self.assertRaises(OfflineDocumentAccessError): action()
        self.user = {'id':'verified-user'}
        self.repo.save('org-a',self.payload)
        self.allowed.clear()
        with self.assertRaises(OfflineDocumentAccessError): self.repo.read('org-a','1'*32)
        with self.assertRaises(OfflineDocumentAccessError): self.repo.save('org-a',self.payload)

    def test_failed_create_does_not_leave_owner_binding(self):
        with self.assertRaises(MarketingDraftError):
            self.repo.save('org-a',{**self.payload,'expectedRevision':5})
        self.repo.save('org-b',self.payload)
        self.assertEqual(len(self.repo.list('org-b')),1)

    def test_refuses_existing_pilot_database(self):
        path = str(Path(self.temp.name)/'pilot.db')
        with sqlite3.connect(path) as con: initialise(con)
        with self.assertRaises(OfflineDocumentAccessError): OfflineMarketingDocuments(path,self.auth,self.org)
