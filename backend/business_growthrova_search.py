"""Opt-in Search Console reads on the existing private campaign repository.

No connection, credentials or worker host is installed. The trusted authoriser
must freshly verify the dedicated property grant and read/cost authority without
browser identity. Each immutable result is a snapshot, never additive analytics.
"""
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
import re
import time
import uuid
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id
from business_marketing_offline import OfflineDocumentAccessError
from business_growthrova_measurement_refresh import encoded
from business_growthrova_measurement_adapters import ReportingAdapter


def period(first, last, now):
    try:
        start, end = date.fromisoformat(first), date.fromisoformat(last)
        if (start.isoformat() != first or end.isoformat() != last or
                not 0 <= (end-start).days < 31 or
                end >= datetime.fromtimestamp(now, ZoneInfo('America/Los_Angeles')).date()):
            raise ValueError()
    except (ValueError, TypeError):
        raise MarketingDraftError('Choose 1–31 completed Search Console dates.') from None


def property_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 512 or any(ord(c) <= 32 for c in value):
        return False
    if value.startswith('sc-domain:'):
        return re.fullmatch(r'sc-domain:[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', value) is not None
    try:
        url = urlsplit(value)
        return bool(url.scheme in ('http', 'https') and url.hostname and not url.username
                    and not url.password and not url.query and not url.fragment and url.port in (None, 80, 443))
    except ValueError:
        return False


@dataclass(frozen=True)
class SearchBinding:
    owner_id: str
    organisation_id: str
    property_id: str
    label: str
    version: str
    access_token: str = field(default='', repr=False)
    enabled: bool = False
    verified: bool = False


class SearchConsoleAdapter(ReportingAdapter):
    platform = 'search_console'

    @staticmethod
    def identity(binding):
        return dict(ownerId=binding.owner_id, organisationId=binding.organisation_id,
                    propertyId=binding.property_id, label=binding.label, connectionVersion=binding.version)

    def binding(self, owner, business):
        value = self.resolve(owner, business, self.platform)
        if (not isinstance(value, SearchBinding) or value.enabled is not True or value.verified is not True
                or (value.owner_id, value.organisation_id) != (owner, business)
                or not property_id(value.property_id) or not value.access_token):
            return None
        return value

    def read(self, snap):
        binding = self.checked_binding(snap)
        period(snap['from'], snap['to'], time.time())
        detailed = snap.get('mode') == 'page_query'
        value = self.wire('post', 'https://www.googleapis.com/webmasters/v3/sites/' +
            quote(binding.property_id, safe='') + '/searchAnalytics/query', binding,
            json=dict(startDate=snap['from'], endDate=snap['to'], dimensions=['page','query'] if detailed else ['date'],
                      type='web', aggregationType='auto' if detailed else 'byProperty',
                      dataState='final', rowLimit=50 if detailed else 32))
        if (not isinstance(value, dict) or value.get('responseAggregationType') != ('byPage' if detailed else 'byProperty')
                or not isinstance(value.get('rows', []), list) or len(value.get('rows', [])) > (50 if detailed else 31)):
            raise ValueError('Unconfirmed search response')
        rows = []
        for row in value.get('rows', []):
            if not isinstance(row, dict) or not isinstance(row.get('keys'), list) or len(row['keys']) != (2 if detailed else 1):
                raise ValueError('Invalid date grouping')
            keys = dict(page=row['keys'][0], query=row['keys'][1]) if detailed else dict(date=row['keys'][0])
            rows.append(dict(**keys, clicks=row['clicks'], impressions=row['impressions']))
        self.checked_binding(snap)
        return rows


def observation_rows(rows, snap):
    detailed = snap.get('mode') == 'page_query'
    if not isinstance(rows, list) or len(rows) > (50 if detailed else 31):
        raise ValueError('Invalid observations')
    result, seen = [], set()
    for row in rows:
        fields = {'page','query','clicks','impressions'} if detailed else {'date','clicks','impressions'}
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError('Invalid observation fields')
        if detailed:
            page, query = row['page'], row['query']
            if (not evidence_page(page)
                    or not isinstance(query, str) or not query.strip() or len(query) > 512
                    or any(ord(c) < 32 for c in query) or (page, query) in seen):
                raise ValueError('Invalid page/query grouping')
            seen.add((page, query))
            item = dict(page=page, query=query)
        else:
            day = row['date']
            if (not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
                    or not snap['from'] <= day <= snap['to'] or day in seen):
                raise ValueError('Invalid observation date')
            seen.add(day)
            item = dict(date=day)
        for key in ('clicks', 'impressions'):
            count = row[key]
            if type(count) not in (int, float) or not 0 <= count <= 10**12 or int(count) != count:
                raise ValueError('Invalid observation count')
            item[key] = int(count)
        if item['clicks'] > item['impressions']:
            raise ValueError('Inconsistent search counts')
        result.append(item)
    return result if detailed else sorted(result, key=lambda r: r['date'])


def evidence_page(value):
    try:
        url = urlsplit(value)
        return (isinstance(value, str) and len(value) <= 512 and
                not any(ord(c) <= 32 for c in value) and url.scheme in ('http','https')
                and bool(url.hostname) and not url.username and not url.password and not url.fragment
                and url.port in (None,80,443))
    except (TypeError, ValueError):
        return False


def search_reference(read_id, snap, result, index):
    row = result['rows'][index]
    # This is an API observation, never a quotation from the destination page.
    quote_text = (f"Search Console page/query observation; snapshot {read_id}; "
        f"property {snap['account']['propertyId']}; connection {snap['account']['connectionVersion']}; "
        f"{snap['from']} to {snap['to']} (America/Los_Angeles); observed {result['observedAt']}. "
        f"Page: {row['page']}; query: {row['query']}; clicks: {row['clicks']}; impressions: {row['impressions']}. "
        "Top returned pairs only; missing/suppressed data unknown. Not a ranking, business fact or attribution.")
    return dict(kind='search', readId=read_id, index=index, quote=quote_text, sourceUrl=row['page'])


@dataclass(frozen=True)
class SearchConfig:
    adapter: object = field(default=None, repr=False)
    authorised: object = field(default=None, repr=False)
    enabled: bool = False
    clock: object = time.time


class SearchObservations:
    LEASE = 90

    def __init__(self, repo, config):
        self.repo, self.config = repo, config or SearchConfig()
        with closing(repo._connect()) as con:
            con.executescript('''CREATE TABLE IF NOT EXISTS growthrova_search_reads(
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
                document_id TEXT NOT NULL, fingerprint TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                state TEXT NOT NULL, claim TEXT, lease REAL NOT NULL, result_json TEXT,
                created REAL NOT NULL, updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS growthrova_search_scope
                ON growthrova_search_reads(owner_id,organisation_id,document_id);''')

    def account(self, scope):
        try:
            if self.config.enabled is not True:
                return None
            value = self.config.adapter.account(*scope)
            if (not isinstance(value, dict) or set(value) != {'ownerId','organisationId','propertyId','label','connectionVersion'}
                    or (value['ownerId'], value['organisationId']) != scope
                    or any(not isinstance(v, str) or not v.strip() or len(v) > 512
                           or any(ord(c) < 32 for c in v) for v in value.values())
                    or not property_id(value['propertyId'])):
                return None
            return deepcopy(value)
        except Exception:
            return None

    def authorised(self, snap):
        try:
            scope = (snap['ownerId'], snap['organisationId'])
            return (self.account(scope) == snap['account'] and callable(self.config.authorised)
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
        con.execute("UPDATE growthrova_search_reads SET state='failed',result_json=?,updated=? "
                    "WHERE state='reading' AND lease<=?", (encoded(dict(message=
                    'Read confirmation expired. Request a new read; this request will not run again.')),
                    self.config.clock(), self.config.clock()))

    def run_one(self):
        token = uuid.uuid4().hex
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            self.expire(con)
            row = con.execute("SELECT * FROM growthrova_search_reads WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                con.commit()
                return False
            row = dict(row)
            con.execute("UPDATE growthrova_search_reads SET state='reading',claim=?,lease=?,updated=? WHERE id=?",
                        (token, self.config.clock()+self.LEASE, self.config.clock(), row['id']))
            con.commit()
        snap = json.loads(row['snapshot_json'])
        data = None
        try:
            with closing(self.repo._connect()) as con:
                live = con.execute('SELECT * FROM growthrova_search_reads WHERE id=?', (row['id'],)).fetchone()
                valid = (live['state'] == 'reading' and live['claim'] == token and
                         live['lease'] > self.config.clock() and self.current(con, row) and self.authorised(snap))
            if valid:
                data = observation_rows(self.config.adapter.read(deepcopy(snap)), snap)
        except Exception:
            data = None  # Do not expose provider diagnostics, credentials or bodies.
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            live = con.execute('SELECT * FROM growthrova_search_reads WHERE id=?', (row['id'],)).fetchone()
            if live['state'] != 'reading' or live['claim'] != token or live['lease'] <= self.config.clock():
                return True
            valid = data is not None and self.current(con, row) and self.authorised(snap)
            result = (dict(message='Search Console observations saved.' if data else 'No daily observations returned. Missing dates remain unmeasured.',
                           rows=data, observedAt=self.config.clock(), source='google_search_console',
                           timezone='America/Los_Angeles', searchType='web',
                           aggregation='byPage' if snap.get('mode') == 'page_query' else 'byProperty', dataState='final')
                      if valid else dict(message='Access changed or the read could not be confirmed. Request a new read after reviewing the connection.'))
            if valid and snap.get('mode') == 'page_query':
                result['references'] = [search_reference(row['id'], snap, result, i) for i in range(len(data))]
                result['message'] = 'Returned page/query evidence saved. Top rows only; missing and suppressed data remain unknown.'
            # Authorisation may be slow: check the lease again immediately before persistence.
            if live['lease'] <= self.config.clock():
                return True
            con.execute('UPDATE growthrova_search_reads SET state=?,result_json=?,updated=? WHERE id=?',
                        ('completed' if valid else 'failed', encoded(result), self.config.clock(), row['id']))
            con.commit()
        return True


def register_search_routes(app, repo, root, *, config=None, revalidate=None):
    service = SearchObservations(repo, config)
    app.extensions['growthrova_search_observations'] = service
    endpoint = root + '/<ident>/search-observations'

    def checked(con, business, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(business) != scope or not repo._owned(con, ident, scope):
            raise OfflineDocumentAccessError('Campaign access changed')

    @app.get(endpoint)
    def growthrova_search_status(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        account = service.account(scope)
        read_authorised = bool(account and service.authorised(dict(ownerId=scope[0], organisationId=scope[1], account=account)))
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            service.expire(con)
            rows = con.execute('SELECT * FROM growthrova_search_reads WHERE owner_id=? AND organisation_id=? '
                'AND document_id=? ORDER BY created DESC', (*scope, ident)).fetchall()
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(account=account, readAuthorised=read_authorised,
                       reads=[service.public(row) for row in rows], workerManagedExternally=True)

    @app.post(endpoint)
    def growthrova_search_queue(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) not in ({'id','account','from','to'}, {'id','account','from','to','mode'}):
            raise MarketingDraftError('Review the exact Search Console property and dates.')
        if 'mode' in payload and payload['mode'] not in ('daily','page_query'):
            raise MarketingDraftError('Choose daily totals or page/query evidence.')
        job_id = _id(payload['id'])
        fingerprint = hashlib.sha256(encoded(payload).encode()).hexdigest()
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            old = con.execute('SELECT * FROM growthrova_search_reads WHERE id=?', (job_id,)).fetchone()
            if old:
                if (old['owner_id'],old['organisation_id'],old['document_id']) != (*scope, ident):
                    raise OfflineDocumentAccessError('Read access denied')
                if old['fingerprint'] != fingerprint:
                    raise MarketingDraftError('This read identity is already used. Recover the original request.', 'revision_conflict', 409)
                result = service.public(old)
            else:
                service.expire(con)
                period(payload['from'], payload['to'], service.config.clock())
                snap = dict(ownerId=scope[0], organisationId=scope[1], account=payload['account'], **{k:payload[k] for k in ('from','to')})
                if 'mode' in payload:
                    snap['mode'] = payload['mode']
                if not service.authorised(snap):
                    raise MarketingDraftError('Connect and authorise a dedicated Search Console property first.', 'account_unavailable', 409)
                count = con.execute('SELECT COUNT(*) FROM growthrova_search_reads WHERE owner_id=? AND organisation_id=?', scope).fetchone()[0]
                if count >= 100:
                    raise MarketingDraftError('This business has reached its 100-read history limit.', 'storage_limit', 409)
                active = con.execute("SELECT 1 FROM growthrova_search_reads WHERE owner_id=? AND organisation_id=? AND state IN ('queued','reading')", scope).fetchone()
                if active:
                    raise MarketingDraftError('Check the pending search read before requesting another.', 'read_pending', 409)
                now = service.config.clock()
                con.execute('INSERT INTO growthrova_search_reads VALUES(?,?,?,?,?,?,?,NULL,0,NULL,?,?)',
                    (job_id,*scope,ident,fingerprint,encoded(snap),'queued',now,now))
                result = service.public(con.execute('SELECT * FROM growthrova_search_reads WHERE id=?', (job_id,)).fetchone())
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(**result, replayed=bool(old))

    @app.post(endpoint + '/<read_id>/cancel')
    def growthrova_search_cancel(organisation_id, ident, read_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            row = con.execute('SELECT * FROM growthrova_search_reads WHERE id=? AND owner_id=? AND organisation_id=? AND document_id=?',
                              (_id(read_id), *scope, ident)).fetchone()
            if not row:
                raise OfflineDocumentAccessError('Read access denied')
            if row['state'] in ('queued', 'reading'):
                con.execute("UPDATE growthrova_search_reads SET state='cancelled',updated=? WHERE id=?", (service.config.clock(), read_id))
            result = service.public(con.execute('SELECT * FROM growthrova_search_reads WHERE id=?', (read_id,)).fetchone())
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(**result)

    return service
