"""Owner-supplied platform exports, kept distinct from connected attribution.

The optional refresh service supplies provider observations through this same
writer. Immutable receipts preserve previous report versions; corrections replace
only the selected report's current observations.
"""
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id, _text
from business_marketing_offline import OfflineDocumentAccessError


def normalise_report(value):
    fields = {'platform', 'accountId', 'campaignId', 'currency', 'timezone', 'sourceReference', 'rows'}
    if not isinstance(value, dict) or set(value) != fields:
        raise MarketingDraftError('Use the supported platform report fields.')
    result = {key: _text(value[key], key, limit, True).strip() for key, limit in
              dict(platform=10, accountId=160, campaignId=160, currency=3,
                   timezone=100, sourceReference=512).items()}
    if result['platform'] not in ('meta', 'google') or not re.fullmatch('[A-Z]{3}', result['currency']):
        raise MarketingDraftError('Choose Meta or Google and a three-letter currency code.')
    # Google commonly displays account IDs with hyphens; use one identity for
    # overlap checks. Only numeric account/campaign resources are supported here.
    if result['platform'] == 'google':
        result['accountId'] = result['accountId'].replace('-', '')
    for key in ('accountId', 'campaignId'):
        if not re.fullmatch(r'[1-9][0-9]{0,39}', result[key]):
            raise MarketingDraftError('Use the numeric platform account and campaign IDs, without prefixes or leading zeros.')
    try:
        zone = ZoneInfo(result['timezone'])
    except (ValueError, ZoneInfoNotFoundError):
        raise MarketingDraftError('Use an IANA reporting timezone, such as Europe/London.') from None
    rows = value['rows']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise MarketingDraftError('Include between 1 and 100 daily observations.')
    result['rows'], seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'date', 'impressions', 'clicks', 'spend'}:
            raise MarketingDraftError('Each daily row needs date, impressions, clicks and spend.')
        day = _text(row['date'], 'report date', 10, True)
        try:
            parsed = date.fromisoformat(day)
            if parsed.isoformat() != day or parsed > datetime.now(zone).date():
                raise ValueError()
        except ValueError:
            raise MarketingDraftError('Use valid report dates that are not in the future.') from None
        if day in seen:
            raise MarketingDraftError('Include each report date only once.')
        seen.add(day)
        for key in ('impressions', 'clicks'):
            if type(row[key]) is not int or not 0 <= row[key] <= 10**12:
                raise MarketingDraftError('Impressions and clicks must be non-negative whole numbers within the report limit.')
        spend = _text(row['spend'], 'spend', 20)
        if not re.fullmatch(r'(0|[1-9][0-9]{0,8})(\.[0-9]{1,6})?', spend):
            raise MarketingDraftError('Use non-negative spend with up to six decimal places and no separators.')
        # Never sum currency using binary floats. Public rows retain canonical decimal wording.
        micros = int(Decimal(spend) * 1000000)
        result['rows'].append(dict(date=day, impressions=row['impressions'], clicks=row['clicks'],
                                   spend=format(Decimal(micros) / 1000000, 'f')))
    result['rows'].sort(key=lambda row: row['date'])
    return result


def snapshot(row):
    return dict(id=row['id'], revision=row['revision'], data=json.loads(row['data_json']),
                created=row['created'], updated=row['updated'], provenance='owner_supplied_export')


def write_report(con, scope, ident, payload, fingerprint, *, source=None):
    """Shared writer; caller holds BEGIN IMMEDIATE and rechecks authority before commit."""
    report_id, mutation, base = payload['id'], payload['mutationId'], payload['expectedRevision']
    old = con.execute('SELECT * FROM growthrova_measurement_reports WHERE id=?', (report_id,)).fetchone()
    if old and (old['owner_id'], old['organisation_id'], old['document_id']) != (*scope, ident):
        raise OfflineDocumentAccessError('Report access denied')
    receipt = con.execute('SELECT * FROM growthrova_measurement_receipts WHERE report_id=? AND mutation_id=?',
                          (report_id, mutation)).fetchone()
    if receipt:
        if receipt['fingerprint'] != fingerprint or not old or old['revision'] != receipt['revision']:
            raise MarketingDraftError('This report has changed. Reopen it before saving.', 'revision_conflict', 409)
        result = report_snapshot(con, old)
    else:
        if (old['revision'] if old else 0) != base:
            raise MarketingDraftError('Another editor saved this report. Reopen it.', 'revision_conflict', 409)
        data = normalise_report(payload['data'])
        others = con.execute('SELECT id,data_json FROM growthrova_measurement_reports WHERE owner_id=? '
                             'AND organisation_id=? AND id<>?', (*scope, report_id)).fetchall()
        if not old and len(others) >= 30:
            raise MarketingDraftError('This business has reached its 30-report limit.', 'storage_limit', 409)
        dates = {row['date'] for row in data['rows']}
        for other in others:
            existing = json.loads(other['data_json'])
            if all(existing[key] == data[key] for key in ('platform', 'accountId', 'campaignId')) and dates.intersection(row['date'] for row in existing['rows']):
                raise MarketingDraftError('These campaign dates already exist in a report for this business. Correct the original report instead.', 'overlapping_report', 409)
        encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        now = time.time()
        if old:
            con.execute('UPDATE growthrova_measurement_reports SET revision=?,data_json=?,updated=? WHERE id=?',
                        (base + 1, encoded, now, report_id))
        else:
            con.execute('INSERT INTO growthrova_measurement_reports VALUES(?,?,?,?,?,?,?,?)',
                        (report_id, *scope, ident, 1, encoded, now, now))
        con.execute('INSERT INTO growthrova_measurement_receipts VALUES(?,?,?,?,?,?)',
                    (report_id, mutation, base + 1, fingerprint, encoded, now))
        if source is not None:
            con.execute('INSERT INTO growthrova_measurement_sources VALUES(?,?,?)',
                        (report_id, base + 1, json.dumps(source, sort_keys=True)))
        result = report_snapshot(con, con.execute('SELECT * FROM growthrova_measurement_reports WHERE id=?', (report_id,)).fetchone())
    return dict(**result, replayed=bool(receipt))


def report_snapshot(con, row):
    result = snapshot(row)
    source = con.execute('SELECT data_json FROM growthrova_measurement_sources WHERE report_id=? AND revision=?',
                         (row['id'], row['revision'])).fetchone()
    if source:
        result.update(provenance='provider_read', observation=json.loads(source['data_json']))
    return result


def register_measurement_routes(app, repo, root, *, revalidate=None, config=None):
    with closing(repo._connect()) as con:
        con.executescript('''
          CREATE TABLE IF NOT EXISTS growthrova_measurement_reports(
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
            document_id TEXT NOT NULL, revision INTEGER NOT NULL, data_json TEXT NOT NULL,
            created REAL NOT NULL, updated REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS growthrova_measurement_scope
            ON growthrova_measurement_reports(owner_id,organisation_id,document_id);
          CREATE TABLE IF NOT EXISTS growthrova_measurement_receipts(
            report_id TEXT NOT NULL, mutation_id TEXT NOT NULL, revision INTEGER NOT NULL,
            fingerprint TEXT NOT NULL, data_json TEXT NOT NULL, occurred REAL NOT NULL,
            PRIMARY KEY(report_id,mutation_id));
          CREATE TABLE IF NOT EXISTS growthrova_measurement_sources(
            report_id TEXT NOT NULL, revision INTEGER NOT NULL, data_json TEXT NOT NULL,
            PRIMARY KEY(report_id,revision));
        ''')

    def checked(con, organisation_id, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
            raise OfflineDocumentAccessError('Campaign access changed')

    endpoint = root + '/<ident>/measurement'

    @app.get(endpoint)
    def growthrova_measurement_list(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            rows = con.execute('SELECT * FROM growthrova_measurement_reports WHERE owner_id=? '
                               'AND organisation_id=? AND document_id=? ORDER BY updated DESC', (*scope, ident)).fetchall()
            result = [report_snapshot(con, row) for row in rows]
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        return jsonify(reports=result, connected=False, attribution='unlinked_platform_observations')

    @app.post(endpoint)
    def growthrova_measurement_save(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {'id', 'mutationId', 'expectedRevision', 'data'}:
            raise MarketingDraftError('A report and save version are required.')
        report_id, mutation = _id(payload['id']), _id(payload['mutationId'])
        base = payload['expectedRevision']
        if type(base) is not int or not 0 <= base < 100:
            raise MarketingDraftError('Invalid report revision or history limit reached.')
        # Fingerprint the exact request before time-dependent validation: a committed
        # save must remain recoverable after timezone rules or date boundaries change.
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            result = write_report(con, scope, ident, payload, fingerprint)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(**result)

    from business_growthrova_measurement_refresh import register_refresh_routes
    return register_refresh_routes(app, repo, endpoint, checked, config=config)
