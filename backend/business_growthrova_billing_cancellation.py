"""Explicit test-only period-end cancellation; no retries or grant writes.

The provider acknowledgement is request evidence only. Existing signed events
and explicit subscription reads remain the authority for coverage and expiry.
"""
from contextlib import closing
import hashlib
import json
import uuid

from business_marketing_drafts import MarketingDraftError


class TestCancellation:
    def __init__(self, billing):
        self.billing, self.repo = billing, billing.repo
        with closing(self.repo._connect()) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS growthrova_billing_cancellations(
                intent TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL, policy TEXT NOT NULL,
                grant_version TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
                digest TEXT)''')
            con.commit()

    def _eligible(self, row, grant):
        now = self.billing.config.clock()
        return bool(row and row['policy'] == self.billing.policy and grant
                    and not grant['terminal']
                    and (projection := json.loads(grant['projection']))['state'] == 'active'
                    and projection['from'] <= now < projection['until']
                    # Historical grants need a fresh verified snapshot. Never
                    # replace an existing earlier/custom cancellation schedule.
                    and projection.get('cancelAtPeriodEnd') is False
                    and 'cancelAt' in projection and projection['cancelAt'] is None)

    def status(self, con, row, grant):
        result = {'canCancelAtPeriodEnd': False}
        if not row:
            return result
        saved = con.execute('SELECT * FROM growthrova_billing_cancellations WHERE intent=?',
                            (row['id'],)).fetchone()
        if saved:
            result['cancellationRequest'] = (saved['state'] if saved['policy'] == self.billing.policy
                                             and saved['state'] != 'dispatching' else 'needs_review')
        if grant and row['policy'] == self.billing.policy:
            projection = json.loads(grant['projection'])
            result['observedCancellation'] = ('ended' if grant['terminal'] else
                'scheduled' if projection.get('cancelAtPeriodEnd') is True else
                'custom_schedule' if projection.get('cancelAt') is not None else
                'not_scheduled' if projection.get('cancelAtPeriodEnd') is False else 'unknown')
        if not saved and self._eligible(row, grant):
            result.update(canCancelAtPeriodEnd=True, cancellationVersion=grant['version'])
        return result

    def cancel(self, org, version, revalidate):
        from business_growthrova_billing import _id
        if not self.billing.config.enabled:
            raise MarketingDraftError('Test subscription cancellation is not configured.', 'billing_unconfigured', 409)
        scope = self.repo._scope(org)
        # Recheck authority before the external write, as well as after it.
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        if self.repo._scope(org) != scope:
            raise MarketingDraftError('Business access changed. Select the business again.', 'access_denied', 403)
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM growthrova_billing_checkouts WHERE owner=? AND organisation=?', scope).fetchone()
            grant = (con.execute('SELECT * FROM growthrova_billing_grants WHERE intent=?', (row['id'],)).fetchone()
                     if row else None)
            saved = (con.execute('SELECT id FROM growthrova_billing_cancellations WHERE intent=?', (row['id'],)).fetchone()
                     if row else None)
            if saved:
                con.rollback()
                return self.billing.status(org)  # Never redispatch, even after provider key expiry.
            if (self.billing.replacement.held(con, scope) or not self._eligible(row, grant) or grant['version'] != version
                    or not _id(grant['subscription'], 'sub_') or not _id(grant['customer'], 'cus_')):
                raise MarketingDraftError('Refresh and check the saved test subscription before confirming cancellation. No cancellation request was sent.',
                                          'billing_review_required', 409)
            ident = uuid.uuid4().hex
            con.execute('INSERT INTO growthrova_billing_cancellations VALUES(?,?,?,?,?,?,?)',
                        (row['id'], ident, self.billing.policy, version, 'dispatching', self.billing.config.clock(), None))
            con.commit()
        state, digest = 'needs_review', None
        try:
            sub = self.billing._post('subscriptions/'+grant['subscription'],
                data={'cancel_at_period_end': 'true'}, key='growthrova-test-cancel-'+ident)
            if (not isinstance(sub, dict) or sub.get('object') != 'subscription'
                    or sub.get('livemode') is not False or sub.get('id') != grant['subscription']
                    or sub.get('customer') != grant['customer']
                    or sub.get('metadata', {}).get('growthrova_intent') != row['id']
                    or sub.get('cancel_at_period_end') is not True):
                raise ValueError('Invalid cancellation acknowledgement')
            digest = hashlib.sha256(json.dumps(sub, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            state = 'acknowledged'
        except Exception:
            pass  # Could have succeeded remotely; retain the identity and never retry.
        with closing(self.repo._connect()) as con:
            con.execute('UPDATE growthrova_billing_cancellations SET state=?,digest=? WHERE id=?', (state, digest, ident))
            con.commit()
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        if self.repo._scope(org) != scope:
            raise MarketingDraftError('Business access changed. Select the business again.', 'access_denied', 403)
        return self.billing.status(org)
