"""Opt-in Google lead-form webhook, using Google's confidential shared key.

Not a signature, account grant, attribution proof or messaging permission.
Only explicit operator bindings select tenants; request fields never do so.
Reference: https://developers.google.com/google-ads/webhook/docs/implementation
"""
from contextlib import closing
from dataclasses import dataclass, field
import hmac
import re

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _text
from business_growthrova_provider_leads import normalise_origin, record_provider_event

ENDPOINT = 'growthrova_google_lead_event'
PATH = '/api/growthrova/google-lead-events/<token>'


@dataclass(frozen=True)
class GoogleLeadBinding:
    owner_id: str
    organisation_id: str
    document_id: str
    customer_id: str  # Operator binding: the webhook carries no customer ID.
    campaign_id: str
    form_id: str
    version: str
    shared_key: str = field(repr=False)


@dataclass(frozen=True)
class GoogleLeadConfig:
    enabled: bool = False
    resolve: object = field(default=None, repr=False)
    authorised: object = field(default=None, repr=False)


def numeric_id(value):
    if type(value) not in (str, int):
        raise MarketingDraftError('Use a valid Google reference.')
    value = str(value)
    if not re.fullmatch(r'[1-9][0-9]{0,18}', value) or int(value) > 2**63 - 1:
        raise MarketingDraftError('Use a valid Google reference.')
    return value


def lead_data(payload, binding):
    """Only consumed fields affect replay; unknown provider fields are ignored."""
    event = _text(payload.get('lead_id'), 'lead_id', 160).strip()
    origin = normalise_origin(dict(platform='google', accountId=binding.customer_id,
        formId=binding.form_id, eventId=event, campaignReference=binding.campaign_id,
        submittedAt=payload.get('lead_submit_time', ''), verification='google_shared_key'))
    if payload.get('lead_source', 'LEAD_FORM') != 'LEAD_FORM':
        raise MarketingDraftError('Only lead-form submissions are supported.')
    columns = payload.get('user_column_data')
    if not isinstance(columns, list) or len(columns) > 100:
        raise MarketingDraftError('Use supported Google contact fields.')
    supported = {'FULL_NAME', 'FIRST_NAME', 'LAST_NAME', 'EMAIL', 'PHONE_NUMBER'}
    values = {}
    for column in columns:
        if not isinstance(column, dict):
            raise MarketingDraftError('Use supported Google contact fields.')
        key = column.get('column_id')
        if not isinstance(key, str) or key not in supported:
            continue
        if key in values:
            raise MarketingDraftError('Repeated contact fields are not supported.')
        values[key] = _text(column.get('string_value'), key, 254).strip()
    name = values.get('FULL_NAME') or ' '.join(filter(None, (values.get('FIRST_NAME'), values.get('LAST_NAME'))))
    return dict(name=name, email=values.get('EMAIL', ''), phone=values.get('PHONE_NUMBER', ''),
        notes='', source='Google lead form · shared-key webhook', sourceReference=event,
        status='new', qualification='', booking='', permissionNotes='',
        emailPermission='unknown', whatsappPermission='unknown', providerOrigin=origin)


def register_google_lead_events(app, repo, config=None):
    config = config or GoogleLeadConfig()

    def resolve(token):
        if config.enabled is not True or not callable(config.resolve) or not callable(config.authorised):
            return None
        binding = config.resolve(token)
        if not isinstance(binding, GoogleLeadBinding):
            return None
        if (not all(isinstance(v, str) and v for v in (binding.owner_id, binding.organisation_id,
                binding.document_id, binding.version)) or not isinstance(binding.shared_key, str)
                or not 32 <= len(binding.shared_key) <= 512):
            return None
        for value in (binding.customer_id, binding.campaign_id, binding.form_id):
            if numeric_id(value) != value:
                return None
        # Host must explicitly verify current business/form authority. A shared
        # key alone cannot establish ownership or continued access to an account.
        return binding if config.authorised(binding) is True else None

    @app.post(PATH, endpoint=ENDPOINT)
    def receive(token):
        request.max_content_length = 32768
        if not re.fullmatch(r'[a-f0-9]{32}', token) or request.query_string:
            return jsonify(message='Unavailable'), 404
        try:
            binding = resolve(token)
        except Exception:
            return jsonify(message='Binding check unavailable'), 503
        if binding is None:
            return jsonify(message='Unavailable'), 404
        if request.mimetype != 'application/json':
            return jsonify(message='Use JSON'), 400
        payload = request.get_json(silent=True)
        key = payload.get('google_key') if isinstance(payload, dict) else None
        if (not isinstance(key, str) or len(key) > 512
                or not hmac.compare_digest(key.encode(), binding.shared_key.encode())):
            return jsonify(message='Invalid key'), 403
        try:
            if (numeric_id(payload.get('form_id')) != binding.form_id
                    or numeric_id(payload.get('campaign_id')) != binding.campaign_id):
                return jsonify(message='Form binding mismatch'), 403
            if type(payload.get('is_test', False)) is not bool:
                raise MarketingDraftError('Use a boolean test indicator.')
            data = lead_data(payload, binding)
            scope = (binding.owner_id, binding.organisation_id)
            with closing(repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                if not repo._owned(con, binding.document_id, scope):
                    return jsonify(message='Unavailable'), 404
                # Test payloads validate parsing but never enter the enquiry or
                # receipt ledger, so they cannot contaminate business results.
                from business_growthrova_leads import normalise
                normalise(data)
                if not payload.get('is_test', False):
                    record_provider_event(con, scope, binding.document_id, data, actor_id='google-lead-webhook')
                try:
                    current = resolve(token)
                except Exception:
                    return jsonify(message='Binding check unavailable'), 503
                if current != binding or not repo._owned(con, binding.document_id, scope):
                    return jsonify(message='Binding changed'), 403
                con.commit()
        except MarketingDraftError as exc:
            # Never echo provider payload, key, contact data or internal receipts.
            status = 503 if exc.code == 'storage_limit' else exc.status
            return jsonify(message='Enquiry could not be retained; review the form configuration.'), status
        return jsonify({})
