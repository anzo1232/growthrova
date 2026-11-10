"""Ayrshare destination inspection and explicitly enabled short-lived linking.

Credentials come only from an explicitly enabled server-owned organisation vault
resolver. No ambient credentials, primary-profile fallback or client profile key.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Callable
from urllib.parse import urlsplit, parse_qs

import requests
from flask import jsonify, request
from business_social_drafts import PLANNED_CHANNELS

ENDPOINT = 'https://api.ayrshare.com/api/user'
MAX_RESPONSE_BYTES = 65536
LINK_ENDPOINT = 'https://api.ayrshare.com/api/profiles/link-sessions'
DISCONNECT_ENDPOINT = 'https://api.ayrshare.com/api/profiles/social'


@dataclass(frozen=True)
class SocialAccountConfig:
    enabled: bool = False
    api_key: str = field(default='', repr=False)
    profile_key_for_org: Callable | None = field(default=None, repr=False)
    linking_enabled: bool = False
    disconnect_enabled: bool = False


def _text(value, maximum=300):
    return value if isinstance(value, str) and 0 < len(value) <= maximum and value.strip() and not any(ord(c) < 32 for c in value) else None


def _expired(item):
    days = item.get('refreshDaysRemaining')
    if type(days) in (int, float) and days <= 0:
        return True
    expiry = item.get('refreshRequired')
    if expiry is not None:
        try:
            parsed = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
            return parsed.tzinfo is None or parsed.astimezone(timezone.utc) <= datetime.now(timezone.utc)
        except (ValueError, TypeError, AttributeError):
            return True  # Unreadable expiry is not permission to publish.
    return False


def _account_type(channel, item):
    kind = _text(item.get('type'))
    if channel == 'facebook':
        # The documented Facebook identity is a Page. An explicit conflicting
        # type must not be relabelled as a Page merely because it is linked.
        if 'type' not in item:
            return 'page'
        return kind if kind in ('page', 'personal') else 'unknown'
    if channel == 'linkedin':
        return {'corporate': 'company', 'personal': 'personal'}.get(kind, 'unknown')
    if channel == 'instagram':
        return kind if kind in ('business', 'creator', 'personal') else 'unknown'
    return 'unknown'


def _account_type_check(channel, destination):
    """Reported type only; neither current grants nor format eligibility."""
    kind = destination['accountType'] if destination else 'unknown'
    if channel == 'instagram':
        if kind == 'personal':
            return dict(state='unsupported', message='Instagram personal accounts cannot be used for publishing. Choose a Business or Creator account.')
        if kind not in ('business', 'creator'):
            return dict(state='unverified', message='Instagram account type is unverified. A Business or Creator account must be reported before publishing can be considered.')
    elif channel == 'facebook':
        if kind == 'personal':
            return dict(state='unsupported', message='Facebook personal profiles cannot be used for publishing through this integration. Choose a Facebook Page.')
        if kind != 'page':
            return dict(state='unverified', message='Facebook Page identity needs verification. A personal profile is not a Page destination.')
    elif channel == 'linkedin':
        if kind not in ('personal', 'company'):
            return dict(state='unverified', message='LinkedIn destination type is unverified. Check whether this is your personal account or company Page.')
    else:
        return dict(state='unverified', message=f'{PLANNED_CHANNELS[channel]} account eligibility is not verified by this account lookup. Publishing permissions and media support still need checking.')
    return dict(state='reported', message='Account type reported only. Current permissions, media format and publishing approval still need checking.')


def account_inventory(payload):
    """Allowlist identities. Reported linking never implies approval or capability."""
    if not isinstance(payload, dict) or payload.get('status') == 'error':
        raise ValueError('Invalid profile response')
    active = payload.get('activeSocialAccounts', [])
    names = payload.get('displayNames', [])
    if (not isinstance(active, list) or len(active) > 100 or any(not isinstance(c, str) for c in active)
            or not isinstance(names, list) or len(names) > 100 or any(not isinstance(n, dict) for n in names)):
        raise ValueError('Invalid account list')
    accounts = []
    for channel, label in PLANNED_CHANNELS.items():
        platform = 'twitter' if channel == 'x' else channel
        items = [n for n in names if n.get('platform') == platform]
        state, destination = 'not_linked', None
        if platform in active:
            state = 'identity_unverified'
            if len(items) == 1:
                item = items[0]
                ident = _text(item.get('id'))
                name = _text(item.get('displayName')) or _text(item.get('username'))
                if ident and name:
                    destination = dict(id=ident, name=name, accountType=_account_type(channel, item))
                    state = 'needs_reconnect' if _expired(item) else 'reported'
        accounts.append(dict(channel=channel, label=label, state=state, destination=destination,
                             accountTypeCheck=_account_type_check(channel, destination), canPublish=False))
    return accounts


def _provider_request(config, profile_key, http, *, linking=False, disconnect=None):
    # Session isolation avoids ambient proxy/.netrc credentials. No redirects,
    # retries, URL inputs, SDK telemetry or provider-response logging.
    with requests.Session() as session:
        session.trust_env = False
        transport = http if http is not None else session
        if disconnect:
            method, endpoint = transport.delete, DISCONNECT_ENDPOINT
            options = dict(json={'platform': disconnect})
        elif linking:
            method, endpoint = transport.post, LINK_ENDPOINT
            options = dict(json={'logout': True, 'allowedSocial': [
                'instagram', 'facebook', 'linkedin', 'tiktok', 'twitter']})
        else:
            method, endpoint = transport.get, ENDPOINT
            options = dict(params={'instagramDetails': 'true'})
        with method(endpoint, headers={'Authorization': 'Bearer '+config.api_key,
                'Profile-Key': profile_key}, **options,
                timeout=10, allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise ValueError('Profile lookup failed')
            body = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError('Profile response too large')
            return json.loads(body)


def _link_result(payload):
    """Only release a short-lived hosted grid link; never arbitrary navigation."""
    if not isinstance(payload, dict) or payload.get('status') != 'success':
        raise ValueError('Invalid link response')
    url = _text(payload.get('url'), 8192)
    if not url or any(c.isspace() for c in url):
        raise ValueError('Invalid link URL')
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if (parsed.scheme != 'https' or parsed.netloc != 'profile.ayrshare.com'
            or parsed.path not in ('', '/') or parsed.fragment
            or set(query) - {'session', 'domain', 'logout'}
            or any(len(values) != 1 or not values[0] for values in query.values())
            or not query.get('session', [''])[0].startswith('ayr_ls_')
            or query.get('logout') != ['true']):
        raise ValueError('Invalid link URL')
    expiry = datetime.fromisoformat(payload['expiresAt'].replace('Z', '+00:00'))
    if expiry.tzinfo is None or not 0 < (expiry-datetime.now(timezone.utc)).total_seconds() <= 360:
        raise ValueError('Invalid link expiry')
    return dict(url=url, expiresAt=expiry.isoformat(), canPublish=False)


def _require_current_profile(config, organisation_id, profile_key):
    """Reject results/dispatch from a revoked or replaced vault mapping.

    This is a boundary recheck, not a lock against concurrent provider relinking.
    Never switch the request to a newly resolved profile without owner review.
    """
    current = config.profile_key_for_org(organisation_id)
    if not _text(current, 8192) or current != profile_key:
        raise ValueError('Business publishing profile changed')


def lookup_social_accounts(config, organisation_id, http=None):
    """Server-only org resolution shared by inventory and draft snapshot checks."""
    if (config is None or config.enabled is not True or not _text(config.api_key, 8192)
            or not callable(config.profile_key_for_org)):
        raise ValueError('Social account inspection is unavailable')
    profile_key = config.profile_key_for_org(organisation_id)
    if profile_key is None:
        return account_inventory({})
    if not _text(profile_key, 8192):
        raise ValueError('Invalid scoped credential')
    accounts = account_inventory(_provider_request(config, profile_key, http))
    _require_current_profile(config, organisation_id, profile_key)
    return accounts


def register_social_account_routes(app, repo, *, config=None, http=None, revalidate=None):
    config = config or SocialAccountConfig()

    def configured():
        return config.enabled is True and bool(_text(config.api_key, 8192)) and callable(config.profile_key_for_org)

    @app.post('/api/growthrova/organisations/<organisation_id>/social-accounts/disconnect')
    def social_disconnect(organisation_id):
        repo._scope(organisation_id)
        payload = request.get_json(silent=True)
        if (not isinstance(payload, dict) or set(payload) != {'channel', 'destinationId'}
                or not isinstance(payload.get('channel'), str) or payload['channel'] not in PLANNED_CHANNELS
                or not _text(payload.get('destinationId'))):
            return jsonify(code='invalid_request', error='Choose the exact displayed channel and account to disconnect.'), 400
        if not configured() or config.disconnect_enabled is not True:
            return jsonify(code='social_disconnect_unavailable', error='Account disconnection is not enabled. Saved drafts are preserved.'), 503
        dispatched = False
        try:
            profile_key = config.profile_key_for_org(organisation_id)
            if profile_key is None:
                return jsonify(code='social_profile_required', error='No publishing profile is configured for this business.'), 409
            if not _text(profile_key, 8192):
                raise ValueError('Invalid scoped credential')
            if revalidate:
                error = revalidate()
                if error is not None:
                    return error
            inventory = account_inventory(_provider_request(config, profile_key, http))
            account = next(a for a in inventory if a['channel'] == payload['channel'])
            if not account['destination'] or account['destination']['id'] != payload['destinationId']:
                return jsonify(code='social_destination_changed', error='The reported destination changed. Check accounts and review before disconnecting.'), 409
            _require_current_profile(config, organisation_id, profile_key)
            if revalidate:
                error = revalidate()
                if error is not None:
                    return error
            platform = 'twitter' if payload['channel'] == 'x' else payload['channel']
            dispatched = True
            result = _provider_request(config, profile_key, http, disconnect=platform)
            if not isinstance(result, dict) or result.get('status') != 'success' or result.get('platform') != platform:
                raise ValueError('Invalid disconnect acknowledgement')
            _require_current_profile(config, organisation_id, profile_key)
        except (requests.RequestException, ValueError, TypeError, OSError, LookupError, RuntimeError):
            return jsonify(code='social_disconnect_uncertain' if dispatched else 'social_disconnect_unavailable',
                error='Disconnection could not be confirmed. Check accounts before taking another action. Saved drafts are preserved; already submitted posts cannot be recalled here.'), 503
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        response = jsonify(state='disconnect_acknowledged', channel=payload['channel'], canPublish=False,
            message='Provider acknowledged disconnection. Check accounts again; reported details may be cached for 60 seconds. Saved drafts and already submitted posts are unchanged.')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/api/growthrova/organisations/<organisation_id>/social-accounts/link-session')
    def social_link_session(organisation_id):
        repo._scope(organisation_id)
        if request.get_json(silent=True) != {}:
            return jsonify(code='invalid_request', error='Connect accounts for the selected business; no account keys or redirects can be supplied.'), 400
        if not configured() or config.linking_enabled is not True:
            return jsonify(code='social_link_unavailable', error='Account linking is not enabled. Saved drafts are preserved.'), 503
        try:
            profile_key = config.profile_key_for_org(organisation_id)
            if profile_key is None:
                return jsonify(code='social_profile_required', error='This business needs a securely provisioned publishing profile before accounts can be connected. Saved drafts are preserved.'), 409
            if not _text(profile_key, 8192):
                raise ValueError('Invalid scoped credential')
            if revalidate:
                error = revalidate()
                if error is not None:
                    return error
            result = _link_result(_provider_request(config, profile_key, http, linking=True))
            _require_current_profile(config, organisation_id, profile_key)
        except (requests.RequestException, ValueError, TypeError, OSError, LookupError, RuntimeError, AttributeError):
            return jsonify(code='social_link_unavailable', error='A secure account link could not be prepared. Check accounts before requesting another link; drafts are preserved. No publishing is enabled.'), 503
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        response = jsonify(**result)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/api/growthrova/organisations/<organisation_id>/social-accounts')
    def social_accounts(organisation_id):
        repo._scope(organisation_id)  # Existing JWT/org contract, before vault/provider.
        if config.enabled is not True or not _text(config.api_key, 8192) or not callable(config.profile_key_for_org):
            return jsonify(accounts=[dict(channel=c, label=label, state='unavailable',
                           destination=None, canPublish=False) for c, label in PLANNED_CHANNELS.items()],
                           canPublish=False, message='Social account connection is not enabled. Posting drafts are preserved.')
        try:
            accounts = lookup_social_accounts(config, organisation_id, http)
        except (requests.RequestException, ValueError, TypeError, OSError, LookupError, RuntimeError):
            # Resolver contract: operational vault failures raise OSError or
            # RuntimeError. Neither vault nor transport details reach the UI.
            return jsonify(code='social_accounts_unavailable', error=
                'Social accounts could not be checked. Retry later; existing drafts are preserved. No publishing is enabled.'), 503
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        return jsonify(accounts=accounts, canPublish=False, canCreateLink=config.linking_enabled is True,
            canDisconnect=config.disconnect_enabled is True, message=
            'Reported account details may be cached for up to 60 seconds. Linking is not publishing approval; permissions and formats remain unverified.')
