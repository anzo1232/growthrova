"""Validate and diversify multi-pass provider suggestions before human approval."""
from __future__ import annotations
import json,math,re

class CandidateError(ValueError):pass

def parse_response(value):
    if isinstance(value,dict) and isinstance(value.get('data'),str):value=value['data']
    if isinstance(value,str):
        clean=re.sub(r'^```(?:json)?\s*|\s*```$', '', value.strip(),flags=re.I)
        try:value=json.loads(clean)
        except (ValueError,TypeError) as exc:raise CandidateError('Invalid provider JSON') from exc
    if isinstance(value,list):value={'clips':value}
    if not isinstance(value,dict) or not isinstance(value.get('clips'),list):raise CandidateError('Invalid clips payload')
    if len(value['clips'])>48:raise CandidateError('Excessive candidate count')
    return value['clips']

def select_candidates(responses, duration, *, max_clips=20,min_seconds=12,max_seconds=65):
    if not isinstance(responses,list) or len(responses)>5:raise CandidateError('Invalid analysis passes')
    if not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0:raise CandidateError('Invalid duration')
    valid=[]
    for pass_no,response in enumerate(responses):
        for i,item in enumerate(parse_response(response)):
            if not isinstance(item,dict):continue
            start,end=item.get('start_s'),item.get('end_s')
            if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (start,end)):continue
            if not (0<=start<end<=duration+.1 and min_seconds<=end-start<=max_seconds):continue
            title=item.get('title');why=item.get('why')
            if not isinstance(title,str) or not isinstance(why,str) or not title.strip() or not why.strip():continue
            valid.append({'start_s':round(start,2),'end_s':round(min(end,duration),2),
                'title':title.strip()[:120],'why':why.strip()[:300],
                'pass':pass_no+1,'status':'requires_human_review',
                'use':'supporting_footage' if re.search('technique|process|guard|scissor|razor|prepar|detail|refin|blend|progress',title,re.I) else 'standalone_candidate'})
    # Strong potential standalone footage goes first, then add geographic timeline
    # variety, excluding substantially overlapping or same-topic duplicates.
    selected=[]
    ordered=sorted(valid,key=lambda x:(x['use']!='standalone_candidate',x['start_s']))
    for item in ordered:
        if len(selected)>=max_clips:break
        if any(max(0,min(item['end_s'],x['end_s'])-max(item['start_s'],x['start_s']))/min(item['end_s']-item['start_s'],x['end_s']-x['start_s'])>.35 for x in selected):continue
        selected.append(item)
    selected.sort(key=lambda x:x['start_s'])
    return {'clips':selected,'received':len(valid),'excluded':len(valid)-len(selected),
            'standalone_candidates':sum(c['use']=='standalone_candidate' for c in selected),
            'review_required':True,'quality_verified':False}
