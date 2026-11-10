"""Focused regression for retained research snapshots through the real save store."""
import copy
import tempfile
import unittest
from pathlib import Path
from business_marketing_offline import OfflineMarketingDocuments
from business_marketing_drafts import MarketingDraftError
from tests.test_business_marketing_drafts import document


class OrganicSnapshotTests(unittest.TestCase):
    def test_saved_stale_reference_remains_editable_and_replayable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'documents.sqlite'
            def repo():
                return OfflineMarketingDocuments(path, lambda: ({'id':'owner'},None),
                    lambda org,user: ({'id':org},None))
            store = repo()
            doc = document()
            ref = dict(kind='fact',index=0,quote=doc['observedFacts'][0],sourceUrl='')
            work = dict(id='organic-1',kind='content',title='Explain seasonal dining',
                brief='Check dates first',draft='',nextAction='',status='planned',reference=ref)
            doc['organicWork'] = [work]
            payload = dict(id='1'*32,mutationId='2'*32,expectedRevision=0,document=doc)
            self.assertEqual(store.save('org',payload)['revision'],1)
            # Editing retained work must survive the first fingerprint pass even
            # when its source observation has subsequently changed.
            doc['observedFacts'] = ['Updated website research']
            work['draft'] = 'Owner draft awaiting review'
            payload.update(mutationId='3'*32,expectedRevision=1)
            saved = store.save('org',payload)
            self.assertEqual(saved['document']['organicWork'],[work])
            self.assertTrue(store.save('org',payload)['replayed'])
            self.assertEqual(repo().read('org','1'*32)['document']['organicWork'],[work])
            forged = copy.deepcopy(payload)
            forged.update(mutationId='4'*32,expectedRevision=2)
            forged['document']['organicWork'][0]['reference']['quote']='Not in retained research'
            with self.assertRaises(MarketingDraftError):
                store.save('org',forged)
            self.assertEqual(repo().read('org','1'*32)['revision'],2)
