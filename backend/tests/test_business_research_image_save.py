"""Real JS research-to-document output must survive the Python save boundary."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from business_marketing_offline import OfflineMarketingDocuments

class ResearchImageSaveTests(unittest.TestCase):
    def test_cdn_research_metadata_does_not_break_campaign_save_and_reopen(self):
        # Regression: copying external CDN references into websiteImages causes
        # the actual save validator to reject an otherwise valid website draft.
        audit={'source_url':'https://example.org/','observations':{
            'title':'Example wellness club','meta_description':'Fitness, spa and dining at our club.',
            'image_candidates':[
                {'url':'https://cdn.example.net/spa.jpg','alt':'External reference only'},
                {'url':'https://example.org/club.jpg','alt':'Club reference'},
                {'url':'https://example.org/club.jpg#fragment','alt':'Fragment reference'},
                {'url':'https://example.org:444/club.jpg','alt':'Unexpected port'}]}}
        js="import fs from 'node:fs';import {prepareUrlCampaign} from './src/lib/businessUrlCampaignPipeline.mjs';import {createMarketingDocument} from './src/lib/businessMarketingDocument.mjs';process.stdout.write(JSON.stringify(createMarketingDocument(prepareUrlCampaign(JSON.parse(fs.readFileSync(0,'utf8'))))));"
        run=subprocess.run(['node','--input-type=module','-e',js],input=json.dumps(audit),
            text=True,capture_output=True,check=True,cwd=Path(__file__).resolve().parents[1])
        document=json.loads(run.stdout)
        with tempfile.TemporaryDirectory() as temp:
            repo=OfflineMarketingDocuments(str(Path(temp)/'campaigns.db'),
                lambda:({'id':'test-owner'},None),lambda ident,user:({'id':ident},None))
            try:
                saved=repo.save('test-org',{'id':'a'*32,'mutationId':'b'*32,'expectedRevision':0,'document':document})
            except Exception as error:
                self.fail('Prepared research campaign must save: '+str(error))
            reopened=repo.read('test-org',saved['id'])
            self.assertEqual(reopened['document']['websiteImages'],[
                {'url':'https://example.org/club.jpg','alt':'Club reference','rights_confirmed':False,'authenticity_verified':False}])
            self.assertEqual(reopened['document']['sourceUrl'],'https://example.org/')
            self.assertFalse(reopened['document']['canPublish'])
