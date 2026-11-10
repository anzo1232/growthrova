"""Opt-in enquiry/prospect message jobs; no credential lookup or worker host.

Adapters check(snapshot), deliver(snapshot, idempotency_key=...), and
reconcile(snapshot, idempotency_key=...) must be injected separately per channel.
Checks verify sender identity, destination/format eligibility and current grants.
Reconciliation is lookup-only. Business authorisation is separate from consent.
A failed receipt must definitively establish no message was sent; accepted or
missing acknowledgement remains uncertain. Sent is not proof of receipt/read.
"""
from contextlib import closing
from dataclasses import dataclass, field
import json
import time
import uuid

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError, _id
from business_social_delivery import _hash


@dataclass(frozen=True)
class FollowUpConfig:
    adapters: dict = field(default_factory=dict, repr=False)
    authorised: object = field(default=None, repr=False)
    clock: object = time.time
    mode: str = 'simulation'
    # Enquiry sender authority must never silently expand to prospect outreach.
    prospect_authorised: object = field(default=None, repr=False)


def snapshot(row, template_wording=None):
    data = json.loads(row['data_json'])
    channel = data.get('followUpChannel')
    if channel not in ('email', 'whatsapp') or not (template_wording or data.get('followUpDraft', '')).strip():
        raise MarketingDraftError('Save email or WhatsApp wording before approval.')
    recipient = data['email'] if channel == 'email' else data['phone']
    if not recipient or data[channel + 'Permission'] != 'recorded' or not data['permissionNotes']:
        raise MarketingDraftError('Record the recipient and actual permission for this channel before approval.')
    return dict(ownerId=row['owner_id'], organisationId=row['organisation_id'], campaignId=row['document_id'],
                leadId=row['id'], revision=row['revision'], channel=channel, recipient=recipient,
                wording=template_wording if template_wording is not None else data['followUpDraft'], permissionNotes=data['permissionNotes'])


def receipt(value):
    if not isinstance(value, dict):
        return None
    ident = value.get('id')
    if not isinstance(ident, str) or not ident.strip() or len(ident) > 300 or any(ord(c) < 32 for c in ident):
        return None
    return dict(id=ident, outcome=value.get('outcome') if value.get('outcome') in ('sent', 'simulated', 'accepted', 'failed') else 'unknown')


class FollowUpDelivery:
    LEASE_SECONDS = 120

    def __init__(self, repo, config=None):
        self.repo, self.config = repo, config or FollowUpConfig()
        if self.config.mode not in ('simulation', 'live'):
            raise ValueError('Explicit follow-up mode required')
        from business_growthrova_sender_setup import SenderSetup
        self.setup = SenderSetup(repo, self.config.clock)
        with closing(repo._connect()) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS growthrova_followup_jobs(
              job_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, lead_id TEXT NOT NULL,
              owner_id TEXT NOT NULL, organisation_id TEXT NOT NULL, snapshot_json TEXT NOT NULL,
              mode TEXT NOT NULL, state TEXT NOT NULL, approved_at REAL NOT NULL,
              claim_token TEXT, lease_until REAL, receipt_json TEXT,
              UNIQUE(lead_id,snapshot_json,mode))''')
            con.execute('''CREATE TABLE IF NOT EXISTS growthrova_sender_events(
              binding_hash TEXT NOT NULL, event_key TEXT NOT NULL, job_id TEXT,
              evidence_json TEXT NOT NULL, PRIMARY KEY(binding_hash,event_key))''')
            con.execute('CREATE INDEX IF NOT EXISTS growthrova_followup_pending ON growthrova_followup_jobs(state,approved_at)')
            con.commit()

    def available(self, channel):
        adapter = self.config.adapters.get(channel)
        return (callable(self.config.authorised) and adapter is not None
                and all(callable(getattr(adapter, name, None)) for name in ('check', 'deliver', 'reconcile')))

    def sender(self, owner, organisation, channel):
        adapter = self.config.adapters.get(channel)
        resolver = getattr(adapter, 'sender', None)
        try:
            return resolver(owner, organisation) if callable(resolver) else None
        except Exception:
            return None

    def prepared(self, lead, template_selection=None):
        template, wording = None, None
        if template_selection is not None:
            adapter = self.config.adapters.get('whatsapp')
            if ('prospectId' in lead.keys() or json.loads(lead['data_json']).get('followUpChannel') != 'whatsapp'
                    or not callable(getattr(adapter, 'prepare_template', None))):
                raise MarketingDraftError('Choose a connected WhatsApp template for a saved enquiry.')
            try:
                template, wording = adapter.prepare_template(lead['owner_id'], lead['organisation_id'], template_selection)
            except ValueError as exc:
                raise MarketingDraftError(str(exc), 'revision_conflict', 409) from exc
        snap = snapshot(lead, wording)
        if template is not None:
            snap['whatsappTemplate'] = template
        if 'prospectId' in lead.keys():
            snap.update(subjectKind='prospect', prospectId=lead['prospectId'],
                        prospectSource=lead['prospectSource'])
        sender = self.sender(snap['ownerId'], snap['organisationId'], snap['channel'])
        if sender is not None:
            snap['sender'] = sender
        adapter = self.config.adapters.get(snap['channel'])
        if getattr(adapter, 'requires_setup', False):
            with closing(self.repo._connect()) as con:
                snap['senderSetupRevision'] = self.setup.read(con, (snap['ownerId'], snap['organisationId']), snap['channel'])['revision']
        return snap

    def prospect(self, con, scope, ident, prospect_id):
        """Project a saved prospect into the existing message contract, never CRM.

        The legacy lead_id job column is a subject key; namespacing by campaign
        prevents collisions with other prospects and real enquiries. A campaign
        revision change deliberately fences every unstarted prospect message.
        """
        if not self.repo._owned(con, ident, scope):
            raise MarketingDraftError('Campaign unavailable.', 'access_denied', 403)
        row = con.execute('SELECT revision,document_json FROM marketing_drafts WHERE id=?', (ident,)).fetchone()
        item = next((p for p in json.loads(row['document_json']).get('prospects', [])
                     if p['id'] == prospect_id), None)
        if item is None:
            raise MarketingDraftError('Prospect unavailable.', 'access_denied', 403)
        permission = item.get('outreachPermission', {})
        from business_growthrova_prospects import outreach_allowed
        permitted = (bool(item['contactEmail']) and permission.get('email') == item['contactEmail']
                     and bool(permission.get('notes', '').strip()))
        data = dict(email=item['contactEmail'], phone='',
                    emailPermission='recorded' if permitted else 'unknown',
                    whatsappPermission='unknown', permissionNotes=permission.get('notes', ''),
                    followUpChannel='email' if outreach_allowed(item) else 'none',
                    followUpDraft=item['outreachDraft'])
        return dict(id='prospect:'+_hash(dict(campaign=ident, prospect=prospect_id)),
                    owner_id=scope[0], organisation_id=scope[1], document_id=ident,
                    revision=row['revision'], data_json=json.dumps(data), prospectId=prospect_id,
                    prospectSource={key: item[key] for key in ('name', 'sourceUrl', 'sourceQuote', 'observedOn')})

    def window_open(self, snap):
        adapter = self.config.adapters.get(snap['channel'])
        if 'whatsappTemplate' in snap:
            matches = getattr(adapter, 'template_matches', None)
            return callable(matches) and matches(snap) is True
        if snap['channel'] != 'whatsapp' or not getattr(adapter, 'requires_setup', False):
            return True
        binding = adapter.binding(snap['ownerId'], snap['organisationId'])
        window = self.setup.window((snap['ownerId'], snap['organisationId']), binding, snap['recipient'])
        return bool(window and window['open'])

    def authorised(self, snap, *, lookup=False):
        try:
            return (self.available(snap['channel'])
                    and (snap.get('subjectKind') != 'prospect' or
                         (callable(self.config.prospect_authorised) and
                          self.config.prospect_authorised(snap['ownerId'], snap['organisationId'], snap['channel']) is True))
                    and getattr(self.config.adapters[snap['channel']], 'mode', 'simulation') == self.config.mode
                    and (self.config.mode != 'live' or snap.get('sender') is not None)
                    and (lookup or not getattr(self.config.adapters[snap['channel']], 'requires_setup', False) or self.setup.matches(snap))
                    and self.config.authorised(snap['ownerId'], snap['organisationId'], snap['channel']) is True
                    and (not callable(getattr(self.config.adapters[snap['channel']], 'ready', None))
                         or self.config.adapters[snap['channel']].ready(snap['ownerId'], snap['organisationId']) is True))
        except Exception:
            return False

    def current(self, con, row):
        snap = json.loads(row['snapshot_json'])
        try:
            lead = (self.prospect(con, (row['owner_id'], row['organisation_id']), row['document_id'], snap['prospectId'])
                    if snap.get('subjectKind') == 'prospect' else
                    con.execute('SELECT * FROM growthrova_leads WHERE id=?', (row['lead_id'],)).fetchone())
            selection = ({key: snap['whatsappTemplate'][key] for key in ('contentSid', 'version', 'variables')}
                         if 'whatsappTemplate' in snap else None)
            return (lead is not None and self.prepared(lead, selection) == snap
                    and self.repo._owned(con, row['document_id'], (row['owner_id'], row['organisation_id'])))
        except MarketingDraftError:
            return False

    @staticmethod
    def public(row):
        return dict(jobId=row['job_id'], snapshot=json.loads(row['snapshot_json']), state=row['state'],
                    mode=row['mode'], approvedAt=row['approved_at'],
                    receipt=json.loads(row['receipt_json']) if row['receipt_json'] else None)

    def rows(self, con, lead_id):
        return con.execute('SELECT * FROM growthrova_followup_jobs WHERE lead_id=? ORDER BY approved_at DESC', (lead_id,)).fetchall()

    def claim(self):
        now = self.config.clock()
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE growthrova_followup_jobs SET state='uncertain' WHERE state='dispatching' AND lease_until<=?", (now,))
            con.execute("UPDATE growthrova_followup_jobs SET state='queued',claim_token=NULL,lease_until=NULL WHERE state='claimed' AND lease_until<=?", (now,))
            row = con.execute("SELECT * FROM growthrova_followup_jobs WHERE state='queued' AND mode=? ORDER BY approved_at LIMIT 1", (self.config.mode,)).fetchone()
            if not row:
                con.commit()
                return None
            token = uuid.uuid4().hex
            con.execute("UPDATE growthrova_followup_jobs SET state='claimed',claim_token=?,lease_until=? WHERE job_id=?", (token, now+self.LEASE_SECONDS, row['job_id']))
            con.commit()
        return dict(row), token

    def finish(self, job_id, token, value):
        result = receipt(value)
        expected = 'simulated' if self.config.mode == 'simulation' else 'sent'
        state = expected if result and result['outcome'] == expected else 'failed' if result and result['outcome'] == 'failed' else 'uncertain'
        with closing(self.repo._connect()) as con:
            con.execute("UPDATE growthrova_followup_jobs SET state=?,receipt_json=?,lease_until=NULL WHERE job_id=? AND claim_token=? AND mode=? AND state IN ('dispatching','uncertain')",
                        (state, json.dumps(result) if result else None, job_id, token, self.config.mode))
            con.commit()

    def run_one(self):
        claim = self.claim()
        if not claim:
            return False
        row, token = claim
        snap = json.loads(row['snapshot_json'])
        eligible = False
        try:
            eligible = self.authorised(snap) and self.window_open(snap) and self.config.adapters[snap['channel']].check(json.loads(row['snapshot_json'])) is True and self.authorised(snap)
        except Exception:
            pass
        # Slow eligibility runs outside the lock; pause/cancel can win the CAS.
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT * FROM growthrova_followup_jobs WHERE job_id=?', (row['job_id'],)).fetchone()
            if current['state'] != 'claimed' or current['claim_token'] != token or current['lease_until'] <= self.config.clock():
                return True
            valid = eligible and self.current(con, current) and self.authorised(snap) and self.window_open(snap)
            valid = valid and current['lease_until'] > self.config.clock()
            con.execute('UPDATE growthrova_followup_jobs SET state=?,lease_until=? WHERE job_id=?',
                        ('dispatching' if valid else 'blocked', self.config.clock()+self.LEASE_SECONDS, row['job_id']))
            con.commit()
        if valid:
            value = None
            try:
                value = self.config.adapters[snap['channel']].deliver(snap, idempotency_key=row['job_id'])
            except Exception:
                pass  # Unknown remote outcome is never automatically retried.
            self.finish(row['job_id'], token, value)
        return True

    def reconcile(self, row):
        if row['state'] != 'uncertain' or row['mode'] != self.config.mode:
            return
        snap = json.loads(row['snapshot_json'])
        if not self.authorised(snap, lookup=True):
            return
        try:
            adapter = self.config.adapters[snap['channel']]
            known = getattr(adapter, 'reconcile_known', None)
            prior = json.loads(row['receipt_json']) if row['receipt_json'] else None
            if callable(known) and prior and prior.get('id'):
                value = known(snap, idempotency_key=row['job_id'], reference=prior['id'])
            else:
                value = adapter.reconcile(snap, idempotency_key=row['job_id'])
        except Exception:
            return
        if value is not None and self.authorised(snap, lookup=True):
            self.finish(row['job_id'], row['claim_token'], value)


def register_followup_routes(app, repo, root, *, config=None, revalidate=None):
    delivery = FollowUpDelivery(repo, config)
    app.extensions['growthrova_followup_delivery'] = delivery
    endpoint = root + '/<ident>/leads/<lead_id>/follow-up'
    prospect_endpoint = root + '/<ident>/prospects/<lead_id>/follow-up'

    def checked(con, organisation_id, ident, lead_id, scope):
        error = revalidate() if revalidate else None
        if error is not None:
            return None, error
        if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
            raise MarketingDraftError('Business access changed.', 'access_denied', 403)
        if request.view_args.get('subject_kind') == 'prospect':
            return delivery.prospect(con, scope, ident, lead_id), None
        _id(lead_id)
        row = con.execute('SELECT * FROM growthrova_leads WHERE id=? AND document_id=? AND owner_id=? AND organisation_id=?', (lead_id, ident, *scope)).fetchone()
        if not row:
            raise MarketingDraftError('Enquiry unavailable.', 'access_denied', 403)
        return row, None

    @app.get(prospect_endpoint, defaults={'subject_kind': 'prospect'})
    @app.get(endpoint)
    def growthrova_followup_status(organisation_id, ident, lead_id, subject_kind='lead'):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            subject, error = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            jobs = [delivery.public(r) for r in delivery.rows(con, subject['id'])]
            for job in jobs:
                job['events'] = [json.loads(r['evidence_json']) for r in con.execute(
                    'SELECT evidence_json FROM growthrova_sender_events WHERE job_id=? ORDER BY rowid DESC LIMIT 20',
                    (job['jobId'],)).fetchall()]
        channels = ('email',) if subject_kind == 'prospect' else ('email', 'whatsapp')
        senders = {c: delivery.sender(*scope, c) for c in channels}
        with closing(repo._connect()) as con:
            setup = {c: delivery.setup.read(con, scope, c) for c in channels}
        available = {c: delivery.authorised(dict(ownerId=scope[0], organisationId=scope[1], channel=c, sender=senders[c], senderSetupRevision=setup[c]['revision'],
                                               **({'subjectKind': 'prospect'} if subject_kind == 'prospect' else {}))) for c in channels}
        with closing(repo._connect()) as con:
            lead, error = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
        adapter = delivery.config.adapters.get('whatsapp') if subject_kind == 'lead' else None
        try:
            binding = adapter.binding(*scope) if getattr(adapter, 'requires_setup', False) else None
        except Exception:
            binding = None
        window = delivery.setup.window(scope, binding, json.loads(lead['data_json'])['phone'])
        templates = adapter.templates(*scope) if callable(getattr(adapter, 'templates', None)) else []
        with closing(repo._connect()) as con:
            _, error = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
        return jsonify(requiresSetup={c: bool(getattr(delivery.config.adapters.get(c), 'requires_setup', False)) for c in channels}, setup=setup, inboundWindow=window, whatsappTemplates=templates, jobs=jobs, mode=delivery.config.mode, senders=senders,
                       available=available)

    @app.post(prospect_endpoint + '/<action>', defaults={'subject_kind': 'prospect'})
    @app.post(endpoint + '/<action>')
    def growthrova_followup_action(organisation_id, ident, lead_id, action, subject_kind='lead'):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        request.max_content_length = 20000
        data = request.get_json(silent=True)
        if action not in ('approve', 'pause', 'cancel', 'reconcile') or not isinstance(data, dict):
            raise MarketingDraftError('Choose a supported follow-up action.')
        if action == 'approve':
            keys = set(data) - {'whatsappTemplate', 'expectedTemplateWording'}
            if keys not in ({'expectedRevision', 'expectedMode'}, {'expectedRevision', 'expectedMode', 'expectedSender'}, {'expectedRevision', 'expectedMode', 'expectedSender', 'expectedSenderSetupRevision'}) or type(data['expectedRevision']) is not int:
                raise MarketingDraftError('Approve the exact saved contact version.')
            if ('whatsappTemplate' in data) != ('expectedTemplateWording' in data) or ('whatsappTemplate' in data and not isinstance(data['whatsappTemplate'], dict)):
                raise MarketingDraftError('Review the complete template and exact wording before approval.')
        elif data != {}:
            raise MarketingDraftError('Use an empty request for this action.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            lead, error = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            subject_id = lead['id']
            if action == 'approve':
                if lead['revision'] != data['expectedRevision']:
                    raise MarketingDraftError('Saved contact changed. Reopen and review before approval.', 'revision_conflict', 409)
                if data['expectedMode'] != delivery.config.mode:
                    raise MarketingDraftError('Delivery mode changed. Check status and review the approval again.', 'revision_conflict', 409)
                snap = delivery.prepared(lead, data.get('whatsappTemplate'))
                if 'whatsappTemplate' in data and data['expectedTemplateWording'] != snap['wording']:
                    raise MarketingDraftError('Template wording changed. Check status and review again.', 'revision_conflict', 409)
                if data.get('expectedSenderSetupRevision') != snap.get('senderSetupRevision'):
                    raise MarketingDraftError('Sender request changed. Check status and review before approval.', 'revision_conflict', 409)
                if data.get('expectedSender') != snap.get('sender'):
                    raise MarketingDraftError('Business sender changed. Check status and review before approval.', 'revision_conflict', 409)
                encoded = json.dumps(snap, sort_keys=True, separators=(',', ':'))
                job_id = _hash(dict(snapshot=snap, mode=delivery.config.mode))
                old = con.execute('SELECT * FROM growthrova_followup_jobs WHERE job_id=?', (job_id,)).fetchone()
                # Never create another send while a prior outcome remains unknown.
                if con.execute("SELECT 1 FROM growthrova_followup_jobs WHERE lead_id=? AND state IN ('dispatching','uncertain')", (subject_id,)).fetchone():
                    raise MarketingDraftError('An earlier message needs confirmation. Check its outcome before approving another.', 'outcome_uncertain', 409)
                if not old or old['state'] in ('paused', 'blocked'):
                    con.execute("UPDATE growthrova_followup_jobs SET state='cancelled',claim_token=NULL,lease_until=NULL WHERE lead_id=? AND state IN ('queued','claimed','paused','blocked') AND job_id<>?", (subject_id, job_id))
                    state = 'queued' if delivery.authorised(snap) else 'blocked'
                    if old:
                        con.execute('UPDATE growthrova_followup_jobs SET state=?,claim_token=NULL,lease_until=NULL,approved_at=? WHERE job_id=?', (state, delivery.config.clock(), job_id))
                    else:
                        con.execute('INSERT INTO growthrova_followup_jobs(job_id,document_id,lead_id,owner_id,organisation_id,snapshot_json,mode,state,approved_at) VALUES(?,?,?,?,?,?,?,?,?)',
                                    (job_id, ident, subject_id, *scope, encoded, delivery.config.mode, state, delivery.config.clock()))
            elif action in ('pause', 'cancel'):
                con.execute("UPDATE growthrova_followup_jobs SET state=?,claim_token=NULL,lease_until=NULL WHERE lead_id=? AND state IN ('queued','claimed','paused','blocked')", ('paused' if action == 'pause' else 'cancelled', subject_id))
            rows = delivery.rows(con, subject_id)
            _, error = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            con.commit()
        if action == 'reconcile':
            for row in rows:
                delivery.reconcile(row)
        return growthrova_followup_status(organisation_id, ident, lead_id, subject_kind)

    @app.route(prospect_endpoint + '/sender-setup/<channel>', methods=['GET', 'POST'], defaults={'subject_kind': 'prospect'})
    @app.route(endpoint + '/sender-setup/<channel>', methods=['GET', 'POST'])
    def growthrova_sender_setup(organisation_id, ident, lead_id, channel, subject_kind='lead'):
        if channel not in ('email', 'whatsapp'):
            raise MarketingDraftError('Choose email or WhatsApp.')
        if subject_kind == 'prospect' and channel != 'email':
            raise MarketingDraftError('Prospect outreach supports individually reviewed email only.')
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        request.max_content_length = 4000
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE' if request.method == 'POST' else 'BEGIN')
            _, error = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            if request.method == 'POST':
                result = delivery.setup.save(con, scope, channel, request.get_json(silent=True))
            else:
                result = delivery.setup.read(con, scope, channel)
            _, error = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            con.commit()
        return jsonify(result)

    @app.post(endpoint + '/verify-inbound')
    def growthrova_verify_inbound(organisation_id, ident, lead_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        request.max_content_length = 2000
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'reference', 'expectedRevision', 'expectedSender', 'expectedSenderSetupRevision'}
                or type(data['expectedRevision']) is not int or type(data['expectedSenderSetupRevision']) is not int):
            raise MarketingDraftError('Review the saved enquiry and sender before checking an inbound reference.')
        adapter = delivery.config.adapters.get('whatsapp')
        if not getattr(adapter, 'requires_setup', False) or not callable(getattr(adapter, 'inbound', None)):
            raise MarketingDraftError('Connect a dedicated WhatsApp sender before verifying an inbound message.', 'not_connected', 409)
        if not adapter.reference(data['reference']):
            raise MarketingDraftError('Use a valid inbound message reference.')
        with closing(repo._connect()) as con:
            lead, error = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            recipient = json.loads(lead['data_json'])['phone']
            snap = dict(ownerId=scope[0], organisationId=scope[1], channel='whatsapp', sender=data['expectedSender'], senderSetupRevision=data['expectedSenderSetupRevision'])
            if lead['revision'] != data['expectedRevision'] or not delivery.authorised(snap):
                raise MarketingDraftError('Saved enquiry or sender is unavailable. Reopen and review.', 'revision_conflict', 409)
        binding = adapter.binding(*scope)
        if not binding or adapter.identity(binding) != data['expectedSender']:
            raise MarketingDraftError('Business sender changed. Review again.', 'revision_conflict', 409)
        try:
            evidence = adapter.inbound(binding, data['reference'], recipient, delivery.config.clock())
        except Exception:
            evidence = None
        if not evidence:
            raise MarketingDraftError('No recent received WhatsApp message was verified for this sender and contact. Nothing was sent.', 'inbound_unverified', 409)
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            lead, error = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            current_binding = adapter.binding(*scope)
            if (lead['revision'] != data['expectedRevision'] or not delivery.authorised(snap)
                    or current_binding != binding or not delivery.config.clock()-86400 < evidence['occurredAt'] <= delivery.config.clock()):
                raise MarketingDraftError('Enquiry, sender or inbound window changed. Review again.', 'revision_conflict', 409)
            delivery.setup.record(con, scope, binding, recipient, evidence)
            _, error = checked(con, organisation_id, ident, lead_id, scope)
            if error is not None:
                return error
            con.commit()
        return growthrova_followup_status(organisation_id, ident, lead_id)

    return delivery
