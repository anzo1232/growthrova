"""Explicit, uncharged research/owner-brief -> revisioned campaign handoff."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from flask import g, jsonify, request
import business_growthrova_research as research
import business_marketing_drafts as drafts


class PlannerUnavailable(Exception):
    pass


def prepare_document(report, goal, business, *, strategy=None, start_date=None, strategy_document=None):
    payload = dict(report=report, goal=goal, business=business)
    if strategy is not None:
        payload['initialStrategy'] = strategy
    if start_date is not None:
        payload['startDate'] = start_date
    if strategy_document is not None:
        payload['strategyDocument'] = strategy_document
    return _prepare_document(payload)


def prepare_owner_document(brief, goal, business, website, *, start_date=None):
    payload = dict(ownerBrief=brief, goal=goal, business=business, sourceUrl=website)
    if start_date is not None:
        payload['startDate'] = start_date
    return _prepare_document(payload)


def _prepare_document(payload):
    """No shell, provider or ambient Node options; one bounded local process."""
    node = shutil.which('node', path=os.defpath)
    if not node:
        raise PlannerUnavailable()
    bridge = Path(__file__).resolve().parent / 'scripts/growthrova_prepare_plan.mjs'
    try:
        result = subprocess.run(
            [node, '--max-old-space-size=128', str(bridge)],
            input=json.dumps(payload, allow_nan=False),
            capture_output=True, text=True, timeout=15, cwd=bridge.parent.parent,
            env={'PATH': os.defpath, 'LANG': 'C.UTF-8'}, check=False)
        if result.returncode == 2:
            raise drafts.MarketingDraftError(
                ('Review the saved website findings and confirm the selected business strategy '
                 'for the current website before preparing this plan.' if 'strategyDocument' in payload else
                 'Business details are incomplete or invalid for plan preparation. '
                 'Review the saved business details and selected findings or owner brief.'), 'plan_needs_details', 409)
        if result.returncode != 0 or len(result.stdout.encode('utf8')) > 300000:
            raise PlannerUnavailable()
        # A review edits the existing campaign. Retained organic references may
        # be stale and must survive under the same rules as an ordinary edit.
        previous = payload.get('sourceDocument') if any(
            key in payload for key in ('strategyReview', 'paidPreparation', 'organicPreparation',
                                       'websiteImprovementPreparation', 'contentCopyPreparation',
                                       'contentPlanPreparation', 'channelPlanPreparation', 'brandPreparation',
                                       'writingCopyPreparation', 'conceptDirectionPreparation',
                                       'imageCopyPreparation')) else None
        output = json.loads(result.stdout)
        if any(key in payload for key in ('exportPreparation', 'planReview', 'planningWorklist', 'limitedResearchContext',
                                          'writingCopyPreview', 'contentAgenda', 'organicQueue')):
            return output
        if 'paidPreparation' in payload:
            return dict(document=drafts.normalise_document(output['document'], previous),
                        preparationIssues=output['preparationIssues'])
        return drafts.normalise_document(output, previous)
    except drafts.MarketingDraftError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise PlannerUnavailable() from exc


class ScopeChanged(Exception):
    def __init__(self, response):
        self.response = response


def selected_findings(con, scope, website, data, previous=None):
    """Explicit current/retained selection; a historical read never adopts it."""
    research_scope = (scope[0], research.ONBOARDING_SCOPE) \
        if data.get('researchSource') == 'onboarding' else scope
    retained = data.get('researchMode', 'current') == 'retained'
    snapshot = (research.read_retained(con, research_scope, data['researchId']) if retained
                else research.latest(con, research_scope))
    if snapshot is None:
        raise drafts.MarketingDraftError('Selected saved findings are unavailable in this business and source.',
                                         'research_not_saved', 404)
    if (snapshot['researchId'] != data['researchId'] or snapshot['website'] != website
            or snapshot['report'].get('source_url') != website
            or (previous is not None and snapshot != previous)):
        raise drafts.MarketingDraftError(
            'Selected findings changed or belong to a previous website. Review the saved findings.',
            'plan_research_changed', 409)
    return snapshot


def valid_partial_selection(selection):
    return (isinstance(selection, dict) and set(selection) == {'attempt', 'source'}
            and type(selection.get('attempt')) is int
            and 1 <= selection['attempt'] < 9223372036854775807
            and selection.get('source') in ('business', 'onboarding'))


def partial_findings(con, scope, website, selection, previous=None):
    """Recover one exact scoped failure receipt; never use earlier useful findings."""
    selected_scope = (scope[0], research.ONBOARDING_SCOPE) \
        if selection['source'] == 'onboarding' else scope
    status = research.attempt_status(con, selected_scope, website, include_partial=True)
    failure = status.get('failure', {})
    candidate = failure.get('partialFindings')
    if (status['attempt'] != selection['attempt'] or status['state'] != 'failed'
            or failure.get('kind') != 'insufficient_evidence' or candidate is None
            or candidate['website'] != website
            or candidate['report'].get('source_url') != website
            or candidate['report'].get('evidence', {}).get('status') != 'insufficient'
            or (previous is not None and candidate != previous)):
        raise drafts.MarketingDraftError(
            'Limited findings changed or are unavailable for this website. Recover the current read before preparing a plan.',
            'plan_research_changed', 409)
    return candidate


def unsaved_plan_review(document):
    """Shared review actions require an explicit save before preparation."""
    review = _prepare_document(dict(sourceDocument=document, planReview=True))
    return {**review, 'scope': 'unsaved_planning_only',
        'preparationRequiresSave': True,
        'limitations': 'Unsaved planning review only. Explicitly save this plan before using '
            'the review actions. Website statements remain unverified. Copy review does not '
            'verify claims, media rights, output quality, account readiness or authorise '
            'scheduling, publication or spend.'}


def register_plan_routes(app, repo, root, *, revalidate):
    from business_growthrova_planning_worklist import register_planning_worklist
    register_planning_worklist(app, repo, root, revalidate=revalidate,
                              prepare=lambda payload: _prepare_document(payload))
    from business_growthrova_content_agenda import register_content_agenda
    register_content_agenda(app, repo, root, revalidate=revalidate,
                           prepare=lambda payload: _prepare_document(payload))
    from business_growthrova_organic_queue import register_organic_queue
    register_organic_queue(app, repo, root, revalidate=revalidate,
                           prepare=lambda payload: _prepare_document(payload))

    def prepare_saved_edit(organisation_id, data, operation, changes, error_message, *, prepare=None,
                           result_key='document', validate_source=None, update_business_context=False):
        """An unsaved exact-revision edit; never dispatches or persists work."""
        scope = repo._scope(organisation_id)
        business, website = g.growthrova_org.get('name'), g.growthrova_org.get('website')

        def validate():
            error = revalidate()
            if error is not None:
                raise ScopeChanged(error)
            if g.growthrova_user['id'] != scope[0]:
                raise ScopeChanged((jsonify(code='auth_required',
                    error='Your session changed. Sign in again.'), 401))
            if (g.growthrova_org.get('name') != business
                    or g.growthrova_org.get('website') != website):
                raise drafts.MarketingDraftError('Business details changed. Review the current context.',
                                                 'plan_business_changed', 409)
            with closing(repo._connect()) as con:
                con.execute('BEGIN')
                if not repo._owned(con, data['id'], scope):
                    raise drafts.MarketingDraftError('Saved campaign not found in this business.', 'not_found', 404)
                source = drafts.read_draft(con, data['id'])
                if validate_source is not None:
                    validate_source(con, scope, website)
            if source['revision'] != data['expectedRevision']:
                raise drafts.MarketingDraftError('The campaign changed. Review its current revision.',
                                                 'revision_conflict', 409)
            doc = source['document']
            if not update_business_context and (doc['business'] != business
                    or doc.get('sourceUrl', '') != (website or '')):
                raise drafts.MarketingDraftError('Review and save the current business context first.',
                                                 'plan_business_changed', 409)
            return source

        try:
            record = validate()
            source = record['document']
            # Calendar identities and timestamps come from the checked saved
            # record, never request fields or a fresh export-time clock.
            metadata = dict(savedMetadata={key: record[key] for key in ('id', 'revision', 'updated')}) \
                if operation == 'exportPreparation' else {}
            try:
                document = (prepare(source, changes) if prepare else
                            _prepare_document(dict(sourceDocument=source, **metadata, **{operation: changes})))
            except (PlannerUnavailable, drafts.MarketingDraftError) as exc:
                validate()
                if isinstance(exc, PlannerUnavailable):
                    return jsonify(code='plan_unavailable', error=
                        'Preparation is unavailable. Your saved campaign is unchanged.'), 503
                codes = {'strategyReview': 'strategy_needs_review',
                         'paidPreparation': 'paid_plan_needs_review',
                         'organicPreparation': 'organic_brief_needs_review',
                         'websiteImprovementPreparation': 'website_improvement_needs_review',
                         'contentCopyPreparation': 'content_copy_needs_review',
                         'contentPlanPreparation': 'content_plan_needs_review',
                         'channelPlanPreparation': 'channel_plan_needs_review',
                         'brandPreparation': 'brand_needs_review',
                         'writingCopyPreparation': 'writing_copy_needs_review',
                         'conceptDirectionPreparation': 'concept_direction_needs_review',
                         'imageCopyPreparation': 'image_copy_needs_review',
                         'organicEdit': 'organic_work_needs_review',
                         'researchRefresh': 'research_refresh_needs_review',
                         'planReview': 'plan_review_unavailable',
                         'exportPreparation': 'export_needs_review'}
                return jsonify(code=codes[operation], error=error_message), 409
            validate()
            extras = {}
            if operation == 'paidPreparation':
                extras = dict(platform=changes['platform'],
                              preparationIssues=document['preparationIssues'])
                document = document['document']
            # Existing writer and receipts own explicit persistence and recovery.
            return jsonify(id=data['id'], expectedRevision=data['expectedRevision'],
                           saved=False, **{result_key: document}, **extras)
        except ScopeChanged as exc:
            return exc.response

    from business_growthrova_articles import register_article_handoff
    register_article_handoff(app, root, prepare_saved_edit=prepare_saved_edit)

    from business_growthrova_content_recovery import register_content_recovery
    register_content_recovery(app, root, prepare_saved_edit=prepare_saved_edit,
                              prepare=lambda payload: _prepare_document(payload))

    @app.post(root + '/review-plan')
    def review_saved_plan(organisation_id):
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'id', 'expectedRevision'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647):
            return jsonify(code='invalid_request', error=
                'Choose an exact saved campaign revision to review.'), 400
        drafts._id(data['id'])
        return prepare_saved_edit(organisation_id, data, 'planReview', {},
            'The saved plan could not be reviewed. Your saved work is unchanged.', result_key='review')

    @app.post(root + '/prepare-research-refresh')
    def prepare_research_refresh(organisation_id):
        data = request.get_json(silent=True)
        partial_mode = isinstance(data, dict) and 'partialResearch' in data
        partial = data.get('partialResearch') if isinstance(data, dict) else None
        required = {'id', 'expectedRevision', 'partialResearch' if partial_mode else 'researchId'}
        optional = {'updateBusinessContext'} | (set() if partial_mode else {'researchSource', 'researchMode'})
        if (not isinstance(data, dict)
                or not required <= set(data) or set(data) - required - optional
                or (partial_mode and not valid_partial_selection(partial))
                or data.get('researchSource', 'business') not in ('business', 'onboarding')
                or data.get('researchMode', 'current') not in ('current', 'retained')
                or ('updateBusinessContext' in data and type(data['updateBusinessContext']) is not bool)
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647):
            return jsonify(code='invalid_request', error=
                'Choose an exact saved campaign revision and saved findings or a recovered limited website read.'), 400
        for key in (('id',) if partial is not None else ('id', 'researchId')):
            drafts._id(data[key])

        snapshot = None
        # Only this explicit research-backed operation can repair a historical
        # context. The common edit fence remains strict for every other caller.
        update_context = data.get('updateBusinessContext', False)
        business = g.growthrova_org.get('name')
        website = g.growthrova_org.get('website')

        def validate_findings(con, scope, website):
            nonlocal snapshot
            if partial is not None:
                snapshot = partial_findings(con, scope, website, partial, snapshot)
                return
            snapshot = selected_findings(con, scope, website, data, snapshot)

        def refresh(source, _changes):
            # Refreshing existing evidence needs no new plan or inferred offer.
            # Keep sufficient-research planning behavior/callers unchanged.
            refreshed = (_prepare_document(dict(report=snapshot['report'], limitedResearchContext=True))
                if snapshot['report'].get('evidence', {}).get('status') == 'insufficient'
                else prepare_document(snapshot['report'], source['goal'],
                                      business if update_context else source['business']))
            keys = ('observedFacts', 'observedFactSources', 'websiteAuditText',
                    'websiteImages', 'editorialShortlist', 'brandIdentity')
            # The retained request URL alone is insufficient: the planner's
            # extracted/redirected site must match the selected target too.
            target_website = website if update_context else source['sourceUrl']
            if refreshed['sourceUrl'] != target_website:
                raise drafts.MarketingDraftError('Review the current business website first.')
            result = dict(source)
            if update_context:
                result.update(business=business, sourceUrl=website)
            for key in keys:
                result.pop(key, None)
                if key in refreshed:
                    result[key] = refreshed[key]
            if any(source.get(key) != result.get(key) for key in (*keys, 'business', 'sourceUrl')):
                if source.get('ownerStrategy') is not None:
                    # Retain corrections and links as historical snapshots;
                    # existing review helpers detect whether each still fits.
                    result['ownerStrategy'] = {**source['ownerStrategy'], 'confirmedContext': None}
                for key in ('posts', 'creatives'):
                    result[key] = [{**item, 'status': 'draft'} for item in source[key]]
            return drafts.normalise_document(result, source)

        return prepare_saved_edit(organisation_id, data, 'researchRefresh', None,
            'The saved findings cannot refresh this campaign. Review the current business website and findings. '
            'Your saved campaign is unchanged.', prepare=refresh, validate_source=validate_findings,
            update_business_context=update_context)

    @app.post(root + '/preview-writing-copy', defaults={'preview': True})
    @app.post(root + '/prepare-writing-copy')
    def prepare_writing_copy(organisation_id, preview=False):
        from business_growthrova_writer import saved_writing_result
        data = request.get_json(silent=True)
        if (not isinstance(data, dict)
                or set(data) - {'id', 'expectedRevision', 'operationId', 'changes', 'comparisons'}
                or not {'id', 'expectedRevision', 'operationId', 'changes'} <= set(data)
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647):
            return jsonify(code='invalid_request', error=
                'Choose an exact saved campaign revision, writing proposal and post destinations.'), 400
        for key in ('id', 'operationId'):
            drafts._id(data[key])
        changes = data['changes']
        if not isinstance(changes, list) or not 1 <= len(changes) <= 30:
            return jsonify(code='invalid_request', error=
                'Choose 1–30 distinct post days or static creative drafts and proposed caption indices from 0 to 2.'), 400
        destinations = []
        for change in changes:
            if not isinstance(change, dict) or set(change) not in (
                    {'day', 'index'}, {'creativeId', 'index'}):
                return jsonify(code='invalid_request', error=
                    'Each caption selection needs a post day or static creative identity and an index.'), 400
            post = 'day' in change
            target = change['day'] if post else change['creativeId']
            if (type(change['index']) is not int or not 0 <= change['index'] <= 2
                    or (post and (type(target) is not int or not 1 <= target <= 30))
                    or (not post and (not isinstance(target, str)
                        or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', target)))):
                return jsonify(code='invalid_request', error=
                    'Choose valid post days or static creative identities and caption indices from 0 to 2.'), 400
            destinations.append(('post' if post else 'creative', target))
        if len(set(destinations)) != len(destinations):
            return jsonify(code='invalid_request', error=
                'Choose each destination only once before comparing the saved words.'), 400
        if 'comparisons' in data:
            comparisons = data['comparisons']
            if (preview or not isinstance(comparisons, list) or len(comparisons) != len(changes)
                    or any(not isinstance(item, dict)
                           or set(item) != {'kind', 'target', 'index', 'before', 'after'}
                           or item['kind'] != destination[0]
                           or type(item['target']) is not type(destination[1])
                           or item['target'] != destination[1]
                           or type(item['index']) is not int or item['index'] != change['index']
                           or not isinstance(item['before'], dict) or not isinstance(item['after'], dict)
                           for item, change, destination in zip(comparisons, changes, destinations))):
                return jsonify(code='invalid_request', error=
                    'Use the exact comparisons returned for these saved destinations, in order.'), 400

        proposal = None
        original = None

        def validate_proposal(con, scope, website):
            nonlocal proposal, original
            row = con.execute('SELECT * FROM growthrova_writing_requests '
                'WHERE document_id=? AND operation_id=?', (data['id'], data['operationId'])).fetchone()
            if row is None:
                raise drafts.MarketingDraftError('Saved writing not found in this campaign.',
                                                 'writing_not_found', 404)
            current = saved_writing_result(con, row)
            if (current.get('state') != 'proposed' or current.get('creativePlan')
                    or current.get('independentReview') != 'pending' or not current.get('sample')):
                raise drafts.MarketingDraftError('Choose a completed proposed writing sample. Held or '
                    'uncertain writing cannot replace saved words.', 'writing_copy_needs_review', 409)
            # Compare evaluated output as well as raw state: parent changes may
            # alter whether a historical revision is eligible for use.
            identity = (row['result_json'], current)
            if original is not None and identity != original:
                raise drafts.MarketingDraftError('Saved writing changed. Reopen the proposal and compare again.',
                                                 'writing_copy_changed', 409)
            if original is None:
                original = identity
                proposal = current

        def prepare(source, changes):
            preparation = dict(proposal=proposal, changes=changes)
            if 'comparisons' in data:
                preparation['comparisons'] = data['comparisons']
            operation = 'writingCopyPreview' if preview else 'writingCopyPreparation'
            return _prepare_document(dict(sourceDocument=source, **{operation: preparation}))

        return prepare_saved_edit(organisation_id, data, 'writingCopyPreparation', changes,
            'Use writing from the current business facts and strategy, choose existing saved posts or static '
            'creative drafts and keep words within their limits. Compare again if saved words or the proposal changed. '
            'Review the prepared changes before saving.',
            prepare=prepare, validate_source=validate_proposal,
            result_key='comparisons' if preview else 'document')

    @app.post(root + '/prepare-concept-direction')
    def prepare_concept_direction(organisation_id):
        from business_growthrova_writer import saved_writing_result
        from business_creative_plans import concept_issues
        data = request.get_json(silent=True)
        required = {'id', 'expectedRevision', 'operationId', 'conceptId', 'targetId', 'edits'}
        if (not isinstance(data, dict) or not required <= set(data)
                or set(data) - required - {'day'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647):
            return jsonify(code='invalid_request', error=
                'Choose an exact saved campaign revision, concept and image draft.'), 400
        for key in ('id', 'operationId'):
            drafts._id(data[key])
        edits = data['edits']
        fields = {'headline': (3, 160), 'callToAction': (3, 240),
                  'visualDirection': (30, 1200), 'supportingLine': (0, 180)}
        if (any(not isinstance(data[key], str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', data[key])
                    for key in ('conceptId', 'targetId'))
                or not isinstance(edits, dict)
                or not {'headline', 'callToAction', 'visualDirection'} <= set(edits)
                or set(edits) - set(fields)
                or any(not isinstance(value, str) or not fields[key][0] <= len(value.strip())
                       or len(value) > fields[key][1]
                       or any(ord(c) < 32 and c not in '\n\t' or ord(c) == 127 for c in value)
                       for key, value in edits.items())
                or ('day' in data and (type(data['day']) is not int or not 1 <= data['day'] <= 30))):
            return jsonify(code='invalid_request', error=
                'Choose existing concept and draft identities, valid headline, call to action and picture '
                'instructions, and optionally an existing post day and supporting line.'), 400

        proposal = None
        original = None

        def validate_proposal(con, scope, website):
            nonlocal proposal, original
            row = con.execute('SELECT * FROM growthrova_writing_requests '
                'WHERE document_id=? AND operation_id=?', (data['id'], data['operationId'])).fetchone()
            if row is None:
                raise drafts.MarketingDraftError('Saved concept plan not found in this campaign.',
                                                 'writing_not_found', 404)
            current = saved_writing_result(con, row)
            if (current.get('state') != 'proposed' or not current.get('creativePlan')
                    or current.get('independentReview') != 'pending' or not current.get('concepts')
                    or concept_issues(current['concepts'], current['material'])):
                raise drafts.MarketingDraftError('Choose a proposed concept plan. Held or uncertain '
                    'concepts cannot replace draft directions.', 'concept_direction_needs_review', 409)
            identity = (row['result_json'], current)
            if original is not None and identity != original:
                raise drafts.MarketingDraftError('Saved concepts changed. Reopen and compare again.',
                                                 'concept_direction_changed', 409)
            if original is None:
                original = identity
                proposal = current

        changes = {key: data[key] for key in ('conceptId', 'targetId', 'edits', 'day') if key in data}

        def prepare(source, changes):
            return _prepare_document(dict(sourceDocument=source,
                conceptDirectionPreparation=dict(proposal=proposal, **changes)))

        return prepare_saved_edit(organisation_id, data, 'conceptDirectionPreparation', changes,
            'Choose a concept matching the current business facts and brand, an existing image draft '
            'and optional post. Review the prepared words and instructions before saving. '
            'Existing artwork is unchanged.', prepare=prepare, validate_source=validate_proposal)

    @app.post(root + '/prepare-image-copy')
    def prepare_image_copy(organisation_id):
        from business_growthrova_images import observed_candidate
        data = request.get_json(silent=True)
        if (not isinstance(data, dict)
                or set(data) != {'id', 'expectedRevision', 'operationId', 'sha256'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647
                or not isinstance(data.get('sha256'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', data['sha256'])):
            return jsonify(code='invalid_request', error=
                'Choose an exact saved campaign revision, image operation and image hash.'), 400
        for key in ('id', 'operationId'):
            drafts._id(data[key])

        candidate = None

        def validate_candidate(con, scope, website):
            nonlocal candidate
            # Read metadata only. Copy preparation never loads or alters pixels.
            row = con.execute('SELECT result_json, length(image_bytes) AS byte_count '
                'FROM growthrova_image_requests WHERE document_id=? AND operation_id=?',
                (data['id'], data['operationId'])).fetchone()
            if row is None:
                raise drafts.MarketingDraftError('Saved image not found in this campaign.',
                                                 'image_not_found', 404)
            saved = drafts.read_draft(con, data['id'])
            current = observed_candidate(con, data['id'], saved, json.loads(row['result_json']))
            if (not row['byte_count'] or current.get('sha256') != data['sha256']
                    or current.get('operationId') != data['operationId']
                    or current.get('state') != 'proposed' or current.get('compositionHeld')):
                raise drafts.MarketingDraftError('Choose the exact saved proposed image. Held or uncertain '
                    'images cannot replace post words.', 'image_copy_needs_review', 409)
            if candidate is not None and current != candidate:
                raise drafts.MarketingDraftError('Saved image or its review changed. Reopen and compare again.',
                                                 'image_copy_changed', 409)
            if candidate is None:
                candidate = current

        def prepare(source, _changes):
            return _prepare_document(dict(sourceDocument=source, imageCopyPreparation=candidate))

        return prepare_saved_edit(organisation_id, data, 'imageCopyPreparation', None,
            'Choose an image with concept words matching the current business facts and brand, '
            'and an existing intended post. Review the prepared words before saving. '
            'Existing artwork is unchanged.', prepare=prepare, validate_source=validate_candidate)

    @app.post(root + '/export-content')
    def export_content(organisation_id):
        data = request.get_json(silent=True)
        required = {'id', 'expectedRevision', 'format'}
        if (not isinstance(data, dict) or not required <= set(data)
                or set(data) - required - {'creativeId', 'operationId', 'itemIds'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647
                or data.get('format') not in ('calendar-csv', 'calendar-ics', 'creative-text', 'writing-text', 'concept-plan-json', 'strategy-text', 'organic-markdown')
                or ('itemIds' in data and (data.get('format') != 'organic-markdown'
                    or not isinstance(data['itemIds'], list) or not 1 <= len(data['itemIds']) <= 30
                    or any(not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ident)
                           for ident in data['itemIds'])
                    or len(set(data['itemIds'])) != len(data['itemIds'])))
                or ('creativeId' in data) != (data.get('format') == 'creative-text')
                or ('operationId' in data) != (data.get('format') in ('writing-text', 'concept-plan-json'))
                or ('creativeId' in data and (not isinstance(data['creativeId'], str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', data['creativeId'])))):
            return jsonify(code='invalid_request', error=
                'Choose an exact saved campaign revision and strategy, calendar, website-work, creative, saved-writing or concept-plan export.'), 400
        drafts._id(data['id'])
        if data['format'] in ('writing-text', 'concept-plan-json'):
            from business_growthrova_writer import saved_writing_result
            from business_creative_plans import concept_issues
            concept_export = data['format'] == 'concept-plan-json'
            drafts._id(data['operationId'])
            proposal = None
            original = None

            def validate_proposal(con, scope, website):
                nonlocal proposal, original
                row = con.execute('SELECT * FROM growthrova_writing_requests '
                    'WHERE document_id=? AND operation_id=?', (data['id'], data['operationId'])).fetchone()
                if row is None:
                    raise drafts.MarketingDraftError('Saved writing not found in this campaign.',
                                                     'writing_not_found', 404)
                current = saved_writing_result(con, row)
                if concept_export:
                    if not current.get('creativePlan') or not current.get('concepts'):
                        raise drafts.MarketingDraftError('This operation has no saved concept plan to export.',
                                                         'export_needs_review', 409)
                    if current.get('state') == 'proposed':
                        issues = concept_issues(current['concepts'], current['material'])
                        if issues:
                            current.update(state='held', issues=issues)
                elif current.get('creativePlan') or not current.get('sample'):
                    raise drafts.MarketingDraftError('This operation has no saved caption and script sample to export.',
                                                     'export_needs_review', 409)
                # Historical and held output may be inspected, never applied or
                # approved by exporting. Keep current holds and parent checks.
                identity = (row['result_json'], current)
                if original is not None and identity != original:
                    raise drafts.MarketingDraftError('Saved output changed. Reopen it before exporting.',
                                                     'writing_export_changed', 409)
                if original is None:
                    original = identity
                    proposal = current

            def export_saved_output(source, changes):
                return _prepare_document(dict(sourceDocument=source,
                    exportPreparation={**changes, 'proposal': proposal}))

            return prepare_saved_edit(organisation_id, data, 'exportPreparation',
                dict(format=data['format']),
                'The saved output cannot be exported. Reopen it; your campaign is unchanged.',
                prepare=export_saved_output, validate_source=validate_proposal, result_key='export')
        return prepare_saved_edit(organisation_id, data, 'exportPreparation',
            {key: data[key] for key in ('format', 'creativeId', 'itemIds') if key in data},
            'Choose website work or a creative in this saved campaign, or a complete dated 30-day plan for calendar reminders. '
            'Exports contain drafts; reminders do not schedule or publish posts.',
            result_key='export')

    @app.post(root + '/prepare-brand')
    def prepare_brand(organisation_id):
        data = request.get_json(silent=True)
        def invalid():
            return jsonify(code='invalid_request', error=
                'Choose a saved campaign revision and name, colour or typography preferences.'), 400
        if (not isinstance(data, dict) or set(data) != {'id', 'expectedRevision', 'brand'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647):
            return invalid()
        drafts._id(data['id'])
        brand = data['brand']
        bounds = {'name': 38, 'primary_color': 7, 'secondary_color': 7, 'font_style': 20}
        if (not isinstance(brand, dict) or not brand or set(brand) - set(bounds)
                or any(not isinstance(value, str) or len(value) > bounds[key]
                       for key, value in brand.items())):
            return invalid()
        # The existing shared brand validator checks colours, Unicode name
        # characters and supported styles after merging with the saved settings.
        return prepare_saved_edit(organisation_id, data, 'brandPreparation', brand,
            'Use a single-line brand name of up to 38 characters, six-digit hex colours '
            'and a supported typography style. Empty values clear preferences. '
            'Existing artwork is unchanged.')

    @app.post(root + '/prepare-channel-plan')
    def prepare_channel_plan(organisation_id):
        data = request.get_json(silent=True)
        def invalid():
            return jsonify(code='invalid_request', error=
                'Choose a saved campaign revision and either the suggested mix or distinct day/channel choices.'), 400
        required = {'id', 'expectedRevision'}
        if (not isinstance(data, dict) or not required <= set(data)
                or set(data) - required - {'applyMix', 'changes'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647
                or ('applyMix' in data) == ('changes' in data)):
            return invalid()
        drafts._id(data['id'])
        if 'applyMix' in data:
            if data['applyMix'] is not True:
                return invalid()
            preparation = dict(applyMix=True)
        else:
            changes = data['changes']
            if not isinstance(changes, list) or not 1 <= len(changes) <= 30:
                return invalid()
            seen = set()
            for change in changes:
                if (not isinstance(change, dict) or set(change) != {'day', 'channel'}
                        or type(change['day']) is not int or not 1 <= change['day'] <= 30
                        or change['day'] in seen or not isinstance(change['channel'], str)
                        or not 1 <= len(change['channel']) <= 50):
                    return invalid()
                seen.add(change['day'])
            preparation = dict(changes=changes)
        return prepare_saved_edit(organisation_id, data, 'channelPlanPreparation', preparation,
            'Confirm the current business strategy and choose suggested channels for existing '
            'unreviewed image posts or carousels. Reviewed posts and other formats are kept by the mix.')

    @app.post(root + '/prepare-content-plan')
    def prepare_content_plan(organisation_id):
        data = request.get_json(silent=True)
        def invalid():
            return jsonify(code='invalid_request', error=
                'Choose a saved campaign revision and distinct calendar or concept edits.'), 400
        required = {'id', 'expectedRevision', 'changes'}
        if (not isinstance(data, dict) or not required <= set(data)
                or set(data) - required - {'addSupportingIdeas'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647
                or ('addSupportingIdeas' in data and type(data['addSupportingIdeas']) is not bool)):
            return invalid()
        drafts._id(data['id'])
        changes = data['changes']
        if (not isinstance(changes, list) or len(changes) > 30
                or (not changes and not data.get('addSupportingIdeas'))):
            return invalid()
        seen = set()
        for change in changes:
            if not isinstance(change, dict) or change.get('type') not in ('post', 'creative'):
                return invalid()
            post = change['type'] == 'post'
            key = 'day' if post else 'id'
            target = change.get(key)
            if post:
                if type(target) is not int or not 1 <= target <= 30:
                    return invalid()
            elif not isinstance(target, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', target):
                return invalid()
            identity = (change['type'], target)
            if identity in seen:
                return invalid()
            seen.add(identity)
            allowed = {'type', key, 'fields'} | (set() if post else {'copyFromDay'})
            if set(change) - allowed:
                return invalid()
            fields = change.get('fields', {})
            bounds = ({'theme': 200, 'channel': 50, 'format': 80, 'objective': 60}
                      if post else {'title': 180, 'brief': 6000})
            if (not isinstance(fields, dict) or set(fields) - set(bounds)
                    or any(not isinstance(value, str) or len(value) > bounds[field]
                           for field, value in fields.items())
                    or (not fields and 'copyFromDay' not in change)):
                return invalid()
            if 'copyFromDay' in change and (type(change['copyFromDay']) is not int
                    or not 1 <= change['copyFromDay'] <= 30):
                return invalid()
        return prepare_saved_edit(organisation_id, data, 'contentPlanPreparation',
            dict(changes=changes, addSupportingIdeas=data.get('addSupportingIdeas', False)),
            'Choose existing calendar days and concepts. Copy only nonempty saved post words '
            'of at most 2000 characters; keep concept instructions and the eight-concept limit.')

    @app.post(root + '/prepare-content-copy')
    def prepare_content_copy(organisation_id):
        data = request.get_json(silent=True)
        def invalid():
            return jsonify(code='invalid_request', error=
                'Choose 1–30 distinct saved posts or concepts. Edit words or review saved words separately.'), 400
        if (not isinstance(data, dict) or set(data) != {'id', 'expectedRevision', 'changes'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647):
            return invalid()
        drafts._id(data['id'])
        changes = data['changes']
        if not isinstance(changes, list) or not 1 <= len(changes) <= 30:
            return invalid()
        seen = set()
        for change in changes:
            if not isinstance(change, dict) or change.get('type') not in ('post', 'creative'):
                return invalid()
            post = change['type'] == 'post'
            key = 'day' if post else 'id'
            target = change.get(key)
            if post:
                if type(target) is not int or not 1 <= target <= 30:
                    return invalid()
            else:
                if not isinstance(target, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', target):
                    return invalid()
            identity = (change['type'], target)
            if identity in seen:
                return invalid()
            seen.add(identity)
            if 'review' in change:
                # Review belongs to unchanged saved wording. The authoritative
                # writer deliberately invalidates review on any changed words.
                if set(change) != {'type', key, 'review'} or change['review'] is not True:
                    return invalid()
                continue
            if (set(change) - {'type', key, 'fields', 'appendFactIndices'}
                    or not ({'fields', 'appendFactIndices'} & set(change))):
                return invalid()
            fields = change.get('fields', {})
            bounds = {'copyDraft': 3000 if post else 2000, 'callToAction': 240}
            if post:
                bounds.update(graphicText=500, supportingLine=180, destinationUrl=512)
            if (not isinstance(fields, dict) or ('fields' in change and not fields)
                    or set(fields) - set(bounds)
                    or any(not isinstance(value, str) or len(value) > bounds[field]
                           for field, value in fields.items())):
                return invalid()
            if 'appendFactIndices' in change:
                indices = change['appendFactIndices']
                if (not isinstance(indices, list) or not 1 <= len(indices) <= 40
                        or any(type(index) is not int or not 0 <= index < 40 for index in indices)
                        or len(set(indices)) != len(indices)):
                    return invalid()
        return prepare_saved_edit(organisation_id, data, 'contentCopyPreparation', changes,
            'Choose existing posts or concepts and valid copy, next steps and HTTPS destinations. '
            'Add only current confirmed or corrected facts within the copy limits. '
            'Save word changes before marking them checked; replace unwritten or planning-only copy first.')

    @app.post(root + '/prepare-organic-work')
    def prepare_organic_work(organisation_id):
        import business_organic_work as organic
        data = request.get_json(silent=True)
        def invalid():
            return jsonify(code='invalid_request', error=
                'Choose a saved campaign revision and 1–30 distinct work items to add, edit or remove.'), 400
        required = {'id', 'expectedRevision'}
        if (not isinstance(data, dict) or not required <= set(data)
                or set(data) - required - {'changes', 'additions'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647):
            return invalid()
        drafts._id(data['id'])
        changes, additions = data.get('changes', []), data.get('additions', [])
        if (not isinstance(changes, list) or not isinstance(additions, list)
                or not 1 <= len(changes) + len(additions) <= 30):
            return invalid()
        bounds = {'title': 200, 'brief': 3000, 'draft': 8000, 'nextAction': 1000}
        statuses = ('planned', 'drafting', 'ready_for_review', 'handed_off', 'parked')
        seen = set()
        for change in changes:
            if (not isinstance(change, dict) or not isinstance(change.get('id'), str)
                    or not 1 <= len(change['id']) <= 64 or change['id'] in seen):
                return invalid()
            seen.add(change['id'])
            if 'remove' in change:
                if set(change) != {'id', 'remove'} or change['remove'] is not True:
                    return invalid()
                continue
            if (len(change) < 2 or set(change) - {'id', 'status'} - set(bounds)
                    or any(key in change and (not isinstance(change[key], str)
                        or len(change[key]) > limit) for key, limit in bounds.items())
                    or ('title' in change and not change['title'].strip())
                    or ('status' in change and change['status'] not in statuses)):
                return invalid()
        for addition in additions:
            if (not isinstance(addition, dict)
                    or not {'id', 'observationIndex', 'title'} <= set(addition)
                    or set(addition) - {'id', 'observationIndex'} - set(bounds)
                    or not isinstance(addition['id'], str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', addition['id'])
                    or addition['id'] in seen
                    or type(addition['observationIndex']) is not int
                    or not 0 <= addition['observationIndex'] < 40
                    or any(key in addition and (not isinstance(addition[key], str)
                        or len(addition[key]) > limit) for key, limit in bounds.items())
                    or not addition['title'].strip()):
                return invalid()
            seen.add(addition['id'])
        return prepare_saved_edit(organisation_id, data, 'organicEdit', changes,
            'Choose existing organic work or saved observations, use new identifiers for additions '
            'and keep up to 30 items with wording within the saved limits. '
            'Website observations remain unconfirmed; review claims before use.',
            prepare=(lambda document, edits: organic.prepare_edit(document, edits, additions=additions))
                if additions else organic.prepare_edit)

    @app.post(root + '/prepare-website-improvements')
    def prepare_website_improvements(organisation_id):
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'id', 'expectedRevision', 'recommendationIndices'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647):
            return jsonify(code='invalid_request', error='Choose a saved campaign revision and audit recommendations.'), 400
        drafts._id(data['id'])
        indices = data['recommendationIndices']
        if (not isinstance(indices, list) or not 1 <= len(indices) <= 30
                or any(type(index) is not int or not 0 <= index < 40 for index in indices)
                or len(set(indices)) != len(indices)):
            return jsonify(code='invalid_request', error='Choose 1–30 distinct audit recommendation indices.'), 400
        return prepare_saved_edit(organisation_id, data, 'websiteImprovementPreparation',
            dict(recommendationIndices=indices),
            'Choose recommendations retained in this saved audit. Keep wording within its limits '
            'and no more than 30 organic work items.')

    @app.post(root + '/prepare-organic-briefs')
    def prepare_organic_briefs(organisation_id):
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'id', 'expectedRevision', 'observationIndices'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647):
            return jsonify(code='invalid_request', error='Choose a saved campaign revision and reviewed observations.'), 400
        drafts._id(data['id'])
        indices = data['observationIndices']
        if (not isinstance(indices, list) or not 1 <= len(indices) <= 30
                or any(type(index) is not int or not 0 <= index < 40 for index in indices)
                or len(set(indices)) != len(indices)):
            return jsonify(code='invalid_request', error='Choose 1–30 distinct observation indices.'), 400
        return prepare_saved_edit(organisation_id, data, 'organicPreparation',
            dict(observationIndices=indices),
            'Confirm the current strategy and confirm or correct each selected observation. '
            'Keep brief wording within its limits and no more than 30 organic work items.')

    @app.post(root + '/prepare-paid-plan')
    def prepare_paid_plan(organisation_id):
        import business_paid_campaign as paid
        data = request.get_json(silent=True)
        required = {'id', 'expectedRevision', 'platform'}
        optional = {'plan', 'strategyFields'}
        if (not isinstance(data, dict) or not required <= set(data)
                or set(data) - required - optional
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647
                or data.get('platform') not in ('meta', 'google')):
            return jsonify(code='invalid_request', error=
                'Choose a saved campaign revision and Meta or Google preparation.'), 400
        drafts._id(data['id'])
        fields = data.get('strategyFields', [])
        allowed = {'objective', 'audience', 'destinationUrl'} | (
            {'primaryText', 'headline', 'callToAction'} if data['platform'] == 'meta'
            else {'headlines', 'descriptions'})
        if (not isinstance(fields, list) or len(fields) > len(allowed)
                or any(not isinstance(key, str) or key not in allowed for key in fields)
                or len(set(fields)) != len(fields)):
            return jsonify(code='invalid_request', error='Choose distinct supported strategy fields.'), 400
        changes = dict(platform=data['platform'], strategyFields=fields)
        if 'plan' in data:
            normalise = paid.normalise if data['platform'] == 'meta' else paid.normalise_google
            changes['plan'] = normalise(data['plan'])
        return prepare_saved_edit(organisation_id, data, 'paidPreparation', changes,
            'Provide or start a platform draft. Confirm the current strategy before copying its '
            'wording, and shorten any selected fields that exceed preparation limits.')

    @app.post(root + '/prepare-strategy-review')
    def prepare_strategy_review(organisation_id):
        data = request.get_json(silent=True)
        required = {'id', 'expectedRevision'}
        optional = {'strategy', 'factReviews', 'evidenceLinks', 'confirm',
                    'calendarStartDate', 'completeCalendar', 'refreshDays', 'briefCopyDays', 'goal'}
        bounds = {'offer': 500, 'audience': 300, 'callToAction': 240,
                  'positioning': 500, 'constraints': 1000}
        def invalid():
            return jsonify(code='invalid_request', error=
                'Choose a saved campaign revision and valid strategy changes.'), 400
        if (not isinstance(data, dict) or not required <= set(data)
                or set(data) - required - optional
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647):
            return invalid()
        drafts._id(data['id'])
        if 'goal' in data and (not isinstance(data['goal'], str)
                or data['goal'] not in ('awareness', 'enquiries', 'bookings', 'education', 'offers')):
            return invalid()
        strategy = data.get('strategy', {})
        links = data.get('evidenceLinks', {})
        facts = data.get('factReviews', [])
        if (not isinstance(strategy, dict) or set(strategy) - set(bounds)
                or any(not isinstance(v, str) or len(v) > bounds[k] for k, v in strategy.items())
                or not isinstance(links, dict) or set(links) - set(bounds)
                or any(v is not None and (not isinstance(v, str) or not 1 <= len(v) <= 32)
                       for v in links.values())
                or not isinstance(facts, list) or len(facts) > 40
                or any(key in data and type(data[key]) is not bool
                       for key in ('confirm', 'completeCalendar'))):
            return invalid()
        seen = set()
        for fact in facts:
            if (not isinstance(fact, dict) or not {'index', 'decision'} <= set(fact)
                    or set(fact) - {'index', 'decision', 'statement'}
                    or type(fact['index']) is not int or not 0 <= fact['index'] < 40
                    or fact['index'] in seen
                    or fact['decision'] not in ('pending', 'confirmed', 'corrected', 'excluded')
                    or not isinstance(fact.get('statement', ''), str)
                    or len(fact.get('statement', '')) > 600
                    or (fact['decision'] != 'corrected' and fact.get('statement'))
                    or (fact['decision'] == 'corrected' and not fact.get('statement', '').strip())):
                return invalid()
            seen.add(fact['index'])
        # The shared normalizer validates real dates, including leap days.
        if 'calendarStartDate' in data and (not isinstance(data['calendarStartDate'], str)
                or len(data['calendarStartDate']) not in (0, 10)):
            return invalid()
        # Separate explicit operations: no ambiguous last-operation-wins result.
        for key in ('refreshDays', 'briefCopyDays'):
            if key in data:
                days = data[key]
                if (not isinstance(days, list) or not 1 <= len(days) <= 30
                        or any(type(day) is not int or not 1 <= day <= 30 for day in days)
                        or len(set(days)) != len(days)):
                    return invalid()
        if set(data.get('refreshDays', [])) & set(data.get('briefCopyDays', [])):
            return invalid()
        return prepare_saved_edit(organisation_id, data, 'strategyReview',
            {k: data[k] for k in optional if k in data},
            'Review the brief, fact decisions, source links and calendar date. '
            'Choose existing unreviewed days for replacements.')

    @app.post(root + '/preview-next', defaults={'preview': True})
    @app.post(root + '/prepare-next')
    def prepare_next_plan(organisation_id, preview=False):
        data = request.get_json(silent=True)
        fields = {'sourceId', 'sourceRevision', 'goal', 'startDate'}
        if not preview:
            fields |= {'id', 'mutationId'}
        if (not isinstance(data, dict) or set(data) != fields
                or type(data.get('sourceRevision')) is not int
                or not 1 <= data['sourceRevision'] < 2147483648
                or not isinstance(data.get('goal'), str)
                or data['goal'] not in {'awareness', 'enquiries', 'bookings', 'education', 'offers'}
                or not isinstance(data.get('startDate'), str) or len(data['startDate']) != 10):
            return jsonify(code='invalid_request', error=
                'Choose a saved strategy revision, goal and start date.' if preview else
                'Choose a saved strategy revision, goal, start date and new campaign/save identifiers.'), 400
        for key in (('sourceId',) if preview else ('id', 'mutationId', 'sourceId')):
            drafts._id(data[key])
        if not preview and data['sourceId'] == data['id']:
            return jsonify(code='invalid_request', error='Use a new campaign identifier to preserve the source.'), 400
        scope = repo._scope(organisation_id)
        website = g.growthrova_org.get('website')
        business = g.growthrova_org.get('name')

        def validate(con, current_scope):
            error = revalidate()
            if error is not None:
                raise ScopeChanged(error)
            if current_scope != scope or g.growthrova_user['id'] != scope[0]:
                raise ScopeChanged((jsonify(code='auth_required',
                    error='Your session changed. Sign in again.'), 401))
            if (g.growthrova_org.get('website') != website
                    or g.growthrova_org.get('name') != business):
                raise drafts.MarketingDraftError('Business details changed. Review before reusing context.',
                                                 'plan_business_changed', 409)
            if not repo._owned(con, data['sourceId'], scope):
                raise drafts.MarketingDraftError('Saved strategy not found in this business.', 'not_found', 404)
            source = drafts.read_draft(con, data['sourceId'])
            if source['revision'] != data['sourceRevision']:
                raise drafts.MarketingDraftError('The source campaign changed. Review its current revision.',
                                                 'plan_source_changed', 409)
            document = source['document']
            if document['business'] != business or document.get('sourceUrl', '') != (website or ''):
                raise drafts.MarketingDraftError('The saved strategy belongs to earlier business details. '
                    'Review and save the current business context first.', 'plan_business_changed', 409)
            return document

        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN')
                source = validate(con, scope)
            try:
                # The shared planner checks exact confirmation and strips delivery
                # preparation. No website, writer or image provider is contacted.
                document = _prepare_document(dict(sourceDocument=source,
                    goal=data['goal'], startDate=data['startDate']))
                if preview:
                    review = unsaved_plan_review(document)
            except (PlannerUnavailable, drafts.MarketingDraftError) as exc:
                with closing(repo._connect()) as con:
                    con.execute('BEGIN')
                    validate(con, scope)
                if isinstance(exc, drafts.MarketingDraftError):
                    return jsonify(code='plan_needs_details', error=
                        'Confirm the saved business strategy and choose a valid calendar start date.'), 409
                return jsonify(code='plan_unavailable', error=
                    ('Plan preview is unavailable. Saved work is unchanged. Try the preview again.'
                     if preview else 'Plan preparation is unavailable. Check saved campaigns and the save receipt '
                     'before retrying with the same identifiers.')), 503
            if preview:
                with closing(repo._connect()) as con:
                    con.execute('BEGIN')
                    validate(con, scope)
                return jsonify(saved=False, document=document, review=review,
                    source=dict(kind='saved_strategy', id=data['sourceId'], revision=data['sourceRevision']))
            return jsonify(repo.save(organisation_id, dict(id=data['id'], mutationId=data['mutationId'],
                expectedRevision=0, document=document), _validate_write=validate))
        except ScopeChanged as exc:
            return exc.response

    @app.post(root + '/preview-plan', defaults={'preview': True})
    @app.post(root + '/prepare-plan')
    def prepare_plan(organisation_id, preview=False):
        data = request.get_json(silent=True)
        owner_brief = isinstance(data, dict) and 'ownerBrief' in data
        required = {'goal'} | ({'ownerBrief'} if owner_brief else {'researchId'})
        if not preview:
            required |= {'id', 'mutationId'}
        optional = {'startDate'} | ({'partialResearch'} if owner_brief else {'researchSource', 'researchMode', 'strategy', 'strategySource'})
        if (not isinstance(data, dict) or not required <= set(data)
                or set(data) - required - optional
                or data.get('researchSource', 'business') not in ('business', 'onboarding')
                or data.get('researchMode', 'current') not in ('current', 'retained')
                or not isinstance(data.get('goal'), str)
                or data['goal'] not in {'awareness', 'enquiries', 'bookings', 'education', 'offers'}):
            return jsonify(code='invalid_request',
                error=('Choose saved findings or an owner brief and a goal.' if preview else
                       'Choose saved findings or an owner brief, a goal and new campaign/save identifiers.')), 400
        partial_source = data.get('partialResearch')
        if 'partialResearch' in data and not valid_partial_selection(partial_source):
            return jsonify(code='invalid_request', error=
                'Choose an exact failed website read and supply the missing business details.'), 400
        strategy_source = data.get('strategySource')
        if 'strategySource' in data:
            if ('strategy' in data or not isinstance(strategy_source, dict)
                    or set(strategy_source) != {'id', 'revision'}
                    or type(strategy_source.get('revision')) is not int
                    or not 1 <= strategy_source['revision'] < 2147483647):
                return jsonify(code='invalid_request', error=
                    'Choose one exact saved strategy revision instead of supplying another brief.'), 400
            drafts._id(strategy_source['id'])
            if not preview and strategy_source['id'] == data['id']:
                return jsonify(code='invalid_request', error='Keep the source campaign and use a new campaign identifier.'), 400
        if 'startDate' in data and (not isinstance(data['startDate'], str)
                or not re.fullmatch(r'20[2-8][0-9]-[01][0-9]-[0-3][0-9]', data['startDate'])):
            return jsonify(code='invalid_request', error='Choose a valid calendar start date.'), 400
        if 'strategy' in data:
            strategy = data['strategy']
            bounds = {'offer': 500, 'audience': 300, 'callToAction': 240, 'positioning': 500}
            if (not isinstance(strategy, dict) or not strategy or set(strategy) - set(bounds)
                    or any(not isinstance(value, str) or len(value) > bounds[key]
                           or (key != 'positioning' and not value.strip())
                           for key, value in strategy.items())):
                return jsonify(code='invalid_request', error=
                    'Supply only the missing audience, service or product, reason to choose you, '
                    'or next step within the field limits.'), 400
        if owner_brief:
            brief = data['ownerBrief']
            bounds = {'offer': 500, 'audience': 300, 'callToAction': 240, 'positioning': 500}
            if (not isinstance(brief, dict)
                    or not {'offer', 'audience', 'callToAction'} <= set(brief)
                    or set(brief) - set(bounds)
                    or any(not isinstance(value, str) or len(value) > bounds[key]
                           or (key != 'positioning' and not value.strip())
                           for key, value in brief.items())):
                return jsonify(code='invalid_request', error=
                    'Supply a service or product, audience and next step within the field limits.'), 400
        for key in (() if preview else ('id', 'mutationId')) + (() if owner_brief else ('researchId',)):
            drafts._id(data[key])
        scope = repo._scope(organisation_id)
        # Source selection is explicit: never borrow another owner's preview or
        # silently fall back to a different saved result. Keep the snapshot in
        # its original scope so response-loss retries do not consume evidence.
        website = g.growthrova_org.get('website')
        business = g.growthrova_org.get('name')
        strategy_document = None
        partial_snapshot = None
        selected_snapshot = None

        def validate(con, current_scope):
            nonlocal strategy_document, partial_snapshot, selected_snapshot
            error = revalidate()
            if error is not None:
                raise ScopeChanged(error)
            if current_scope != scope or g.growthrova_user['id'] != scope[0]:
                raise ScopeChanged((jsonify(code='auth_required',
                    error='Your session changed. Sign in again.'), 401))
            if (g.growthrova_org.get('website') != website
                    or g.growthrova_org.get('name') != business):
                raise drafts.MarketingDraftError(
                    'Business details changed. Review the current business before preparing a plan.',
                    'plan_business_changed', 409)
            if strategy_source is not None:
                if not repo._owned(con, strategy_source['id'], scope):
                    raise drafts.MarketingDraftError('Saved strategy not found in this business.', 'not_found', 404)
                source = drafts.read_draft(con, strategy_source['id'])
                if source['revision'] != strategy_source['revision']:
                    raise drafts.MarketingDraftError('Saved strategy changed. Select its current revision.',
                                                     'revision_conflict', 409)
                candidate = source['document']
                if candidate['business'] != business or candidate.get('sourceUrl', '') != (website or ''):
                    raise drafts.MarketingDraftError('Review the saved strategy for the current business website.',
                                                     'plan_business_changed', 409)
                strategy_document = candidate
            if partial_source is not None:
                # An attempt identifies a dispatch; also fence the exact receipt
                # so a changed body within that dispatch cannot slip through.
                candidate = partial_findings(con, scope, website, partial_source, partial_snapshot)
                partial_snapshot = candidate
                return candidate
            if owner_brief:
                # Explicit owner statements are not website evidence and need
                # no snapshot. Business identity/access must still match.
                return None
            selected_snapshot = selected_findings(con, scope, website, data, selected_snapshot)
            return selected_snapshot

        try:
            with closing(repo._connect()) as con:
                con.execute('BEGIN')
                snapshot = validate(con, scope)
            try:
                calendar = {'start_date': data['startDate']} if 'startDate' in data else {}
                if partial_source is not None:
                    document = prepare_document(snapshot['report'], data['goal'], business, strategy=brief, **calendar)
                elif owner_brief:
                    document = prepare_owner_document(brief, data['goal'], business, website, **calendar)
                else:
                    document = prepare_document(snapshot['report'], data['goal'], business,
                        **calendar, **({'strategy': data['strategy']} if 'strategy' in data else {}),
                        **({'strategy_document': strategy_document} if strategy_source is not None else {}))
                if (not owner_brief or partial_source is not None) and document['sourceUrl'] != website:
                    raise drafts.MarketingDraftError(
                        'Prepared findings do not match the current business website.',
                        'plan_research_changed', 409)
                if preview:
                    review = unsaved_plan_review(document)
            except (PlannerUnavailable, drafts.MarketingDraftError) as exc:
                # Even a failed local operation must not disclose outcome details
                # to a session that lost access while the planner was running.
                with closing(repo._connect()) as con:
                    con.execute('BEGIN')
                    validate(con, scope)
                if isinstance(exc, drafts.MarketingDraftError):
                    raise
                return jsonify(code='plan_unavailable', error=(
                    'Plan preview is unavailable. Saved work is unchanged. Try the preview again.'
                    if preview else 'Plan preparation is unavailable. Saved work is unchanged. '
                    'Check your saved campaigns before retrying with the same identifiers.')), 503
            if preview:
                # Review uses another bounded local process. Check the exact
                # source again only after both slow operations have finished.
                with closing(repo._connect()) as con:
                    con.execute('BEGIN')
                    validate(con, scope)
                return jsonify(saved=False, document=document, review=review,
                    source=(dict(kind='owner_brief_with_partial_research',
                        partialResearch=partial_source, website=snapshot['website'],
                        status='unconfirmed', sufficientForPlan=False,
                        ownerInputFields=sorted(brief)) if partial_source is not None else
                        dict(kind='owner_brief') if owner_brief else dict(
                        kind=data.get('researchSource', 'business'),
                        researchId=snapshot['researchId'], savedAt=snapshot['savedAt'],
                        researchMode=data.get('researchMode', 'current'),
                        website=snapshot['website'], status=snapshot['status'],
                        **({'ownerInputFields': sorted(data['strategy'])} if 'strategy' in data else {}),
                        **({'strategySource': strategy_source} if strategy_source is not None else {}))))
            saved = repo.save(organisation_id, dict(id=data['id'], mutationId=data['mutationId'],
                expectedRevision=0, document=document), _validate_write=validate)
            return jsonify(saved)
        except ScopeChanged as exc:
            return exc.response
