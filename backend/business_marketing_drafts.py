"""Durable marketing documents in the existing loopback-only pilot database.

No cloud identity, media generation, publishing or spending authority lives here.
Mutations use a document revision and a stable operation ID for lost acknowledgements.
"""
from __future__ import annotations
import hashlib,json,re,time
from datetime import date
from urllib.parse import urlsplit
from pathlib import Path
from business_brand_render import HEX as BRAND_HEX, TEMPLATES as BRAND_STYLES

_COPY_RULES = json.loads((Path(__file__).parent / 'src/lib/businessCopyReadiness.json').read_text(encoding='utf-8'))

PLACEHOLDER_WORDING = re.compile(
    r'\b(?:lorem ipsum|insert here|insert your|your business|placeholder|todo|tbd)\b|\[[^\]]+\]|\{[^}]+\}', re.I)

def marketing_copy_issue(item, business):
    """Complete captions and their graphic wording have different editorial roles."""
    return _marketing_wording_issue(item, business, graphic=False)


def marketing_graphic_issue(item, business):
    """Questions can be headlines; this does not approve claims or creative quality."""
    return _marketing_wording_issue(item, business, graphic=True)


def _marketing_wording_issue(item, business, *, graphic):
    """Basic shared checks, without treating a headline as a whole caption."""
    copy = item.get('copyDraft', '').strip()
    normalise = lambda text: ' '.join(text.split()).lower()
    messages = _COPY_RULES['messages']
    if len(copy) < 3 or normalise(copy) == normalise(business):
        return messages['unwritten']
    if any(line.strip().lower().startswith(prefix) for line in copy.splitlines()
           for prefix in _COPY_RULES['internalLinePrefixes']):
        return messages['notes']
    if not graphic and re.fullmatch(r'(?:[^.!?]+\?\s*)+', copy):
        return messages['question']
    if re.fullmatch(r'[“"][^“”"]+[”"]\s*[.!]?', copy):
        return messages['quotation']
    if not item.get('callToAction', '').strip():
        return messages['cta']
    for field in ('graphicText', 'supportingLine'):
        if item.get(field, '').strip():
            issue = marketing_graphic_issue(dict(copyDraft=item[field],callToAction=item.get('callToAction','')), business)
            if issue:
                return issue
    return ''

class MarketingDraftError(ValueError):
    def __init__(self,message,code='invalid_marketing_draft',status=400):
        super().__init__(message);self.code=code;self.status=status

def _text(value,name,limit,required=False):
    if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):
        raise MarketingDraftError(f'Invalid {name}')
    return value

def _id(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{32}',value):
        raise MarketingDraftError('Invalid draft or save identifier')
    return value

def _campaign_brand(value):
    """Preserve explicit palette drafts; readability and media approval are separate."""
    fields={'name','primary_color','secondary_color','font_style'}
    if not isinstance(value,dict) or set(value)!=fields:
        raise MarketingDraftError('Use only the campaign brand name, colours and typography')
    name=_text(value['name'],'brand name',38)
    if any(not char.isprintable() for char in name):
        raise MarketingDraftError('Use a single-line brand name')
    for field in ('primary_color','secondary_color'):
        colour=value[field]
        if not isinstance(colour,str) or (colour and not BRAND_HEX.fullmatch(colour)):
            raise MarketingDraftError('Enter brand colours as six-digit hex values, such as #123ABC')
    if not isinstance(value['font_style'],str) or value['font_style'] not in BRAND_STYLES|{''}:
        raise MarketingDraftError('Choose one of the supported brand typography styles')
    return dict(value)


def _brand_identity(value, expected_url):
    fields={'status','sourceUrl','capturedAt','method','roles','colours','fontFamilies','logoCandidates','suggestedBrandKit'}
    if not isinstance(value,dict) or set(value)!=fields or value.get('status')!='website_observed_unconfirmed' or value.get('method')!='rendered_computed_styles':
        raise MarketingDraftError('Invalid website visual identity')
    source=_text(value['sourceUrl'],'visual identity source',512,True)
    try:
        parsed=urlsplit(source)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError()
    except ValueError:
        raise MarketingDraftError('Invalid website visual identity source') from None
    if source!=expected_url:
        raise MarketingDraftError('Website visual identity must match the campaign website')
    captured=_text(value['capturedAt'],'visual identity capture time',48)
    roles=value['roles']
    if not isinstance(roles,dict) or set(roles)!={'background','text','accent'}:
        raise MarketingDraftError('Invalid website colour roles')
    clean_roles={}
    for key,colour in roles.items():
        if not isinstance(colour,str) or (colour and not BRAND_HEX.fullmatch(colour)):
            raise MarketingDraftError('Invalid website colour role')
        clean_roles[key]=colour.upper()
    colours=value['colours']
    if not isinstance(colours,list) or len(colours)>12:
        raise MarketingDraftError('Invalid website colour evidence')
    clean_colours=[];seen=set()
    for item in colours:
        if (not isinstance(item,dict) or set(item)!={'hex','count'} or not isinstance(item['hex'],str)
                or not BRAND_HEX.fullmatch(item['hex']) or type(item['count']) is not int
                or not 1<=item['count']<=10000 or item['hex'].upper() in seen):
            raise MarketingDraftError('Invalid website colour evidence')
        seen.add(item['hex'].upper());clean_colours.append({'hex':item['hex'].upper(),'count':item['count']})
    fonts=value['fontFamilies']
    if not isinstance(fonts,list) or len(fonts)>6:
        raise MarketingDraftError('Invalid website typography evidence')
    clean_fonts=[]
    for item in fonts:
        if (not isinstance(item,dict) or set(item)!={'family','count'} or type(item['count']) is not int
                or not 1<=item['count']<=10000):
            raise MarketingDraftError('Invalid website typography evidence')
        clean_fonts.append({'family':_text(item['family'],'website font family',80,True),'count':item['count']})
    logos=value['logoCandidates']
    if not isinstance(logos,list) or len(logos)>4:
        raise MarketingDraftError('Invalid website logo evidence')
    clean_logos=[]
    for item in logos:
        if not isinstance(item,dict) or item.get('kind') not in ('image_url','inline_svg'):
            raise MarketingDraftError('Invalid website logo evidence')
        description=_text(item.get('description',''),'website logo description',120,True)
        if item['kind']=='image_url':
            if set(item)!={'kind','url','description'}:raise MarketingDraftError('Invalid website logo evidence')
            candidate=_text(item['url'],'website logo URL',512,True)
            try:
                parsed=urlsplit(candidate)
                if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                    raise ValueError()
            except ValueError:
                raise MarketingDraftError('Invalid website logo URL') from None
            clean_logos.append({'kind':'image_url','url':candidate,'description':description})
        else:
            if (set(item)!={'kind','svg','sha256','description'} or not re.fullmatch('[0-9a-f]{64}',str(item.get('sha256','')))
                    or not isinstance(item.get('svg'),str) or not item['svg'].startswith('<svg')
                    or len(item['svg'].encode())>32768):
                raise MarketingDraftError('Invalid website logo candidate')
            clean_logos.append({'kind':'inline_svg','svg':item['svg'],'sha256':item['sha256'],'description':description})
    suggested=value['suggestedBrandKit']
    if not isinstance(suggested,dict) or set(suggested)!={'primary_color','secondary_color','font_style'}:
        raise MarketingDraftError('Invalid suggested website brand')
    for key in ('primary_color','secondary_color'):
        if not isinstance(suggested[key],str) or not BRAND_HEX.fullmatch(suggested[key]):
            raise MarketingDraftError('Invalid suggested website brand colour')
    if suggested['font_style'] not in BRAND_STYLES:
        raise MarketingDraftError('Invalid suggested website typography')
    return {'status':'website_observed_unconfirmed','sourceUrl':source,'capturedAt':captured,
            'method':'rendered_computed_styles','roles':clean_roles,'colours':clean_colours,
            'fontFamilies':clean_fonts,'logoCandidates':clean_logos,
            'suggestedBrandKit':{'primary_color':suggested['primary_color'].upper(),
              'secondary_color':suggested['secondary_color'].upper(),'font_style':suggested['font_style']}}

def initialise(con):
    con.executescript('''
      CREATE TABLE IF NOT EXISTS marketing_drafts(
        id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
        document_json TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS marketing_draft_mutations(
        draft_id TEXT NOT NULL, mutation_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL, result_revision INTEGER NOT NULL,
        PRIMARY KEY(draft_id,mutation_id));
    ''')

def normalise_document(value,previous=None,*,_validate_organic_references=True):
    if not isinstance(value,dict) or value.get('version')!=1:
        raise MarketingDraftError('Unsupported marketing document')
    result={k:_text(value.get(k,''),k,n,True) for k,n in [('name',120),('business',120),('goal',40)]}
    if result['goal'] not in {'awareness','enquiries','bookings','education','offers'}:
        raise MarketingDraftError('Unknown marketing objective')
    url=_text(value.get('sourceUrl',''),'source URL',512)
    if url:
        try:
            parsed=urlsplit(url)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or any(ord(c)<33 for c in url):
                raise ValueError()
        except ValueError:raise MarketingDraftError('Use an HTTPS source reference') from None
    calendar_start=_text(value.get('calendarStartDate',''),'calendar start date',10)
    if calendar_start:
        if not re.fullmatch(r'20[2-8][0-9]-[01][0-9]-[0-3][0-9]',calendar_start):
            raise MarketingDraftError('Choose a valid starting day for your posts')
        try:date.fromisoformat(calendar_start)
        except ValueError:raise MarketingDraftError('Invalid starting date for your posts') from None
    facts=value.get('observedFacts',[])
    if not isinstance(facts,list) or len(facts)>40:raise MarketingDraftError('Too many evidence entries')
    # Optional for historical campaigns. Preserve exact page provenance for each
    # new observation; never infer it from a merged homepage or a keyword.
    fact_sources=None
    if 'observedFactSources' in value:
        raw_sources=value['observedFactSources']
        if not isinstance(raw_sources,list) or len(raw_sources)!=len(facts):
            raise MarketingDraftError('Each observation needs its original page reference')
        fact_sources=[]
        base=urlsplit(url)
        for raw_source in raw_sources:
            source=_text(raw_source,'observation page URL',512,True)
            try:
                page=urlsplit(source)
                if (page.scheme!='https' or not page.hostname or page.hostname!=base.hostname or
                    (page.port or 443)!=(base.port or 443) or page.username or page.password or page.fragment or
                    any(ord(c)<33 or ord(c)==127 for c in source) or '\\' in source):
                    raise ValueError()
            except ValueError:
                raise MarketingDraftError('Observation page must be a safe HTTPS reference on the source site') from None
            fact_sources.append(source)
    images=value.get('websiteImages',[])
    if not isinstance(images,list) or len(images)>8:raise MarketingDraftError('Invalid website image references')
    clean_images=[]
    for image in images:
        if not isinstance(image,dict):raise MarketingDraftError('Invalid website image reference')
        image_url=_text(image.get('url',''),'website image URL',512,True)
        try:
            parsed=urlsplit(image_url)
            base=urlsplit(url)
            if (parsed.scheme!='https' or parsed.hostname!=base.hostname or parsed.username or parsed.password or
                parsed.port not in (None,443) or parsed.fragment or not parsed.path or not parsed.netloc):
                raise ValueError()
        except ValueError:raise MarketingDraftError('Unsafe website image reference') from None
        if image_url not in {x['url'] for x in clean_images}:
            clean_images.append({'url':image_url,'alt':_text(image.get('alt',''),'image description',160),
                'rights_confirmed':False,'authenticity_verified':False})
    # Save only bounded source-linked planning context. This cannot grant
    # media usage, generation, publishing or an owner approval status.
    raw_shortlist=value.get('editorialShortlist')
    clean_shortlist=None
    if raw_shortlist is not None:
        if not isinstance(raw_shortlist,dict) or raw_shortlist.get('status') not in (
          'three_directions_ready_for_asset_intake','blocked_insufficient_unique_brand_evidence'):
            raise MarketingDraftError('Invalid editorial shortlist')
        candidates=raw_shortlist.get('candidates',[])
        if not isinstance(candidates,list) or len(candidates)>3:
            raise MarketingDraftError('Only three editorial concepts may be prepared before more research')
        seen=set();clean=[]
        for candidate in candidates:
            if not isinstance(candidate,dict):
                raise MarketingDraftError('Invalid editorial concept')
            ident=_text(candidate.get('id',''),'concept id',32,True)
            if ident in seen or not re.fullmatch(r'[a-z0-9_-]{1,32}',ident):
                raise MarketingDraftError('Duplicate or invalid editorial concept')
            seen.add(ident)
            evidence=candidate.get('evidence') or {}
            if not isinstance(evidence,dict) or not _text(evidence.get('quote',''),'evidence quote',420,True):
                raise MarketingDraftError('Every proposed concept needs a direct source excerpt')
            evidence_url=_text(evidence.get('sourceUrl',''),'evidence source URL',512)
            if evidence_url:
                try:
                    source=urlsplit(evidence_url);base=urlsplit(url)
                    if (source.scheme!='https' or source.hostname!=base.hostname or source.port!=base.port or
                        source.username or source.password or any(ord(c)<33 for c in evidence_url)):
                        raise ValueError()
                except ValueError:raise MarketingDraftError('Evidence source must belong to the same site') from None
            clean.append({'id':ident,
                'role':_text(candidate.get('role',''),'concept role',80,True),
                'media':_text(candidate.get('media',''),'concept format',40,True),
                'format':_text(candidate.get('format',''),'ratio',12,True),
                'direction':_text(candidate.get('direction',''),'art direction',600,True),
                'hook':_text(candidate.get('hook',''),'source-linked hook',160,True),
                'evidence':{'kind':_text(evidence.get('kind',''),'evidence kind',40),
                     'label':_text(evidence.get('label',''),'evidence origin',80),
                     'quote':_text(evidence.get('quote',''),'evidence quote',420,True),
                     **({'sourceUrl':evidence_url} if evidence_url else {})},
                'generationState':'unrendered','publishApproved':False,
                'spendApproved':False,'ownerApproved':False,
                'quality':'needs_authentic_assets_and_human_art_review'})
        if raw_shortlist['status']=='three_directions_ready_for_asset_intake' and len(clean)!=3:
            raise MarketingDraftError('Three distinct grounded concepts are required')
        sector=raw_shortlist.get('sector','other')
        if sector not in {'restaurant','concierge','beauty','renovation','roofing','country_club','plumbing','other'}:
            raise MarketingDraftError('Invalid sourced business sector')
        clean_shortlist={'status':raw_shortlist['status'],'sector':sector,'candidates':clean,
            'approved':False,'canGenerateAutomatically':False,
            'sourceUrl':url,'ownerAssetsRequired':True}
    # Local owner attestation is tied to the exact planning context. It is not
    # authenticated identity, claim verification, media approval or publication.
    owner_strategy=None
    raw_strategy=value.get('ownerStrategy')
    if raw_strategy is not None:
        if not isinstance(raw_strategy,dict):raise MarketingDraftError('Invalid owner strategy')
        limits={'audience':300,'offer':500,'positioning':500,'callToAction':240,'constraints':1000}
        owner_strategy={k:_text(raw_strategy.get(k,''),k,n) for k,n in limits.items()}
        context={'business':result['business'],'goal':result['goal'],'sourceUrl':url,
                 'observedFacts':[_text(f,'observation',600) for f in facts],**owner_strategy}
        if fact_sources is not None:context['observedFactSources']=fact_sources
        decisions=raw_strategy.get('factDecisions',[])
        if not isinstance(decisions,list) or len(decisions)>40:
            raise MarketingDraftError('Invalid business fact reviews')
        clean_decisions=[];seen_facts=set()
        for entry in decisions:
            if not isinstance(entry,dict):raise MarketingDraftError('Invalid business fact review')
            index=entry.get('index');decision=entry.get('decision')
            if type(index) is not int or not 0<=index<40 or index in seen_facts or decision not in ('confirmed','corrected','excluded'):
                raise MarketingDraftError('Invalid business fact review')
            seen_facts.add(index)
            statement=_text(entry.get('statement',''),'owner correction',600)
            if decision!='corrected' and statement:
                raise MarketingDraftError('Only corrected facts accept an owner statement')
            clean_decisions.append({'index':index,'observation':_text(entry.get('observation',''),'reviewed observation',600),
                                    'decision':decision,'statement':statement})
        clean_decisions.sort(key=lambda entry:entry['index'])
        if clean_decisions:
            owner_strategy['factDecisions']=clean_decisions
            context['factDecisions']=clean_decisions
        current_decisions={entry['index']:entry for entry in clean_decisions}
        facts_reviewed=all(index in current_decisions and current_decisions[index]['observation']==fact
            and (current_decisions[index]['decision']!='corrected' or current_decisions[index]['statement'].strip())
            for index,fact in enumerate(facts))
        raw_links=raw_strategy.get('evidenceLinks',{})
        if not isinstance(raw_links,dict) or any(k not in limits for k in raw_links):
            raise MarketingDraftError('Invalid strategy evidence links')
        links={}
        for key,link in raw_links.items():
            if not isinstance(link,dict):raise MarketingDraftError('Invalid strategy evidence reference')
            links[key]={'id':_text(link.get('id',''),'evidence id',32,True),
                        'sourceUrl':_text(link.get('sourceUrl',''),'evidence URL',512,True),
                        'quote':_text(link.get('quote',''),'evidence quote',420,True)}
        if links:
            owner_strategy['evidenceLinks']=links
            context['evidenceLinks']=links
            context['researchEvidence']=[{'id':c['id'],'sourceUrl':c['evidence'].get('sourceUrl',url),'quote':c['evidence']['quote']}
                for c in (clean_shortlist or {}).get('candidates',[])]
        current_evidence={(c['id'],c['evidence'].get('sourceUrl',url),c['evidence']['quote'])
            for c in (clean_shortlist or {}).get('candidates',[])}
        links_current=all((link['id'],link['sourceUrl'],link['quote']) in current_evidence for link in links.values())
        owner_strategy['confirmedContext']=(context if facts_reviewed and links_current and all(owner_strategy[k].strip() for k in limits if k != 'positioning')
            and raw_strategy.get('confirmedContext')==context else None)
    posts=value.get('posts');creatives=value.get('creatives')
    if not isinstance(posts,list) or not 1<=len(posts)<=30:raise MarketingDraftError('A plan needs 1–30 posts')
    if not isinstance(creatives,list) or not 1<=len(creatives)<=8:raise MarketingDraftError('A campaign needs 1–8 concepts')
    old_posts={p['day']:p for p in (previous or {}).get('posts',[])}
    old_creatives={p['id']:p for p in (previous or {}).get('creatives',[])}
    days=set();ids=set();clean_posts=[];clean_creatives=[]
    def review_status(item,old,fields):
        status='copy_reviewed' if item.get('status')=='copy_reviewed' else 'draft'
        # Preserve old documents and all words, but never carry known planning
        # material forward as checked customer copy. Draft saves remain allowed.
        if marketing_copy_issue(item,result['business']):status='draft'
        if old and any(item.get(k,'')!=old.get(k,'') for k in fields):status='draft'
        return status
    for item in posts:
        if not isinstance(item,dict):raise MarketingDraftError('Invalid post')
        day=item.get('day')
        if type(day) is not int or not 1<=day<=30 or day in days:raise MarketingDraftError('Invalid or duplicate plan day')
        days.add(day)
        fields={'theme':200,'channel':50,'format':80,'objective':60,'copyDraft':3000,'callToAction':240}
        if 'graphicText' in item:fields['graphicText']=500
        if 'supportingLine' in item:fields['supportingLine']=180
        clean={k:_text(item.get(k,''),k,n) for k,n in fields.items()}
        if 'destinationUrl' in item:
            destination = _text(item['destinationUrl'], 'CTA destination', 512)
            if destination:
                try:
                    parsed = urlsplit(destination)
                    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                            or parsed.port == 0 or '\\' in destination
                            or any(ord(c) < 33 or ord(c) == 127 for c in destination)):
                        raise ValueError()
                except ValueError:
                    raise MarketingDraftError('Use a complete HTTPS CTA destination without credentials or spaces. No link was connected.') from None
            clean['destinationUrl'] = destination
        clean_posts.append({**clean,'day':day,'status':review_status(clean|{'status':item.get('status')},old_posts.get(day),set(fields)|{'graphicText','supportingLine','destinationUrl'}),
                            'scheduled':False,'published':False})
    for item in creatives:
        if not isinstance(item,dict):raise MarketingDraftError('Invalid concept')
        cid=item.get('id')
        if not isinstance(cid,str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',cid) or cid in ids:raise MarketingDraftError('Invalid creative identifier')
        ids.add(cid)
        fields={'format':60,'title':180,'ratio':16,'brief':6000,'copyDraft':2000,'callToAction':240}
        clean={k:_text(item.get(k,''),k,n) for k,n in fields.items()}
        # Video briefs include voiceover and on-screen words. We cannot infer
        # that an unstructured edit changed only the picture instructions.
        word_review_fields=tuple(key for key in fields if key!='brief' or clean['format']=='video_ad')
        clean_creatives.append({**clean,'id':cid,'status':review_status(clean|{'status':item.get('status')},old_creatives.get(cid),word_review_fields),
          'assetUrl':None,'mediaStatus':'not_generated','published':False,'approved':False})
    return {**result,'version':1,'calendarStartDate':calendar_start,'sourceUrl':url,'websiteAuditText':_text(value.get('websiteAuditText',''),'website audit',12000),
      'observedFacts':[_text(f,'observation',600) for f in facts],
      **({'observedFactSources':fact_sources} if fact_sources is not None else {}),
      'websiteImages':clean_images,'editorialShortlist':clean_shortlist,'ownerStrategy':owner_strategy,
      **({'brandKit':_campaign_brand(value['brandKit'])} if 'brandKit' in value else {}),
      **({'brandIdentity':_brand_identity(value['brandIdentity'],url)} if 'brandIdentity' in value else {}),
      **({'paidCampaign':__import__('business_paid_campaign').normalise(value['paidCampaign'])} if 'paidCampaign' in value else {}),
      **({'googleCampaign':__import__('business_paid_campaign').normalise_google(value['googleCampaign'])} if 'googleCampaign' in value else {}),
      **({'searchPropertySetup':__import__('business_search_property').normalise(value['searchPropertySetup'])} if 'searchPropertySetup' in value else {}),
      **({'organicWork':__import__('business_organic_work').normalise(value['organicWork'],value,previous,validate_references=_validate_organic_references)} if 'organicWork' in value else {}),
      **({'prospects':__import__('business_growthrova_prospects').normalise(value['prospects'])} if 'prospects' in value else {}),
      'posts':clean_posts,'creatives':clean_creatives,'canPublish':False,'canSpend':False,
      'sourceStatus':'website_observations_require_owner_confirmation'}

def _public(row):
    return {'id':row['id'],'revision':row['revision'],'document':json.loads(row['document_json']),
            'created':row['created'],'updated':row['updated'],'storage':'local_device_only'}

def read_draft(con,draft_id):
    row=con.execute('SELECT * FROM marketing_drafts WHERE id=?',(_id(draft_id),)).fetchone()
    if not row:raise MarketingDraftError('Campaign not found','not_found',404)
    return _public(row)

def list_drafts(con):
    records=con.execute('SELECT * FROM marketing_drafts ORDER BY updated DESC LIMIT 100').fetchall()
    return [{'id':r['id'],'revision':r['revision'],'updated':r['updated'],
             'name':json.loads(r['document_json'])['name'],'business':json.loads(r['document_json'])['business'],
             'sourceUrl':json.loads(r['document_json']).get('sourceUrl','')} for r in records]

def save_draft(con,payload,*,_authorize_write=None,_retain_revision=None):
    if not isinstance(payload,dict):raise MarketingDraftError('Campaign document required')
    draft_id=_id(payload.get('id'));mutation=_id(payload.get('mutationId'));base=payload.get('expectedRevision')
    if type(base) is not int or not 0<=base<2147483647:raise MarketingDraftError('Invalid campaign revision')
    # Fingerprint the submitted intent before review-status invalidation. Repeating
    # precisely the same operation remains idempotent even if it reset approval.
    # Validate reference ownership against the persisted revision below, after
    # the write lock. Fingerprinting must also accept retained stale snapshots.
    document=normalise_document(payload.get('document'),_validate_organic_references=False)
    encoded=json.dumps(document,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    if len(encoded.encode('utf8'))>220000:raise MarketingDraftError('Campaign document is too large')
    fingerprint=hashlib.sha256((str(base)+'\n'+encoded).encode('utf8')).hexdigest()
    con.execute('BEGIN IMMEDIATE')
    if _authorize_write is not None:
        _authorize_write(con,draft_id)
    old=con.execute('SELECT * FROM marketing_drafts WHERE id=?',(draft_id,)).fetchone()
    receipt=con.execute('SELECT * FROM marketing_draft_mutations WHERE draft_id=? AND mutation_id=?',(draft_id,mutation)).fetchone()
    if receipt:
        if receipt['fingerprint']!=fingerprint:raise MarketingDraftError('Save identifier already used for different edits','mutation_conflict',409)
        if not old or old['revision']!=receipt['result_revision']:
            raise MarketingDraftError('A newer campaign revision exists. Reload before saving.','replay_superseded',409)
        return {**_public(old),'replayed':True}
    from business_paid_campaign import validate_asset
    validate_asset(con,draft_id,document.get('paidCampaign'))
    current=old['revision'] if old else 0
    if current!=base:raise MarketingDraftError('Another editor saved changes. Your edits are retained; reload the saved version to resolve.','revision_conflict',409)
    if not old and con.execute('SELECT count(*) FROM marketing_drafts').fetchone()[0]>=100:
        raise MarketingDraftError('Local campaign limit reached','storage_limit',409)
    document=normalise_document(payload['document'],json.loads(old['document_json']) if old else None)
    from business_organic_work import validate_work_references
    validate_work_references(con,draft_id,document,json.loads(old['document_json']) if old else None)
    from business_growthrova_prospects import retain_delivery_subjects
    retain_delivery_subjects(con,draft_id,document)
    encoded=json.dumps(document,ensure_ascii=False,separators=(',',':'))
    now=time.time();revision=current+1
    if old:con.execute('UPDATE marketing_drafts SET revision=?,document_json=?,updated=? WHERE id=?',(revision,encoded,now,draft_id))
    else:con.execute('INSERT INTO marketing_drafts VALUES(?,?,?,?,?)',(draft_id,revision,encoded,now,now))
    con.execute('INSERT INTO marketing_draft_mutations VALUES(?,?,?,?)',(draft_id,mutation,fingerprint,revision))
    # Isolated authenticated storage may retain exact bodies under this same
    # writer lock. A retention failure must roll back the save and its receipt.
    if _retain_revision is not None:
        _retain_revision(con, old, con.execute('SELECT * FROM marketing_drafts WHERE id=?', (draft_id,)).fetchone())
    result=read_draft(con,draft_id);con.commit()
    return {**result,'replayed':False}
