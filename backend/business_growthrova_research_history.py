"""Private retained website evidence inspection; never a fetch or restoration."""
from contextlib import closing
import math
import re
import sqlite3

from flask import g, jsonify, request

import business_growthrova_research as research
from business_growthrova_document_history import compare_sections


def register_research_history(app, repo, *, validate_owner, validate_business):
    @app.get('/api/growthrova/website-preview/history/compare', defaults={'compare': True})
    @app.get('/api/growthrova/organisations/<organisation_id>/research/history/compare',
             defaults={'compare': True})
    @app.get('/api/growthrova/website-preview/history')
    @app.get('/api/growthrova/website-preview/history/<research_id>')
    @app.get('/api/growthrova/organisations/<organisation_id>/research/history')
    @app.get('/api/growthrova/organisations/<organisation_id>/research/history/<research_id>')
    def research_history(organisation_id=None, research_id=None, compare=False):
        args = request.args
        if compare:
            invalid = set(args) != {'fromResearchId', 'toResearchId'} or any(
                len(args.getlist(key)) != 1 or not re.fullmatch(r'[0-9a-f]{32}', args[key])
                for key in args)
        else:
            invalid = bool(args) if research_id is not None else (
                set(args) - {'limit', 'beforeSaved', 'beforeId'}
                or any(len(args.getlist(key)) != 1 for key in args)
                or not re.fullmatch(r'(?:[1-9]|[1-4][0-9]|50)', args.get('limit', '20'))
                or ('beforeSaved' in args) != ('beforeId' in args))
        if (invalid or (research_id is not None and not re.fullmatch(r'[0-9a-f]{32}', research_id))
                or ('beforeId' in args and not re.fullmatch(r'[0-9a-f]{32}', args['beforeId']))):
            return jsonify(code='invalid_request', error='Choose two exact saved findings to compare.'
                if compare else 'Choose saved findings or a history page of 1–50 results.'), 400
        cursor = None
        if 'beforeSaved' in args:
            try:
                saved = float(args['beforeSaved'])
            except ValueError:
                saved = float('nan')
            if not math.isfinite(saved) or saved < 0:
                return jsonify(code='invalid_request', error='Use the saved findings history cursor.'), 400
            cursor = (saved, args['beforeId'])
        owner = g.growthrova_user['id']
        website = g.growthrova_org.get('website') if organisation_id else None
        scope = (owner, organisation_id or research.ONBOARDING_SCOPE)
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN')
                current = research.latest(con, scope)
                if compare:
                    snapshots = [research.read_retained(con, scope, args[key])
                                 for key in ('fromResearchId', 'toResearchId')]
                    result = None
                    if all(item is not None for item in snapshots):
                        changes = compare_sections(*(item['report'] for item in snapshots))
                        versions = [{key: value for key, value in item.items() if key != 'report'}
                                    for item in snapshots]
                        result = dict(fromVersion=versions[0], toVersion=versions[1],
                                      changes=changes, changedFields=[item['field'] for item in changes])
                elif research_id is not None:
                    snapshot = research.read_retained(con, scope, research_id)
                    result = dict(findings=snapshot) if snapshot else None
                else:
                    snapshots, cursor = research.retained_page(con, scope, int(args.get('limit', '20')), cursor)
                    result = dict(versions=[{key: value for key, value in item.items() if key != 'report'}
                                            for item in snapshots], nextCursor=cursor)
                if result is not None and organisation_id:
                    originals = {item['researchId']: item for item in ([snapshot] if research_id else snapshots)}
                    items = ([result['fromVersion'], result['toVersion']] if compare else
                             [result['findings']] if research_id else result['versions'])
                    for item in items:
                        # Report source is checked too, using the exact retained
                        # body, rather than treating a requested URL as evidence.
                        original = originals[item['researchId']]
                        item['matchesCurrentWebsite'] = bool(website) and item['website'] == website \
                            and original['report'].get('source_url') == website
            error = validate_business(owner, website) if organisation_id else validate_owner(owner)
            if error is not None:
                return error
            if result is None:
                return jsonify(code='research_not_retained', error=
                    'These findings are not retained in this account and business. Choose an available history result.'), 404
            return jsonify(**result, scope='retained_research_comparison' if compare else 'retained_research_snapshot',
                currentResearchId=current['researchId'] if current else None,
                canPublish=False, canSpend=False,
                limitations='Original unconfirmed website findings for inspection. Current identity is a read snapshot. '
                    'Comparisons show complete changed report sections; absent fields are distinct from null. '
                    'Results overwritten before history was installed may be unavailable. '
                    'Opening history does not restore findings, confirm claims or prepare a plan.')
        except sqlite3.Error:
            return jsonify(code='research_storage_unavailable', error=
                'Saved findings history could not be read. Retry recovery without reading the website again.'), 503
