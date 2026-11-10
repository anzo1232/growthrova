"""Complete Reel delivery QC: technical + audio + claims + mobile safety.

A private silent WIP is allowed; final acceptance is not. The actual MP4 is
decoded, and licensing/brand attestations remain explicit, never invented.
"""
from __future__ import annotations
import json,math,subprocess,re
from pathlib import Path
import business_reel_visual_intelligence as vi

class DeliveryError(ValueError):pass

def _probe(path):
 result=subprocess.run(['ffprobe','-v','error','-show_entries',
  'format=duration:stream=codec_type,codec_name,channels,width,height','-of','json',str(path)],
  check=True,capture_output=True,text=True,timeout=15)
 return json.loads(result.stdout)

def verify(path,*,expected_duration,approval,has_audio_evidence=False):
 if not isinstance(approval,dict):raise DeliveryError('Final brand, claims and crop review required')
 if not approval.get('brandAndCtaVerified') or not approval.get('claimsChecked') or not approval.get('allMediaRightsReviewed'):
  raise DeliveryError('Brand, claims or media rights have not been reviewed')
 boxes=approval.get('textBoxes')
 if not isinstance(boxes,list) or len(boxes)<3:raise DeliveryError('Measured title, CTA and contact safe areas required')
 subjects=set()
 for bbox in boxes:
  if not isinstance(bbox,dict):raise DeliveryError('Invalid mobile crop specification')
  x=bbox.get('x');y=bbox.get('y');w=bbox.get('width');h=bbox.get('height')
  name=bbox.get('subject')
  if name not in ('brand','cta','contact') or name in subjects:raise DeliveryError('Each text role must be unique and present')
  subjects.add(name)
  if any(type(val) not in (float,int) or not math.isfinite(val) for val in (x,y,w,h)):
   raise DeliveryError('Safe-zone geometry is invalid')
  if x<55 or y<220 or w<=10 or h<=12 or x+w>665 or y+h>1000:
   raise DeliveryError('Text may overlap the mobile platform controls')
 if subjects!={'brand','cta','contact'}:raise DeliveryError('Brand, CTA and contact geometry all required')
 if has_audio_evidence is not True:raise DeliveryError('No verified and licensed soundtrack receipt for this cut')
 p=Path(path)
 if p.is_symlink() or not p.is_file() or p.stat().st_size>65*1024*1024:
  raise DeliveryError('Final preview is missing or untrusted')
 try:probe=_probe(p)
 except (ValueError,OSError,subprocess.SubprocessError,json.JSONDecodeError):
  raise DeliveryError('Cannot probe the final Reel safely') from None
 videos=[x for x in probe.get('streams',[]) if x.get('codec_type')=='video']
 audios=[x for x in probe.get('streams',[]) if x.get('codec_type')=='audio']
 if len(videos)!=1 or len(audios)!=1 or int(audios[0].get('channels',0))<1:
  raise DeliveryError('Final Reel must have one video and one audible soundtrack stream')
 if abs(float(probe['format']['duration'])-expected_duration)>.8:
  raise DeliveryError('Final Reel has an unexpected playback duration')
 # Sampled frames and a normal loudness value can conceal damaged compressed
 # packets. Decode the complete actual deliverable before any acceptance.
 # Some FFmpeg builds log decoder errors but still return 0, even with -xerror.
 try:
  integrity=subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(p),
   '-map','0:v:0','-map','0:a:0','-f','null','-'],
   check=True,capture_output=True,timeout=25)
  if integrity.stderr.strip():raise ValueError('Decoder reported damaged media')
 except (OSError,ValueError,subprocess.SubprocessError):
  raise DeliveryError('Final video or audio contains damaged data and cannot be approved') from None
 # ffmpeg audio analysis, no remote transcription or API.
 try:
  cmd=['ffmpeg','-nostdin','-v','info','-i',str(p),'-vn','-af','volumedetect','-f','null','-']
  data=subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=25).stderr
  match=re.search(r'mean_volume:\s*([-\d.]+)\s*dB',data)
  peak=re.search(r'max_volume:\s*([-\d.]+)\s*dB',data)
  if not match or not peak:raise ValueError()
  mean=float(match.group(1));maximum=float(peak.group(1))
 except (OSError,ValueError,subprocess.SubprocessError):
  raise DeliveryError('Final audio loudness could not be verified') from None
 if mean< -45 or maximum < -30 or maximum >0:
  raise DeliveryError('Audio is inaudible, severely under-levelled or clipped')
 # Run a real visual/frame QC again after any sound edit, not just on originals.
 stages=vi.run_staged_review(p,expected_duration=expected_duration,expected_brand='Final private owner-reviewed Reel')
 if not stages['fast']['technicalMotionPass']:
  raise DeliveryError('Assembled output failed motion/exposure checks')
 return {'stage':'awaiting_internal_creative_director_acceptance',
  'technicalReelPass':True,'audioPresent':True,'meanAudioDb':mean,'maxAudioDb':maximum,
  'mobileSafeTextPass':True,'ownerBrandDetailsReviewed':True,'published':False,
  'automaticallyApproved':False,'semanticVisualReviewPending':True,
  'frameCount':len(stages['fast']['frameSamples'])}
