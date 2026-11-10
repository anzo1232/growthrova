import unittest,tempfile
from pathlib import Path
import business_visual_review_queue as q
class VisualReviewQueueTests(unittest.TestCase):
 def test_missing_video_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(q.ReviewQueueError):q.generate(Path(d)/'missing.mp4',d)
 def test_missing_symlink_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'video.mp4';p.symlink_to(Path(d)/'missing.mp4')
   with self.assertRaises(q.ReviewQueueError):q.generate(p,d)
 def test_invalid_sampling_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'video.mp4';p.write_bytes(b'fake')
   with self.assertRaises(q.ReviewQueueError):q.generate(p,d,samples=25)
