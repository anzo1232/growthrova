"""Read-only retained generation reservations, not billing or inferred charges."""
import math


def operation_usage(con, scope):
    """Use document ownership; these older ledgers have no separate tenant keys.

    Aggregate every owned request, but return only a bounded identity list. Never
    select result bodies, prompts, provider IDs or image BLOBs. A completed result
    does not settle its reservation, and a saved pending state may be stale.
    """
    ledgers, campaigns = [], {}
    for table, family in (('growthrova_writing_requests', 'writing'),
                          ('growthrova_image_requests', 'images')):
        query = '''WITH owned AS (
            SELECT r.rowid AS saved_order, r.document_id, r.operation_id, r.reservation,
              json_extract(d.document_json,'$.name') AS campaign_name,
              CASE WHEN json_extract(r.result_json,'$.state') IN ('pending','uncertain','proposed','held')
                THEN json_extract(r.result_json,'$.state') ELSE 'unknown' END AS state,
              CASE WHEN ?='images' THEN 'image'
                WHEN json_type(r.result_json,'$.creativePlan')='object' THEN 'concepts'
                ELSE 'copy' END AS kind,
              CASE WHEN ?='images' AND json_extract(r.result_json,'$.model')='gemini_image3_pro'
                THEN json_extract(r.result_json,'$.actualProviderCredits') END AS credits
            FROM ''' + table + ''' r
            JOIN offline_document_owners o ON o.draft_id=r.document_id
            JOIN marketing_drafts d ON d.id=r.document_id
            WHERE o.owner_id=? AND o.organisation_id=?) '''
        args = (family, family, *scope)
        groups = [dict(kind=row['kind'], savedState=row['state'], count=row['count'],
                       retainedReservationMicrousd=row['reserved'])
                  for row in con.execute(query + '''SELECT kind,state,COUNT(*) AS count,
                    SUM(reservation) AS reserved FROM owned GROUP BY kind,state ORDER BY kind,state''', args)]
        # Aggregate from every owned row, never from the truncated reference list.
        for row in con.execute(query + '''SELECT document_id,campaign_name,kind,state,
                COUNT(*) AS count,SUM(reservation) AS reserved FROM owned
                GROUP BY document_id,campaign_name,kind,state ORDER BY document_id,kind,state''', args):
            campaign = campaigns.setdefault(row['document_id'], dict(
                campaignId=row['document_id'], name=row['campaign_name'], count=0,
                retainedReservationMicrousd=0, groups=[]))
            campaign['count'] += row['count']
            campaign['retainedReservationMicrousd'] += row['reserved']
            campaign['groups'].append(dict(family=family, kind=row['kind'], savedState=row['state'],
                count=row['count'], retainedReservationMicrousd=row['reserved']))
        recent = []
        for row in con.execute(query + 'SELECT * FROM owned ORDER BY saved_order DESC LIMIT 25', args):
            credits = row['credits']
            if type(credits) not in (int, float) or not math.isfinite(credits) or credits < 0:
                credits = None
            recent.append(dict(campaignId=row['document_id'], operationId=row['operation_id'],
                kind=row['kind'], savedState=row['state'], retainedReservationMicrousd=row['reservation'],
                observedRunwayCredits=credits))
        ledgers.append(dict(family=family, count=sum(group['count'] for group in groups),
            retainedReservationMicrousd=sum(group['retainedReservationMicrousd'] for group in groups),
            groups=groups, latestSavedRequests=recent))
    return dict(scope='all_saved_operations', ledgers=ledgers,
        campaigns=sorted(campaigns.values(), key=lambda row: (row['name'] or '', row['campaignId'])),
        count=sum(ledger['count'] for ledger in ledgers),
        retainedReservationMicrousd=sum(ledger['retainedReservationMicrousd'] for ledger in ledgers),
        observedFinalUsd=None)
