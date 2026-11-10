"""Explicit read-only observations of saved exact paid resource trees.

No polling, writes, ledger transitions or status inference from old receipts.
The existing native pause lookup verifies account and full resource lineage.
"""
from contextlib import closing
from copy import deepcopy
import json
import re

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError


def register_observation_routes(app, delivery, endpoint, checked):
    repo = delivery.repo

    def sources(con, ident, platform):
        result = []
        for row in delivery.rows(con, ident, platform):
            if row['mode'] != 'live' or row['state'] != 'created_paused':
                continue
            receipt = json.loads(row['receipt_json']) if row['receipt_json'] else None
            if not receipt or receipt.get('outcome') != 'paused':
                continue
            snap = json.loads(row['snapshot_json'])
            result.append(dict(jobId=row['job_id'], revision=snap['revision'],
                               account=snap['account'], resources=receipt['resources']))
        return result

    @app.route(endpoint + '/campaign-state', methods=['GET', 'POST'])
    def growthrova_paid_campaign_state(organisation_id, ident, platform):
        if platform not in ('meta', 'google'):
            raise MarketingDraftError('Choose Meta or Google Search.')
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            saved = sources(con, ident, platform)
        config = delivery.config
        adapter = config.adapters.get(platform)
        available = config.mode == 'live' and callable(getattr(adapter, 'observe_campaign', None))
        observation = None
        if request.method == 'POST':
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or set(data) != {'jobId'}:
                raise MarketingDraftError('Choose one saved platform campaign to check.')
            if not isinstance(data['jobId'], str) or not re.fullmatch('[a-f0-9]{64}', data['jobId']):
                raise MarketingDraftError('Choose a valid saved campaign identifier.')
            source = next((s for s in saved if s['jobId'] == data['jobId']), None)
            if source is None:
                raise MarketingDraftError('Confirmed platform campaign not found.', 'not_found', 404)
            # Internal snapshot shape reuses read-only pause binding/lineage
            # validation. No pause method or mutation authority is invoked.
            snap = dict(intent='pause_exact_resources', campaignId=ident,
                        ownerId=scope[0], organisationId=scope[1], platform=platform,
                        account=source['account'], resources=source['resources'])
            def read_authorised():
                return (delivery.authorised(snap, creation=False)
                        and delivery.config is config and config.adapters.get(platform) is adapter)

            observation = dict(jobId=source['jobId'], outcome='unavailable')
            try:
                if available and read_authorised():
                    value = adapter.observe_campaign(deepcopy(snap))
                    # Discard acknowledgements after any connection/authority
                    # change, even if the old adapter returned a valid state.
                    if (read_authorised()
                            and isinstance(value, dict) and set(value) == {'campaignState'}
                            and value['campaignState'] in ('paused', 'enabled')):
                        observation.update(outcome='observed', campaignState=value['campaignState'],
                                           observedAt=config.clock())
            except Exception:
                pass  # Never expose raw provider errors or credentials.
        # New transaction after the slow read: SQLite's old snapshot cannot
        # establish current ownership or receipt identity.
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            if observation and observation['outcome'] == 'observed' and not read_authorised():
                observation = dict(jobId=source['jobId'], outcome='unavailable')
            latest = sources(con, ident, platform)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            if observation and source not in latest:
                raise MarketingDraftError('Saved campaign changed. Reopen before checking again.', 'revision_conflict', 409)
        response = jsonify(sources=latest, available=available, observation=observation)
        response.headers['Cache-Control'] = 'no-store'
        return response
