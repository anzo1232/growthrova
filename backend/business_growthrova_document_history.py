"""Immutable saved document bodies for isolated authenticated campaign storage.

Historical content is inspection evidence, never current delivery authority.
Only the authoritative writer retains bodies, inside its existing transaction.
"""
from contextlib import closing
import json
import re

from flask import jsonify, request

import business_marketing_drafts as drafts
from business_marketing_offline import OfflineDocumentAccessError


def initialise(con):
    con.execute('''CREATE TABLE IF NOT EXISTS marketing_draft_versions(
        draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
        document_json TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
        PRIMARY KEY(draft_id,revision))''')


def retain_revision(con, old, current):
    # Preserve a legacy campaign's last known body at its next successful edit.
    # Older overwritten bodies cannot be reconstructed from save fingerprints.
    for row in (old, current):
        if row is None:
            continue
        values = (row['id'], row['revision'], row['document_json'], row['created'], row['updated'])
        existing = con.execute('SELECT draft_id,revision,document_json,created,updated '
            'FROM marketing_draft_versions WHERE draft_id=? AND revision=?', values[:2]).fetchone()
        if existing is not None:
            if tuple(existing) != values:
                raise drafts.MarketingDraftError('Saved history differs from the current campaign. '
                    'Your new edits were not saved.', 'history_conflict', 409)
        else:
            con.execute('INSERT INTO marketing_draft_versions VALUES(?,?,?,?,?)', values)


# Include the current body for legacy campaigns that have not been edited since
# installation. Reads never backfill, relabel or normalise historical documents.
VERSIONS = '''SELECT revision,document_json,created,updated FROM marketing_draft_versions WHERE draft_id=?
    UNION ALL SELECT revision,document_json,created,updated FROM marketing_drafts WHERE id=?
    AND NOT EXISTS (SELECT 1 FROM marketing_draft_versions v
                    WHERE v.draft_id=marketing_drafts.id AND v.revision=marketing_drafts.revision)'''


def read_version(con, ident, revision):
    return con.execute('SELECT * FROM ('+VERSIONS+') WHERE revision=?',
                       (ident, ident, revision)).fetchone()


def compare_sections(before, after):
    """Complete top-level sections; array order and absent vs null are meaningful.

    Do not normalise historical documents: doing so can discard old fields or
    reinterpret a past review using current rules. This is inspection only.
    """
    changes = []
    for field in sorted(before.keys() | after.keys()):
        old_present, new_present = field in before, field in after
        # Canonical JSON equality avoids Python equating booleans and numbers.
        if old_present == new_present and json.dumps(before.get(field), sort_keys=True) == \
                json.dumps(after.get(field), sort_keys=True):
            continue
        changes.append(dict(field=field, beforePresent=old_present, afterPresent=new_present,
                            before=before.get(field), after=after.get(field)))
    return changes


def register_history_routes(app, repo, root, *, revalidate):
    @app.get(root+'/<ident>/history/compare')
    def compare_document_history(organisation_id, ident):
        scope = repo._scope(organisation_id)
        drafts._id(ident)
        args = request.args
        if (set(args) != {'fromRevision', 'toRevision'}
                or any(len(args.getlist(key)) != 1
                       or not re.fullmatch(r'[1-9][0-9]{0,9}', args[key]) for key in args)):
            raise drafts.MarketingDraftError('Choose two exact saved revisions to compare.')
        revisions = [int(args[key]) for key in ('fromRevision', 'toRevision')]
        if any(revision >= 2147483647 for revision in revisions):
            raise drafts.MarketingDraftError('Choose two exact saved revisions to compare.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            if not repo._owned(con, ident, scope):
                raise OfflineDocumentAccessError('Document access denied')
            current = drafts.read_draft(con, ident)
            rows = [read_version(con, ident, revision) for revision in revisions]
            # Access is checked again even when one selected version is absent.
            result = None
            if all(row is not None for row in rows):
                changes = compare_sections(*(json.loads(row['document_json']) for row in rows))
                versions = [dict(revision=row['revision'], savedAt=row['updated']) for row in rows]
                result = dict(fromVersion=versions[0], toVersion=versions[1], changes=changes,
                              changedFields=[item['field'] for item in changes])
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(organisation_id) != scope:
            raise OfflineDocumentAccessError('Document access denied')
        if result is None:
            raise drafts.MarketingDraftError('A selected saved revision was not retained. '
                'Choose available versions from saved history.', 'history_not_retained', 404)
        return jsonify(id=ident, **result, scope='saved_history_comparison', saved=False,
            currentRevision=current['revision'], canPublish=False, canSpend=False,
            limitations='Complete changed sections from the selected saved versions, not current authority. '
                'Absent fields are marked separately from null values. Current revision is a read snapshot. '
                'No changes were applied. Inspect the current campaign before explicitly saving any '
                'replacement through the normal writer; historical reviews and permissions are not approval.')

    @app.get(root+'/<ident>/history')
    @app.get(root+'/<ident>/history/<int:revision>')
    def document_history(organisation_id, ident, revision=None):
        scope = repo._scope(organisation_id)
        drafts._id(ident)
        args = request.args
        if (revision is not None and (args or not 1 <= revision < 2147483647)) or (
                revision is None and (set(args) - {'limit', 'beforeRevision'}
                or any(len(args.getlist(key)) != 1 for key in args)
                or not re.fullmatch(r'(?:[1-9]|[1-4][0-9]|50)', args.get('limit', '20'))
                or ('beforeRevision' in args and
                    not re.fullmatch(r'[1-9][0-9]{0,9}', args['beforeRevision'])))):
            raise drafts.MarketingDraftError('Choose a saved revision or a history page of 1–50 versions.')
        before = int(args['beforeRevision']) if 'beforeRevision' in args else 2147483647
        if not 1 <= before <= 2147483647:
            raise drafts.MarketingDraftError('Use the saved history page cursor.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            if not repo._owned(con, ident, scope):
                raise OfflineDocumentAccessError('Document access denied')
            current = drafts.read_draft(con, ident)
            if revision is not None:
                row = read_version(con, ident, revision)
                result = dict(id=ident, revision=revision, historical=True, saved=True,
                    document=json.loads(row['document_json']), created=row['created'], updated=row['updated']) \
                    if row is not None else None
            else:
                limit = int(args.get('limit', '20'))
                rows = con.execute('SELECT * FROM ('+VERSIONS+') WHERE revision<? '
                    'ORDER BY revision DESC LIMIT ?', (ident, ident, before, limit+1)).fetchall()
                versions = []
                for row in rows[:limit]:
                    doc = json.loads(row['document_json'])
                    versions.append(dict(revision=row['revision'], savedAt=row['updated'],
                        name=doc['name'], business=doc['business'], goal=doc['goal']))
                result = dict(id=ident, versions=versions,
                    nextCursor=dict(beforeRevision=versions[-1]['revision']) if len(rows)>limit else None)
        # The private app refreshes bearer/business access after the database
        # snapshot; offline callers also recheck their authoritative callbacks.
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(organisation_id) != scope:
            raise OfflineDocumentAccessError('Document access denied')
        if result is None:
            raise drafts.MarketingDraftError('This saved revision was not retained. '
                'Versions overwritten before history was installed cannot be recovered.',
                'history_not_retained', 404)
        return jsonify(**result, scope='saved_history_snapshot', currentRevision=current['revision'],
            isCurrent=revision == current['revision'] if revision is not None else None,
            canPublish=False, canSpend=False,
            limitations='Retained saved versions only. Earlier overwritten versions may be unavailable. '
                'Historical reviews, permissions and delivery settings are not current authority. '
                'Inspect the current campaign before explicitly saving any replacement through the normal writer.')
