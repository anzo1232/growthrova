"""Campaign intake source contract. Hosting is explicitly disabled by default.

Public callers can only create bounded enquiries; they never choose a tenant,
source, status, or permission record and never receive private lead information.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from flask import jsonify, request, render_template_string
from business_marketing_drafts import MarketingDraftError, _text
from business_marketing_offline import OfflineDocumentAccessError
from business_growthrova_leads import persist_lead

PUBLIC_ENDPOINTS = frozenset(('growthrova_capture_form', 'growthrova_capture_submit'))
TOKEN = re.compile(r'[a-f0-9]{64}')
FIELDS = dict(heading=160, introduction=1500, privacyUrl=512, emailConsent=500, whatsappConsent=500)


def normalise_config(value):
    if not isinstance(value, dict) or set(value) != set(FIELDS) | {'enabled', 'token'}:
        raise MarketingDraftError('Use the supported intake settings.')
    result = {key: _text(value[key], key, limit).strip() for key, limit in FIELDS.items()}
    if type(value['enabled']) is not bool or not isinstance(value['token'], str) or not TOKEN.fullmatch(value['token']):
        raise MarketingDraftError('Intake settings and a valid link identity are required.')
    if not result['heading']:
        raise MarketingDraftError('Add a heading for your enquiry form.')
    if sum(len(result[k]) for k in ('privacyUrl', 'emailConsent', 'whatsappConsent')) > 700:
        raise MarketingDraftError('Keep the privacy URL and both permission statements within 700 characters together.')
    try:
        url = urlsplit(result['privacyUrl'])
    except ValueError:
        raise MarketingDraftError('Add a complete HTTPS privacy notice URL.') from None
    if (url.scheme != 'https' or not url.hostname or url.username or url.password or
            any(c.isspace() for c in result['privacyUrl'])):
        raise MarketingDraftError('Add a complete HTTPS privacy notice URL.')
    return {**result, 'enabled': value['enabled'], 'token': value['token']}


FORM = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ config.heading }}</title><style>body{font:1rem system-ui;max-width:40rem;margin:2rem auto;padding:1rem}label{display:block;margin:1rem 0}input,textarea,button{font:inherit;padding:.6rem;max-width:100%;box-sizing:border-box}input:not([type=checkbox]),textarea{width:100%}p{white-space:pre-wrap}</style>
<h1>{{ config.heading }}</h1><p>{{ config.introduction }}</p>
{% if error %}<p role="alert">{{ error }}</p>{% endif %}
<form method="post"><input type="hidden" name="submissionId" value="{{ submission }}"><input type="hidden" name="settingsRevision" value="{{ revision }}">
<label>Your name<input name="name" maxlength="160" autocomplete="name" required value="{{ values.get('name','') }}"></label>
<label>Email<input type="email" name="email" maxlength="254" autocomplete="email" value="{{ values.get('email','') }}"></label>
<label>Phone including country code<input type="tel" name="phone" maxlength="40" autocomplete="tel" value="{{ values.get('phone','') }}"></label>
<p>Provide an email address or phone number so the business can respond.</p>
<label>How can we help?<textarea name="message" maxlength="2000">{{ values.get('message','') }}</textarea></label>
<p><a href="{{ config.privacyUrl }}" rel="noreferrer">Read this business’s privacy notice</a>. Your details and enquiry will be shared with this business to handle your request.</p>
{% if config.emailConsent %}<label><input type="checkbox" name="emailConsent" value="yes" {% if values.get('emailConsent')=='yes' %}checked{% endif %}> {{ config.emailConsent }}</label>{% endif %}
{% if config.whatsappConsent %}<label><input type="checkbox" name="whatsappConsent" value="yes" {% if values.get('whatsappConsent')=='yes' %}checked{% endif %}> {{ config.whatsappConsent }}</label>{% endif %}
<p>Optional permission boxes start unchecked. Submitting this form does not send marketing messages.</p>
<button type="submit">Send enquiry</button></form><p><a href="{{ request.path }}">Start a new enquiry</a></p></html>'''


def register_capture_routes(app, repo, root, *, hosting_enabled=False, revalidate=None):
    with closing(repo._connect()) as con:
        con.executescript('''
          CREATE TABLE IF NOT EXISTS growthrova_capture_configs(
            document_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
            revision INTEGER NOT NULL, data_json TEXT NOT NULL, token TEXT NOT NULL UNIQUE,
            mutation_id TEXT NOT NULL, fingerprint TEXT NOT NULL, updated REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS growthrova_capture_receipts(
            token TEXT NOT NULL, submission_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            created REAL NOT NULL, PRIMARY KEY(token,submission_id));
          CREATE TABLE IF NOT EXISTS growthrova_capture_submissions(
            token TEXT NOT NULL, submission_id TEXT NOT NULL, settings_revision INTEGER NOT NULL,
            data_json TEXT NOT NULL, config_json TEXT NOT NULL, outcome TEXT NOT NULL,
            PRIMARY KEY(token,submission_id));
        ''')

    from business_growthrova_capture_inbox import register_business_capture_inbox, inbox_query, inbox_search
    register_business_capture_inbox(app, repo, root, revalidate)

    def checked(con, org, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(org) != scope or not repo._owned(con, ident, scope):
            raise OfflineDocumentAccessError('Campaign access changed')

    def settings(row):
        return dict(revision=row['revision'] if row else 0,
                    data=json.loads(row['data_json']) if row else None,
                    hostingEnabled=hosting_enabled,
                    publicPath='/api/growthrova/intake/' + row['token'] if row else None)

    endpoint = root + '/<ident>/intake'

    @app.get(endpoint + '/submissions')
    def growthrova_capture_inbox(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        query = inbox_query()
        before = request.args.get('before', '')
        if before and not re.fullmatch(r'[a-f0-9]{32}', before):
            raise MarketingDraftError('Use the saved inbox page reference.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            config = con.execute('SELECT * FROM growthrova_capture_configs WHERE document_id=?', (ident,)).fetchone()
            if config and (config['owner_id'], config['organisation_id']) != scope:
                raise OfflineDocumentAccessError('Campaign access changed')
            token = config['token'] if config else ''
            total = con.execute('SELECT count(*) FROM growthrova_capture_receipts WHERE token=?', (token,)).fetchone()[0]
            retained = con.execute('SELECT count(*) FROM growthrova_capture_submissions WHERE token=?', (token,)).fetchone()[0]
            search, search_params = inbox_search(con, query)
            matching = con.execute('SELECT count(*) FROM growthrova_capture_submissions s WHERE s.token=?' + search,
                                   (token, *search_params)).fetchone()[0]
            clause, params = '', [token]
            if before:
                anchor = con.execute('SELECT created FROM growthrova_capture_receipts WHERE token=? AND submission_id=?',
                                     (token, before)).fetchone()
                if not anchor:
                    raise MarketingDraftError('Refresh this campaign inbox before opening another page.')
                clause = ' AND (r.created<? OR (r.created=? AND r.submission_id<?))'
                params.extend((anchor['created'], anchor['created'], before))
            rows = con.execute('SELECT s.*,r.created FROM growthrova_capture_submissions s '
                               'JOIN growthrova_capture_receipts r USING(token,submission_id) WHERE s.token=?' + search + clause +
                               ' ORDER BY r.created DESC,r.submission_id DESC LIMIT 31',
                               [token, *search_params, *params[1:]]).fetchall()
            items = [dict(id=row['submission_id'], receivedAt=row['created'], settingsRevision=row['settings_revision'],
                          contact=json.loads(row['data_json']), form=json.loads(row['config_json']), outcome=row['outcome'])
                     for row in rows[:30]]
            result = dict(campaignId=ident, totalReceived=total, retained=retained, historicalWithoutContent=total-retained,
                          query=query, matchingRetained=matching, submissions=items,
                          nextBefore=items[-1]['id'] if len(rows)>30 else None)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        return jsonify(result)

    @app.get(endpoint)
    def growthrova_capture_read(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            row = con.execute('SELECT * FROM growthrova_capture_configs WHERE document_id=?', (ident,)).fetchone()
            if row and (row['owner_id'], row['organisation_id']) != scope:
                raise OfflineDocumentAccessError('Campaign access changed')
            result = settings(row)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        return jsonify(result)

    @app.post(endpoint)
    def growthrova_capture_save(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        request.max_content_length = 16000
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {'expectedRevision', 'mutationId', 'data'}:
            raise MarketingDraftError('Intake settings and save version are required.')
        base, mutation = payload['expectedRevision'], payload['mutationId']
        if type(base) is not int or not 0 <= base < 10000 or not isinstance(mutation, str) or not re.fullmatch(r'[a-f0-9]{32}', mutation):
            raise MarketingDraftError('Invalid intake save version.')
        data = normalise_config(payload['data'])
        encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        fingerprint = hashlib.sha256((str(base) + '\n' + encoded).encode()).hexdigest()
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            row = con.execute('SELECT * FROM growthrova_capture_configs WHERE document_id=?', (ident,)).fetchone()
            if row and (row['owner_id'], row['organisation_id']) != scope:
                raise OfflineDocumentAccessError('Campaign access changed')
            if row and row['mutation_id'] == mutation and row['fingerprint'] == fingerprint:
                result = settings(row)
            else:
                if (row['revision'] if row else 0) != base or (row and row['mutation_id'] == mutation):
                    raise MarketingDraftError('Another edit was saved. Reopen the intake settings.', 'revision_conflict', 409)
                # Tokens are permanent across text revisions. A pause is immediate;
                # re-enable uses the same link. Rotation is deliberately not implicit.
                if row and row['token'] != data['token']:
                    raise MarketingDraftError('Keep the saved form link identity.')
                con.execute('INSERT INTO growthrova_capture_configs VALUES(?,?,?,?,?,?,?,?,?) '
                            'ON CONFLICT(document_id) DO UPDATE SET revision=excluded.revision,data_json=excluded.data_json,'
                            'mutation_id=excluded.mutation_id,fingerprint=excluded.fingerprint,updated=excluded.updated',
                            (ident, *scope, base + 1, encoded, data['token'], mutation, fingerprint, time.time()))
                result = settings(con.execute('SELECT * FROM growthrova_capture_configs WHERE document_id=?', (ident,)).fetchone())
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(result)

    def available(con, token):
        if not hosting_enabled or not TOKEN.fullmatch(token):
            return None
        row = con.execute('SELECT * FROM growthrova_capture_configs WHERE token=?', (token,)).fetchone()
        if not row or not json.loads(row['data_json'])['enabled']:
            return None
        if not repo._owned(con, row['document_id'], (row['owner_id'], row['organisation_id'])):
            return None
        return row

    def unavailable():
        return 'This enquiry form is unavailable. Please contact the business directly.', 404

    @app.get('/api/growthrova/intake/<token>')
    def growthrova_capture_form(token):
        with closing(repo._connect()) as con:
            row = available(con, token)
            if not row:
                return unavailable()
            return render_template_string(FORM, config=json.loads(row['data_json']),
                                          submission=secrets.token_hex(16), revision=row['revision'], values={})

    @app.post('/api/growthrova/intake/<token>')
    def growthrova_capture_submit(token):
        request.max_content_length = 16000
        # No CORS grant. Native POST form and optional same-origin JSON use the
        # same normaliser and transaction. Never accept source/tenant claims.
        values = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            row = available(con, token)
            if not row:
                return unavailable()
            config = json.loads(row['data_json'])
            try:
                allowed = {'settingsRevision', 'submissionId', 'name', 'email', 'phone', 'message', 'emailConsent', 'whatsappConsent'}
                if not isinstance(values, dict) or set(values) - allowed:
                    raise MarketingDraftError('Use the enquiry form fields.')
                submission = values.get('submissionId', '')
                if not isinstance(submission, str) or not re.fullmatch(r'[a-f0-9]{32}', submission):
                    raise MarketingDraftError('Reopen the enquiry form before submitting.')
                revision = values.get('settingsRevision')
                if not isinstance(revision, (str, int)) or isinstance(revision, bool) or not re.fullmatch(r'[0-9]{1,5}', str(revision)):
                    raise MarketingDraftError('Reopen the form to load its current permission wording.')
                raw = {key: _text(values.get(key, ''), key, limit).strip() for key, limit in
                       dict(name=160, email=254, phone=40, message=2000, emailConsent=3, whatsappConsent=3).items()}
                if any(raw[k] not in ('', 'yes') for k in ('emailConsent', 'whatsappConsent')):
                    raise MarketingDraftError('Choose only the permissions offered on this form.')
                if (raw['emailConsent'] and not raw['email']) or (raw['whatsappConsent'] and not raw['phone']):
                    raise MarketingDraftError('Provide the contact detail for each optional permission selected.')
                fingerprint = hashlib.sha256((str(revision) + '\n' + json.dumps(raw, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
                receipt = con.execute('SELECT fingerprint FROM growthrova_capture_receipts WHERE token=? AND submission_id=?',
                                      (token, submission)).fetchone()
                if receipt:
                    if receipt['fingerprint'] != fingerprint:
                        raise MarketingDraftError('This submission has changed. Reopen the form for a new enquiry.')
                else:
                    if int(revision) != row['revision']:
                        raise MarketingDraftError('The form changed. Review the current wording and select any optional permissions again.')
                    if any(raw[k] and not config[k] for k in ('emailConsent', 'whatsappConsent')):
                        raise MarketingDraftError('Choose only the permissions offered on this form.')
                    now = time.time()
                    total, daily = con.execute('SELECT count(*),coalesce(sum(created>=?),0) FROM growthrova_capture_receipts WHERE token=?',
                                               (now - 86400, token)).fetchone()
                    if total >= 1000 or daily >= 100:
                        return 'This form cannot accept more enquiries right now. Contact the business directly.', 429
                    provenance = f"Campaign intake; settings revision {row['revision']}; submitted {datetime.fromtimestamp(now, timezone.utc).isoformat()}; privacy notice {config['privacyUrl']}"
                    permissions = [f'{key}: {config[key]}' for key in ('emailConsent', 'whatsappConsent') if raw[key]]
                    data = dict(name=raw['name'], email=raw['email'], phone=raw['phone'], source='Campaign enquiry form',
                                sourceReference='intake:' + hashlib.sha256(token.encode()).hexdigest()[:16], status='new',
                                qualification='', booking='', notes=raw['message'],
                                emailPermission='recorded' if raw['emailConsent'] else 'unknown',
                                whatsappPermission='recorded' if raw['whatsappConsent'] else 'unknown',
                                permissionNotes=provenance + '\n' + '\n'.join(permissions))
                    # Bound the combined immutable consent evidence without truncating it.
                    # Full wording remains in the version recorded in this snapshot.
                    if len(data['permissionNotes']) > 1000:
                        raise MarketingDraftError('The form permission wording is too long. Contact the business directly.')
                    outcome = 'new_contact'
                    try:
                        persist_lead(con, (row['owner_id'], row['organisation_id']), row['document_id'],
                                     dict(id=secrets.token_hex(16), mutationId=submission, expectedRevision=0, data=data), actor_id='public-intake')
                    except MarketingDraftError as exc:
                        if exc.code != 'duplicate_contact':
                            raise
                        # Keep the new enquiry in the inbox without overwriting a
                        # contact, inferring permission or disclosing a match publicly.
                        outcome = 'existing_contact_unchanged'
                    con.execute('INSERT INTO growthrova_capture_receipts VALUES(?,?,?,?)', (token, submission, fingerprint, now))
                    con.execute('INSERT INTO growthrova_capture_submissions VALUES(?,?,?,?,?,?)',
                                (token, submission, row['revision'], json.dumps(raw, ensure_ascii=False),
                                 json.dumps({key: config[key] for key in FIELDS}, ensure_ascii=False), outcome))
                con.commit()
            except MarketingDraftError as exc:
                if request.is_json:
                    return jsonify(error=str(exc), code='invalid_submission'), 400
                return render_template_string(FORM, config=config, submission=values.get('submissionId', '') if isinstance(values, dict) else '',
                                              revision=row['revision'],
                                              values={k: v for k, v in values.items() if k not in ('emailConsent', 'whatsappConsent')} if isinstance(values, dict) else {}, error=str(exc)), 400
        if request.is_json:
            return jsonify(accepted=True)
        return '<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Enquiry received</title><h1>Thank you</h1><p>Your submission was received. No marketing messages have been sent.</p></html>'
