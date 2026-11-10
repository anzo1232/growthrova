"""Cumulative observations for exact live publication receipts.

Manual and explicitly connected reads share one revisioned writer.
No account authority or engagement is inferred from publication.
Corrections replace the current snapshot; mutation receipts remain immutable.
"""
from contextlib import closing
from datetime import datetime, timezone, timedelta
import hashlib
import json
import time

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id, _text
from business_marketing_offline import OfflineDocumentAccessError

METRICS = ('impressions', 'likes', 'comments', 'shares', 'linkClicks')


def normalise(value):
    if not isinstance(value, dict) or set(value) != {'asOf', 'sourceReference', *METRICS}:
        raise MarketingDraftError('Include observation time, source reference and supported metrics.')
    stamp = _text(value['asOf'], 'observation time', 20, True)
    try:
        parsed = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        if parsed.strftime('%Y-%m-%dT%H:%M:%SZ') != stamp or parsed.timestamp() > time.time():
            raise ValueError()
    except ValueError:
        raise MarketingDraftError('Use a valid UTC observation time that is not in the future.') from None
    result = dict(asOf=stamp, sourceReference=_text(value['sourceReference'], 'source reference', 512, True).strip())
    if not result['sourceReference']:
        raise MarketingDraftError('Describe the platform report or export used.')
    for key in METRICS:
        val = value[key]
        if val is not None and (type(val) is not int or not 0 <= val <= 10**12):
            raise MarketingDraftError('Use non-negative whole counts, or leave unavailable metrics blank.')
        result[key] = val
    if all(result[key] is None for key in METRICS):
        raise MarketingDraftError('Record at least one observed metric. Blank means unknown, not zero.')
    return result


def binding(row):
    receipt = json.loads(row['receipt_json'] or 'null')
    if (row['mode'] != 'live' or row['state'] != 'published' or not isinstance(receipt, dict)
            or receipt.get('outcome') != 'published' or not isinstance(receipt.get('id'), str)
            or not receipt['id'].strip()):
        return None
    snapshot = json.loads(row['snapshot_json'])
    if (not isinstance(snapshot, dict) or not snapshot.get('artworkSha256')
            or type(snapshot.get('revision')) is not int):
        return None
    return dict(jobId=row['job_id'], draftId=row['draft_id'], channel=row['channel'],
                approvalHash=row['approval_hash'], artworkSha256=snapshot['artworkSha256'],
                campaignRevision=snapshot['revision'], publicationReceipt=receipt['id'])


def check_capacity(con, scope, job_id, current):
    count = con.execute('SELECT COUNT(*) FROM growthrova_social_observation_receipts WHERE job_id=?', (job_id,)).fetchone()[0]
    if count >= 100:
        raise MarketingDraftError('This publication has reached its 100-observation revision limit.', 'storage_limit', 409)
    if not current:
        total = con.execute('SELECT COUNT(*) FROM growthrova_social_observations r JOIN growthrova_social_jobs j '
                            'ON j.job_id=r.job_id WHERE j.owner_id=? AND j.organisation_id=?', scope).fetchone()[0]
        if total >= 500:
            raise MarketingDraftError('This business has reached its 500-publication observation limit.', 'storage_limit', 409)


def persist_observation(con, scope, job_id, exact, expected_revision, mutation_id, fingerprint, data, *, provider_read=None):
    """Inside the caller's write transaction; caller rechecks access before commit."""
    receipt = con.execute('SELECT * FROM growthrova_social_observation_receipts WHERE job_id=? AND mutation_id=?',
                          (job_id, mutation_id)).fetchone()
    current = con.execute('SELECT * FROM growthrova_social_observations WHERE job_id=?', (job_id,)).fetchone()
    if receipt:
        if receipt['fingerprint'] != fingerprint:
            raise MarketingDraftError('This recovery request changed. Reopen the observation.', 'revision_conflict', 409)
        result = json.loads(receipt['result_json'])
        if result['binding'] != exact:
            raise MarketingDraftError('The publication identity changed. Reopen it.', 'revision_conflict', 409)
        result['replayed'] = True
        result['currentRevision'] = current['revision']
    else:
        if current and json.loads(current['binding_json']) != exact:
            raise MarketingDraftError('The publication identity changed. Keep the original observation for review.', 'revision_conflict', 409)
        if (current['revision'] if current else 0) != expected_revision:
            raise MarketingDraftError('Another editor saved this observation. Reopen it.', 'revision_conflict', 409)
        check_capacity(con, scope, job_id, current)
        revision, now = expected_revision + 1, time.time()
        encoded = json.dumps(dict(data, **({'_providerRead': provider_read} if provider_read else {})), sort_keys=True)
        con.execute('INSERT INTO growthrova_social_observations VALUES(?,?,?,?,?) '
                    'ON CONFLICT(job_id) DO UPDATE SET revision=excluded.revision,data_json=excluded.data_json,binding_json=excluded.binding_json,updated=excluded.updated',
                    (job_id, revision, encoded, json.dumps(exact, sort_keys=True), now))
        result = dict(binding=exact, revision=revision, currentRevision=revision, data=data,
                      savedAt=now, provenance='provider_read' if provider_read else 'owner_recorded', replayed=False)
        if provider_read:
            result['providerRead'] = provider_read
        con.execute('INSERT INTO growthrova_social_observation_receipts VALUES(?,?,?,?)',
                    (job_id, mutation_id, fingerprint, json.dumps(result, sort_keys=True)))
    return result


def saved(row):
    if not row:
        return None
    data = json.loads(row['data_json'])
    provider_read = data.pop('_providerRead', None)
    result = dict(revision=row['revision'], data=data, binding=json.loads(row['binding_json']), savedAt=row['updated'],
                  provenance='provider_read' if provider_read else 'owner_recorded')
    if provider_read:
        result['providerRead'] = provider_read
    return result


def social_observation_overview(con, scope, period, now):
    through = datetime.fromtimestamp(now, timezone.utc).date()
    start = None if period == 'all' else (through - timedelta(days=int(period)-1)).isoformat()
    items = []
    rows = con.execute('''SELECT j.*,r.revision AS observation_revision,r.data_json,r.binding_json,r.updated
        FROM growthrova_social_observations r JOIN growthrova_social_jobs j ON j.job_id=r.job_id
        JOIN offline_document_owners o ON o.draft_id=j.document_id
        JOIN marketing_drafts d ON d.id=j.document_id
        WHERE j.owner_id=? AND j.organisation_id=?
        AND o.owner_id=j.owner_id AND o.organisation_id=j.organisation_id
        ORDER BY r.updated DESC,j.job_id''', scope)
    for row in rows:
        exact = binding(row)
        data = json.loads(row['data_json'])
        day = data['asOf'][:10]
        if exact and exact == json.loads(row['binding_json']) and (not start or day >= start) and day <= through.isoformat():
            # Source notes/receipt/account/caption text never enters the aggregate export.
            items.append(dict(campaignId=row['document_id'],
                **{k: v for k, v in exact.items() if k != 'publicationReceipt'},
                revision=row['observation_revision'], savedAt=row['updated'],
                asOf=data['asOf'], metrics={key: data[key] for key in METRICS}, provenance='provider_read' if data.get('_providerRead') else 'owner_recorded'))
    return dict(fromDate=start, throughDate=through.isoformat(), items=items)


def register_social_observation_routes(app, repo, root, *, revalidate=None):
    with closing(repo._connect()) as con:
        con.executescript('''CREATE TABLE IF NOT EXISTS growthrova_social_observations(
            job_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, data_json TEXT NOT NULL, binding_json TEXT NOT NULL, updated REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS growthrova_social_observation_receipts(
            job_id TEXT NOT NULL, mutation_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            result_json TEXT NOT NULL, PRIMARY KEY(job_id,mutation_id));''')
    endpoint = root + '/<ident>/social-observations'

    def checked(con, org, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(org) != scope or not repo._owned(con, ident, scope):
            raise OfflineDocumentAccessError('Campaign access changed')

    @app.get(endpoint)
    def social_observations_list(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            rows = con.execute('SELECT * FROM growthrova_social_jobs WHERE document_id=? AND owner_id=? '
                               'AND organisation_id=? ORDER BY approved_at DESC,job_id', (ident, *scope)).fetchall()
            items = []
            for row in rows:
                exact = binding(row)
                if exact:
                    current = con.execute('SELECT * FROM growthrova_social_observations WHERE job_id=?',
                                          (row['job_id'],)).fetchone()
                    items.append(dict(**exact, observation=saved(current) if current and json.loads(current['binding_json']) == exact else None))
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        reader = app.extensions.get('growthrova_social_analytics')
        return jsonify(items=items, readerConfigured=bool(reader and reader.available))

    @app.post(endpoint + '/<job_id>')
    def social_observation_save(organisation_id, ident, job_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        _id(job_id)
        payload = request.get_json(silent=True)
        if (not isinstance(payload, dict) or set(payload) != {'expectedRevision', 'mutationId', 'data'}
                or type(payload['expectedRevision']) is not int or payload['expectedRevision'] < 0):
            raise MarketingDraftError('Save an exact observation revision and mutation identity.')
        _id(payload['mutationId'])
        data = normalise(payload['data'])
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            job = con.execute('SELECT * FROM growthrova_social_jobs WHERE job_id=? AND document_id=? '
                              'AND owner_id=? AND organisation_id=?', (job_id, ident, *scope)).fetchone()
            if not job:
                raise OfflineDocumentAccessError('Publication access denied')
            exact = binding(job)
            if not exact:
                raise MarketingDraftError('A confirmed live publication receipt is required.', 'publication_required', 409)
            if datetime.strptime(data['asOf'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp() < int(job['approved_at']):
                raise MarketingDraftError('Observation time must follow approval of this publication.')
            result = persist_observation(con, scope, job_id, exact, payload['expectedRevision'],
                                         payload['mutationId'], fingerprint, data)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(result)
