"""Offline technical preview gate for already-authorised, real motion MP4.

Checks motion and orientation, but not artistic authenticity or platform suitability.
No generation, publication, spending, uploads or retries.
"""
from __future__ import annotations
import hashlib,json,math,subprocess
from pathlib import Path
from PIL import Image,ImageChops,ImageStat

class MotionReviewError(ValueError):pass

def review(path,*,expected_duration=5):
 p=Path(path)
 if p.is_symlink() or not p.is_file() or p.stat().st_size>65*1024*1024 or p.stat().st_size<1000:
  raise MotionReviewError('Unsupported, untrusted or missing video file')
 try:
  info=subprocess.run(['ffprobe','-v','error','-show_entries',
    'format=duration:stream=codec_type,width,height','-of','json',str(p)],
    capture_output=True,text=True,timeout=20,check=True)
  details=json.loads(info.stdout)
  streams=[x for x in details['streams'] if x.get('codec_type')=='video']
  duration=float(details['format']['duration'])
  if len(streams)!=1 or not math.isfinite(duration) or not 1<=duration<=30:raise ValueError()
  width,height=int(streams[0]['width']),int(streams[0]['height'])
  if width<500 or height<850 or width>=height:raise MotionReviewError('Video must be a legible portrait frame')
  if abs(duration-expected_duration)>0.75:raise MotionReviewError('Video duration does not match the reviewed brief')
  # Extract a small set of actual decoded frames; fake provider task statuses cannot pass.
  frame_bytes=180*320*3
  extraction=subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(p),
   '-vf','fps=1/1.5,scale=180:320,format=rgb24',
   '-f','rawvideo','-pix_fmt','rgb24','-frames:v','4','pipe:1'],
   capture_output=True,timeout=25,check=True)
  raw=extraction.stdout
  if len(raw)<frame_bytes*3 or len(raw)%frame_bytes:raise MotionReviewError('Not enough decoded scene frames')
  pics=[Image.frombytes('RGB',(180,320),raw[i:i+frame_bytes]) for i in range(0,len(raw),frame_bytes)]
  differences=[]
  for i in range(1,len(pics)):
   pixels=ImageChops.difference(pics[i-1],pics[i])
   differences.append(round(sum(ImageStat.Stat(pixels).mean)/3,2))
  # Conservative minimum: detects a static slideshow/poster, not verified semantic motion.
  moving=sum(delta>=2.5 for delta in differences)>=2
  brightness=[round(sum(ImageStat.Stat(pic).mean)/3,2) for pic in pics]
  # Only high-confidence failures are automatically rejected. Dark cinematic
  # footage alone is not a failure unless nearly all sampled frames are blank.
  exposure_bad=sum(x<9 or x>247 for x in brightness)>=3
  issues=[]
  if not moving:issues.append('static_or_insufficient_motion')
  if exposure_bad:issues.append('near_black_or_blown_out_frames')
  technical_pass=moving and not exposure_bad
  quality=('awaiting_human_video_review' if technical_pass else
    'rejected_static_or_insufficient_motion' if not moving else
    'rejected_exposure_or_black_frames')
  return {'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
   'sizeBytes':p.stat().st_size,'width':width,'height':height,'durationSeconds':round(duration,3),
   'frameDifferences':differences,'frameBrightness':brightness,
   'automaticQcIssues':issues,'technicalMotionPass':technical_pass,
   'qualityStatus':quality,
   'physicalMotionAuthenticityVerified':False,'realBusinessFootageVerified':False,
   'approved':False,'published':False,'paidRetriesAllowed':False}
 except MotionReviewError:raise
 except (OSError,ValueError,KeyError,subprocess.SubprocessError,json.JSONDecodeError) as err:
  raise MotionReviewError('Video cannot be safely decoded or validated') from err
