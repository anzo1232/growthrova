"""Bounded saved planning review across one authenticated business; no writes."""
from contextlib import closing
import math
import re

from flask import g, jsonify, request
import business_marketing_drafts as drafts


def read_planning_page(repo, scope, limit, cursor):
    """One scoped saved snapshot; include the lookahead in its change fence."""
    with closing(repo._connect()) as con:
        con.execute('BEGIN')
        condition = ' AND (d.updated<? OR (d.updated=? AND d.id<?))' if cursor else ''
        rows = con.execute('''SELECT d.id,d.revision,d.updated FROM marketing_drafts d
            JOIN offline_document_owners o ON o.draft_id=d.id
            WHERE o.owner_id=? AND o.organisation_id=?''' + condition +
            ' ORDER BY d.updated DESC,d.id DESC LIMIT ?',
            (*scope, *(cursor or ()), limit + 1)).fetchall()
        signature = [tuple(row) for row in rows]
        records = [drafts.read_draft(con, row['id']) for row in rows[:limit]]
    return signature, records


def register_planning_worklist(app, repo, root, *, revalidate, prepare):
    @app.get(root + '/planning-worklist')
    def planning_worklist(organisation_id):
        from business_growthrova_plans import PlannerUnavailable

        args = request.args
        invalid = (set(args) - {'limit', 'beforeUpdated', 'beforeId'}
                   or any(len(args.getlist(key)) != 1 for key in args)
                   or not re.fullmatch(r'(?:[1-9]|10)', args.get('limit', '5'))
                   or ('beforeUpdated' in args) != ('beforeId' in args))
        if invalid:
            raise drafts.MarketingDraftError('Choose 1–10 saved plans and a complete page cursor.')
        limit = int(args.get('limit', '5'))
        cursor = None
        if 'beforeId' in args:
            ident = drafts._id(args['beforeId'])
            try:
                updated = float(args['beforeUpdated'])
            except ValueError:
                updated = float('nan')
            if not math.isfinite(updated) or updated < 0:
                raise drafts.MarketingDraftError('Use the saved planning page cursor.')
            cursor = (updated, updated, ident)

        scope = repo._scope(organisation_id)
        business = g.growthrova_org.get('name')
        website = g.growthrova_org.get('website')

        def read_page():
            return read_planning_page(repo, scope, limit, cursor)

        signature, records = read_page()

        def final_check():
            error = revalidate()
            if error is not None:
                return error
            if g.growthrova_user['id'] != scope[0]:
                return jsonify(code='auth_required', error='Your session changed. Sign in again.'), 401
            if (g.growthrova_org.get('name') != business
                    or g.growthrova_org.get('website') != website):
                return jsonify(code='plan_business_changed',
                    error='Business details changed. Reload the planning worklist.'), 409
            if read_page()[0] != signature:
                return jsonify(code='planning_worklist_changed',
                    error='Saved plans changed during review. Reload this planning page.'), 409
            return None

        try:
            campaigns = prepare(dict(planningWorklist=records, business=business, sourceUrl=website)) \
                if records else []
        except (PlannerUnavailable, drafts.MarketingDraftError):
            error = final_check()
            if error is not None:
                return error
            return jsonify(code='plan_review_unavailable',
                error='Planning review is unavailable. Your saved campaigns are unchanged.'), 503
        error = final_check()
        if error is not None:
            return error
        last = records[-1] if records else None
        next_cursor = dict(beforeUpdated=last['updated'], beforeId=last['id']) \
            if len(signature) > limit else None
        return jsonify(scope='saved_planning_page', campaigns=campaigns, nextCursor=next_cursor,
            pageSummary=dict(campaigns=len(campaigns),
                needingAction=sum(bool(item['actions']) for item in campaigns),
                historicalContext=sum(not item['contextMatches'] for item in campaigns)),
            limitations='Counts cover this page only. Saved planning review does not verify website '
                'claims, media rights, provider readiness, publication, campaign performance or spend. '
                'Reopen the exact campaign revision before preparing and explicitly saving changes. '
                'Concurrent saves between pages can move campaigns; restart paging for a fresh worklist.',
            saved=False, canPublish=False, canSpend=False)
