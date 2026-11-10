"""Real Flask requests + dedicated SQLite + existing JS strategy, without sockets."""
import copy
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from business_marketing_offline import create_offline_document_app
from tests.test_business_marketing_drafts import document


class OfflineDocumentHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'documents.db')
        self.user = {'id': 'owner-a'}
        self.memberships = {'org-a', 'org-b'}
        self.app = self.make_app()
        self.client = self.app.test_client()
        self.url = '/offline/organisations/org-a/marketing-documents'
        self.payload = {'id': 'a'*32, 'mutationId': 'b'*32,
                        'expectedRevision': 0, 'document': document()}

    def make_app(self):
        return create_offline_document_app(
            self.path,
            current_user=lambda: (self.user, None) if self.user else (None, 'denied'),
            load_org=lambda ident, user: ({'id': ident}, None)
            if ident in self.memberships else (None, 'denied'))

    def test_confirmed_strategy_calendar_save_reopen_edit_conflict_and_retry(self):
        script = """
import {reviewBusinessFact,editOwnerStrategy,confirmOwnerStrategy,completeStrategyCalendar} from './src/lib/businessOwnerStrategy.mjs';
let d=JSON.parse(process.argv[1]);d.posts=d.posts.slice(0,1);
for(const key of ['audience','offer','positioning','callToAction','constraints'])
 d=editOwnerStrategy(d,key,'Owner supplied '+key);
d.calendarStartDate='2026-11-01';
for(let i=0;i<(d.observedFacts||[]).length;i++)d=reviewBusinessFact(d,i,'confirmed');
console.log(JSON.stringify(completeStrategyCalendar(confirmOwnerStrategy(d))));
"""
        self.payload['document'] = json.loads(subprocess.check_output(
            ['node', '--input-type=module', '-e', script, json.dumps(document())], text=True))
        first = self.client.post(self.url, json=self.payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json['revision'], 1)
        self.assertTrue(self.client.post(self.url, json=self.payload).json['replayed'])
        client = self.make_app().test_client()
        saved = client.get(self.url+'/'+self.payload['id'])
        self.assertEqual(saved.status_code, 200)
        self.assertFalse(saved.json['hostedStorageVerified'])
        doc = saved.json['document']
        self.assertEqual(len(doc['posts']), 30)
        self.assertIsNotNone(doc['ownerStrategy']['confirmedContext'])
        doc['posts'][8]['copyDraft'] = 'Owner changed day nine'
        update = {**self.payload, 'document': doc, 'mutationId': 'c'*32, 'expectedRevision': 1}
        self.assertEqual(client.post(self.url, json=update).json['revision'], 2)
        self.assertTrue(client.post(self.url, json=update).json['replayed'])
        stale = client.post(self.url, json={**update, 'mutationId': 'd'*32})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json['code'], 'revision_conflict')
        superseded = client.post(self.url, json=self.payload)
        self.assertEqual(superseded.status_code, 409)
        self.assertEqual(superseded.json['code'], 'replay_superseded')
        restored = client.get(self.url).json['documents'][0]['document']
        self.assertEqual(restored['posts'][8]['copyDraft'], 'Owner changed day nine')
        self.assertIsNotNone(restored['ownerStrategy']['confirmedContext'])
        self.assertFalse(restored['canSpend']); self.assertFalse(restored['canPublish'])
        changed = copy.deepcopy(restored)
        changed['observedFacts'] = ['Changed source statement']
        response = client.post(self.url, json={**update, 'document': changed,
                               'mutationId': 'e'*32, 'expectedRevision': 2})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json['document']['ownerStrategy']['confirmedContext'])

    def test_foreign_owner_org_and_retry_are_denied_without_disclosure(self):
        self.assertEqual(self.client.post(self.url, json=self.payload).status_code, 200)
        for user, url in [({'id': 'owner-b'}, self.url),
                          (self.user, self.url.replace('org-a', 'org-b'))]:
            self.user = user
            denied = self.client.get(url+'/'+self.payload['id'])
            absent = self.client.get(url+'/'+'f'*32)
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(denied.json, absent.json)
            self.assertEqual(self.client.post(url, json=self.payload).status_code, 403)
            self.assertEqual(self.client.get(url).json['documents'], [])

    def test_pilot_header_and_submitted_ownership_never_authenticate(self):
        self.user = None
        payload = {**self.payload, 'owner_id': 'owner-a', 'organisation_id': 'org-a',
                   'verified_owner_reference': 'owner-a'}
        headers = {'X-Clippr-Pilot': 'local-only', 'Authorization': 'Bearer invented'}
        for response in [self.client.post(self.url, json=payload, headers=headers),
                         self.client.get(self.url, headers=headers),
                         self.client.get(self.url+'/'+'a'*32, headers=headers),
                         self.client.post(self.url, data='bad', headers=headers)]:
            self.assertEqual(response.status_code, 403)
        self.user = {'id': 'owner-a'}
        self.memberships.clear()
        self.assertEqual(self.client.post(self.url, json=payload).status_code, 403)
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM marketing_drafts').fetchone()[0], 0)

    def test_bad_input_bounds_private_errors_and_no_production_routes(self):
        for kwargs in ({'json': []}, {'data': '{', 'content_type': 'application/json'}):
            response = self.client.post(self.url, **kwargs)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(self.url, data='x'*300001,
                         content_type='application/json').status_code, 413)
        with patch('business_marketing_offline.OfflineMarketingDocuments.read',
                   side_effect=sqlite3.OperationalError('private database path')):
            response = self.client.get(self.url+'/'+'a'*32)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private database path', response.get_data(as_text=True))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        for route in ('/api/business/drafts', '/api/pilot/marketing-drafts'):
            self.assertEqual(self.client.get(route).status_code, 404)
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)
