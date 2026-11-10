"""Two-tier offline Reel visual evidence review.

Tier 1: analyse real decoded frames using no paid API.
Tier 2: a future explicitly authorised vision adapter, with strict result schema.
Neither tier can make a creative 'accepted' verdict; only qualified internal
reviewers can. Failed or missing tier-2 evidence is never invented as a pass.
"""
from __future__ import annotations
import hashlib,json,math,re,subprocess
from pathlib import Path
from PIL import Image,ImageChops,ImageFilter,ImageStat
import business_video_motion_qc as technical

ISSUES=('hands','faces','food_accuracy','brand_accuracy','physical_realism','composition','cinematography')
CRITICAL=frozenset(('hands','faces','food_accuracy','brand_accuracy','physical_realism'))
VERSION=1

class VisualReviewError(ValueError):pass

def _get_frames(path, duration):
 # Cover beginning, middle, and end instead of just taking the first four.
 n=max(5,min(12,int(math.ceil(duration*1.5))))
 times=[round((0.3+(duration-.6)*i/(n-1)),2) for i in range(n)]
 frames=[]
 for second in times:
  cmd=['ffmpeg','-nostdin','-v','error','-ss',str(second),'-i',str(path),
   '-frames:v','1','-vf','scale=180:320,format=rgb24',
   '-pix_fmt','rgb24','-f','rawvideo','pipe:1']
  try:
   result=subprocess.run(cmd,check=True,capture_output=True,timeout=8)
  except (OSError,subprocess.SubprocessError) as exc:
   raise VisualReviewError('A video frame could not be decoded') from exc
  if len(result.stdout)!=180*320*3:raise VisualReviewError('Frame sample has invalid dimensions')
  frame=Image.frombytes('RGB',(180,320),result.stdout)
  frames.append((second,frame))
 return frames

def cheap_scan(path,*,expected_duration):
 p=Path(path)
 motion=technical.review(p,expected_duration=expected_duration)
 if not motion['technicalMotionPass']:
  return {'version':VERSION,'stage':'technical_rejected','videoSha256':motion['sha256'],
   'technicalMotionPass':False,'issues':motion['automaticQcIssues'],
   'visualStageAllowed':False,'advancedVision':None,'humanReviewRequired':True,
   'automaticVisualApproval':False,'published':False,'providerCalls':0,'frameSamples':[]}
 sampled=_get_frames(p,motion['durationSeconds'])
 frames=[]
 frame_colors=[]
 previous_frame=None
 for second,frame in sampled:
  stat=ImageStat.Stat(frame)
  mean=sum(stat.mean)/3
  variance=sum(stat.var)/3
  lap=ImageStat.Stat(frame.filter(ImageFilter.FIND_EDGES)).var
  edge=sum(lap)/3
  delta=(sum(ImageStat.Stat(ImageChops.difference(previous_frame,frame)).mean)/3
    if previous_frame is not None else None)
  frames.append({'timeSeconds':second,'sha256':hashlib.sha256(frame.tobytes()).hexdigest(),
   'luma':round(mean,2),'detailVariance':round(edge,1),'colorVariance':round(variance,1),
   'deltaFromPrevious':round(delta,2) if delta is not None else None})
  previous_frame=frame
  frame_colors.append(mean)
 blank=sum(f['detailVariance']<5 and f['colorVariance']<50 for f in frames)
 exposure=sum(f['luma']<10 or f['luma']>247 for f in frames)
 # Continuous timeline sampling catches a long frozen portion which a few
 # front-loaded frames cannot detect. Only a sustained near-zero run is a hard
 # failure; cinematic slow motion remains subjective review.
 delta_values=[f['deltaFromPrevious'] for f in frames[1:]]
 freeze_run=longest_freeze=0
 for value in delta_values:
  freeze_run=freeze_run+1 if value is not None and value<=1.15 else 0
  longest_freeze=max(longest_freeze,freeze_run)
 # Objective pathological cases only: broad low-detail and near-blank sequences.
 failures=[]
 if longest_freeze>=max(4,math.ceil(len(delta_values)*.52)):
  failures.append('sustained_frozen_video_segment')
 if blank>=math.ceil(len(frames)*.85):failures.append('near_blank_across_timeline')
 if exposure>=math.ceil(len(frames)*.85):failures.append('extreme_exposure_across_timeline')
 warnings=[]
 if sum(f['detailVariance']<15 for f in frames)>=math.ceil(len(frames)*.65):
  warnings.append('low_detail_requires_review')
 if any(x is not None and x>72 for x in delta_values):
  warnings.append('abrupt_motion_or_transition_needs_review')
 if longest_freeze>=3 and 'sustained_frozen_video_segment' not in failures:
  warnings.append('localised_frozen_segment_needs_review')
 stage='technical_rejected' if failures else 'awaiting_visual_semantics'
 return {'version':VERSION,'stage':stage,'videoSha256':motion['sha256'],
  'technicalMotionPass':not failures,'issues':failures,'warnings':warnings,
  'visualStageAllowed':not failures,'advancedVision':None,'humanReviewRequired':True,
  'automaticVisualApproval':False,'published':False,'providerCalls':0,
  'frameSamples':frames,'sampleCoverageSeconds':[frames[0]['timeSeconds'],frames[-1]['timeSeconds']]}

def validate_vision_result(raw,*,sample_report,expected_brand):
 """Validate optional model output; never treat model text as trusted instructions.

 A model report can block a clear failure, or request review. It cannot
 certify a brand/food subject as fact without external owner evidence.
 """
 if not isinstance(raw,dict) or not isinstance(sample_report,dict):raise VisualReviewError('Invalid evidence report')
 if sample_report.get('stage')!='awaiting_visual_semantics':
  raise VisualReviewError('Expensive analysis forbidden on a technically failed shot')
 if raw.get('videoSha256')!=sample_report.get('videoSha256'):
  raise VisualReviewError('Vision result belongs to another source')
 if raw.get('model') not in ('offline_vision_fixture','approved_vision_adapter_v1'):
  raise VisualReviewError('Unrecognised visual evaluator')
 entries=raw.get('findings')
 if not isinstance(entries,list) or len(entries)>20:raise VisualReviewError('Invalid finding collection')
 frame_times=[item['timeSeconds'] for item in sample_report['frameSamples']]
 conclusions=[]
 for f in entries:
  if not isinstance(f,dict):raise VisualReviewError('Invalid visual finding')
  category=f.get('category');severity=f.get('severity')
  confidence=f.get('confidence');second=f.get('timeSeconds')
  if category not in ISSUES or severity not in ('none','minor','major','critical'):
   raise VisualReviewError('Unrecognised visual category or severity')
  if type(confidence) not in (float,int) or not math.isfinite(confidence) or not 0<=confidence<=1:
   raise VisualReviewError('Confidence must be a bounded numeric probability')
  if type(second) not in (float,int) or not any(abs(second-t)<=.8 for t in frame_times):
   raise VisualReviewError('Finding must refer to an actual sampled frame')
  evidence=f.get('explanation')
  if not isinstance(evidence,str) or not 15<=len(evidence)<=350:
   raise VisualReviewError('Specific visual evidence is required')
  conclusions.append({'category':category,'severity':severity,'confidence':round(confidence,3),
   'timeSeconds':round(second,2),'explanation':evidence})
 definite=[x for x in conclusions if x['category'] in CRITICAL and x['severity']=='critical' and x['confidence']>=.92]
 noncritical=[x for x in conclusions if x['severity'] in ('major','critical') and x not in definite]
 return {'version':VERSION,'stage':'auto_rejected' if definite else 'awaiting_internal_creative_review',
  'videoSha256':sample_report['videoSha256'],'model':raw['model'],
  'business':str(expected_brand)[:90], 'criticalFindings':definite,'needsHumanAttention':noncritical,
  'findings':conclusions,'identityVerified':False,'foodClaimsVerified':False,
  'humanReviewRequired':True,'automaticVisualApproval':False,
  'recommendedDecision':'reject' if definite else 'internal_review',
  'providerCallsByThisValidator':0}

def run_staged_review(path,*,expected_duration,expected_brand,vision_adapter=None,paid_vision_approved=False):
 """No adapter by default, and never call a paid adapter without permission."""
 fast=cheap_scan(path,expected_duration=expected_duration)
 if not fast['visualStageAllowed']:
  return {'fast':fast,'visual':None,'finalDisposition':'technical_rejected','visionCalls':0}
 if vision_adapter is None:
  return {'fast':fast,'visual':None,'finalDisposition':'awaiting_semantic_visual_review','visionCalls':0}
 if paid_vision_approved is not True:
  return {'fast':fast,'visual':None,'finalDisposition':'awaiting_paid_vision_approval','visionCalls':0}
 try:
  # Adapter owns its expense and must only receive real sampled frame hashes and
  # the verified local path; it cannot authorise a regeneration or publication.
  raw=vision_adapter(Path(path),fast['frameSamples'],str(expected_brand)[:90])
  model_report=validate_vision_result(raw,sample_report=fast,expected_brand=expected_brand)
 except Exception as exc:
  return {'fast':fast,'visual':None,'finalDisposition':'vision_unavailable_needs_manual_review',
   'visionCalls':1,'errorType':type(exc).__name__}
 return {'fast':fast,'visual':model_report,'finalDisposition':model_report['stage'],
  'visionCalls':1}
