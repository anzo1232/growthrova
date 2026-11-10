"""Manual website-read recovery uses the real document/review/store/writer contracts."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from business_growthrova_writer import source_material
from business_marketing_drafts import MarketingDraftError, normalise_document
from business_marketing_offline import OfflineMarketingDocuments


class ResearchRecoveryTests(unittest.TestCase):
    maxDiff = None
    def test_manual_brief_save_reopen_preserves_owner_input_without_website_evidence(self):
        script = """
import {prepareOwnerCampaign} from './src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument,editMarketingPost,marketingPlanCsv} from './src/lib/businessMarketingDocument.mjs';
import {confirmOwnerStrategy} from './src/lib/businessOwnerStrategy.mjs';
const pending=createMarketingDocument(prepareOwnerCampaign({business:'Example workshop',sourceUrl:'https://example.org/',goal:'enquiries',
 offer:'Bicycle brake adjustments by appointment.',audience:'Local bicycle commuters',
 positioning:'Discuss the brake problem at our workshop before booking.',callToAction:'Contact the workshop to discuss an appointment.'}));
const confirmed=confirmOwnerStrategy(pending);
const edited=editMarketingPost(confirmed,1,{copyDraft:'Owner words retained through save and reopen.'});
process.stdout.write(JSON.stringify({pending,confirmed:edited,download:marketingPlanCsv(edited)}));
"""
        run = subprocess.run(['node', '--input-type=module', '-e', script],
                             cwd=Path(__file__).resolve().parents[1],
                             capture_output=True, text=True, check=True)
        output = json.loads(run.stdout)
        with self.assertRaises(MarketingDraftError):
            source_material(output['pending'])
        with tempfile.TemporaryDirectory() as temp:
            db = str(Path(temp) / 'documents.sqlite3')
            def repo():
                return OfflineMarketingDocuments(db, lambda: ({'id': 'synthetic-owner'}, None),
                                                 lambda ident, user: ({'id': ident}, None))
            saved = repo().save('synthetic-org', {'id': 'a'*32, 'mutationId': 'b'*32,
                                                'expectedRevision': 0, 'document': output['confirmed']})
            reopened = repo().read('synthetic-org', saved['id'])['document']
        # The established normalizer omits an empty factDecisions key; compare
        # its canonical contract as well as every owner-entered word below.
        self.assertEqual(reopened, normalise_document(output['confirmed']))
        for field in ('offer', 'audience', 'positioning', 'callToAction', 'constraints', 'confirmedContext'):
            self.assertEqual(reopened['ownerStrategy'][field], output['confirmed']['ownerStrategy'][field])
        self.assertEqual(reopened['ownerStrategy'].get('factDecisions', []), [])
        self.assertEqual(reopened['posts'], output['confirmed']['posts'])
        self.assertEqual(reopened['observedFacts'], [])
        self.assertEqual(reopened['websiteImages'], [])
        self.assertFalse(reopened['canPublish'])
        self.assertFalse(reopened['canSpend'])
        material = source_material(reopened)
        self.assertTrue(material['evidence'])
        self.assertTrue(all(item['status'] == 'owner_input' and item['sourceUrl'] == ''
                            for item in material['evidence']))
        self.assertEqual(material['audience']['status'], 'owner_planning_input')
        self.assertIn('Owner words retained through save and reopen.', output['download'])
        Path('/tmp/growthrova-recovery-saved-document.json').write_text(json.dumps(reopened, indent=2))
        Path('/tmp/growthrova-recovery-download.csv').write_text(output['download'])
