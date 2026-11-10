"""Human visual checklist for footage from a real scene.

Prevent a technical 'motion passed' flag or unverified AI vision output from
being treated as actual creative-director approval.
"""
from __future__ import annotations
import re
import business_reel_visual_intelligence as vision

class ArtReviewError(ValueError):pass

def check_categories(checks,sampled,*,required_categories=()):
 if not isinstance(checks,list) or len(checks)!=len(vision.ISSUES):
  raise ArtReviewError('Review every anatomy, accuracy and creative category')
 if not isinstance(sampled,dict) or not sampled.get('frameSamples'):
  raise ArtReviewError('A real decoded-frame evidence report is required')
 times=[x['timeSeconds'] for x in sampled['frameSamples']]
 result={}
 for item in checks:
  if not isinstance(item,dict):raise ArtReviewError('Invalid review entry')
  key=item.get('category');state=item.get('verdict')
  reason=item.get('evidence');at=item.get('timeSeconds')
  if key not in vision.ISSUES or key in result:
   raise ArtReviewError('Unknown or repeated category')
  if state not in ('pass','not_applicable','reject'):
   raise ArtReviewError('Unknown category verdict')
  if not isinstance(reason,str) or not 20<=len(reason.strip())<=400:
   raise ArtReviewError('Explain the visible evidence for every category')
  if type(at) not in (int,float) or not any(abs(at-t)<=.8 for t in times):
   raise ArtReviewError('Evidence must refer to a decoded frame time')
  # If no hands/faces appear, 'not applicable' is honest; it is not 'passed'.
  result[key]={'verdict':state,'timeSeconds':round(at,2),'evidence':reason.strip()}
 if set(result)!=set(vision.ISSUES):raise ArtReviewError('Visual category review incomplete')
 for mandatory in ('physical_realism','composition','cinematography',*required_categories):
  if mandatory not in result or result[mandatory]['verdict']=='not_applicable':
   raise ArtReviewError('The subject, physical realism, framing and cinematography must be assessed')
 # A human reviewer is not allowed to 'pass' while calling out a hard failure
 # elsewhere in their checklist.
 return {'categories':result,'allPassed':all(x['verdict']!='reject' for x in result.values()),
  'hardFailures':[key for key,val in result.items() if val['verdict']=='reject'],
  'humanReviewerRequired':True,'automaticallyApproved':False}

def reviewer_id(value):
 if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,64}',value):
  raise ArtReviewError('Identified, authorised creative reviewer required')
 return value
