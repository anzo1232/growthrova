"""Read-only source-anchored offer research and single-scene intent proposals.

Input is *researcher-supplied* public excerpts, not verified search or demand.
No network, model, provider, credits, database writes or publishing. Facts,
buyer anecdotes and competitor comparisons keep distinct trust boundaries.
"""
from __future__ import annotations
from datetime import date
from urllib.parse import urlsplit
import ipaddress,re
import business_marketing_drafts as drafts
import business_scene_contracts as contracts
import business_niche_strategy as niche

VERSION=1
SOURCE_FIELDS={'id','kind','url','excerpt','capturedAt','publishedAt'}
ANGLE_FIELDS={'id','factIndex','businessSourceId','buyerSourceIds','competitorSourceIds',
              'subjectCue','actionCue','peoplePolicy','format','role'}
SOURCE_KINDS={'business','buyer','competitor'}
ID=re.compile(r'[a-z][a-z0-9_-]{1,48}\Z')
INSTRUCTIONS=re.compile(r'\b(?:ignore\s+(?:all\s+|previous\s+)?instructions|system\s+prompt|developer\s*:|assistant\s*:|execute\s+(?:this\s+)?command|reveal\s+secrets|print\s+(?:api\s+)?keys?)\b',re.I)
EMAIL=re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')
PHONE=re.compile(r'(?<!\w)(?:\+?44|0)\s?\d(?:[\s\-]?\d){8,11}(?!\w)')

class ResearchError(ValueError):pass

def _text(value,label,minimum=8,maximum=600):
    if not isinstance(value,str) or not minimum<=len(value.strip())<=maximum or any(ord(c)<32 for c in value):
        raise ResearchError('Invalid '+label)
    return ' '.join(value.split())

def _id(value):
    if not isinstance(value,str) or not ID.fullmatch(value):raise ResearchError('Invalid or duplicate research identifier')
    return value

def _date(value,label,optional=False):
    if value is None and optional:return None
    if not isinstance(value,str) or not re.fullmatch(r'20\d\d-\d\d-\d\d',value):raise ResearchError('Invalid '+label)
    try:return date.fromisoformat(value)
    except ValueError as exc:raise ResearchError('Invalid '+label) from exc

def _domain(url):
    if not isinstance(url,str) or len(url)>600 or any(ord(c)<33 for c in url):raise ResearchError('Invalid public HTTPS source URL')
    try:
        parts=urlsplit(url)
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.fragment or parts.query or parts.port not in (None,443):
            raise ValueError()
        host=parts.hostname.encode('idna').decode('ascii').lower().rstrip('.').removeprefix('www.')
        if '.' not in host or host.endswith(('.local','.internal','.localhost')):raise ValueError()
        try:ipaddress.ip_address(host)
        except ValueError:pass
        else:raise ValueError()
    except (ValueError,TypeError,UnicodeError) as exc:raise ResearchError('Invalid public HTTPS source URL') from exc
    return host

def _sources(records,scope,as_of):
    if not isinstance(records,list) or not 1<=len(records)<=18:raise ResearchError('A bounded public research source list is required')
    output={}
    for record in records:
        if not isinstance(record,dict) or set(record)!=SOURCE_FIELDS:raise ResearchError('Complete public-source provenance required')
        ident=_id(record['id'])
        if ident in output:raise ResearchError('Duplicate source identifier')
        kind=record['kind']
        if kind not in SOURCE_KINDS:raise ResearchError('Unknown source type')
        domain=_domain(record['url'])
        if (domain==scope)!=(kind=='business'):
            raise ResearchError('Business evidence and independent sources must not be mixed')
        excerpt=_text(record['excerpt'],'source excerpt',24,600)
        if INSTRUCTIONS.search(excerpt):raise ResearchError('Source contains instructions, not admissible research evidence')
        if EMAIL.search(excerpt) or PHONE.search(excerpt):
            raise ResearchError('Personal contact details must not enter marketing research')
        captured=_date(record['capturedAt'],'source capture date')
        published=_date(record['publishedAt'],'publication date',optional=True)
        output[ident]={'id':ident,'kind':kind,'url':record['url'],'domain':domain,
                       'excerpt':excerpt,'capturedAt':captured,'publishedAt':published,
                       'futureCapture':captured>as_of,'invalidPublication':bool(published and (published>captured or published>as_of)),
                       'ageDays':(as_of-captured).days}
    return output

def _linked_sources(identifiers,records,expected):
    if not isinstance(identifiers,list) or len(identifiers)>3 or len(identifiers)!=len(set(map(str,identifiers))):
        raise ResearchError('Invalid repeated source associations')
    for ident in identifiers:
        if not isinstance(ident,str) or ident not in records or records[ident]['kind']!=expected:
            raise ResearchError('Research source kind or link does not match its declared purpose')
    return [records[x] for x in identifiers]

def _cue(value,label):
    cue=_text(value,label,3,140)
    if INSTRUCTIONS.search(cue) or EMAIL.search(cue):raise ResearchError('Unsafe creative cue')
    return cue

def compose(con,draft_id,revision,dossier,*,as_of):
    """Research-backed proposal for internal direction review, never generation."""
    try:saved=contracts._saved(con,draft_id,revision);scope=contracts._scope(saved['document'])
    except (contracts.ContractError,drafts.MarketingDraftError) as exc:raise ResearchError(str(exc)) from exc
    today=_date(as_of,'evaluation date')
    if not isinstance(dossier,dict) or set(dossier)!={'sources','angles'}:raise ResearchError('Structured research dossier required')
    sources=_sources(dossier['sources'],scope,today)
    angles=dossier['angles']
    if not isinstance(angles,list) or not 1<=len(angles)<=3:raise ResearchError('One to three researched concepts required')
    facts=saved['document'].get('observedFacts') or []
    profile=niche.profile(saved['document']['business'],facts)
    created=[];seen=set();seen_subjects={}
    for item in angles:
        if not isinstance(item,dict) or not isinstance(item.get('subjectCue'),str):
            raise ResearchError('Invalid researched subject')
        key=' '.join(item['subjectCue'].casefold().split())
        seen_subjects[key]=seen_subjects.get(key,0)+1
    for angle in angles:
        if not isinstance(angle,dict) or set(angle)!=ANGLE_FIELDS:raise ResearchError('Complete sourced angle required')
        ident=_id(angle['id'])
        if ident in seen:raise ResearchError('Duplicate proposed creative angle')
        seen.add(ident)
        source_id=angle['businessSourceId']
        if not isinstance(source_id,str) or source_id not in sources or sources[source_id]['kind']!='business':
            raise ResearchError('Each offer requires first-party business evidence')
        official=sources[source_id]
        buyers=_linked_sources(angle['buyerSourceIds'],sources,'buyer')
        competitors=_linked_sources(angle['competitorSourceIds'],sources,'competitor')
        subject=_cue(angle['subjectCue'],'supported visible subject')
        action=_cue(angle['actionCue'],'supported observable action')
        if angle['role'] not in ('hook','problem','cause','process','solution','proof','cta'):
            raise ResearchError('Unsupported scene role')
        if angle['format'] not in ('image','video') or angle['peoplePolicy'] not in ('none','illustrative_only'):
            raise ResearchError('Scene format or people policy is undefined')
        index=angle['factIndex'];issues=[];warnings=[]
        if type(index) is not int or index<0 or index>=len(facts):issues.append('invalid_business_fact_reference')
        fact=facts[index] if not issues else ''
        normal=lambda s:' '.join(str(s).casefold().split())
        if fact and normal(official['excerpt'])!=normal(fact):
            issues.append('business_source_not_in_saved_facts')
        if not fact or normal(subject) not in normal(fact) or normal(subject) not in normal(official['excerpt']):
            issues.append('subject_not_supported_by_business_evidence')
        if not fact or normal(action) not in normal(fact) or normal(action) not in normal(official['excerpt']):
            issues.append('action_not_supported_by_business_evidence')
        # Words in a *negated* offer are not evidence of an offered service.
        # Split at positive pivots; this is a conservative lexical veto, not
        # a semantic claim verifier or permission to remove source caveats.
        for clause in re.split(r'[.;!?]|\b(?:but|however)\b',fact,flags=re.I):
            if normal(action) in normal(clause):
                before=normal(clause).split(normal(action),1)[0]
                if re.search(r'\b(?:do not|does not|did not|don.t|never|no longer|not currently|cannot|can.t|ceased|stopped|no)\b',before):
                    issues.append('negated_business_offer')
                    break
        if seen_subjects[normal(subject)]>1:issues.append('repeated_subject_requires_continuity_plan')
        if official['futureCapture']:issues.append('source_future_dated')
        if official['invalidPublication']:issues.append('source_publication_date_invalid')
        elif official['ageDays']>90:issues.append('business_source_stale')
        if not buyers:issues.append('buyer_motivation_research_required')
        for b in buyers:
            if b['futureCapture']:issues.append('source_future_dated')
            if b['invalidPublication']:issues.append('source_publication_date_invalid')
            elif b['ageDays']>45:issues.append('buyer_source_stale')
        for competitor in competitors:
            if competitor['futureCapture']:issues.append('source_future_dated')
            if competitor['invalidPublication']:issues.append('source_publication_date_invalid')
            elif competitor['ageDays']>45:warnings.append('competitor_context_stale')
        if not competitors:warnings.append('competitor_context_missing')
        if profile['researchRequired']:issues.append('specialist_niche_research_required')
        # No public discussion, competitor content or unverified outcomes ever
        # become scene instructions. Only literal business evidence cues survive.
        intent=None
        if not issues:
            intent={'sceneId':'research-'+ident,'role':angle['role'],'sourceFactIndices':[index],
                'subject':subject if len(subject)>=12 else 'Documented subject: '+subject,
                'action':'Depict one evidenced process: '+action+'. Maintain natural object scale.',
                'camera':'Single stable close view of '+subject+' with consistent geometry and no invented surroundings.',
                'customerAction':'Visit the business website to learn about this documented service',
                'peoplePolicy':angle['peoplePolicy'],'useAsProof':angle['role']=='proof',
                'format':angle['format'],'continuity':None,
                'needsExactIdentity':(angle['role']=='proof' or
                    (profile['primaryTrait'] in ('hospitality','retail_product','property','software')
                     and angle['role'] in ('process','solution')))}
        created.append({'id':ident,'sourceFactIndices':[index] if type(index) is int and 0<=index<len(facts) else [],
            'businessSourceId':source_id,'buyerSourceIds':[b['id'] for b in buyers],
            'competitorSourceIds':[c['id'] for c in competitors],
            'buyerSignalStatus':('single_source_not_representative_demand' if len(buyers)==1 else
                                 'multiple_sources_not_representative_demand' if buyers else 'missing'),
            'competitorStatus':'unverified_context_only' if competitors else 'missing_comparative_context',
            'blockers':sorted(set(issues)),'warnings':sorted(set(warnings)),
            'intent':intent,'needsHumanReview':True,'proofClaimSupported':False,'buyerDemandProven':False})
    public_sources=[{key:(val.isoformat() if isinstance(val,date) else val)
                     for key,val in record.items() if key not in ('domain','futureCapture','invalidPublication','ageDays')}
                    for record in sources.values()]
    report={'version':VERSION,'draftId':draft_id,'revision':revision,'asOf':today.isoformat(),
        'documentSha256':contracts._hash(saved['document']),'policySha256':contracts._policy(),
        'businessTrait':profile['primaryTrait'],'researchSnapshot':public_sources,'candidates':created,
        'status':'needs_internal_scene_review' if any(not x['blockers'] for x in created) else 'research_incomplete',
        'claimsVerified':False,'buyerDemandProven':False,'competitorClaimsVerified':False,
        'humanReviewRequired':True,'canSpend':False,'canPublish':False,'networkAttempts':0,
        'providerCalls':0,'fineTuningPerformed':False}
    report['fingerprint']=contracts._hash(report)
    return report


def compose_preproduction(con,draft_id,revision,dossier,*,as_of,reference_pools):
    """Link source-led candidates to the existing read-only media planner.

    Never auto-record a reviewed contract. Missing/uncertain imagery remains
    held, not replaced with speculative footage or generic text-to-video.
    """
    import business_scene_preparation as preparation
    if not isinstance(reference_pools,dict) or len(reference_pools)>3:
        raise ResearchError('Explicit bounded reference pools required')
    report=compose(con,draft_id,revision,dossier,as_of=as_of)
    allowed={item['id'] for item in report['candidates']}
    if not set(reference_pools).issubset(allowed):raise ResearchError('Unknown scene reference assignment')
    for item in report['candidates']:
        if item['intent'] is None:
            item['preproduction']={'mode':'hold','blockers':list(item['blockers']),
                'canSpend':False,'approvedForPublishing':False,'visualQualityVerified':False}
            continue
        prepared=preparation.prepare(con,draft_id,revision,item['intent'],
                                     reference_pool=reference_pools.get(item['id'],()))
        item['preproduction']={key:prepared[key] for key in
            ('mode','blockers','selectedReference','estimatedCredits','fingerprint',
             'canSpend','approvedForPublishing','visualQualityVerified','referenceRelevanceVerified')}
    report['fingerprint']=contracts._hash({k:v for k,v in report.items() if k!='fingerprint'})
    return report
