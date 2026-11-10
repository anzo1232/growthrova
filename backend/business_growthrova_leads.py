"""Manual enquiries and observed outcomes in the existing private database.

Consent is an owner's recorded statement, never a grant to send messages.
There are no provider calls or inferred outcomes. Intake reuses the same writer.
"""
from contextlib import closing
from datetime import date, datetime, timezone
import hashlib
import json
import re
import time

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id, _text
from business_marketing_offline import OfflineDocumentAccessError
from business_growthrova_customer_care import normalise_customer_care, prepare_due_care
from business_growthrova_sales import normalise_sale, normalise_purchases, observed_sales, validate_sale_changes

STATUSES = ('new', 'contacted', 'qualified', 'booked', 'won', 'lost')
FOLLOW_THROUGH_LIMITS = dict(responsiblePerson=160, nextAction=1000, actionDueDate=10,
                             followUpDraft=4000)


def normalise(value):
    limits = dict(name=160, email=254, phone=40, source=160, sourceReference=512,
                  permissionNotes=1000, qualification=1000, booking=300, notes=2000)
    required = set(limits) | {'status', 'emailPermission', 'whatsappPermission'}
    optional = set(FOLLOW_THROUGH_LIMITS) | {'actionState', 'followUpChannel', 'customerCare', 'sale', 'purchases', 'prospectOrigin', 'providerOrigin'}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
        raise MarketingDraftError('Use the supported enquiry fields.')
    result = {k: _text(value[k], k, limit).strip() for k, limit in limits.items()}
    if not result['name'] or not result['source'] or not (result['email'] or result['phone']):
        raise MarketingDraftError('Add a name, source and email or phone number.')
    if result['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', result['email']):
        raise MarketingDraftError('Enter a complete email address.')
    phone = re.sub(r'[ ()+.-]', '', result['phone'])
    if result['phone'] and not re.fullmatch(r'[0-9]{7,15}', phone):
        raise MarketingDraftError('Use a phone number with country code and 7–15 digits.')
    if value['status'] not in STATUSES:
        raise MarketingDraftError('Choose a supported enquiry status.')
    result['status'] = value['status']
    for key in ('emailPermission', 'whatsappPermission'):
        if value[key] not in ('unknown', 'recorded', 'withdrawn'):
            raise MarketingDraftError('Choose a permission record.')
        result[key] = value[key]
    if 'recorded' in (result['emailPermission'], result['whatsappPermission']) and not result['permissionNotes']:
        raise MarketingDraftError('Record when, where and what the contact agreed to.')
    # Keep absent fields absent: historical save fingerprints must still replay.
    for key, limit in FOLLOW_THROUGH_LIMITS.items():
        if key in value:
            result[key] = _text(value[key], key, limit).strip()
    due = result.get('actionDueDate', '')
    if due:
        try:
            if date.fromisoformat(due).isoformat() != due:
                raise ValueError()
        except ValueError:
            raise MarketingDraftError('Choose a valid action due date (YYYY-MM-DD).') from None
    for key, allowed in (('actionState', ('open', 'done', 'cancelled')),
                         ('followUpChannel', ('unspecified', 'email', 'whatsapp', 'phone', 'other'))):
        if key in value:
            if value[key] not in allowed:
                raise MarketingDraftError('Choose a supported follow-through setting.')
            result[key] = value[key]
    if (due or result.get('actionState') in ('done', 'cancelled')) and not result.get('nextAction'):
        raise MarketingDraftError('Describe the human action before dating or closing it.')
    if 'customerCare' in value:
        result['customerCare'] = normalise_customer_care(value['customerCare'])
    if 'sale' in value:
        result['sale'] = normalise_sale(value['sale'])
    if 'purchases' in value:
        result['purchases'] = normalise_purchases(value['purchases'])
    if 'prospectOrigin' in value:
        from business_growthrova_prospects import normalise_origin
        result['prospectOrigin'] = normalise_origin(value['prospectOrigin'])
    if 'providerOrigin' in value:
        from business_growthrova_provider_leads import normalise_origin
        result['providerOrigin'] = normalise_origin(value['providerOrigin'])
    return result, result['email'].casefold() or None, phone or None


def lead_snapshot(con, row):
    history = con.execute('SELECT revision,actor_id,occurred,data_json FROM growthrova_lead_events '
                          'WHERE lead_id=? ORDER BY revision', (row['id'],)).fetchall()
    return dict(id=row['id'], campaignId=row['document_id'], revision=row['revision'],
                data=json.loads(row['data_json']), created=row['created'], updated=row['updated'],
                history=[dict(revision=e['revision'], actorId=e['actor_id'], at=e['occurred'],
                              data=json.loads(e['data_json'])) for e in history])


def persist_lead(con, scope, ident, payload, *, actor_id=None, preparing_care=False, provider_import=False):
    """Caller owns transaction and access checks. Never performs external work."""
    lead_id, mutation = _id(payload['id']), _id(payload['mutationId'])
    base = payload['expectedRevision']
    if type(base) is not int or not 0 <= base < 500:
        raise MarketingDraftError('Invalid enquiry revision or history limit reached.')
    data, email_key, phone_key = normalise(payload['data'])
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    fingerprint = hashlib.sha256((str(base) + '\n' + encoded).encode()).hexdigest()
    old = con.execute('SELECT * FROM growthrova_leads WHERE id=?', (lead_id,)).fetchone()
    if old and (old['owner_id'], old['organisation_id'], old['document_id']) != (*scope, ident):
        raise OfflineDocumentAccessError('Enquiry access denied')
    receipt = con.execute('SELECT * FROM growthrova_lead_events WHERE lead_id=? AND mutation_id=?',
                          (lead_id, mutation)).fetchone()
    if receipt:
        if receipt['fingerprint'] != fingerprint or not old or old['revision'] != receipt['revision']:
            raise MarketingDraftError('This save has changed or a newer version exists. Reopen the enquiry.', 'revision_conflict', 409)
        result = lead_snapshot(con, old)
        return result, True
    if (old['revision'] if old else 0) != base:
        raise MarketingDraftError('Another editor saved this enquiry. Reopen it before saving.', 'revision_conflict', 409)
    old_data = json.loads(old['data_json']) if old else {}
    if old and data.get('providerOrigin') != old_data.get('providerOrigin'):
        raise MarketingDraftError('Keep the saved provider event unchanged. Add corrections in enquiry notes.')
    if not old and data.get('providerOrigin') and not provider_import:
        raise MarketingDraftError('Use the reviewed provider enquiry handoff to retain event identity.')
    if old and data.get('prospectOrigin') != old_data.get('prospectOrigin'):
        raise MarketingDraftError('Keep the saved prospect response and source unchanged. Add corrections in enquiry notes.')
    if not old and data.get('prospectOrigin'):
        from business_growthrova_prospects import validate_handoff
        validate_handoff(con, scope, ident, data['prospectOrigin'])
    validate_sale_changes(old_data.get('sale'), data.get('sale'))
    purchases = {item['id']: item for item in data.get('purchases', [])}
    for previous in old_data.get('purchases', []):
        validate_sale_changes(previous, purchases.get(previous['id']))
    if not preparing_care and data.get('customerCare', {}).get('repeatProgress') != old_data.get('customerCare', {}).get('repeatProgress'):
        raise MarketingDraftError('Keep saved repeat progress unchanged. Use Prepare due tasks for new occurrences.')
    if con.execute('SELECT 1 FROM growthrova_leads WHERE owner_id=? AND organisation_id=? AND id<>? '
                   'AND ((email_key IS NOT NULL AND email_key=?) OR (phone_key IS NOT NULL AND phone_key=?))',
                   (*scope, lead_id, email_key, phone_key)).fetchone():
        raise MarketingDraftError('That contact is already recorded for this business. Open the original enquiry in its campaign.', 'duplicate_contact', 409)
    if not old and con.execute('SELECT count(*) FROM growthrova_leads WHERE owner_id=? AND organisation_id=?', scope).fetchone()[0] >= 1000:
        raise MarketingDraftError('This business has reached the local enquiry storage limit.', 'storage_limit', 409)
    now = time.time()
    if old:
        con.execute('UPDATE growthrova_leads SET revision=?,data_json=?,email_key=?,phone_key=?,updated=? WHERE id=?',
                    (base + 1, encoded, email_key, phone_key, now, lead_id))
    else:
        con.execute('INSERT INTO growthrova_leads VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (lead_id, *scope, ident, 1, encoded, email_key, phone_key, now, now))
    con.execute('INSERT INTO growthrova_lead_events VALUES(?,?,?,?,?,?,?)',
                (lead_id, base + 1, mutation, fingerprint, actor_id or scope[0], now, encoded))
    result = lead_snapshot(con, con.execute('SELECT * FROM growthrova_leads WHERE id=?', (lead_id,)).fetchone())
    return result, False


def register_lead_routes(app, repo, root, *, revalidate=None):
    with closing(repo._connect()) as con:
        con.executescript('''
          CREATE TABLE IF NOT EXISTS growthrova_leads(
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
            document_id TEXT NOT NULL, revision INTEGER NOT NULL, data_json TEXT NOT NULL,
            email_key TEXT, phone_key TEXT, created REAL NOT NULL, updated REAL NOT NULL,
            UNIQUE(owner_id,organisation_id,email_key), UNIQUE(owner_id,organisation_id,phone_key));
          CREATE INDEX IF NOT EXISTS growthrova_leads_campaign ON growthrova_leads(document_id,updated);
          CREATE TABLE IF NOT EXISTS growthrova_lead_events(
            lead_id TEXT NOT NULL, revision INTEGER NOT NULL, mutation_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, actor_id TEXT NOT NULL, occurred REAL NOT NULL,
            data_json TEXT NOT NULL, PRIMARY KEY(lead_id,revision), UNIQUE(lead_id,mutation_id));
        ''')

    def checked(con, organisation_id, ident, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return error
        if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
            raise OfflineDocumentAccessError('Campaign access changed')

    endpoint = root + '/<ident>/leads'

    @app.get(root + '/contacts')
    def growthrova_business_contacts(organisation_id):
        return business_enquiry_summary(organisation_id, tasks=False)

    @app.get(root + '/follow-through')
    def growthrova_business_follow_through(organisation_id):
        return business_enquiry_summary(organisation_id, tasks=True)

    @app.get(root + '/bookings')
    def growthrova_business_bookings(organisation_id):
        return business_enquiry_summary(organisation_id, tasks=False, bookings=True)

    @app.get(root + '/sales')
    def growthrova_business_sales(organisation_id):
        return business_enquiry_summary(organisation_id, tasks=False, sales=True)

    def business_enquiry_summary(organisation_id, *, tasks, bookings=False, sales=False):
        from business_growthrova_pipeline import enquiry_review
        observed_at = time.time()
        scope = repo._scope(organisation_id)
        if request.args:
            raise MarketingDraftError('Use the workspace filters for saved records.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            rows = con.execute('SELECT l.*,d.document_json FROM growthrova_leads l '
                               'JOIN offline_document_owners o ON o.draft_id=l.document_id '
                               'JOIN marketing_drafts d ON d.id=l.document_id '
                               'WHERE l.owner_id=? AND l.organisation_id=? '
                               'AND o.owner_id=l.owner_id AND o.organisation_id=l.organisation_id '
                               'ORDER BY l.updated DESC,l.id', scope).fetchall()
            # Existing bound: 1,000 contacts, each with at most 51 observed sales.
            # Return only the chosen projection; full records use the campaign read.
            contacts, work, appointments, sale_records = [], [], [], []
            for row in rows:
                data = json.loads(row['data_json'])
                identity = dict(id=row['id'], campaignId=row['document_id'],
                    campaignName=json.loads(row['document_json'])['name'],
                    revision=row['revision'], updated=row['updated'])
                if sales:
                    for sale in observed_sales(data):
                        if sale.get('state') in ('recorded', 'voided'):
                            saved = {key: sale[key] for key in ('amount', 'currency', 'date', 'state')}
                            saved['sourceReference'] = sale.get('sourceReference', '')
                            key = ('purchase:' + sale['id']) if 'id' in sale else 'original'
                            sale_records.append(dict(identity, saleKey=key,
                                data=dict(name=data['name'], sale=saved)))
                    continue
                if bookings:
                    booking = data.get('customerCare', {}).get('booking', {})
                    if booking.get('state') in ('confirmed', 'attended', 'cancelled', 'no_show'):
                        saved = {key: booking.get(key, '') for key in ('state', 'scheduledDate', 'outcomeDate')}
                        if booking.get('appointment'):
                            saved['appointment'] = booking['appointment']
                        appointments.append(dict(identity, data=dict(name=data['name'], customerCare=dict(booking=saved))))
                    continue
                if not tasks:
                    contacts.append(dict(identity,
                        data={key: data[key] for key in ('name', 'email', 'phone', 'status', 'source')},
                        review=enquiry_review(data, row['updated'], observed_at)))
                    continue
                actions = dict(human=dict(action=data.get('nextAction', ''),
                    dueDate=data.get('actionDueDate', ''), state=data.get('actionState', 'open'),
                    responsiblePerson=data.get('responsiblePerson', '')))
                actions.update({kind: data.get('customerCare', {}).get(kind, {})
                                for kind in ('retention', 'review')})
                for kind, task in actions.items():
                    if task.get('action', '').strip():
                        work.append(dict(identity, kind=kind, name=data['name'],
                            action=task['action'], dueDate=task.get('dueDate', ''),
                            state=task.get('state', 'open'),
                            responsiblePerson=task.get('responsiblePerson', '')))
            error = revalidate() if revalidate else None
            if error is not None:
                return error
            if repo._scope(organisation_id) != scope:
                raise OfflineDocumentAccessError('Business access changed')
        if sales:
            response = jsonify(sales=sale_records, total=len(sale_records))
        elif bookings:
            response = jsonify(bookings=appointments, total=len(appointments))
        elif tasks:
            response = jsonify(tasks=work, total=len(work), throughDate=datetime.now(timezone.utc).date().isoformat())
        else:
            response = jsonify(contacts=contacts, total=len(contacts), observedAt=observed_at)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get(root + '/recorded-results')
    def growthrova_recorded_results(organisation_id):
        from business_growthrova_overview import recorded_overview, measurement_overview
        from business_growthrova_usage import operation_usage
        from business_growthrova_plan_progress import plan_progress
        from business_growthrova_measurement import report_snapshot
        scope = repo._scope(organisation_id)
        if set(request.args) - {'period'} or len(request.args.getlist('period')) > 1:
            raise MarketingDraftError('Choose one supported reporting period.')
        period = request.args.get('period', '30')
        if period not in ('30', '90', 'all'):
            raise MarketingDraftError('Choose 30, 90 or all recording dates.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            rows = con.execute('SELECT l.document_id,l.created,l.updated,l.data_json FROM growthrova_leads l '
                               'JOIN offline_document_owners o ON o.draft_id=l.document_id '
                               'JOIN marketing_drafts d ON d.id=l.document_id '
                               'WHERE l.owner_id=? AND l.organisation_id=? '
                               'AND o.owner_id=l.owner_id AND o.organisation_id=l.organisation_id', scope).fetchall()
            now = time.time()
            result = recorded_overview(rows, period, now)
            from business_growthrova_pipeline import pipeline_overview, status_history
            result['pipeline'] = pipeline_overview(rows, now)
            result['statusHistory'] = status_history(con, scope, period, now)
            # All reads share one snapshot and exact owner/business/document join.
            # Current report rows exclude receipt history and superseded versions.
            def owned_rows(table, extra=''):
                return con.execute('SELECT r.* FROM ' + table + ' r '
                    'JOIN offline_document_owners o ON o.draft_id=r.document_id '
                    'JOIN marketing_drafts d ON d.id=r.document_id '
                    'WHERE r.owner_id=? AND r.organisation_id=? '
                    'AND o.owner_id=r.owner_id AND o.organisation_id=r.organisation_id ' + extra,
                    scope).fetchall()
            reports = [dict(report_snapshot(con, row), document_id=row['document_id'])
                       for row in owned_rows('growthrova_measurement_reports')]
            reads = owned_rows('growthrova_search_reads', "AND r.state='completed'")
            result['measurement'] = measurement_overview(reports, reads, period, now)
            result['operations'] = operation_usage(con, scope)
            result['planProgress'] = plan_progress(con, scope, now)
            from business_growthrova_paid_results import paid_delivery_results
            result['paidDelivery'] = paid_delivery_results(con, scope, now)
            from business_growthrova_organic_results import organic_delivery_results
            result['organicDelivery'] = organic_delivery_results(con, scope, now)
            from business_growthrova_followup_results import followup_delivery_results
            result['followupDelivery'] = followup_delivery_results(con, scope, now)
            from business_growthrova_social_observations import social_observation_overview
            result['socialEngagement'] = social_observation_overview(con, scope, period, now)
            error = revalidate() if revalidate else None
            if error is not None:
                return error
            if repo._scope(organisation_id) != scope:
                raise OfflineDocumentAccessError('Business access changed')
        response = jsonify(result)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get(endpoint)
    def growthrova_leads_list(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            rows = con.execute('SELECT * FROM growthrova_leads WHERE owner_id=? AND organisation_id=? '
                               'AND document_id=? ORDER BY updated DESC', (*scope, ident)).fetchall()
            # Summary listing omits snapshots; history is loaded only on opening a lead.
            leads = [dict(id=r['id'], campaignId=ident, revision=r['revision'], data=json.loads(r['data_json']),
                          created=r['created'], updated=r['updated']) for r in rows]
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        counts = {status: sum(lead['data']['status'] == status for lead in leads) for status in STATUSES}
        worker = app.extensions.get('growthrova_care_preparation')
        return jsonify(leads=leads, counts=counts, total=len(leads), attribution='owner_recorded',
                       careWorkerConfigured=bool(worker and worker.config.enabled is True), canSendMessages=False)

    @app.get(endpoint + '/<lead_id>')
    def growthrova_lead_read(organisation_id, ident, lead_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        _id(lead_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            row = con.execute('SELECT * FROM growthrova_leads WHERE id=? AND owner_id=? AND organisation_id=? '
                              'AND document_id=?', (lead_id, *scope, ident)).fetchone()
            if not row:
                raise OfflineDocumentAccessError('Enquiry access denied')
            result = lead_snapshot(con, row)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        return jsonify(result)

    @app.get(endpoint + '/<lead_id>/booking-calendar')
    def growthrova_booking_calendar(organisation_id, ident, lead_id):
        from business_growthrova_booking_calendar import booking_calendar
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        _id(lead_id)
        if (set(request.args) != {'revision'} or len(request.args.getlist('revision')) != 1
                or not re.fullmatch(r'[1-9][0-9]{0,2}', request.args['revision'])):
            raise MarketingDraftError('Choose the saved enquiry revision to download.')
        revision = int(request.args['revision'])
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            row = con.execute('SELECT * FROM growthrova_leads WHERE id=? AND owner_id=? AND organisation_id=? '
                              'AND document_id=?', (lead_id, *scope, ident)).fetchone()
            if not row:
                raise OfflineDocumentAccessError('Enquiry access denied')
            if row['revision'] != revision:
                raise MarketingDraftError('This booking changed. Refresh enquiries and review its saved times before downloading.', 'revision_conflict', 409)
            content = booking_calendar(row)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
        response = jsonify(filename='growthrova-booking.ics', content=content, revision=revision)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post(endpoint)
    def growthrova_lead_save(organisation_id, ident):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {'id', 'mutationId', 'expectedRevision', 'data'}:
            raise MarketingDraftError('An enquiry and save version are required.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            result, replayed = persist_lead(con, scope, ident, payload)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(**result, replayed=replayed)

    @app.post(endpoint + '/<lead_id>/booking-plan')
    @app.post(endpoint + '/<lead_id>/booking-outcome')
    def growthrova_booking_command(organisation_id, ident, lead_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        _id(lead_id)
        command = request.get_json(silent=True)
        planning = request.path.endswith('/booking-plan')
        fields = {'scheduledDate', 'appointment', 'evidence'} if planning else {'state', 'outcomeDate', 'evidence'}
        if not isinstance(command, dict) or set(command) != {'expectedRevision', 'mutationId'} | fields:
            raise MarketingDraftError('Review one saved booking, its proposed change and confirmation evidence.')
        base = command['expectedRevision']
        if type(base) is not int or not 1 <= base < 500:
            raise MarketingDraftError('Reopen a saved booking before changing it.')
        _id(command['mutationId'])
        if not planning and command['state'] not in ('attended', 'cancelled', 'no_show'):
            raise MarketingDraftError('Choose attendance, cancellation or did not attend.')
        if planning:
            from business_growthrova_customer_care import calendar_date
            scheduled = calendar_date(command['scheduledDate'], 'Booking date')
            appointment = command['appointment']
            if appointment is not None:
                from business_growthrova_booking_calendar import appointment_times
                # Resolve the proposed wall times now; no saved UTC instants or
                # client-derived booking dates may override the normaliser.
                if not isinstance(appointment, dict) or set(appointment) != {'localStart', 'localEnd', 'timeZone'}:
                    raise MarketingDraftError('Enter the new local start, end and timezone.')
                appointment, start, _ = appointment_times(appointment)
                scheduled = start.date().isoformat()
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            row = con.execute('SELECT * FROM growthrova_leads WHERE id=? AND owner_id=? AND organisation_id=? AND document_id=?',
                              (lead_id, *scope, ident)).fetchone()
            if not row:
                raise OfflineDocumentAccessError('Enquiry access denied')
            # Reconstruct the reviewed version for exact lost-response replay.
            # persist_lead rejects stale commands and altered replay bodies.
            historical = con.execute('SELECT data_json FROM growthrova_lead_events WHERE lead_id=? AND revision=?',
                                     (lead_id, base)).fetchone()
            if not historical:
                raise MarketingDraftError('Refresh saved bookings before changing this booking.', 'revision_conflict', 409)
            data = json.loads(historical['data_json'])
            booking = data.get('customerCare', {}).get('booking', {})
            if booking.get('state') != 'confirmed':
                raise MarketingDraftError('Only a reviewed confirmed booking can be changed here.', 'revision_conflict', 409)
            if planning:
                booking.update(scheduledDate=scheduled, evidence=command['evidence'])
                booking.pop('appointment', None)
                if appointment is not None:
                    booking['appointment'] = appointment
            else:
                booking.update({key: command[key] for key in ('state', 'outcomeDate', 'evidence')})
            result, replayed = persist_lead(con, scope, ident, dict(id=lead_id,
                mutationId=command['mutationId'], expectedRevision=base, data=data))
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        response = jsonify(**result, replayed=replayed)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post(endpoint + '/<lead_id>/task-plan')
    @app.post(endpoint + '/<lead_id>/task-state')
    def growthrova_task_command(organisation_id, ident, lead_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        _id(lead_id)
        command = request.get_json(silent=True)
        planning = request.path.endswith('/task-plan')
        fields = {'dueDate', 'responsiblePerson'} if planning else {'state'}
        if not isinstance(command, dict) or set(command) != {'expectedRevision', 'mutationId', 'kind'} | fields:
            raise MarketingDraftError('Review one saved task and its enquiry version.')
        base = command['expectedRevision']
        if type(base) is not int or not 1 <= base < 500:
            raise MarketingDraftError('Reopen a saved enquiry before recording task work.')
        _id(command['mutationId'])
        kind, state = command['kind'], command.get('state')
        if kind not in ('human', 'retention', 'review') or (not planning and state not in ('done', 'cancelled')):
            raise MarketingDraftError('Choose a supported open task and task change.')
        if planning:
            from business_growthrova_customer_care import calendar_date
            due = calendar_date(command['dueDate'], 'Action due date')
            person = _text(command['responsiblePerson'], 'Responsible person', 160).strip()
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            row = con.execute('SELECT * FROM growthrova_leads WHERE id=? AND owner_id=? AND organisation_id=? AND document_id=?',
                              (lead_id, *scope, ident)).fetchone()
            if not row:
                raise OfflineDocumentAccessError('Enquiry access denied')
            # Rebuild the original command, never a newer recurring occurrence.
            historical = con.execute('SELECT data_json FROM growthrova_lead_events WHERE lead_id=? AND revision=?',
                                     (lead_id, base)).fetchone()
            if not historical:
                raise MarketingDraftError('Refresh saved actions before recording work.', 'revision_conflict', 409)
            data = json.loads(historical['data_json'])
            task = (dict(action=data.get('nextAction', ''), state=data.get('actionState', 'open'))
                    if kind == 'human' else data.get('customerCare', {}).get(kind, {}))
            if not task.get('action', '').strip() or task.get('state', 'open') != 'open':
                raise MarketingDraftError('This task was not open in the reviewed version.', 'revision_conflict', 409)
            if planning and kind == 'human':
                data.update(actionDueDate=due, responsiblePerson=person)
            elif planning:
                data['customerCare'][kind].update(dueDate=due, responsiblePerson=person)
            elif kind == 'human':
                data['actionState'] = state
            else:
                data['customerCare'][kind]['state'] = state
            result, replayed = persist_lead(con, scope, ident, dict(id=lead_id,
                mutationId=command['mutationId'], expectedRevision=base, data=data))
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        response = jsonify(**result, replayed=replayed)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post(endpoint + '/<lead_id>/prepare-care')
    def growthrova_prepare_care(organisation_id, ident, lead_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        _id(lead_id)
        command = request.get_json(silent=True)
        if not isinstance(command, dict) or set(command) != {'expectedRevision', 'mutationId', 'throughDate'}:
            raise MarketingDraftError('A saved enquiry version and preparation date are required.')
        base = command['expectedRevision']
        if type(base) is not int or not 1 <= base < 500:
            raise MarketingDraftError('Reopen a saved enquiry before preparing repeat tasks.')
        _id(command['mutationId'])
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            row = con.execute('SELECT * FROM growthrova_leads WHERE id=? AND owner_id=? AND organisation_id=? AND document_id=?',
                              (lead_id, *scope, ident)).fetchone()
            if not row:
                raise OfflineDocumentAccessError('Enquiry access denied')
            # Rebuild the identical save on a lost-response retry, even after it committed.
            historical = con.execute('SELECT data_json FROM growthrova_lead_events WHERE lead_id=? AND revision=?', (lead_id, base)).fetchone()
            if not historical:
                raise MarketingDraftError('Reopen the enquiry before preparing tasks.', 'revision_conflict', 409)
            data, prepared = prepare_due_care(json.loads(historical['data_json']), command['throughDate'])
            if not prepared:
                if row['revision'] != base:
                    raise MarketingDraftError('Another editor saved this enquiry. Reopen it before preparing tasks.', 'revision_conflict', 409)
                result, replayed = lead_snapshot(con, row), False
            else:
                result, replayed = persist_lead(con, scope, ident, dict(id=lead_id, mutationId=command['mutationId'], expectedRevision=base, data=data), preparing_care=True)
            error = checked(con, organisation_id, ident, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(**result, replayed=replayed, prepared=prepared)
