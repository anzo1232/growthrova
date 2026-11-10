"""Opt-in bounded local task preparation. No host, provider or message dispatch.

An operator calls run_batch repeatedly with its returned nextCursor until None.
The trusted authorised(owner, business) callback must freshly check membership;
request sessions and ambient credentials are never used. Counts and exact task
lineage live in lead snapshots, so restart or repeated scans cannot duplicate work.
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
import uuid

from business_growthrova_customer_care import prepare_due_care
from business_growthrova_leads import persist_lead
from business_marketing_drafts import MarketingDraftError


@dataclass(frozen=True)
class CareConfig:
    enabled: bool = False
    authorised: object = None
    clock: object = time.time


class CarePreparation:
    def __init__(self, repo, config=None):
        self.repo, self.config = repo, config or CareConfig()

    def authorised(self, scope):
        try:
            return self.config.enabled is True and callable(self.config.authorised) and self.config.authorised(*scope) is True
        except Exception:
            return False

    def run_batch(self, *, cursor=''):
        """At most 30 leads per scan; a local write and progress commit together."""
        if not isinstance(cursor, str) or len(cursor) > 128:
            raise ValueError('Invalid scan cursor')
        result = dict(scanned=0, prepared=0, held=0, nextCursor=None)
        if self.config.enabled is not True:
            return result
        cutoff = datetime.fromtimestamp(self.config.clock(), timezone.utc).date().isoformat()
        with closing(self.repo._connect()) as con:
            ids = con.execute('SELECT id FROM growthrova_leads WHERE id>? ORDER BY id LIMIT 30', (cursor,)).fetchall()
        for entry in ids:
            with closing(self.repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                row = con.execute('SELECT * FROM growthrova_leads WHERE id=?', (entry['id'],)).fetchone()
                result['scanned'] += 1
                if row is None:
                    continue
                scope = row['owner_id'], row['organisation_id']
                original = json.loads(row['data_json'])
                if not original.get('customerCare', {}).get('background', {}).get('enabled'):
                    continue
                # Reserve 20 revisions for human pause, edits and takeover.
                if row['revision'] >= 480 or not self.repo._owned(con, row['document_id'], scope) or not self.authorised(scope):
                    result['held'] += 1
                    continue
                data, kinds = prepare_due_care(original, cutoff, background=True)
                if not kinds:
                    continue
                try:
                    persist_lead(con, scope, row['document_id'], dict(id=row['id'], mutationId=uuid.uuid4().hex,
                        expectedRevision=row['revision'], data=data), actor_id='customer-care-worker', preparing_care=True)
                    if not self.authorised(scope) or not self.repo._owned(con, row['document_id'], scope):
                        result['held'] += 1
                        continue  # Closing without commit rolls back tasks AND progress.
                    con.commit()
                    result['prepared'] += len(kinds)
                except MarketingDraftError:
                    result['held'] += 1
        if len(ids) == 30:
            result['nextCursor'] = ids[-1]['id']
        return result
