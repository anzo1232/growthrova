"""Explicit, default-disconnected creation of new plain-text site articles.

Injected adapters implement site(owner, business), check(snapshot),
deliver(snapshot, idempotency_key=...), reconcile(snapshot, idempotency_key=...).
They must enforce dedicated site grants, bounded transport and remote idempotency.
No URL/credential lookup, CMS transport, worker host or existing-page edits here.
Only a definitive published/drafted/simulated/failed receipt ends uncertainty; failed
must establish no article was created. Accepted means unknown. Reconciliation
is lookup-only and must never create an article. site() and authorised() are
local metadata/policy checks; all provider I/O belongs in check/deliver/reconcile.
"""
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
import json
import re
import time
import uuid

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError
from business_social_delivery import _hash


@dataclass(frozen=True)
class OrganicDeliveryConfig:
    adapter: object = None
    authorised: object = None
    mode: str = 'simulation'
    clock: object = time.time


class OrganicDelivery:
    LEASE_SECONDS = 120

    def __init__(self, repo, config=None):
        self.repo, self.config = repo, config or OrganicDeliveryConfig()
        if self.config.mode not in ('simulation', 'live'):
            raise ValueError('Explicit organic delivery mode required')
        with closing(repo._connect()) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS growthrova_organic_jobs(
                job_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, item_id TEXT NOT NULL,
                owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                mode TEXT NOT NULL, state TEXT NOT NULL, approved_at REAL NOT NULL,
                claim_token TEXT, lease_until REAL, receipt_json TEXT)''')
            con.execute('CREATE INDEX IF NOT EXISTS growthrova_organic_pending ON growthrova_organic_jobs(state,approved_at)')
            con.commit()

    def site(self, scope):
        try:
            adapter = self.config.adapter
            if not all(callable(getattr(adapter, name, None)) for name in ('site', 'check', 'deliver', 'reconcile')):
                return None
            site = adapter.site(*scope)
            if (not isinstance(site, dict) or set(site) != {'siteId', 'label', 'version'}
                    or any(not isinstance(v, str) or not v.strip() or len(v) > 300
                           or any(ord(c) < 32 for c in v) for v in site.values())):
                return None
            return dict(site)
        except Exception:
            return None

    def authorised(self, snap):
        try:
            scope = (snap['ownerId'], snap['organisationId'])
            return (snap['site'] is not None and self.site(scope) == snap['site']
                    and getattr(self.config.adapter, 'mode', None) == self.config.mode
                    and self.config.mode == snap['mode']
                    and callable(self.config.authorised)
                    and self.config.authorised(*scope, snap['site']) is True)
        except Exception:
            return False

    def snapshot(self, con, ident, item_id, scope):
        if not self.repo._owned(con, ident, scope):
            raise MarketingDraftError('Campaign unavailable.', 'access_denied', 403)
        row = con.execute('SELECT revision,document_json FROM marketing_drafts WHERE id=?', (ident,)).fetchone()
        doc = json.loads(row['document_json'])
        item = next((i for i in doc.get('organicWork', []) if i['id'] == item_id), None)
        if not item or item['kind'] != 'content' or item['status'] != 'ready_for_review' or not item['draft'].strip():
            raise MarketingDraftError('Save a content draft as ready for review before approving site delivery.')
        snap = dict(ownerId=scope[0], organisationId=scope[1], campaignId=ident,
                    revision=row['revision'], itemId=item_id, title=item['title'], body=item['draft'],
                    reference=item['reference'], site=self.site(scope), mode=self.config.mode,
                    operation='create_plain_text_article')
        if self.config.mode == 'live' and getattr(self.config.adapter, 'delivery_outcome', None) == 'drafted':
            snap['deliveryOutcome'] = 'drafted'
        return snap

    def current(self, con, row):
        try:
            return self.snapshot(con, row['document_id'], row['item_id'],
                                 (row['owner_id'], row['organisation_id'])) == json.loads(row['snapshot_json'])
        except MarketingDraftError:
            return False

    @staticmethod
    def public(row):
        return dict(jobId=row['job_id'], snapshot=json.loads(row['snapshot_json']), state=row['state'],
                    mode=row['mode'], approvedAt=row['approved_at'],
                    receipt=json.loads(row['receipt_json']) if row['receipt_json'] else None)

    def rows(self, con, ident):
        return con.execute('SELECT * FROM growthrova_organic_jobs WHERE document_id=? ORDER BY approved_at DESC,job_id', (ident,)).fetchall()

    def expire(self, con, ident=None):
        # A crash after dispatch can never turn into a fresh create operation.
        suffix = ' AND document_id=?' if ident else ''
        params = (self.config.clock(), ident) if ident else (self.config.clock(),)
        con.execute("UPDATE growthrova_organic_jobs SET state='uncertain' WHERE state='dispatching' AND lease_until<=?"+suffix, params)
        con.execute("UPDATE growthrova_organic_jobs SET state='queued',claim_token=NULL,lease_until=NULL WHERE state='claimed' AND lease_until<=?"+suffix, params)

    def finish(self, row, token, value):
        valid = (isinstance(value, dict) and isinstance(value.get('id'), str)
                 and 0 < len(value['id'].strip()) <= 300 and not any(ord(c) < 32 for c in value['id']))
        expected = ('drafted' if json.loads(row['snapshot_json']).get('deliveryOutcome') == 'drafted'
                    else 'published') if row['mode'] == 'live' else 'simulated'
        outcome = value.get('outcome') if valid else None
        state = outcome if outcome in (expected, 'failed') else 'uncertain'
        result = dict(id=value['id'], outcome=state) if valid else None
        with closing(self.repo._connect()) as con:
            con.execute("UPDATE growthrova_organic_jobs SET state=?,receipt_json=?,lease_until=NULL WHERE job_id=? AND claim_token=? AND state IN ('dispatching','uncertain')",
                        (state, json.dumps(result) if result else None, row['job_id'], token))
            con.commit()

    def run_one(self):
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            self.expire(con)
            row = con.execute("SELECT * FROM growthrova_organic_jobs WHERE state='queued' AND mode=? ORDER BY approved_at,job_id LIMIT 1", (self.config.mode,)).fetchone()
            if not row:
                con.commit()
                return False
            token = uuid.uuid4().hex
            con.execute("UPDATE growthrova_organic_jobs SET state='claimed',claim_token=?,lease_until=? WHERE job_id=?",
                        (token, self.config.clock()+self.LEASE_SECONDS, row['job_id']))
            con.commit()
        snap = json.loads(row['snapshot_json'])
        eligible = False
        try:
            eligible = self.authorised(snap) and self.config.adapter.check(deepcopy(snap)) is True and self.authorised(snap)
        except Exception:
            pass
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT * FROM growthrova_organic_jobs WHERE job_id=?', (row['job_id'],)).fetchone()
            if current['state'] != 'claimed' or current['claim_token'] != token or current['lease_until'] <= self.config.clock():
                return True
            valid = eligible and self.current(con, current) and self.authorised(snap)
            valid = valid and current['lease_until'] > self.config.clock()
            con.execute('UPDATE growthrova_organic_jobs SET state=?,lease_until=? WHERE job_id=?',
                        ('dispatching' if valid else 'blocked', self.config.clock()+self.LEASE_SECONDS, row['job_id']))
            con.commit()
        if valid:
            result = None
            try:
                # Adapters receive only article wording as publishable content;
                # reference metadata must never be inserted into customer artwork.
                result = self.config.adapter.deliver(deepcopy(snap), idempotency_key=row['job_id'])
            except Exception:
                pass
            self.finish(row, token, result)
        return True

    def reconcile(self, row):
        if row['state'] != 'uncertain' or row['mode'] != self.config.mode:
            return
        snap = json.loads(row['snapshot_json'])
        if not self.authorised(snap):
            return
        try:
            value = self.config.adapter.reconcile(deepcopy(snap), idempotency_key=row['job_id'])
        except Exception:
            return
        if value is not None and self.authorised(snap):
            self.finish(row, row['claim_token'], value)


def register_organic_delivery_routes(app, repo, root, *, config=None, revalidate=None):
    service = OrganicDelivery(repo, config)
    app.extensions['growthrova_organic_delivery'] = service
    endpoint = root + '/<ident>/organic-delivery'

    def checked(con, organisation_id, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
            raise MarketingDraftError('Business access changed.', 'access_denied', 403)
        return None

    @app.get(endpoint)
    def organic_delivery_status(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        site = service.site(scope)
        available = service.authorised(dict(ownerId=scope[0], organisationId=scope[1], site=site, mode=service.config.mode))
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            service.expire(con, ident)
            jobs = [service.public(row) for row in service.rows(con, ident)]
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(site=site, available=available, mode=service.config.mode, jobs=jobs,
                       deliveryOutcome='drafted' if service.config.mode == 'live'
                       and getattr(service.config.adapter, 'delivery_outcome', None) == 'drafted'
                       else ('published' if service.config.mode == 'live' else 'simulated'))

    @app.post(endpoint + '/<action>')
    def organic_delivery_action(organisation_id, ident, action):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        request.max_content_length = 4000
        data = request.get_json(silent=True)
        fields = {'itemId', 'expectedRevision', 'expectedSite', 'expectedMode'} if action == 'approve' else {'jobId'}
        if action not in ('approve', 'pause', 'cancel', 'reconcile') or not isinstance(data, dict) or set(data) != fields:
            raise MarketingDraftError('Review the saved content and choose a supported site action.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            service.expire(con, ident)
            if action == 'approve':
                if not isinstance(data['itemId'], str) or len(data['itemId']) > 64 or type(data['expectedRevision']) is not int:
                    raise MarketingDraftError('Review the exact saved content version.')
                snap = service.snapshot(con, ident, data['itemId'], scope)
                if (snap['revision'] != data['expectedRevision'] or snap['site'] != data['expectedSite']
                        or snap['mode'] != data['expectedMode']):
                    raise MarketingDraftError('Saved campaign or site changed. Reopen and review.', 'revision_conflict', 409)
                if not service.authorised(snap):
                    raise MarketingDraftError('Connect and authorise a dedicated site before approval.', 'not_connected', 409)
                job_id = _hash(snap)
                old = con.execute('SELECT * FROM growthrova_organic_jobs WHERE job_id=?', (job_id,)).fetchone()
                # Exact replay remains safe even if its original dispatch is uncertain.
                if not old or old['state'] in ('paused', 'blocked'):
                    if con.execute("SELECT 1 FROM growthrova_organic_jobs WHERE document_id=? AND item_id=? AND state IN ('dispatching','uncertain')", (ident, data['itemId'])).fetchone():
                        raise MarketingDraftError('Confirm the earlier article outcome before approving another.', 'outcome_uncertain', 409)
                    con.execute("UPDATE growthrova_organic_jobs SET state='cancelled',claim_token=NULL,lease_until=NULL WHERE document_id=? AND item_id=? AND job_id<>? AND state IN ('queued','claimed','paused','blocked')", (ident, data['itemId'], job_id))
                    if old:
                        con.execute("UPDATE growthrova_organic_jobs SET state='queued',claim_token=NULL,lease_until=NULL WHERE job_id=?", (job_id,))
                    else:
                        if con.execute('SELECT COUNT(*) FROM growthrova_organic_jobs WHERE document_id=?', (ident,)).fetchone()[0] >= 300:
                            raise MarketingDraftError('This campaign has reached its saved site-job limit. Existing history and recovery remain available.', 'job_limit', 409)
                        con.execute('INSERT INTO growthrova_organic_jobs(job_id,document_id,item_id,owner_id,organisation_id,snapshot_json,mode,state,approved_at) VALUES(?,?,?,?,?,?,?,?,?)',
                                    (job_id, ident, data['itemId'], *scope, json.dumps(snap, sort_keys=True), service.config.mode, 'queued', service.config.clock()))
                row = con.execute('SELECT * FROM growthrova_organic_jobs WHERE job_id=?', (job_id,)).fetchone()
            else:
                if not isinstance(data['jobId'], str) or not re.fullmatch('[0-9a-f]{64}', data['jobId']):
                    raise MarketingDraftError('Choose a saved site job.')
                row = con.execute('SELECT * FROM growthrova_organic_jobs WHERE job_id=? AND document_id=? AND owner_id=? AND organisation_id=?', (data['jobId'], ident, *scope)).fetchone()
                if not row:
                    raise MarketingDraftError('Site job unavailable.', 'access_denied', 403)
                if action in ('pause', 'cancel'):
                    con.execute("UPDATE growthrova_organic_jobs SET state=?,claim_token=NULL,lease_until=NULL WHERE job_id=? AND state IN ('queued','claimed','paused','blocked')",
                                ('paused' if action == 'pause' else 'cancelled', row['job_id']))
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        if action == 'reconcile':
            service.reconcile(row)
        return organic_delivery_status(organisation_id, ident)

    return service
