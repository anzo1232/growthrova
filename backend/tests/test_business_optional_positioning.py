"""Optional differentiation must not block a reviewed owner brief or fake source evidence."""
import json, subprocess, tempfile, unittest
from pathlib import Path
from business_marketing_drafts import normalise_document
from business_marketing_offline import OfflineMarketingDocuments
from business_growthrova_writer import source_material

class OptionalPositioningTests(unittest.TestCase):
 def test_empty_optional_positioning_remains_confirmed_after_real_save_reopen(self):
  result=subprocess.run(['node','--input-type=module','-e',SCRIPT],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stderr)
  document=json.loads(result.stdout)
  with tempfile.TemporaryDirectory() as folder:
   db=str(Path(folder)/'drafts.sqlite3')
   def repo(): return OfflineMarketingDocuments(db,lambda: ({'id':'synthetic-owner'},None),lambda ident,user: ({'id':ident},None))
   saved=repo().save('synthetic-org',{'id':'e'*32,'mutationId':'f'*32,'expectedRevision':0,'document':document})
   reopened=repo().read('synthetic-org',saved['id'])['document']
  self.assertIsNotNone(reopened['ownerStrategy']['confirmedContext'])
  self.assertEqual(reopened['ownerStrategy']['positioning'],'')
  self.assertEqual(reopened['observedFacts'],[])
  material=source_material(reopened)
  self.assertFalse(any(item['id']=='brief-positioning' for item in material['evidence']))
  self.assertTrue(all(item['status']=='owner_input' for item in material['evidence']))
  for field in ['audience','offer','callToAction','constraints']:
   changed=json.loads(json.dumps(document))
   changed['ownerStrategy'][field]=''
   self.assertIsNone(normalise_document(changed)['ownerStrategy']['confirmedContext'],field)
  self.assertFalse(reopened['canPublish'])
  self.assertFalse(reopened['canSpend'])

SCRIPT = "import assert from 'node:assert/strict';\nimport {prepareOwnerCampaign} from './src/lib/businessUrlCampaignPipeline.mjs';\nimport {createMarketingDocument} from './src/lib/businessMarketingDocument.mjs';\nimport {confirmOwnerStrategy,strategyConfirmed,editOwnerStrategy} from './src/lib/businessOwnerStrategy.mjs';\nimport {summariseJourney} from './src/lib/businessJourneyStages.mjs';\nconst pending=createMarketingDocument(prepareOwnerCampaign({business:'Internal QA Workshop',sourceUrl:'https://example.org/',goal:'enquiries',offer:'Bicycle brake adjustments by appointment.',audience:'Local bicycle commuters',positioning:'',callToAction:'Contact the workshop to discuss an appointment.'}));\nconst confirmed=confirmOwnerStrategy(pending);\nassert.equal(strategyConfirmed(confirmed),true);\nassert.equal(confirmed.ownerStrategy.positioning,'');\nconst summary=summariseJourney(confirmed);\nassert.notEqual(summary.steps[0].status,'blocked');\nassert.notEqual(summary.steps[1].status,'blocked');\nassert.match(summary.steps[0].detail,/owner.supplied/i);\nassert.doesNotMatch(summary.nextAction,/Add evidence for the business/);\nassert.equal(summary.steps[3].status,'waiting');\nassert.equal(summary.published,0);\nassert.equal(strategyConfirmed(editOwnerStrategy(confirmed,'offer','Changed owner offer.')),false);\nfor(const key of ['audience','offer','callToAction','constraints']){\n assert.throws(()=>confirmOwnerStrategy(editOwnerStrategy(pending,key,'')),/Complete/);\n}\nprocess.stdout.write(JSON.stringify(confirmed));\n"
