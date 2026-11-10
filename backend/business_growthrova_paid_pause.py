"""Owner-approved pause on the existing paid ledger; no live adapter installed.

Optional adapters implement check_pause(snapshot), pause(snapshot,
idempotency_key=...), lookup_pause(snapshot, idempotency_key=..., reference=...).
They must stop delivery for the exact reviewed resource tree without enabling
resources, changing budgets or creating anything. Lookup is strictly read-only.
A paused outcome confirms that this entire tree cannot deliver, not just that
the platform accepted a request. Concrete platform implementation is separate.
"""
from contextlib import closing
import json
import uuid

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id
from business_social_delivery import _hash

INTENT = 'pause_exact_resources'
METHODS = ('check_pause', 'pause', 'lookup_pause')


class PaidPause:
    def __init__(self, delivery):
        self.delivery, self.repo = delivery, delivery.repo

    def rows(self, con, ident, platform):
        return con.execute("SELECT * FROM growthrova_paid_jobs WHERE document_id=? AND platform=? AND json_extract(snapshot_json,'$.intent')=? ORDER BY approved_at DESC", (ident, platform, INTENT)).fetchall()

    def source(self, con, ident, platform, job_id):
        return next((r for r in self.delivery.launch.rows(con, ident, platform) if r['job_id'] == job_id and r['state'] == 'active' and r['mode'] == 'live'), None)

    def snapshot(self, con, ident, platform, job_id=None, *, creation_job_id=None):
        if creation_job_id is not None:
            if job_id is not None:
                raise MarketingDraftError('Review one saved campaign identity.', 'revision_conflict', 409)
            source = next((r for r in self.delivery.rows(con, ident, platform)
                           if r['job_id'] == creation_job_id and r['state'] == 'created_paused'
                           and r['mode'] == 'live'), None)
            receipt = json.loads(source['receipt_json']) if source and source['receipt_json'] else None
            launches = self.delivery.launch.rows(con, ident, platform)
            if (not receipt or receipt.get('outcome') != 'paused' or not receipt.get('id')
                    or not isinstance(receipt.get('resources'), dict) or not receipt['resources'].get('campaignId')
                    or any(json.loads(r['snapshot_json']).get('creationJobId') == creation_job_id
                           and r['state'] not in ('blocked', 'cancelled', 'failed') for r in launches)):
                raise MarketingDraftError('Choose a confirmed saved campaign. Cancel pending activation or resolve its outcome first.', 'revision_conflict', 409)
            saved = json.loads(source['snapshot_json'])
            # Stopping delivery must survive edits to the local plan/setup and
            # expired spending approval. Only the frozen remote tree is used.
            return dict(intent=INTENT, campaignId=ident, ownerId=source['owner_id'],
                        organisationId=source['organisation_id'], platform=platform,
                        account=saved['account'], creationJobId=creation_job_id,
                        resources=receipt['resources'])
        source = self.source(con, ident, platform, job_id)
        if not source:
            raise MarketingDraftError('Choose a confirmed activation. Resolve uncertain activation before requesting pause.', 'revision_conflict', 409)
        launch = json.loads(source['snapshot_json'])
        return dict(intent=INTENT, campaignId=ident, ownerId=source['owner_id'],
                    organisationId=source['organisation_id'], platform=platform,
                    account=launch['account'], launchJobId=job_id,
                    resources=launch['creationReceipt']['resources'])

    def sources(self, con, ident, platform):
        result = [self.snapshot(con, ident, platform, r['job_id'])
                  for r in self.delivery.launch.rows(con, ident, platform)
                  if r['state'] == 'active' and r['mode'] == 'live']
        for row in self.delivery.rows(con, ident, platform):
            try:
                result.append(self.snapshot(con, ident, platform, creation_job_id=row['job_id']))
            except MarketingDraftError:
                continue
        return result

    def current(self, con, row):
        snap = json.loads(row['snapshot_json'])
        try:
            return (self.repo._owned(con, row['document_id'], (row['owner_id'], row['organisation_id']))
                    and self.snapshot(con, row['document_id'], row['platform'], snap.get('launchJobId'),
                                      creation_job_id=snap.get('creationJobId')) == snap)
        except MarketingDraftError:
            return False

    def available(self, platform):
        config = self.delivery.config
        adapter = config.adapters.get(platform)
        return (config.mode == 'live' and callable(config.pause_authorised)
                and all(callable(getattr(adapter, method, None)) for method in METHODS))

    def authorised(self, snap, *, mutation=True):
        try:
            config = self.delivery.config
            # Do not require the old plan/setup, launch permission or unexpired
            # spending approval to stop delivery. Exact account read/write scope
            # and separately trusted pause authority must still be current.
            adapter = config.adapters.get(snap['platform'])
            if mutation:
                allowed = (self.available(snap['platform'])
                           and config.pause_authorised(snap['ownerId'], snap['organisationId'], json.loads(json.dumps(snap))) is True)
            else:
                allowed = config.mode == 'live' and callable(getattr(adapter, 'lookup_pause', None))
            return (allowed
                    and config is self.delivery.config
                    and self.delivery.authorised(snap, creation=False))
        except Exception:
            return False

    def run_one(self):
        if self.delivery.config.mode != 'live':
            return False
        now = self.delivery.config.clock()
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE growthrova_paid_jobs SET state='uncertain' WHERE state='dispatching' AND lease_until<=? AND json_extract(snapshot_json,'$.intent')=?", (now, INTENT))
            con.execute("UPDATE growthrova_paid_jobs SET state='queued',claim_token=NULL,lease_until=NULL WHERE state='claimed' AND lease_until<=? AND json_extract(snapshot_json,'$.intent')=?", (now, INTENT))
            row = con.execute("SELECT * FROM growthrova_paid_jobs WHERE state='queued' AND mode='live' AND json_extract(snapshot_json,'$.intent')=? ORDER BY approved_at LIMIT 1", (INTENT,)).fetchone()
            if not row:
                con.commit()
                return False
            row = dict(row)
            token = uuid.uuid4().hex
            row['claim_token'] = token
            con.execute("UPDATE growthrova_paid_jobs SET state='claimed',claim_token=?,lease_until=? WHERE job_id=?", (token, now+self.delivery.LEASE_SECONDS, row['job_id']))
            con.commit()
        snap = json.loads(row['snapshot_json'])
        ready = False
        try:
            with closing(self.repo._connect()) as con:
                con.execute('BEGIN')
                ready = self.authorised(snap) and self.current(con, row)
            ready = ready and self.delivery.config.adapters[row['platform']].check_pause(json.loads(row['snapshot_json'])) is True
        except Exception:
            pass
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT * FROM growthrova_paid_jobs WHERE job_id=?', (row['job_id'],)).fetchone()
            if current['state'] != 'claimed' or current['claim_token'] != token:
                return True
            ready = ready and self.authorised(snap) and self.current(con, current)
            # Authority checks can be slow: fence the lease AFTER those checks.
            if current['lease_until'] <= self.delivery.config.clock():
                return True
            con.execute('UPDATE growthrova_paid_jobs SET state=?,lease_until=? WHERE job_id=?', ('dispatching' if ready else 'blocked', self.delivery.config.clock()+self.delivery.LEASE_SECONDS, row['job_id']))
            con.commit()  # Durable intent precedes the only remote attempt.
        if ready:
            value = None
            try:
                value = self.delivery.config.adapters[row['platform']].pause(json.loads(row['snapshot_json']), idempotency_key=row['job_id'])
            except Exception:
                pass
            self.finish(row, value)
        return True

    def finish(self, row, value):
        snap = json.loads(row['snapshot_json'])
        valid = (isinstance(value, dict) and set(value) == {'outcome', 'resources'}
                 and value['outcome'] in ('paused', 'not_paused') and value['resources'] == snap['resources'])
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            valid = valid and self.authorised(snap, mutation=False) and self.current(con, row)
            result = dict(value, confirmedAt=self.delivery.config.clock()) if valid else None
            con.execute("UPDATE growthrova_paid_jobs SET state=?,receipt_json=?,lease_until=NULL WHERE job_id=? AND claim_token=? AND state IN ('dispatching','uncertain')", ('remote_paused' if valid and value['outcome'] == 'paused' else 'failed' if valid else 'uncertain', json.dumps(result) if result else None, row['job_id'], row['claim_token']))
            con.commit()

    def reconcile(self, row):
        snap = json.loads(row['snapshot_json'])
        if row['state'] != 'uncertain':
            return
        try:
            with closing(self.repo._connect()) as con:
                con.execute('BEGIN')
                # Revoking mutation authority must not hide a known outcome;
                # current account/scope and a read-only adapter are still needed.
                if not self.authorised(snap, mutation=False) or not self.current(con, row):
                    return
            value = self.delivery.config.adapters[row['platform']].lookup_pause(json.loads(row['snapshot_json']),
                idempotency_key=row['job_id'], reference=json.loads(row['receipt_json']) if row['receipt_json'] else None)
            self.finish(row, value)
        except Exception:
            pass


def register_pause_routes(app, delivery, endpoint, checked):
    pause, repo = delivery.pause, delivery.repo

    @app.route(endpoint + '/remote-pause', methods=['GET', 'POST'])
    def growthrova_paid_remote_pause(organisation_id, ident, platform):
        if platform not in ('meta', 'google'):
            raise MarketingDraftError('Choose Meta or Google Search.')
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        data = request.get_json(silent=True) if request.method == 'POST' else None
        selected = []
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE' if request.method == 'POST' else 'BEGIN')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            if request.method == 'POST':
                if not isinstance(data, dict) or data.get('action') not in ('approve', 'cancel', 'reconcile'):
                    raise MarketingDraftError('Choose a platform pause control.')
                action = data['action']
                if set(data) != ({'action', 'mutationId', 'review'} if action == 'approve' else {'action', 'mutationId', 'jobId'}):
                    raise MarketingDraftError('Review the exact pause fields.')
                _id(data['mutationId'])
                encoded = 'remote-pause:' + json.dumps(data, sort_keys=True, separators=(',', ':'))
                prior = con.execute('SELECT * FROM growthrova_paid_actions WHERE mutation_id=?', (data['mutationId'],)).fetchone()
                if prior and (prior['document_id'], prior['platform'], prior['request_json']) != (ident, platform, encoded):
                    raise MarketingDraftError('Recovery identity belongs to a different action.', 'mutation_conflict', 409)
                if not prior:
                    if con.execute('SELECT COUNT(*) FROM growthrova_paid_actions WHERE document_id=?', (ident,)).fetchone()[0] >= 2000:
                        raise MarketingDraftError('Paid action history needs support review.', 'job_limit', 409)
                    if action == 'approve':
                        review = data['review']
                        if not isinstance(review, dict):
                            raise MarketingDraftError('Review the exact campaign resources to pause.')
                        snap = pause.snapshot(con, ident, platform, review.get('launchJobId'),
                                              creation_job_id=review.get('creationJobId'))
                        if review != snap:
                            raise MarketingDraftError('Pause resources or account changed. Refresh and review.', 'revision_conflict', 409)
                        if not pause.authorised(snap):
                            raise MarketingDraftError('Platform pause is disconnected. Separate verified pause access is required.', 'pause_unavailable', 409)
                        earlier = [r for r in pause.rows(con, ident, platform)
                                   if all(json.loads(r['snapshot_json']).get(k) == snap.get(k)
                                          for k in ('account', 'resources'))]
                        if any(r['state'] not in ('blocked', 'cancelled') for r in earlier):
                            raise MarketingDraftError('This campaign already has a pause request. Follow its saved outcome or lookup.', 'pause_exists', 409)
                        job_id = _hash(dict(snapshot=snap, mode='live'))
                        if any(r['job_id'] == job_id for r in earlier):
                            con.execute("UPDATE growthrova_paid_jobs SET state='queued',claim_token=NULL,lease_until=NULL,approved_at=? WHERE job_id=?", (delivery.config.clock(), job_id))
                        else:
                            if len(pause.rows(con, ident, platform)) >= 200:
                                raise MarketingDraftError('Pause history needs support review.', 'job_limit', 409)
                            con.execute('INSERT INTO growthrova_paid_jobs(job_id,document_id,platform,owner_id,organisation_id,snapshot_json,mode,state,approved_at) VALUES(?,?,?,?,?,?,?,?,?)', (job_id, ident, platform, *scope, json.dumps(snap, sort_keys=True), 'live', 'queued', delivery.config.clock()))
                    else:
                        selected = [r for r in pause.rows(con, ident, platform) if r['job_id'] == data['jobId']]
                        if not selected:
                            raise MarketingDraftError('Pause request not found.', 'not_found', 404)
                        if action == 'cancel':
                            con.execute("UPDATE growthrova_paid_jobs SET state='cancelled',claim_token=NULL,lease_until=NULL WHERE job_id=? AND state IN ('queued','claimed','blocked')", (data['jobId'],))
                    con.execute('INSERT INTO growthrova_paid_actions VALUES(?,?,?,?)', (data['mutationId'], ident, platform, encoded))
                elif action == 'reconcile':
                    selected = [r for r in pause.rows(con, ident, platform) if r['job_id'] == data['jobId']]
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        for row in selected if data and data['action'] == 'reconcile' else []:
            pause.reconcile(row)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            sources = pause.sources(con, ident, platform)
            jobs = [delivery.public(r) for r in pause.rows(con, ident, platform)]
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        response = jsonify(sources=sources, jobs=jobs, available=pause.available(platform))
        response.headers['Cache-Control'] = 'no-store'
        return response
