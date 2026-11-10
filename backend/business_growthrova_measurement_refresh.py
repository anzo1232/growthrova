"""Explicitly configured read-only report refresh; no installed credentials or host.

A worker may call app.extensions['growthrova_measurement_refresh'].run_one().
The trusted authorised callback must freshly verify owner/business read grants and
cost authority; it cannot rely on browser sessions. Expired reads never requeue.
Report replacement and job completion commit atomically under the claim fence.
"""
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
import time
import uuid
from zoneinfo import ZoneInfo

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id
from business_marketing_offline import OfflineDocumentAccessError
from business_growthrova_measurement import normalise_report, write_report


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


@dataclass(frozen=True)
class MeasurementConfig:
    adapters: dict = field(default_factory=dict, repr=False)
    authorised: object = field(default=None, repr=False)
    enabled: bool = False
    clock: object = time.time


class MeasurementRefresh:
    LEASE = 180

    def __init__(self, repo, config):
        self.repo, self.config = repo, config or MeasurementConfig()
        with closing(repo._connect()) as con:
            con.executescript('''CREATE TABLE IF NOT EXISTS growthrova_measurement_jobs(
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
                document_id TEXT NOT NULL, fingerprint TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                state TEXT NOT NULL, claim TEXT, lease REAL NOT NULL, result_json TEXT,
                created REAL NOT NULL, updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS growthrova_measurement_queue
                  ON growthrova_measurement_jobs(state,created);''')

    def account(self, scope, platform):
        try:
            if self.config.enabled is not True:
                return None
            value = self.config.adapters[platform].account(*scope)
            fields = {'platform', 'ownerId', 'organisationId', 'accountId', 'label',
                      'connectionVersion', 'currency', 'timezone'}
            if (not isinstance(value, dict) or set(value) != fields or value['platform'] != platform
                    or (value['ownerId'], value['organisationId']) != scope
                    or any(not isinstance(v, str) or not v.strip() or len(v) > 180
                           or any(ord(c) < 32 for c in v) for v in value.values())):
                return None
            normal = normalise_report(dict(platform=platform, accountId=value['accountId'], campaignId='1',
                currency=value['currency'], timezone=value['timezone'], sourceReference='Account validation',
                rows=[dict(date='2000-01-01', impressions=0, clicks=0, spend='0')]))
            if value['accountId'] != normal['accountId']:
                return None
            return deepcopy(value)
        except Exception:
            return None

    def authorised(self, snap):
        try:
            scope = (snap['ownerId'], snap['organisationId'])
            return (self.account(scope, snap['account']['platform']) == snap['account']
                    and callable(self.config.authorised)
                    and self.config.authorised(*scope, deepcopy(snap['account'])) is True)
        except Exception:
            return False

    def current(self, con, row):
        return self.repo._owned(con, row['document_id'], (row['owner_id'], row['organisation_id']))

    @staticmethod
    def public(row):
        return dict(id=row['id'], state=row['state'], request=json.loads(row['snapshot_json']),
                    result=json.loads(row['result_json']) if row['result_json'] else None,
                    created=row['created'], updated=row['updated'])

    def expire(self, con):
        con.execute("UPDATE growthrova_measurement_jobs SET state='failed',result_json=?,updated=? "
                    "WHERE state='reading' AND lease<=?",
                    (encoded(dict(message='Read confirmation expired. Request a fresh read; saved observations were retained.')),
                     self.config.clock(), self.config.clock()))

    def queue(self, con, scope, ident, payload, *, schedule=None, validate_only=False):
        job_id, report_id = _id(payload['id']), _id(payload['reportId'])
        base = payload['expectedRevision']
        if type(base) is not int or not 0 <= base < 100:
            raise MarketingDraftError('Reopen the current report version.')
        fields = {'reportId', 'expectedRevision', 'account', 'campaignId', 'from', 'to'}
        fingerprint = hashlib.sha256(encoded(payload).encode()).hexdigest()
        account = payload['account']
        snap = dict(ownerId=scope[0], organisationId=scope[1], **{k: payload[k] for k in fields - {'id'}})
        if schedule is not None:
            snap['schedule'] = schedule
        if not isinstance(account, dict) or not self.authorised(snap):
            raise MarketingDraftError('Connect and authorise this dedicated reporting account first.', 'account_unavailable', 409)
        try:
            first, last = date.fromisoformat(payload['from']), date.fromisoformat(payload['to'])
            if (first.isoformat() != payload['from'] or last.isoformat() != payload['to']
                    or not 0 <= (last-first).days < 100
                    or last >= datetime.fromtimestamp(self.config.clock(), ZoneInfo(account['timezone'])).date()):
                raise ValueError()
        except (TypeError, ValueError):
            raise MarketingDraftError('Choose 1–100 completed reporting dates in the account timezone.') from None
        normalise_report(dict(platform=account['platform'], accountId=account['accountId'], campaignId=payload['campaignId'],
            currency=account['currency'], timezone=account['timezone'], sourceReference='Approved account read',
            rows=[dict(date=payload['from'], impressions=0, clicks=0, spend='0')]))
        target = con.execute('SELECT * FROM growthrova_measurement_reports WHERE id=?', (report_id,)).fetchone()
        if target and (target['owner_id'], target['organisation_id'], target['document_id']) != (*scope, ident):
            raise OfflineDocumentAccessError('Report access denied')
        if (target['revision'] if target else 0) != base:
            raise MarketingDraftError('Reopen the current report.', 'revision_conflict', 409)
        if target:
            data = json.loads(target['data_json'])
            if (any(data[k] != account[k] for k in ('platform', 'accountId', 'currency', 'timezone'))
                    or data['campaignId'] != payload['campaignId']
                    or any(not payload['from'] <= r['date'] <= payload['to'] for r in data['rows'])):
                raise MarketingDraftError('Refresh the same campaign and include all currently saved dates.')
        self.expire(con)
        jobs = con.execute('SELECT * FROM growthrova_measurement_jobs WHERE owner_id=? AND organisation_id=?', scope).fetchall()
        if len(jobs) >= 100:
            raise MarketingDraftError('This business has reached its refresh history limit.', 'storage_limit', 409)
        if any(j['state'] in ('queued', 'reading') and json.loads(j['snapshot_json'])['reportId'] == report_id for j in jobs):
            raise MarketingDraftError('A refresh for this report is already pending.', 'refresh_pending', 409)
        if validate_only:
            return snap
        now = self.config.clock()
        con.execute('INSERT INTO growthrova_measurement_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (job_id, *scope, ident, fingerprint, encoded(snap), 'queued', None, 0, None, now, now))
        result = self.public(con.execute('SELECT * FROM growthrova_measurement_jobs WHERE id=?', (job_id,)).fetchone())
        return result

    def run_one(self):
        self.schedules.prepare_due()
        token = uuid.uuid4().hex
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            self.expire(con)
            row = con.execute("SELECT * FROM growthrova_measurement_jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                con.commit()
                return False
            row = dict(row)
            con.execute("UPDATE growthrova_measurement_jobs SET state='reading',claim=?,lease=?,updated=? WHERE id=?",
                        (token, self.config.clock()+self.LEASE, self.config.clock(), row['id']))
            con.commit()  # Recoverable read intent before provider access.
        snap = json.loads(row['snapshot_json'])
        result, data = dict(message='Account access or report data could not be confirmed. Saved observations were retained.'), None
        try:
            with closing(self.repo._connect()) as con:
                live = con.execute('SELECT * FROM growthrova_measurement_jobs WHERE id=?', (row['id'],)).fetchone()
                valid = (live['state'] == 'reading' and live['claim'] == token
                         and live['lease'] > self.config.clock() and self.current(con, row) and self.schedules.valid(con, snap) and self.authorised(snap))
            if valid:
                data = self.config.adapters[snap['account']['platform']].read(deepcopy(snap))
                # Adapter output is not trusted to select another account/resource or time range.
                if isinstance(data, dict) and data.get('rows') == []:
                    result = dict(message='The platform returned no daily observations. Existing reports were retained; no zero performance is inferred.')
                data = normalise_report(data)
                account = snap['account']
                if (any(data[k] != account[k] for k in ('platform', 'accountId', 'currency', 'timezone'))
                        or data['campaignId'] != snap['campaignId']
                        or any(not snap['from'] <= r['date'] <= snap['to'] for r in data['rows'])):
                    raise ValueError('Report identity mismatch')
        except Exception:
            data = None  # Never persist provider diagnostics or credentials.
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            live = con.execute('SELECT * FROM growthrova_measurement_jobs WHERE id=?', (row['id'],)).fetchone()
            if live['state'] != 'reading' or live['claim'] != token or live['lease'] <= self.config.clock():
                return True
            state = 'failed'
            if (data is not None and self.current(con, row) and self.schedules.valid(con, snap)
                    and self.authorised(snap)):
                payload = dict(id=snap['reportId'], mutationId=row['id'], expectedRevision=snap['expectedRevision'], data=data)
                source = dict(jobId=row['id'], account=deepcopy(snap['account']), requestedFrom=snap['from'],
                              requestedTo=snap['to'], observedAt=self.config.clock(),
                              returnedDates=[r['date'] for r in data['rows']],
                              gaps='Unreturned dates are not filled with zeros; metrics may be revised by the platform.')
                con.execute('SAVEPOINT report_write')
                try:
                    saved = write_report(con, (row['owner_id'], row['organisation_id']), row['document_id'],
                                         payload, hashlib.sha256(encoded(payload).encode()).hexdigest(), source=source)
                    if (not self.current(con, row) or not self.authorised(snap)
                            or not self.schedules.valid(con, snap) or live['lease'] <= self.config.clock()):
                        raise OfflineDocumentAccessError('Report access changed')
                    result = dict(message='Provider observations saved.', reportId=saved['id'], revision=saved['revision'])
                    state = 'completed'
                    con.execute('RELEASE report_write')
                except (MarketingDraftError, OfflineDocumentAccessError) as error:
                    con.execute('ROLLBACK TO report_write')
                    con.execute('RELEASE report_write')
                    result = dict(message='Report changed, overlapped another report or access changed. Reopen reports before requesting a fresh read.',
                                  code=getattr(error, 'code', 'access_changed'))
            con.execute('UPDATE growthrova_measurement_jobs SET state=?,result_json=?,updated=? WHERE id=?',
                        (state, encoded(result), self.config.clock(), row['id']))
            self.schedules.finish(con, snap, row['id'], state, result)
            con.commit()
        return True


def register_refresh_routes(app, repo, endpoint, checked, *, config=None):
    service = MeasurementRefresh(repo, config)
    from business_growthrova_measurement_schedule import MeasurementSchedules
    service.schedules = MeasurementSchedules(service)
    service.schedules.register(app, endpoint, checked)
    app.extensions['growthrova_measurement_refresh'] = service

    @app.get(endpoint + '/refresh')
    def growthrova_measurement_refresh_status(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        accounts = [account for platform in ('meta', 'google') if (account := service.account(scope, platform))]
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            service.expire(con)
            rows = con.execute('SELECT * FROM growthrova_measurement_jobs WHERE owner_id=? AND organisation_id=? '
                               'AND document_id=? ORDER BY created DESC LIMIT 100', (*scope, ident)).fetchall()
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(accounts=accounts, jobs=[service.public(row) for row in rows], workerManagedExternally=True)

    @app.post(endpoint + '/refresh')
    def growthrova_measurement_refresh_request(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        payload = request.get_json(silent=True)
        fields = {'id', 'reportId', 'expectedRevision', 'account', 'campaignId', 'from', 'to'}
        if not isinstance(payload, dict) or set(payload) != fields:
            raise MarketingDraftError('Choose the reviewed account, campaign and reporting period.')
        job_id, report_id = _id(payload['id']), _id(payload['reportId'])
        base = payload['expectedRevision']
        if type(base) is not int or not 0 <= base < 100:
            raise MarketingDraftError('Reopen the current report version.')
        fingerprint = hashlib.sha256(encoded(payload).encode()).hexdigest()
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            old = con.execute('SELECT * FROM growthrova_measurement_jobs WHERE id=?', (job_id,)).fetchone()
            if old:
                if (old['owner_id'], old['organisation_id'], old['document_id']) != (*scope, ident):
                    raise OfflineDocumentAccessError('Read access denied')
                if old['fingerprint'] != fingerprint:
                    raise MarketingDraftError('This request identity was already used.', 'revision_conflict', 409)
                result = service.public(old)
            else:
                result = service.queue(con, scope, ident, payload)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(**result, replayed=bool(old))

    return service
