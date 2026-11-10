"""Read-only business projection of immutable, receipt-backed form submissions."""
from contextlib import closing
import json
import re

from flask import jsonify, request

from business_marketing_drafts import MarketingDraftError
from business_marketing_offline import OfflineDocumentAccessError


def inbox_query():
    """One bounded, literal search contract for both private inboxes."""
    if (set(request.args) - {'before', 'query'}
            or any(len(request.args.getlist(key)) > 1 for key in ('before', 'query'))):
        raise MarketingDraftError('Use one search and the saved inbox page reference.')
    query = request.args.get('query', '')
    if len(query) > 160 or any(ord(char) < 32 or ord(char) == 127 for char in query):
        raise MarketingDraftError('Search with up to 160 characters on one line.')
    return query.strip()


def inbox_search(con, query):
    # SQLite lower() only folds ASCII. A connection-local pure function keeps
    # international names searchable without changing stored evidence or schema.
    con.create_function('growthrova_inbox_contains', 2,
                        lambda value, needle: int(needle.casefold() in (value or '').casefold()),
                        deterministic=True)
    fields = ["s.submission_id"] + [f"json_extract(s.data_json,'$.{key}')"
                                         for key in ('name', 'email', 'phone', 'message')]
    return (' AND (' + ' OR '.join('growthrova_inbox_contains('+field+',?)' for field in fields) + ')',
            [query] * len(fields)) if query else ('', [])


def register_business_capture_inbox(app, repo, root, revalidate):
    @app.get(root + '/intake/submissions')
    def growthrova_business_capture_inbox(organisation_id):
        scope = repo._scope(organisation_id)
        query = inbox_query()
        before = request.args.get('before', '')
        if before and not re.fullmatch(r'[a-f0-9]{32}:[a-f0-9]{32}', before):
            raise MarketingDraftError('Use the saved business inbox page reference.')
        # Both the config and authoritative document owner must match. This
        # excludes orphaned receipts and campaigns moved out of this scope.
        owned = ''' FROM growthrova_capture_configs c
            JOIN offline_document_owners o ON o.draft_id=c.document_id
            JOIN marketing_drafts d ON d.id=c.document_id
            JOIN growthrova_capture_receipts r ON r.token=c.token
            LEFT JOIN growthrova_capture_submissions s
              ON s.token=r.token AND s.submission_id=r.submission_id
            WHERE c.owner_id=? AND c.organisation_id=?
              AND o.owner_id=c.owner_id AND o.organisation_id=c.organisation_id'''
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            counts = con.execute('SELECT count(*) AS total, count(s.submission_id) AS retained' + owned, scope).fetchone()
            search, search_params = inbox_search(con, query)
            matching = con.execute('SELECT count(s.submission_id)' + owned + search,
                                   (*scope, *search_params)).fetchone()[0]
            clause, params = '', list(scope)
            if before:
                campaign, submission = before.split(':')
                anchor = con.execute('SELECT r.created' + owned +
                    ' AND c.document_id=? AND s.submission_id=?', (*scope, campaign, submission)).fetchone()
                if not anchor:
                    raise MarketingDraftError('Refresh this business inbox before opening another page.')
                clause = ''' AND (r.created<? OR (r.created=? AND
                    (c.document_id<? OR (c.document_id=? AND s.submission_id<?))))'''
                params.extend((anchor['created'], anchor['created'], campaign, campaign, submission))
            rows = con.execute('''SELECT s.*,r.created,c.document_id,
                    json_extract(d.document_json,'$.name') AS campaign_name''' + owned +
                ' AND s.submission_id IS NOT NULL' + search + clause +
                ' ORDER BY r.created DESC,c.document_id DESC,s.submission_id DESC LIMIT 31',
                [*scope, *search_params, *params[len(scope):]]).fetchall()
            items = [dict(id=row['submission_id'], campaignId=row['document_id'], campaignName=row['campaign_name'],
                          receivedAt=row['created'], settingsRevision=row['settings_revision'],
                          contact=json.loads(row['data_json']), form=json.loads(row['config_json']), outcome=row['outcome'])
                     for row in rows[:30]]
            result = dict(organisationId=organisation_id, totalReceived=counts['total'], retained=counts['retained'],
                          historicalWithoutContent=counts['total']-counts['retained'], query=query,
                          matchingRetained=matching, submissions=items,
                          nextBefore=items[-1]['campaignId']+':'+items[-1]['id'] if len(rows)>30 else None)
            error = revalidate() if revalidate else None
            if error is not None:
                return error
            if repo._scope(organisation_id) != scope:
                raise OfflineDocumentAccessError('Business access changed')
        return jsonify(result)
