"""Real decoded-media provenance and temporal coverage; not semantic model validation."""
import copy, json, subprocess, tempfile, unittest
from pathlib import Path
from PIL import Image
import business_visual_review_queue as sheets
import business_media_replay as replay

class MediaReplayTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='business-replay-offline-')
  self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.video=self.root/'actual.mp4'
  subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i',
    'testsrc2=size=180x320:rate=12','-t','3','-c:v','libx264','-preset','ultrafast',
    str(self.video)],check=True,capture_output=True,timeout=25)
 def packet(self):
  return replay.prepare(self.video,self.root/'out',samples=12)
 def test_real_decoded_frames_cover_entire_source_and_stay_unapproved(self):
  p=self.packet()
  self.assertEqual(p['sourceSha256'],sheets.generate(self.video,self.root/'second',samples=12)['sha256'])
  self.assertEqual(len(p['sampledFrames']),12)
  self.assertGreater(p['sampledFrames'][-1]['timeSeconds'],2.7)
  self.assertAlmostEqual(p['temporalWindows'][0]['startSeconds'],0)
  self.assertAlmostEqual(p['temporalWindows'][-1]['endSeconds'],p['durationSeconds'])
  self.assertTrue(all(x['reviewStatus']=='unreviewed' for x in p['temporalWindows']))
  self.assertFalse(p['wholeExportReviewed'])
  self.assertFalse(p['creativeApproved'])
  self.assertEqual(p['externalRequests'],0)
 def test_valid_packet_needs_real_human_temporal_review_even_with_frame_findings(self):
  p=self.packet();frame=p['sampledFrames'][0]
  assessed=replay.assess(self.video,p,[
   {'type':'sampled_frame','category':'composition','severity':'major',
    'frameIndex':frame['index'],'frameSha256':frame['sha256'],
    'reviewerReference':'offline-example-reviewer','observation':'The sample needs critical composition review.'}])
  self.assertEqual(assessed['disposition'],'rejected_by_recorded_finding')
  self.assertFalse(assessed['wholeExportReviewed'])
  self.assertEqual(len(assessed['unreviewedWindows']),len(p['temporalWindows']))
 def test_project_level_user_rejection_cannot_be_attributed_to_a_specific_frame(self):
  p=self.packet()
  a=replay.assess(self.video,p,[{'type':'project_feedback','category':'physical_realism','severity':'critical',
    'reviewerReference':'user-JA-project-feedback','observation':'Prior projects had oversized droplets that missed the intended bucket.'}])
  self.assertEqual(a['disposition'],'hold_project_feedback_unlocated')
  self.assertFalse(a['wholeExportReviewed'])
  self.assertFalse(a['sourceSpecificRejection'])
 def test_unreviewed_intervals_cannot_be_marked_complete_by_one_observation(self):
  p=self.packet();one=p['temporalWindows'][0]
  a=replay.assess(self.video,p,[{'type':'temporal_segment','category':'continuity','severity':'minor',
    'windowId':one['id'],'startSeconds':one['startSeconds'],'endSeconds':one['endSeconds'],
    'reviewerReference':'human-logged-session','observation':'One local interval reviewed for continuity; remaining footage was not.'}])
  self.assertFalse(a['wholeExportReviewed'])
  self.assertEqual(len(a['unreviewedWindows']),len(p['temporalWindows'])-1)
 def test_all_temporal_windows_recorded_does_not_automatically_approve(self):
  p=self.packet()
  items=[{'type':'temporal_segment','category':'continuity','severity':'none',
    'windowId':w['id'],'startSeconds':w['startSeconds'],'endSeconds':w['endSeconds'],
    'reviewerReference':'human-test-fixture','observation':'Offline fixture review only, not independent creative acceptance.'} for w in p['temporalWindows']]
  a=replay.assess(self.video,p,items)
  self.assertTrue(a['wholeExportReviewed'])
  self.assertFalse(a['creativeApproved'])
  self.assertEqual(a['disposition'],'needs_independent_creative_review')
 def test_stale_source_is_rejected(self):
  p=self.packet();self.video.write_bytes(self.video.read_bytes()+b'changed')
  with self.assertRaises(replay.ReplayError):replay.assess(self.video,p,[])
 def test_contact_sheet_cropped_or_swapped_frame_is_rejected(self):
  p=self.packet();sheet=Path(p['contactSheet'])
  with Image.open(sheet) as img:img.crop((0,0,img.width,img.height-520)).save(sheet)
  with self.assertRaises(replay.ReplayError):replay.assess(self.video,p,[])
 def test_missing_or_swapped_frame_is_rejected(self):
  p=self.packet()
  Path(p['sampledFrames'][0]['file']).write_bytes(Path(p['sampledFrames'][1]['file']).read_bytes())
  with self.assertRaises(replay.ReplayError):replay.assess(self.video,p,[])
 def test_cannot_invent_frame_or_temporal_interval(self):
  p=self.packet();f=p['sampledFrames'][0]
  bad=[
   {'type':'sampled_frame','category':'composition','severity':'major','frameIndex':999,
    'frameSha256':f['sha256'],'reviewerReference':'test-review','observation':'An entirely fabricated frame evidence citation.'},
   {'type':'temporal_segment','category':'continuity','severity':'major','windowId':999,
    'startSeconds':0,'endSeconds':999,'reviewerReference':'test-review','observation':'This assessment exceeds the length of the source.'}
  ]
  for item in bad:
   with self.subTest(item=item['type']),self.assertRaises(replay.ReplayError):
    replay.assess(self.video,p,[item])
 def test_unknown_labels_or_malformed_notes_fail_closed(self):
  p=self.packet()
  with self.assertRaises(replay.ReplayError):
   replay.assess(self.video,p,[{'type':'project_feedback','category':'physics',
    'severity':'critical','reviewerReference':'fixture','observation':'Some issue'}])
 def test_sampled_sheet_cannot_be_relabelled_continuous_review(self):
  p=self.packet();p['coverage']='full_temporal_verified'
  with self.assertRaises(replay.ReplayError):replay.assess(self.video,p,[])
if __name__=='__main__':unittest.main()
