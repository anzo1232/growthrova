"""Owner-recorded prospect research inside the existing campaign document.

Research and owner-recorded permission notes remain separate from enquiries and
exact message delivery approvals; public contact details confer no permission.
Explicit single-page reads reuse the existing safe website reader. No contact
discovery, provider inference or messages are performed here.
"""
from datetime import date
import re
from urllib.parse import urlsplit


def normalise(value):
    from business_marketing_drafts import MarketingDraftError, _text

    limits = dict(name=160, sourceUrl=512, sourceQuote=2000, observedOn=10,
                  fit=2000, contactName=160, contactEmail=254,
                  researchNotes=2000, outreachDraft=4000, nextAction=1000)
    if not isinstance(value, list) or len(value) > 30:
        raise MarketingDraftError('Keep up to 30 prospects per campaign.')
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) - {'outreachPermission', 'qualification'} != set(limits) | {'id', 'status'}:
            raise MarketingDraftError('Use the supported prospect preparation fields.')
        ident = item['id']
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ident) or ident in seen:
            raise MarketingDraftError('Invalid or duplicate prospect identifier.')
        seen.add(ident)
        if item['status'] not in ('researching', 'drafting', 'ready_for_review', 'parked'):
            raise MarketingDraftError('Choose a prospect preparation status.')
        clean = {key: _text(item[key], 'prospect '+key, limit, key == 'name')
                 for key, limit in limits.items()}
        # Validate references without fetching them. A syntactically valid URL
        # is still an owner's unverified source, not confirmed research.
        url = clean['sourceUrl']
        if url:
            try:
                parsed = urlsplit(url)
                if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                        or parsed.port == 0 or '\\' in url
                        or any(ord(c) < 33 or ord(c) == 127 for c in url)):
                    raise ValueError()
            except ValueError:
                raise MarketingDraftError('Use a complete HTTPS prospect source without credentials or spaces.') from None
        observed = clean['observedOn']
        if observed:
            try:
                if date.fromisoformat(observed).isoformat() != observed:
                    raise ValueError()
            except ValueError:
                raise MarketingDraftError('Use a valid prospect observation date (YYYY-MM-DD).') from None
        if clean['contactEmail'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', clean['contactEmail']):
            raise MarketingDraftError('Enter a complete prospect email address or leave it empty.')
        if item['status'] == 'ready_for_review' and not all(clean[key].strip() for key in
                ('sourceUrl', 'sourceQuote', 'observedOn', 'fit', 'outreachDraft')):
            raise MarketingDraftError('Add the prospect source, quotation, date, fit and wording before human review.')
        record = dict(id=ident, status=item['status'], **clean)
        if 'qualification' in item:
            qualification = item['qualification']
            if (not isinstance(qualification, dict) or set(qualification) != {'decision', 'reason'}
                    or qualification['decision'] not in ('unreviewed', 'pursue', 'hold', 'not_fit')):
                raise MarketingDraftError('Choose a supported prospect qualification decision.')
            reason = _text(qualification['reason'], 'qualification reason', 2000)
            if qualification['decision'] != 'unreviewed' and not reason.strip():
                raise MarketingDraftError('Record why you made this prospect qualification decision.')
            record['qualification'] = dict(decision=qualification['decision'], reason=reason)
        if 'outreachPermission' in item:
            permission = item['outreachPermission']
            if not isinstance(permission, dict) or set(permission) != {'email', 'notes'}:
                raise MarketingDraftError('Record the exact permitted email and actual permission notes.')
            email = _text(permission['email'], 'permitted email', 254)
            notes = _text(permission['notes'], 'outreach permission notes', 2000)
            if email and not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', email):
                raise MarketingDraftError('Use a complete permitted email address or leave it empty.')
            record['outreachPermission'] = dict(email=email, notes=notes)
        result.append(record)
    return result


def outreach_allowed(item):
    """Qualification can withhold outreach; it never establishes permission.

    Keep historical absent qualifications compatible with existing approvals.
    The saved campaign revision already fences every unstarted message.
    """
    return (item['status'] == 'ready_for_review'
            and item.get('qualification', {}).get('decision') not in ('hold', 'not_fit'))


def normalise_origin(value):
    """A retained research snapshot plus an owner's actual-response statement."""
    from business_marketing_drafts import MarketingDraftError, _text
    limits = dict(prospectId=64, name=160, sourceUrl=512, sourceQuote=2000,
                  observedOn=10, responseNote=2000)
    if not isinstance(value, dict) or set(value) != set(limits) | {'campaignRevision'}:
        raise MarketingDraftError('Use the supported prospect response fields.')
    result = {key: _text(value[key], key, limit) for key, limit in limits.items()}
    if (not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', result['prospectId'])
            or not result['name'].strip() or not result['responseNote'].strip()
            or type(value['campaignRevision']) is not int or value['campaignRevision'] < 1):
        raise MarketingDraftError('Select a saved prospect and describe the actual response.')
    return dict(result, campaignRevision=value['campaignRevision'])


def retain_delivery_subjects(con, ident, document):
    """Keep approved message recovery reachable; caller holds the save lock."""
    from business_marketing_drafts import MarketingDraftError
    import json
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='growthrova_followup_jobs'").fetchone():
        return
    kept = {p['id'] for p in document.get('prospects', [])}
    rows = con.execute('SELECT snapshot_json FROM growthrova_followup_jobs WHERE document_id=?', (ident,)).fetchall()
    for row in rows:
        snap = json.loads(row['snapshot_json'])
        if snap.get('subjectKind') == 'prospect' and snap['prospectId'] not in kept:
            raise MarketingDraftError('Keep prospects with approved email history so their outcomes remain accessible. Park the prospect instead.',
                                      'outreach_history_retained', 409)


def validate_handoff(con, scope, ident, origin):
    """Caller holds the existing lead write transaction and ownership fence."""
    import json
    from business_marketing_drafts import MarketingDraftError
    row = con.execute('SELECT revision,document_json FROM marketing_drafts WHERE id=?', (ident,)).fetchone()
    if not row or row['revision'] != origin['campaignRevision']:
        raise MarketingDraftError('The campaign changed. Reopen it before recording this response.', 'revision_conflict', 409)
    prospect = next((item for item in json.loads(row['document_json']).get('prospects', [])
                     if item['id'] == origin['prospectId']), None)
    if not prospect or any(origin[key] != prospect[key] for key in
                           ('name', 'sourceUrl', 'sourceQuote', 'observedOn')):
        raise MarketingDraftError('Use the saved prospect source unchanged. Reopen the campaign.', 'revision_conflict', 409)
    # Bounded by the existing 1,000-lead business limit. Includes contacts whose
    # details have since changed, preventing a second enquiry for this handoff.
    rows = con.execute('SELECT data_json FROM growthrova_leads WHERE owner_id=? '
                       'AND organisation_id=? AND document_id=?', (*scope, ident)).fetchall()
    if any(json.loads(row['data_json']).get('prospectOrigin', {}).get('prospectId') == origin['prospectId'] for row in rows):
        raise MarketingDraftError('This prospect already has an enquiry. Find its saved record in Leads and results.', 'duplicate_prospect', 409)


def register_prospect_routes(app, repo, root, *, revalidate=None, reader=None):
    """Read-only research; selected quotations use normal document persistence."""
    from contextlib import closing
    from datetime import datetime, timezone
    from flask import jsonify, request
    from business_marketing_drafts import MarketingDraftError
    from business_marketing_offline import OfflineDocumentAccessError
    from business_website_analysis import extract_website, external_page_references, WebsiteSafetyError

    @app.post(root + '/<ident>/prospect-research')
    def growthrova_prospect_research(organisation_id, ident):
        scope = repo._scope(organisation_id)
        repo.read(organisation_id, ident)
        if request.content_length is None or request.content_length > 2048:
            raise MarketingDraftError('Supply one public HTTPS prospect page.')
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'website'}
                or not isinstance(data['website'], str) or not 1 <= len(data['website']) <= 500):
            raise MarketingDraftError('Supply one public HTTPS prospect page.')
        # No transaction spans network I/O. The shared reader owns DNS pinning,
        # redirect validation, deadlines, byte caps and concurrent-reader limits.
        try:
            report = (reader or extract_website)(data['website'])
        except WebsiteSafetyError:
            return jsonify(code='research_unavailable', error='This page could not be read safely. Your saved research is unchanged. Try another public page or record a quotation yourself.'), 400
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        with closing(repo._connect()) as con:
            if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
                raise OfflineDocumentAccessError('Campaign access changed')
        # Preserve whole bounded excerpts, rather than clip text and call it an
        # exact quotation. Never return arbitrary report HTML/links/contact fields.
        quotes = list(dict.fromkeys(text for text in report.get('observations', {}).get('visible_paragraphs', [])
                                   if isinstance(text, str) and 40 <= len(text) <= 2000))[:12]
        return jsonify(sourceUrl=report['source_url'],
                       observedOn=datetime.now(timezone.utc).date().isoformat(),
                       quotes=quotes,
                       candidates=external_page_references(report.get('observations', {}).get('external_links', []), report['source_url']),
                       status='extracted_unconfirmed',
                       notice='Website statements are unverified. Select a quotation, review it and save the campaign to retain it. No contact permission is established.')
