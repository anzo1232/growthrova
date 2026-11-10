"""Exact-resource launch protocol on the existing paid ledger, disabled by default.

Optional adapters implement check_launch(snapshot), activate(snapshot,
idempotency_key=...), lookup_launch(snapshot,idempotency_key=...,reference=...).
check_launch must independently verify unchanged remote resources, billing/grants,
policy and enforceable daily/total/expiry limits. A daily budget or polling worker
alone is NOT a hard total cap. No existing paused transport implements this
contract. Lookup never activates, changes budgets or repeats a write.
"""
from contextlib import closing
from datetime import datetime
from decimal import Decimal
import json
import re
import uuid

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id
from business_social_delivery import _hash

INTENT = 'launch_exact_resources'


def limits(value, now):
    if not isinstance(value, dict) or set(value) != {'daily', 'total', 'currency', 'expiresAt'}:
        raise MarketingDraftError('Review daily and total limits, currency and UTC expiry.')
    result = dict(value)
    for key in ('daily', 'total'):
        if not isinstance(value[key], str) or not re.fullmatch(r'[0-9]{1,7}(\.[0-9]{1,2})?', value[key]) or Decimal(value[key]) <= 0:
            raise MarketingDraftError('Use positive spending limits with up to two decimal places.')
        result[key] = format(Decimal(value[key]), '.2f')
    if Decimal(result['daily']) > Decimal(result['total']):
        raise MarketingDraftError('Daily limit cannot exceed the total limit.')
    try:
        if not isinstance(value['expiresAt'], str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:00Z', value['expiresAt']):
            raise ValueError()
        expiry = datetime.fromisoformat(value['expiresAt'].replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, OverflowError):
        raise MarketingDraftError('Choose a UTC expiry to the minute.')
    if not now < expiry <= now + 30*86400:
        raise MarketingDraftError('Expiry must be in the next 30 days.')
    if value['currency'] not in ('USD', 'GBP', 'EUR', 'AUD', 'CAD', 'INR'):
        raise MarketingDraftError('Use the selected account currency.')
    return result


class PaidLaunch:
    def __init__(self, delivery):
        self.delivery, self.repo = delivery, delivery.repo

    def blockers(self, snap):
        """Optional local adapter policy; errors hold approval and dispatch.

        Older dedicated adapters retain the independent check_launch contract.
        The policy inspects the saved creation profile, both for presentation
        and for enforcement. It never replaces the worker's fresh remote check
        of the requested limits. It must be local and perform no external IO.
        """
        adapter = self.delivery.config.adapters.get(snap['platform'])
        policy = getattr(adapter, 'launch_blockers', None)
        if policy is None:
            return []
        try:
            profile = json.loads(json.dumps(snap))
            profile['intent'] = 'create_paused_only'
            for key in ('limits', 'creationJobId', 'creationReceipt'):
                profile.pop(key, None)
            value = policy(profile)
            if (isinstance(value, list) and len(value) <= 8
                    and all(isinstance(s, str) and 1 <= len(s.strip()) <= 600
                            and not any(ord(c) < 32 for c in s) for s in value)):
                return value
        except Exception:
            pass
        return ['Launch-limit compatibility could not be checked. Keep the campaign paused and refresh before reviewing activation.']

    def support(self, snap):
        reasons = self.blockers(snap)
        adapter = self.delivery.config.adapters.get(snap['platform'])
        configured = (self.delivery.config.mode == 'live'
                      and callable(self.delivery.config.launch_authorised)
                      and all(callable(getattr(adapter, key, None)) for key in ('check_launch', 'activate', 'lookup_launch')))
        if not configured and not reasons:
            reasons = ['Activation is disconnected. A dedicated connection with verified spending and expiry enforcement and separate launch authority is required.']
        return dict(available=configured and not reasons, blockers=reasons)

    def rows(self, con, ident, platform):
        return con.execute("SELECT * FROM growthrova_paid_jobs WHERE document_id=? AND platform=? AND json_extract(snapshot_json,'$.intent')=? ORDER BY approved_at DESC", (ident, platform, INTENT)).fetchall()

    def source(self, con, ident, platform, source_id):
        return next((r for r in self.delivery.rows(con, ident, platform) if r['job_id'] == source_id), None)

    def snapshot(self, con, ident, scope, platform, source_id, bound):
        # The pause approval and launch approval share the same write
        # transaction. Never queue activation behind an approved stop request.
        if any(json.loads(r['snapshot_json']).get('creationJobId') == source_id
               and r['state'] not in ('blocked', 'cancelled')
               for r in self.delivery.pause.rows(con, ident, platform)):
            raise MarketingDraftError('This saved campaign has a platform pause request. Follow its outcome; restarting needs a separate reviewed campaign.', 'pause_exists', 409)
        row = self.source(con, ident, platform, source_id)
        if not row or row['state'] != 'created_paused' or row['mode'] != 'live' or not self.delivery.current(con, row):
            raise MarketingDraftError('Choose a confirmed live paused campaign matching the saved plan and account.', 'revision_conflict', 409)
        source = json.loads(row['snapshot_json'])
        receipt = json.loads(row['receipt_json'])
        if source['plan'].get('budgetSchedule'):
            raise MarketingDraftError('Keep this total-budget campaign paused. Its budget and local dates do not enforce the required hard daily ceiling and exact UTC expiry.', 'launch_limits_unsupported', 409)
        if bound['currency'] != source['account']['currency'] or Decimal(bound['daily']) != Decimal(source['plan']['dailyBudget']):
            raise MarketingDraftError('Use the account currency and unchanged created daily budget; budget editing is a separate action.')
        return dict(**{**source, 'intent': INTENT}, creationJobId=source_id, creationReceipt=receipt, limits=bound)

    def current(self, con, row):
        snap = json.loads(row['snapshot_json'])
        try:
            return self.snapshot(con, row['document_id'], (row['owner_id'], row['organisation_id']), row['platform'], snap['creationJobId'], snap['limits']) == snap
        except MarketingDraftError:
            return False

    def authorised(self, snap):
        config = self.delivery.config
        adapter = config.adapters.get(snap['platform'])
        try:
            return (config.mode == 'live' and callable(config.launch_authorised)
                    and not self.blockers(snap)
                    and self.delivery.authorised(snap)
                    and all(callable(getattr(adapter, key, None)) for key in ('check_launch', 'activate', 'lookup_launch'))
                    and config.launch_authorised(snap['ownerId'], snap['organisationId'], json.loads(json.dumps(snap))) is True)
        except Exception:
            return False

    def unexpired(self, snap):
        return datetime.fromisoformat(snap['limits']['expiresAt'].replace('Z', '+00:00')).timestamp() > self.delivery.config.clock()

    def run_one(self):
        if self.delivery.config.mode != 'live':
            return False
        now = self.delivery.config.clock()
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE growthrova_paid_jobs SET state='uncertain' WHERE state='dispatching' AND lease_until<=? AND json_extract(snapshot_json,'$.intent')=?", (now, INTENT))
            con.execute("UPDATE growthrova_paid_jobs SET state='queued',claim_token=NULL WHERE state='claimed' AND lease_until<=? AND json_extract(snapshot_json,'$.intent')=?", (now, INTENT))
            row = con.execute("SELECT * FROM growthrova_paid_jobs WHERE state='queued' AND mode='live' AND json_extract(snapshot_json,'$.intent')=? ORDER BY approved_at LIMIT 1", (INTENT,)).fetchone()
            if not row:
                con.commit()
                return False
            row = dict(row)
            token = uuid.uuid4().hex
            con.execute("UPDATE growthrova_paid_jobs SET state='claimed',claim_token=?,lease_until=? WHERE job_id=?", (token, now+self.delivery.LEASE_SECONDS, row['job_id']))
            con.commit()
        snap = json.loads(row['snapshot_json'])
        ready = False
        try:
            ready = self.authorised(snap) and self.unexpired(snap) and self.delivery.config.adapters[row['platform']].check_launch(json.loads(row['snapshot_json'])) is True
        except Exception:
            pass
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT * FROM growthrova_paid_jobs WHERE job_id=?', (row['job_id'],)).fetchone()
            if current['state'] != 'claimed' or current['claim_token'] != token or current['lease_until'] <= self.delivery.config.clock():
                return True
            ready = ready and self.current(con, current) and self.authorised(snap) and self.unexpired(snap)
            con.execute('UPDATE growthrova_paid_jobs SET state=?,lease_until=? WHERE job_id=?', ('dispatching' if ready else 'blocked', self.delivery.config.clock()+self.delivery.LEASE_SECONDS, row['job_id']))
            con.commit()
        if ready:
            value = None
            try:
                value = self.delivery.config.adapters[row['platform']].activate(json.loads(row['snapshot_json']), idempotency_key=row['job_id'])
            except Exception:
                pass
            self.finish(row, token, value)
        return True

    def finish(self, row, token, value):
        # Only bounded evidence for the EXACT reviewed resources; no provider dumps.
        snap = json.loads(row['snapshot_json'])
        valid = (isinstance(value, dict) and set(value) == {'outcome', 'resources', 'limits'}
                 and value['outcome'] in ('active', 'not_activated')
                 and value['resources'] == snap['creationReceipt']['resources'] and value['limits'] == snap['limits'])
        result = value if valid else None
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE growthrova_paid_jobs SET state=?,receipt_json=?,lease_until=NULL WHERE job_id=? AND claim_token=? AND state IN ('dispatching','uncertain')", ('active' if valid and value['outcome'] == 'active' else 'failed' if valid else 'uncertain', json.dumps(result) if result else None, row['job_id'], token))
            con.commit()

    def reconcile(self, row):
        snap = json.loads(row['snapshot_json'])
        adapter = self.delivery.config.adapters.get(row['platform'])
        # Owner pause/draft drift must not prevent read-only outcome recovery.
        if row['state'] != 'uncertain' or not self.delivery.authorised(snap, creation=False) or not callable(getattr(adapter, 'lookup_launch', None)):
            return
        try:
            value = adapter.lookup_launch(json.loads(row['snapshot_json']), idempotency_key=row['job_id'], reference=json.loads(row['receipt_json']) if row['receipt_json'] else None)
            if self.delivery.authorised(snap, creation=False):
                self.finish(row, row['claim_token'], value)
        except Exception:
            pass


def register_launch_routes(app, delivery, endpoint, checked):
    launch = delivery.launch
    repo = delivery.repo

    @app.route(endpoint + '/launch', methods=['GET', 'POST'])
    def growthrova_paid_launch(organisation_id, ident, platform):
        if platform not in ('meta', 'google'):
            raise MarketingDraftError('Choose Meta or Google Search.')
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        data = request.get_json(silent=True) if request.method == 'POST' else None
        selected = []
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE' if data is not None else 'BEGIN')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            if request.method == 'POST':
                if not isinstance(data, dict) or data.get('action') not in ('approve', 'cancel', 'reconcile'):
                    raise MarketingDraftError('Choose a launch control.')
                action = data['action']
                fields = {'action', 'mutationId', 'review'} if action == 'approve' else {'action', 'mutationId', 'jobId'}
                if set(data) != fields:
                    raise MarketingDraftError('Review exact launch fields.')
                _id(data['mutationId'])
                encoded = 'launch:' + json.dumps(data, sort_keys=True, separators=(',', ':'))
                prior = con.execute('SELECT * FROM growthrova_paid_actions WHERE mutation_id=?', (data['mutationId'],)).fetchone()
                if prior and (prior['document_id'], prior['platform'], prior['request_json']) != (ident, platform, encoded):
                    raise MarketingDraftError('Recovery identity belongs to a different action.', 'mutation_conflict', 409)
                if not prior:
                    if con.execute('SELECT COUNT(*) FROM growthrova_paid_actions WHERE document_id=?', (ident,)).fetchone()[0] >= 2000:
                        raise MarketingDraftError('Paid action history needs support review.', 'job_limit', 409)
                    if action == 'approve':
                        review = data['review']
                        if not isinstance(review, dict):
                            raise MarketingDraftError('Review the exact launch resources and limits.')
                        bound = limits(review.get('limits'), delivery.config.clock())
                        snap = launch.snapshot(con, ident, scope, platform, review.get('creationJobId'), bound)
                        if review != snap:
                            raise MarketingDraftError('Plan, resources, account or limits changed. Refresh and review.', 'revision_conflict', 409)
                        blockers = launch.blockers(snap)
                        if blockers:
                            raise MarketingDraftError(' '.join(blockers), 'launch_limits_unsupported', 409)
                        if not launch.authorised(snap):
                            raise MarketingDraftError('Launch is disconnected: verified limit enforcement and separate launch authority are required.', 'launch_unavailable', 409)
                        # Reapproval is safe only if every prior intent was stopped BEFORE dispatch.
                        earlier = [r for r in launch.rows(con, ident, platform)
                                   if json.loads(r['snapshot_json'])['creationJobId'] == snap['creationJobId']]
                        if any(r['state'] not in ('blocked', 'cancelled') for r in earlier):
                            raise MarketingDraftError('This resource tree already has a launch request. Use its controls or lookup.', 'launch_exists', 409)
                        job_id = _hash(dict(snapshot=snap, mode='live'))
                        same = next((r for r in earlier if r['job_id'] == job_id), None)
                        if not same and len(launch.rows(con, ident, platform)) >= 200:
                            raise MarketingDraftError('Launch history needs support review.', 'job_limit', 409)
                        for old in earlier:
                            con.execute("UPDATE growthrova_paid_jobs SET state='cancelled',claim_token=NULL,lease_until=NULL WHERE job_id=?", (old['job_id'],))
                        if same:
                            con.execute("UPDATE growthrova_paid_jobs SET state='queued',approved_at=? WHERE job_id=?", (delivery.config.clock(), job_id))
                        else:
                            con.execute('INSERT INTO growthrova_paid_jobs(job_id,document_id,platform,owner_id,organisation_id,snapshot_json,mode,state,approved_at) VALUES(?,?,?,?,?,?,?,?,?)', (job_id, ident, platform, *scope, json.dumps(snap, sort_keys=True), 'live', 'queued', delivery.config.clock()))
                    else:
                        selected = [r for r in launch.rows(con, ident, platform) if r['job_id'] == data['jobId']]
                        if not selected:
                            raise MarketingDraftError('Launch request not found.', 'not_found', 404)
                        if action == 'cancel':
                            con.execute("UPDATE growthrova_paid_jobs SET state='cancelled',claim_token=NULL,lease_until=NULL WHERE job_id=? AND state IN ('queued','claimed','blocked')", (data['jobId'],))
                    con.execute('INSERT INTO growthrova_paid_actions VALUES(?,?,?,?)', (data['mutationId'], ident, platform, encoded))
                elif action == 'reconcile':
                    selected = [r for r in launch.rows(con, ident, platform) if r['job_id'] == data['jobId']]
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        for row in selected if data and data['action'] == 'reconcile' else []:
            launch.reconcile(row)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            sources = [delivery.public(r) for r in delivery.rows(con, ident, platform) if r['state'] == 'created_paused' and r['mode'] == 'live' and delivery.current(con, r)]
            for source in sources:
                source['launchSupport'] = launch.support(source['snapshot'])
            jobs = [delivery.public(r) for r in launch.rows(con, ident, platform)]
            adapter = delivery.config.adapters.get(platform)
            available = (delivery.config.mode == 'live' and callable(delivery.config.launch_authorised)
                         and all(callable(getattr(adapter, key, None)) for key in ('check_launch', 'activate', 'lookup_launch')))
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        return jsonify(sources=sources, jobs=jobs, available=available)
