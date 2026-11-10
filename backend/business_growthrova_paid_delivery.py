"""Opt-in paid provisioning protocol; no credential or host installed.

Paused creation remains separate from the optional exact-resource launch
protocol in business_growthrova_paid_launch. Launch authority defaults off.

Adapters expose mode, account(owner, business), check(snapshot),
create_paused(snapshot, idempotency_key=...), lookup(snapshot, idempotency_key=...,
reference=...). Account is an exact non-secret binding; all resources must remain
paused, including after partial creation. Lookup MUST NOT create or retry writes.
Only an explicit `paused` outcome confirms the complete paused resource tree;
`partial`, acknowledgement and missing identity remain uncertain. Adapter setup
must separately verify grants, billing, destination, conversions, platform policy
and permitted costs. The optional concrete Google Search transport lives in
business_growthrova_google_ads. Meta's optional create_paused_progressive method
receives retained bytes and a fenced journal(step, identity=None): intent must
commit before each write, acknowledgement immediately afterwards. Its receipt
retains progress without a new campaign store. No transport is installed here.
"""
from contextlib import closing
from dataclasses import dataclass, field
from decimal import Decimal
import json
import re
import time
import uuid

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, read_draft, _id
from business_paid_campaign import validate_asset
from business_social_delivery import _hash
from business_growthrova_paid_setup import PaidSetup

PLANS = {'meta': 'paidCampaign', 'google': 'googleCampaign'}
META_STEPS = ('campaignId', 'imageHash', 'creativeId', 'adSetId', 'adId')


@dataclass(frozen=True)
class PaidDeliveryConfig:
    adapters: dict = field(default_factory=dict, repr=False)
    authorised: object = field(default=None, repr=False)
    mode: str = 'simulation'
    clock: object = time.time
    launch_authorised: object = field(default=None, repr=False)
    discovery: object = field(default=None, repr=False)
    pause_authorised: object = field(default=None, repr=False)


def account_binding(value, platform, scope):
    fields = {'platform', 'accountId', 'label', 'connectionVersion', 'currency', 'ownerId', 'organisationId'}
    if (not isinstance(value, dict) or set(value) != fields or value['platform'] != platform
            or (value.get('ownerId'), value.get('organisationId')) != scope
            or value['currency'] not in ('USD', 'GBP', 'EUR', 'AUD', 'CAD', 'INR')):
        return None
    if any(not isinstance(v, str) or not v.strip() or len(v) > 180
           or any(ord(c) < 32 for c in v) for v in value.values()):
        return None
    return dict(value)


def missing(plan, platform, *, total_budget_supported=False):
    if not plan:
        return ['Save a preparation plan first.']
    required = ('audience', 'primaryText', 'headline', 'callToAction', 'destinationUrl') if platform == 'meta' else ('location', 'language', 'destinationUrl')
    result = [f'Complete {key} in the saved plan.' for key in required if not plan.get(key, '').strip()]
    if platform == 'meta' and 'budgetSchedule' in plan:
        if not total_budget_supported:
            result.append('The saved Meta total-budget/date plan is preparation only. Paused creation for this profile is not installed; it cannot use the daily-budget path. Keep this draft for review.')
        schedule = plan['budgetSchedule']
        if Decimal(schedule.get('totalBudget') or '0') <= 0:
            result.append('Propose a positive ad-set lifetime budget.')
        for key in ('startDate', 'endDate', 'accountTimezone'):
            if not schedule.get(key):
                result.append(f'Complete {key} in the saved total-budget plan.')
    elif platform == 'google' and 'budgetSchedule' in plan:
        schedule = plan['budgetSchedule']
        if not total_budget_supported:
            result.append('The saved Google total-budget/date plan is preparation only. Paused creation for this profile is not installed; it cannot use the average daily-budget path. Keep this draft for review. Its total budget does not enforce a daily ceiling or the UTC launch expiry.')
        if Decimal(schedule.get('totalBudget') or '0') <= 0:
            result.append('Propose a positive campaign total budget.')
        for key in ('startDate', 'endDate', 'accountTimezone'):
            if not schedule.get(key):
                result.append(f'Complete {key} in the saved total-budget plan.')
    elif Decimal(plan.get('dailyBudget') or '0') <= 0:
        result.append('Propose a positive daily budget.')
    if platform == 'meta' and not plan.get('asset'):
        result.append('Choose an exact saved image.')
    if platform == 'google':
        for key, count in (('headlines', 3), ('descriptions', 2), ('keywords', 1)):
            if len([s for s in plan.get(key, []) if s.strip()]) < count:
                result.append(f'Complete {key} in the saved Search plan.')
    return result


def receipt(value):
    # Do not persist arbitrary provider errors, tokens or diagnostic payloads.
    if not isinstance(value, dict):
        return None
    ident = value.get('id')
    if not isinstance(ident, str) or not ident.strip() or len(ident) > 300 or any(ord(c) < 32 for c in ident):
        return None
    resources = value.get('resources', {})
    if (not isinstance(resources, dict) or len(resources) > 20
            or any(not isinstance(k, str) or not isinstance(v, str) or not k or not v
                   or len(k) > 60 or len(v) > 300 or any(ord(c) < 32 for c in k+v)
                   for k, v in resources.items())):
        return None
    outcome = value.get('outcome')
    if outcome == 'paused' and not resources.get('campaignId'):
        outcome = 'unknown'
    if outcome == 'failed' and resources:
        outcome = 'partial'
    result = dict(id=ident, resources=resources, outcome=outcome if outcome in ('paused', 'simulated', 'failed', 'partial') else 'unknown')
    progress = value.get('progress')
    if (isinstance(progress, dict) and set(progress) == {'step', 'state'}
            and progress['step'] in META_STEPS and progress['state'] in ('intent', 'acknowledged')):
        result['progress'] = dict(progress)
    return result


class PaidDelivery:
    LEASE_SECONDS = 120

    def __init__(self, repo, config=None):
        self.repo, self.config = repo, config or PaidDeliveryConfig()
        if self.config.mode not in ('simulation', 'live'):
            raise ValueError('Explicit paid provisioning mode required')
        self.setup = PaidSetup(repo)
        with closing(repo._connect()) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS growthrova_paid_jobs(
                job_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, platform TEXT NOT NULL,
                owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                mode TEXT NOT NULL, state TEXT NOT NULL, approved_at REAL NOT NULL,
                claim_token TEXT, lease_until REAL, receipt_json TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS growthrova_paid_actions(
                mutation_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, platform TEXT NOT NULL,
                request_json TEXT NOT NULL)''')
            con.execute('CREATE INDEX IF NOT EXISTS growthrova_paid_pending ON growthrova_paid_jobs(state,approved_at)')
            con.commit()
        from business_growthrova_paid_launch import PaidLaunch
        self.launch = PaidLaunch(self)
        from business_growthrova_paid_pause import PaidPause
        self.pause = PaidPause(self)

    def missing(self, snap):
        adapter = self.config.adapters.get(snap['platform'])
        return missing(snap['plan'], snap['platform'],
                       total_budget_supported=getattr(adapter, snap['platform']+'_total_budget_paused', False) is True)

    def account(self, scope, platform):
        try:
            adapter = self.config.adapters.get(platform)
            return account_binding(adapter.account(*scope), platform, scope) if adapter else None
        except Exception:
            return None

    def authorised(self, snap, *, creation=True):
        try:
            adapter = self.config.adapters[snap['platform']]
            return ((not creation or self.setup.matches(snap))
                    and snap['account'] is not None and getattr(adapter, 'mode', None) == self.config.mode
                    and all(callable(getattr(adapter, n, None)) for n in ('check', 'create_paused', 'lookup'))
                    and self.config.authorised(snap['ownerId'], snap['organisationId'], snap['platform'], dict(snap['account'])) is True
                    and self.account((snap['ownerId'], snap['organisationId']), snap['platform']) == snap['account'])
        except Exception:
            return False

    def snapshot(self, con, ident, scope, platform):
        saved = read_draft(con, ident)
        snap = dict(campaignId=ident, ownerId=scope[0], organisationId=scope[1],
                    revision=saved['revision'], platform=platform, intent='create_paused_only',
                    plan=saved['document'].get(PLANS[platform]), account=self.account(scope, platform))
        adapter = self.config.adapters.get(platform)
        if callable(getattr(adapter, 'execution', None)):
            # Optional so legacy approvals retain their exact snapshot identity.
            try:
                snap['execution'] = adapter.execution(json.loads(json.dumps(snap)))
            except Exception:
                snap['execution'] = None
        setup = self.setup.read(con, scope, platform)
        if setup['revision']:
            snap['accountSetupRevision'] = setup['revision']
        return snap

    def current(self, con, row):
        snap = json.loads(row['snapshot_json'])
        scope = (row['owner_id'], row['organisation_id'])
        return (self.repo._owned(con, row['document_id'], scope)
                and self.snapshot(con, row['document_id'], scope, row['platform']) == snap)

    @staticmethod
    def public(row):
        return dict(jobId=row['job_id'], state=row['state'], mode=row['mode'], approvedAt=row['approved_at'],
                    snapshot=json.loads(row['snapshot_json']),
                    receipt=json.loads(row['receipt_json']) if row['receipt_json'] else None)

    def rows(self, con, ident, platform):
        return con.execute("SELECT * FROM growthrova_paid_jobs WHERE document_id=? AND platform=? AND json_extract(snapshot_json,'$.intent')='create_paused_only' ORDER BY approved_at DESC", (ident, platform)).fetchall()

    def claim(self):
        now = self.config.clock()
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE growthrova_paid_jobs SET state='uncertain' WHERE state='dispatching' AND lease_until<=? AND json_extract(snapshot_json,'$.intent')='create_paused_only'", (now,))
            con.execute("UPDATE growthrova_paid_jobs SET state='queued',claim_token=NULL,lease_until=NULL WHERE state='claimed' AND lease_until<=? AND json_extract(snapshot_json,'$.intent')='create_paused_only'", (now,))
            row = con.execute("SELECT * FROM growthrova_paid_jobs WHERE state='queued' AND mode=? AND json_extract(snapshot_json,'$.intent')='create_paused_only' ORDER BY approved_at LIMIT 1", (self.config.mode,)).fetchone()
            if not row:
                con.commit()
                return None
            token = uuid.uuid4().hex
            con.execute("UPDATE growthrova_paid_jobs SET state='claimed',claim_token=?,lease_until=? WHERE job_id=?", (token, now+self.LEASE_SECONDS, row['job_id']))
            con.commit()
            return dict(row), token

    def finish(self, row, value):
        result = receipt(value)
        expected = 'simulated' if row['mode'] == 'simulation' else 'paused'
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT * FROM growthrova_paid_jobs WHERE job_id=?', (row['job_id'],)).fetchone()
            if (not current or current['claim_token'] != row['claim_token']
                    or current['state'] not in ('dispatching', 'uncertain')):
                return
            prior = json.loads(current['receipt_json']) if current['receipt_json'] else None
            # Retain every known partial resource across incomplete/contradictory lookups.
            if result and prior and prior['resources']:
                conflict = any(key in result['resources'] and result['resources'][key] != ident
                               for key, ident in prior['resources'].items())
                result['resources'] = {**result['resources'], **prior['resources']}
                if conflict or result['outcome'] == 'failed':
                    result['outcome'] = 'partial'
            if result and prior and prior.get('progress'):
                result['progress'] = prior['progress']
            state = ('created_paused' if expected == 'paused' else expected) if result and result['outcome'] == expected else 'failed' if result and result['outcome'] == 'failed' else 'uncertain'
            con.execute('UPDATE growthrova_paid_jobs SET state=?,receipt_json=?,lease_until=NULL WHERE job_id=?',
                        (state, json.dumps(result) if result else current['receipt_json'], row['job_id']))
            con.commit()

    def resource_progress(self, row, step, identity=None):
        """Fence each Meta write; persist a late acknowledgement even after expiry.

        No resume operation exists: intent without an identity permanently holds
        that job for lookup/support. The next write requires current authority,
        saved version and an unexpired claim, independently of earlier writes.
        """
        if row['platform'] != 'meta' or step not in META_STEPS:
            return False
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT * FROM growthrova_paid_jobs WHERE job_id=?', (row['job_id'],)).fetchone()
            if (not current or current['claim_token'] != row['claim_token']
                    or current['state'] not in ('dispatching', 'uncertain')):
                return False
            prior = json.loads(current['receipt_json']) if current['receipt_json'] else dict(
                id=row['job_id'], resources={}, outcome='partial')
            progress, resources = prior.get('progress'), prior['resources']
            if identity is None:
                if (current['state'] != 'dispatching' or current['lease_until'] <= self.config.clock()
                        or set(resources) != set(META_STEPS[:META_STEPS.index(step)])
                        or (progress and progress['state'] != 'acknowledged')
                        or not self.current(con, current)
                        or not self.authorised(json.loads(current['snapshot_json']))):
                    return False
                try:
                    validate_asset(con, row['document_id'], json.loads(current['snapshot_json'])['plan'])
                except MarketingDraftError:
                    return False
                prior['progress'] = dict(step=step, state='intent')
            else:
                pattern = r'[a-fA-F0-9]{32}' if step == 'imageHash' else r'[0-9]{1,40}'
                if (not isinstance(identity, str) or not re.fullmatch(pattern, identity)
                        or progress != dict(step=step, state='intent') or step in resources):
                    return False
                resources[step] = identity
                prior['progress'] = dict(step=step, state='acknowledged')
            con.execute('UPDATE growthrova_paid_jobs SET receipt_json=?,lease_until=? WHERE job_id=?',
                        (json.dumps(prior), self.config.clock()+self.LEASE_SECONDS if identity is None else current['lease_until'], row['job_id']))
            con.commit()
            return True

    def retained_meta_image(self, row):
        from business_growthrova_images import retained_image_bytes
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN')
            if not self.current(con, row):
                raise ValueError('Saved creative access changed')
            plan = json.loads(row['snapshot_json'])['plan']
            validate_asset(con, row['document_id'], plan)
            return retained_image_bytes(con, row['document_id'], plan['asset']['operationId'])

    def run_one(self):
        # Stopping existing delivery takes priority over creating or launching more.
        if self.pause.run_one():
            return True
        claim = self.claim()
        if not claim:
            return self.launch.run_one()
        row, token = claim
        row['claim_token'] = token
        snap = json.loads(row['snapshot_json'])
        eligible = False
        try:
            eligible = (not self.missing(snap) and self.authorised(snap)
                        and self.config.adapters[row['platform']].check(json.loads(row['snapshot_json'])) is True)
        except Exception:
            pass
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT * FROM growthrova_paid_jobs WHERE job_id=?', (row['job_id'],)).fetchone()
            if current['state'] != 'claimed' or current['claim_token'] != token or current['lease_until'] <= self.config.clock():
                return True
            valid = eligible and self.current(con, current) and self.authorised(snap)
            if valid and row['platform'] == 'meta':
                try:
                    validate_asset(con, row['document_id'], snap['plan'])
                except MarketingDraftError:
                    valid = False
            con.execute('UPDATE growthrova_paid_jobs SET state=?,lease_until=? WHERE job_id=?',
                        ('dispatching' if valid else 'blocked', self.config.clock()+self.LEASE_SECONDS, row['job_id']))
            con.commit()  # Durable intent before any external mutation.
        if valid:
            value = None
            try:
                adapter = self.config.adapters[row['platform']]
                if row['platform'] == 'meta' and callable(getattr(adapter, 'create_paused_progressive', None)):
                    value = adapter.create_paused_progressive(json.loads(row['snapshot_json']),
                        idempotency_key=row['job_id'], image_bytes=self.retained_meta_image(row),
                        journal=lambda step, identity=None: self.resource_progress(row, step, identity))
                else:
                    value = adapter.create_paused(json.loads(row['snapshot_json']), idempotency_key=row['job_id'])
            except Exception:
                pass
            self.finish(row, value)
        return True

    def reconcile(self, row):
        if row['state'] != 'uncertain' or row['mode'] != self.config.mode:
            return
        snap = json.loads(row['snapshot_json'])
        # Reconcile the approved old plan/account, even if the draft has changed.
        if not self.authorised(snap, creation=False):
            return
        try:
            value = self.config.adapters[row['platform']].lookup(json.loads(row['snapshot_json']),
                idempotency_key=row['job_id'], reference=json.loads(row['receipt_json']) if row['receipt_json'] else None)
            if value is not None and self.authorised(snap, creation=False):
                self.finish(row, value)
        except Exception:
            return


def register_paid_delivery_routes(app, repo, root, *, config=None, revalidate=None):
    delivery = PaidDelivery(repo, config)
    app.extensions['growthrova_paid_delivery'] = delivery
    endpoint = root + '/<ident>/paid-provisioning/<platform>'

    def checked(con, organisation_id, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
            raise MarketingDraftError('Business access changed.', 'access_denied', 403)
        return None

    def platform_check(platform):
        if platform not in PLANS:
            raise MarketingDraftError('Choose Meta or Google Search.')

    @app.get(endpoint)
    def growthrova_paid_status(organisation_id, ident, platform):
        platform_check(platform)
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            snap = delivery.snapshot(con, ident, scope, platform)
            jobs = [delivery.public(r) for r in delivery.rows(con, ident, platform)]
            setup = delivery.setup.read(con, scope, platform)
        reasons = delivery.missing(snap) + delivery.setup.blockers(setup, snap)
        if not snap['account']:
            reasons.append('Connect and verify a dedicated business ad account.')
        elif snap['plan'] and snap['account']['currency'] != snap['plan']['currency']:
            reasons.append('Match the saved planning currency to the account currency.')
        if not delivery.authorised(snap):
            reasons.append('Paused creation permission, cost authority and adapter setup are not verified.')
        adapter = delivery.config.adapters.get(platform)
        if callable(getattr(adapter, 'blockers', None)):
            try:
                reasons.extend(adapter.blockers(json.loads(json.dumps(snap))))
            except Exception:
                reasons.append('Account setup could not be checked. Refresh before approval.')
        with closing(repo._connect()) as con:
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        return jsonify(review=snap, jobs=jobs, mode=delivery.config.mode, blockers=reasons, accountSetup=setup)

    @app.post(endpoint + '/account-discovery')
    def growthrova_paid_discovery(organisation_id, ident, platform):
        return observe_selection(organisation_id, ident, platform, pages=False)

    @app.post(endpoint + '/page-discovery')
    def growthrova_paid_page_discovery(organisation_id, ident, platform):
        if platform != 'meta':
            raise MarketingDraftError('Page selection is available for Meta requests only.')
        return observe_selection(organisation_id, ident, platform, pages=True)

    @app.post(endpoint + '/page-linkage')
    def growthrova_paid_page_linkage(organisation_id, ident, platform):
        platform_check(platform)
        if platform != 'meta' or request.get_json(silent=True) != {}:
            raise MarketingDraftError('Check the saved Meta account and Page without overrides.')
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            saved = delivery.setup.read(con, scope, platform)
        data = saved['data'] or {}
        if not data.get('accountId') or not data.get('pageId'):
            raise MarketingDraftError('Save your chosen ad account and Facebook Page before checking their access.')
        failed = False
        try:
            reader = getattr(delivery.config.discovery, 'observe_linkage', None)
            result = (reader(scope, platform, data['accountId'], data['pageId'])
                      if callable(reader) else dict(available=False))
        except Exception:
            failed = True
        with closing(repo._connect()) as con:
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            latest = delivery.setup.read(con, scope, platform)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            if latest != saved:
                raise MarketingDraftError('Account selection changed during the check. Reopen and check again.', 'revision_conflict', 409)
        if failed:
            raise MarketingDraftError('Account / Page access could not be confirmed. Your saved preparation is unchanged. Arrange connection review or retry the read.', 'account_read_unavailable', 503)
        response = jsonify(**result, setupRevision=saved['revision'], observedAt=delivery.config.clock())
        response.headers['Cache-Control'] = 'no-store'
        return response

    def observe_selection(organisation_id, ident, platform, *, pages):
        platform_check(platform)
        if request.get_json(silent=True) != {}:
            raise MarketingDraftError('Check assigned business accounts or Pages without identity or credential overrides.')
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        failed = False
        try:
            reader = getattr(delivery.config.discovery, 'observe_pages' if pages else 'observe', None)
            result = (reader(scope, platform) if callable(reader)
                      else dict(available=False, **{'pages' if pages else 'accounts': []}))
        except Exception:
            failed = True
        # Never acknowledge account metadata after a slow read changed access.
        with closing(repo._connect()) as con:
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        if failed:
            raise MarketingDraftError(('Page' if pages else 'Account')+' check could not be confirmed. Your saved request is unchanged. Retry the read or arrange connection review.', 'account_read_unavailable', 503)
        response = jsonify(**result, observedAt=delivery.config.clock())
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route(endpoint + '/account-setup', methods=['GET', 'POST'])
    def growthrova_paid_setup(organisation_id, ident, platform):
        platform_check(platform)
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE' if request.method == 'POST' else 'BEGIN')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            result = (delivery.setup.save(con, scope, platform, request.get_json(silent=True))
                      if request.method == 'POST' else delivery.setup.read(con, scope, platform))
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(result)

    @app.post(endpoint + '/<action>')
    def growthrova_paid_action(organisation_id, ident, platform, action):
        platform_check(platform)
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        data = request.get_json(silent=True)
        if action not in ('approve', 'pause', 'cancel', 'reconcile') or not isinstance(data, dict):
            raise MarketingDraftError('Choose a supported paused campaign action.')
        if action == 'approve':
            if (set(data) - {'expectedExecution', 'expectedSetupRevision'} != {'mutationId', 'expectedRevision', 'expectedMode', 'expectedAccount'}
                    or type(data['expectedRevision']) is not int
                    or ('expectedSetupRevision' in data and type(data['expectedSetupRevision']) is not int)):
                raise MarketingDraftError('Review the exact saved campaign, account and mode.')
        elif (set(data) != {'mutationId', 'jobIds'} or not isinstance(data['jobIds'], list)
              or len(data['jobIds']) > 200 or any(not isinstance(v, str) or not re.fullmatch('[a-f0-9]{64}', v) for v in data['jobIds'])):
            raise MarketingDraftError('Choose the saved creation jobs to control.')
        _id(data['mutationId'])
        encoded_request = json.dumps(data, sort_keys=True, separators=(',', ':'))
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            prior = con.execute('SELECT * FROM growthrova_paid_actions WHERE mutation_id=?', (data['mutationId'],)).fetchone()
            if prior and (prior['document_id'] != ident or prior['platform'] != platform
                          or prior['request_json'] != action + ':' + encoded_request):
                raise MarketingDraftError('This recovery request belongs to a different action.', 'mutation_conflict', 409)
            if not prior and con.execute('SELECT COUNT(*) FROM growthrova_paid_actions WHERE document_id=?', (ident,)).fetchone()[0] >= 2000:
                raise MarketingDraftError('Creation action history is full. Ask support.', 'job_limit', 409)
            if action == 'approve' and not prior:
                snap = delivery.snapshot(con, ident, scope, platform)
                if (data['expectedRevision'] != snap['revision'] or data['expectedMode'] != delivery.config.mode
                        or data['expectedAccount'] != snap['account']
                        or data.get('expectedExecution') != snap.get('execution')
                        or data.get('expectedSetupRevision') != snap.get('accountSetupRevision')):
                    raise MarketingDraftError('Saved plan, account or mode changed. Refresh and review again.', 'revision_conflict', 409)
                reasons = delivery.missing(snap) + delivery.setup.blockers(
                    delivery.setup.read(con, scope, platform), snap)
                adapter = delivery.config.adapters.get(platform)
                if callable(getattr(adapter, 'blockers', None)):
                    try:
                        reasons.extend(adapter.blockers(json.loads(json.dumps(snap))))
                    except Exception:
                        reasons.append('Account setup could not be checked. Refresh before approval.')
                if snap['account'] and snap['plan'] and snap['account']['currency'] != snap['plan']['currency']:
                    reasons.append('Match the plan currency to the selected account.')
                if reasons:
                    raise MarketingDraftError(' '.join(reasons))
                if platform == 'meta':
                    validate_asset(con, ident, snap['plan'])
                # Across modes/accounts/versions: never duplicate an unresolved creation.
                if con.execute("SELECT 1 FROM growthrova_paid_jobs WHERE document_id=? AND platform=? AND state IN ('dispatching','uncertain')", (ident, platform)).fetchone():
                    raise MarketingDraftError('Check the earlier unknown outcome before another creation.', 'outcome_uncertain', 409)
                job_id = _hash(dict(snapshot=snap, mode=delivery.config.mode))
                old = con.execute('SELECT * FROM growthrova_paid_jobs WHERE job_id=?', (job_id,)).fetchone()
                if not old or old['state'] in ('blocked', 'paused'):
                    if len(delivery.rows(con, ident, platform)) >= 200 and not old:
                        raise MarketingDraftError('Campaign creation history is full. Ask support before further creation.', 'job_limit', 409)
                    con.execute("UPDATE growthrova_paid_jobs SET state='cancelled',claim_token=NULL,lease_until=NULL WHERE document_id=? AND platform=? AND json_extract(snapshot_json,'$.intent')='create_paused_only' AND state IN ('queued','claimed','paused','blocked') AND job_id<>?", (ident, platform, job_id))
                    state = 'queued' if delivery.authorised(snap) else 'blocked'
                    if old:
                        con.execute('UPDATE growthrova_paid_jobs SET state=?,claim_token=NULL,lease_until=NULL,approved_at=? WHERE job_id=?', (state, delivery.config.clock(), job_id))
                    else:
                        con.execute('INSERT INTO growthrova_paid_jobs(job_id,document_id,platform,owner_id,organisation_id,snapshot_json,mode,state,approved_at) VALUES(?,?,?,?,?,?,?,?,?)',
                                    (job_id, ident, platform, *scope, json.dumps(snap, sort_keys=True, separators=(',', ':')), delivery.config.mode, state, delivery.config.clock()))
            elif action in ('pause', 'cancel') and not prior:
                for job_id in data['jobIds']:
                    con.execute("UPDATE growthrova_paid_jobs SET state=?,claim_token=NULL,lease_until=NULL WHERE job_id=? AND document_id=? AND platform=? AND json_extract(snapshot_json,'$.intent')='create_paused_only' AND state IN ('queued','claimed','paused','blocked')", ('paused' if action == 'pause' else 'cancelled', job_id, ident, platform))
            rows = delivery.rows(con, ident, platform)
            if action != 'approve':
                rows = [row for row in rows if row['job_id'] in data['jobIds']]
            if not prior:
                con.execute('INSERT INTO growthrova_paid_actions VALUES(?,?,?,?)', (data['mutationId'], ident, platform, action + ':' + encoded_request))
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        if action == 'reconcile':
            for row in rows:
                delivery.reconcile(row)
        return growthrova_paid_status(organisation_id, ident, platform)

    from business_growthrova_paid_launch import register_launch_routes
    register_launch_routes(app, delivery, endpoint, checked)
    from business_growthrova_paid_pause import register_pause_routes
    register_pause_routes(app, delivery, endpoint, checked)
    from business_growthrova_paid_observation import register_observation_routes
    register_observation_routes(app, delivery, endpoint, checked)
    return delivery
