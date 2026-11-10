"""Offline source-hashed media replay: decoded frames, complete window ledger.

This is review *evidence*, never a classifier, trusted rights certificate,
continuous-motion measurement, creative acceptance, or paid vision call.
Recorded observations are reviewer assertions with their scope preserved.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageChops, ImageStat
import business_visual_review_queue as contact

VERSION=1
MAX_BYTES=70*1024*1024
WINDOW_SECONDS=2.0
COVERAGE='sampled_frame_contact_sheet_and_unreviewed_full_duration_windows'
CATEGORIES={'composition','continuity','physical_realism','people','identity',
            'physics','factual_claim','motion','brand_accuracy','other'}
SEVERITIES={'none','minor','major','critical'}
REF=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{7,79}\Z')

class ReplayError(ValueError):
    pass

def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _safe_video(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.suffix.lower()!='.mp4':
        raise ReplayError('Review requires an existing regular MP4')
    if not 1024<=p.stat().st_size<=MAX_BYTES:
        raise ReplayError('Review source size is unsafe')
    return p

def _windows(duration):
    count=math.ceil(duration/WINDOW_SECONDS)
    if count<1 or count>30:
        raise ReplayError('Invalid review timeline duration')
    result=[]
    for i in range(count):
        result.append({'id':f'window-{i+1:02}',
             'startSeconds':round(i*WINDOW_SECONDS,6),
             'endSeconds':round(min(duration,(i+1)*WINDOW_SECONDS),6),
             'reviewStatus':'unreviewed'})
    return result

def _fingerprint(packet):
    return hashlib.sha256(json.dumps(packet,sort_keys=True,
                 separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def prepare(video_path,out_dir,*,samples=12):
    """Decode actual local frames to an evidentiary packet; never mark accepted."""
    src=_safe_video(video_path)
    digest=_sha(src)
    size=src.stat().st_size
    try:
        original=contact.generate(src,out_dir,samples=samples)
    except (contact.ReviewQueueError,OSError,ValueError) as exc:
        raise ReplayError('Local media could not produce a complete review sheet') from exc
    if digest!=original['sha256'] or digest!=_sha(src):
        raise ReplayError('Source changed while generating evidence')
    duration=original['durationSeconds']
    if not math.isfinite(duration) or not 1<=duration<=60:
        raise ReplayError('Invalid source duration')
    report={'version':VERSION,'createdAt':datetime.now(timezone.utc).isoformat(),
       'sourceSha256':digest,'sourceFileSize':size,
       'durationSeconds':duration,'sampledFrames':original['frames'],
       'sampledFrameCount':len(original['frames']),'gridRows':original['gridRows'],
       'gridColumns':original['gridColumns'],
       'contactSheet':original['contactSheet'],
       'contactSheetSha256':original['contactSheetSha256'],
       'windowSeconds':WINDOW_SECONDS,'temporalWindows':_windows(duration),
       'coverage':COVERAGE,'wholeExportReviewed':False,
       'creativeApproved':False,'providerCalls':0,'externalRequests':0,
       'provenance':'offline_local_ffmpeg_decoded_frames',
       'limitations':['Sampled frames do not prove continuous physical realism.',
         'Unreviewed intervals do not establish that any frame was watched.',
         'A review note is an attributed claim, not an independent ground truth.',
         'No visual evaluation authorises creative acceptance or publication.']}
    report['packetSha256']=_fingerprint(report)
    _verify(src,report)
    return report

def _verify(src,packet):
    if not isinstance(packet,dict):
        raise ReplayError('Invalid replay packet')
    if packet.get('version')!=VERSION or packet.get('coverage')!=COVERAGE:
        raise ReplayError('Unknown or overstated media review coverage')
    if packet.get('provenance')!='offline_local_ffmpeg_decoded_frames' or (
        packet.get('wholeExportReviewed') is not False or
        packet.get('creativeApproved') is not False or
        packet.get('providerCalls')!=0 or packet.get('externalRequests')!=0):
        raise ReplayError('Media packet has an unsupported approval or provider claim')
    digest=packet.get('packetSha256')
    if not isinstance(digest,str) or digest!=_fingerprint({k:v for k,v in packet.items() if k!='packetSha256'}):
        raise ReplayError('Review packet metadata was changed')
    if packet.get('sourceFileSize')!=src.stat().st_size or packet.get('sourceSha256')!=_sha(src):
        raise ReplayError('Video no longer matches original review source')
    duration=packet.get('durationSeconds')
    if type(duration) not in (float,int) or not math.isfinite(duration) or not 1<=duration<=60:
        raise ReplayError('Unsafe source duration')
    if packet.get('windowSeconds')!=WINDOW_SECONDS or packet.get('temporalWindows')!=_windows(duration):
        raise ReplayError('Incomplete or misrepresented video timeline')
    frames=packet.get('sampledFrames')
    if not isinstance(frames,list) or not 4<=len(frames)<=12 or packet.get('sampledFrameCount')!=len(frames):
        raise ReplayError('Incomplete sampled-frame inventory')
    if packet.get('gridColumns')!=4 or packet.get('gridRows')!=math.ceil(len(frames)/4):
        raise ReplayError('Sampled-frame grid does not fit every frame')
    sheet=Path(packet.get('contactSheet',''))
    if sheet.is_symlink() or not sheet.is_file() or _sha(sheet)!=packet.get('contactSheetSha256'):
        raise ReplayError('Contact-sheet evidence is missing or changed')
    with Image.open(sheet) as img:
        if img.size!=(1080,packet['gridRows']*520):
            raise ReplayError('Contact-sheet evidence was cropped')
        image=img.convert('RGB')
    seen=set();previous=-1.0
    for i,item in enumerate(frames):
        if not isinstance(item,dict) or item.get('index')!=i+1:
            raise ReplayError('Missing or reordered sampled frame')
        t=item.get('timeSeconds')
        if type(t) not in (int,float) or not math.isfinite(t) or t<=previous or t<0 or t>=duration:
            raise ReplayError('Invalid frame time or duplicate sample')
        previous=t
        file=Path(item.get('file',''))
        if file.parent!=sheet.parent or file.is_symlink() or not file.is_file() or file in seen:
            raise ReplayError('Missing, misplaced or repeated frame')
        seen.add(file)
        if _sha(file)!=item.get('sha256'):
            raise ReplayError('Sampled frame bytes have changed')
        with Image.open(file) as frame:
            if frame.size!=(270,480):
                raise ReplayError('Sampled frame dimensions changed')
            tile=image.crop(((i%4)*270,(i//4)*520,
                            (i%4+1)*270,(i//4)*520+480))
            delta=ImageStat.Stat(ImageChops.difference(frame.convert('RGB'),tile)).mean
            if sum(delta)/3>16:
                raise ReplayError('Sample image does not match its contact-sheet cell')
    if _sha(src)!=packet['sourceSha256']:
        raise ReplayError('Video changed during review')
    return True

def _note(item):
    if not isinstance(item,dict):
        raise ReplayError('Malformed attributed review finding')
    kind=item.get('type')
    standard={'type','category','severity','reviewerReference','observation'}
    extra={'sampled_frame':{'frameIndex','frameSha256'},
           'temporal_segment':{'windowId','startSeconds','endSeconds'},
           'project_feedback':set()}
    if kind not in extra or set(item)!=standard|extra[kind]:
        raise ReplayError('Review finding type and evidence fields are incomplete')
    if item['category'] not in CATEGORIES or item['severity'] not in SEVERITIES:
        raise ReplayError('Unsupported review issue or severity')
    if not isinstance(item['reviewerReference'],str) or not REF.fullmatch(item['reviewerReference']):
        raise ReplayError('Attribution reference is required')
    note=item['observation']
    if not isinstance(note,str) or not 24<=len(note)<=300 or any(ord(c)<32 for c in note):
        raise ReplayError('Specific bounded observation is required')
    return kind

def assess(video_path,packet,observations):
    """Validate immutable sampled pixels and attribute, but never approve creative."""
    src=_safe_video(video_path)
    _verify(src,packet)
    if not isinstance(observations,list) or len(observations)>90:
        raise ReplayError('Bounded review findings required')
    frames={f['index']:f for f in packet['sampledFrames']}
    windows={w['id']:w for w in packet['temporalWindows']}
    reviewed=set();source_rejection=False;unlocated=False;normal=[]
    for obs in observations:
        kind=_note(obs)
        if kind=='sampled_frame':
            f=frames.get(obs['frameIndex']) if type(obs['frameIndex']) is int else None
            if f is None or f['sha256']!=obs['frameSha256']:
                raise ReplayError('Finding is not tied to the exact reviewed pixels')
        elif kind=='temporal_segment':
            w=windows.get(obs['windowId'])
            if w is None or (obs['startSeconds'],obs['endSeconds'])!=(
                        w['startSeconds'],w['endSeconds']):
                raise ReplayError('A temporal observation must reference an exact window')
            reviewed.add(w['id'])
        else:
            unlocated=True
        source_rejection|=(kind!='project_feedback' and obs['severity'] in ('major','critical'))
        normal.append(dict(obs))
    pending=[w['id'] for w in packet['temporalWindows'] if w['id'] not in reviewed]
    full=not pending
    disposition=('rejected_by_recorded_finding' if source_rejection else
                 'hold_project_feedback_unlocated' if unlocated else
                 'needs_independent_creative_review' if full else 'needs_visual_review')
    return {'version':VERSION,'sourceSha256':packet['sourceSha256'],
        'packetSha256':packet['packetSha256'],'reviewedWindowIds':sorted(reviewed),
        'unreviewedWindows':pending,'wholeExportReviewed':full,
        'wholeExportReviewBasis':'self_attested_window_reviews_only' if full else 'incomplete',
        'observations':normal,'disposition':disposition,
        'sourceSpecificRejection':source_rejection,
        'creativeApproved':False,'published':False,'providerCalls':0,
        'noIndependentPerceptualVerification':True,
        'sourceBytesVerified':True,'contactSheetVerified':True}
