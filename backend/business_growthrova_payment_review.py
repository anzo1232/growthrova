"""Saved, minimal payment evidence. Rechecks never mutate purchases or billing."""
from contextlib import closing
import json
import time

import requests
from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id
from business_growthrova_payments import binding_for, read_charge, payment_sale


def observation(value, receipt, scope, campaign, lead, now):
    # Reuse the initial strict identity/capture/currency checks, permitting only
    # the refund/dispute fields to differ. Never retain raw customer payloads.
    if (not isinstance(value, dict) or type(value.get('amount_refunded')) is not int
            or type(value.get('amount_captured')) is not int
            or not 0 <= value['amount_refunded'] <= value['amount_captured']
            or type(value.get('refunded')) is not bool
            or value['refunded'] != (value['amount_refunded'] == value['amount_captured'])
            or type(value.get('disputed')) is not bool):
        raise ValueError('Invalid refund/dispute observation')
    initial = json.loads(receipt['sale_json'])
    sale = payment_sale(dict(value, amount_refunded=0, refunded=False, disputed=False),
                        receipt['charge_id'], scope, campaign, lead, now)
    if (sale['amount'] != initial['amount'] or sale['currency'] != initial['currency']
            or value['created'] != receipt['charge_created']):
        raise ValueError('Original payment identity changed')
    refunded = value['amount_refunded']
    return dict(checkedAt=now, refundedAmount=f'{refunded // 100}.{refunded % 100:02}',
                fullyRefunded=value['refunded'], disputed=value['disputed'])


def register_payment_review(app, repo, root, *, config, checked):
    with closing(repo._connect()) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS growthrova_payment_checks(
            account_id TEXT NOT NULL, charge_id TEXT NOT NULL, version INTEGER NOT NULL,
            observation_json TEXT NOT NULL, PRIMARY KEY(account_id,charge_id))''')
        con.commit()

    def receipts(con, scope, campaign, lead):
        return con.execute('SELECT * FROM growthrova_payment_receipts WHERE owner_id=? '
            'AND organisation_id=? AND document_id=? AND lead_id=? ORDER BY recorded DESC, charge_id LIMIT 101',
            (*scope, campaign, lead)).fetchall()

    def previous(con, receipt):
        return con.execute('SELECT * FROM growthrova_payment_checks WHERE account_id=? AND charge_id=?',
                           (receipt['account_id'], receipt['charge_id'])).fetchone()

    def project(con, receipt, row):
        initial = json.loads(receipt['sale_json'])
        data = json.loads(row['data_json'])
        current = (data.get('sale') if receipt['purchase_key'] == 'sale' else
                   next((item for item in data.get('purchases', []) if item['id'] == receipt['purchase_key']), None))
        if current:
            current = {key: current[key] for key in initial}
        check = previous(con, receipt)
        return dict(accountId=receipt['account_id'], chargeId=receipt['charge_id'],
            purchaseKey=receipt['purchase_key'], initial=initial, initialCheckedAt=receipt['recorded'],
            current=current, ownerChanged=current != initial,
            latest=json.loads(check['observation_json']) if check else None)

    def reply(value):
        response = jsonify(value)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get(root + '/<ident>/leads/<lead_id>/payment/receipts')
    def growthrova_payment_receipts(organisation_id, ident, lead_id):
        _id(lead_id)
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            error, row = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            saved = receipts(con, scope, ident, lead_id)
            result = dict(receipts=[project(con, item, row) for item in saved[:100]],
                          hasMore=len(saved) > 100, enquiryRevision=row['revision'])
            error, _ = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            return reply(result)

    @app.post(root + '/<ident>/leads/<lead_id>/payment/recheck')
    def growthrova_recheck_payment(organisation_id, ident, lead_id):
        request.max_content_length = 2000
        value = request.get_json(silent=True)
        if (not isinstance(value, dict) or set(value) != {'accountId', 'chargeId', 'confirmed'}
                or value['confirmed'] is not True or not isinstance(value['accountId'], str)
                or not isinstance(value['chargeId'], str)):
            raise MarketingDraftError('Select a saved payment and confirm a status check.')
        _id(lead_id)
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        binding = binding_for(config, scope)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            error, _ = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            receipt = con.execute('SELECT * FROM growthrova_payment_receipts WHERE account_id=? '
                'AND charge_id=? AND owner_id=? AND organisation_id=? AND document_id=? AND lead_id=?',
                (value['accountId'], value['chargeId'], *scope, ident, lead_id)).fetchone()
            if (receipt is None or receipt['account_id'] != binding.account_id
                    or receipt['connection_version'] != binding.version):
                raise MarketingDraftError('Original payment connection is unavailable. Review saved evidence or ask for connection recovery.', 'payment_connection_changed', 409)
            old = previous(con, receipt)
            old_version = old['version'] if old else 0
        if binding_for(config, scope) != binding:
            raise MarketingDraftError('Payment connection changed. No status check was started.', 'payment_connection_changed', 409)
        try:
            observed = observation(read_charge(config, binding, receipt['charge_id']), receipt,
                                   scope, ident, lead_id, time.time())
        except (requests.RequestException, ValueError, TypeError, OverflowError):
            raise MarketingDraftError('Payment status could not be verified. Previous saved evidence and purchases are unchanged.', 'payment_unverified', 409) from None
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error, row = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            if binding_for(config, scope) != binding:
                raise MarketingDraftError('Payment connection changed. No status check was saved.', 'payment_connection_changed', 409)
            latest = previous(con, receipt)
            if (latest['version'] if latest else 0) != old_version:
                raise MarketingDraftError('Another payment check was saved first. Refresh saved evidence before checking again.', 'payment_check_conflict', 409)
            con.execute('INSERT INTO growthrova_payment_checks VALUES(?,?,?,?) '
                'ON CONFLICT(account_id,charge_id) DO UPDATE SET version=excluded.version, observation_json=excluded.observation_json',
                (receipt['account_id'], receipt['charge_id'], old_version+1, json.dumps(observed, sort_keys=True)))
            result = dict(receipt=project(con, receipt, row), enquiryRevision=row['revision'])
            error, _ = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            if binding_for(config, scope) != binding:
                raise MarketingDraftError('Payment connection changed. No status check was saved.', 'payment_connection_changed', 409)
            con.commit()
        return reply(result)
