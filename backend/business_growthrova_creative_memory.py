"""Brand-scoped visual references and observed creative results.

References reuse the private original library. Selection explicitly authorises
provider processing. Results describe exact adverts and reporting windows;
observational associations are never causal claims or automatic spending rules.
"""
import base64
from contextlib import closing
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import re
import time

from flask import jsonify, request
from PIL import Image, ImageOps
import business_asset_catalog as catalog
from business_marketing_drafts import MarketingDraftError, _id
from business_marketing_offline import OfflineDocumentAccessError


PIPELINE_VERSION = 'growthrova-creative-20261109-v8'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def initialise(con):
    catalog.initialise_originals(con)
    con.executescript('''
      CREATE TABLE IF NOT EXISTS growthrova_creative_references(
        owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, document_id TEXT NOT NULL,
        version INTEGER NOT NULL, data_json TEXT NOT NULL,
        PRIMARY KEY(owner_id,organisation_id,document_id));
      CREATE TABLE IF NOT EXISTS growthrova_creative_results(
        owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, document_id TEXT NOT NULL,
        report_id TEXT NOT NULL, version INTEGER NOT NULL, data_json TEXT NOT NULL,
        updated REAL NOT NULL, PRIMARY KEY(owner_id,organisation_id,report_id));
      CREATE TABLE IF NOT EXISTS growthrova_creative_result_history(
        owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, report_id TEXT NOT NULL,
        version INTEGER NOT NULL, data_json TEXT NOT NULL, recorded REAL NOT NULL,
        PRIMARY KEY(owner_id,organisation_id,report_id,version));
    ''')


def references(con, scope, ident):
    row = con.execute('SELECT version,data_json FROM growthrova_creative_references '
                      'WHERE owner_id=? AND organisation_id=? AND document_id=?', (*scope, ident)).fetchone()
    return dict(version=row['version'], items=json.loads(row['data_json'])) if row else dict(version=0, items=[])


def checked_reference(con, scope, value):
    if (not isinstance(value, dict) or set(value) != {'assetId', 'role', 'direction', 'providerConsent'}
            or value['role'] not in ('brand_style', 'product', 'approved_ad')
            or value['providerConsent'] is not True
            or not isinstance(value['direction'], str) or not 10 <= len(value['direction'].strip()) <= 300):
        raise MarketingDraftError('Choose a reference role, describe what to preserve and allow image-provider processing.')
    try:
        item, content = catalog.original(con, scope[1], scope[0], value['assetId'])
    except (catalog.AssetError, TypeError):
        raise MarketingDraftError('Choose an image from this business’s original library.') from None
    if (item.get('permissionWithdrawn') or item.get('consentStatus') != 'owner_asserted'
            or item['mimeType'] not in ('image/png', 'image/jpeg', 'image/webp')):
        raise MarketingDraftError('This reference is unavailable or its image permissions need attention.')
    return dict(value, direction=value['direction'].strip(), sha256=item['sourceSha256'],
                name=item['originalName']), content


def reference_inputs(con, scope, ident):
    """Recheck permission/integrity at dispatch, then bound provider image bytes."""
    saved = references(con, scope, ident)
    result = []
    for value in saved['items']:
        selected = {k: value[k] for k in ('assetId', 'role', 'direction', 'providerConsent')}
        checked, content = checked_reference(con, scope, selected)
        if checked['sha256'] != value['sha256']:
            raise MarketingDraftError('The selected reference changed. Review it before generating.', 'reference_changed', 409)
        with Image.open(io.BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((1024, 1024))
            output = io.BytesIO()
            image.save(output, 'JPEG', quality=90)
        result.append(dict(metadata=value, mimeType='image/jpeg',
                           data=base64.b64encode(output.getvalue()).decode()))
    return result


def normalise_result(value):
    fields = {'operationId', 'platform', 'accountId', 'adId', 'fromDate', 'throughDate',
              'currency', 'impressions', 'clicks', 'leads', 'spend', 'revenue',
              'attributionWindow', 'sourceReference'}
    if not isinstance(value, dict) or set(value) != fields:
        raise MarketingDraftError('Include the exact advert, reporting window, counts, spend, revenue and source.')
    _id(value['operationId'])
    result = dict(value)
    if result['platform'] not in ('meta', 'google', 'instagram', 'facebook', 'linkedin', 'tiktok', 'x'):
        raise MarketingDraftError('Choose a supported advertising or social platform.')
    for key, limit in [('accountId', 100), ('adId', 100), ('sourceReference', 500), ('attributionWindow', 120)]:
        val = result[key]
        if not isinstance(val, str) or not 1 <= len(val.strip()) <= limit or any(ord(c) < 32 for c in val):
            raise MarketingDraftError('Include readable account, advert, attribution and report-source details.')
        result[key] = val.strip()
    try:
        start, end = date.fromisoformat(result['fromDate']), date.fromisoformat(result['throughDate'])
        if (start.isoformat() != result['fromDate'] or end.isoformat() != result['throughDate']
                or start > end or end > date.today() or (end-start).days > 366):
            raise ValueError()
    except (ValueError, TypeError):
        raise MarketingDraftError('Use a valid reporting window of at most one year, ending no later than today.') from None
    if not isinstance(result['currency'], str) or not re.fullmatch('[A-Z]{3}', result['currency']):
        raise MarketingDraftError('Use a three-letter reporting currency.')
    for key in ('impressions', 'clicks', 'leads'):
        val = result[key]
        if val is not None and (type(val) is not int or not 0 <= val <= 10**12):
            raise MarketingDraftError('Use non-negative whole counts; leave unavailable figures blank.')
    if result['impressions'] is not None and result['clicks'] is not None and result['clicks'] > result['impressions']:
        raise MarketingDraftError('Clicks cannot exceed impressions in this report.')
    for key in ('spend', 'revenue'):
        val = result[key]
        if val is None:
            continue
        if not isinstance(val, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,9})(\.[0-9]{1,6})?', val):
            raise MarketingDraftError('Use non-negative monetary amounts without currency symbols, or leave them blank.')
        result[key] = format(Decimal(val), 'f')
    if all(result[k] is None for k in ('impressions', 'clicks', 'leads', 'spend', 'revenue')):
        raise MarketingDraftError('Record at least one observed result.')
    return result


def ratios(data):
    def ratio(a, b, multiplier=1):
        if a is None or b is None or Decimal(str(b)) == 0:
            return None
        return format((Decimal(str(a))/Decimal(str(b))*multiplier).quantize(Decimal('.0001')), 'f')
    return dict(ctr=ratio(data['clicks'], data['impressions'], 100),
                costPerLead=ratio(data['spend'], data['leads']),
                roas=ratio(data['revenue'], data['spend']))


def learning(con, scope, ident):
    """Use current report versions only. Keep platforms/windows/currencies apart."""
    rows = con.execute('SELECT r.* FROM growthrova_creative_results r JOIN offline_document_owners o '
                       'ON o.draft_id=r.document_id AND o.owner_id=r.owner_id AND o.organisation_id=r.organisation_id '
                       'WHERE r.owner_id=? AND r.organisation_id=? ORDER BY r.updated DESC LIMIT 30', scope).fetchall()
    observations = []
    for row in rows:
        data = json.loads(row['data_json'])
        candidate = con.execute('SELECT result_json FROM growthrova_image_requests WHERE document_id=? '
                                'AND operation_id=?', (row['document_id'], data['operationId'])).fetchone()
        if not candidate:
            continue
        creative = json.loads(candidate['result_json'])
        concept = creative.get('conceptBinding', {}).get('concept', {})
        observations.append(dict(reportId=row['report_id'], documentId=row['document_id'], version=row['version'], data=data,
            metrics=ratios(data), headline=creative.get('advertCopy', {}).get('headline', ''),
            buyerMotivation=concept.get('buyerMotivation', ''), visualDirection=creative.get('visualBrief', ''),
            evidenceStrength='directional' if (data['impressions'] or 0) >= 1000 and (data['clicks'] or 0) >= 20 else 'limited',
            provenance='owner_imported_ad_report'))
    connected = []
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {'growthrova_social_observations', 'growthrova_social_jobs'} <= tables:
        from business_growthrova_social_observations import binding
        rows = con.execute('SELECT j.*,r.data_json,r.binding_json FROM growthrova_social_observations r '
            'JOIN growthrova_social_jobs j ON j.job_id=r.job_id WHERE j.owner_id=? '
            'AND j.organisation_id=? ORDER BY r.updated DESC LIMIT 12', scope).fetchall()
        for row in rows:
            exact = binding(row)
            if not exact or exact != json.loads(row['binding_json']):
                continue
            data = json.loads(row['data_json'])
            snapshot = json.loads(row['snapshot_json'])
            candidate = con.execute('SELECT result_json FROM growthrova_image_requests WHERE document_id=? '
                'AND operation_id=?', (row['document_id'], snapshot.get('operationId', ''))).fetchone()
            if not candidate:
                continue
            creative = json.loads(candidate['result_json'])
            impressions, clicks = data['impressions'], data['linkClicks']
            connected.append(dict(jobId=row['job_id'], operationId=snapshot['operationId'],
                headline=creative.get('advertCopy', {}).get('headline', ''),
                buyerMotivation=creative.get('conceptBinding', {}).get('concept', {}).get('buyerMotivation', ''),
                platform=row['channel'], asOf=data['asOf'], impressions=impressions, clicks=clicks,
                ctr=ratios(dict(clicks=clicks, impressions=impressions, spend=None, leads=None, revenue=None))['ctr'],
                provenance='provider_read' if data.get('_providerRead') else 'owner_recorded_publication',
                interpretation='Cumulative post observations; revenue, spend and leads are unavailable here.'))
    return dict(observations=observations, connectedSocial=connected, guidance=[
        'Use observed creative results to propose the next test, never as proof that a design caused the outcome.',
        'Compare only matching platform, audience/objective, currency, reporting period and attribution window. Unknown metrics remain unknown.',
        'Limited samples are hypotheses. Keep exploring distinct angles; do not repeatedly clone the highest observed ratio.',
        'Never place these private results in customer artwork or turn them into factual marketing claims.',
    ])


def context(con, scope, ident):
    ref = references(con, scope, ident)
    learnt = learning(con, scope, ident)
    result = dict(references=ref, performance=learnt)
    return dict(result, fingerprint=digest(result))


def generation_context(value):
    """Small provider brief, with no account IDs, source notes or private receipts."""
    rows = value['performance']['observations'][:6]
    return dict(
        references=[dict(role=item['role'], direction=item['direction'], tag='brandref'+str(index))
                    for index, item in enumerate(value['references']['items'], 1)],
        observedResults=[dict(headline=row['headline'], buyerMotivation=row['buyerMotivation'],
            platform=row['data']['platform'], currency=row['data']['currency'],
            fromDate=row['data']['fromDate'], throughDate=row['data']['throughDate'],
            attributionWindow=row['data']['attributionWindow'],
            impressions=row['data']['impressions'], clicks=row['data']['clicks'],
            leads=row['data']['leads'], spend=row['data']['spend'], revenue=row['data']['revenue'],
            **row['metrics'], evidenceStrength=row['evidenceStrength'], provenance=row['provenance']) for row in rows],
        connectedSocial=[{k:v for k,v in row.items() if k not in ('jobId','operationId')}
                         for row in value['performance']['connectedSocial'][:4]],
        guidance=value['performance']['guidance'])


def attach_references(payload, model, inputs):
    if not inputs:
        return payload
    if model == 'gemini-3-pro-image':
        parts = payload['contents'][0]['parts']
        for index, item in enumerate(inputs, 1):
            parts.extend([{'text': 'Reference %d: %s. %s' %
                (index, item['metadata']['role'], item['metadata']['direction'])},
                {'inlineData': {'mimeType': item['mimeType'], 'data': item['data']}}])
    elif model == 'gemini_image3_pro':
        payload['referenceImages'] = [dict(uri='data:'+item['mimeType']+';base64,'+item['data'],
                                         tag='brandref'+str(index)) for index, item in enumerate(inputs, 1)]
    else:
        raise MarketingDraftError('The selected image provider cannot use the saved brand references.', 'references_unsupported', 409)
    return payload


def recipe_request(payload):
    """Keep exact prompt and reference identities without copying private image bytes into JSON."""
    result = json.loads(json.dumps(payload))
    for content in result.get('contents', []):
        for part in content.get('parts', []):
            if 'inlineData' in part:
                part['inlineData']['data'] = '[retained private reference image]'
    if 'referenceImages' in result:
        result['referenceImages'] = [dict(tag=item['tag'], uri='[retained private reference image]') for item in result['referenceImages']]
    return result


def register_routes(app, repo, root, *, revalidate=None):
    with closing(repo._connect()) as con:
        initialise(con)
        con.commit()

    def checked(con, org, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(org) != scope or not repo._owned(con, ident, scope):
            raise OfflineDocumentAccessError('Campaign access changed')

    @app.get(root+'/<ident>/creative-memory')
    def get_creative_memory(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            result = context(con, scope, ident)
            rows = con.execute('SELECT asset_id FROM business_asset_originals WHERE owner_id=? AND organisation_id=?', scope).fetchall()
            assets = [catalog.original(con, scope[1], scope[0], row['asset_id'])[0] for row in rows]
            result['availableImages'] = [dict(assetId=a['assetId'], name=a['originalName'], sha256=a['sourceSha256'])
                for a in assets if not a.get('permissionWithdrawn') and a['mimeType'].startswith('image/') and a['consentStatus']=='owner_asserted']
            if checked(con, organisation_id, ident, scope) is not None:
                raise OfflineDocumentAccessError('Campaign access changed')
        return jsonify(result)

    @app.put(root+'/<ident>/creative-memory/references')
    def put_creative_references(organisation_id, ident):
        saved = repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        value = request.get_json(silent=True)
        if (not isinstance(value, dict) or set(value) != {'expectedRevision', 'expectedVersion', 'items'}
                or value['expectedRevision'] != saved['revision'] or type(value['expectedVersion']) is not int
                or not isinstance(value['items'], list) or len(value['items']) > 3):
            raise MarketingDraftError('Save up to three brand references from the current campaign.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            old = references(con, scope, ident)
            items = [checked_reference(con, scope, item)[0] for item in value['items']]
            if len({x['assetId'] for x in items}) != len(items):
                raise MarketingDraftError('Choose each reference once.')
            if old['version'] != value['expectedVersion']:
                if old['items'] == items:
                    if checked(con, organisation_id, ident, scope) is not None:
                        raise OfflineDocumentAccessError('Campaign access changed')
                    return jsonify(old)
                raise MarketingDraftError('Brand references changed. Reload them before saving.', 'revision_conflict', 409)
            if checked(con, organisation_id, ident, scope) is not None:
                raise OfflineDocumentAccessError('Campaign access changed')
            current = con.execute('SELECT revision FROM marketing_drafts WHERE id=?', (ident,)).fetchone()
            if current['revision'] != saved['revision']:
                raise MarketingDraftError('Campaign changed. Reload it before saving.', 'revision_conflict', 409)
            con.execute('INSERT INTO growthrova_creative_references VALUES(?,?,?,?,?) '
                        'ON CONFLICT(owner_id,organisation_id,document_id) DO UPDATE SET version=excluded.version,data_json=excluded.data_json',
                        (*scope, ident, old['version']+1, json.dumps(items)))
            con.commit()
        return jsonify(version=old['version']+1, items=items)

    @app.put(root+'/<ident>/creative-memory/results/<report_id>')
    def put_creative_result(organisation_id, ident, report_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        _id(report_id)
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or set(value) != {'expectedVersion', 'data'} or type(value['expectedVersion']) is not int:
            raise MarketingDraftError('Use the current result version and reporting fields.')
        data = normalise_result(value['data'])
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            candidate = con.execute('SELECT result_json FROM growthrova_image_requests WHERE document_id=? AND operation_id=?',
                                    (ident, data['operationId'])).fetchone()
            if not candidate or not json.loads(candidate['result_json']).get('sha256'):
                raise MarketingDraftError('Choose a saved advert from this campaign.')
            old = con.execute('SELECT * FROM growthrova_creative_results WHERE owner_id=? AND organisation_id=? AND report_id=?', (*scope, report_id)).fetchone()
            if old and old['document_id'] != ident:
                raise OfflineDocumentAccessError('Report access denied')
            if old and json.loads(old['data_json']) == data:
                if checked(con, organisation_id, ident, scope) is not None:
                    raise OfflineDocumentAccessError('Campaign access changed')
                return jsonify(reportId=report_id, version=old['version'], data=data, metrics=ratios(data))
            if (old['version'] if old else 0) != value['expectedVersion']:
                raise MarketingDraftError('Results changed. Reload before correcting them.', 'revision_conflict', 409)
            others = con.execute('SELECT report_id,data_json FROM growthrova_creative_results WHERE owner_id=? AND organisation_id=?', scope).fetchall()
            if not old and len(others) >= 500:
                raise MarketingDraftError('This business has reached its saved result limit.', 'storage_limit', 409)
            for other in others:
                previous = json.loads(other['data_json'])
                if other['report_id'] != report_id and all(previous[k] == data[k] for k in ('platform','accountId','adId')) and previous['fromDate'] <= data['throughDate'] and data['fromDate'] <= previous['throughDate']:
                    raise MarketingDraftError('This advert already has results for overlapping dates. Correct that report.', 'overlapping_report', 409)
            if checked(con, organisation_id, ident, scope) is not None:
                raise OfflineDocumentAccessError('Campaign access changed')
            version, now = value['expectedVersion']+1, time.time()
            con.execute('INSERT INTO growthrova_creative_results VALUES(?,?,?,?,?,?,?) '
                        'ON CONFLICT(owner_id,organisation_id,report_id) DO UPDATE SET version=excluded.version,data_json=excluded.data_json,updated=excluded.updated',
                        (*scope, ident, report_id, version, json.dumps(data), now))
            con.execute('INSERT INTO growthrova_creative_result_history VALUES(?,?,?,?,?,?)',
                        (*scope, report_id, version, json.dumps(data), now))
            con.commit()
        return jsonify(reportId=report_id, version=version, data=data, metrics=ratios(data))
