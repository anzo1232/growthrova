"""Explicit, read-only social analytics orchestration; no native transport installed.

The operator adapter's connection(snapshot) is local-only and returns the public
provider/version/channel/accountId identity of a dedicated, currently verified
read connection. read(snapshot, connection) returns exactly {publication, data},
where publication is snapshot['publication'] and data uses the observation schema.
It must fetch only that exact post/account, return cumulative supported counts
(unknown stays None), and bound response size/time, redirects and remote retries.
The separate authorised(snapshot, connection) callback must check current grants,
tenant/account association and commercial read authority; rotate version on any
credential/grant change. Neither callback may borrow ambient credentials.

No vendor capability, credential installation, worker or runtime enablement is
implied. Read intent survives restart. Recovery never dispatches a second read.
An unconfirmed read may be replaced by a new explicit read after the 120s hold;
its late result cannot overwrite a later revision. This is not a publishing path.
"""
from contextlib import closing
from dataclasses import dataclass, field
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import time

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id, _text
from business_marketing_offline import OfflineDocumentAccessError
from business_growthrova_social_observations import binding, check_capacity, normalise, persist_observation


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class SocialAnalyticsConfig:
    enabled: bool = False
    adapter: object = field(default=None, repr=False)
    authorised: object = field(default=None, repr=False)


class SocialAnalytics:
    def __init__(self, repo, config=None):
        self.repo, self.config = repo, config or SocialAnalyticsConfig()
        with closing(repo._connect()) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS growthrova_social_analytics_reads(
                job_id TEXT NOT NULL, mutation_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                intent_json TEXT NOT NULL, state TEXT NOT NULL, result_json TEXT,
                started REAL NOT NULL, PRIMARY KEY(job_id,mutation_id))''')
            con.commit()

    @property
    def available(self):
        return (self.config.enabled is True and callable(self.config.authorised)
                and all(callable(getattr(self.config.adapter, key, None)) for key in ('connection', 'read')))

    def connection(self, snapshot):
        try:
            if not self.available:
                return None
            value = self.config.adapter.connection(deepcopy(snapshot))
            if not isinstance(value, dict) or set(value) != {'provider', 'version', 'channel', 'accountId'}:
                return None
            value = {key: _text(val, key, 160, True).strip() for key, val in value.items()}
            if (not all(value.values()) or value['channel'] != snapshot['channel']
                    or value['accountId'] != snapshot['destination']['id']
                    or self.config.authorised(deepcopy(snapshot), deepcopy(value)) is not True):
                return None
            return value
        except Exception:
            # No callback/provider errors or credentials in responses/logs.
            return None


def register_social_analytics_routes(app, repo, root, *, config=None, revalidate=None):
    reader = SocialAnalytics(repo, config)
    app.extensions['growthrova_social_analytics'] = reader

    def checked(con, org, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(org) != scope or not repo._owned(con, ident, scope):
            raise OfflineDocumentAccessError('Campaign access changed')

    def publication(con, ident, job_id, scope):
        row = con.execute('SELECT * FROM growthrova_social_jobs WHERE job_id=? AND document_id=? '
                          'AND owner_id=? AND organisation_id=?', (job_id, ident, *scope)).fetchone()
        if not row:
            raise OfflineDocumentAccessError('Publication access denied')
        exact = binding(row)
        if not exact:
            raise MarketingDraftError('A confirmed live publication is required.', 'publication_required', 409)
        snapshot = json.loads(row['snapshot_json'])
        if snapshot.get('channel') != row['channel'] or not isinstance(snapshot.get('destination'), dict):
            raise MarketingDraftError('Reopen the exact published account before reading.', 'publication_required', 409)
        return row, dict(snapshot, ownerId=scope[0], organisationId=scope[1], publication=exact)

    @app.post(root + '/<ident>/social-observations/<job_id>/read')
    def social_analytics_read(organisation_id, ident, job_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        _id(job_id)
        payload = request.get_json(silent=True)
        if (not isinstance(payload, dict) or set(payload) != {'expectedRevision', 'mutationId'}
                or type(payload['expectedRevision']) is not int or payload['expectedRevision'] < 0):
            raise MarketingDraftError('Include the saved observation version and read request identity.')
        _id(payload['mutationId'])
        fingerprint = digest(payload)
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            job, snapshot = publication(con, ident, job_id, scope)
            prior = con.execute('SELECT * FROM growthrova_social_analytics_reads WHERE job_id=? AND mutation_id=?',
                                (job_id, payload['mutationId'])).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint or json.loads(prior['intent_json'])['snapshotHash'] != digest(snapshot):
                    raise MarketingDraftError('This read request or publication changed. Reopen saved observations.', 'revision_conflict', 409)
                error = checked(con, organisation_id, ident, scope)
                if error is not None:
                    return error
                result = json.loads(prior['result_json']) if prior['result_json'] else dict(state='unconfirmed')
                result['replayed'] = True
                if result['state'] == 'saved':
                    current = con.execute('SELECT revision FROM growthrova_social_observations WHERE job_id=?', (job_id,)).fetchone()
                    result['observation']['currentRevision'] = current['revision']
                return jsonify(result)
            if not reader.available:
                raise MarketingDraftError('Platform reading is not connected. Record actual report counts manually.', 'reader_unavailable', 409)
            connection = reader.connection(snapshot)
            if connection is None:
                raise MarketingDraftError('Read access for this published account could not be confirmed. Reconnect or record counts manually.', 'reader_unavailable', 409)
            current = con.execute('SELECT * FROM growthrova_social_observations WHERE job_id=?', (job_id,)).fetchone()
            if ((current['revision'] if current else 0) != payload['expectedRevision']
                    or current and json.loads(current['binding_json']) != snapshot['publication']):
                raise MarketingDraftError('Saved observations changed. Reopen before reading.', 'revision_conflict', 409)
            check_capacity(con, scope, job_id, current)
            recent = con.execute('SELECT 1 FROM growthrova_social_analytics_reads WHERE job_id=? AND started>? LIMIT 1',
                                 (job_id, time.time()-120)).fetchone()
            count = con.execute('SELECT COUNT(*) FROM growthrova_social_analytics_reads WHERE job_id=?', (job_id,)).fetchone()[0]
            total = con.execute('SELECT COUNT(*) FROM growthrova_social_analytics_reads r JOIN growthrova_social_jobs j '
                                'ON j.job_id=r.job_id WHERE j.owner_id=? AND j.organisation_id=?', scope).fetchone()[0]
            if recent or count >= 100 or total >= 5000:
                raise MarketingDraftError('Read limit reached. Wait at least two minutes between reads; maximum 100 per post and 5,000 per business.', 'read_limit', 429)
            intent = dict(snapshotHash=digest(snapshot), connection=connection)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.execute('INSERT INTO growthrova_social_analytics_reads VALUES(?,?,?,?,?,?,?)',
                        (job_id, payload['mutationId'], fingerprint, json.dumps(intent, sort_keys=True), 'reading', None, time.time()))
            con.commit()

        # Intent is durable; no database transaction is held across the slow read.
        data, failure = None, 'read_unconfirmed'
        try:
            if reader.connection(snapshot) != connection:
                raise ValueError('Connection changed')
            response = reader.config.adapter.read(deepcopy(snapshot), deepcopy(connection))
            if (not isinstance(response, dict) or set(response) != {'publication', 'data'}
                    or response['publication'] != snapshot['publication']):
                raise ValueError('Publication mismatch')
            data = normalise(response['data'])
            if datetime.strptime(data['asOf'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp() < int(job['approved_at']):
                raise ValueError('Observation predates approval')
            if reader.connection(snapshot) != connection:
                data, failure = None, 'access_changed'
        except Exception:
            data = None

        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error  # durable unconfirmed intent is retained, never redispatched
            _, current_snapshot = publication(con, ident, job_id, scope)
            result = dict(state='unconfirmed', reason=failure, replayed=False)
            if digest(current_snapshot) != intent['snapshotHash'] or reader.connection(snapshot) != connection:
                data, result['reason'] = None, 'access_changed'
            if data is not None:
                current = con.execute('SELECT data_json FROM growthrova_social_observations WHERE job_id=?', (job_id,)).fetchone()
                if current and data['asOf'] < json.loads(current['data_json'])['asOf']:
                    data = None
                    result = dict(state='not_saved', reason='older_observation', replayed=False)
            if data is not None:
                try:
                    # Distinct namespace prevents a manual save reusing this request ID.
                    mutation_id = digest(['social-analytics', payload['mutationId']])[:32]
                    observation = persist_observation(con, scope, job_id, snapshot['publication'], payload['expectedRevision'],
                        mutation_id, digest([payload, intent]), data, provider_read=connection)
                    result = dict(state='saved', observation=observation, replayed=False)
                except MarketingDraftError:
                    result = dict(state='not_saved', reason='saved_observation_changed_or_limit', replayed=False)
            # Final access check covers callbacks and shared writer work too.
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.execute('UPDATE growthrova_social_analytics_reads SET state=?,result_json=? WHERE job_id=? AND mutation_id=?',
                        (result['state'], json.dumps(result, sort_keys=True), job_id, payload['mutationId']))
            con.commit()
        return jsonify(result)
