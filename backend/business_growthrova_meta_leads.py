"""Explicitly bound Meta leadgen notifications; no ambient grants or hosting.

Signature authenticates the app notification, not tenant/account authority.
Host callbacks must affirm current Page/form/CRM ownership independently.
Wire reference: https://github.com/facebookincubator/catalogue-of-api-solutions/
blob/main/solutions/leads/leads-retrieval-set-up-checker.md
Signature/handshake contract: https://developers.facebook.com/docs/graph-api/webhooks/getting-started/
Connected protocol verification is required before host installation.
"""
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re

import requests
from flask import jsonify, request
from business_growthrova_provider_leads import normalise_origin, record_provider_event

ENDPOINT = 'growthrova_meta_lead_event'
PATH = '/api/growthrova/meta-lead-events/<token>'


@dataclass(frozen=True)
class MetaLeadBinding:
    owner_id: str
    organisation_id: str
    document_id: str
    account_id: str
    page_id: str
    form_id: str
    version: str
    graph_version: str
    access_token: str = field(repr=False)


@dataclass(frozen=True)
class MetaLeadConfig:
    enabled: bool = False
    app_secret: str = field(default='', repr=False)
    verify_token: str = field(default='', repr=False)
    resolve: object = field(default=None, repr=False)  # (path token, Page ID, form ID)
    authorised: object = field(default=None, repr=False)  # Current binding authority.
    http: object = field(default=None, repr=False)


def reference(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,39}', value):
        raise ValueError('Invalid Meta reference')
    return value


def read_lead(binding, lead_id, config):
    """One exact-object read. Never follow URLs returned in provider data."""
    proof = hmac.new(config.app_secret.encode(), binding.access_token.encode(), hashlib.sha256).hexdigest()
    with requests.Session() as session:
        session.trust_env = False
        transport = config.http or session
        with transport.get(f'https://graph.facebook.com/{binding.graph_version}/{reference(lead_id)}',
                params=dict(fields='id,form_id,created_time,field_data', appsecret_proof=proof),
                headers={'Authorization': 'Bearer ' + binding.access_token},
                timeout=(3, 6), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise ValueError('Lead read unavailable')
            body = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                body.extend(chunk)
                if len(body) > 32768:
                    raise ValueError('Lead response too large')
            value = json.loads(body)
    if (not isinstance(value, dict) or value.get('error') or value.get('id') != lead_id
            or value.get('form_id') != binding.form_id):
        raise ValueError('Lead identity mismatch')
    return value


def lead_data(value, binding):
    stamp = value.get('created_time')
    if not isinstance(stamp, str) or len(stamp) > 40:
        raise ValueError('Missing submission time')
    parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.microsecond:
        raise ValueError('Invalid submission time')
    origin = normalise_origin(dict(platform='meta', accountId=binding.account_id,
        formId=binding.form_id, eventId=value['id'], campaignReference='',
        submittedAt=parsed.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        verification='meta_signed_retrieval'))
    columns = value.get('field_data')
    if not isinstance(columns, list) or len(columns) > 100:
        raise ValueError('Unsupported contact fields')
    fields = {}
    for column in columns:
        if not isinstance(column, dict):
            raise ValueError('Unsupported contact fields')
        key = column.get('name')
        if not isinstance(key, str) or key not in ('full_name', 'first_name', 'last_name', 'email', 'phone_number'):
            continue
        values = column.get('values')
        if key in fields or not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
            raise ValueError('Ambiguous contact field')
        fields[key] = values[0]
    return dict(name=fields.get('full_name') or ' '.join(filter(None, (fields.get('first_name'), fields.get('last_name')))),
        email=fields.get('email', ''), phone=fields.get('phone_number', ''), notes='',
        source='Meta lead form · signed notification and retrieval', sourceReference=value['id'],
        status='new', qualification='', booking='', permissionNotes='',
        emailPermission='unknown', whatsappPermission='unknown', providerOrigin=origin)


def notifications(payload):
    if not isinstance(payload, dict) or payload.get('object') != 'page':
        raise ValueError('Use Page notifications')
    entries = payload.get('entry')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 5:
        raise ValueError('Unsupported batch')
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid Page entry')
        page = reference(entry.get('id'))
        changes = entry.get('changes')
        if not isinstance(changes, list) or len(changes) > 5:
            raise ValueError('Unsupported batch')
        for change in changes:
            if not isinstance(change, dict):
                raise ValueError('Invalid change')
            if change.get('field') != 'leadgen':
                continue
            value = change.get('value')
            if not isinstance(value, dict) or reference(value.get('page_id')) != page:
                raise ValueError('Page mismatch')
            result.append((page, reference(value.get('form_id')), reference(value.get('leadgen_id'))))
    if len(result) > 5:
        raise ValueError('Unsupported batch')
    return result


def register_meta_lead_events(app, repo, config=None):
    config = config or MetaLeadConfig()

    def available():
        return (config.enabled is True and callable(config.resolve) and callable(config.authorised)
                and isinstance(config.app_secret, str) and 32 <= len(config.app_secret) <= 512
                and isinstance(config.verify_token, str) and 32 <= len(config.verify_token) <= 512)

    def resolve(token, page, form):
        binding = config.resolve(token, page, form)
        if not isinstance(binding, MetaLeadBinding):
            raise ValueError('Binding unavailable')
        if (not all(isinstance(v, str) and v and len(v) <= 160 for v in (
                binding.owner_id, binding.organisation_id, binding.document_id, binding.version))
                or binding.page_id != page or binding.form_id != form
                or not isinstance(binding.graph_version, str)
                or not re.fullmatch(r'v[1-9][0-9]{0,2}\.0', binding.graph_version)
                or not isinstance(binding.access_token, str) or not 1 <= len(binding.access_token) <= 8192
                or any(ord(c) < 32 for c in binding.access_token)
                or config.authorised(binding) is not True):
            raise ValueError('Binding unavailable')
        reference(binding.account_id)
        return binding

    def owned(con, binding):
        return repo._owned(con, binding.document_id, (binding.owner_id, binding.organisation_id))

    @app.route(PATH, methods=['GET', 'POST'], endpoint=ENDPOINT)
    def receive(token):
        request.max_content_length = 32768
        if not available() or not re.fullmatch(r'[a-f0-9]{32}', token):
            return jsonify(message='Unavailable'), 404
        if request.method == 'GET':
            supplied = request.args.get('hub.verify_token', '')
            challenge = request.args.get('hub.challenge', '')
            if (request.args.get('hub.mode') != 'subscribe' or len(supplied) > 512
                    or not hmac.compare_digest(supplied.encode(), config.verify_token.encode())
                    or not re.fullmatch(r'[0-9]{1,100}', challenge)):
                return jsonify(message='Verification denied'), 403
            return app.response_class(challenge, mimetype='text/plain')
        if request.query_string or request.mimetype != 'application/json':
            return jsonify(message='Use JSON'), 400
        raw = request.get_data()
        expected = 'sha256=' + hmac.new(config.app_secret.encode(), raw, hashlib.sha256).hexdigest()
        signature = request.headers.get('X-Hub-Signature-256', '')
        if len(signature) != len(expected) or not hmac.compare_digest(signature.encode(), expected.encode()):
            return jsonify(message='Invalid signature'), 403
        try:
            events = notifications(json.loads(raw))
        except (ValueError, TypeError):
            return jsonify(message='Unsupported notification'), 400
        try:
            for page, form, lead_id in events:
                binding = resolve(token, page, form)
                scope = (binding.owner_id, binding.organisation_id)
                # Receipt lookup avoids another Graph read after restart or a
                # human CRM correction. All prior writes were identity-checked.
                with closing(repo._connect()) as con:
                    if not owned(con, binding):
                        raise ValueError('Campaign unavailable')
                    old = con.execute('SELECT document_id,form_id FROM growthrova_provider_lead_receipts '
                        'WHERE owner_id=? AND organisation_id=? AND platform=? AND account_id=? AND event_id=?',
                        (*scope, 'meta', binding.account_id, lead_id)).fetchone()
                if old:
                    if old['document_id'] != binding.document_id or old['form_id'] != form:
                        raise ValueError('Event binding changed')
                    if resolve(token, page, form) != binding:
                        raise ValueError('Binding changed')
                    with closing(repo._connect()) as con:
                        if not owned(con, binding):
                            raise ValueError('Campaign unavailable')
                    continue
                value = read_lead(binding, lead_id, config)  # No database write lock during HTTP.
                data = lead_data(value, binding)
                if resolve(token, page, form) != binding:
                    raise ValueError('Binding changed')
                with closing(repo._connect()) as con:
                    con.execute('BEGIN IMMEDIATE')
                    if not owned(con, binding) or resolve(token, page, form) != binding:
                        raise ValueError('Binding changed')
                    record_provider_event(con, scope, binding.document_id, data, actor_id='meta-lead-webhook')
                    if resolve(token, page, form) != binding or not owned(con, binding):
                        raise ValueError('Binding changed')
                    con.commit()
        except Exception:
            # Partial commits are durable and replay-safe. Never echo contact,
            # credential, provider exception URL or receipt details to callers.
            return jsonify(message='Enquiry intake unavailable; retry the notification.'), 503
        return jsonify({})
