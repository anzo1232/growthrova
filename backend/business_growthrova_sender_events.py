"""Opt-in signed callbacks. No replies, permission grants or contact creation.

Install twilio and svix only in a dedicated callback host before enabling it.
Resolvers supply exact public URLs (never proxy headers) and dedicated secrets.
Twilio callbacks have no reliable event time: inbound windows use GET evidence.
"""
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from urllib.parse import urlsplit

from flask import request
from business_social_delivery import _hash

ENDPOINT = 'growthrova_sender_event'
PATH = '/api/growthrova/sender-events/<token>'


@dataclass(frozen=True)
class SenderEventBinding:
    owner_id: str
    organisation_id: str
    channel: str
    sender_version: str
    public_url: str
    signing_secret: str = field(repr=False)


@dataclass(frozen=True)
class SenderEventConfig:
    enabled: bool = False
    resolve: object = field(default=None, repr=False)


def verify(binding, provider):
    """Official SDKs; absent packages and malformed signatures fail closed."""
    if provider == 'twilio':
        from twilio.request_validator import RequestValidator
        if request.mimetype != 'application/x-www-form-urlencoded':
            return None
        if not RequestValidator(binding.signing_secret).validate(
                binding.public_url, request.form, request.headers.get('X-Twilio-Signature', '')):
            return None
        if any(len(request.form.getlist(k)) != 1 for k in request.form):
            return None
        return request.form.to_dict()
    if provider == 'resend':
        from svix.webhooks import Webhook
        if request.mimetype != 'application/json':
            return None
        raw = request.get_data()
        Webhook(binding.signing_secret).verify(raw, {k.lower(): v for k, v in request.headers.items()})
        # Current Svix versions return None after verification; parse only AFTER
        # verification, preserving the exact signed bytes for the SDK.
        return json.loads(raw)
    return None


def event_time(value, now):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        stamp = date.timestamp() if date.tzinfo else None
        return stamp if stamp is not None and 0 < stamp <= now else None
    except (ValueError, OverflowError):
        return None


def register_sender_events(app, delivery, config=None):
    config = config or SenderEventConfig()
    repo = delivery.repo
    with closing(repo._connect()) as con:
        con.execute('CREATE INDEX IF NOT EXISTS growthrova_sender_event_job ON growthrova_sender_events(job_id)')
        con.commit()

    def resolve(token):
        if config.enabled is not True or not callable(config.resolve):
            return None
        binding = config.resolve(token)
        if not isinstance(binding, SenderEventBinding) or binding.channel not in ('email', 'whatsapp'):
            return None
        url = urlsplit(binding.public_url)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment
                or url.path != PATH.replace('<token>', token) or not binding.signing_secret):
            return None
        adapter = delivery.config.adapters.get(binding.channel)
        if (getattr(adapter, 'provider', None) != {'email':'resend', 'whatsapp':'twilio'}[binding.channel]
                or delivery.config.mode != 'live' or not getattr(adapter, 'requires_setup', False)
                or not callable(delivery.config.authorised)
                or delivery.config.authorised(binding.owner_id, binding.organisation_id, binding.channel) is not True):
            return None
        sender = adapter.binding(binding.owner_id, binding.organisation_id)
        if not sender or not sender.enabled or sender.version != binding.sender_version:
            return None
        return binding, adapter, sender

    @app.post(PATH, endpoint=ENDPOINT)
    def receive(token):
        request.max_content_length = 32768
        if not re.fullmatch('[a-f0-9]{32}', token) or request.query_string:
            return '', 404
        try:
            resolved = resolve(token)
            if not resolved:
                return '', 404
            binding, adapter, sender = resolved
            try:
                payload = verify(binding, adapter.provider)
            except ImportError:
                return '', 503  # Dedicated host has not installed its verifier.
            except Exception:
                return '', 403
            if not isinstance(payload, dict):
                return '', 403
            scope = (binding.owner_id, binding.organisation_id)
            binding_key = _hash(dict(token=token, scope=scope, channel=binding.channel,
                                     sender=delivery.setup.binding_hash(sender)))
            now = delivery.config.clock()
            inbound = False
            if adapter.provider == 'twilio':
                reference = payload.get('MessageSid')
                if payload.get('AccountSid') != sender.account_id or not adapter.reference(reference):
                    return '', 403
                inbound = payload.get('MessageStatus', payload.get('SmsStatus')) == 'received'
                status = 'inbound' if inbound else payload.get('MessageStatus')
                event_key = _hash(dict(reference=reference, status=status))
                recipient = payload.get('From' if inbound else 'To', '')
                if (payload.get('To' if inbound else 'From') != 'whatsapp:'+sender.address
                        or not recipient.startswith('whatsapp:') or not adapter.recipient(recipient[9:])):
                    return '', 403
                recipient = recipient[9:]
                occurred = None  # Verify the original time with the dedicated GET below.
            else:
                data = payload.get('data')
                if not isinstance(data, dict):
                    return '', 400
                reference, status = data.get('email_id'), payload.get('type')
                if (not adapter.reference(reference) or data.get('from') != sender.address
                        or not isinstance(data.get('to'), list) or len(data['to']) != 1
                        or not adapter.recipient(data['to'][0])):
                    return '', 403
                recipient = data['to'][0]
                occurred = event_time(payload.get('created_at'), now)
                if occurred is None:
                    return '', 400
                event_key = _hash(dict(reference=reference, status=status, occurred=occurred))
            allowed = ('inbound', 'sent', 'delivered', 'read', 'failed', 'undelivered') if adapter.provider == 'twilio' else ('email.sent', 'email.delivered', 'email.bounced', 'email.complained', 'email.failed')
            if status not in allowed:
                return '', 204
            with closing(repo._connect()) as con:
                if con.execute('SELECT 1 FROM growthrova_sender_events WHERE binding_hash=? AND event_key=?', (binding_key, event_key)).fetchone():
                    return '', 204
                if con.execute('SELECT COUNT(*) FROM growthrova_sender_events WHERE binding_hash=?', (binding_key,)).fetchone()[0] >= 10000:
                    return '', 503
                if inbound:
                    known = con.execute('SELECT document_id FROM growthrova_leads WHERE owner_id=? AND organisation_id=? AND phone_key=? LIMIT 1', (*scope, recipient[1:])).fetchone()
                    if not known or not repo._owned(con, known['document_id'], scope):
                        return '', 204
                    job = None
                else:
                    rows = con.execute("SELECT * FROM growthrova_followup_jobs WHERE owner_id=? AND organisation_id=? AND mode='live' AND json_extract(receipt_json,'$.id')=?", (*scope, reference)).fetchall()
                    matches = [r for r in rows if json.loads(r['snapshot_json']).get('sender') == adapter.identity(sender)
                               and json.loads(r['snapshot_json']).get('recipient') == recipient
                               and repo._owned(con, r['document_id'], scope)]
                    if len(matches) != 1:
                        return '', 204  # Never attach unknown IDs to an uncertain job.
                    job = matches[0]
            if inbound:
                evidence = adapter.inbound(sender, reference, recipient, now)
                if not evidence:
                    return '', 204
                occurred = evidence['occurredAt']
            elif adapter.provider == 'twilio':
                # Signed callbacks lack an original event timestamp. Keep observation
                # time distinct; never use it to open a customer-service window.
                occurred = None
            evidence = dict(reference=reference, status=status, occurredAt=occurred, observedAt=delivery.config.clock())
            with closing(repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                if resolve(token) != resolved:
                    return '', 409
                if con.execute('SELECT COUNT(*) FROM growthrova_sender_events WHERE binding_hash=?', (binding_key,)).fetchone()[0] >= 10000:
                    return '', 503
                if inbound:
                    known = con.execute('SELECT document_id FROM growthrova_leads WHERE owner_id=? AND organisation_id=? AND phone_key=? LIMIT 1', (*scope, recipient[1:])).fetchone()
                    if not known or not repo._owned(con, known['document_id'], scope):
                        return '', 204
                    delivery.setup.record(con, scope, sender, recipient, evidence)
                elif not repo._owned(con, job['document_id'], scope):
                    return '', 204
                con.execute('INSERT OR IGNORE INTO growthrova_sender_events VALUES(?,?,?,?)',
                            (binding_key, event_key, job['job_id'] if job else None, json.dumps(evidence)))
                # Positive evidence can resolve a known uncertain send. Negative
                # delivery events do not prove that nothing was sent; retain them
                # separately instead of enabling a retry through a failure state.
                if job and status in ('sent', 'delivered', 'read', 'email.sent', 'email.delivered'):
                    con.execute("UPDATE growthrova_followup_jobs SET state='sent',lease_until=NULL WHERE job_id=? AND state IN ('dispatching','uncertain') AND json_extract(receipt_json,'$.id')=?", (job['job_id'], reference))
                con.commit()
            # Empty TwiML explicitly produces no reply. Other callbacks accept 204.
            return ('<Response/>', 200, {'Content-Type':'application/xml'}) if inbound else ('', 204)
        except Exception:
            # Do not disclose payloads, secrets, contacts or provider errors.
            return '', 503

    return config
