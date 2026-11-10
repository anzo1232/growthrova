"""Opt-in Stripe TEST checkout and durable subscription coverage, never credits.

Wire contract: Stripe 2025-03-31.basil snapshot subscription events. A single
checkout slot per business across policy changes is deliberately conservative.
Only explicitly confirmed, verified expired sessions can be replaced; old
identities and contradictory late events are retained for review.
Explicit current-state recovery reads only saved remote identities. No
secrets/environment lookup, live mode, portal, plan changes or resend worker.
Explicit period-end cancellation has a separate durable operation record.
"""
from contextlib import closing
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit
import uuid

from flask import jsonify, request
import requests

from business_growthrova_access import GenerationAccessConfig
from business_marketing_drafts import MarketingDraftError

ENDPOINT = 'growthrova_test_billing_event'
PATH = '/api/growthrova/test-billing/events'
API_VERSION = '2025-03-31.basil'
EVENT_TYPES = {'customer.subscription.created', 'customer.subscription.updated', 'customer.subscription.deleted'}


def _id(value, prefix):
    return isinstance(value, str) and re.fullmatch(prefix + r'[A-Za-z0-9]{1,180}', value) is not None


def _https(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    url = urlsplit(value)
    return url.scheme == 'https' and bool(url.hostname) and not (url.username or url.password or url.fragment)


def _checkout_url(value):
    return _https(value) and urlsplit(value).netloc == 'checkout.stripe.com'


@dataclass(frozen=True)
class TestBillingConfig:
    enabled: bool = False
    version: str = ''
    price_id: str = ''
    plan_label: str = ''
    secret_key: str = field(default='', repr=False)
    webhook_secret: str = field(default='', repr=False)
    success_url: str = ''
    cancel_url: str = ''
    clock: object = time.time
    http: object = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.enabled) is not bool or not callable(self.clock):
            raise ValueError('Explicit test billing configuration required')
        if self.enabled and (not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', self.version)
                or not _id(self.price_id, 'price_')
                or not 1 <= len(self.plan_label.strip()) <= 100
                or not _id(self.secret_key, 'sk_test_')
                or not _id(self.webhook_secret, 'whsec_')
                or not _https(self.success_url) or not _https(self.cancel_url)):
            raise ValueError('Dedicated test key, price, webhook, policy version and HTTPS return URLs required')


class TestBilling:
    def __init__(self, repo, config=None):
        self.repo, self.config = repo, config or TestBillingConfig()
        # Policy changes cannot silently adopt another account/price's receipts.
        self.policy = hashlib.sha256(json.dumps([self.config.version, self.config.price_id,
            self.config.secret_key, self.config.webhook_secret, self.config.success_url,
            self.config.cancel_url], separators=(',', ':')).encode()).hexdigest()
        with closing(repo._connect()) as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS growthrova_billing_checkouts(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, organisation TEXT NOT NULL,
                    policy TEXT NOT NULL, state TEXT NOT NULL, session TEXT, url TEXT,
                    expires REAL, created REAL NOT NULL, UNIQUE(owner,organisation));
                CREATE TABLE IF NOT EXISTS growthrova_billing_grants(
                    intent TEXT PRIMARY KEY, subscription TEXT UNIQUE NOT NULL,
                    customer TEXT NOT NULL, event_created INTEGER NOT NULL,
                    version TEXT NOT NULL, projection TEXT NOT NULL, terminal INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS growthrova_billing_events(
                    id TEXT PRIMARY KEY, digest TEXT NOT NULL, intent TEXT NOT NULL);
            ''')
            con.commit()
        from business_growthrova_billing_cancellation import TestCancellation
        self.cancellation = TestCancellation(self)
        from business_growthrova_billing_replacement import TestCheckoutReplacement
        self.replacement = TestCheckoutReplacement(self)

    def grant(self, owner, org):
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN')
            if self.replacement.held(con, (owner, org)):
                return None
            row = con.execute('''SELECT g.version,g.projection FROM growthrova_billing_grants g
                JOIN growthrova_billing_checkouts c ON c.id=g.intent
                WHERE c.owner=? AND c.organisation=? AND c.policy=?''', (owner, org, self.policy)).fetchone()
        if row is None:
            return None
        return dict(ownerId=owner, organisationId=org, version=row['version'], **json.loads(row['projection']))

    def status(self, org):
        scope = self.repo._scope(org)
        if not self.config.enabled:
            return dict(mode='unconfigured', state='unconfigured')
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN')
            row = con.execute('SELECT * FROM growthrova_billing_checkouts WHERE owner=? AND organisation=?',
                              scope).fetchone()
            saved = (con.execute('SELECT * FROM growthrova_billing_grants WHERE intent=?',
                                 (row['id'],)).fetchone() if row else None)
            held = self.replacement.held(con, scope)
            cancellation = self.cancellation.status(con, row, saved) if not held else {}
            replaceable = self.replacement.eligible(row, saved) and not held
        grant = (json.loads(saved['projection']) if saved and row['policy'] == self.policy else None)
        result = dict(mode='test', planLabel=self.config.plan_label, state='not_started', creditBalance=None)
        if row:
            result['state'] = 'needs_review' if row['state'] == 'dispatching' or row['policy'] != self.policy else row['state']
            result['attemptId'] = row['id']
            if result['state'] == 'ready':
                if row['expires'] > self.config.clock() and grant is None:
                    result['checkoutUrl'] = row['url']
                elif grant is None:
                    result['state'] = 'expired'
            if grant:
                result['state'] = 'subscription_received'
                result['subscriptionState'] = grant['state']
                result['validUntil'] = grant['until']
            result['canCheckProvider'] = (row['policy'] == self.policy and bool(row['session'] or grant)
                                          and not (saved and saved['terminal']))
        result.update(cancellation)
        result['canReplaceCheckout'] = replaceable
        if replaceable:
            result.update(state='expired', replacementVersion=row['id'])
        if held:
            result.update(state='needs_review', billingReviewHold=True, canCheckProvider=False, canCancelAtPeriodEnd=False)
            result.pop('checkoutUrl', None)
        return result

    def _read(self, path, *, params=None):
        return self._request('get', path, params=params)

    def _post(self, path, *, data, key):
        return self._request('post', path, data=data, key=key)

    def _request(self, method, path, *, params=None, data=None, key=None):
        # Fixed Stripe origin; callers supply only validated, saved IDs. No
        # redirects/retry, ambient credentials/proxies or unbounded response.
        started = time.monotonic()
        with requests.Session() as session:
            session.trust_env = False
            transport = self.config.http or session
            headers = {'Authorization': 'Bearer '+self.config.secret_key, 'Stripe-Version': API_VERSION}
            options = {'params': params} if method == 'get' else {'data': data}
            if key:
                headers['Idempotency-Key'] = key
            with getattr(transport, method)('https://api.stripe.com/v1/'+path, **options,
                    headers=headers,
                    timeout=(3, 10), allow_redirects=False, stream=True) as response:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 65536 or time.monotonic()-started > 20:
                        raise ValueError('Subscription response exceeds transport bounds')
                if response.status_code != 200:
                    raise ValueError('Subscription read not acknowledged')
                return json.loads(body)

    def reconcile(self, org, revalidate):
        if not self.config.enabled:
            raise MarketingDraftError('Test subscription checks are not configured.', 'billing_unconfigured', 409)
        scope = self.repo._scope(org)
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN')
            row = con.execute('SELECT * FROM growthrova_billing_checkouts WHERE owner=? AND organisation=?', scope).fetchone()
            old = (con.execute('SELECT * FROM growthrova_billing_grants WHERE intent=?', (row['id'],)).fetchone()
                   if row else None)
            held = self.replacement.held(con, scope)
        if (held or not row or row['policy'] != self.policy or not (old or _id(row['session'], 'cs_test_'))
                or (old and old['terminal'])):
            raise MarketingDraftError('This attempt needs operator review; another checkout has not been created.',
                                      'billing_review_required', 409)
        observed = int(self.config.clock())
        # A read has no provider event sequence. Fence older deliveries at the
        # read's start second, and require a strictly later read after a conflict.
        if old and observed <= old['event_created']:
            raise MarketingDraftError('A subscription update just arrived. Wait a moment and check again.',
                                      'billing_changed', 409)
        try:
            if old:
                if not _id(old['subscription'], 'sub_'):
                    raise ValueError('Invalid saved subscription')
                sub = self._read('subscriptions/'+old['subscription'])
            else:
                checkout = self._read('checkout/sessions/'+row['session'], params={'expand[]': 'subscription'})
                if (not isinstance(checkout, dict) or checkout.get('object') != 'checkout.session'
                        or checkout.get('id') != row['session'] or checkout.get('livemode') is not False
                        or checkout.get('mode') != 'subscription' or checkout.get('client_reference_id') != row['id']
                        or checkout.get('status') not in ('open', 'expired', 'complete')):
                    raise ValueError('Invalid saved checkout')
                sub = checkout.get('subscription')
                if checkout['status'] != 'complete':
                    if sub is not None:
                        raise ValueError('Unexpected subscription')
                    sub = None  # Open/expired alone never infers coverage.
                elif not isinstance(sub, dict) or checkout.get('customer') != sub.get('customer'):
                    raise ValueError('Invalid checkout subscription')
            if sub is not None:
                if (not isinstance(sub, dict) or sub.get('object') != 'subscription' or sub.get('livemode') is not False
                        or not _id(sub.get('id'), 'sub_') or not _id(sub.get('customer'), 'cus_')
                        or (old and (sub['id'] != old['subscription'] or sub['customer'] != old['customer']))):
                    raise ValueError('Invalid subscription identity')
                metadata = sub.get('metadata')
                bound = isinstance(metadata, dict) and metadata.get('growthrova_intent') == row['id']
                if not old and not bound:
                    raise ValueError('Unbound subscription')
                projection = (self._projection(sub, 'customer.subscription.updated') if bound
                              else {'state': 'suspended', 'from': 0, 'until': 1})
        except Exception:
            raise MarketingDraftError('The test subscription could not be checked. Saved access and the checkout attempt are retained; try checking again.',
                                      'billing_check_unavailable', 503) from None
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        if self.repo._scope(org) != scope:
            raise MarketingDraftError('Business access changed. Select the business again.', 'access_denied', 403)
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT * FROM growthrova_billing_checkouts WHERE id=?', (row['id'],)).fetchone()
            latest = con.execute('SELECT * FROM growthrova_billing_grants WHERE intent=?', (row['id'],)).fetchone()
            if (self.replacement.held(con, scope) or current is None or dict(current) != dict(row)
                    or (dict(latest) if latest else None) != (dict(old) if old else None)):
                raise MarketingDraftError('Subscription evidence changed during the check. Refresh saved status and check again.',
                                          'billing_changed', 409)
            if sub is not None:
                bound_elsewhere = con.execute('SELECT intent FROM growthrova_billing_grants WHERE subscription=?',
                                              (sub['id'],)).fetchone()
                if bound_elsewhere and bound_elsewhere['intent'] != row['id']:
                    raise MarketingDraftError('Subscription evidence needs operator review. Saved access is retained.',
                                              'billing_review_required', 409)
                version = 'check_'+uuid.uuid4().hex
                # Record only a digest and the existing local intent, not the
                # provider response (which can contain payment/contact details).
                digest = hashlib.sha256(json.dumps(sub, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                con.execute('''INSERT INTO growthrova_billing_grants VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(intent) DO UPDATE SET event_created=excluded.event_created,
                    version=excluded.version,projection=excluded.projection,terminal=excluded.terminal''',
                    (row['id'], sub['id'], sub['customer'], observed, version,
                     json.dumps(projection, sort_keys=True), int(sub.get('status') == 'canceled')))
                con.execute('INSERT INTO growthrova_billing_events VALUES(?,?,?)', (version, digest, row['id']))
            elif checkout['status'] == 'expired':
                # A verified remote expiry must remove the old checkout link even
                # if its locally saved scheduled expiry is still in the future.
                from business_growthrova_billing_replacement import verified_expiry
                state = 'verified_expired' if verified_expiry(checkout) else 'expired'
                con.execute('UPDATE growthrova_billing_checkouts SET state=? WHERE id=?', (state, row['id']))
                if state == 'verified_expired':
                    digest = hashlib.sha256(json.dumps(checkout, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                    con.execute('INSERT INTO growthrova_billing_events VALUES(?,?,?)', ('expiry_'+uuid.uuid4().hex, digest, row['id']))
            elif checkout['status'] == 'open':
                # A newer contradictory read removes prior replacement proof.
                con.execute('UPDATE growthrova_billing_checkouts SET state=? WHERE id=?', ('ready', row['id']))
            con.commit()
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        result = self.status(org)
        result['providerCheck'] = 'subscription_checked' if sub is not None else 'checkout_'+checkout['status']
        return result

    def checkout(self, org, revalidate):
        if not self.config.enabled:
            raise MarketingDraftError('Test subscription checkout is not configured.', 'billing_unconfigured', 409)
        scope = self.repo._scope(org)
        # Admission/intent insertion is atomic. Replays only return saved state,
        # including across restart; no client key can create a second session.
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            old = con.execute('SELECT id FROM growthrova_billing_checkouts WHERE owner=? AND organisation=?',
                              scope).fetchone()
            if old:
                con.rollback()
                return self.status(org)
            ident = uuid.uuid4().hex
            con.execute('INSERT INTO growthrova_billing_checkouts(id,owner,organisation,policy,state,created) VALUES(?,?,?,?,?,?)',
                        (ident, *scope, self.policy, 'dispatching', self.config.clock()))
            con.commit()
        return self.dispatch_checkout(org, scope, ident, revalidate)

    def dispatch_checkout(self, org, scope, ident, revalidate):
        # The durable slot already exists. Never call this to replay an attempt.
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        if self.repo._scope(org) != scope:
            raise MarketingDraftError('Business access changed.', 'access_denied', 403)
        with closing(self.repo._connect()) as con:
            if self.replacement.held(con, scope):
                return self.status(org)
        try:
            data = self._post('checkout/sessions', data={'mode': 'subscription',
                'line_items[0][price]': self.config.price_id, 'line_items[0][quantity]': '1',
                'client_reference_id': ident, 'subscription_data[metadata][growthrova_intent]': ident,
                'success_url': self.config.success_url, 'cancel_url': self.config.cancel_url},
                key='growthrova-test-'+ident)
            if (not isinstance(data, dict) or data.get('livemode') is not False
                    or data.get('mode') != 'subscription' or data.get('status') != 'open'
                    or data.get('client_reference_id') != ident
                    or not _id(data.get('id'), 'cs_test_') or not _checkout_url(data.get('url'))
                    or type(data.get('expires_at')) is not int
                    or not self.config.clock() < data['expires_at'] <= self.config.clock()+86460):
                raise ValueError('Invalid test checkout acknowledgement')
            with closing(self.repo._connect()) as con:
                con.execute('BEGIN IMMEDIATE')
                if con.execute('SELECT 1 FROM growthrova_billing_replacements WHERE session=?', (data['id'],)).fetchone():
                    raise ValueError('Reused checkout identity')
                con.execute('UPDATE growthrova_billing_checkouts SET state=?,session=?,url=?,expires=? WHERE id=?',
                            ('ready', data['id'], data['url'], data['expires_at'], ident))
                con.commit()
        except Exception:
            # The provider may have accepted: never resend, even after restart.
            with closing(self.repo._connect()) as con:
                con.execute('UPDATE growthrova_billing_checkouts SET state=? WHERE id=?', ('needs_review', ident))
                con.commit()
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        if self.repo._scope(org) != scope:
            raise MarketingDraftError('Business access changed.', 'access_denied', 403)
        return self.status(org)

    def receive(self, raw, signature):
        if len(raw) > 65536 or not isinstance(signature, str) or len(signature) > 4096:
            raise ValueError('Invalid event')
        fields = [part.split('=', 1) for part in signature.split(',')]
        stamps = [value for key, value in fields if key == 't']
        if len(stamps) != 1 or not stamps[0].isdigit() or abs(self.config.clock()-int(stamps[0])) > 300:
            raise ValueError('Invalid event time')
        expected = hmac.new(self.config.webhook_secret.encode(), stamps[0].encode()+b'.'+raw, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, value) for key, value in fields if key == 'v1'):
            raise ValueError('Invalid signature')
        event = json.loads(raw)
        if (not isinstance(event, dict) or event.get('livemode') is not False or event.get('account')
                or event.get('api_version') != API_VERSION or not _id(event.get('id'), 'evt_')
                or type(event.get('created')) is not int or not 0 < event['created'] <= self.config.clock()+300):
            raise ValueError('Invalid test event')
        if event.get('type') not in EVENT_TYPES:
            return  # No access is ever granted from a return URL or Checkout completion.
        sub = event.get('data', {}).get('object')
        if (not isinstance(sub, dict) or sub.get('object') != 'subscription' or sub.get('livemode') is not False
                or not _id(sub.get('id'), 'sub_') or not _id(sub.get('customer'), 'cus_')):
            raise ValueError('Invalid subscription')
        metadata = sub.get('metadata')
        claimed_intent = metadata.get('growthrova_intent') if isinstance(metadata, dict) else None
        digest = hashlib.sha256(raw).hexdigest()
        with closing(self.repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            if (isinstance(claimed_intent, str) and re.fullmatch('[a-f0-9]{32}', claimed_intent)
                    and self.replacement.receive_archived(con, claimed_intent, event, digest)):
                return
            bound = con.execute('SELECT intent FROM growthrova_billing_grants WHERE subscription=?', (sub['id'],)).fetchone()
            ident = bound['intent'] if bound else claimed_intent
            if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
                return  # Unrelated subscriptions must never be adopted.
            intent = con.execute('SELECT * FROM growthrova_billing_checkouts WHERE id=? AND policy=?', (ident, self.policy)).fetchone()
            if not intent:
                return
            prior_event = con.execute('SELECT digest FROM growthrova_billing_events WHERE id=?', (event['id'],)).fetchone()
            if prior_event:
                if prior_event['digest'] != digest:
                    raise ValueError('Conflicting event identity')
                return
            old = con.execute('SELECT * FROM growthrova_billing_grants WHERE intent=?', (ident,)).fetchone()
            if old and (old['subscription'] != sub['id'] or old['customer'] != sub['customer']):
                raise ValueError('Subscription identity changed')
            projection = (self._projection(sub, event['type']) if claimed_intent == ident
                          else {'state': 'suspended', 'from': 0, 'until': 1})
            terminal = event['type'] == 'customer.subscription.deleted' or sub.get('status') == 'canceled'
            if old and (old['terminal'] or event['created'] < old['event_created']):
                pass  # Older deliveries cannot restore revoked coverage.
            else:
                if old and event['created'] == old['event_created'] and projection != json.loads(old['projection']):
                    # Stripe event timestamps have second precision, no ordering
                    # guarantee. A conflict pauses until a strictly newer event.
                    projection['state'] = 'suspended'
                con.execute('''INSERT INTO growthrova_billing_grants VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(intent) DO UPDATE SET event_created=excluded.event_created,
                    version=excluded.version,projection=excluded.projection,terminal=excluded.terminal''',
                    (ident, sub['id'], sub['customer'], event['created'], event['id'],
                     json.dumps(projection, sort_keys=True), int(terminal)))
            con.execute('INSERT INTO growthrova_billing_events VALUES(?,?,?)', (event['id'], digest, ident))
            con.commit()

    def _projection(self, sub, event_type):
        # Unknown/multi-item/changed-price/paused states revoke rather than leave
        # an earlier active grant in place. No trial or unpaid grace is inferred.
        result = {'state': 'suspended', 'from': 0, 'until': 1}
        items = sub.get('items', {})
        rows = items.get('data') if isinstance(items, dict) else None
        if not isinstance(rows, list) or len(rows) != 1 or items.get('has_more') is not False:
            return result
        item = rows[0]
        if not isinstance(item, dict):
            return result
        price = item.get('price', {})
        start, end = item.get('current_period_start'), item.get('current_period_end')
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= 253402300799
                or not isinstance(price, dict) or price.get('id') != self.config.price_id
                or price.get('livemode') is not False or type(item.get('quantity')) is not int or item['quantity'] != 1):
            return result
        result.update({'from': start, 'until': end})
        if type(sub.get('cancel_at_period_end')) is bool:
            result['cancelAtPeriodEnd'] = sub['cancel_at_period_end']
        cancel_at = sub.get('cancel_at')
        if cancel_at is not None:
            if type(cancel_at) is not int or cancel_at <= start:
                return result
            result['until'] = min(end, cancel_at)
        result['cancelAt'] = cancel_at
        if (sub.get('status') == 'active' and sub.get('pause_collection') is None
                and event_type != 'customer.subscription.deleted'):
            result['state'] = 'active'
        return result


def register_test_billing(app, repo, root, *, config=None, revalidate=None):
    service = TestBilling(repo, config)
    app.extensions['growthrova_test_billing'] = service

    @app.get(root+'/subscription')
    def subscription(organisation_id):
        service.status(organisation_id)
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        return jsonify(service.status(organisation_id))

    @app.post(root+'/subscription/checkout')
    def checkout(organisation_id):
        if request.get_json(silent=True) != {}:
            raise MarketingDraftError('Checkout uses the configured test plan for this business.', 'invalid_request', 400)
        result = service.checkout(organisation_id, revalidate)
        return jsonify(result) if isinstance(result, dict) else result

    @app.post(root+'/subscription/check')
    def check_subscription(organisation_id):
        if request.get_json(silent=True) != {}:
            raise MarketingDraftError('Check the saved test subscription for this business.', 'invalid_request', 400)
        result = service.reconcile(organisation_id, revalidate)
        return jsonify(result) if isinstance(result, dict) else result

    @app.post(root+'/subscription/replace')
    def replace_checkout(organisation_id):
        body = request.get_json(silent=True)
        if (not isinstance(body, dict) or set(body) != {'confirmation', 'version'}
                or body.get('confirmation') != 'replace_expired_checkout'
                or not isinstance(body.get('version'), str) or not re.fullmatch('[a-f0-9]{32}', body['version'])):
            raise MarketingDraftError('Confirm replacement of the saved expired test checkout.', 'invalid_request', 400)
        result = service.replacement.replace(organisation_id, body['version'], revalidate)
        return jsonify(result) if isinstance(result, dict) else result

    @app.post(root+'/subscription/cancel')
    def cancel_subscription(organisation_id):
        body = request.get_json(silent=True)
        if (not isinstance(body, dict) or set(body) != {'confirmation', 'version'}
                or body.get('confirmation') != 'cancel_at_period_end'
                or not isinstance(body.get('version'), str) or not 1 <= len(body['version']) <= 128):
            raise MarketingDraftError('Confirm period-end cancellation of the saved test subscription.', 'invalid_request', 400)
        result = service.cancellation.cancel(organisation_id, body['version'], revalidate)
        return jsonify(result) if isinstance(result, dict) else result

    @app.post(PATH, endpoint=ENDPOINT)
    def event():
        if not service.config.enabled:
            return '', 404
        request.max_content_length = 65536
        if request.query_string or request.mimetype != 'application/json':
            return '', 400
        try:
            service.receive(request.get_data(), request.headers.get('Stripe-Signature', ''))
        except (ValueError, TypeError, KeyError, AttributeError):
            return '', 400
        return '', 200

    return (GenerationAccessConfig(enforced=True, source='test_subscription', resolve=service.grant, clock=service.config.clock)
            if service.config.enabled else None)
