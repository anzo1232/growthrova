"""Explicit OFFLINE reviewed-scene fixtures. Never imported by product code.

These records only exercise admission mechanics. They do not claim real creative
review, actual business evidence, paid authority or client asset usage rights.
"""
import hashlib,json
import business_marketing_drafts as drafts
import business_scene_contracts as contracts

AUTHORITY='offline-fixture-budget-no-paid-provider'

def seed(con,draft_id,request,credits,*,revision=None):
    saved=drafts.read_draft(con,draft_id);revision=revision or saved['revision']
    contracts.open_envelope(con,draft_id,maximum_credits=1000,approval_reference=AUTHORITY)
    ident='fixture-'+hashlib.sha256(json.dumps([draft_id,revision,request],sort_keys=True).encode()).hexdigest()[:32]
    refs=[]
    if 'promptImage' in request:
        reference=ident+'-image'
        contracts.register_reference(con,draft_id,reference,request['promptImage'],origin='illustrative_ai',
            rights_reference='synthetic-test-fixture-no-client-material',reviewer_reference='offline-test-not-visual-acceptance')
        refs=[reference]
    spec={'sceneId':ident,'purpose':'Exercise exact reviewed scene admission with a fake provider',
        'customerAction':'Check the documented business enquiry route',
        'sourceFactIndices':[next(i for i,fact in enumerate(saved['document']['observedFacts']) if isinstance(fact,str) and len(fact.strip())>=12)],'origin':'illustrative_ai','useAsProof':False,'peoplePolicy':'illustrative_only',
        'expectedAction':'The reviewed test subject is shown without representing actual client work.',
        'failureChecks':['Reject physical distortions in actual output review.','Reject unsupported claims and identity changes.'],
        'referenceIds':refs,'continuity':None}
    return contracts.record(con,draft_id,revision,spec,request,credits,reviewer_reference='offline-scene-fixture-not-art-approval')

def seed_image(con,draft_id,cid='creative-1'):
    import business_runway as api
    saved=drafts.read_draft(con,draft_id)
    return seed(con,draft_id,api._recipe(saved['document'],cid),api.IMAGE_CREDITS)

def seed_video(con,draft_id,path):
    import business_runway_video as api
    _,request=api.prepare_request(path)
    return seed(con,draft_id,request,api.CREDITS)

def seed_cinema(con,draft_id,key):
    import business_cinematic_video as api
    request={'model':api.MODEL,'duration':api.DURATION,'ratio':'720:1280','promptText':api.SHOTS[key][1]}
    return seed(con,draft_id,request,api.CREDITS)

def seed_reel(con,project,slot):
    import business_reel_provider_bridge as api
    quote=api.quote(con,project,slot)
    request={'model':quote['model'],'duration':quote['durationSeconds'],'ratio':quote['ratio'],'promptText':quote['promptText']}
    return seed(con,quote['draftId'],request,quote['estimatedCredits'])
