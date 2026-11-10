"""Storyboard words share review invalidation with the saved video caption."""
import copy
import tempfile
import unittest
from pathlib import Path

from business_marketing_offline import OfflineMarketingDocuments
from tests.test_business_marketing_drafts import document


class VideoScriptReviewTests(unittest.TestCase):
    def test_changed_storyboard_cannot_keep_review_on_save_replay_and_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            database = str(Path(folder) / 'campaigns.sqlite3')

            def repository():
                return OfflineMarketingDocuments(database,
                    lambda: ({'id': 'synthetic-owner'}, None),
                    lambda ident, user: ({'id': ident}, None))

            draft = document()
            image = draft['creatives'][0]
            image['status'] = 'copy_reviewed'
            video = copy.deepcopy(image)
            video.update(id='creative-2', format='video_ad', ratio='9:16',
                brief='Voiceover: Discuss your servicing needs with our team.\nOn-screen words: Enquire about servicing.')
            draft['creatives'].append(video)

            def save(value, revision, operation):
                return repository().save('synthetic-org', {'id': '1' * 32,
                    'mutationId': operation * 32, 'expectedRevision': revision, 'document': value})

            first = save(draft, 0, '2')
            changed = copy.deepcopy(first['document'])
            changed['creatives'][0]['brief'] = 'Leave more space around the authorised logo.'
            changed['creatives'][1]['brief'] = 'Voiceover: Tell us which service you need.\nOn-screen words: Contact our team.'
            # A stale client submits its old review status. The store must also enforce this.
            saved = save(changed, 1, '3')
            self.assertEqual(saved['document']['creatives'][1]['status'], 'draft')
            self.assertEqual(saved['document']['creatives'][0]['status'], 'copy_reviewed')
            replayed = save(changed, 1, '3')
            self.assertTrue(replayed['replayed'])
            self.assertEqual(replayed['revision'], saved['revision'])
            self.assertEqual(replayed['document'], saved['document'])
            reopened = repository().read('synthetic-org', saved['id'])
            self.assertEqual(reopened['document'], saved['document'])
            for key in ('copyDraft', 'callToAction'):
                self.assertEqual(reopened['document']['creatives'][1][key], video[key])
            self.assertEqual(reopened['document']['posts'], first['document']['posts'])
            self.assertFalse(reopened['document']['creatives'][1]['approved'])
            self.assertFalse(reopened['document']['canPublish'])
            # Explicit re-review after the edit was saved is still supported.
            checked = copy.deepcopy(reopened['document'])
            checked['creatives'][1]['status'] = 'copy_reviewed'
            confirmed = save(checked, 2, '4')
            self.assertEqual(confirmed['document']['creatives'][1]['status'], 'copy_reviewed')
