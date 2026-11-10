"""Explicit replacement of verified expired test sessions, retaining history.

The current checkout table stays the single business admission slot. Replacing
it archives its exact snapshot atomically; old identities are never reused.
Contradictory late subscription evidence sets a durable business review hold.
"""
from contextlib import closing
import json
import uuid

from business_marketing_drafts import MarketingDraftError


class TestCheckoutReplacement:
    def __init__(self, billing):
        self.billing, self.repo = billing, billing.repo
        with closing(self.repo._connect()) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS growthrova_billing_replacements(
                intent TEXT PRIMARY KEY, replacement TEXT UNIQUE NOT NULL,
                owner TEXT NOT NULL, organisation TEXT NOT NULL, policy TEXT NOT NULL,
                snapshot TEXT NOT NULL, session TEXT UNIQUE NOT NULL, created REAL NOT NULL, conflict INTEGER NOT NULL)''')
            con.execute('CREATE INDEX IF NOT EXISTS growthrova_billing_replacement_holds ON growthrova_billing_replacements(owner,organisation,conflict)')
            con.commit()

    def held(self, con, scope):
        return con.execute('''SELECT 1 FROM growthrova_billing_replacements
            WHERE owner=? AND organisation=? AND conflict=1 LIMIT 1''', scope).fetchone() is not None

    def eligible(self, row, grant):
        return bool(row and row['policy'] == self.billing.policy
                    and row['state'] == 'verified_expired' and not grant)

    def replace(self, org, version, revalidate):
        if not self.billing.config.enabled:
            raise MarketingDraftError('Test checkout is not configured.', 'billing_unconfigured', 409)
        scope = self.repo._scope(org)
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        if self.repo._scope(org) != scope:
            raise MarketingDraftError('Business access changed.', 'access_denied', 403)
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            prior = con.execute('''SELECT 1 FROM growthrova_billing_replacements
                WHERE intent=? AND owner=? AND organisation=?''', (version, *scope)).fetchone()
            if prior:
                con.rollback()
                return self.billing.status(org)  # Replay returns current state, never resends.
            row = con.execute('SELECT * FROM growthrova_billing_checkouts WHERE owner=? AND organisation=?', scope).fetchone()
            grant = (con.execute('SELECT 1 FROM growthrova_billing_grants WHERE intent=?', (row['id'],)).fetchone()
                     if row else None)
            if (not self.eligible(row, grant) or row['id'] != version or self.held(con, scope)):
                raise MarketingDraftError('Check the saved checkout before replacing it. Only a verified expired checkout without a subscription or recovery link can be replaced.',
                                          'billing_review_required', 409)
            ident = uuid.uuid4().hex
            con.execute('INSERT INTO growthrova_billing_replacements VALUES(?,?,?,?,?,?,?,?,0)',
                        (row['id'], ident, *scope, self.billing.policy,
                         json.dumps(dict(row), sort_keys=True), row['session'], self.billing.config.clock()))
            con.execute('DELETE FROM growthrova_billing_checkouts WHERE id=?', (row['id'],))
            con.execute('INSERT INTO growthrova_billing_checkouts(id,owner,organisation,policy,state,created) VALUES(?,?,?,?,?,?)',
                        (ident, *scope, self.billing.policy, 'dispatching', self.billing.config.clock()))
            con.commit()
        return self.billing.dispatch_checkout(org, scope, ident, revalidate)

    def receive_archived(self, con, ident, event, digest):
        """A signed contradiction must never grant coverage or release a hold."""
        archived = con.execute('SELECT * FROM growthrova_billing_replacements WHERE intent=? AND policy=?',
                               (ident, self.billing.policy)).fetchone()
        if not archived:
            return False
        prior = con.execute('SELECT digest FROM growthrova_billing_events WHERE id=?', (event['id'],)).fetchone()
        if prior and prior['digest'] != digest:
            raise ValueError('Conflicting event identity')
        if not prior:
            con.execute('INSERT INTO growthrova_billing_events VALUES(?,?,?)', (event['id'], digest, ident))
        con.execute('UPDATE growthrova_billing_replacements SET conflict=1 WHERE intent=?', (ident,))
        con.commit()
        return True


def verified_expiry(checkout):
    # Missing fields in old/partial snapshots are not proof that recovery is off.
    return (checkout.get('status') == 'expired' and 'subscription' in checkout
            and checkout['subscription'] is None and 'customer' in checkout
            and checkout['customer'] is None and 'after_expiration' in checkout
            and checkout['after_expiration'] is None)
