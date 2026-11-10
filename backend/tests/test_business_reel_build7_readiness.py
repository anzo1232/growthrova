import unittest
from business_reel_build7_readiness import assess,SLOTS

class TestReadiness(unittest.TestCase):
 def base(self):
  return {'business':'Fixture','isCurrentRevision':True,
   'slots':[{'slot':name,'productionStatus':'accepted'} for name in SLOTS],
   'brandLock':{'locked':True},'edits':[{'variant':v,'previewAvailable':True,'contentSha256':'a'*64} for v in ('a','b')],
   'captionTracks':{'a':{'captionRevision':1,'cues':[1]},'b':{'captionRevision':1,'cues':[2]}},
   'bothEditsQualityChecked':True,'localOwnerChoiceRecorded':True,
   'providerSubmissionUnknownJobs':0,'providerCostUnreconciledJobs':0}
 def test_complete_private_only(self):
  x=assess(self.base());self.assertTrue(x['readyForPrivateHandoff']);self.assertFalse(x['publishPermitted']);self.assertFalse(x['paidGenerationPermitted'])
 def test_empty_campaign_requires_real_media(self):
  state=self.base();state['slots']=[{'slot':name,'productionStatus':'not_generated'} for name in SLOTS];state['edits']=[];state['captionTracks']={};state['brandLock']={'locked':False};state['bothEditsQualityChecked']=False;state['localOwnerChoiceRecorded']=False
  x=assess(state);self.assertFalse(x['readyForPrivateHandoff']);self.assertIn('approved_hook',[a['code'] for a in x['blockingActions']]);self.assertIn('internal_final_qc',[a['code'] for a in x['blockingActions']])
 def test_one_cut_and_unknown_provider_job_blocks(self):
  state=self.base();state['edits']=[{'variant':'a','previewAvailable':True,'contentSha256':'a'*64}];state['providerSubmissionUnknownJobs']=1
  self.assertEqual({'cut_b','spend_reconciled'}, {a['code'] for a in assess(state)['blockingActions']})
 def test_synthetic_technical_pass_cannot_become_creative_approval(self):
  state=self.base();state['slots'][0]['productionStatus']='awaiting_internal_review';state['slots'][0]['technicalQC']={'technicalMotionPass':True}
  self.assertFalse(assess(state)['readyForPrivateHandoff'])
 def test_old_campaign_cannot_be_handed_off(self):
  state=self.base();state['isCurrentRevision']=False
  self.assertFalse(assess(state)['readyForPrivateHandoff'])

 def test_missing_cost_or_unversioned_edit_fails_closed(self):
  state=self.base();del state['providerSubmissionUnknownJobs'];state['edits'][0].pop('contentSha256')
  blocked={x['code'] for x in assess(state)['blockingActions']}
  self.assertIn('spend_reconciled',blocked);self.assertIn('cut_a',blocked)
 def test_null_track_is_not_a_server_error(self):
  state=self.base();state['captionTracks']['a']=None
  self.assertIn('caption_a',{x['code'] for x in assess(state)['blockingActions']})
 def test_caption_track_without_cues_is_not_finished(self):
  state=self.base();state['captionTracks']['b']={'captionRevision':1,'cues':[]}
  self.assertIn('caption_b',{x['code'] for x in assess(state)['blockingActions']})

if __name__=='__main__':unittest.main()
