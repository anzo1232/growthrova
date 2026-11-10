"""Dedicated opt-in discovery interface. No ambient vendor or credential lookup."""
from dataclasses import dataclass, field
from threading import Lock
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ProspectSearchConfig:
    # Adapter search(owner, organisation, query, limit=10) must enforce deadlines,
    # byte/commercial bounds and return {sourceUrl, results:[{url,label,snippet}]} (snippet <=200 chars).
    # It must never fetch candidate pages or infer contact permission.
    enabled: bool = False
    provider: str = ''
    search: object = field(default=None, repr=False)
    authorised: object = field(default=None, repr=False)


def register_prospect_search(app, repo, root, *, config=None, revalidate=None):
    from contextlib import closing
    from datetime import datetime, timezone
    from flask import jsonify, request
    from business_marketing_drafts import MarketingDraftError
    from business_marketing_offline import OfflineDocumentAccessError
    from business_website_analysis import external_page_references, validate_target
    config = config or ProspectSearchConfig()
    gate = Lock()  # One bounded discovery call per isolated process, no queue.

    def allowed(scope):
        try:
            return callable(config.authorised) and config.authorised(*scope) is True
        except Exception:
            return False

    @app.post(root + '/<ident>/prospect-search')
    def prospect_search(organisation_id, ident):
        scope = repo._scope(organisation_id)
        repo.read(organisation_id, ident)
        data = request.get_json(silent=True)
        if (request.content_length is None or request.content_length > 2048
                or not isinstance(data, dict) or set(data) != {'query'}
                or not isinstance(data['query'], str) or not 3 <= len(data['query'].strip()) <= 240
                or any(ord(c) < 32 for c in data['query'])):
            raise MarketingDraftError('Enter a search phrase of 3–240 characters.')
        query = data['query'].strip()
        if (not config.enabled or not callable(config.search) or not allowed(scope)
                or not isinstance(config.provider, str) or not 1 <= len(config.provider) <= 80):
            return jsonify(code='search_disconnected', error='Business search is not connected for this business. Use a directory page or add a researched prospect below.'), 409
        if not gate.acquire(blocking=False):
            return jsonify(code='search_busy', error='A business search is already running. Try again after it finishes.'), 429
        try:
            try:
                report = config.search(*scope, query, limit=10)
                if not isinstance(report, dict):
                    raise ValueError()
                source = report.get('sourceUrl')
                if not isinstance(source, str) or len(source) > 500:
                    raise ValueError()
                validate_target(source)
                rows = report.get('results')
                if not isinstance(rows, list) or len(rows) > 10:
                    raise ValueError()
                # Allow-list fields; do not return provider payloads or credentials.
                candidates = []
                seen = set()
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError()
                    links = external_page_references([row], source)
                    if not links:
                        continue
                    candidate = links[0]
                    host = urlsplit(candidate['url']).hostname.rstrip('.').lower()
                    if host in seen or len(candidate['url']) > 500:
                        continue
                    snippet = row.get('snippet', '')
                    if not isinstance(snippet, str) or len(snippet) > 200:
                        raise ValueError()
                    seen.add(host)
                    candidates.append(dict(candidate, snippet=snippet))
            except Exception:
                return jsonify(code='search_unavailable', error='Search could not be completed. Saved prospects are unchanged. You can try again or use a directory page.'), 502
            error = revalidate() if revalidate else None
            if error is not None:
                return error
            with closing(repo._connect()) as con:
                if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope) or not allowed(scope):
                    raise OfflineDocumentAccessError('Campaign or search access changed')
            return jsonify(provider=config.provider, query=query, sourceUrl=source,
                           observedOn=datetime.now(timezone.utc).date().isoformat(),
                           candidates=candidates, status='search_unconfirmed')
        finally:
            gate.release()
