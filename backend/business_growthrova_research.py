"""Current unconfirmed website findings and immutable originals per private scope.

The caller owns the transaction and must revalidate access before committing or
disclosing a result, plus the exact website for saved-business scopes.
No fetch or campaign writes.
"""
import json
import sqlite3
import time
import uuid

# Organisation routes accept UUIDs only; the empty key cannot alias a business.
# Onboarding retains one latest result per owner, rather than one per entered URL.
ONBOARDING_SCOPE = ''


def initialise(con):
    con.execute('''CREATE TABLE IF NOT EXISTS growthrova_research_snapshots(
        owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
        requested INTEGER NOT NULL, website TEXT, started INTEGER,
        saved REAL, id TEXT, report_json TEXT,
        PRIMARY KEY(owner_id, organisation_id))''')
    con.execute('''CREATE TABLE IF NOT EXISTS growthrova_research_history(
        owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, id TEXT NOT NULL,
        website TEXT NOT NULL, saved REAL NOT NULL, report_json TEXT NOT NULL,
        PRIMARY KEY(owner_id, organisation_id, id))''')
    con.execute('''CREATE INDEX IF NOT EXISTS growthrova_research_history_page
        ON growthrova_research_history(owner_id,organisation_id,saved DESC,id DESC)''')
    con.execute('''CREATE TABLE IF NOT EXISTS growthrova_research_failures(
        owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
        attempt INTEGER NOT NULL, website TEXT, kind TEXT NOT NULL, finished REAL NOT NULL,
        partial_json TEXT,
        PRIMARY KEY(owner_id, organisation_id))''')
    # Existing isolated preview databases retain their category-only receipts.
    columns = {row[1] for row in con.execute('PRAGMA table_info(growthrova_research_failures)')}
    if 'partial_json' not in columns:
        con.execute('ALTER TABLE growthrova_research_failures ADD COLUMN partial_json TEXT')


def _current_row(con, scope):
    return con.execute('''SELECT id,website,saved,report_json
        FROM growthrova_research_snapshots WHERE owner_id=? AND organisation_id=?
        AND report_json IS NOT NULL''', scope).fetchone()


def _archive(con, scope, row):
    if row is None:
        return
    values = tuple(row[key] for key in ('id', 'website', 'saved', 'report_json'))
    existing = con.execute('''SELECT id,website,saved,report_json FROM growthrova_research_history
        WHERE owner_id=? AND organisation_id=? AND id=?''', (*scope, row['id'])).fetchone()
    if existing is not None:
        if tuple(existing) != values:
            # Never replace an original; the caller rolls back the whole write.
            raise sqlite3.IntegrityError('Saved research history differs from its original')
        return
    con.execute('INSERT INTO growthrova_research_history VALUES(?,?,?,?,?,?)', (*scope, *values))


# Read legacy current findings without backfilling or inventing earlier bodies.
HISTORY = '''SELECT id,website,saved,report_json FROM growthrova_research_history
    WHERE owner_id=? AND organisation_id=?
    UNION ALL SELECT id,website,saved,report_json FROM growthrova_research_snapshots s
    WHERE owner_id=? AND organisation_id=? AND report_json IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM growthrova_research_history h
        WHERE h.owner_id=s.owner_id AND h.organisation_id=s.organisation_id AND h.id=s.id)'''


def _snapshot(row):
    return dict(researchId=row['id'], website=row['website'], savedAt=row['saved'],
                status='unconfirmed', report=json.loads(row['report_json'])) if row is not None else None


def read_retained(con, scope, research_id):
    return _snapshot(con.execute('SELECT * FROM ('+HISTORY+') WHERE id=?',
                                (*scope, *scope, research_id)).fetchone())


def retained_page(con, scope, limit, cursor=None):
    condition = ' WHERE saved<? OR (saved=? AND id<?)' if cursor else ''
    rows = con.execute('SELECT * FROM ('+HISTORY+')'+condition+' ORDER BY saved DESC,id DESC LIMIT ?',
        (*scope, *scope, *((cursor[0], cursor[0], cursor[1]) if cursor else ()), limit+1)).fetchall()
    items = [_snapshot(row) for row in rows[:limit]]
    return items, (dict(beforeSaved=items[-1]['savedAt'], beforeId=items[-1]['researchId'])
                   if len(rows) > limit else None)


def reserve(con, scope):
    """Durable dispatch order survives restarts and wall-clock adjustments."""
    con.execute('''INSERT INTO growthrova_research_snapshots
        (owner_id,organisation_id,requested) VALUES(?,?,1)
        ON CONFLICT(owner_id,organisation_id) DO UPDATE SET requested=requested+1''', scope)
    return con.execute('''SELECT requested FROM growthrova_research_snapshots
        WHERE owner_id=? AND organisation_id=?''', scope).fetchone()['requested']


def retain(con, scope, website, started, report):
    # Start order, rather than completion order: a slow earlier request must not
    # overwrite findings from a later request that already completed successfully.
    old = _current_row(con, scope)
    changed = con.execute('''UPDATE growthrova_research_snapshots SET
        website=?,started=?,saved=?,id=?,report_json=?
        WHERE owner_id=? AND organisation_id=? AND requested>=?
          AND (started IS NULL OR started<?)''',
        (website, started, time.time(), uuid.uuid4().hex,
         json.dumps(report, ensure_ascii=False, allow_nan=False), *scope, started, started))
    if changed.rowcount != 1:
        return False
    _archive(con, scope, old)
    _archive(con, scope, _current_row(con, scope))
    return True


FAILURE_MESSAGES = {
    'read_unavailable': 'The website could not be read safely. Check the public HTTPS website or supply business details for review.',
    'insufficient_evidence': 'The website returned too little readable business information. Supply the missing business details for review or retry later.',
}


def retain_failure(con, scope, attempt, website, kind, *, partial=None):
    """Caller holds the write lock and revalidates access before commit.

    Only a known failure of the latest dispatch is recoverable here. Never
    persist raw exception/provider text or infer failure from elapsed time.
    Optional sparse extracted evidence is for inspection, never usable findings.
    One row per scope bounds retention; newer dispatches hide older receipts.
    """
    if kind not in FAILURE_MESSAGES:
        raise ValueError('Unknown research failure kind')
    partial_json = None
    if partial is not None:
        if (kind != 'insufficient_evidence' or not isinstance(partial, dict)
                or partial.get('evidence', {}).get('status') != 'insufficient'):
            raise ValueError('Only insufficient website evidence can be retained as partial findings')
        partial_json = json.dumps(partial, ensure_ascii=False, allow_nan=False)
        if len(partial_json.encode('utf8')) > 300000:
            # Preserve known failure recovery even if an unusually large report
            # cannot be retained. Never truncate evidence into an altered report.
            partial_json = None
    row = con.execute('''SELECT requested,started FROM growthrova_research_snapshots
        WHERE owner_id=? AND organisation_id=?''', scope).fetchone()
    if row is None or row['requested'] != attempt or row['started'] == attempt:
        return False
    con.execute('''INSERT INTO growthrova_research_failures
        (owner_id,organisation_id,attempt,website,kind,finished,partial_json) VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(owner_id,organisation_id) DO UPDATE SET
        attempt=excluded.attempt,website=excluded.website,kind=excluded.kind,
        finished=excluded.finished,partial_json=excluded.partial_json''',
        (*scope, attempt, website, kind, time.time(), partial_json))
    return True


def attempt_status(con, scope, website=None, *, include_partial=False):
    """Existing dispatch counters describe persistence, never worker liveness.

    Known failures have bounded receipts; interrupted/legacy reads remain
    unknown. A newer unresolved attempt never hides older useful findings.
    """
    row = con.execute('''SELECT requested,started,website,saved,id,report_json
        FROM growthrova_research_snapshots
        WHERE owner_id=? AND organisation_id=?''', scope).fetchone()
    if row is None:
        return dict(state='not_started', attempt=None, retainedAttempt=None, savedFindings=None)
    saved = None
    if row['report_json'] is not None:
        report = json.loads(row['report_json'])
        saved = dict(researchId=row['id'], website=row['website'], savedAt=row['saved'],
                     status='unconfirmed')
        if scope[1] != ONBOARDING_SCOPE:
            saved['matchesCurrentWebsite'] = bool(website) and row['website'] == website \
                and report.get('source_url') == website
    state = 'saved' if saved and row['started'] == row['requested'] else 'unresolved'
    result = dict(state=state, attempt=row['requested'], retainedAttempt=row['started'], savedFindings=saved)
    failure = con.execute('''SELECT website,kind,finished,partial_json FROM growthrova_research_failures
        WHERE owner_id=? AND organisation_id=? AND attempt=?''', (*scope, row['requested'])).fetchone()
    if state != 'saved' and failure is not None:
        result.update(state='failed', failure=dict(kind=failure['kind'],
            message=FAILURE_MESSAGES[failure['kind']], finishedAt=failure['finished']))
        result['failure']['partialFindingsAvailable'] = failure['partial_json'] is not None
        if include_partial and failure['partial_json'] is not None:
            result['failure']['partialFindings'] = dict(website=failure['website'],
                status='unconfirmed', sufficientForPlan=False, report=json.loads(failure['partial_json']))
        if scope[1] != ONBOARDING_SCOPE:
            result['failure']['matchesCurrentWebsite'] = bool(website) and failure['website'] == website \
                and (failure['partial_json'] is None
                     or json.loads(failure['partial_json']).get('source_url') == website)
    return result


def latest(con, scope):
    return _snapshot(_current_row(con, scope))


class ResearchAdoptionError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status


def adopt_onboarding(con, scope, website, research_id, expected_id):
    """Caller holds a write transaction and revalidates access before commit.

    Copy the original identity/time as well as the report: adoption is not a
    fresh website read. Identity remains scoped by owner and business. This
    makes an exact retry recoverable without a second receipt store.
    """
    source_row = _current_row(con, (scope[0], ONBOARDING_SCOPE))
    source = _snapshot(source_row)
    if source is None:
        raise ResearchAdoptionError('research_not_saved', 'No saved onboarding findings for this account.', 404)
    if source['researchId'] != research_id:
        raise ResearchAdoptionError('research_source_changed',
                                    'Onboarding findings changed. Review the saved findings before adopting them.')
    if (not website or source['website'] != website
            or source['report'].get('source_url') != website):
        raise ResearchAdoptionError('research_website_changed',
                                    'Choose findings from the current business website.')
    if source['report'].get('evidence', {}).get('status') == 'insufficient':
        raise ResearchAdoptionError('research_unavailable', 'These findings contain too little business information.')
    current = latest(con, scope)
    if current == source:
        return current, True
    if (current['researchId'] if current else None) != expected_id:
        raise ResearchAdoptionError('research_destination_changed',
                                    'Business findings changed. Recover and review them before replacing them.')
    # Reserving after all prior dispatches prevents their delayed completion
    # from replacing this explicit adoption. Future reads still supersede it.
    started = reserve(con, scope)
    _archive(con, scope, _current_row(con, scope))
    con.execute('''UPDATE growthrova_research_snapshots SET
        website=?,started=?,saved=?,id=?,report_json=?
        WHERE owner_id=? AND organisation_id=?''',
        (website, started, source['savedAt'], source['researchId'],
         source_row['report_json'], *scope))
    _archive(con, scope, _current_row(con, scope))
    return latest(con, scope), False
