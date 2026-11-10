"""Bounded fixed or advancing completed-date reads; no scheduler host installed."""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import uuid

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id
from business_marketing_offline import OfflineDocumentAccessError
from business_growthrova_measurement_refresh import encoded


class MeasurementSchedules:
    def __init__(self, service):
        self.service, self.repo = service, service.repo
        with closing(self.repo._connect()) as con:
            con.executescript('''CREATE TABLE IF NOT EXISTS growthrova_measurement_schedules(
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
                document_id TEXT NOT NULL, revision INTEGER NOT NULL, data_json TEXT NOT NULL,
                state TEXT NOT NULL, next_due REAL NOT NULL, runs INTEGER NOT NULL,
                report_revision INTEGER NOT NULL, last_job TEXT, message TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS growthrova_measurement_schedule_receipts(
                schedule_id TEXT NOT NULL, mutation_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                result_json TEXT NOT NULL, PRIMARY KEY(schedule_id,mutation_id));''')

    @staticmethod
    def public(row):
        return dict(id=row['id'], revision=row['revision'], data=json.loads(row['data_json']),
                    state=row['state'], nextDue=row['next_due'], runs=row['runs'],
                    reportRevision=row['report_revision'], lastJob=row['last_job'], message=row['message'])

    def period(self, data):
        """Extend coverage without silently discarding earlier report dates."""
        read = dict(data['read'])
        collection = data.get('collection')
        if collection is not None:
            today = datetime.fromtimestamp(self.service.config.clock(), ZoneInfo(read['account']['timezone'])).date()
            last = min(today - timedelta(days=collection['lagDays']), date.fromisoformat(collection['through']))
            if last < date.fromisoformat(read['to']):
                raise MarketingDraftError('The reviewed period is not yet complete at the selected reporting lag.')
            read['to'] = last.isoformat()
        return read

    def valid(self, con, snap):
        ref = snap.get('schedule')
        if ref is None:
            return True
        row = con.execute('SELECT * FROM growthrova_measurement_schedules WHERE id=?', (ref['id'],)).fetchone()
        return bool(row and row['revision'] == ref['revision'] and row['state'] == 'active'
                    and (row['owner_id'], row['organisation_id'], row['document_id']) ==
                    (snap['ownerId'], snap['organisationId'], ref['documentId'])
                    and row['report_revision'] == snap['expectedRevision'])

    def finish(self, con, snap, job_id, state, result):
        ref = snap.get('schedule')
        if ref is None or not self.valid(con, snap):
            return
        row = con.execute('SELECT * FROM growthrova_measurement_schedules WHERE id=?', (ref['id'],)).fetchone()
        data = json.loads(row['data_json'])
        at_end = data.get('collection') is not None and snap['to'] == data['collection']['through']
        next_state = ('finished' if row['runs'] >= data['maxRuns'] or at_end else 'active') if state == 'completed' else 'held'
        con.execute('UPDATE growthrova_measurement_schedules SET state=?,report_revision=?,message=? WHERE id=? AND last_job=?',
                    (next_state, result.get('revision', row['report_revision']), result['message'], row['id'], job_id))

    def prepare_due(self):
        """One latest occurrence per rule. Transactions serialize concurrent workers."""
        if self.service.config.enabled is not True:
            return
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            self.service.expire(con)
            now = self.service.config.clock()
            rows = con.execute("SELECT * FROM growthrova_measurement_schedules WHERE state='active' AND next_due<=? ORDER BY next_due LIMIT 30", (now,)).fetchall()
            for row in rows:
                if row['last_job']:
                    job = con.execute('SELECT state FROM growthrova_measurement_jobs WHERE id=?', (row['last_job'],)).fetchone()
                    if job and job['state'] in ('queued', 'reading'):
                        continue
                    if not job or job['state'] != 'completed':
                        con.execute("UPDATE growthrova_measurement_schedules SET state='held',message=? WHERE id=?",
                                    ('Previous read was not confirmed. Review the report and save a new rule.', row['id']))
                        continue
                data = json.loads(row['data_json'])
                scope = row['owner_id'], row['organisation_id']
                con.execute('SAVEPOINT due_read')
                try:
                    if not self.repo._owned(con, row['document_id'], scope):
                        raise OfflineDocumentAccessError('Access changed')
                    payload = dict(self.period(data), id=uuid.uuid4().hex, expectedRevision=row['report_revision'])
                    self.service.queue(con, scope, row['document_id'], payload,
                        schedule=dict(id=row['id'], revision=row['revision'], documentId=row['document_id']))
                    if not self.repo._owned(con, row['document_id'], scope):
                        raise OfflineDocumentAccessError('Access changed')
                    # Skip missed intervals: no catch-up burst after an outage.
                    step = data['intervalDays'] * 86400
                    due = row['next_due'] + (int((now-row['next_due']) // step)+1)*step
                    con.execute('UPDATE growthrova_measurement_schedules SET next_due=?,runs=runs+1,last_job=?,message=? WHERE id=?',
                                (due, payload['id'], 'Read queued; observations are not yet confirmed.', row['id']))
                    con.execute('RELEASE due_read')
                except (MarketingDraftError, OfflineDocumentAccessError):
                    con.execute('ROLLBACK TO due_read')
                    con.execute('RELEASE due_read')
                    con.execute("UPDATE growthrova_measurement_schedules SET state='held',message=? WHERE id=?",
                                ('Account, report version or read limit changed. Reopen and review before resuming.', row['id']))
            con.commit()

    def register(self, app, endpoint, checked):
        @app.get(endpoint + '/schedules')
        def growthrova_measurement_schedules(organisation_id, ident):
            self.repo.read(organisation_id, ident)
            scope = self.repo._scope(organisation_id)
            with closing(self.repo._connect()) as con:
                con.execute('BEGIN')
                rows = con.execute('SELECT * FROM growthrova_measurement_schedules WHERE owner_id=? AND organisation_id=? AND document_id=?', (*scope, ident)).fetchall()
                error = checked(con, organisation_id, ident, scope)
                if error is not None:
                    return error
            return jsonify(schedules=[self.public(row) for row in rows])

        @app.post(endpoint + '/schedules')
        def growthrova_measurement_schedule_save(organisation_id, ident):
            self.repo.read(organisation_id, ident)
            scope = self.repo._scope(organisation_id)
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or set(payload) != {'id', 'mutationId', 'expectedRevision', 'data'}:
                raise MarketingDraftError('Review the repeat rule before saving.')
            rule_id, mutation = _id(payload['id']), _id(payload['mutationId'])
            base = payload['expectedRevision']
            if type(base) is not int or not 0 <= base < 100:
                raise MarketingDraftError('Reopen the repeat rule; its history may be full.')
            fingerprint = hashlib.sha256(encoded(payload).encode()).hexdigest()
            with closing(self.repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                error = checked(con, organisation_id, ident, scope)
                if error is not None:
                    return error
                old = con.execute('SELECT * FROM growthrova_measurement_schedules WHERE id=?', (rule_id,)).fetchone()
                if old and (old['owner_id'], old['organisation_id'], old['document_id']) != (*scope, ident):
                    raise OfflineDocumentAccessError('Rule access denied')
                receipt = con.execute('SELECT * FROM growthrova_measurement_schedule_receipts WHERE schedule_id=? AND mutation_id=?', (rule_id, mutation)).fetchone()
                if receipt:
                    if receipt['fingerprint'] != fingerprint:
                        raise MarketingDraftError('This save identity was already used.', 'revision_conflict', 409)
                    result = json.loads(receipt['result_json'])
                else:
                    if (old['revision'] if old else 0) != base:
                        raise MarketingDraftError('Reopen the latest repeat rule.', 'revision_conflict', 409)
                    data = payload['data']
                    if (not isinstance(data, dict) or set(data) not in (
                            {'enabled', 'read', 'intervalDays', 'maxRuns', 'startDate'},
                            {'enabled', 'read', 'intervalDays', 'maxRuns', 'startDate', 'collection'})
                            or type(data['enabled']) is not bool):
                        raise MarketingDraftError('Review the rule settings.')
                    # Pause remains possible while the account is disconnected.
                    if not data['enabled']:
                        if not old:
                            raise MarketingDraftError('Save a reviewed rule first.')
                        data = dict(json.loads(old['data_json']), enabled=False)
                        due, report_revision = old['next_due'], old['report_revision']
                    else:
                        # Keep the final bounded revision available for pause.
                        if base >= 99:
                            raise MarketingDraftError('This rule history is full. Pause it before preparing another rule.')
                        if any(type(data[k]) is not int or not 1 <= data[k] <= 30 for k in ('intervalDays', 'maxRuns')):
                            raise MarketingDraftError('Choose a 1–30-day interval and 1–30 reads.')
                        try:
                            start = datetime.strptime(data['startDate'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                            now = datetime.fromtimestamp(self.service.config.clock(), timezone.utc)
                            if start.strftime('%Y-%m-%d') != data['startDate'] or not 0 <= (start.date()-now.date()).days <= 365:
                                raise ValueError()
                            due = max(start.timestamp(), self.service.config.clock())
                        except (TypeError, ValueError):
                            raise MarketingDraftError('Choose a UTC start date from today through the next year.') from None
                        read = data['read']
                        if not isinstance(read, dict) or set(read) != {'reportId', 'expectedRevision', 'account', 'campaignId', 'from', 'to'}:
                            raise MarketingDraftError('Review the exact account, campaign, report version and dates.')
                        if (type(read['expectedRevision']) is not int or read['expectedRevision'] < 1
                                or read['expectedRevision'] + data['maxRuns'] > 100):
                            raise MarketingDraftError('Reduce the run count to fit the report history limit.')
                        self.service.queue(con, scope, ident, dict(read, id=uuid.uuid4().hex), validate_only=True)
                        if 'collection' in data:
                            collection = data['collection']
                            if (not isinstance(collection, dict) or set(collection) != {'through', 'lagDays'}
                                    or type(collection['lagDays']) is not int or not 1 <= collection['lagDays'] <= 7):
                                raise MarketingDraftError('Choose a final reporting date and a 1–7-day completion lag.')
                            try:
                                first, last = date.fromisoformat(read['from']), date.fromisoformat(collection['through'])
                                if (last.isoformat() != collection['through'] or not 0 <= (last-first).days < 100
                                        or last < date.fromisoformat(read['to'])):
                                    raise ValueError()
                            except (TypeError, ValueError):
                                raise MarketingDraftError('Choose a final date covering the saved period, within 100 days of its start.') from None
                            self.service.queue(con, scope, ident, dict(self.period(data), id=uuid.uuid4().hex), validate_only=True)
                        report_revision = read['expectedRevision']
                        existing = con.execute('SELECT * FROM growthrova_measurement_schedules WHERE owner_id=? AND organisation_id=?', scope).fetchall()
                        if not old and len(existing) >= 30:
                            raise MarketingDraftError('This business has reached its 30-rule limit.')
                        if any(r['id'] != rule_id and r['state'] == 'active' and json.loads(r['data_json'])['read']['reportId'] == read['reportId'] for r in existing):
                            raise MarketingDraftError('Pause the other repeat rule for this report first.')
                    if old:
                        con.execute("UPDATE growthrova_measurement_jobs SET state='failed',result_json=?,updated=? WHERE id=? AND state='queued'",
                            (encoded(dict(message='Repeat rule changed or paused before the read.')), self.service.config.clock(), old['last_job']))
                        con.execute('UPDATE growthrova_measurement_schedules SET revision=?,data_json=?,state=?,next_due=?,runs=?,report_revision=?,last_job=NULL,message=? WHERE id=?',
                            (base+1, encoded(data), 'active' if data['enabled'] else 'paused', due, 0 if data['enabled'] else old['runs'], report_revision,
                             'Repeat rule saved. A configured worker is required.' if data['enabled'] else 'Paused. An in-flight read may finish remotely; its result will not be saved.', rule_id))
                    else:
                        con.execute('INSERT INTO growthrova_measurement_schedules VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                            (rule_id, *scope, ident, 1, encoded(data), 'active', due, 0, report_revision, None, 'Repeat rule saved. A configured worker is required.'))
                    result = self.public(con.execute('SELECT * FROM growthrova_measurement_schedules WHERE id=?', (rule_id,)).fetchone())
                    con.execute('INSERT INTO growthrova_measurement_schedule_receipts VALUES(?,?,?,?)', (rule_id, mutation, fingerprint, encoded(result)))
                error = checked(con, organisation_id, ident, scope)
                if error is not None:
                    return error
                con.commit()
            return jsonify(**result, replayed=bool(receipt))

