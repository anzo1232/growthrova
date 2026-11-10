"""Contact-free saved article delivery evidence; never queries or changes a site."""


def organic_delivery_results(con, scope, now):
    campaigns = {}
    totals = dict(totalJobs=0, draftReceipts=0, publicationReceipts=0,
                  simulations=0, unresolvedJobs=0, unconfirmedCompletions=0)
    # Project only aggregate fields, never article text, site configuration or receipts.
    rows = con.execute('''SELECT r.document_id,d.revision,
        json_extract(d.document_json,'$.name') AS name,r.mode,r.state,
        COALESCE(json_extract(r.snapshot_json,'$.deliveryOutcome'),'published') AS action,
        COUNT(*) AS count,
        SUM(CASE WHEN json_extract(r.snapshot_json,'$.revision')!=d.revision THEN 1 ELSE 0 END) AS older,
        SUM(CASE WHEN r.state IN ('published','drafted','simulated')
            AND json_extract(r.receipt_json,'$.outcome')=r.state
            AND json_type(r.receipt_json,'$.id')='text'
            AND length(trim(json_extract(r.receipt_json,'$.id')))>0
            AND ((r.mode='simulation' AND r.state='simulated')
                OR (r.mode='live' AND r.state=COALESCE(
                    json_extract(r.snapshot_json,'$.deliveryOutcome'),'published')))
            THEN 1 ELSE 0 END) AS confirmed
        FROM growthrova_organic_jobs r
        JOIN marketing_drafts d ON d.id=r.document_id
        JOIN offline_document_owners o ON o.draft_id=d.id
        WHERE r.owner_id=? AND r.organisation_id=?
          AND o.owner_id=r.owner_id AND o.organisation_id=r.organisation_id
        GROUP BY r.document_id,r.mode,r.state,action
        ORDER BY d.updated DESC,r.document_id,r.mode,action,r.state''', scope)
    for row in rows:
        campaign = campaigns.setdefault(row['document_id'], dict(
            campaignId=row['document_id'], name=row['name'], revision=row['revision'],
            **{key: 0 for key in totals}, olderApprovalJobs=0, jobs=[]))
        confirmed = row['confirmed']
        counts = dict(totalJobs=row['count'],
            draftReceipts=confirmed if row['mode'] == 'live' and row['state'] == 'drafted' else 0,
            publicationReceipts=confirmed if row['mode'] == 'live' and row['state'] == 'published' else 0,
            simulations=confirmed if row['mode'] == 'simulation' and row['state'] == 'simulated' else 0,
            unresolvedJobs=row['count'] if row['state'] in ('dispatching', 'uncertain') else 0,
            unconfirmedCompletions=(row['count'] - confirmed
                if row['state'] in ('published', 'drafted', 'simulated') else 0))
        for key, value in counts.items():
            campaign[key] += value
            totals[key] += value
        campaign['olderApprovalJobs'] += row['older']
        campaign['jobs'].append(dict(mode=row['mode'], savedState=row['state'],
            approvedAction=('simulation' if row['mode'] == 'simulation' else row['action']),
            count=row['count'], confirmedReceipts=confirmed))
    return dict(scope='all_saved_organic_delivery_jobs', observedAt=now,
                **totals, campaigns=list(campaigns.values()))
