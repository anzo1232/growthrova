"""Offline authenticated document contract; deliberately has no HTTP registration.

Use a dedicated empty SQLite database and trusted current_user/load_org callbacks
with the same (value, error) contract as business_campaign_store_routes. Never
pass request claims as callback results. This is not hosted storage or JWT proof:
production integration still requires reviewed storage/RLS rules. No pilot import,
cloud client, credential lookup, network access or media authority exists here.
"""
import sqlite3
from contextlib import closing

import business_marketing_drafts as drafts


DOCUMENT_TABLES = {'marketing_drafts', 'marketing_draft_mutations', 'offline_document_owners'}
OPTIONAL_TABLES = {'growthrova_creative_references', 'growthrova_creative_results', 'growthrova_creative_result_history', 'marketing_draft_versions', 'growthrova_research_history', 'growthrova_research_failures', 'business_asset_catalog', 'business_asset_originals',
                'business_asset_intake_receipts',
                'business_asset_withdrawals',
                'business_campaign_asset_selections',
                'marketing_storage_project', 'growthrova_writing_requests', 'growthrova_research_snapshots',
                'growthrova_image_requests', 'growthrova_image_observations', 'growthrova_image_sources',
                'growthrova_image_selections', 'growthrova_image_batches', 'growthrova_static_observations',
                'growthrova_social_drafts', 'growthrova_social_jobs', 'growthrova_ad_agent_runs',
                'growthrova_social_observations', 'growthrova_social_observation_receipts', 'growthrova_social_analytics_reads',
                'growthrova_leads', 'growthrova_lead_events', 'growthrova_followup_jobs', 'growthrova_organic_jobs',
                'growthrova_provider_lead_receipts', 'growthrova_payment_receipts', 'growthrova_payment_checks', 'growthrova_capture_configs', 'growthrova_capture_receipts', 'growthrova_capture_submissions', 'growthrova_paid_jobs', 'growthrova_paid_actions',
                'growthrova_paid_setup', 'growthrova_paid_setup_receipts',
                'growthrova_measurement_reports', 'growthrova_measurement_receipts',
                'growthrova_measurement_sources', 'growthrova_measurement_jobs',
                'growthrova_meta_connections', 'growthrova_meta_grants',
                'growthrova_search_connections', 'growthrova_search_grants', 'growthrova_search_refreshes',
                'growthrova_search_reads', 'growthrova_google_connections', 'growthrova_google_grants', 'growthrova_google_refreshes',
                'growthrova_measurement_schedules', 'growthrova_measurement_schedule_receipts',
                'growthrova_billing_checkouts', 'growthrova_billing_grants', 'growthrova_billing_events',
                'growthrova_billing_cancellations', 'growthrova_billing_replacements',
                'growthrova_sender_events', 'growthrova_sender_requests', 'growthrova_sender_receipts', 'growthrova_inbound_evidence'}

class OfflineDocumentAccessError(PermissionError):
    pass


class OfflineMarketingDocuments:
    def __init__(self, path, current_user, load_org, *, project_origin=None):
        self.path = path
        self.current_user = current_user
        self.load_org = load_org
        with closing(self._connect()) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and (not DOCUMENT_TABLES.issubset(tables) or tables - DOCUMENT_TABLES - OPTIONAL_TABLES):
                raise OfflineDocumentAccessError('A dedicated offline document database is required')
            if 'marketing_storage_project' in tables:
                binding = con.execute('SELECT origin FROM marketing_storage_project WHERE singleton=1').fetchone()
                if not project_origin or not binding or binding[0] != project_origin:
                    raise OfflineDocumentAccessError('Document database belongs to a different authentication project')
            elif project_origin:
                if tables:
                    raise OfflineDocumentAccessError('A new isolated document database is required; existing offline documents cannot be adopted')
                con.execute('CREATE TABLE marketing_storage_project(singleton INTEGER PRIMARY KEY CHECK(singleton=1), origin TEXT NOT NULL)')
                con.execute('INSERT INTO marketing_storage_project VALUES(1,?)', (project_origin,))
            drafts.initialise(con)
            from business_growthrova_document_history import initialise
            initialise(con)
            con.execute('''CREATE TABLE IF NOT EXISTS offline_document_owners(
                draft_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                organisation_id TEXT NOT NULL)''')
            con.commit()

    def _connect(self):
        con = sqlite3.connect(self.path, timeout=5)
        con.row_factory = sqlite3.Row
        return con

    def _scope(self, organisation_id):
        user, error = self.current_user()
        if error is not None or not isinstance(user, dict) or not user.get('id'):
            raise OfflineDocumentAccessError('Authentication required')
        org, error = self.load_org(organisation_id, user)
        if (error is not None or not isinstance(org, dict) or not org.get('id')
                or org['id'] != organisation_id):
            raise OfflineDocumentAccessError('Organisation access denied')
        if any(not isinstance(v, str) or not v.strip() for v in (user['id'], org['id'])):
            raise OfflineDocumentAccessError('Verified identity required')
        return user['id'], org['id']

    @staticmethod
    def _owned(con, ident, scope):
        row = con.execute('SELECT owner_id,organisation_id FROM offline_document_owners WHERE draft_id=?',
                          (ident,)).fetchone()
        return row is not None and tuple(row) == scope

    @staticmethod
    def _result(saved):
        return {**saved, 'storage': 'offline_authenticated_contract',
                'hostedStorageVerified': False}

    def save(self, organisation_id, payload, *, _validate_write=None):
        scope = self._scope(organisation_id)
        def authorize(con, ident):
            # Optional server-owned precondition runs under the writer's lock,
            # including exact-operation replay. Never supplied by request JSON.
            if _validate_write is not None:
                _validate_write(con, scope)
            row = con.execute('SELECT 1 FROM offline_document_owners WHERE draft_id=?', (ident,)).fetchone()
            if row:
                if not self._owned(con, ident, scope):
                    raise OfflineDocumentAccessError('Document access denied')
            else:
                # Never adopt a pre-existing unowned pilot document.
                if con.execute('SELECT 1 FROM marketing_drafts WHERE id=?', (ident,)).fetchone():
                    raise OfflineDocumentAccessError('Document access denied')
                con.execute('INSERT INTO offline_document_owners VALUES(?,?,?)', (ident, *scope))
        with closing(self._connect()) as con:
            try:
                from business_growthrova_document_history import retain_revision
                return self._result(drafts.save_draft(con, payload, _authorize_write=authorize,
                                                    _retain_revision=retain_revision))
            finally:
                # Includes replay returns and every validation/ownership failure.
                con.rollback()

    def read(self, organisation_id, ident):
        scope = self._scope(organisation_id)
        drafts._id(ident)
        with closing(self._connect()) as con:
            if not self._owned(con, ident, scope):
                raise OfflineDocumentAccessError('Document access denied')
            return self._result(drafts.read_draft(con, ident))

    def list(self, organisation_id):
        scope = self._scope(organisation_id)
        with closing(self._connect()) as con:
            rows = con.execute('''SELECT d.id FROM marketing_drafts d
                JOIN offline_document_owners o ON o.draft_id=d.id
                WHERE o.owner_id=? AND o.organisation_id=? ORDER BY d.updated DESC LIMIT 100''', scope)
            return [self._result(drafts.read_draft(con, row['id'])) for row in rows]

    def save_outcome(self, organisation_id, ident, mutation_id):
        """Read a receipt and current version from one snapshot, without replay.

        Absence is deliberately inconclusive: a writer may still be running.
        Foreign IDs have the same result as absent IDs in the selected scope.
        Receipts identify revisions; retained bodies may be retrieved separately.
        """
        scope = self._scope(organisation_id)
        drafts._id(ident)
        drafts._id(mutation_id)
        with closing(self._connect()) as con:
            con.execute('BEGIN')
            current = None
            receipt = None
            if self._owned(con, ident, scope):
                current = self._result(drafts.read_draft(con, ident))
                receipt = con.execute('''SELECT result_revision FROM marketing_draft_mutations
                    WHERE draft_id=? AND mutation_id=?''', (ident, mutation_id)).fetchone()
            if self._scope(organisation_id) != scope:
                raise OfflineDocumentAccessError('Document access denied')
            revision = receipt['result_revision'] if receipt else None
            available = bool(receipt and (current['revision'] == revision or con.execute(
                'SELECT 1 FROM marketing_draft_versions WHERE draft_id=? AND revision=?',
                (ident, revision)).fetchone()))
            return dict(id=ident, mutationId=mutation_id,
                status='recorded' if receipt else 'not_recorded',
                resultRevision=revision,
                superseded=(current['revision'] != revision) if receipt else None,
                currentCampaign=current,
                historicalDocumentAvailable=available,
                historicalRevision=revision if available else None,
                retrySafety='not_determined',
                interpretation=('The save was recorded. Current campaign content may include later edits.'
                    if receipt else 'No matching save receipt was visible in this business at the time of '
                    'the read. A save may still be running; this does not prove failure or permit a new retry.'))


def create_offline_document_app(path, *, current_user, load_org):
    """Isolated offline HTTP contract, never registered on the Business app.

    Callbacks are trusted server dependencies, not values from headers or JSON.
    This factory does not validate JWTs or provide a runnable server. Use its
    in-process test client for offline integration; hosted integration needs a
    separate storage/security review. The pilot header has no authority here.
    """
    from flask import Flask
    repo = OfflineMarketingDocuments(path, current_user, load_org)
    app = Flask(__name__, static_folder=None)
    register_document_routes(app, repo, '/offline/organisations/<organisation_id>/marketing-documents')
    return app


def register_document_routes(app, repo, root, *, revalidate=None):
    """Shared revisioned document/media routes; caller owns authentication policy."""
    from flask import jsonify, request
    from werkzeug.exceptions import HTTPException

    app.config['MAX_CONTENT_LENGTH'] = 300000

    @app.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.errorhandler(OfflineDocumentAccessError)
    def denied(exc):
        # Do not disclose whether a foreign document or organisation exists.
        return jsonify(code='access_denied', error='Document access denied'), 403

    @app.errorhandler(drafts.MarketingDraftError)
    def invalid(exc):
        return jsonify(code=exc.code, error=str(exc)), exc.status

    @app.errorhandler(sqlite3.Error)
    def unavailable(exc):
        return jsonify(code='storage_unavailable',
                       error='Campaign storage unavailable. Check the saved version before retrying.'), 503

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(code='invalid_request', error=exc.name), exc.code

    # Organisation is only a selector. The repository verifies membership and
    # immutable user/org ownership on every operation, including retry receipts.
    @app.get(root)
    def list_documents(organisation_id):
        return jsonify(documents=repo.list(organisation_id),
                       storage='offline_authenticated_contract', hostedStorageVerified=False)

    @app.get(root+'/<ident>')
    def read_document(organisation_id, ident):
        return jsonify(repo.read(organisation_id, ident))

    @app.get(root+'/<ident>/saves/<mutation_id>')
    def recover_document_save(organisation_id, ident, mutation_id):
        scope = repo._scope(organisation_id)
        result = repo.save_outcome(organisation_id, ident, mutation_id)
        # Preview callbacks cache the initial verified identity. Refresh remote
        # bearer/RLS access after the read before disclosing any saved content.
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(organisation_id) != scope:
            raise OfflineDocumentAccessError('Document access denied')
        return jsonify(result)

    @app.post(root)
    def save_document(organisation_id):
        # Authenticate even malformed input, before document validation or DB reads.
        repo._scope(organisation_id)
        if request.content_length and request.content_length > 300000:
            return jsonify(code='invalid_request', error='Request Entity Too Large'), 413
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise drafts.MarketingDraftError('Campaign document required')
        return jsonify(repo.save(organisation_id, payload))

    from business_source_routes import register_offline_photo_routes
    register_offline_photo_routes(app, repo, root=root+'/<ident>/media')
    from business_growthrova_document_history import register_history_routes
    register_history_routes(app, repo, root, revalidate=revalidate)
