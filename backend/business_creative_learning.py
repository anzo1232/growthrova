"""Source-labelled creative lessons reused in planning and review. No paid I/O."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path

LIBRARY=Path(__file__).resolve().parent/'data/business_creative_lessons.json'

class LearningPolicyError(ValueError):pass

def scene_term(term):
    # Bounded variants transfer a lesson from a drip to dripping/pouring, without
    # matching unrelated substrings such as rain inside brain.
    variants={'drip':r'drip(?:s|ping|ped)?','pour':r'pour(?:s|ing|ed)?',
              'rain':r'rain(?:s|ing|ed)?','drink':r'drink(?:s|ing)?',
              'water':r'water','sauce':r'sauce(?:s)?'}
    return variants.get(term,re.escape(term)+r'(?:s)?')

def rubric(profile,scene_text=''):
    if not isinstance(profile,dict):raise LearningPolicyError('Business profile required')
    data=LIBRARY.read_bytes()
    if len(data)>100_000:raise LearningPolicyError('Lesson library exceeds limit')
    try:
        library=json.loads(data)
        if library.get('schemaVersion')!=1 or not isinstance(library.get('policyVersion'),str):raise ValueError()
        lessons=library['lessons']
        if not isinstance(lessons,list) or not 1<=len(lessons)<=60:raise ValueError()
        ids=[]
        for item in lessons:
            if not isinstance(item,dict) or not re.fullmatch('[a-z_]{3,60}',item.get('id','')):raise ValueError()
            if item['id'] in ids:raise ValueError()
            ids.append(item['id'])
            if item.get('scope') not in ('all','selected'):raise ValueError()
            for name in ('traits','risks','sceneTerms'):
                if not isinstance(item.get(name),list) or any(not isinstance(x,str) or len(x)>80 for x in item[name]):raise ValueError()
            if not isinstance(item.get('check'),str) or not 20<=len(item['check'])<=700:raise ValueError()
            if not isinstance(item.get('provenance'),dict):raise ValueError()
    except (ValueError,TypeError,KeyError) as exc:
        raise LearningPolicyError('Invalid versioned lesson library') from exc
    traits={profile.get('primaryTrait'),*profile.get('secondaryTraits',[])}
    risks=set(profile.get('risks',[]))
    text=str(scene_text or '').casefold()[:12_000]
    selected=[]
    for lesson in lessons:
        relevant=(lesson['scope']=='all' or bool(traits.intersection(lesson['traits'])) or
                  bool(risks.intersection(lesson['risks'])) or
                  any(re.search(r'\b'+scene_term(term)+r'\b',text) for term in lesson['sceneTerms']))
        if relevant:selected.append({'id':lesson['id'],'check':lesson['check'],'provenance':lesson['provenance']})
    identity={'librarySha256':hashlib.sha256(data).hexdigest(),'selectedIds':[x['id'] for x in selected]}
    digest=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'version':library['policyVersion'],'policyFingerprint':digest,'librarySha256':identity['librarySha256'],
        'checks':selected,'noAutomaticAcceptance':True,'fineTuningPerformed':False,
        'evidenceRequired':'actual current media and source references, not prompt assertions'}

def review_instructions(policy):
    """Bounded evaluator instructions, keeping untrusted website data separate."""
    if not isinstance(policy,dict) or policy.get('noAutomaticAcceptance') is not True:
        raise LearningPolicyError('Untrusted review policy')
    checks=policy.get('checks',[])
    if not isinstance(checks,list) or len(checks)>60:raise LearningPolicyError('Invalid review checks')
    return '\n'.join(str(x['id'])+': '+str(x['check']) for x in checks)[:9000]
