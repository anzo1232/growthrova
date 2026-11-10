"""Opt-in local credit policy; reservations live in the existing request ledgers.

Resolvers are bounded, independently verified local metadata reads, never network
calls or writes. A bucket is a durable allowance identity: policy/version changes
do not reset usage. Only explicit operator provisioning creates a new bucket.
"""
from contextlib import closing
from dataclasses import dataclass
import math
import time

from business_marketing_drafts import MarketingDraftError


@dataclass(frozen=True)
class GenerationCreditConfig:
    resolve: object
    clock: object = time.time

    def __post_init__(self):
        if not callable(self.resolve) or not callable(self.clock):
            raise ValueError('Verified local credit resolver and clock required')


class GenerationCredits:
    def __init__(self, repo, config):
        self.repo, self.config = repo, config

    def status(self, organisation_id, *, con=None):
        owner, org = self.repo._scope(organisation_id)
        try:
            row, now = self.config.resolve(owner, org), self.config.clock()
            if row is None:
                return dict(state='missing', available=False)
            if (not isinstance(row, dict) or row.get('ownerId') != owner or row.get('organisationId') != org
                    or any(not isinstance(row.get(k), str) or not 1 <= len(row[k]) <= 128 for k in ('bucket', 'version'))
                    or any(type(row.get(k)) is not int or not 1 <= row[k] <= 10**9
                           for k in ('allowance', 'writingCost', 'imageCost'))
                    or any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) for k in ('from', 'until'))
                    or not 0 <= row['from'] < row['until'] <= 253402300799
                    or type(now) not in (int, float) or not math.isfinite(now)):
                raise ValueError('Invalid policy')
            if con is None:
                with closing(self.repo._connect()) as read:
                    read.execute('BEGIN')
                    return self._project(read, owner, org, row, now)
            return self._project(con, owner, org, row, now)
        except Exception:
            raise MarketingDraftError('Credit access could not be checked. Saved work is retained; refresh access.',
                                      'generation_credits_unavailable', 503) from None

    @staticmethod
    def _project(con, owner, org, row, now):
        used = 0
        for table in ('growthrova_writing_requests', 'growthrova_image_requests'):
            # Fixed internal table names. Ownership, bucket and saved cost are
            # checked independently of current grant/version and request state.
            for saved in con.execute('''SELECT json_extract(r.result_json,'$.generationAccess.credits.cost') AS cost
                    FROM ''' + table + ''' r JOIN offline_document_owners o ON o.draft_id=r.document_id
                    WHERE o.owner_id=? AND o.organisation_id=?
                    AND json_extract(r.result_json,'$.generationAccess.credits.bucket')=?''', (owner, org, row['bucket'])):
                if type(saved['cost']) is not int or not 1 <= saved['cost'] <= 10**9:
                    raise ValueError('Corrupt credit reservation')
                used += saved['cost']
        state = 'scheduled' if now < row['from'] else 'expired' if now >= row['until'] else 'active'
        return dict(state=state, available=state == 'active', bucket=row['bucket'], policyVersion=row['version'],
                    validFrom=row['from'], validUntil=row['until'], allowance=row['allowance'],
                    retained=used, remaining=max(0, row['allowance']-used),
                    writingCost=row['writingCost'], imageCost=row['imageCost'])

    def reserve(self, organisation_id, con, family):
        status = self.status(organisation_id, con=con)
        if family not in ('writing', 'images'):
            raise ValueError('Explicit generation family required')
        cost = status.get('writingCost' if family == 'writing' else 'imageCost')
        if not status['available'] or status['remaining'] < cost:
            raise MarketingDraftError('The current credit allowance cannot cover this request. Review Generation access; saved work and pending checks remain available.',
                                      'generation_credits_required', 403)
        return dict(bucket=status['bucket'], policyVersion=status['policyVersion'], cost=cost,
                    validFrom=status['validFrom'], validUntil=status['validUntil'])

    def activity(self, organisation_id, page=1):
        """One read snapshot, current bucket only; never load prompts or pixels.

        Pages use stable identities, not fabricated request/completion times.
        The full-bucket balance is calculated independently of the page.
        """
        owner, org = self.repo._scope(organisation_id)
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN')
            status = self.status(organisation_id, con=con)
            if 'bucket' not in status:
                return dict(allowance=status, count=0, page=1, pageSize=50, pages=1, groups=[], requests=[])
            parts, args = [], []
            for table, family in (('growthrova_writing_requests', 'writing'),
                                  ('growthrova_image_requests', 'images')):
                parts.append('''SELECT r.document_id AS campaignId, r.operation_id AS operationId,
                    json_extract(d.document_json,'$.name') AS campaignName,
                    ? AS family,
                    CASE WHEN ?='images' THEN 'image'
                      WHEN json_type(r.result_json,'$.creativePlan')='object' THEN 'concepts'
                      ELSE 'copy' END AS kind,
                    CASE WHEN json_extract(r.result_json,'$.state') IN ('pending','uncertain','proposed','held')
                      THEN json_extract(r.result_json,'$.state') ELSE 'unknown' END AS savedState,
                    json_extract(r.result_json,'$.generationAccess.credits.cost') AS credits
                    FROM ''' + table + ''' r
                    JOIN offline_document_owners o ON o.draft_id=r.document_id
                    LEFT JOIN marketing_drafts d ON d.id=r.document_id
                    WHERE o.owner_id=? AND o.organisation_id=?
                    AND json_extract(r.result_json,'$.generationAccess.credits.bucket')=?''')
                args.extend((family, family, owner, org, status['bucket']))
            query = 'WITH owned AS (' + ' UNION ALL '.join(parts) + ') '
            groups = [dict(row) for row in con.execute(query + '''SELECT kind,savedState,
                COUNT(*) AS count,SUM(credits) AS credits FROM owned
                GROUP BY kind,savedState ORDER BY kind,savedState''', args)]
            count = sum(row['count'] for row in groups)
            pages = max(1, (count + 49) // 50)
            page = min(page, pages)
            requests = [dict(row) for row in con.execute(query + '''SELECT * FROM owned
                ORDER BY campaignId,family,operationId LIMIT 50 OFFSET ?''', [*args, (page-1)*50])]
            return dict(allowance=status, count=count, page=page, pageSize=50, pages=pages,
                        groups=groups, requests=requests)
