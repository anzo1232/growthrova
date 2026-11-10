"""Read-only customer-facing handoff for research -> plan -> creative approval.

Not a live autonomous marketing manager. No media creation, account changes,
publishing, paid calls, approval writes or implied performance measurements.
"""
import business_marketing_drafts as drafts
import business_offer_research as research
import business_scene_contracts as contracts

class JourneyError(ValueError): pass

def prepare(con,draft_id,revision,dossier,*,as_of):
    """Join existing real draft/planning evidence and reference holds."""
    try:
        saved=contracts._saved(con,draft_id,revision)
        report=research.compose_preproduction(con,draft_id,revision,dossier,
                    as_of=as_of,reference_pools={})
    except (contracts.ContractError,drafts.MarketingDraftError,research.ResearchError) as exc:
        raise JourneyError(str(exc)) from exc
    doc=saved['document']
    items=[]
    for candidate in report['candidates']:
        stage=candidate['preproduction']
        blockers=list(dict.fromkeys(candidate['blockers']+stage['blockers']))
        items.append({'id':candidate['id'],
           'status':'blocked_by_research' if candidate['intent'] is None else 'held_for_reference_and_review',
           'sourceFactIndices':candidate['sourceFactIndices'],
           'businessSourceId':candidate['businessSourceId'],
           'researchWarnings':candidate['warnings'],
           'blockers':blockers,
           'mode':stage['mode'],
           'conceptPrepared':candidate['intent'] is not None,
           'mediaGenerated':False,'qualityApproved':False,'ownerApproved':False,
           'publishApproved':False})
    need_research=any(i['status']=='blocked_by_research' for i in items)
    return {'version':1,'business':doc['business'],'draftId':draft_id,'revision':revision,
        'documentSha256':report['documentSha256'],'researchFingerprint':report['fingerprint'],
        'research':{'status':report['status'],'sources':report['researchSnapshot'],
                    'verified':False,'buyerDemandProven':False},
        'marketingPlan':{'goal':doc['goal'],
            'postCount':len(doc.get('posts') or []),
            'creativeConceptCount':len(doc.get('creatives') or []),
            'draftOnly':True,'scheduledCount':0,
            'performanceMeasured':False},
        'creativeQueue':items,
        'nextOwnerAction':'resolve_business_evidence' if need_research else 'provide_authentic_assets',
        'needsOwnerApproval':True,'resultsVerified':False,
        'paidGeneration':{'allowed':False,'creditsReserved':0},
        'publishing':{'allowed':False,'scheduled':False},
        'externalRequests':0,'providerCalls':0,
        'limitations':['Existing source excerpts are not independently verified.',
                       'Creative proposals are not completed media.',
                       'Owner review and actual delivery remain separate required stages.']}
