"""Explicitly configured transports for Growthrova's durable follow-up worker.

No environment, account discovery, retries, worker installation or sender grants.
Bindings come from a trusted operator resolver, keyed by owner AND business.
Changing identity/subject/credentials/grants must rotate the connection version.
`eligible` must freshly check sender grants, suppression/opt-outs, permitted costs
and (WhatsApp) trusted inbound service-window evidence. Stored lead permission
alone is insufficient. Templates require separate configured catalogue/authority;
no bulk automation is installed.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import json
import re

import requests


@dataclass(frozen=True)
class SenderBinding:
    owner_id: str
    organisation_id: str
    version: str
    address: str
    # Only a verified domain/sender owned by this business may be configured.
    verified: bool = False
    enabled: bool = False
    subject: str = ''
    account_id: str = ''
    secret: str = field(default='', repr=False)


def clean(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit and not any(ord(c) < 32 for c in value)


def valid_recipient(channel, address):
    if not isinstance(address, str):
        return False
    return bool(re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', address)) if channel == 'email' else bool(re.fullmatch(r'\+[1-9][0-9]{7,14}', address))


class BusinessSender:
    """Resolver and eligibility are trusted server callbacks, never request data."""
    provider = channel = ''
    mode = 'live'
    requires_setup = True

    def __init__(self, resolve, eligible, *, http=None):
        self.resolve, self.eligible, self.http = resolve, eligible, http

    def binding(self, owner, organisation):
        value = self.resolve(owner, organisation, self.channel)
        if (not isinstance(value, SenderBinding) or value.owner_id != owner
                or value.organisation_id != organisation or not clean(value.version, 100)
                or not clean(value.address, 254) or not value.verified):
            return None
        return value if self.valid(value) else None

    def valid(self, binding):
        raise NotImplementedError

    def sender(self, owner, organisation):
        binding = self.binding(owner, organisation)
        if not binding:
            return None
        return dict(provider=self.provider, address=binding.address,
                    version=binding.version, subject=binding.subject if self.channel == 'email' else '')

    def ready(self, owner, organisation):
        binding = self.binding(owner, organisation)
        return bool(binding and binding.enabled and binding.secret)

    def check(self, snap):
        try:
            binding = self.binding(snap['ownerId'], snap['organisationId'])
            return bool(snap['channel'] == self.channel and binding and binding.enabled
                        and binding.secret and snap.get('sender') == self.sender(snap['ownerId'], snap['organisationId'])
                        and self.eligible(deepcopy(snap)) is True and self.recipient(snap['recipient']))
        except Exception:
            return False

    def recipient(self, address):
        return valid_recipient(self.channel, address)

    def remote(self, binding, method, url, **options):
        # Dedicated credentials only; no netrc, ambient proxy, cookies or retries.
        options.update(timeout=15, allow_redirects=False)
        if self.http is not None:
            return self.http.request(method, url, **options)
        with requests.Session() as session:
            session.trust_env = False
            return session.request(method, url, **options)

    def deliver(self, snap, *, idempotency_key):
        if not self.check(snap):
            return None
        binding = self.binding(snap['ownerId'], snap['organisationId'])
        # Resolve once more and compare the actual binding used for the request.
        if not binding or self.identity(binding) != snap.get('sender') or not binding.enabled:
            return None
        return self.send(binding, snap, idempotency_key)

    def identity(self, binding):
        return dict(provider=self.provider, address=binding.address, version=binding.version,
                    subject=binding.subject if self.channel == 'email' else '')

    def reconcile(self, snap, *, idempotency_key):
        # A lost acknowledgement has no safe provider ID. Never POST to recover it,
        # including after Resend's 24h idempotency retention expires.
        return None

    def reconcile_known(self, snap, *, idempotency_key, reference):
        if not self.reference(reference) or snap.get('channel') != self.channel:
            return None
        binding = self.binding(snap['ownerId'], snap['organisationId'])
        if not binding or self.identity(binding) != snap.get('sender') or not binding.enabled:
            return None
        return self.lookup(binding, reference)


class ResendEmailSender(BusinessSender):
    provider, channel = 'resend', 'email'

    def valid(self, binding):
        return self.recipient(binding.address) and clean(binding.subject, 200)

    @staticmethod
    def reference(value):
        return isinstance(value, str) and bool(re.fullmatch(r'[a-fA-F0-9-]{36}', value))

    def send(self, binding, snap, key):
        response = self.remote(binding, 'POST', 'https://api.resend.com/emails',
                               headers={'Authorization': 'Bearer ' + binding.secret, 'Idempotency-Key': key},
                               json={'from': binding.address, 'to': [snap['recipient']],
                                     'subject': binding.subject, 'text': snap['wording']})
        if response.status_code not in (200, 201):
            return None  # No generic HTTP error proves a safe retry.
        ident = response.json().get('id')
        return dict(id=ident, outcome='accepted') if self.reference(ident) else None

    def lookup(self, binding, reference):
        response = self.remote(binding, 'GET', 'https://api.resend.com/emails/' + reference,
                               headers={'Authorization': 'Bearer ' + binding.secret})
        if response.status_code != 200:
            return None
        data = response.json()
        if data.get('id') != reference:
            return None
        state = 'sent' if data.get('last_event') in ('sent', 'delivered', 'opened', 'clicked') else 'unknown'
        return dict(id=reference, outcome=state)


class TwilioWhatsAppSender(BusinessSender):
    provider, channel = 'twilio', 'whatsapp'

    def __init__(self, resolve, eligible, *, http=None, template_resolve=None, template_authorised=None):
        super().__init__(resolve, eligible, http=http)
        self.template_resolve, self.template_authorised = template_resolve, template_authorised

    def templates(self, owner, organisation):
        from business_growthrova_whatsapp_templates import catalogue
        try:
            return catalogue(self.binding(owner, organisation), self.template_resolve)
        except Exception:
            return []

    def prepare_template(self, owner, organisation, selection):
        from business_growthrova_whatsapp_templates import prepare
        return prepare(self.templates(owner, organisation), selection)

    def template_matches(self, snap):
        try:
            frozen = snap['whatsappTemplate']
            selection = {key: frozen[key] for key in ('contentSid', 'version', 'variables')}
            template, wording = self.prepare_template(snap['ownerId'], snap['organisationId'], selection)
            return template == frozen and wording == snap['wording']
        except (KeyError, TypeError, ValueError):
            return False

    def valid(self, binding):
        return self.recipient(binding.address) and bool(re.fullmatch(r'AC[a-fA-F0-9]{32}', binding.account_id))

    @staticmethod
    def reference(value):
        return isinstance(value, str) and bool(re.fullmatch(r'SM[a-fA-F0-9]{32}', value))

    def check(self, snap):
        # Free text still needs an open window. Templates additionally require a
        # distinct fresh cost/grant/suppression/approval policy callback.
        if 'whatsappTemplate' in snap:
            try:
                if (not self.template_matches(snap) or not callable(self.template_authorised)
                        or self.template_authorised(deepcopy(snap)) is not True):
                    return False
            except Exception:
                return False
        return super().check(snap) and len(snap.get('wording', '')) <= 1600

    @staticmethod
    def url(binding):
        return 'https://api.twilio.com/2010-04-01/Accounts/' + binding.account_id + '/Messages'

    def send(self, binding, snap, key):
        payload = {'From': 'whatsapp:' + binding.address, 'To': 'whatsapp:' + snap['recipient']}
        if 'whatsappTemplate' in snap:
            if not self.template_matches(snap):
                return None
            payload.update(ContentSid=snap['whatsappTemplate']['contentSid'],
                           ContentVariables=json.dumps(snap['whatsappTemplate']['variables'], ensure_ascii=False))
        else:
            payload['Body'] = snap['wording']
        response = self.remote(binding, 'POST', self.url(binding) + '.json',
                               auth=(binding.account_id, binding.secret),
                               data=payload)
        if response.status_code != 201:
            return None
        data = response.json()
        ident = data.get('sid')
        if not self.reference(ident):
            return None
        return dict(id=ident, outcome='sent' if data.get('status') in ('sent', 'delivered', 'read') else 'accepted')

    def lookup(self, binding, reference):
        response = self.remote(binding, 'GET', self.url(binding) + '/' + reference + '.json',
                               auth=(binding.account_id, binding.secret))
        if response.status_code != 200:
            return None
        data = response.json()
        if data.get('sid') != reference or data.get('account_sid') != binding.account_id:
            return None
        state = 'sent' if data.get('status') in ('sent', 'delivered', 'read') else 'failed' if data.get('status') == 'failed' else 'unknown'
        return dict(id=reference, outcome=state)

    def inbound(self, binding, reference, recipient, now):
        """GET-only verification; provider time prevents webhook/reference replay extending a window."""
        from email.utils import parsedate_to_datetime
        if not self.reference(reference) or not self.recipient(recipient):
            return None
        response = self.remote(binding, 'GET', self.url(binding) + '/' + reference + '.json',
                               auth=(binding.account_id, binding.secret))
        if response.status_code != 200:
            return None
        data = response.json()
        if (data.get('sid') != reference or data.get('account_sid') != binding.account_id
                or data.get('direction') != 'inbound' or data.get('status') != 'received'
                or data.get('from') != 'whatsapp:' + recipient
                or data.get('to') != 'whatsapp:' + binding.address):
            return None
        try:
            date = parsedate_to_datetime(data['date_sent'])
            if date.tzinfo is None:
                return None
            occurred = date.timestamp()
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if not now - 86400 < occurred <= now:
            return None
        return dict(reference=reference, occurredAt=occurred)
