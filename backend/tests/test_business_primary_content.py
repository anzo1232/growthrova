"""Primary service copy must survive bounded extraction into owner review.

Synthetic HTML reproduces the observed Pimlico twelve shared paragraphs; these
are not fresh public URL results or invented business facts.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from business_website_analysis import extract_website
from business_marketing_offline import OfflineMarketingDocuments
from business_growthrova_writer import provider_source_material, source_material


class PrimaryContentTests(unittest.TestCase):
    def extract(self, body):
        return extract_website('https://example.org/repairs/',
            resolve=lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))],
            fetch=lambda *a: body.encode())

    def test_late_service_detail_reaches_review_without_automatic_confirmation(self):
        shared = ''.join(f'<p>Shared property maintenance introduction number {i}.</p>' for i in range(12))
        detail = 'Drain inspections use a camera survey to identify the location of a blockage.'
        audit = self.extract('<title>Internal QA Repairs</title>' + shared +
            '<main><p>' + detail + '</p></main>')
        script = """
import fs from 'node:fs';
import {prepareUrlCampaign} from './src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument} from './src/lib/businessMarketingDocument.mjs';
import {reviewBusinessFact,confirmOwnerStrategy} from './src/lib/businessOwnerStrategy.mjs';
const pending=createMarketingDocument(prepareUrlCampaign(JSON.parse(fs.readFileSync(0,'utf8'))));
// Explicit synthetic test decisions, never real owner confirmations.
let reviewed=pending;
for(let i=0;i<pending.observedFacts.length;i++)reviewed=reviewBusinessFact(reviewed,i,
 pending.observedFacts[i].startsWith('Drain inspections')?'confirmed':'excluded');
reviewed=confirmOwnerStrategy(reviewed);
process.stdout.write(JSON.stringify({pending,reviewed}));
"""
        result = subprocess.run(['node', '--input-type=module', '-e', script],
            cwd=Path(__file__).resolve().parents[1], input=json.dumps(audit),
            capture_output=True, text=True, check=True, timeout=20)
        documents = json.loads(result.stdout)
        document = documents['pending']
        self.assertIn(detail, document['observedFacts'])
        index = document['observedFacts'].index(detail)
        self.assertEqual(document['observedFactSources'][index], 'https://example.org/repairs/')
        self.assertIsNone(document['ownerStrategy']['confirmedContext'])
        self.assertEqual(document['ownerStrategy']['factDecisions'], [])
        self.assertFalse(document['canPublish'])
        self.assertFalse(document['canSpend'])
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / 'drafts.sqlite3')
            def repository():
                return OfflineMarketingDocuments(db,
                    lambda: ({'id': 'synthetic-owner'}, None),
                    lambda ident, user: ({'id': ident}, None))
            repository().save('synthetic-org', {'id': 'a' * 32,
                'mutationId': 'b' * 32, 'expectedRevision': 0,
                'document': documents['reviewed']})
            reopened = repository().read('synthetic-org', 'a' * 32)['document']
        material = provider_source_material(source_material(reopened))
        facts = [item for item in material['evidence'] if item['id'].startswith('fact-')]
        self.assertEqual(facts, [{'id': 'fact-' + str(index), 'quote': detail,
            'sourceUrl': 'https://example.org/repairs/', 'status': 'owner_reviewed_observation'}])

    def test_primary_content_precedes_navigation_and_footer_with_same_bounds(self):
        detail = 'Our kitchen serves handmade dumplings with seasonal vegetable fillings.'
        navigation = 'Read our restaurant news and browse the other venues in our group.'
        footer = 'Sign up to receive the latest group news and venue announcements.'
        for landmark in ('main', 'article'):
            with self.subTest(landmark=landmark):
                page = self.extract('<title>Internal QA Kitchen</title><' + landmark +
                    '><nav><p>' + navigation + '</p></nav><section><p>' + detail +
                    '</p></section><footer><p>' + footer + '</p></footer></' + landmark + '>' +
                    ''.join(f'<p>Other general site information number {i}.</p>' for i in range(20)))
                paragraphs = page['observations']['visible_paragraphs']
                self.assertEqual(paragraphs[0], detail)
                self.assertEqual(len(paragraphs), 12)
                self.assertTrue(all(len(item) <= 1200 for item in paragraphs))
                self.assertFalse(page['confirmed'])

    def test_pages_without_landmarks_and_empty_main_keep_existing_fallback(self):
        detail = 'Our workshop offers bicycle wheel building by advance appointment.'
        for markup in ('', '<main></main>', '<main><script><p>Invented service description.</p></script></main>'):
            page = self.extract('<title>Internal QA Workshop</title>' + markup + '<p>' + detail + '</p>')
            self.assertEqual(page['observations']['visible_paragraphs'], [detail])
