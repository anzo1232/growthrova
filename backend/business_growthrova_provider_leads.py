"""Provider event provenance/receipts and owner-reviewed manual handoff.

Receipts are contact-free. The existing enquiry store remains authoritative.
No provider requests, account authority or messaging permissions are inferred.
"""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import secrets
import time

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _text
from business_marketing_offline import OfflineDocumentAccessError
from business_growthrova_leads import normalise, persist_lead

ORIGIN_LIMITS = dict(accountId=160, formId=160, eventId=160, campaignReference=160, submittedAt=25)
PLATFORMS = {'meta': 'Meta lead form', 'google': 'Google lead form'}


def normalise_origin(value):
    if not isinstance(value, dict) or set(value) != set(ORIGIN_LIMITS) | {'platform', 'verification'}:
        raise MarketingDraftError('Use the supported provider event references.')
    if not isinstance(value['platform'], str) or value['platform'] not in PLATFORMS or value['verification'] not in ('owner_import', 'google_shared_key', 'meta_signed_retrieval'):
        raise MarketingDraftError('Use a supported provider provenance type.')
    if value['verification'] == 'google_shared_key' and value['platform'] != 'google':
        raise MarketingDraftError('Shared-key provenance is only supported for Google forms.')
    if value['verification'] == 'meta_signed_retrieval' and value['platform'] != 'meta':
        raise MarketingDraftError('Signed-retrieval provenance is only supported for Meta forms.')
    result = {key: _text(value[key], key, limit).strip() for key, limit in ORIGIN_LIMITS.items()}
    if any(not result[key] for key in ('accountId', 'formId', 'eventId')):
        raise MarketingDraftError('Add the account, form, event identity and reported submission time.')
    if any(any(ord(c) < 32 for c in result[key]) for key in ORIGIN_LIMITS):
        raise MarketingDraftError('Use single-line provider references.')
    if not result['submittedAt'] and value['verification'] == 'google_shared_key':
        return dict(result, platform=value['platform'], verification=value['verification'])
    try:
        stamp = datetime.strptime(result['submittedAt'], '%Y-%m-%dT%H:%M:%SZ')
        if stamp.strftime('%Y-%m-%dT%H:%M:%SZ') != result['submittedAt']:
            raise ValueError()
    except ValueError:
        raise MarketingDraftError('Use the reported UTC submission time: YYYY-MM-DDTHH:MM:SSZ.') from None
    return dict(result, platform=value['platform'], verification=value['verification'])


def provider_receipt(row):
    return dict(platform=row['platform'], accountId=row['account_id'], formId=row['form_id'],
                eventId=row['event_id'], outcome=row['outcome'], leadId=row['lead_id'], recordedAt=row['created'])


def record_provider_event(con, scope, ident, data, *, actor_id):
    """Caller holds write transaction and checks binding/ownership before commit."""
    data, _, _ = normalise(data)
    origin = data['providerOrigin']
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    key = (*scope, origin['platform'], origin['accountId'], origin['eventId'])
    old = con.execute('SELECT * FROM growthrova_provider_lead_receipts WHERE owner_id=? AND '
                      'organisation_id=? AND platform=? AND account_id=? AND event_id=?', key).fetchone()
    if old:
        if old['document_id'] != ident or old['fingerprint'] != fingerprint:
            raise MarketingDraftError('This event was already reviewed with different details or in another campaign. Keep the original record and add corrections in its enquiry.', 'provider_event_conflict', 409)
        result = dict(**provider_receipt(old), replayed=True)
    else:
        if con.execute('SELECT count(*) FROM growthrova_provider_lead_receipts WHERE owner_id=? '
                       'AND organisation_id=?', scope).fetchone()[0] >= 5000:
            raise MarketingDraftError('This business has reached the provider-event receipt limit.', 'storage_limit', 409)
        lead_id = secrets.token_hex(16)
        outcome = 'recorded'
        try:
            persist_lead(con, scope, ident, dict(id=lead_id, mutationId=secrets.token_hex(16),
                expectedRevision=0, data=data), actor_id=actor_id, provider_import=True)
        except MarketingDraftError as exc:
            if exc.code != 'duplicate_contact':
                raise
            lead_id, outcome = None, 'existing_contact_unchanged'
        now = time.time()
        con.execute('INSERT INTO growthrova_provider_lead_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (*key, ident, origin['formId'], fingerprint, outcome, lead_id, now))
        result = dict(platform=origin['platform'], accountId=origin['accountId'], formId=origin['formId'],
                      eventId=origin['eventId'], outcome=outcome, leadId=lead_id, recordedAt=now, replayed=False)
    return result


def register_provider_lead_routes(app, repo, root, *, revalidate=None):
    with closing(repo._connect()) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS growthrova_provider_lead_receipts(
            owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, platform TEXT NOT NULL,
            account_id TEXT NOT NULL, event_id TEXT NOT NULL, document_id TEXT NOT NULL,
            form_id TEXT NOT NULL, fingerprint TEXT NOT NULL, outcome TEXT NOT NULL,
            lead_id TEXT, created REAL NOT NULL,
            PRIMARY KEY(owner_id,organisation_id,platform,account_id,event_id))''')
        con.commit()

    def checked(con, org, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(org) != scope or not repo._owned(con, ident, scope):
            raise OfflineDocumentAccessError('Campaign access changed')

    endpoint = root + '/<ident>/provider-enquiries'

    @app.get(endpoint)
    def growthrova_provider_enquiries_read(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            rows = con.execute('SELECT * FROM growthrova_provider_lead_receipts WHERE owner_id=? '
                               'AND organisation_id=? AND document_id=? ORDER BY created DESC LIMIT 25', (*scope, ident)).fetchall()
            total = con.execute('SELECT count(*) FROM growthrova_provider_lead_receipts WHERE owner_id=? '
                                'AND organisation_id=? AND document_id=?', (*scope, ident)).fetchone()[0]
            result = dict(receipts=[provider_receipt(row) for row in rows], total=total, manualHandoff=True)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        response = jsonify(result)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post(endpoint)
    def growthrova_provider_enquiry_import(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        request.max_content_length = 16000
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or set(value) != {'origin', 'contact', 'reviewed'} or value['reviewed'] is not True:
            raise MarketingDraftError('Review the actual enquiry and its provider references before saving.')
        origin = normalise_origin(value['origin'])
        if origin['verification'] != 'owner_import':
            raise MarketingDraftError('Manual handoffs must use owner-import provenance.')
        contact = value['contact']
        if not isinstance(contact, dict) or set(contact) != {'name', 'email', 'phone', 'message'}:
            raise MarketingDraftError('Use name, email, phone and enquiry message fields.')
        data = dict(name=contact['name'], email=contact['email'], phone=contact['phone'], notes=contact['message'],
                    source=PLATFORMS[origin['platform']] + ' · owner import', sourceReference=origin['eventId'],
                    status='new', qualification='', booking='', permissionNotes='',
                    emailPermission='unknown', whatsappPermission='unknown', providerOrigin=origin)
        data, _, _ = normalise(data)
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            result = record_provider_event(con, scope, ident, data, actor_id=scope[0])
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        response = jsonify(result)
        response.headers['Cache-Control'] = 'no-store'
        return response
