"""Opt-in WordPress article transports; never update an existing article.

Draft handoff is the default. Publication requires a separate adapter, explicit
operator binding permission and a new saved approval against its distinct site
identity; switching connectors never promotes a remote draft.

The trusted host resolves dedicated, versioned credentials; nothing reads env or
ambient accounts. WordPress has no native create idempotency key. This adapter
MUST run behind OrganicDelivery's persisted one-attempt dispatch fence. A missing
acknowledgement is lookup-only forever, including when the slug lookup is empty.
Rotate version on any credential, endpoint, user or authority change. The host
must restrict network egress to its reviewed public WordPress origin.
"""
from dataclasses import dataclass, field
import hashlib
import html
import ipaddress
import json
import re
import time
from urllib.parse import urlsplit

import requests


@dataclass(frozen=True)
class WordPressBinding:
    owner_id: str
    organisation_id: str
    site_id: str
    label: str
    version: str
    rest_root: str
    username: str = field(repr=False)
    application_password: str = field(repr=False)
    enabled: bool = False
    verified: bool = False
    publication_enabled: bool = False


class WordPressDraftAdapter:
    mode = 'live'  # A real remote draft, explicitly NOT a simulation/publication.
    delivery_outcome = 'drafted'
    post_status = 'draft'
    policy_identity = 'wordpress-draft-v1'

    def __init__(self, resolve=None, authorised=None, *, http=None):
        self.resolve, self.authority, self.http = resolve, authorised, http

    def binding(self, scope):
        if not callable(self.resolve) or not callable(self.authority):
            raise ValueError('Dedicated WordPress site authority required')
        value = self.resolve(*scope)
        if (not isinstance(value, WordPressBinding) or value.enabled is not True
                or value.verified is not True or (value.owner_id, value.organisation_id) != scope):
            raise ValueError('WordPress site unavailable')
        for text in (value.site_id, value.label, value.version, value.rest_root,
                     value.username, value.application_password):
            if (not isinstance(text, str) or not text.strip() or len(text) > 500
                    or any(ord(c) < 32 for c in text)):
                raise ValueError('Invalid WordPress binding')
        if ':' in value.username:
            raise ValueError('Invalid WordPress user')
        parsed = urlsplit(value.rest_root)
        if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query
                or parsed.fragment or parsed.port not in (None, 443) or not parsed.hostname
                or not re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname)
                or '.' not in parsed.hostname or parsed.hostname.endswith(('.localhost', '.local', '.internal'))
                or not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*/wp-json', parsed.path)):
            raise ValueError('A reviewed HTTPS WordPress REST root is required')
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            raise ValueError('A reviewed public WordPress hostname is required')
        if self.post_status == 'publish' and value.publication_enabled is not True:
            raise ValueError('Separate WordPress publication authority required')
        if self.authority(*scope, value) is not True:
            raise ValueError('WordPress site authority unavailable')
        return value

    @classmethod
    def identity(cls, binding):
        version = hashlib.sha256(json.dumps([binding.site_id, binding.label, binding.version,
            binding.rest_root, binding.username, cls.policy_identity], separators=(',', ':')).encode()).hexdigest()
        return dict(siteId=binding.site_id, label=binding.label, version=version)

    def site(self, owner, business):
        try:
            return self.identity(self.binding((owner, business)))
        except Exception:
            return None

    def authorised(self, owner, business, site):
        current = self.site(owner, business)
        return current is not None and current == site

    def selected(self, snap):
        binding = self.binding((snap['ownerId'], snap['organisationId']))
        if (self.identity(binding) != snap['site'] or snap['mode'] != self.mode
                or snap.get('deliveryOutcome', 'published') != self.delivery_outcome
                or snap.get('operation') != 'create_plain_text_article'):
            raise ValueError('WordPress approval changed')
        return binding

    def guard(self, snap, binding):
        if self.selected(snap) != binding:
            raise ValueError('WordPress authority changed')

    def check(self, snap):
        # Local policy only; provider readiness is not asserted from metadata.
        self.selected(snap)
        return True

    @classmethod
    def payload(cls, snap, key):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
            raise ValueError('A durable organic job identity is required')
        if any(not isinstance(snap.get(k), str) or not snap[k].strip() for k in ('title', 'body')):
            raise ValueError('Saved article wording is required')
        # Plain text cannot become executable HTML; provenance stays out of body.
        return dict(slug='growthrova-'+key, status=cls.post_status,
                    title=html.escape(snap['title'], quote=False),
                    content='<p>'+html.escape(snap['body'], quote=False).replace('\n', '<br />\n')+'</p>',
                    comment_status='closed', ping_status='closed')

    def wire(self, method, binding, **options):
        started = time.monotonic()
        with requests.Session() as session:
            session.trust_env = False
            transport = self.http or session
            with getattr(transport, method)(binding.rest_root+'/wp/v2/posts',
                    auth=(binding.username, binding.application_password),
                    headers={'Accept': 'application/json'}, timeout=(3, 10),
                    allow_redirects=False, stream=True, **options) as response:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 262144 or time.monotonic()-started > 20:
                        raise ValueError('WordPress response exceeds transport bounds')
                if not 200 <= response.status_code < 300:
                    # Do not expose remote messages, URLs or credentials.
                    raise ValueError('WordPress did not confirm the article request')
                return json.loads(body)

    @classmethod
    def receipt(cls, value, payload):
        if (not isinstance(value, dict) or type(value.get('id')) is not int or value['id'] <= 0
                or value.get('slug') != payload['slug'] or value.get('status') != cls.post_status
                or not isinstance(value.get('title'), dict) or value['title'].get('raw') != payload['title']
                or not isinstance(value.get('content'), dict) or value['content'].get('raw') != payload['content']):
            return None
        return dict(id='wordpress-post-'+str(value['id']), outcome=cls.delivery_outcome)

    def lookup(self, snap, binding, payload):
        self.guard(snap, binding)
        rows = self.wire('get', binding, params=dict(slug=payload['slug'], status='any',
            context='edit', per_page=2, _fields='id,slug,status,title,content'))
        self.guard(snap, binding)
        if not isinstance(rows, list) or len(rows) > 1:
            raise ValueError('WordPress article lookup is ambiguous')
        if not rows:
            return None
        receipt = self.receipt(rows[0], payload)
        if receipt is None:
            raise ValueError('WordPress article differs from the approved wording or action')
        return receipt

    def deliver(self, snap, *, idempotency_key):
        binding = self.selected(snap)
        payload = self.payload(snap, idempotency_key)
        existing = self.lookup(snap, binding, payload)
        if existing:
            return existing
        self.guard(snap, binding)
        # Exactly one POST in this invocation; never retry errors or mutate posts.
        result = self.wire('post', binding, json=payload, params={'context': 'edit'})
        self.guard(snap, binding)
        return self.receipt(result, payload)

    def reconcile(self, snap, *, idempotency_key):
        binding = self.selected(snap)
        return self.lookup(snap, binding, self.payload(snap, idempotency_key))


class WordPressPublicationAdapter(WordPressDraftAdapter):
    """New-post publication only, behind separate host and exact owner approval.

    Never supply this adapter merely to inspect/recover old draft jobs. Its
    distinct site identity blocks their dispatch/reconciliation. The host must
    explicitly enable publication on a dedicated reviewed binding; existing
    draft configurations remain incapable of publication.
    """
    delivery_outcome = 'published'
    post_status = 'publish'
    policy_identity = 'wordpress-publication-v1'
