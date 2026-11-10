import unittest
from business_spoken_clips import spoken_windows

class SpokenClipTests(unittest.TestCase):
    def test_groups_longer_complete_review_windows(self):
        lines=[{'start':i*5,'end':i*5+4.5,'text':f'Topic {i} explained.'} for i in range(36)]
        clips=spoken_windows(lines,duration=180)
        self.assertGreaterEqual(len(clips),3)
        self.assertTrue(all(22<=c['end_s']-c['start_s']<=65 for c in clips))
        self.assertTrue(all(c['review_required'] and not c['verified'] for c in clips))
    def test_invalid_timestamps_fail_closed(self):
        for value in [float('nan'),-1,600]:
            with self.assertRaises(ValueError):spoken_windows([{'start':value,'end':9,'text':'x'}],duration=120)
    def test_silence_gap_does_not_splice_unrelated_topics(self):
        rows=[{'start':0,'end':30,'text':'First explanation'},{'start':70,'end':105,'text':'Second explanation'}]
        result=spoken_windows(rows,duration=120)
        self.assertEqual(len(result),2)
        self.assertEqual(result[1]['start_s'],70)

if __name__=='__main__':unittest.main()
