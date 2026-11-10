"""Research-linked preparation stored inside the authoritative campaign document."""
import re


def prepare_edit(document, changes, *, additions=None):
    """Prepare edits without replacing original research or saving the campaign."""
    from business_marketing_drafts import MarketingDraftError, normalise_document
    existing = {item['id']: item for item in document.get('organicWork', [])}
    if any(change['id'] not in existing for change in changes):
        raise MarketingDraftError('Choose work retained in this saved campaign')
    by_id = {change['id']: change for change in changes}
    work = []
    for item in document.get('organicWork', []):
        change = by_id.get(item['id'], {})
        if change.get('remove'):
            continue
        work.append({**item, **{key: value for key, value in change.items() if key != 'id'}})
    for addition in additions or []:
        # IDs belong to the owner's unsaved preparation, so retrying the same
        # request does not create a fresh identity. Never recycle removed IDs.
        if addition['id'] in existing:
            raise MarketingDraftError('This work identifier is already saved. Edit the existing item or choose a new identifier')
        index = addition['observationIndex']
        facts = document.get('observedFacts', [])
        if index >= len(facts):
            raise MarketingDraftError('Choose an observation retained in this saved campaign')
        sources = document.get('observedFactSources')
        work.append(dict(id=addition['id'], kind='content', status='planned',
            title=addition['title'], brief=addition.get('brief', ''),
            draft=addition.get('draft', ''), nextAction=addition.get('nextAction', ''),
            reference=dict(kind='fact', index=index, quote=facts[index],
                           sourceUrl=sources[index] if sources else '')))
    # Existing references remain historical snapshots even after new research.
    return normalise_document({**document, 'organicWork': work}, document)


def normalise(value, document, previous=None, *, validate_references=True):
    from business_marketing_drafts import MarketingDraftError, _text
    if not isinstance(value, list) or len(value) > 30:
        raise MarketingDraftError('Keep up to 30 organic work items per campaign')
    prior = {item['id']: item for item in (previous or {}).get('organicWork', [])}
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {'id','kind','title','brief','draft','nextAction','status','reference'}:
            raise MarketingDraftError('Use the supported organic work fields')
        ident = item['id']
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ident) or ident in seen:
            raise MarketingDraftError('Invalid or duplicate organic work identifier')
        seen.add(ident)
        if item['kind'] not in ('improvement','content') or item['status'] not in ('planned','drafting','ready_for_review','handed_off','parked'):
            raise MarketingDraftError('Choose an organic work type and preparation status')
        ref = item['reference']
        search = isinstance(ref, dict) and ref.get('kind') == 'search'
        fields = {'kind','index','quote','sourceUrl'} | ({'readId'} if search else set())
        if not isinstance(ref, dict) or set(ref) != fields:
            raise MarketingDraftError('Organic work needs its original research reference')
        reference = {'kind': _text(ref['kind'], 'reference type', 12),
                     'index': ref['index'], 'quote': _text(ref['quote'], 'research quotation', 12000, True),
                     'sourceUrl': _text(ref['sourceUrl'], 'research page', 512)}
        if search:
            from business_marketing_drafts import _id
            reference['readId'] = _id(ref['readId'])
        if reference['kind'] not in ('fact','audit','search') or type(reference['index']) is not int or not 0 <= reference['index'] < (50 if search else 40):
            raise MarketingDraftError('Invalid organic research reference')
        # Old snapshots may become stale; retain them exactly. New/replaced
        # references must point to research in this same saved document.
        if validate_references and not search and prior.get(ident, {}).get('reference') != reference:
            index = reference['index']
            if reference['kind'] == 'fact':
                facts, sources = document.get('observedFacts', []), document.get('observedFactSources')
                valid = index < len(facts) and reference['quote'] == facts[index] and reference['sourceUrl'] == (sources[index] if sources else '')
            else:
                valid = reference['quote'] in document.get('websiteAuditText', '') and reference['sourceUrl'] == document.get('sourceUrl', '')
            if not valid:
                raise MarketingDraftError('Choose research retained in this campaign for the organic work')
        result.append({'id': ident, 'kind': item['kind'], 'status': item['status'], 'reference': reference,
                       **{key: _text(item[key], 'organic '+key, limit, key == 'title') for key, limit in
                          [('title',200),('brief',3000),('draft',8000),('nextAction',1000)]}})
    return result


def validate_work_references(con, document_id, document, previous):
    import json
    from business_marketing_drafts import MarketingDraftError
    prior = {item['id']: item for item in (previous or {}).get('organicWork', [])}
    for item in document.get('organicWork', []):
        ref = item['reference']
        if ref['kind'] != 'search' or prior.get(item['id'], {}).get('reference') == ref:
            continue
        from business_growthrova_search import search_reference
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='growthrova_search_reads'").fetchone()
        row = con.execute("SELECT * FROM growthrova_search_reads WHERE id=? AND document_id=? AND state='completed'",
                          (ref['readId'], document_id)).fetchone() if exists else None
        if row:
            owner = con.execute('SELECT owner_id,organisation_id FROM offline_document_owners WHERE draft_id=?', (document_id,)).fetchone()
            if owner and tuple(owner) == (row['owner_id'], row['organisation_id']):
                snap, result = json.loads(row['snapshot_json']), json.loads(row['result_json'])
                if (snap.get('mode') == 'page_query' and ref['index'] < len(result['rows'])
                        and ref == search_reference(row['id'], snap, result, ref['index'])):
                    continue
        raise MarketingDraftError('Choose page/query evidence from a completed read in this saved campaign.')
