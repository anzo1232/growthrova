"""Private saved planning dates and reminders; never delivery or publication."""
from datetime import date
import math
import re

from flask import g, jsonify, request

import business_marketing_drafts as drafts
from business_growthrova_planning_worklist import read_planning_page


def register_content_agenda(app, repo, root, *, revalidate, prepare):
    @app.get(root + '/content-agenda')
    def saved_content_agenda(organisation_id):
        from business_growthrova_plans import PlannerUnavailable

        args = request.args
        allowed = {'limit', 'beforeUpdated', 'beforeId', 'from', 'through', 'channel', 'review', 'format'}

        def invalid():
            raise drafts.MarketingDraftError(
                'Choose 1–10 campaigns, a complete page cursor and valid planning filters.')

        if (set(args) - allowed or any(len(args.getlist(key)) != 1 for key in args)
                or not re.fullmatch(r'(?:[1-9]|10)', args.get('limit', '5'))
                or ('beforeUpdated' in args) != ('beforeId' in args)
                or args.get('review', 'all') not in ('all', 'reviewed', 'needs_review')
                or args.get('format', 'json') not in ('json', 'calendar-ics')
                or len(args.get('channel', '')) > 50):
            invalid()
        filters = {key: args.get(key, '') for key in ('from', 'through', 'channel')}
        filters['review'] = args.get('review', 'all')
        for key in ('from', 'through'):
            if key in args:
                try:
                    if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', args[key]):
                        invalid()
                    date.fromisoformat(args[key])
                except ValueError:
                    invalid()
        if filters['from'] and filters['through'] and filters['from'] > filters['through']:
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
                    error='Business details changed. Reload your content plan.'), 409
            if read_planning_page(repo, scope, limit, cursor)[0] != signature:
                return jsonify(code='content_agenda_changed',
                    error='Saved plans changed. Reload this content plan page before downloading.'), 409
            return None

        try:
            agenda = prepare(dict(contentAgenda=records, business=business, sourceUrl=website,
                                  filters=filters, agendaFormat=args.get('format', 'json')))
        except (PlannerUnavailable, drafts.MarketingDraftError) as exc:
            error = final_check()
            if error is not None:
                return error
            return jsonify(code='content_agenda_unavailable' if isinstance(exc, PlannerUnavailable)
                           else 'content_agenda_needs_review', error=
                'Content planning is unavailable. Retry this saved page.' if isinstance(exc, PlannerUnavailable)
                else 'No matching saved dates can be exported. Review campaign preparation or change filters.'), \
                503 if isinstance(exc, PlannerUnavailable) else 409
        error = final_check()
        if error is not None:
            return error
        last = records[-1] if records else None
        return jsonify(**agenda, scope='saved_content_agenda_page', filters=filters,
            campaigns=[dict(id=record['id'], revision=record['revision'], updated=record['updated'])
                       for record in records],
            nextCursor=dict(beforeUpdated=last['updated'], beforeId=last['id'])
                if len(signature) > limit else None,
            pageSummary=dict(campaigns=len(records), items=len(agenda['items']),
                             needingPreparation=len(agenda['gaps'])),
            saved=False, canPublish=False, canSpend=False,
            limitations='Items, gaps and calendar downloads cover this saved campaign page only. '
                'Filters select items within the page; an empty page can still have a next cursor. '
                'Use the same filters on subsequent pages. Concurrent saves can move campaigns '
                'between pages; restart paging for a fresh snapshot. Planning reminders do not '
                'schedule or publish posts. Copy review does not verify claims or approve media. '
                'Calendar imports are snapshots; removed or rescheduled dates need manual cleanup.')
