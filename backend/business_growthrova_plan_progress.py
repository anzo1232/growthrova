"""Read-only saved planning and delivery states, never inferred publication."""
import json


def plan_progress(con, scope, now):
    campaigns = {}
    for row in con.execute('''SELECT d.id,d.revision,d.updated,
            json_extract(d.document_json,'$.name') AS name,
            json_extract(d.document_json,'$.calendarStartDate') AS start_date,
            json_extract(d.document_json,'$.posts') AS posts
            FROM marketing_drafts d JOIN offline_document_owners o ON o.draft_id=d.id
            WHERE o.owner_id=? AND o.organisation_id=? ORDER BY d.updated DESC,d.id''', scope):
        posts = json.loads(row['posts'] or '[]')
        campaigns[row['id']] = dict(campaignId=row['id'], name=row['name'], revision=row['revision'],
            savedAt=row['updated'], calendarStartDate=row['start_date'], plannedPosts=len(posts),
            copyReviewed=sum(post.get('status') == 'copy_reviewed' for post in posts),
            postingDrafts=0, olderPostingDrafts=0, jobs=[], totalJobs=0,
            waitingPastScheduledTime=0, olderApprovalJobs=0, livePublicationReceipts=0)

    for row in con.execute('''SELECT r.document_id,COUNT(*) AS count,
            SUM(CASE WHEN json_extract(r.draft_json,'$.revision')!=d.revision THEN 1 ELSE 0 END) AS older
            FROM growthrova_social_drafts r
            JOIN marketing_drafts d ON d.id=r.document_id
            JOIN offline_document_owners o ON o.draft_id=d.id
            WHERE o.owner_id=? AND o.organisation_id=? GROUP BY r.document_id''', scope):
        campaigns[row['document_id']].update(postingDrafts=row['count'], olderPostingDrafts=row['older'])

    # Select aggregates only: no captions, destinations, artwork or raw receipts.
    for row in con.execute('''SELECT r.document_id,r.channel,r.mode,r.state,COUNT(*) AS count,
            SUM(CASE WHEN r.state IN ('scheduled','claimed') AND r.due_at<? THEN 1 ELSE 0 END) AS elapsed,
            SUM(CASE WHEN json_extract(r.snapshot_json,'$.revision')!=d.revision THEN 1 ELSE 0 END) AS older,
            SUM(CASE WHEN r.mode='live' AND r.state='published'
                AND json_extract(r.receipt_json,'$.outcome')='published'
                AND length(trim(json_extract(r.receipt_json,'$.id')))>0 THEN 1 ELSE 0 END) AS published
            FROM growthrova_social_jobs r
            JOIN marketing_drafts d ON d.id=r.document_id
            JOIN offline_document_owners o ON o.draft_id=d.id
            WHERE r.owner_id=? AND r.organisation_id=?
                AND o.owner_id=r.owner_id AND o.organisation_id=r.organisation_id
            GROUP BY r.document_id,r.channel,r.mode,r.state
            ORDER BY r.document_id,r.channel,r.mode,r.state''', (now, *scope)):
        campaign = campaigns[row['document_id']]
        campaign['jobs'].append(dict(channel=row['channel'], mode=row['mode'], savedState=row['state'],
            count=row['count'], waitingPastScheduledTime=row['elapsed'], olderApprovalJobs=row['older'],
            livePublicationReceipts=row['published']))
        for key, column in (('totalJobs', 'count'), ('waitingPastScheduledTime', 'elapsed'),
                            ('olderApprovalJobs', 'older'), ('livePublicationReceipts', 'published')):
            campaign[key] += row[column]
    return dict(scope='all_saved_plans_and_social_jobs', observedAt=now,
        campaigns=list(campaigns.values()))
