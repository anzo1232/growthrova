"""Private, bounded website preparation queue over authoritative saved campaigns."""
import math
import re

from flask import g, jsonify, request

import business_marketing_drafts as drafts
from business_growthrova_planning_worklist import read_planning_page


def register_organic_queue(app, repo, root, *, revalidate, prepare):
    @app.get(root + '/organic-queue')
    def saved_organic_queue(organisation_id):
        from business_growthrova_plans import PlannerUnavailable

        args = request.args
        allowed = {'limit', 'beforeUpdated', 'beforeId', 'status', 'kind', 'review'}

        def invalid():
            raise drafts.MarketingDraftError(
                'Choose 1–10 campaigns, a complete saved page cursor and supported website-work filters.')

        if (set(args) - allowed or any(len(args.getlist(key)) != 1 for key in args)
                or not re.fullmatch(r'(?:[1-9]|10)', args.get('limit', '5'))
                or ('beforeUpdated' in args) != ('beforeId' in args)
                or args.get('status', '') not in ('', 'planned', 'drafting', 'ready_for_review', 'handed_off', 'parked')
                or args.get('kind', '') not in ('', 'content', 'improvement')
                or args.get('review', '') not in ('', 'retained', 'changed', 'historical', 'missing_draft', 'missing_action')):
            invalid()
        cursor = None
        if 'beforeId' in args:
            ident = drafts._id(args['beforeId'])
            try:
                updated = float(args['beforeUpdated'])
            except ValueError:
                updated = float('nan')
            if not math.isfinite(updated) or updated < 0:
                invalid()
            cursor = (updated, updated, ident)
        limit = int(args.get('limit', '5'))
        filters = {key: args.get(key, '') for key in ('status', 'kind', 'review')}
        scope = repo._scope(organisation_id)
        business, website = g.growthrova_org.get('name'), g.growthrova_org.get('website')
        signature, records = read_planning_page(repo, scope, limit, cursor)

        def final_check():
            error = revalidate()
            if error is not None:
                return error
            if g.growthrova_user['id'] != scope[0]:
                return jsonify(code='auth_required', error='Your session changed. Sign in again.'), 401
            if (g.growthrova_org.get('name') != business
                    or g.growthrova_org.get('website') != website):
                return jsonify(code='plan_business_changed',
                    error='Business details changed. Reload saved website work.'), 409
            if read_planning_page(repo, scope, limit, cursor)[0] != signature:
                return jsonify(code='organic_queue_changed',
                    error='Saved campaigns changed. Reload this website-work page.'), 409
            return None

        try:
            queue = prepare(dict(organicQueue=records, business=business, sourceUrl=website, filters=filters))
        except (PlannerUnavailable, drafts.MarketingDraftError):
            error = final_check()
            if error is not None:
                return error
            return jsonify(code='organic_queue_unavailable',
                error='Saved website work is unavailable. Retry this page; saved work is unchanged.'), 503
        error = final_check()
        if error is not None:
            return error
        last = records[-1] if records else None
        return jsonify(**queue, scope='saved_organic_queue_page', filters=filters,
            campaigns=[dict(id=record['id'], revision=record['revision'], updated=record['updated'])
                       for record in records],
            nextCursor=dict(beforeUpdated=last['updated'], beforeId=last['id'])
                if len(signature) > limit else None,
            pageSummary=dict(campaigns=len(records), matchingItems=len(queue['items']),
                withoutWork=len(queue['empty']), historicalContext=len(queue['historical'])),
            saved=False, canPublish=False, canSpend=False,
            limitations='Items and counts cover this saved campaign page only. Filters apply within the page; '
                'an empty filtered page can have a next cursor. Reuse the same filters on subsequent pages. '
                'Concurrent saves can move campaigns between pages; restart paging for a fresh snapshot. '
                'Open the exact campaign revision to prepare edits, then inspect and explicitly save. '
                'Preparation statuses are owner records, not publication receipts or website changes. '
                'Retained references are unverified and search snapshots are historical. '
                'Rankings, traffic and AI-search visibility are unmeasured.')
