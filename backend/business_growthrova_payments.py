"""Explicit read-only payment observations. No payment or billing mutations.

Operator bindings must use dedicated account-scoped read credentials and fresh
authority. Metadata is an integration association, not advertising attribution.
Receipts retain the initial observation; explicit rechecks retain later refund/dispute evidence.
Inject PaymentConfig through create_growthrova_preview(payment_config=...). Both
callbacks must be bounded trusted local reads; rotate version on account/key/grant
changes. Connect account read permissions and charge metadata must be configured
outside this module. No access to the Growthrova subscription account is implied.
"""
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
import secrets
import time

import requests
from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id
from business_marketing_offline import OfflineDocumentAccessError
from business_growthrova_leads import persist_lead, lead_snapshot
from business_growthrova_sales import normalise_sale, observed_sales


@dataclass(frozen=True)
class PaymentBinding:
    owner_id: str
    organisation_id: str
    account_id: str
    version: str
    read_key: str = field(repr=False)


@dataclass(frozen=True)
class PaymentConfig:
    enabled: bool = False
    resolve: object = field(default=None, repr=False)
    authorised: object = field(default=None, repr=False)
    http: object = field(default=None, repr=False)


def binding_for(config, scope):
    if config.enabled is not True or not callable(config.resolve) or not callable(config.authorised):
        raise MarketingDraftError('Payment checks need a dedicated business read connection.', 'payment_disconnected', 409)
    value = config.resolve(*scope)
    if (not isinstance(value, PaymentBinding) or (value.owner_id, value.organisation_id) != scope
            or not isinstance(value.account_id, str) or not re.fullmatch(r'acct_[A-Za-z0-9]{1,100}', value.account_id)
            or not isinstance(value.version, str) or not 1 <= len(value.version) <= 160
            or not isinstance(value.read_key, str) or not value.read_key.startswith('rk_live_')
            or config.authorised(value) is not True):
        raise MarketingDraftError('Payment read access is unavailable. Ask the operator to check this business connection.', 'payment_disconnected', 409)
    return value


def read_charge(config, binding, ident):
    # No netrc, ambient proxies, redirects, arbitrary URLs, expansions or retries.
    with requests.Session() as session:
        session.trust_env = False
        with (config.http or session).get('https://api.stripe.com/v1/charges/' + ident,
                headers={'Authorization': 'Bearer ' + binding.read_key,
                         'Stripe-Account': binding.account_id, 'Stripe-Version': '2026-10-28.endive'},
                timeout=(3, 10), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise ValueError('Payment read unconfirmed')
            body = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError('Payment response too large')
            return json.loads(body)


def payment_sale(value, charge, scope, campaign, lead, observed_at):
    if (not isinstance(value, dict) or value.get('id') != charge or value.get('object') != 'charge'
            or value.get('livemode') is not True or value.get('status') != 'succeeded'
            or value.get('paid') is not True or value.get('captured') is not True
            or value.get('refunded') is not False or value.get('disputed') is not False
            or type(value.get('amount_refunded')) is not int or value['amount_refunded'] != 0
            or type(value.get('amount')) is not int or not 0 < value['amount'] <= 99999999999
            or type(value.get('amount_captured')) is not int or value['amount_captured'] != value['amount']
            or type(value.get('created')) is not int or not 0 < value['created'] <= observed_at
            or not isinstance(value.get('metadata'), dict)
            or any(value['metadata'].get(key) != expected for key, expected in (
                ('growthrova_business_id', scope[1]), ('growthrova_campaign_id', campaign),
                ('growthrova_enquiry_id', lead)))):
        raise ValueError('Payment state or association not verified')
    currency = value.get('currency')
    if not isinstance(currency, str) or not re.fullmatch('[a-z]{3}', currency):
        raise ValueError('Unsupported payment currency')
    amount = value['amount_captured']
    return normalise_sale(dict(amount=f'{amount // 100}.{amount % 100:02}', currency=currency.upper(),
        date=datetime.fromtimestamp(observed_at, timezone.utc).date().isoformat(),
        sourceReference='Stripe charge ' + charge, state='recorded', correctionNote=''))


def record_captured_sale(con, scope, campaign, row, binding, charge, sale, observed_at,
                         *, expected_revision, actor_id=None):
    """Caller owns exclusive transaction, duplicate receipt and authority checks.

    Shared by explicit verification and separately authorised signed sale intake.
    Receipt and revisioned purchase commit together; no external work occurs.
    """
    data = json.loads(row['data_json'])
    if any(item['sourceReference'] == sale['sourceReference'] for item in observed_sales(data)):
        raise MarketingDraftError('This payment reference already has an owner-recorded purchase. Review it instead of adding another.', 'payment_conflict', 409)
    if con.execute('SELECT count(*) FROM growthrova_payment_receipts WHERE owner_id=? '
                   'AND organisation_id=?', scope).fetchone()[0] >= 5000:
        raise MarketingDraftError('Payment observation storage is full.', 'storage_limit', 409)
    if not data.get('sale'):
        purchase_key = 'sale'
        data['sale'] = sale
    else:
        purchase_key = secrets.token_hex(16)
        data['purchases'] = data.get('purchases', []) + [dict(sale, id=purchase_key)]
    enquiry, _ = persist_lead(con, scope, campaign, dict(id=row['id'],
        expectedRevision=expected_revision, mutationId=secrets.token_hex(16), data=data), actor_id=actor_id)
    con.execute('INSERT INTO growthrova_payment_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
        (binding.account_id, charge['id'], *scope, campaign, row['id'], binding.version,
         purchase_key, enquiry['revision'], json.dumps(sale, sort_keys=True), charge['created'], observed_at))
    return enquiry


def register_payment_routes(app, repo, root, *, config=None, revalidate=None):
    config = config or PaymentConfig()
    with closing(repo._connect()) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS growthrova_payment_receipts(
            account_id TEXT NOT NULL, charge_id TEXT NOT NULL, owner_id TEXT NOT NULL,
            organisation_id TEXT NOT NULL, document_id TEXT NOT NULL, lead_id TEXT NOT NULL,
            connection_version TEXT NOT NULL, purchase_key TEXT NOT NULL, lead_revision INTEGER NOT NULL,
            sale_json TEXT NOT NULL, charge_created INTEGER NOT NULL, recorded REAL NOT NULL,
            PRIMARY KEY(account_id,charge_id))''')
        con.commit()

    def checked(con, org, campaign, lead, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error, None
        if repo._scope(org) != scope or not repo._owned(con, campaign, scope):
            raise OfflineDocumentAccessError('Campaign access changed')
        row = con.execute('SELECT * FROM growthrova_leads WHERE id=? AND owner_id=? '
                          'AND organisation_id=? AND document_id=?', (lead, *scope, campaign)).fetchone()
        if row is None:
            raise OfflineDocumentAccessError('Enquiry access denied')
        return None, row

    @app.post(root + '/<ident>/leads/<lead_id>/payment')
    def growthrova_record_payment(organisation_id, ident, lead_id):
        request.max_content_length = 2000
        value = request.get_json(silent=True)
        if (not isinstance(value, dict) or set(value) != {'chargeId', 'expectedRevision', 'confirmed'}
                or value['confirmed'] is not True or type(value['expectedRevision']) is not int
                or not 1 <= value['expectedRevision'] < 500
                or not isinstance(value['chargeId'], str)
                or not re.fullmatch(r'ch_[A-Za-z0-9]{1,100}', value['chargeId'])):
            raise MarketingDraftError('Confirm the exact payment reference and saved enquiry version.')
        _id(lead_id)
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        binding = binding_for(config, scope)

        def replay(con, row):
            receipt = con.execute('SELECT * FROM growthrova_payment_receipts WHERE account_id=? '
                                  'AND charge_id=?', (binding.account_id, value['chargeId'])).fetchone()
            if receipt is None:
                return None
            if (receipt['owner_id'], receipt['organisation_id'], receipt['document_id'], receipt['lead_id']) != (*scope, ident, lead_id):
                raise MarketingDraftError('This payment is already associated with another enquiry.', 'payment_conflict', 409)
            return dict(enquiry=lead_snapshot(con, row), replayed=True, observedAt=receipt['recorded'])

        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            error, row = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            result = replay(con, row)
            if result:
                if binding_for(config, scope) != binding:
                    raise MarketingDraftError('Payment connection changed.', 'payment_connection_changed', 409)
                response = jsonify(result)
                response.headers['Cache-Control'] = 'no-store'
                return response
            if row['revision'] != value['expectedRevision']:
                raise MarketingDraftError('Reopen the saved enquiry before recording a payment.', 'revision_conflict', 409)
        try:
            charge = read_charge(config, binding, value['chargeId'])
            observed_at = time.time()
            sale = payment_sale(charge, value['chargeId'], scope, ident, lead_id, observed_at)
        except (requests.RequestException, ValueError, TypeError, OverflowError):
            raise MarketingDraftError('Payment could not be verified. Check its reference, business association, captured amount, refunds and disputes. Nothing was recorded.', 'payment_unverified', 409) from None
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error, row = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            if binding_for(config, scope) != binding:
                raise MarketingDraftError('Payment connection changed. Reopen before trying again.', 'payment_connection_changed', 409)
            result = replay(con, row)
            if not result:
                enquiry = record_captured_sale(con, scope, ident, row, binding, charge, sale,
                    observed_at, expected_revision=value['expectedRevision'])
                result = dict(enquiry=enquiry, replayed=False, observedAt=observed_at)
            error, _ = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            if binding_for(config, scope) != binding:
                raise MarketingDraftError('Payment connection changed. Nothing was recorded.', 'payment_connection_changed', 409)
            con.commit()
        response = jsonify(result)
        response.headers['Cache-Control'] = 'no-store'
        return response

    from business_growthrova_payment_review import register_payment_review
    register_payment_review(app, repo, root, config=config, checked=checked)
    from business_growthrova_payment_queue import register_payment_queue
    register_payment_queue(app, repo, root, revalidate=revalidate)
