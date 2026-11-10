"""Opt-in signed payment evidence and separately authorised captured-sale intake.

Use a dedicated Connect snapshot endpoint pinned to API_VERSION. Resolvers and
payment authority are trusted bounded local reads. No provider reads on delivery.
Event snapshots require an explicit current-state check before correction.
Inject PaymentEventConfig(enabled=True, resolve=...) via payment_event_config.
The resolver maps an opaque endpoint token to an exact PaymentEventBinding;
PaymentConfig must separately authorise the same business/account/version.
Subscribe to the explicit EVENT_KINDS snapshot allowlist below. Refund/dispute
objects are individual signals, never aggregate charge observations. Only an
endpoint with record_sales=True may append fully captured sale snapshots whose
metadata identifies an existing owned campaign/enquiry. That flag requires
separate owner-approved sale-recording authority; read authority alone is not
permission. Other unknown charges are acknowledged without association.
Sale dates are snapshot observation dates, not settlement dates. Historical
snapshots do not prove current refund state: owners must explicitly recheck.
No automatic monitoring guarantee: disabled/revoked/rotated endpoints need
operator recovery, and the owner can still use exact-payment status checks.
"""
from contextlib import closing
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import time

from flask import request
from business_marketing_drafts import MarketingDraftError, _id
from business_growthrova_payments import binding_for, payment_sale, record_captured_sale
from business_growthrova_payment_review import observation

ENDPOINT = 'growthrova_payment_event'
PATH = '/api/growthrova/payment-events/<token>'
API_VERSION = '2026-10-28.endive'
EVENT_KINDS = {
    'charge.refunded': 'charge', 'charge.updated': 'charge',
    'charge.succeeded': 'sale', 'charge.captured': 'sale',
    'refund.created': 'refund', 'refund.updated': 'refund', 'refund.failed': 'refund',
    'charge.refund.updated': 'refund',
    **{f'charge.dispute.{name}': 'dispute' for name in
       ('created', 'updated', 'closed', 'funds_withdrawn', 'funds_reinstated')},
}


def object_signal(value, kind, receipt, created):
    """Retain only an individual object's signal, not inferred charge totals.

    Refund metadata need not copy charge metadata. The existing immutable
    account/charge receipt is the association authority. Disputes can have a
    different amount/currency from the charge; never convert or net them here.
    """
    prefix = 're' if kind == 'refund' else 'du'
    statuses = (('pending', 'requires_action', 'succeeded', 'failed', 'canceled') if kind == 'refund' else
                ('warning_needs_response', 'warning_under_review', 'warning_closed',
                 'needs_response', 'under_review', 'appeal_needs_response',
                 'appeal_under_review', 'won', 'lost', 'prevented'))
    if (value.get('object') != kind or not isinstance(value.get('id'), str)
            or not re.fullmatch(prefix + r'_[A-Za-z0-9]{1,100}', value['id'])
            or value.get('status') not in statuses
            or type(value.get('amount')) is not int or not 0 < value['amount'] <= 99999999999
            or not isinstance(value.get('currency'), str) or not re.fullmatch('[a-z]{3}', value['currency'])
            or type(value.get('created')) is not int
            or not receipt['charge_created'] <= value['created'] <= created
            or ('livemode' in value and value['livemode'] is not True)):
        raise ValueError('Invalid payment object signal')
    initial = json.loads(receipt['sale_json'])
    if kind == 'refund':
        major, minor = initial['amount'].split('.')
        if value['currency'].upper() != initial['currency'] or value['amount'] > int(major)*100+int(minor):
            raise ValueError('Refund does not match original capture')
    amount = value['amount']
    # Integer minor units are deliberate: dispute currency may have a different
    # exponent. UI formats via Intl rather than assuming two decimal places.
    return dict(checkedAt=created, objectKind=kind, objectId=value['id'],
                objectStatus=value['status'], objectAmountMinor=amount,
                objectCurrency=value['currency'].upper())


@dataclass(frozen=True)
class PaymentEventBinding:
    owner_id: str
    organisation_id: str
    account_id: str
    connection_version: str
    signing_secret: str = field(repr=False)
    record_sales: bool = False


@dataclass(frozen=True)
class PaymentEventConfig:
    enabled: bool = False
    resolve: object = field(default=None, repr=False)


def signed_event(raw, signature, secret, now):
    if len(raw) > 65536 or len(signature) > 4096:
        raise ValueError('Event too large')
    fields = [part.strip().partition('=') for part in signature.split(',')]
    stamps = [value for key, _, value in fields if key == 't']
    if len(stamps) != 1 or not re.fullmatch(r'[0-9]{1,12}', stamps[0]) or abs(now-int(stamps[0])) > 300:
        raise ValueError('Invalid signature timestamp')
    digest = hmac.new(secret.encode(), stamps[0].encode()+b'.'+raw, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(digest, value) for key, _, value in fields
               if key == 'v1' and re.fullmatch('[a-f0-9]{64}', value)):
        raise ValueError('Invalid signature')
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get('livemode') is not True
            or value.get('api_version') != API_VERSION
            or not isinstance(value.get('id'), str) or not re.fullmatch(r'evt_[A-Za-z0-9]{1,100}', value['id'])
            or type(value.get('created')) is not int or not 0 < value['created'] <= now):
        raise ValueError('Invalid snapshot event')
    return value


def register_payment_events(app, repo, payment_config, config=None):
    config = config or PaymentEventConfig()

    def resolve(token):
        if config.enabled is not True or not callable(config.resolve) or not re.fullmatch('[A-Za-z0-9_-]{16,160}', token):
            raise ValueError('Unavailable')
        event_binding = config.resolve(token)
        if (not isinstance(event_binding, PaymentEventBinding)
                or not isinstance(event_binding.signing_secret, str)
                or not re.fullmatch('whsec_[A-Za-z0-9]{1,200}', event_binding.signing_secret)):
            raise ValueError('Unavailable')
        binding = binding_for(payment_config, (event_binding.owner_id, event_binding.organisation_id))
        if (binding.account_id != event_binding.account_id or binding.version != event_binding.connection_version):
            raise ValueError('Connection changed')
        return event_binding, binding

    @app.post(PATH, endpoint=ENDPOINT)
    def receive(token):
        request.max_content_length = 65536
        try:
            endpoint, binding = resolve(token)
            event = signed_event(request.get_data(), request.headers.get('Stripe-Signature', ''),
                                 endpoint.signing_secret, time.time())
            if event.get('account') != binding.account_id:
                raise ValueError('Account mismatch')
            kind = EVENT_KINDS.get(event.get('type'))
            if kind is None:
                return '', 204
            value = event.get('data', {}).get('object')
            if not isinstance(value, dict):
                raise ValueError('Invalid payment object')
            # Snapshot endpoint expects unexpanded charge identities. A missing
            # association (e.g. a refund not yet tied to a charge) is ignored.
            charge_id = value.get('id') if kind in ('charge', 'sale') else value.get('charge')
            if charge_id is None and kind == 'refund':
                return '', 204
            if not isinstance(charge_id, str) or not re.fullmatch(r'ch_[A-Za-z0-9]{1,100}', charge_id):
                raise ValueError('Invalid charge identity')
            with closing(repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                receipt = con.execute('SELECT * FROM growthrova_payment_receipts WHERE account_id=? AND charge_id=?',
                                      (binding.account_id, charge_id)).fetchone()
                scope = (binding.owner_id, binding.organisation_id)
                if kind == 'sale':
                    if endpoint.record_sales is not True:
                        return '', 204
                    metadata = value.get('metadata')
                    if not isinstance(metadata, dict):
                        raise ValueError('Missing sale association')
                    campaign = _id(metadata.get('growthrova_campaign_id'))
                    lead = _id(metadata.get('growthrova_enquiry_id'))
                    sale = payment_sale(value, charge_id, scope, campaign, lead, event['created'])
                    if not repo._owned(con, campaign, scope):
                        raise ValueError('Campaign unavailable')
                    row = con.execute('SELECT * FROM growthrova_leads WHERE id=? AND owner_id=? '
                        'AND organisation_id=? AND document_id=?', (lead, *scope, campaign)).fetchone()
                    if row is None:
                        raise ValueError('Enquiry unavailable')
                    if receipt is not None:
                        if (receipt['owner_id'], receipt['organisation_id'], receipt['document_id'],
                                receipt['lead_id'], receipt['connection_version']) != (*scope, campaign, lead, binding.version):
                            raise ValueError('Payment already associated elsewhere')
                        # Never replay purchases, owner corrections or newer status evidence.
                        if resolve(token) != (endpoint, binding):
                            raise ValueError('Authority changed')
                        return '', 204
                    record_captured_sale(con, scope, campaign, row, binding, value, sale,
                        event['created'], expected_revision=row['revision'], actor_id='stripe_payment_event')
                    # Retain minimal provenance without a new schema. Even a signed
                    # successful snapshot needs GET before any later correction.
                    observed = dict(checkedAt=event['created'], refundedAmount='0.00',
                        fullyRefunded=False, disputed=False, source='stripe_event',
                        eventId=event['id'], eventType=event['type'], receivedAt=time.time(), needsRecheck=True)
                    con.execute('INSERT INTO growthrova_payment_checks VALUES(?,?,?,?)',
                        (binding.account_id, charge_id, 1, json.dumps(observed, sort_keys=True)))
                    if resolve(token) != (endpoint, binding):
                        raise ValueError('Authority changed')
                    con.commit()
                    return '', 204
                # Evidence-only events never create an association.
                if receipt is None:
                    return '', 204
                if ((receipt['owner_id'], receipt['organisation_id']) != scope
                        or receipt['connection_version'] != binding.version
                        or not repo._owned(con, receipt['document_id'], scope)
                        or con.execute('SELECT 1 FROM growthrova_leads WHERE id=? AND owner_id=? AND organisation_id=? AND document_id=?',
                            (receipt['lead_id'], *scope, receipt['document_id'])).fetchone() is None):
                    raise ValueError('Association unavailable')
                observed = (observation(value, receipt, scope, receipt['document_id'], receipt['lead_id'], event['created'])
                            if kind == 'charge' else object_signal(value, kind, receipt, event['created']))
                old = con.execute('SELECT * FROM growthrova_payment_checks WHERE account_id=? AND charge_id=?',
                                  (binding.account_id, charge_id)).fetchone()
                previous = json.loads(old['observation_json']) if old else None
                # Delivery order is not resource order. Same-second snapshots are
                # not used for correction either; any event evidence needs GET.
                if event['created'] <= (previous['checkedAt'] if previous else receipt['recorded']):
                    return '', 204
                observed.update(source='stripe_event', eventId=event['id'], eventType=event['type'],
                                receivedAt=time.time(), needsRecheck=True)
                con.execute('INSERT INTO growthrova_payment_checks VALUES(?,?,?,?) '
                    'ON CONFLICT(account_id,charge_id) DO UPDATE SET version=excluded.version, observation_json=excluded.observation_json',
                    (binding.account_id, charge_id, old['version']+1 if old else 1, json.dumps(observed, sort_keys=True)))
                if resolve(token) != (endpoint, binding):
                    raise ValueError('Authority changed')
                con.commit()
            return '', 204
        except (MarketingDraftError, ValueError, TypeError, KeyError, OverflowError, AttributeError):
            return '', 400
