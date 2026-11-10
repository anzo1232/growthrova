"""Non-secret sender requests and account-read inbound evidence. No registration/send.

Only dedicated adapters perform GET lookup. Browser input is a reference, never
an event timestamp, verified flag, account binding or permission grant.
"""
from contextlib import closing
import json
import re

from business_marketing_drafts import MarketingDraftError
from business_social_delivery import _hash


class SenderSetup:
    def __init__(self, repo, clock):
        self.repo, self.clock = repo, clock
        with closing(repo._connect()) as con:
            con.executescript('''
              CREATE TABLE IF NOT EXISTS growthrova_sender_requests(
                owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, channel TEXT NOT NULL,
                revision INTEGER NOT NULL, data_json TEXT NOT NULL,
                PRIMARY KEY(owner_id,organisation_id,channel));
              CREATE TABLE IF NOT EXISTS growthrova_sender_receipts(
                owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, channel TEXT NOT NULL,
                mutation_id TEXT NOT NULL, fingerprint TEXT NOT NULL, result_json TEXT NOT NULL,
                PRIMARY KEY(owner_id,organisation_id,channel,mutation_id));
              CREATE TABLE IF NOT EXISTS growthrova_inbound_evidence(
                owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, binding_hash TEXT NOT NULL,
                recipient TEXT NOT NULL, reference TEXT NOT NULL, occurred REAL NOT NULL, observed REAL NOT NULL,
                PRIMARY KEY(owner_id,organisation_id,binding_hash,recipient));
            ''')

    @staticmethod
    def read(con, scope, channel):
        row = con.execute('SELECT * FROM growthrova_sender_requests WHERE owner_id=? AND organisation_id=? AND channel=?', (*scope, channel)).fetchone()
        return dict(revision=row['revision'], data=json.loads(row['data_json'])) if row else dict(revision=0, data=None)

    def save(self, con, scope, channel, payload):
        if not isinstance(payload, dict) or set(payload) != {'expectedRevision', 'mutationId', 'data'}:
            raise MarketingDraftError('Sender settings and save version are required.')
        base, mutation, data = payload['expectedRevision'], payload['mutationId'], payload['data']
        if (type(base) is not int or not 0 <= base < 200 or not isinstance(mutation, str)
                or not re.fullmatch('[a-f0-9]{32}', mutation) or not isinstance(data, dict)
                or set(data) != {'address', 'subject', 'enabled'} or type(data['enabled']) is not bool):
            raise MarketingDraftError('Use the supported sender settings and save identity.')
        address, subject = data['address'], data['subject']
        if (not isinstance(address, str) or len(address) > 254
                or not isinstance(subject, str) or len(subject) > 200
                or any(ord(c) < 32 for c in address + subject)):
            raise MarketingDraftError('Use a valid sender address and plain email subject.')
        address, subject = address.strip(), subject.strip()
        from business_growthrova_senders import valid_recipient
        if not valid_recipient(channel, address) or (channel == 'email' and not subject) or (channel == 'whatsapp' and subject):
            raise MarketingDraftError('Email needs an address and subject; WhatsApp needs an international phone number without a subject.')
        data = dict(address=address, subject=subject, enabled=data['enabled'])
        fingerprint = _hash(dict(expectedRevision=base, data=data))
        prior = con.execute('SELECT * FROM growthrova_sender_receipts WHERE owner_id=? AND organisation_id=? AND channel=? AND mutation_id=?', (*scope, channel, mutation)).fetchone()
        if prior:
            if prior['fingerprint'] != fingerprint:
                raise MarketingDraftError('Save identity was already used.', 'revision_conflict', 409)
            return json.loads(prior['result_json'])
        old = self.read(con, scope, channel)
        if old['revision'] != base:
            raise MarketingDraftError('Sender settings changed. Reopen before saving.', 'revision_conflict', 409)
        if base == 199 and data['enabled']:
            raise MarketingDraftError('Sender request history needs operator review. You can still save a paused request.', 'storage_limit', 409)
        result = dict(revision=base+1, data=data)
        con.execute('INSERT OR REPLACE INTO growthrova_sender_requests VALUES(?,?,?,?,?)', (*scope, channel, base+1, json.dumps(data)))
        con.execute('INSERT INTO growthrova_sender_receipts VALUES(?,?,?,?,?,?)', (*scope, channel, mutation, fingerprint, json.dumps(result)))
        return result

    def matches(self, snap):
        with closing(self.repo._connect()) as con:
            saved = self.read(con, (snap['ownerId'], snap['organisationId']), snap['channel'])
        data, sender = saved['data'], snap.get('sender') or {}
        return bool(data and data['enabled'] and saved['revision'] == snap.get('senderSetupRevision')
                    and data['address'] == sender.get('address') and data['subject'] == sender.get('subject', ''))

    @staticmethod
    def binding_hash(binding):
        # Account identity is included even if an operator forgets a version rotation.
        return _hash(dict(version=binding.version, account=binding.account_id, address=binding.address))

    def window(self, scope, binding, recipient):
        if binding is None:
            return None
        with closing(self.repo._connect()) as con:
            row = con.execute('SELECT * FROM growthrova_inbound_evidence WHERE owner_id=? AND organisation_id=? AND binding_hash=? AND recipient=?', (*scope, self.binding_hash(binding), recipient)).fetchone()
        if not row:
            return None
        return dict(reference=row['reference'], occurredAt=row['occurred'], observedAt=row['observed'],
                    expiresAt=row['occurred']+86400, open=row['occurred'] <= self.clock() < row['occurred']+86400)

    def record(self, con, scope, binding, recipient, evidence):
        key = (*scope, self.binding_hash(binding), recipient)
        count = con.execute('SELECT COUNT(*) FROM growthrova_inbound_evidence WHERE owner_id=? AND organisation_id=?', scope).fetchone()[0]
        old = con.execute('SELECT occurred FROM growthrova_inbound_evidence WHERE owner_id=? AND organisation_id=? AND binding_hash=? AND recipient=?', key).fetchone()
        if not old and count >= 10000:
            raise MarketingDraftError('Inbound evidence storage needs operator review.', 'storage_limit', 409)
        # Replaying an old reference never starts a new service window.
        if not old or old['occurred'] < evidence['occurredAt']:
            con.execute('INSERT OR REPLACE INTO growthrova_inbound_evidence VALUES(?,?,?,?,?,?,?)', (*key, evidence['reference'], evidence['occurredAt'], self.clock()))
