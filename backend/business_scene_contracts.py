"""Internal reviewed-scene admission. No provider calls or output-quality approval.

Contracts bind exact requests to source evidence and reviewed reference bytes.
Credit envelopes span the same website in ONE local database, not other workers
or tenants. Internal review/rights references are attestations, not AI truth.
"""
from __future__ import annotations
import base64,binascii,hashlib,io,json,re,sqlite3,time,uuid
from urllib.parse import urlsplit
from PIL import Image
import business_marketing_drafts as drafts
import business_creative_learning as learning
import business_creative_preflight as preflight

POLICY_VERSION=1
LEGACY_TABLES=('runway_image_jobs','runway_video_jobs','runway_cinematic_shots','business_paid_video_tests')
SCENE_FIELDS={'sceneId','purpose','customerAction','sourceFactIndices','origin','useAsProof',
              'peoplePolicy','expectedAction','failureChecks','referenceIds','continuity'}

class ContractError(ValueError):
    def __init__(self,message,code='scene_contract_invalid',status=403):
        super().__init__(message);self.code=code;self.status=status

def _json(value):
    try:return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    except (ValueError,TypeError) as exc:raise ContractError('Scene data is not valid bounded JSON') from exc

def _hash(value):return hashlib.sha256(_json(value).encode()).hexdigest()

def _text(value,label,low=12,high=500):
    if not isinstance(value,str) or not low<=len(value.strip())<=high or '\x00' in value:
        raise ContractError('Missing or invalid '+label)
    return value.strip()

def _id(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_-]{1,120}',value):raise ContractError('Invalid scene/reference identifier')
    return value

def _cost(value):
    if type(value) is not int or not 1<=value<=1000:raise ContractError('A bounded integer credit amount is required')
    return value

def _scope(document):
    try:
        url=urlsplit(document['sourceUrl']);host=url.hostname.encode('idna').decode('ascii').lower().rstrip('.').removeprefix('www.')
        if url.scheme!='https' or '.' not in host or url.username or url.password or url.port not in (None,443):raise ValueError()
    except (ValueError,KeyError,AttributeError,TypeError,UnicodeError) as exc:
        raise ContractError('A canonical business website scope is required','business_scope_required') from exc
    return host

def _policy():
    # Any lesson or preflight-policy update invalidates previously reviewed inputs.
    library=learning.rubric({})['librarySha256']
    return _hash([POLICY_VERSION,preflight.POLICY_VERSION,library])

def _saved(con,draft_id,revision=None):
    saved=drafts.read_draft(con,draft_id)
    if revision is not None and (type(revision) is not int or saved['revision']!=revision):
        raise ContractError('Scene belongs to a different campaign revision','scene_contract_changed',409)
    return saved

def _begin(con):
    if con.in_transaction:raise ContractError('Internal preparation requires its own transaction')
    con.execute('BEGIN IMMEDIATE')

def initialise(con):
    con.executescript('''
      CREATE TABLE IF NOT EXISTS business_campaign_envelopes(
        scope TEXT PRIMARY KEY,maximum_credits INTEGER NOT NULL,legacy_reserved INTEGER NOT NULL,
        approval_reference TEXT NOT NULL,created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS business_scene_references(
        id TEXT PRIMARY KEY,scope TEXT NOT NULL,sha256 TEXT NOT NULL,identity_root TEXT NOT NULL,
        parent_id TEXT,origin TEXT NOT NULL,rights_reference TEXT NOT NULL,reviewer_reference TEXT NOT NULL,
        fingerprint TEXT NOT NULL,created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS business_scene_continuity(
        scope TEXT NOT NULL,group_id TEXT NOT NULL,identity_root TEXT NOT NULL,PRIMARY KEY(scope,group_id));
      CREATE TABLE IF NOT EXISTS business_scene_contracts(
        id TEXT PRIMARY KEY,scope TEXT NOT NULL,draft_id TEXT NOT NULL,revision INTEGER NOT NULL,
        scene_id TEXT NOT NULL,scene_json TEXT NOT NULL,request_sha TEXT NOT NULL,source_sha TEXT NOT NULL,
        policy_sha TEXT NOT NULL,credits INTEGER NOT NULL,identity_root TEXT,reference_sha TEXT NOT NULL,
        reviewer_reference TEXT NOT NULL,fingerprint TEXT NOT NULL,created REAL NOT NULL,
        UNIQUE(scope,scene_id),UNIQUE(draft_id,revision,request_sha));
      CREATE TABLE IF NOT EXISTS business_scene_preparation_reviews(
        contract_id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,proposal_sha TEXT NOT NULL,
        review_json TEXT NOT NULL,sha256 TEXT NOT NULL,created REAL NOT NULL,
        UNIQUE(draft_id,proposal_sha));
      CREATE TABLE IF NOT EXISTS business_scene_reservations(
        contract_id TEXT PRIMARY KEY,scope TEXT NOT NULL,job_id TEXT UNIQUE NOT NULL,
        credits INTEGER NOT NULL,created REAL NOT NULL);
    ''')

def open_envelope(con,draft_id,*,maximum_credits,approval_reference):
    """Record a bounded internal authority; never reset an existing envelope."""
    limit=_cost(maximum_credits);authority=_text(approval_reference,'budget authority',12,200)
    _begin(con)
    try:
        scope=_scope(_saved(con,draft_id)['document'])
        previous=con.execute('SELECT * FROM business_campaign_envelopes WHERE scope=?',(scope,)).fetchone()
        if previous:
            if previous['maximum_credits']!=limit or previous['approval_reference']!=authority:
                raise ContractError('Existing campaign allowance cannot be reset or topped up','budget_envelope_immutable')
            con.commit()
            return {'scope':scope,'maximumCredits':limit,'legacyReservedCredits':previous['legacy_reserved']}
        # Preserve historical reservations from ALL old media ledgers, including
        # uncertain/rejected attempts. Never assume a provider refunded a charge.
        same=[]
        for row in con.execute('SELECT id,document_json FROM marketing_drafts'):
            try:matches=_scope(json.loads(row['document_json']))==scope
            except (ContractError,ValueError,TypeError):matches=False
            if matches:same.append(row['id'])
        total=0
        tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in LEGACY_TABLES:
            if table in tables:
                for row in con.execute('SELECT draft_id,reserved_credits FROM '+table):
                    if row['draft_id'] in same:
                        if type(row['reserved_credits']) is not int or row['reserved_credits']<0:raise ContractError('Legacy cost requires reconciliation')
                        total+=row['reserved_credits']
        con.execute('INSERT INTO business_campaign_envelopes VALUES(?,?,?,?,?)',(scope,limit,total,authority,time.time()))
        con.commit();return {'scope':scope,'maximumCredits':limit,'legacyReservedCredits':total}
    except BaseException:con.rollback();raise

def _image_digest(uri):
    if not isinstance(uri,str) or len(uri)>6_000_000:raise ContractError('Reference must contain bounded provider-ready bytes')
    match=re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)',uri)
    if not match:raise ContractError('A URL or claimed hash is not verified reference bytes','reference_bytes_required')
    try:
        data=base64.b64decode(match[2],validate=True)
        if not 100<=len(data)<=4_000_000:raise ValueError()
        with Image.open(io.BytesIO(data)) as image:
            if image.format!={'png':'PNG','jpeg':'JPEG','webp':'WEBP'}[match[1]] or min(image.size)<64 or image.width*image.height>20_000_000:raise ValueError()
            image.verify()
    except (ValueError,OSError,binascii.Error,Image.DecompressionBombError) as exc:raise ContractError('Invalid provider-ready reference image') from exc
    return hashlib.sha256(data).hexdigest()

def register_reference(con,draft_id,reference_id,provider_image,*,origin,rights_reference,reviewer_reference,parent_reference_id=None):
    """Internal attestation after reviewing source/derivative; no model or upload."""
    ident=_id(reference_id);digest=_image_digest(provider_image)
    if origin not in ('illustrative_ai','owner_asset','licensed_asset'):raise ContractError('Reference origin required')
    rights=_text(rights_reference,'reference rights',12,200);reviewer=_text(reviewer_reference,'reference review',12,200)
    _begin(con)
    try:
        scope=_scope(_saved(con,draft_id)['document']);root=ident
        if parent_reference_id is not None:
            _id(parent_reference_id)
            if ident==parent_reference_id:raise ContractError('Reference cannot be its own parent')
            parent=con.execute('SELECT * FROM business_scene_references WHERE id=? AND scope=?',(parent_reference_id,scope)).fetchone()
            if not parent:raise ContractError('Reference parent is absent or belongs to another business')
            root=parent['identity_root']
        fingerprint=_hash([scope,digest,root,parent_reference_id,origin,rights,reviewer])
        old=con.execute('SELECT * FROM business_scene_references WHERE id=?',(ident,)).fetchone()
        if old:
            if old['fingerprint']!=fingerprint:raise ContractError('Reviewed reference is immutable','reference_changed')
        else:
            con.execute('INSERT INTO business_scene_references VALUES(?,?,?,?,?,?,?,?,?,?)',
                (ident,scope,digest,root,parent_reference_id,origin,rights,reviewer,fingerprint,time.time()))
        con.commit();return {'id':ident,'sha256':digest,'identityRoot':root,'visualIdentityProven':False}
    except BaseException:con.rollback();raise

def _request(request):
    if not isinstance(request,dict):raise ContractError('Exact provider request required')
    _text(request.get('model'),'provider model',3,100)
    _text(request.get('ratio'),'output ratio',3,30)
    prompt=_text(request.get('promptText'),'scene prompt',100,6000)
    if 'duration' in request:
        if type(request['duration']) is not int or not 1<=request['duration']<=10 or len(prompt)>1000:
            raise ContractError('Video parameters exceed the verified local adapter limits','invalid_provider_parameters')
    elif type(request.get('outputCount')) is not int or request['outputCount']!=1:
        raise ContractError('Exactly one image per reviewed request is required')
    if 'referenceImages' in request:raise ContractError('This reference transport is not implemented in the local adapter')
    actual=[]
    if 'promptImage' in request:actual=[_image_digest(request['promptImage'])]
    return _hash(request),actual

def _validate(con,saved,scene,request,credits):
    cost=_cost(credits);request_sha,actual_refs=_request(request);doc=saved['document'];scope=_scope(doc)
    if not isinstance(scene,dict) or set(scene)!=SCENE_FIELDS:raise ContractError('A complete structured scene is required')
    _id(scene['sceneId'])
    for field in ('purpose','customerAction','expectedAction'):_text(scene[field],field)
    if scene['origin']!='illustrative_ai' or scene['useAsProof'] is not False:
        raise ContractError('Generated media cannot be submitted as actual business work or results','synthetic_proof_forbidden')
    # Metadata cannot excuse explicit conflicting claims in the actual prompt.
    # This is a conservative lexical check, not semantic/visual verification.
    text=re.sub(r'(?<!do )\bnot (?:a |an |the )?', 'no ', request['promptText'], flags=re.I)
    actual=r'(?:(?:actual|real|genuine)\s+(?:customers?|clients?|staff|employees?|premises|completed\s+(?:jobs?|work)|results)|our\s+completed\s+(?:jobs?|work))'
    # A bounded negative claim clause is not a claim. Stop at a positive
    # pivot so 'never claim X, but show actual staff' still fails.
    clause=r'\b(?:never|do not)\s+(?:imply|claim|represent)\b(?:(?!\b(?:but|also|however|then|instead)\b|\band\s+(?:show|depict|include|use|present)\b)[^.!?;]){0,220}'
    claim_text=re.sub(clause,' ',text,flags=re.I)
    if preflight.positive_mentions(claim_text,actual):
        raise ContractError('Prompt presents generated material as actual business proof','synthetic_proof_forbidden')
    linked=r'(?:same\s+(?:roof|house|property|product|vehicle|room|building|person|subject|location)|before(?:[- /]and[- /]|[- /])after)'
    if scene['continuity'] is None and preflight.positive_mentions(text,linked):
        raise ContractError('Matching-scene instructions need an explicit referenced continuity plan','continuity_reference_required')
    if scene['peoplePolicy'] not in ('none','illustrative_only'):raise ContractError('Explicit people policy required')
    if scene['peoplePolicy']=='none' and preflight.positive_mentions(request['promptText'],preflight.HUMANS):
        raise ContractError('Prompt conflicts with the no-people scene policy','scene_people_conflict')
    checks=scene['failureChecks']
    if not isinstance(checks,list) or not 2<=len(checks)<=12:raise ContractError('Observable failure checks required')
    for item in checks:_text(item,'failure check',12,400)
    facts=doc.get('observedFacts') or [];indices=scene['sourceFactIndices']
    if not isinstance(indices,list) or not 1<=len(indices)<=6 or any(type(i) is not int or not 0<=i<len(facts) for i in indices) or len(set(indices))!=len(indices):
        raise ContractError('Scene must point to saved business evidence','scene_evidence_required')
    for i in indices:_text(facts[i],'saved evidence',12,2000)
    ref_ids=scene['referenceIds']
    if not isinstance(ref_ids,list) or len(ref_ids)>1 or any(not isinstance(x,str) for x in ref_ids) or len(set(ref_ids))!=len(ref_ids):
        raise ContractError('Invalid reference assignment')
    refs=[]
    for ident in ref_ids:
        _id(ident)
        row=con.execute('SELECT * FROM business_scene_references WHERE id=? AND scope=?',(ident,scope)).fetchone()
        if not row:raise ContractError('Unreviewed or foreign reference','reference_unverified')
        fingerprint=_hash([row['scope'],row['sha256'],row['identity_root'],row['parent_id'],row['origin'],row['rights_reference'],row['reviewer_reference']])
        if fingerprint!=row['fingerprint']:raise ContractError('Reference record changed','reference_changed')
        refs.append(row)
    continuity=scene['continuity'];root=refs[0]['identity_root'] if refs else None
    if continuity is not None:
        if not isinstance(continuity,dict) or set(continuity)!={'groupId','previousSceneId'}:raise ContractError('Invalid continuity relationship')
        _id(continuity['groupId'])
        if not refs or not actual_refs:raise ContractError('Continuous identity requires an actual reviewed provider reference','continuity_reference_required')
        group=con.execute('SELECT identity_root FROM business_scene_continuity WHERE scope=? AND group_id=?',(scope,continuity['groupId'])).fetchone()
        if group and group['identity_root']!=root:raise ContractError('Scenes use unrelated identities','continuity_identity_mismatch')
        previous=continuity['previousSceneId']
        if previous is not None:
            _id(previous)
            if previous==scene['sceneId']:raise ContractError('Scene cannot continue itself')
            parent=con.execute('SELECT scene_json,identity_root FROM business_scene_contracts WHERE scope=? AND scene_id=?',(scope,previous)).fetchone()
            if not parent:raise ContractError('Previous continuity scene has not been reviewed')
            before=json.loads(parent['scene_json']).get('continuity')
            if not before or before['groupId']!=continuity['groupId'] or parent['identity_root']!=root:
                raise ContractError('Previous scene uses an unrelated identity','continuity_identity_mismatch')
    if [ref['sha256'] for ref in refs]!=actual_refs:raise ContractError('Provider reference differs from reviewed image','reference_changed')
    envelope=con.execute('SELECT * FROM business_campaign_envelopes WHERE scope=?',(scope,)).fetchone()
    if not envelope:raise ContractError('No shared campaign envelope was recorded','campaign_envelope_required')
    if cost>envelope['maximum_credits']:raise ContractError('Scene exceeds the campaign envelope','campaign_budget_exceeded')
    values={'scope':scope,'draft_id':saved['id'],'revision':saved['revision'],'scene_id':scene['sceneId'],
        'scene_json':_json(scene),'request_sha':request_sha,'source_sha':_hash(doc),'policy_sha':_policy(),
        'credits':cost,'identity_root':root,'reference_sha':_hash([ref['fingerprint'] for ref in refs])}
    return values

def _public(row):
    return {'id':row['id'],'scope':row['scope'],'sceneId':row['scene_id'],'requestSha256':row['request_sha'],
        'fingerprint':row['fingerprint'],'identityRoot':row['identity_root'],'estimatedCredits':row['credits'],
        'spendAuthorised':False,'visualQualityVerified':False,'approvedForPublishing':False}

def record(con,draft_id,revision,scene,request,credits,*,reviewer_reference,preparation_review=None):
    """Internal reviewed plan, not an owner publishing or spending approval."""
    reviewer=_text(reviewer_reference,'scene reviewer',12,200)
    review_json=None
    if preparation_review is not None:
        if (not isinstance(preparation_review,dict) or preparation_review.get('draftId')!=draft_id or
            preparation_review.get('revision')!=revision or preparation_review.get('outputQualityApproved') is not False or
            not re.fullmatch('[0-9a-f]{64}',str(preparation_review.get('proposalFingerprint','')))):
            raise ContractError('Invalid preparation review evidence')
        review_json=_json(preparation_review)
        if len(review_json)>16000 or reviewer!='preparation-review:'+_hash(preparation_review):
            raise ContractError('Preparation review is not bound to this reviewer record')
    _begin(con)
    try:
        values=_validate(con,_saved(con,draft_id,revision),scene,request,credits)
        if preparation_review is not None and (preparation_review.get('sourceSha256')!=values['source_sha'] or
                                              preparation_review.get('policyFingerprint')!=values['policy_sha']):
            raise ContractError('Prepared source or policy changed before the contract write','scene_contract_changed',409)
        fingerprint=_hash({**values,'reviewer_reference':reviewer})
        previous=con.execute('SELECT * FROM business_scene_contracts WHERE (scope=? AND scene_id=?) OR (draft_id=? AND revision=? AND request_sha=?)',
            (values['scope'],values['scene_id'],draft_id,revision,values['request_sha'])).fetchall()
        if previous:
            if len(previous)!=1 or previous[0]['fingerprint']!=fingerprint:raise ContractError('Reviewed scene cannot be overwritten','scene_contract_changed',409)
            if review_json is not None:
                recorded=con.execute('SELECT review_json FROM business_scene_preparation_reviews WHERE contract_id=?',(previous[0]['id'],)).fetchone()
                if not recorded or recorded['review_json']!=review_json:raise ContractError('Preparation review changed or missing')
            con.commit();return _public(previous[0])
        ident=uuid.uuid4().hex
        values.update(id=ident,reviewer_reference=reviewer,fingerprint=fingerprint,created=time.time())
        columns=','.join(values);marks=','.join('?' for _ in values)
        con.execute('INSERT INTO business_scene_contracts('+columns+') VALUES('+marks+')',tuple(values.values()))
        if review_json is not None:
            con.execute('INSERT INTO business_scene_preparation_reviews VALUES(?,?,?,?,?,?)',
                (ident,draft_id,preparation_review['proposalFingerprint'],review_json,_hash(preparation_review),time.time()))
        if scene['continuity']:
            con.execute('INSERT OR IGNORE INTO business_scene_continuity VALUES(?,?,?)',
                (values['scope'],scene['continuity']['groupId'],values['identity_root']))
        con.commit();return _public(values)
    except BaseException:con.rollback();raise

def check(con,draft_id,revision,request,credits):
    """Read-only: exact plan, policy, evidence and outgoing references must match."""
    saved=_saved(con,draft_id,revision);request_sha,_=_request(request)
    try:
        row=con.execute('SELECT * FROM business_scene_contracts WHERE draft_id=? AND revision=? AND request_sha=?',
            (draft_id,revision,request_sha)).fetchone()
    except sqlite3.OperationalError as exc:raise ContractError('Reviewed scene contract required','scene_contract_required') from exc
    if not row:raise ContractError('Reviewed scene contract required before generation','scene_contract_required')
    try:scene=json.loads(row['scene_json'])
    except (ValueError,TypeError) as exc:raise ContractError('Scene record is corrupt','scene_contract_changed') from exc
    current=_validate(con,saved,scene,request,credits)
    if _hash({**current,'reviewer_reference':row['reviewer_reference']})!=row['fingerprint']:
        raise ContractError('Evidence, request or creative policy changed','scene_contract_changed',409)
    return _public(row)

def reserve(con,draft_id,revision,request,credits,job_id):
    """Called within the SAME write transaction as the actual provider-job row."""
    if not con.in_transaction:raise ContractError('Atomic job transaction required','reservation_transaction_required')
    _id(job_id);contract=check(con,draft_id,revision,request,credits)
    previous=con.execute('SELECT * FROM business_scene_reservations WHERE contract_id=? OR job_id=?',(contract['id'],job_id)).fetchall()
    if previous:
        if len(previous)!=1 or previous[0]['contract_id']!=contract['id'] or previous[0]['job_id']!=job_id:
            raise ContractError('Scene has already reserved a generation attempt','scene_attempt_already_reserved')
        return {'contractId':contract['id'],'jobId':job_id,'reservedCredits':credits}
    envelope=con.execute('SELECT * FROM business_campaign_envelopes WHERE scope=?',(contract['scope'],)).fetchone()
    used=con.execute('SELECT COALESCE(SUM(credits),0) FROM business_scene_reservations WHERE scope=?',(contract['scope'],)).fetchone()[0]
    if used+envelope['legacy_reserved']+credits>envelope['maximum_credits']:
        raise ContractError('Shared campaign credit limit exceeded','campaign_budget_exceeded')
    con.execute('INSERT INTO business_scene_reservations VALUES(?,?,?,?,?)',(contract['id'],contract['scope'],job_id,credits,time.time()))
    return {'contractId':contract['id'],'jobId':job_id,'reservedCredits':credits}

def status(con,draft_id,revision,request,credits):
    try:return {'ready':True,**check(con,draft_id,revision,request,credits)}
    except ContractError as exc:return {'ready':False,'code':exc.code,'message':str(exc),'spendAuthorised':False}
