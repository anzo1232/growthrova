"""Reference-first internal scene proposals. No provider, credentials or approval.

Source and reference associations are proposals requiring actual internal review,
not model-verified facts. Never write a contract merely because preparation ran.
"""
from __future__ import annotations
import re,sqlite3
import business_marketing_drafts as drafts
import business_scene_contracts as contracts
import business_creative_learning as learning
import business_creative_preflight as preflight
import business_niche_strategy as strategy

VERSION=1
FIELDS={'sceneId','role','sourceFactIndices','subject','action','camera','customerAction',
        'peoplePolicy','useAsProof','format','continuity','needsExactIdentity'}
ROLES={'hook','problem','cause','process','solution','proof','cta'}
COMMAND=re.compile(r'\b(?:ignore (?:all |previous )?instructions|system prompt|developer:|assistant:|execute command|reveal secrets|print (?:api|secret|key))',re.I)
LINKED=re.compile(r'\b(?:same (?:roof|house|property|product|vehicle|room|building|person|subject|location)|before(?:[- /]and[- /]|[- /])after)\b',re.I)
MULTIBEAT=re.compile(r'\b(?:cut to|transition to|montage|then (?:cut|show|reveal|switch)|finally (?:reveal|show))\b',re.I)

class PreparationError(ValueError):pass

def _text(value,label,low=8,high=300):
    if not isinstance(value,str) or not low<=len(value.strip())<=high or any(ord(x)<32 and x not in '\n\t' for x in value):
        raise PreparationError('Missing or invalid '+label)
    return ' '.join(value.split())

def _indices(value,facts):
    if not isinstance(value,list) or not 1<=len(value)<=6 or any(type(i) is not int or not 0<=i<len(facts) for i in value) or len(set(value))!=len(value):
        raise PreparationError('Explicit valid source fact indices required')
    for i in value:_text(facts[i],'source evidence',12,2000)
    return sorted(value)

def _intent(value,facts):
    if not isinstance(value,dict) or set(value)!=FIELDS:raise PreparationError('Complete single-scene intent required')
    output=dict(value)
    try:contracts._id(output['sceneId'])
    except contracts.ContractError as exc:raise PreparationError(str(exc)) from exc
    if output['role'] not in ROLES or output['format'] not in ('image','video'):raise PreparationError('Unknown scene role or format')
    if output['peoplePolicy'] not in ('none','illustrative_only'):raise PreparationError('Explicit people policy required')
    for key in ('useAsProof','needsExactIdentity'):
        if type(output[key]) is not bool:raise PreparationError('Explicit boolean '+key+' required')
    for key in ('subject','action','camera','customerAction'):output[key]=_text(output[key],key,12,300)
    output['sourceFactIndices']=_indices(output['sourceFactIndices'],facts)
    continuity=output['continuity']
    if continuity is not None:
        if not isinstance(continuity,dict) or set(continuity)!={'groupId','previousSceneId'}:raise PreparationError('Explicit continuity group and predecessor required')
        try:
            contracts._id(continuity['groupId'])
            if continuity['previousSceneId'] is not None:contracts._id(continuity['previousSceneId'])
        except contracts.ContractError as exc:raise PreparationError(str(exc)) from exc
        if continuity['previousSceneId']==output['sceneId']:raise PreparationError('Scene cannot continue itself')
        output['continuity']=dict(continuity)
    return output

def _references(con,scope,facts,intent,pool):
    if not isinstance(pool,(list,tuple)) or len(pool)>12:raise PreparationError('Bounded reviewed reference pool required')
    valid=[];rejected=[];seen=set()
    for candidate in pool:
        if not isinstance(candidate,dict) or set(candidate)!={'id','sourceFactIndices','providerImage'}:raise PreparationError('Invalid candidate reference fields')
        ident=candidate['id']
        try:contracts._id(ident)
        except contracts.ContractError as exc:raise PreparationError(str(exc)) from exc
        if ident in seen:raise PreparationError('Duplicate candidate reference')
        seen.add(ident);indices=_indices(candidate['sourceFactIndices'],facts);issues=[]
        row=con.execute('SELECT * FROM business_scene_references WHERE id=?',(ident,)).fetchone()
        if not row or row['scope']!=scope:issues.append('unregistered_or_foreign_reference')
        else:
            expected=contracts._hash([row['scope'],row['sha256'],row['identity_root'],row['parent_id'],row['origin'],row['rights_reference'],row['reviewer_reference']])
            if row['fingerprint']!=expected:issues.append('reference_record_changed')
            try:
                digest=contracts._image_digest(candidate['providerImage'])
                if digest!=row['sha256']:issues.append('reference_bytes_changed')
            except contracts.ContractError:issues.append('verified_reference_bytes_required')
        if not set(intent['sourceFactIndices']).issubset(indices):issues.append('reference_not_linked_to_scene_evidence')
        if issues:rejected.append({'id':ident,'issues':issues});continue
        valid.append({'id':ident,'origin':row['origin'],'sha256':row['sha256'],'identityRoot':row['identity_root'],
            'registrationFingerprint':row['fingerprint'],'sourceFactIndices':indices,'providerImage':candidate['providerImage']})
    order={'owner_asset':0,'licensed_asset':1,'illustrative_ai':2}
    valid.sort(key=lambda x:(order[x['origin']],x['id']))
    return valid,rejected

def prepare(con,draft_id,revision,intent,*,reference_pool=()):
    """Read-only proposal; no automatic contract, approval, budget or provider use."""
    try:saved=contracts._saved(con,draft_id,revision);scope=contracts._scope(saved['document'])
    except (contracts.ContractError,drafts.MarketingDraftError) as exc:raise PreparationError(str(exc)) from exc
    doc=saved['document'];facts=doc.get('observedFacts') or [];intent=_intent(intent,facts)
    profile=strategy.profile(doc['business'],facts)
    evidence=[{'index':i,'quote':facts[i],'ownerVerified':False} for i in intent['sourceFactIndices']]
    scene_text=' '.join(intent[k] for k in ('subject','action','camera'))
    policy=learning.rubric(profile,scene_text)
    blockers=[]
    if profile['researchRequired']:blockers.append('business_research_required')
    if COMMAND.search(' '.join(facts[i] for i in intent['sourceFactIndices'])):blockers.append('untrusted_source_instruction')
    if COMMAND.search(scene_text+' '+intent['customerAction']):blockers.append('unsafe_scene_instruction')
    if intent['peoplePolicy']=='none' and preflight.positive_mentions(re.sub(r'\bhuman[- ]scale\b','natural scale',scene_text,flags=re.I),preflight.HUMANS):
        blockers.append('people_policy_conflict')
    if MULTIBEAT.search(intent['action']):blockers.append('split_into_single_action_scenes')
    if LINKED.search(scene_text) and intent['continuity'] is None:blockers.append('explicit_continuity_required')
    # This detects obvious off-topic filler; overlap is NOT factual or
    # perceptual verification. Every viable proposal still needs source review.
    stop={'this','that','with','from','into','their','your','business','service','services','local','professional','specific','show','showing','scene','realistic'}
    def terms(text):
        return {re.sub(r'(?:ing|ed|s)$','',word) for word in re.findall(r'\b[a-z]{4,}\b',text.casefold()) if word not in stop}
    source_terms=terms(' '.join(facts[i] for i in intent['sourceFactIndices']))
    if not source_terms.intersection(terms(intent['subject']+' '+intent['action'])):
        blockers.append('business_relevance_not_established')
    actual_claim=preflight.positive_mentions(re.sub(r'\bnot (?:a |the )?','no ',scene_text,flags=re.I),
        r'(?:actual|real|genuine)\s+(?:customers?|clients?|staff|employees?|premises|completed\s+(?:work|jobs?)|results?)')
    if 'regulated_or_high_trust_claims' in profile['risks'] and preflight.positive_mentions(scene_text,
            r'(?:guaranteed|cures?|results?|before(?:[- /]and[- /]|[- /])after)'):
        blockers.append('verified_claim_evidence_required')
    valid,rejected=_references(con,scope,facts,intent,reference_pool)
    continuity=intent['continuity'];expected_root=None
    if continuity:
        group=con.execute('SELECT identity_root FROM business_scene_continuity WHERE scope=? AND group_id=?',(scope,continuity['groupId'])).fetchone()
        if group:expected_root=group['identity_root']
        if continuity['previousSceneId'] is not None:
            previous=con.execute('SELECT scene_json,identity_root FROM business_scene_contracts WHERE scope=? AND scene_id=?',(scope,continuity['previousSceneId'])).fetchone()
            if not previous:blockers.append('previous_scene_not_reviewed')
            else:
                import json
                before=json.loads(previous['scene_json']).get('continuity')
                if not before or before['groupId']!=continuity['groupId']:blockers.append('previous_scene_identity_mismatch')
                elif expected_root and expected_root!=previous['identity_root']:blockers.append('previous_scene_identity_mismatch')
                else:expected_root=previous['identity_root']
        if expected_root:
            for item in valid[:]:
                if item['identityRoot']!=expected_root:
                    valid.remove(item);rejected.append({'id':item['id'],'issues':['continuity_identity_mismatch']})
    proof=intent['useAsProof'] or intent['role']=='proof' or actual_claim
    # A software demonstration is actual evidence, never an invented interface.
    software_demo=profile['primaryTrait']=='software' and bool(re.search(r'\b(?:screen|dashboard|interface|demonstrat\w*)\b',scene_text,re.I))
    proof=proof or software_demo
    if proof:
        valid=[x for x in valid if x['origin']=='owner_asset']
        if not valid:blockers.append('authentic_business_material_required')
        if intent['format']=='video':blockers.append('authentic_video_required')
    elif intent['needsExactIdentity']:
        # Stock/licensed photos cannot establish the actual named dish,
        # product, premises or other specific business identity.
        valid=[x for x in valid if x['origin']=='owner_asset']
        if not valid:blockers.append('authentic_subject_reference_required')
    selected=valid[0] if valid else None
    if not selected:blockers.append('reviewed_reference_required')
    checks=[{'id':x['id'],'criterion':x['check']} for x in policy['checks']]
    checks.extend([
      {'id':'reference_relevance','criterion':'Inspect the exact reference image and record visible details that support this scene and its source facts; tags alone are not evidence.'},
      {'id':'single_action','criterion':'One observable action per generated shot; preserve subject scale, camera geometry and the planned crop.'},
      {'id':'source_support','criterion':'Check that the chosen factual source supports the service and that the illustration cannot be mistaken for a real client result.'}])
    mode='hold';request=None;cost=None;scene=None
    if not blockers:
        if intent['format']=='image':mode='reuse_source_image';cost=0
        else:
            from business_runway_video import CREDITS
            mode='reference_image_to_video';cost=CREDITS
            exclusion='No people, hands or faces. ' if intent['peoplePolicy']=='none' else 'People are illustrative, never actual staff or clients. '
            prompt=('Illustrative documentary scene. Subject: '+intent['subject']+'. One action: '+intent['action']+
                ' Camera: '+intent['camera']+' '+exclusion+
                'Preserve reference geometry, materials and object identity. Natural real-time motion. No text or logos. '
                'Fictional illustration, not client-job evidence. Add branding separately.')
            if len(prompt)>980:blockers.append('scene_prompt_too_long');mode='hold';cost=None
            else:
                request={'model':'gen4_turbo','ratio':'720:1280','duration':5,'promptImage':selected['providerImage'],'promptText':prompt}
                scene={'sceneId':intent['sceneId'],'purpose':intent['role'].capitalize()+': '+intent['subject'],
                    'customerAction':intent['customerAction'],'sourceFactIndices':intent['sourceFactIndices'],
                    'origin':'illustrative_ai','useAsProof':False,'peoplePolicy':intent['peoplePolicy'],
                    'expectedAction':intent['action'],'failureChecks':[x['criterion'][:400] for x in checks][:12],
                    'referenceIds':[selected['id']],'continuity':continuity}
    selected_public={k:v for k,v in selected.items() if k!='providerImage'} if selected else None
    planning_checks=[
      {'id':'marketing_intent','criterion':'Explain the customer need, this scene’s specific contribution and the supported next step.'},
      {'id':'reference_relevance','criterion':'Inspect the exact reference pixels and identify subject details relevant to the linked source evidence.'},
      {'id':'source_support','criterion':'Identify which saved source statements support the offer; do not turn unconfirmed wording into verified claims.'},
      {'id':'single_action','criterion':'Assess one achievable action, a coherent camera/crop and realistic scale before commissioning motion.'},
      {'id':'identity_plan','criterion':'Explain whether identity continuity is required and how the selected reference lineage will preserve it.'}]
    if any(c['id']=='liquid_physics' for c in checks):
        planning_checks.append({'id':'physics_plan','criterion':'Inspect particle size, gravity path and receiving-vessel alignment in the reference; specify the movement to test after generation.'})
    result={'version':VERSION,'draftId':draft_id,'revision':revision,'intent':intent,
        'sourceSha256':contracts._hash(doc),'policyFingerprint':contracts._policy(),
        'businessTrait':profile['primaryTrait'],'evidence':evidence,'mode':mode,
        'selectedReference':selected_public,'rejectedReferences':rejected,'blockers':sorted(set(blockers)),
        'preproductionChecks':planning_checks,'reviewChecks':checks,'scene':scene,'request':request,'estimatedCredits':cost,
        'estimateBasis':'existing_local_adapter_constants_not_live_pricing' if cost else 'no_new_provider_generation',
        'reviewRequired':True,'canSpend':False,'approvedForPublishing':False,'visualQualityVerified':False,
        'referenceRelevanceVerified':False,'fineTuningPerformed':False}
    result['fingerprint']=contracts._hash(result)
    return result


def record_reviewed(con,draft_id,revision,intent,*,reference_pool,expected_fingerprint,assessment):
    """Record an explicitly reviewed proposal. Never self-approve or spend."""
    prepared=prepare(con,draft_id,revision,intent,reference_pool=reference_pool)
    if expected_fingerprint!=prepared['fingerprint']:raise PreparationError('Scene, evidence, policy or reference changed after review')
    if prepared['blockers'] or prepared['mode']!='reference_image_to_video' or not prepared['request']:
        raise PreparationError('A blocked or reuse-only proposal cannot create an AI scene contract')
    if not isinstance(assessment,dict) or set(assessment)!={'reviewerReference','checks'}:
        raise PreparationError('An explicit internal assessment is required')
    reviewer=_text(assessment['reviewerReference'],'reviewer reference',12,160)
    required={x['id'] for x in prepared['preproductionChecks']};checks=assessment['checks']
    if not isinstance(checks,list) or len(checks)!=len(required):raise PreparationError('Every pre-production check needs an evidenced verdict')
    seen=set();notes=set();normal=[]
    for entry in checks:
        if not isinstance(entry,dict) or set(entry)!={'id','verdict','evidence'}:raise PreparationError('Invalid reviewer check')
        key=entry['id']
        if not isinstance(key,str) or key not in required or key in seen or entry['verdict']!='pass':raise PreparationError('Missing, unknown or failed review cannot be accepted')
        note=_text(entry['evidence'],'observable review evidence',35,600)
        if note.casefold() in notes:raise PreparationError('Each review check needs its own specific evidence, not a repeated generic pass')
        seen.add(key);notes.add(note.casefold());normal.append({'id':key,'verdict':'pass','evidence':note})
    review={'proposalFingerprint':prepared['fingerprint'],'sourceSha256':prepared['sourceSha256'],
        'policyFingerprint':prepared['policyFingerprint'],'draftId':draft_id,'revision':revision,
        'assessment':{'reviewerReference':reviewer,'checks':sorted(normal,key=lambda x:x['id'])},
        'outputQualityApproved':False,'modelTrainingPerformed':False}
    try:
        return contracts.record(con,draft_id,revision,prepared['scene'],prepared['request'],prepared['estimatedCredits'],
            reviewer_reference='preparation-review:'+contracts._hash(review),preparation_review=review)
    except contracts.ContractError as exc:raise PreparationError(str(exc)) from exc


def read_review(con,draft_id,proposal_fingerprint):
    """Read preserved planning evidence; it is never output approval."""
    import json
    row=con.execute('SELECT review_json,sha256 FROM business_scene_preparation_reviews WHERE draft_id=? AND proposal_sha=?',
        (draft_id,proposal_fingerprint)).fetchone()
    if not row:raise PreparationError('Preparation review not found')
    try:
        result=json.loads(row['review_json'])
        if contracts._hash(result)!=row['sha256'] or result.get('outputQualityApproved') is not False:raise ValueError()
    except (ValueError,TypeError) as exc:raise PreparationError('Preparation review integrity check failed') from exc
    return result


def saved_slot_summary(con,draft_id,revision,part):
    """Read-only next-action guidance for an existing draft; no guessed reference.

    Older shot briefs are not silently promoted to structured, reviewed intents.
    Source overlap is merely an internal candidate association, clearly labelled.
    """
    saved=contracts._saved(con,draft_id,revision);doc=saved['document']
    facts=doc.get('observedFacts') or []
    tokens=lambda text:set(re.findall(r'\b[a-z]{4,}\b',str(text).casefold()))-{'this','that','with','from','their','website','business','source','into'}
    evidence=part.get('sourceEvidence','');words=tokens(evidence)
    scored=sorted([(len(words&tokens(f)),i) for i,f in enumerate(facts)],reverse=True)
    indices=[i for score,i in scored[:3] if score>0]
    profile=strategy.profile(doc['business'],facts) if any(isinstance(f,str) and len(f.strip())>=12 for f in facts) else {}
    policy=learning.rubric(profile,str(part.get('shotBrief',''))+' '+evidence)
    return {'version':VERSION,'status':'needs_internal_scene_preparation',
       'sourceCandidateIndices':indices,'sourceAssociationVerified':False,
       'blockers':['explicit_single_action_intent_required','reviewed_reference_selection_required']+([] if indices else ['source_evidence_link_required']),
       'workflow':['Choose a specific customer need and single observable action from the saved evidence.',
                   'Inspect relevant owner material first; use actual source material for proof.',
                   'Bind exact reference pixels and related-scene identity; do not invent a matching house or product.',
                   'Prepare and critically assess the proposal before recording its scene contract.'],
       'outputReviewChecks':policy['checks'],'canSpend':False,'outputQualityApproved':False,
       'newProviderCalls':0,'existingSavedBriefChanged':False}
