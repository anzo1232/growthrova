"""Conservative, no-spend readiness checklist for an actual business Reel.

No visual semantics or usage rights are inferred from a technical pass.
"""
from __future__ import annotations

SLOTS=('hook','craft','experience','payoff')

def assess(state):
 if not isinstance(state,dict):raise ValueError('Project state required')
 slots={slot.get('slot'):slot for slot in state.get('slots',[]) if isinstance(slot,dict)}
 checks=[]
 def add(code,ok,action):checks.append({'code':code,'passed':bool(ok),'nextAction':None if ok else action})
 add('current_campaign',state.get('isCurrentRevision') is True,'Restore the current campaign revision')
 for key in SLOTS:
  slot=slots.get(key,{})
  status=slot.get('productionStatus')
  add('approved_'+key,status=='accepted',
      'Supply actual owner-authorised footage and secure internal visual approval' if key!='payoff'
      else 'Lock the genuine brand and approve the ending')
 add('locked_brand',state.get('brandLock',{}).get('locked') is True,'Verify real logo, colours, brand name and contact information')
 variants={e.get('variant') for e in state.get('edits',[]) if isinstance(e,dict) and e.get('previewAvailable') is True and isinstance(e.get('contentSha256'),str) and len(e['contentSha256'])==64}
 for name in ('a','b'):
  add('cut_'+name,name in variants,'Render the complete '+('social-first' if name=='a' else 'cinematic')+' cut from accepted shots')
  track=(state.get('captionTracks') or {}).get(name) or {}
  add('caption_'+name, bool(isinstance(track,dict) and track.get('captionRevision') and track.get('cues')), 'Write or verify exact timed captions for cut '+name)
 add('internal_final_qc',state.get('bothEditsQualityChecked') is True,
     'Inspect actual A/B exports, licensed audio, crop, factual claims and final content hashes')
 add('owner_choice',state.get('localOwnerChoiceRecorded') is True,
     'Show both current cuts to the owner and record a version-bound choice')
 add('spend_reconciled',state.get('providerSubmissionUnknownJobs')==0 and state.get('providerCostUnreconciledJobs')==0,
     'Reconcile unresolved provider tasks before spending anything')
 passed=all(c['passed'] for c in checks)
 return {'business':state.get('business','Unverified business'), 'readyForPrivateHandoff':passed,
         'publishPermitted':False,'paidGenerationPermitted':False,
         'passed':sum(c['passed'] for c in checks),'total':len(checks),
         'blockingActions':[c for c in checks if not c['passed']], 'checks':checks}
