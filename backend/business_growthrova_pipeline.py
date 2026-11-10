"""Read-only enquiry states and revision history, never verified contact."""
import json
from datetime import datetime, timedelta, timezone

from business_growthrova_leads import STATUSES


def enquiry_review(data, updated, now):
    """Shared current-snapshot rules for aggregate and individual owner review."""
    active = data['status'] in ('new', 'contacted', 'qualified', 'booked')
    open_action = bool(data.get('nextAction', '').strip()
                       and data.get('actionState', 'open') == 'open')
    due = data.get('actionDueDate', '') if open_action else ''
    today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    return dict(active=active,
                stale=data['status'] in ('new', 'contacted') and now - updated >= 7 * 86400,
                unplanned=active and not open_action,
                openAction=open_action, actionDueDate=due,
                actionTiming=('overdue' if due < today else 'today' if due == today else 'upcoming')
                    if due else ('undated' if open_action else ''),
                responsiblePerson=data.get('responsiblePerson', ''))


def pipeline_overview(rows, now):
    def counts():
        return dict(total=0, active=0, stale=0, unplanned=0,
                    statuses={status: 0 for status in STATUSES})

    totals, campaigns = counts(), {}
    for row in rows:
        data = json.loads(row['data_json'])
        status = data['status']
        review = enquiry_review(data, row['updated'], now)
        campaign = campaigns.setdefault(row['document_id'], counts())
        for value in (totals, campaign):
            value['total'] += 1
            for key in ('active', 'stale', 'unplanned'):
                value[key] += int(review[key])
            if status in value['statuses']:
                value['statuses'][status] += 1
    return dict(observedAt=now, totals=totals,
                campaigns=[dict(campaignId=ident, **value)
                           for ident, value in sorted(campaigns.items())])


def status_history(con, scope, period, now):
    """Aggregate consecutive saved revisions, not inferred funnel conversions.

    Join the predecessor before filtering time so an older saved status remains
    the baseline. SQL projects only status/date/counts, never contact snapshots.
    The caller supplies the same read transaction and final access check as all
    other recorded-results sections.
    """
    today = datetime.fromtimestamp(now, timezone.utc).date()
    start = today - timedelta(days=int(period) - 1) if period != 'all' else None
    first_stamp = datetime.combine(start, datetime.min.time(), timezone.utc).timestamp() if start else 0
    rows = con.execute('''SELECT l.document_id AS campaign_id,
            date(e.occurred,'unixepoch') AS saved_date,
            CASE WHEN e.revision=1 THEN 'initial'
                 WHEN p.revision IS NULL THEN 'gap' ELSE 'transition' END AS kind,
            json_extract(p.data_json,'$.status') AS before_status,
            json_extract(e.data_json,'$.status') AS after_status, COUNT(*) AS count
        FROM growthrova_lead_events e
        JOIN growthrova_leads l ON l.id=e.lead_id
        JOIN offline_document_owners o ON o.draft_id=l.document_id
        JOIN marketing_drafts d ON d.id=l.document_id
        LEFT JOIN growthrova_lead_events p ON p.lead_id=e.lead_id AND p.revision=e.revision-1
        WHERE l.owner_id=? AND l.organisation_id=?
          AND o.owner_id=l.owner_id AND o.organisation_id=l.organisation_id
          AND e.occurred>=? AND e.occurred<=?
          AND (e.revision=1 OR p.revision IS NULL
               OR json_extract(p.data_json,'$.status') IS NOT json_extract(e.data_json,'$.status'))
        GROUP BY l.document_id,saved_date,kind,before_status,after_status
        ORDER BY saved_date,l.document_id,kind,before_status,after_status''', (*scope, first_stamp, now)).fetchall()
    if start is None:
        start = datetime.fromisoformat(rows[0]['saved_date']).date() if rows else today
    span = (today - start).days + 1
    width = max(1, (span + 11) // 12)

    def counts():
        return dict(initialRecords=0, statusChanges=0, historyGaps=0)

    buckets = [dict(fromDate=(start + timedelta(days=i)).isoformat(),
                    throughDate=min(today, start + timedelta(days=i + width - 1)).isoformat(), **counts())
               for i in range(0, span, width)]
    totals, campaigns, transitions = counts(), {}, {}
    for row in rows:
        day = datetime.fromisoformat(row['saved_date']).date()
        bucket = buckets[(day - start).days // width]
        campaign = campaigns.setdefault(row['campaign_id'], counts())
        valid = row['after_status'] in STATUSES
        if row['kind'] == 'initial' and valid:
            key = 'initialRecords'
        elif row['kind'] == 'transition' and valid and row['before_status'] in STATUSES:
            key = 'statusChanges'
            pair = (row['before_status'], row['after_status'])
            transitions[pair] = transitions.get(pair, 0) + row['count']
        else:
            key = 'historyGaps'
        for target in (totals, campaign, bucket):
            target[key] += row['count']
    return dict(observedAt=now, fromDate=start.isoformat(), throughDate=today.isoformat(), timezone='UTC',
                limitations='Saved revision event dates, not enquiry arrival, contact or outcome dates. '
                    'Initial records are separate from later status changes. Unchanged statuses add no transition. '
                    'Repeated changes and reversals count each time, not unique people or conversions. '
                    'Missing or invalid consecutive history is excluded from transition totals and counted as gaps; '
                    'entirely absent historical events cannot be counted or reconstructed. '
                    'No verified contact, permission, bookings, payments or marketing attribution is inferred.',
                totals=totals, buckets=buckets,
                transitions=[dict(fromStatus=before, toStatus=after, count=count)
                             for (before, after), count in sorted(transitions.items())],
                campaigns=[dict(campaignId=ident, **value) for ident, value in sorted(campaigns.items())])
