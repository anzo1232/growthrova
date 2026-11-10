"""Conservative explainable creative-review triage from real offline frame data.

Flags require human judgement; a machine never verifies faces, food or branding.
"""
from __future__ import annotations

WARNINGS={
 'low_detail_requires_review':('medium','Review sharpness of the subject in sampled footage'),
 'abrupt_motion_or_transition_needs_review':('medium','Inspect the cut for accidental jump, jarring movement or transition'),
 'localised_frozen_segment_needs_review':('high','Inspect potential frozen frames at the recorded sample times'),
}

def summarise(scan):
 if not isinstance(scan,dict):raise ValueError('Offline frame scan required')
 issues=scan.get('issues',[])
 if not isinstance(issues,list):raise ValueError('Invalid machine findings')
 warnings=scan.get('warnings',[])
 if not isinstance(warnings,list):raise ValueError('Invalid machine warnings')
 if scan.get('technicalMotionPass') is not True or issues:
  return {'disposition':'technical_rejected','machineCanApprove':False,
   'priority':'critical','reviewTasks':[{'code':str(x)[:80],'priority':'critical','instruction':'Replace or repair technically failed footage'} for x in issues] or [{'code':'technical_failed','priority':'critical','instruction':'Recheck the video technical failure'}],
   'visualSemanticsChecked':False,'paidCalls':0}
 tasks=[]
 for code in dict.fromkeys(warnings):
  severity,action=WARNINGS.get(code,('medium','Inspect the flagged part of the source video'))
  tasks.append({'code':code,'priority':severity,'instruction':action})
 tasks.append({'code':'human_scene_integrity','priority':'required',
  'instruction':'Manually check hands, faces, physical realism, accurate food and logo, framing and brand fit against genuine source evidence'})
 return {'disposition':'human_review_required','machineCanApprove':False,
  'priority':'high' if any(x['priority']=='high' for x in tasks) else 'review',
  'reviewTasks':tasks,'visualSemanticsChecked':False,'paidCalls':0}
