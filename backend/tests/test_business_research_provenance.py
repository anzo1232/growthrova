"""Exact page provenance through real JS preparation, saved review and writer input."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from business_marketing_drafts import MarketingDraftError, normalise_document
from business_marketing_offline import OfflineMarketingDocuments
from business_growthrova_writer import source_material, writing_context


class ResearchProvenanceTests(unittest.TestCase):
    def prepare(self):
        detail='We offer bicycle servicing and brake adjustments by appointment.'
        audit={'source_url':'https://example.org/', 'observations':{
            'title':'Example workshop','meta_description':'Bicycle services.', 'visible_paragraphs':[detail]},
            'page_reports':[
                {'source_url':'https://example.org/','status':'extracted_unconfirmed','observations':{
                    'title':'Example workshop','meta_description':'Bicycle services.'}},
                {'source_url':'https://example.org/servicing','status':'extracted_unconfirmed','observations':{
                    'visible_paragraphs':[detail]}}]}
        js="""import fs from 'node:fs';
import {prepareUrlCampaign} from './src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument} from './src/lib/businessMarketingDocument.mjs';
import {reviewBusinessFact,confirmOwnerStrategy} from './src/lib/businessOwnerStrategy.mjs';
let d=createMarketingDocument(prepareUrlCampaign(JSON.parse(fs.readFileSync(0,'utf8'))));
for(let i=0;i<d.observedFacts.length;i++)d=reviewBusinessFact(d,i,'confirmed');
process.stdout.write(JSON.stringify(confirmOwnerStrategy(d)));"""
        run=subprocess.run(['node','--input-type=module','-e',js],input=json.dumps(audit),
            text=True,capture_output=True,check=True,cwd=Path(__file__).resolve().parents[1])
        return json.loads(run.stdout),detail

    def test_secondary_page_survives_save_reopen_and_writer_with_exact_review_context(self):
        document,detail=self.prepare()
        with tempfile.TemporaryDirectory() as temp:
            repo=OfflineMarketingDocuments(str(Path(temp)/'documents.db'),
                lambda:({'id':'synthetic-owner'},None),lambda ident,user:({'id':ident},None))
            repo.save('synthetic-org',{'id':'a'*32,'mutationId':'b'*32,'expectedRevision':0,'document':document})
            saved=repo.read('synthetic-org','a'*32)['document']
        self.assertIsNotNone(saved['ownerStrategy']['confirmedContext'])
        evidence=next(item for item in source_material(saved)['evidence'] if item['quote']==detail)
        self.assertEqual(evidence['sourceUrl'],'https://example.org/servicing')
        self.assertEqual(evidence['status'],'owner_reviewed_observation')
        self.assertEqual(saved['observedFactSources'],document['observedFactSources'])
        changed=copy.deepcopy(saved)
        changed['observedFactSources'][saved['observedFacts'].index(detail)]='https://example.org/other'
        self.assertIsNone(normalise_document(changed)['ownerStrategy']['confirmedContext'])
        self.assertNotEqual(writing_context(saved),writing_context(changed))
        self.assertEqual(saved['posts'],document['posts'])
        self.assertFalse(saved['canPublish']);self.assertFalse(saved['canSpend'])

    def test_provenance_rejects_wrong_count_foreign_and_unsafe_pages_without_rewriting_legacy(self):
        document,_=self.prepare()
        for urls in [[],['https://foreign.example/page']*len(document['observedFacts']),
                     ['https://example.org:444/page']*len(document['observedFacts']),
                     ['https://user@example.org/page']*len(document['observedFacts']),
                     ['https://example.org/page#fragment']*len(document['observedFacts']),
                     ['http://example.org/page']*len(document['observedFacts'])]:
            with self.subTest(urls=urls):
                changed={**document,'observedFactSources':urls}
                with self.assertRaises(MarketingDraftError):normalise_document(changed)
        # Historical documents have no page map. Keep that explicit absence;
        # never reconstruct secondary page provenance from keyword matching.
        legacy=copy.deepcopy(document);legacy.pop('observedFactSources',None)
        legacy['ownerStrategy']['confirmedContext'].pop('observedFactSources',None)
        saved=normalise_document(legacy)
        self.assertNotIn('observedFactSources',saved)
        self.assertIsNotNone(saved['ownerStrategy']['confirmedContext'])

    def test_surplus_historical_review_cannot_become_writer_evidence(self):
        document,_=self.prepare()
        phantom={'index':39,'observation':'Unsupported historical service claim.',
                 'decision':'confirmed','statement':''}
        document['ownerStrategy']['factDecisions'].append(phantom)
        document['ownerStrategy']['confirmedContext']['factDecisions'].append(phantom)
        saved=normalise_document(document)
        self.assertIsNotNone(saved['ownerStrategy']['confirmedContext'])
        material=source_material(saved)
        self.assertNotIn('fact-39',[item['id'] for item in material['evidence']])
        self.assertFalse(any('historical service' in item['quote'] for item in material['evidence']))
