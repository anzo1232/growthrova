"""Durable delivery of frozen Growthrova social drafts in their existing database.

No provider implementation, environment configuration, credentials or background
thread is installed here. The operator must explicitly inject an adapter and an
owner/business authorisation callback for a worker. `check(snapshot)` must verify
current destination identity, grants, format and caption support; account lookup
alone is not that check. `deliver` must honour the persisted idempotency key.
`reconcile` only looks up that key and must never submit a new post.
Carousel snapshots additionally require check_carousel(snapshot) and
deliver_carousel(snapshot, ordered_png_bytes, idempotency_key=...). The check
must validate every ordered PNG and channel/account format/limits, current
rights/grants and exact destination; single-image checks never substitute.
"""
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import time
import uuid

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id
from business_social_media import carousel_files


@dataclass(frozen=True)
class SocialDeliveryConfig:
    adapter: object = field(default=None, repr=False)
    authorised: object = field(default=None, repr=False)
    clock: object = time.time
    mode: str = 'simulation'


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _receipt(value):
    # Provider bodies may contain tokens or personal data. Retain only the
    # receipt identity needed for reconciliation, never arbitrary response JSON.
    if not isinstance(value, dict):
        return None
    ident = value.get('id')
    if (not isinstance(ident, str) or not ident.strip() or len(ident) > 300
            or any(ord(c) < 32 for c in ident)):
        return None
    outcome = value.get('outcome')
    return {'id': ident, 'outcome': outcome if outcome in ('published', 'simulated', 'accepted') else 'unknown'}


def cancel_delivery_jobs(con, document_id, draft_id):
    """Stop every unstarted channel; retain in-flight/uncertain outcomes honestly."""
    active = con.execute("SELECT 1 FROM growthrova_social_jobs WHERE document_id=? AND draft_id=? "
                         "AND state IN ('dispatching','uncertain') LIMIT 1", (document_id, draft_id)).fetchone()
    con.execute("UPDATE growthrova_social_jobs SET state='cancelled', claim_token=NULL, lease_until=NULL "
                "WHERE document_id=? AND draft_id=? AND state IN ('scheduled','claimed','paused','blocked')",
                (document_id, draft_id))
    return bool(active)


class SocialDelivery:
    LEASE_SECONDS = 120

    def __init__(self, repo, config=None):
        self.repo = repo
        self.config = config or SocialDeliveryConfig()
        if self.config.mode not in ('simulation', 'live'):
            raise ValueError('Explicit delivery mode required')
        with closing(repo._connect()) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS growthrova_social_jobs(
                job_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, draft_id TEXT NOT NULL,
                owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, channel TEXT NOT NULL,
                approval_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL, mode TEXT NOT NULL,
                due_at REAL NOT NULL, approved_at REAL NOT NULL, state TEXT NOT NULL,
                claim_token TEXT, lease_until REAL, receipt_json TEXT, reason TEXT,
                UNIQUE(document_id,draft_id,channel))''')
            con.execute('CREATE INDEX IF NOT EXISTS growthrova_social_jobs_due ON growthrova_social_jobs(state,due_at)')
            con.commit()

    @property
    def available(self):
        return (callable(self.config.authorised) and self.config.adapter is not None
                and all(callable(getattr(self.config.adapter, name, None)) for name in ('check', 'deliver', 'reconcile')))

    @staticmethod
    def public(row, revision=None):
        snapshot = json.loads(row['snapshot_json'])
        return dict(jobId=row['job_id'], channel=row['channel'], state=row['state'], mode=row['mode'],
                    approvalHash=row['approval_hash'], approvedAt=row['approved_at'], approvalCurrent=revision is None or revision == snapshot['revision'],
                    artworkSha256=snapshot['artworkSha256'], caption=snapshot['caption'],
                    destination=snapshot['destination'], schedule=snapshot['schedule'],
                    receipt=json.loads(row['receipt_json']) if row['receipt_json'] else None, reason=row['reason'])

    def rows(self, con, ident, draft_id):
        return con.execute('SELECT * FROM growthrova_social_jobs WHERE document_id=? AND draft_id=? ORDER BY channel',
                           (ident, draft_id)).fetchall()

    def authorised(self, scope):
        try:
            return self.available and self.config.authorised(*scope) is True
        except Exception:
            return False

    def eligible(self, snapshot, scope):
        if not self.available:
            return False
        # Fail closed; never log callback exception text or provider payloads.
        try:
            check = self.config.adapter.check
            if snapshot.get('format') == 'carousel':
                check = getattr(self.config.adapter, 'check_carousel', None)
                if not callable(check) or not callable(getattr(self.config.adapter, 'deliver_carousel', None)):
                    return False
            return (self.config.authorised(*scope) is True and check(snapshot) is True
                    and self.config.authorised(*scope) is True)
        except Exception:
            return False

    @staticmethod
    def snapshots(draft, scope):
        snapshots = []
        for channel in draft['channels']:
            destination = draft.get('destinationAccounts', {}).get(channel)
            if not destination or not destination.get('id'):
                raise MarketingDraftError('Choose a destination account for every channel in a new posting draft before approval.',
                                          'destination_required', 409)
            snapshots.append(dict(ownerId=scope[0], organisationId=scope[1], channel=channel, destination=destination,
                revision=draft['revision'], artworkSha256=draft['artworkSha256'],
                caption=draft.get('channelCaptions', {}).get(channel, draft['caption']),
                schedule=draft['schedule'], operationId=draft['operationId'], frame=draft['frame'],
                manifest=draft['manifest']))
            if draft.get('format') == 'carousel':
                snapshots[-1]['format'] = 'carousel'
                snapshots[-1]['slides'] = [dict(file=s['file'], sha256=s['sha256'], bytes=s['bytes'])
                    for s in draft['manifest']['slides']]
        return snapshots

    def claim_due(self):
        """One atomic claim. Expired pre-dispatch work is safe to reclaim.

        Dispatch intent is committed separately *before* adapter invocation.
        A crash after that boundary cannot prove whether a send happened, so an
        expired dispatch is held as uncertain, never put back in the queue.
        """
        if not self.available:
            return None
        now = self.config.clock()
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE growthrova_social_jobs SET state='uncertain', reason='Delivery confirmation is missing. Check status; do not post again.' "
                        "WHERE state='dispatching' AND lease_until<=?", (now,))
            con.execute("UPDATE growthrova_social_jobs SET state='scheduled', claim_token=NULL, lease_until=NULL "
                        "WHERE state='claimed' AND lease_until<=?", (now,))
            row = con.execute("SELECT * FROM growthrova_social_jobs WHERE state='scheduled' AND due_at<=? AND mode=? "
                              "ORDER BY due_at,job_id LIMIT 1", (now, self.config.mode)).fetchone()
            if not row:
                con.commit()
                return None
            token = uuid.uuid4().hex
            con.execute("UPDATE growthrova_social_jobs SET state='claimed', claim_token=?, lease_until=? WHERE job_id=?",
                        (token, now+self.LEASE_SECONDS, row['job_id']))
            con.commit()
            return dict(jobId=row['job_id'], token=token)

    def begin_dispatch(self, claim):
        if not claim:
            return False
        # Do slow account/grant checks outside the SQLite writer lock. A cancel
        # or pause can win while these checks run; the final CAS then denies send.
        with closing(self.repo._connect()) as con:
            row = con.execute('SELECT * FROM growthrova_social_jobs WHERE job_id=?', (claim['jobId'],)).fetchone()
        if not row or row['state'] != 'claimed' or row['claim_token'] != claim['token']:
            return False
        snapshot = json.loads(row['snapshot_json'])
        scope = (row['owner_id'], row['organisation_id'])
        eligible = row['mode'] == self.config.mode and self.eligible(snapshot, scope)
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT j.state,j.claim_token,j.lease_until,m.revision,d.draft_json '
                'FROM growthrova_social_jobs j LEFT JOIN marketing_drafts m ON m.id=j.document_id '
                'LEFT JOIN growthrova_social_drafts d ON d.document_id=j.document_id AND d.draft_id=j.draft_id '
                'WHERE j.job_id=?', (claim['jobId'],)).fetchone()
            if (not current or current['state'] != 'claimed' or current['claim_token'] != claim['token']
                    or current['lease_until'] <= self.config.clock()):
                return False
            valid = (eligible and self.authorised(scope) and current['revision'] == snapshot['revision'] and current['draft_json']
                     and json.loads(current['draft_json'])['state'] == 'draft'
                     and self.repo._owned(con, row['document_id'], scope))
            state = 'dispatching' if valid else 'blocked'
            reason = None if valid else 'Review this saved version and reconnect or check channel eligibility before approving again.'
            con.execute('UPDATE growthrova_social_jobs SET state=?,reason=?,lease_until=? WHERE job_id=?',
                        (state, reason, self.config.clock()+self.LEASE_SECONDS, claim['jobId']))
            con.commit()
            return bool(valid)

    def finish(self, claim, receipt):
        receipt = _receipt(receipt)
        expected = 'simulated' if self.config.mode == 'simulation' else 'published'
        state = expected if receipt and receipt['outcome'] == expected else 'uncertain'
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE growthrova_social_jobs SET state=?,receipt_json=?,reason=?,lease_until=NULL "
                "WHERE job_id=? AND claim_token=? AND state IN ('dispatching','uncertain') AND mode=?",
                (state, json.dumps(receipt) if receipt else None,
                 None if state != 'uncertain' else 'Delivery confirmation is missing. Check status; do not post again.',
                 claim['jobId'], claim['token'], self.config.mode))
            con.commit()

    def run_one(self):
        claim = self.claim_due()
        if not claim:
            return False
        if not self.begin_dispatch(claim):
            return True
        with closing(self.repo._connect()) as con:
            row = con.execute('SELECT j.snapshot_json,d.artwork FROM growthrova_social_jobs j '
                'JOIN growthrova_social_drafts d ON d.document_id=j.document_id AND d.draft_id=j.draft_id '
                'WHERE j.job_id=?', (claim['jobId'],)).fetchone()
        receipt = None
        try:
            snapshot = json.loads(row['snapshot_json'])
            if hashlib.sha256(row['artwork']).hexdigest() == snapshot['artworkSha256']:
                if snapshot.get('format') == 'carousel':
                    files = carousel_files(row['artwork'], snapshot['manifest'])
                    receipt = self.config.adapter.deliver_carousel(snapshot, files, idempotency_key=claim['jobId'])
                else:
                    receipt = self.config.adapter.deliver(snapshot, row['artwork'], idempotency_key=claim['jobId'])
        except Exception:
            # The call may have succeeded remotely. Never schedule an automatic retry.
            pass
        self.finish(claim, receipt)
        return True

    def reconcile(self, job_id):
        """Operator worker action: lookup only; no retry even if no receipt exists."""
        if not self.available:
            return
        with closing(self.repo._connect()) as con:
            row = con.execute("SELECT * FROM growthrova_social_jobs WHERE job_id=? AND state='uncertain' AND mode=?",
                              (job_id, self.config.mode)).fetchone()
        if not row:
            return
        snapshot = json.loads(row['snapshot_json'])
        try:
            if self.config.authorised(row['owner_id'], row['organisation_id']) is not True:
                return
            receipt = _receipt(self.config.adapter.reconcile(snapshot, idempotency_key=job_id))
        except Exception:
            return
        if receipt and self.authorised((row['owner_id'], row['organisation_id'])):
            self.finish(dict(jobId=job_id, token=row['claim_token']), receipt)


def register_social_delivery_routes(app, repo, root, *, config=None, revalidate=None):
    delivery = SocialDelivery(repo, config)
    app.extensions['growthrova_social_delivery'] = delivery
    from business_growthrova_social_observations import register_social_observation_routes
    register_social_observation_routes(app, repo, root, revalidate=revalidate)
    endpoint = root + '/<ident>/social-drafts/<draft_id>/delivery'

    def checked(con, organisation_id, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
            raise MarketingDraftError('Business access changed. Sign in again to review scheduling.', 'access_denied', 403)

    def read_draft(con, ident, draft_id):
        _id(draft_id)
        row = con.execute('SELECT draft_json FROM growthrova_social_drafts WHERE document_id=? AND draft_id=?',
                          (ident, draft_id)).fetchone()
        if not row:
            raise MarketingDraftError('Posting draft not found.', 'draft_not_found', 404)
        return json.loads(row['draft_json'])

    @app.get(endpoint)
    def social_delivery_status(organisation_id, ident, draft_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            read_draft(con, ident, draft_id)
            rows = delivery.rows(con, ident, draft_id)
            revision = con.execute('SELECT revision FROM marketing_drafts WHERE id=?', (ident,)).fetchone()[0]
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        return jsonify(jobs=[delivery.public(row, revision) for row in rows], available=delivery.available,
                       mode=delivery.config.mode)

    @app.post(endpoint + '/reconcile')
    def social_delivery_reconcile(organisation_id, ident, draft_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        if request.get_json(silent=True) != {}:
            raise MarketingDraftError('Check confirmation for this saved schedule with an empty request.')
        with closing(repo._connect()) as con:
            read_draft(con, ident, draft_id)
            rows = delivery.rows(con, ident, draft_id)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        if not delivery.available:
            raise MarketingDraftError('Delivery confirmation is unavailable. Keep this saved item; do not post again.',
                                      'social_delivery_unavailable', 503)
        for row in rows:
            if row['state'] == 'uncertain':
                delivery.reconcile(row['job_id'])  # Lookup only; never deliver().
        return social_delivery_status(organisation_id, ident, draft_id)

    @app.post(endpoint + '/approve')
    def social_delivery_approve(organisation_id, ident, draft_id):
        saved = repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'expectedRevision', 'artworkSha256'}
                or type(data['expectedRevision']) is not int or not isinstance(data['artworkSha256'], str)):
            raise MarketingDraftError('Approve the exact inspected saved revision and artwork.')
        if not delivery.available:
            raise MarketingDraftError('Scheduling is unavailable. Your saved draft is preserved; connect an eligible delivery service first.',
                                      'social_delivery_unavailable', 503)
        with closing(repo._connect()) as con:
            draft = read_draft(con, ident, draft_id)
        snapshots = delivery.snapshots(draft, scope)
        # Check every channel before inserting any job. Provider/account inspection
        # is outside the write transaction and cannot imply owner approval itself.
        eligible = all(delivery.eligible(snapshot, scope) for snapshot in snapshots)
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            current = read_draft(con, ident, draft_id)
            revision = con.execute('SELECT revision FROM marketing_drafts WHERE id=?', (ident,)).fetchone()[0]
            if (current != draft or current['state'] != 'draft' or revision != saved['revision']
                    or current['revision'] != revision or data['expectedRevision'] != revision
                    or data['artworkSha256'] != current['artworkSha256']):
                raise MarketingDraftError('Campaign or artwork changed. Inspect a new posting draft before approval.', 'revision_conflict', 409)
            existing = delivery.rows(con, ident, draft_id)
            bindings = {snapshot['channel']: _hash(snapshot) for snapshot in snapshots}
            if any(row['mode'] != delivery.config.mode or row['approval_hash'] != bindings.get(row['channel']) for row in existing):
                raise MarketingDraftError('Saved approval belongs to another delivery version. Review a new draft.', 'approval_conflict', 409)
            # An acknowledgement replay returns durable terminal/in-flight jobs
            # even when current account checks fail; it cannot create a new send.
            if existing and all(row['state'] not in ('paused', 'blocked') for row in existing):
                return jsonify(jobs=[delivery.public(row) for row in existing], mode=delivery.config.mode, available=delivery.available), 200
            if not eligible:
                raise MarketingDraftError('A channel is disconnected or its permissions, caption or media need review. Nothing new was scheduled.',
                                          'channel_not_ready', 409)
            due = datetime.fromisoformat(draft['schedule']['utcTime'].replace('Z', '+00:00')).timestamp()
            now = delivery.config.clock()
            if due <= now:
                raise MarketingDraftError('This planned time has passed. Save a new posting draft with a future time.', 'schedule_in_past', 409)
            for snapshot in snapshots:
                binding = _hash(snapshot)
                previous = next((row for row in existing if row['channel'] == snapshot['channel']), None)
                if previous:
                    if previous['state'] in ('paused', 'blocked'):
                        con.execute("UPDATE growthrova_social_jobs SET state='scheduled',reason=NULL,claim_token=NULL,lease_until=NULL,approved_at=? WHERE job_id=?",
                                    (now, previous['job_id']))
                else:
                    con.execute('INSERT INTO growthrova_social_jobs '
                        '(job_id,document_id,draft_id,owner_id,organisation_id,channel,approval_hash,snapshot_json,mode,due_at,approved_at,state) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        (uuid.uuid4().hex, ident, draft_id, *scope, snapshot['channel'], binding,
                         json.dumps(snapshot), delivery.config.mode, due, now, 'scheduled'))
            rows = delivery.rows(con, ident, draft_id)
            con.commit()
        return jsonify(jobs=[delivery.public(row) for row in rows], mode=delivery.config.mode, available=delivery.available), 200 if existing else 201

    @app.post(endpoint + '/pause')
    def social_delivery_pause(organisation_id, ident, draft_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        if request.get_json(silent=True) != {}:
            raise MarketingDraftError('Pause this saved schedule with an empty request.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            read_draft(con, ident, draft_id)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.execute("UPDATE growthrova_social_jobs SET state='paused',claim_token=NULL,lease_until=NULL "
                        "WHERE document_id=? AND draft_id=? AND state IN ('scheduled','claimed','blocked')", (ident, draft_id))
            rows = delivery.rows(con, ident, draft_id)
            revision = con.execute('SELECT revision FROM marketing_drafts WHERE id=?', (ident,)).fetchone()[0]
            con.commit()
        return jsonify(jobs=[delivery.public(row, revision) for row in rows], mode=delivery.config.mode, available=delivery.available)

    return delivery
