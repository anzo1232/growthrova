"""Owner-supplied non-secret account selection. Never grants or verifies access."""
from contextlib import closing
import json
import re

from business_marketing_drafts import MarketingDraftError
from business_social_delivery import _hash

CURRENCIES = ('USD', 'GBP', 'EUR', 'AUD', 'CAD', 'INR')
READINESS = ('permissions', 'billing', 'destination', 'conversion')


class PaidSetup:
    def __init__(self, repo):
        self.repo = repo
        with closing(repo._connect()) as con:
            con.executescript('''
              CREATE TABLE IF NOT EXISTS growthrova_paid_setup(
                owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, platform TEXT NOT NULL,
                revision INTEGER NOT NULL, data_json TEXT NOT NULL,
                PRIMARY KEY(owner_id,organisation_id,platform));
              CREATE TABLE IF NOT EXISTS growthrova_paid_setup_receipts(
                owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, platform TEXT NOT NULL,
                mutation_id TEXT NOT NULL, fingerprint TEXT NOT NULL, result_json TEXT NOT NULL,
                PRIMARY KEY(owner_id,organisation_id,platform,mutation_id));
            ''')

    @staticmethod
    def read(con, scope, platform):
        row = con.execute('SELECT * FROM growthrova_paid_setup WHERE owner_id=? AND organisation_id=? AND platform=?', (*scope, platform)).fetchone()
        return dict(revision=row['revision'], data=json.loads(row['data_json'])) if row else dict(revision=0, data=None)

    @staticmethod
    def normalise(data, platform):
        fields = {'accountId', 'businessId', 'pageId', 'managerId', 'currency', 'enabled', 'readiness', 'notes'}
        if (not isinstance(data, dict) or set(data) != fields or type(data['enabled']) is not bool
                or data['currency'] not in CURRENCIES or not isinstance(data['readiness'], dict)
                or set(data['readiness']) != set(READINESS)
                or any(v not in ('unknown', 'ready', 'needs_action', 'not_required') for v in data['readiness'].values())):
            raise MarketingDraftError('Use supported account selection and owner-reported setup fields.')
        result = dict(data)
        for key in ('accountId', 'businessId', 'pageId', 'managerId', 'notes'):
            value = data[key]
            if (not isinstance(value, str) or len(value) > (1500 if key == 'notes' else 80)
                    or any(ord(c) < 32 and c not in ('\n', '\t') for c in value)):
                raise MarketingDraftError('Keep account references and setup notes within their limits.')
            value = value.strip()
            if key != 'notes':
                if platform == 'google' and key in ('accountId', 'managerId'):
                    value = value.replace('-', '')
                if platform == 'meta' and key == 'accountId' and value.startswith('act_'):
                    value = value[4:]
                if value and not re.fullmatch(r'[0-9]{10}' if platform == 'google' else r'[0-9]{1,40}', value):
                    raise MarketingDraftError('Use numeric Meta references or ten-digit Google customer IDs.')
            result[key] = value
        if (platform == 'google' and (result['pageId'] or result['businessId'])
                or platform == 'meta' and result['managerId']):
            raise MarketingDraftError('Keep Meta and Google account references separate.')
        return result

    def save(self, con, scope, platform, payload):
        if not isinstance(payload, dict) or set(payload) != {'expectedRevision', 'mutationId', 'data'}:
            raise MarketingDraftError('Account settings and save version are required.')
        base, mutation = payload['expectedRevision'], payload['mutationId']
        if (type(base) is not int or not 0 <= base < 200 or not isinstance(mutation, str)
                or not re.fullmatch('[a-f0-9]{32}', mutation)):
            raise MarketingDraftError('Use the supported account save version and identity.')
        data = self.normalise(payload['data'], platform)
        fingerprint = _hash(dict(expectedRevision=base, data=data))
        prior = con.execute('SELECT * FROM growthrova_paid_setup_receipts WHERE owner_id=? AND organisation_id=? AND platform=? AND mutation_id=?', (*scope, platform, mutation)).fetchone()
        if prior:
            if prior['fingerprint'] != fingerprint:
                raise MarketingDraftError('Save identity was already used.', 'revision_conflict', 409)
            return json.loads(prior['result_json'])
        old = self.read(con, scope, platform)
        if old['revision'] != base:
            raise MarketingDraftError('Business account settings changed. Reopen before saving.', 'revision_conflict', 409)
        if base == 199 and data['enabled']:
            raise MarketingDraftError('Setup history needs support review. You can still save a paused request.', 'storage_limit', 409)
        result = dict(revision=base+1, data=data)
        con.execute('INSERT OR REPLACE INTO growthrova_paid_setup VALUES(?,?,?,?,?)', (*scope, platform, base+1, json.dumps(data)))
        con.execute('INSERT INTO growthrova_paid_setup_receipts VALUES(?,?,?,?,?,?)', (*scope, platform, mutation, fingerprint, json.dumps(result)))
        # This business-wide selection controls unstarted work across its campaigns.
        # Never discard identities or interrupt lookup of already dispatched work.
        con.execute("UPDATE growthrova_paid_jobs SET state='blocked',claim_token=NULL,lease_until=NULL WHERE owner_id=? AND organisation_id=? AND platform=? AND state IN ('queued','claimed')", (*scope, platform))
        return result

    @staticmethod
    def blockers(saved, snap):
        if not saved['revision']:
            return []  # Preserve existing installations with no owner request.
        data, account = saved['data'], snap.get('account')
        reasons = []
        if not data['enabled']:
            reasons.append('This business account request is paused. Enable and save it before fresh approval.')
        if not data['accountId']:
            reasons.append('Save the ad account ID you want to use.')
        elif not account or (data['accountId'], data['currency']) != (account['accountId'], account['currency']):
            reasons.append('Arrange verification of the requested ad account and currency; the configured account does not match.')
        if snap['platform'] == 'meta' and (not data['pageId'] or data['pageId'] != (snap.get('execution') or {}).get('pageId')):
            reasons.append('Save the intended Facebook Page ID and arrange verification for this exact plan.')
        return reasons

    def matches(self, snap):
        with closing(self.repo._connect()) as con:
            saved = self.read(con, (snap['ownerId'], snap['organisationId']), snap['platform'])
        return (saved['revision'] == snap.get('accountSetupRevision', 0)
                and not self.blockers(saved, snap))
