"""Standalone isolated preview. No creator app imports or ambient credentials.

Supabase Auth verifies the bearer; the same project's caller-JWT RLS verifies
organisation ownership on EVERY request. Private SQLite reuses the existing
revision/receipt/media stores. Single process + persistent local volume only.
This implementation is not evidence of provisioned/deployed isolation.
"""
from pathlib import Path
from contextlib import closing
import sqlite3
from urllib.parse import urlsplit
import re
import requests
from flask import Flask, g, jsonify, request
from business_auth_config import business_auth_projects_match, business_public_anon_key
from business_marketing_offline import OfflineMarketingDocuments, register_document_routes
from business_website_analysis import extract_website, expand_business_audit, WebsiteSafetyError
import business_growthrova_research as research_snapshots

UUID = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}', re.I)
ROOT = '/api/growthrova/organisations/<organisation_id>/marketing-documents'


def create_growthrova_preview(*, database_path, project_url, auth_url, anon_key,
                             http=None, writer_config=None, writer_http=None,
                             image_config=None, image_http=None,
                             social_account_config=None, social_account_http=None,
                             social_delivery_config=None, social_analytics_config=None, google_connection_config=None, search_connection_config=None, meta_connection_config=None, google_lead_config=None, meta_lead_config=None, capture_hosting_enabled=False, followup_config=None, sender_event_config=None, paid_delivery_config=None, measurement_config=None, search_config=None, care_config=None, prospect_search_config=None, organic_delivery_config=None, generation_access_config=None, test_billing_config=None, generation_credit_config=None, payment_config=None, payment_event_config=None):
    """Explicit operator config only. `http` is a transport seam, never identity.

    Provision a NEW isolated Supabase project and private empty directory first.
    Do not point this factory at a creator project or existing pilot database.
    The anon key is public; service-role credentials must never be supplied.
    """
    if (not business_auth_projects_match(project_url, auth_url, anon_key) or
            not business_public_anon_key(anon_key)):
        raise ValueError('Growthrova auth and data must use one isolated Supabase project')
    path = Path(database_path)
    if not path.is_absolute() or not path.parent.is_dir() or path.is_symlink():
        raise ValueError('Absolute private persistent database path required')
    if path.parent.stat().st_mode & 0o077 or (path.exists() and path.stat().st_mode & 0o077):
        raise ValueError('Database directory and file must be private to the server user')
    # Never follow an existing symlink; create new files with private permissions.
    import os
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    app = Flask(__name__, static_folder=None)
    base = 'https://' + urlsplit(project_url.strip()).hostname.lower()

    def remote(path, *, params=None):
        try:
            options = dict(params=params, headers={
                'apikey': anon_key, 'Authorization': 'Bearer ' + g.bearer,
                'Accept': 'application/json'}, timeout=7, allow_redirects=False)
            if http is None:
                # Requests otherwise consults netrc and ambient proxies/CA paths;
                # netrc can even replace our explicit caller Authorization header.
                # A fresh session also prevents cookies crossing auth/org requests.
                with requests.Session() as transport:
                    transport.trust_env = False
                    response = transport.get(base + path, **options)
            else:
                response = http.get(base + path, **options)
            if response.status_code in (401, 403):
                return None, (jsonify(code='access_denied', error='Sign in again or select an accessible business.'), 403)
            if response.status_code != 200:
                raise ValueError('Unavailable')
            return response.json(), None
        except (requests.RequestException, ValueError, TypeError):
            return None, (jsonify(code='auth_storage_unavailable', error='Session or business storage could not be checked. Retry without resubmitting.'), 503)

    def current_user():
        return getattr(g, 'growthrova_user', None), None

    def load_org(ident, user):
        if not isinstance(ident, str) or not UUID.fullmatch(ident):
            return None, 'denied'
        if getattr(g, 'growthrova_org', {}).get('id') == ident:
            return g.growthrova_org, None
        rows, error = remote('/rest/v1/business_organisations', params={
            'id': 'eq.' + ident, 'owner_id': 'eq.' + user['id'],
            'select': 'id,owner_id,name,website,primary_goal', 'limit': '1'})
        if error is not None:
            return None, error
        if (not isinstance(rows, list) or len(rows) != 1 or
                not isinstance(rows[0], dict) or rows[0].get('id') != ident or
                rows[0].get('owner_id') != user['id']):
            return None, (jsonify(code='access_denied', error='Business access denied.'), 403)
        g.growthrova_org = rows[0]
        return rows[0], None

    @app.before_request
    def verify_scope():
        # Exact opt-in public endpoints only; private routes retain bearer auth.
        from business_growthrova_meta_leads import ENDPOINT as META_LEAD_ENDPOINT
        if meta_lead_config is not None and meta_lead_config.enabled is True and request.endpoint == META_LEAD_ENDPOINT:
            return None
        from business_growthrova_google_leads import ENDPOINT as GOOGLE_LEAD_ENDPOINT
        if google_lead_config is not None and google_lead_config.enabled is True and request.endpoint == GOOGLE_LEAD_ENDPOINT:
            return None
        from business_growthrova_sender_events import ENDPOINT
        if sender_event_config is not None and sender_event_config.enabled is True and request.endpoint == ENDPOINT:
            return None
        from business_growthrova_capture import PUBLIC_ENDPOINTS
        if capture_hosting_enabled is True and request.endpoint in PUBLIC_ENDPOINTS:
            return None
        from business_growthrova_billing import ENDPOINT as BILLING_ENDPOINT
        if test_billing_config is not None and test_billing_config.enabled is True and request.endpoint == BILLING_ENDPOINT:
            return None
        from business_growthrova_payment_events import ENDPOINT as PAYMENT_EVENT_ENDPOINT
        if payment_event_config is not None and payment_event_config.enabled is True and request.endpoint == PAYMENT_EVENT_ENDPOINT:
            return None
        # No cookies/pilot header/body identity, CORS grant or redirect login.
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer ') or not re.fullmatch(r'[A-Za-z0-9._~-]{1,8192}', auth[7:]):
            return jsonify(code='auth_required', error='Sign in to Growthrova to continue.'), 401
        g.bearer = auth[7:]
        user, error = remote('/auth/v1/user')
        if error is not None:
            return error
        if not isinstance(user, dict) or not UUID.fullmatch(str(user.get('id', ''))):
            return jsonify(code='auth_required', error='Your session could not be verified.'), 401
        g.growthrova_user = {'id': user['id']}
        ident = (request.view_args or {}).get('organisation_id')
        if ident:
            _, error = load_org(ident, g.growthrova_user)
            if error is not None:
                if isinstance(error, tuple):
                    return error
                return jsonify(code='access_denied', error='Business access denied.'), 403

    repo = OfflineMarketingDocuments(str(path), current_user, load_org, project_origin=base)
    with closing(repo._connect()) as con:
        research_snapshots.initialise(con)
        con.commit()
    from business_growthrova_writer import WriterConfig, register_writer_routes
    def revalidate_scope():
        g.pop('growthrova_org', None)
        return verify_scope()

    register_document_routes(app, repo, ROOT, revalidate=revalidate_scope)
    from business_growthrova_plans import register_plan_routes
    register_plan_routes(app, repo, ROOT, revalidate=revalidate_scope)

    from business_growthrova_billing import register_test_billing
    if test_billing_config is not None and test_billing_config.enabled and generation_access_config is not None:
        raise ValueError('Choose subscription coverage or explicit grants, never both')
    subscription_access = register_test_billing(app, repo, ROOT, config=test_billing_config, revalidate=revalidate_scope)
    from business_growthrova_access import register_generation_access
    generation_access = register_generation_access(app, repo, ROOT, config=subscription_access or generation_access_config, credit_config=generation_credit_config, revalidate=revalidate_scope)

    from business_growthrova_organic_delivery import register_organic_delivery_routes
    register_organic_delivery_routes(app, repo, ROOT, config=organic_delivery_config, revalidate=revalidate_scope)
    from business_growthrova_leads import register_lead_routes
    register_lead_routes(app, repo, ROOT, revalidate=revalidate_scope)
    from business_growthrova_payments import register_payment_routes
    register_payment_routes(app, repo, ROOT, config=payment_config, revalidate=revalidate_scope)
    from business_growthrova_payment_events import register_payment_events
    from business_growthrova_payments import PaymentConfig
    register_payment_events(app, repo, payment_config or PaymentConfig(), payment_event_config)
    from business_growthrova_provider_leads import register_provider_lead_routes
    register_provider_lead_routes(app, repo, ROOT, revalidate=revalidate_scope)
    from business_growthrova_google_leads import register_google_lead_events
    register_google_lead_events(app, repo, google_lead_config)
    from business_growthrova_meta_leads import register_meta_lead_events
    register_meta_lead_events(app, repo, meta_lead_config)
    from business_growthrova_prospects import register_prospect_routes
    register_prospect_routes(app, repo, ROOT, revalidate=revalidate_scope)
    from business_growthrova_prospect_search import register_prospect_search
    register_prospect_search(app, repo, ROOT, config=prospect_search_config, revalidate=revalidate_scope)
    from business_growthrova_care_worker import CarePreparation
    app.extensions['growthrova_care_preparation'] = CarePreparation(repo, care_config)

    from business_growthrova_measurement import register_measurement_routes
    register_measurement_routes(app, repo, ROOT, revalidate=revalidate_scope, config=measurement_config)

    from business_growthrova_followup import register_followup_routes
    followup = register_followup_routes(app, repo, ROOT, config=followup_config, revalidate=revalidate_scope)
    from business_growthrova_sender_events import register_sender_events
    register_sender_events(app, followup, sender_event_config)

    from business_growthrova_google_connection import register_google_connection_routes
    register_google_connection_routes(app, repo, config=google_connection_config, revalidate=revalidate_scope)

    from business_growthrova_search_connection import register_search_connection_routes
    register_search_connection_routes(app, repo, config=search_connection_config, revalidate=revalidate_scope)

    from business_growthrova_search import register_search_routes
    from business_growthrova_search_reads import SearchPropertyReadConfig, SearchGrantAdapter
    search_service = app.extensions['growthrova_search_connection']
    if search_service.config.property_reads is not None:
        if search_config is not None or not isinstance(search_service.config.property_reads, SearchPropertyReadConfig):
            raise ValueError('Configure one explicit Search Console read source')
        search_config = SearchGrantAdapter(search_service, search_service.config.property_reads).search_config()
    register_search_routes(app, repo, ROOT, revalidate=revalidate_scope, config=search_config)

    from business_growthrova_meta_connection import register_meta_connection_routes
    register_meta_connection_routes(app, repo, config=meta_connection_config, revalidate=revalidate_scope)

    from business_growthrova_paid_delivery import register_paid_delivery_routes
    from business_growthrova_google_reads import GoogleAccountReadConfig, GoogleGrantDiscovery
    google_service = app.extensions['growthrova_google_connection']
    if isinstance(google_service.config.account_reads, GoogleAccountReadConfig):
        from dataclasses import replace
        from business_growthrova_paid_delivery import PaidDeliveryConfig
        paid_delivery_config = paid_delivery_config or PaidDeliveryConfig()
        paid_delivery_config = replace(paid_delivery_config, discovery=GoogleGrantDiscovery(
            google_service, google_service.config.account_reads, paid_delivery_config.discovery))
    from business_growthrova_meta_reads import MetaAccountReadConfig, MetaGrantDiscovery
    meta_service = app.extensions['growthrova_meta_connection']
    if isinstance(meta_service.config.account_reads, MetaAccountReadConfig):
        from dataclasses import replace
        from business_growthrova_paid_delivery import PaidDeliveryConfig
        paid_delivery_config = paid_delivery_config or PaidDeliveryConfig()
        paid_delivery_config = replace(paid_delivery_config, discovery=MetaGrantDiscovery(
            meta_service, meta_service.config.account_reads, paid_delivery_config.discovery))
    register_paid_delivery_routes(app, repo, ROOT, config=paid_delivery_config, revalidate=revalidate_scope)

    from business_growthrova_capture import register_capture_routes
    register_capture_routes(app, repo, ROOT, hosting_enabled=capture_hosting_enabled is True,
                            revalidate=revalidate_scope)

    from business_growthrova_creative_memory import register_routes as register_creative_memory
    register_creative_memory(app, repo, ROOT, revalidate=revalidate_scope)

    writer_services = register_writer_routes(app, repo, ROOT, writer_config or WriterConfig(),
                           http=writer_http, revalidate=revalidate_scope, access_check=generation_access.admit)
    from business_growthrova_images import ImageConfig, register_image_routes
    from business_social_accounts import lookup_social_accounts
    image_services = register_image_routes(app, repo, ROOT, image_config or ImageConfig(),
                          http=image_http, revalidate=revalidate_scope, access_check=generation_access.admit,
                          social_accounts=lambda org: lookup_social_accounts(social_account_config, org, social_account_http))

    from business_social_delivery import register_social_delivery_routes
    register_social_delivery_routes(app, repo, ROOT, config=social_delivery_config, revalidate=revalidate_scope)
    from business_growthrova_social_analytics import register_social_analytics_routes
    register_social_analytics_routes(app, repo, ROOT, config=social_analytics_config, revalidate=revalidate_scope)

    from business_growthrova_ad_agent import register_ad_agent
    register_ad_agent(app, repo, ROOT, writer_config or WriterConfig(), image_config or ImageConfig(),
                      writer_services, image_services)

    from business_social_accounts import register_social_account_routes
    register_social_account_routes(app, repo, config=social_account_config,
                                   http=social_account_http, revalidate=revalidate_scope)

    def validate_research_owner(owner):
        error = revalidate_scope()
        if error is not None:
            return error
        if g.growthrova_user['id'] != owner:
            return jsonify(code='auth_required', error='Your session changed. Sign in again.'), 401
        return None

    @app.get('/api/growthrova/website-preview/status')
    @app.get('/api/growthrova/organisations/<organisation_id>/research/status')
    def research_attempt_status(organisation_id=None):
        if (set(request.args) - {'includePartial'}
                or len(request.args.getlist('includePartial')) > 1
                or request.args.get('includePartial', 'false') not in ('true', 'false')):
            return jsonify(code='invalid_request', error=
                'Choose whether to include limited website findings in this account and business.'), 400
        options = {'include_partial': True} if request.args.get('includePartial') == 'true' else {}
        owner = g.growthrova_user['id']
        website = g.growthrova_org.get('website') if organisation_id else None
        scope = (owner, organisation_id or research_snapshots.ONBOARDING_SCOPE)
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN')
                result = research_snapshots.attempt_status(con, scope, website, **options)
            error = (validate_research_scope(owner, website) if organisation_id
                     else validate_research_owner(owner))
            if error is not None:
                return error
            with closing(repo._connect()) as con:
                con.execute('BEGIN')
                if research_snapshots.attempt_status(con, scope, website, **options) != result:
                    return jsonify(code='research_status_changed', error='Website findings changed. Reload their status.'), 409
            recovery_path = (f'/api/growthrova/organisations/{organisation_id}/research'
                             if organisation_id else '/api/growthrova/website-preview')
            if result.get('failure', {}).get('partialFindingsAvailable'):
                result['failure']['partialRecoveryPath'] = recovery_path + '/status?includePartial=true'
            return jsonify(**result, executionState='completed' if result['state'] == 'failed' else 'unknown',
                recoveryPath=recovery_path,
                message=('This website read failed. Earlier saved findings are preserved. Review the failure '
                    'and any limited evidence before choosing another read. Limited evidence is unconfirmed '
                    'and cannot create a plan automatically. Status does not retry it.'
                    if result['state'] == 'failed' else
                    'Recover saved findings before starting another website read. An unresolved attempt '
                    'may still be running, may have failed or may have been interrupted. Status does not retry it.'))
        except sqlite3.Error:
            return jsonify(code='research_storage_unavailable', error='Website read status could not be recovered. Retry status without starting another read.'), 503

    def record_research_failure(scope, started, website, kind, validate, *, partial=None):
        """Retain a bounded receipt/limited report without replacing earlier findings."""
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                research_snapshots.retain_failure(con, scope, started, website, kind,
                    **({'partial': partial} if partial is not None else {}))
                error = validate()
                if error is not None:
                    return error  # Roll back on changed access or business context.
                con.commit()
        except (sqlite3.Error, ValueError):
            return jsonify(code='research_storage_unavailable', error=
                'The website read failed and its recovery status could not be saved. '
                'Earlier findings are preserved. Recover saved findings before another read.'), 503
        return None

    @app.get('/api/growthrova/website-preview')
    def recover_website_preview():
        owner = g.growthrova_user['id']
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN')
                snapshot = research_snapshots.latest(con, (owner, research_snapshots.ONBOARDING_SCOPE))
                error = validate_research_owner(owner)
                if error is not None:
                    return error
                if snapshot is None:
                    return jsonify(code='research_not_saved',
                        error='No saved onboarding findings yet. Read your website to prepare them.'), 404
                return jsonify(snapshot)
        except sqlite3.Error:
            return jsonify(code='research_storage_unavailable',
                error='Saved website findings could not be read. Retry recovery without reading the website again.'), 503

    @app.post('/api/growthrova/website-preview')
    def website_preview():
        # Research before an organisation exists. Identity still comes exclusively
        # from the verified bearer; the safe extractor owns DNS/redirect limits.
        if request.content_length is None or request.content_length > 2048:
            return jsonify(code='invalid_request', error='Supply one public HTTPS website.'), 400
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'website'}
                or not isinstance(data['website'], str) or len(data['website']) > 500):
            return jsonify(code='invalid_request', error='Supply one public HTTPS website.'), 400
        owner = g.growthrova_user['id']
        scope = (owner, research_snapshots.ONBOARDING_SCOPE)
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                started = research_snapshots.reserve(con, scope)
                con.commit()
        except sqlite3.Error:
            return jsonify(code='research_storage_unavailable',
                error='Website research could not be prepared for recovery. Retry; no website read was started.'), 503
        failure = None
        try:
            report = expand_business_audit(extract_website(data['website']), reader=extract_website)
        except WebsiteSafetyError as exc:
            failure = str(exc)
        # A failed read can be slow too. Validate the session before returning
        # any research outcome, just as for saved-business research below.
        error = validate_research_owner(owner)
        if error is not None:
            return error
        kind = ('read_unavailable' if failure is not None else
                'insufficient_evidence' if report.get('evidence', {}).get('status') == 'insufficient' else None)
        if kind is not None:
            error = record_research_failure(scope, started, data['website'], kind,
                lambda: validate_research_owner(owner),
                partial=report if kind == 'insufficient_evidence' else None)
            if error is not None:
                return error
        if failure is not None:
            return jsonify(code='research_unavailable', error=failure), 400
        if report.get('evidence', {}).get('status') == 'insufficient':
            return jsonify(code='research_unavailable', error='The website returned too little readable business information. Retry or create the business with details you supply.'), 400
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                retained = research_snapshots.retain(con, scope, data['website'], started, report)
                error = validate_research_owner(owner)
                if error is not None:
                    return error  # Closing the connection rolls back tentative findings.
                if not retained:
                    return jsonify(code='research_superseded', error='Newer findings were saved. Recover them before preparing a plan.'), 409
                con.commit()
        except sqlite3.Error:
            return jsonify(code='research_storage_unavailable',
                error='Website findings could not be saved. Try recovering saved findings before reading the website again.'), 503
        # No placeholder organisation, saved campaign or confirmed facts are
        # created by this read. The owner reviews before the normal private save.
        return jsonify(report)

    def validate_research_scope(owner, website):
        error = revalidate_scope()
        if error is not None:
            return error
        if g.growthrova_user['id'] != owner:
            return jsonify(code='auth_required', error='Your session changed. Sign in again.'), 401
        if g.growthrova_org.get('website') != website:
            return jsonify(code='research_website_changed',
                error='Your saved business website changed during research. Existing work is preserved. Retry to read the current website.'), 409
        return None

    from business_growthrova_research_history import register_research_history
    register_research_history(app, repo, validate_owner=validate_research_owner,
                              validate_business=validate_research_scope)

    @app.get('/api/growthrova/organisations/<organisation_id>/research')
    def recover_research(organisation_id):
        args = request.args
        if (set(args) - {'includeHistorical'}
                or len(args.getlist('includeHistorical')) > 1
                or args.get('includeHistorical', 'false') not in ('true', 'false')):
            return jsonify(code='invalid_request', error=
                'Choose whether to include historical website findings.'), 400
        include_historical = args.get('includeHistorical') == 'true'
        owner, website = g.growthrova_user['id'], g.growthrova_org.get('website')
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN')
                snapshot = research_snapshots.latest(con, (owner, organisation_id))
                error = validate_research_scope(owner, website)
                if error is not None:
                    return error
                if snapshot is None:
                    return jsonify(code='research_not_saved',
                        error='No saved website findings yet. Read your website to prepare them.'), 404
                requested_matches = bool(website) and snapshot['website'] == website
                extracted_matches = bool(website) and snapshot['report'].get('source_url') == website
                matches = requested_matches and extracted_matches
                if not matches and not include_historical:
                    return jsonify(code='research_website_changed',
                        error='Saved findings do not match your current website. Include historical findings '
                            'to inspect them before explicitly replacing them, or read your current website.'), 409
                if include_historical:
                    # Inspection preserves the original snapshot identity and
                    # provenance; it is never adoption or fact confirmation.
                    snapshot['websiteReview'] = dict(currentWebsite=website,
                        requestedWebsiteMatches=requested_matches,
                        extractedWebsiteMatches=extracted_matches,
                        matchesCurrentWebsite=matches,
                        message='Unconfirmed findings from the current website.' if matches else
                            'Historical or different-site findings. Inspect only; select current-site '
                            'findings before preparing a plan. Use this research ID as the expected '
                            'destination when explicitly replacing these findings.')
                return jsonify(snapshot)
        except sqlite3.Error:
            return jsonify(code='research_storage_unavailable',
                error='Saved website findings could not be read. Retry recovery without reading the website again.'), 503

    @app.post('/api/growthrova/organisations/<organisation_id>/research/adopt-onboarding')
    def adopt_onboarding_research(organisation_id):
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'researchId', 'expectedResearchId'}
                or not isinstance(data.get('researchId'), str)
                or not re.fullmatch(r'[a-f0-9]{32}', data['researchId'])
                or (data['expectedResearchId'] is not None and
                    (not isinstance(data['expectedResearchId'], str)
                     or not re.fullmatch(r'[a-f0-9]{32}', data['expectedResearchId'])))):
            return jsonify(code='invalid_request', error=
                'Select saved onboarding findings and the expected business findings, or null for an empty business.'), 400
        owner, website = g.growthrova_user['id'], g.growthrova_org.get('website')
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                snapshot, replayed = research_snapshots.adopt_onboarding(
                    con, (owner, organisation_id), website,
                    data['researchId'], data['expectedResearchId'])
                error = validate_research_scope(owner, website)
                if error is not None:
                    return error  # Uncommitted adoption rolls back on close.
                con.commit()
            return jsonify(**snapshot, replayed=replayed)
        except research_snapshots.ResearchAdoptionError as exc:
            error = validate_research_scope(owner, website)
            if error is not None:
                return error
            return jsonify(code=exc.code, error=exc.message), exc.status
        except sqlite3.Error:
            return jsonify(code='research_storage_unavailable', error=
                'Findings could not be adopted. Recover saved business findings before retrying.'), 503

    @app.post('/api/growthrova/organisations/<organisation_id>/research')
    def research(organisation_id):
        data = request.get_json(silent=True)
        # Website is selected from the RLS-authorised org, not a hidden request selector.
        if not isinstance(data, dict) or data:
            return jsonify(code='invalid_request', error='Research uses your saved business website.'), 400
        owner = g.growthrova_user['id']
        website = g.growthrova_org.get('website')
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                started = research_snapshots.reserve(con, (owner, organisation_id))
                con.commit()
        except sqlite3.Error:
            return jsonify(code='research_storage_unavailable',
                error='Website research could not be prepared for recovery. Retry; no website read was started.'), 503
        failure = None
        try:
            report = expand_business_audit(extract_website(website), reader=extract_website)
        except WebsiteSafetyError as exc:
            failure = str(exc)
        # Extraction/enrichment can outlast access or website changes. Recheck
        # even failed/insufficient reads before disclosing any research details.
        error = validate_research_scope(owner, website)
        if error is not None:
            return error
        kind = ('read_unavailable' if failure is not None else
                'insufficient_evidence' if report.get('evidence', {}).get('status') == 'insufficient' else None)
        if kind is not None:
            error = record_research_failure((owner, organisation_id), started, website, kind,
                lambda: validate_research_scope(owner, website),
                partial=report if kind == 'insufficient_evidence' else None)
            if error is not None:
                return error
        if failure is not None:
            return jsonify(code='research_unavailable', error=failure), 400
        if report.get('evidence', {}).get('status') == 'insufficient':
            return jsonify(code='research_unavailable',
                error='Insufficient business evidence. The website returned too little readable business content. '
                    'Existing work is preserved. Retry later or supply business details for review.',
                evidence=report['evidence'], rendering=report.get('rendering', {}),
                source_url=report['source_url'], coverage=report.get('coverage', {}),
                enrichment_warnings=report.get('enrichment_warnings', [])), 400
        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                retained = research_snapshots.retain(con, (owner, organisation_id), website, started, report)
                error = validate_research_scope(owner, website)
                if error is not None:
                    return error  # Closing the uncommitted connection rolls back.
                if not retained:
                    return jsonify(code='research_superseded', error='Newer findings were saved. Recover them before preparing a plan.'), 409
                con.commit()
        except sqlite3.Error:
            return jsonify(code='research_storage_unavailable',
                error='Website findings could not be saved. Try recovering saved findings before reading the website again.'), 503
        return jsonify(report)

    @app.after_request
    def preview_contract(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        from business_growthrova_capture import PUBLIC_ENDPOINTS
        if request.endpoint in PUBLIC_ENDPOINTS:
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        # The same bounded private SQLite byte format is reused. Preserve the
        # conservative legacy hostedStorageVerified=False throughout its receipts.
        response.headers['X-Growthrova-Storage'] = 'private-sqlite-single-process'
        return response

    return app


def from_environment():
    """WSGI/Flask factory; deliberately no generic Supabase/creator fallbacks."""
    import os
    names = ('GROWTHROVA_DATABASE_PATH', 'GROWTHROVA_SUPABASE_URL',
             'GROWTHROVA_AUTH_URL', 'GROWTHROVA_SUPABASE_ANON_KEY')
    if any(not os.environ.get(name) for name in names):
        raise ValueError('Supply the four isolated GROWTHROVA preview settings documented in docs/GROWTHROVA_PREVIEW.md')
    from business_growthrova_writer import WriterConfig
    from business_growthrova_images import ImageConfig
    return create_growthrova_preview(writer_config=WriterConfig.from_environment(os.environ),
        image_config=ImageConfig.from_environment(os.environ), database_path=os.environ[names[0]],
        project_url=os.environ[names[1]], auth_url=os.environ[names[2]], anon_key=os.environ[names[3]])
