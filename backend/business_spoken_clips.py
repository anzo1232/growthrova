"""Bounded, transcript-grounded review windows for speech-led business videos.

No claims about customer conversion, accuracy or rights. Transcript input must
already be timestamp-aligned to the source by a trusted transcription step.
"""
from __future__ import annotations
import math


def spoken_windows(segments, *, duration, min_seconds=22, target_seconds=42,
                   max_seconds=65, max_results=18):
    if not isinstance(segments,list) or len(segments)>10000:
        raise ValueError('Invalid transcript')
    duration=float(duration)
    if not math.isfinite(duration) or not 3<=duration<=3600:
        raise ValueError('Invalid source duration')
    if not 10<=min_seconds<=target_seconds<=max_seconds<=90:
        raise ValueError('Invalid window lengths')
    clean=[]
    for row in segments:
        if not isinstance(row,dict):raise ValueError('Malformed transcript segment')
        a,b=row.get('start'),row.get('end')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (a,b)):
            raise ValueError('Invalid transcript timestamps')
        if a<0 or b<=a or b>duration+0.15:raise ValueError('Transcript outside source')
        if clean and a<clean[-1]['end']-0.15:raise ValueError('Overlapping transcript timestamps')
        text=row.get('text')
        if not isinstance(text,str):raise ValueError('Invalid transcript text')
        if text.strip():clean.append({'start':float(a),'end':min(float(b),duration),'text':text.strip()[:400]})
    out=[];i=0
    while i<len(clean) and len(out)<max_results:
        start=clean[i]['start'];j=i
        while j+1<len(clean) and clean[j]['end']-start<target_seconds:
            if clean[j+1]['end']-start>max_seconds or clean[j+1]['start']-clean[j]['end']>8:break
            j+=1
        end=clean[j]['end']
        if end-start>=min_seconds:
            words=' '.join(x['text'] for x in clean[i:j+1])
            out.append({'start_s':round(start,2),'end_s':round(end,2),
                        'transcript':words[:2200],
                        'title':'Spoken segment for review',
                        'review_required':True,'verified':False,
                        'reason':'Timestamped speech grouping; check full context and clip boundaries.'})
        i=j+1
    return out
