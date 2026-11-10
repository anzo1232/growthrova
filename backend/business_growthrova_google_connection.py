"""Explicit Google Ads consent; tokens go only to an installed tenant vault.

Vault contract (all methods server-only): status(scope) -> {'version': None or
32 lowercase hex}; replace(scope, expected_version, version, grant) atomically
compares the old version, installs the grant and fences obsolete consumer
bindings. It must be idempotent for version and must not log token values.
The optional explicitly keyed vault and account-read bridge install no execution
grant. A saved grant is not evidence of current Google access.
"""
from dataclasses import dataclass, field
import base64
import hashlib
import json
import time
from urllib.parse import urlencode, urlsplit

import requests
from business_growthrova_consent import BusinessConsent, _plain, register_business_consent_routes

SCOPE = 'https://www.googleapis.com/auth/adwords'
CALLBACK = '/growthrova-google-callback.html'


@dataclass(frozen=True)
class GoogleConnectionConfig:
    enabled: bool = False
    client_id: str = ''
    client_secret: str = field(default='', repr=False)
    redirect_uri: str = ''
    version: str = ''  # Rotate with OAuth configuration or authority changes.
    vault: object = field(default=None, repr=False)
    vault_key: bytes = field(default=b'', repr=False)  # Optional dedicated Fernet key; never ambient.
    authorised: object = field(default=None, repr=False)
    clock: object = time.time
    http: object = field(default=None, repr=False)
    account_reads: object = field(default=None, repr=False)


class GoogleConnection(BusinessConsent):
    provider = 'google'
    oauth_scope = SCOPE
    callback_path = CALLBACK

    def __init__(self, repo, config=None):
        super().__init__(repo, config or GoogleConnectionConfig(), self.provider)

    @staticmethod
    def make_vault(repo, key, authorised):
        from business_growthrova_google_vault import GoogleGrantVault
        return GoogleGrantVault(repo, key, authorised)

    def available(self):
        cfg = self.config
        parsed = urlsplit(cfg.redirect_uri)
        return (cfg.enabled is True and _plain(cfg.client_id, 300) and _plain(cfg.client_secret, 8192)
                and _plain(cfg.version, 100) and parsed.scheme == 'https' and bool(parsed.hostname)
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path == self.callback_path and callable(cfg.authorised)
                and callable(getattr(cfg.vault, 'status', None)) and callable(getattr(cfg.vault, 'replace', None)))

    def authorization_url(self, state, verifier):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(dict(
            client_id=self.config.client_id, redirect_uri=self.config.redirect_uri,
            response_type='code', scope=self.oauth_scope, access_type='offline', prompt='consent select_account',
            state=state, code_challenge=challenge, code_challenge_method='S256'))
        return url

    def exchange(self, code, verifier):
        value = self.token_request(dict(client_id=self.config.client_id, client_secret=self.config.client_secret,
            code=code, code_verifier=verifier, redirect_uri=self.config.redirect_uri,
            grant_type='authorization_code'))
        return self.token_grant(value)

    def token_request(self, data):
        options = dict(data=data, timeout=(3, 10), allow_redirects=False, stream=True)
        with requests.Session() as session:
            session.trust_env = False
            transport = self.config.http or session
            with transport.post('https://oauth2.googleapis.com/token', **options) as response:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 32768:
                        raise ValueError('Invalid token response')
                if response.status_code != 200:
                    raise ValueError('Consent exchange unconfirmed')
                value = json.loads(body)
        return value

    def token_grant(self, value, previous=None):
        if not isinstance(value, dict):
            raise ValueError('Invalid token response')
        refresh = value.get('refresh_token', previous['refreshToken'] if previous else None)
        scope = value.get('scope', previous['scope'] if previous else None)
        if (not isinstance(value.get('token_type'), str) or value['token_type'].lower() != 'bearer'
                or not _plain(value.get('access_token'), 8192) or not _plain(refresh, 8192)
                or not isinstance(scope, str) or self.oauth_scope not in scope.split()
                or type(value.get('expires_in')) is not int or not 0 < value['expires_in'] <= 86400):
            raise ValueError('Required grant not confirmed')
        return dict(accessToken=value['access_token'], refreshToken=refresh,
                    expiresAt=self.config.clock()+value['expires_in'], scope=self.oauth_scope)

    def access_grant(self, scope, version, *, guard=lambda: None):
        guard()
        self.permitted(scope)
        grant = self.config.vault.load(scope, version)
        if grant['expiresAt'] <= self.config.clock()+60:
            def exchange(previous):
                guard()
                self.permitted(scope)
                value = self.token_request(dict(client_id=self.config.client_id,
                    client_secret=self.config.client_secret, refresh_token=previous['refreshToken'],
                    grant_type='refresh_token'))
                self.permitted(scope)
                guard()
                return self.token_grant(value, previous)
            grant = self.config.vault.refresh(scope, version, grant, exchange)
        self.permitted(scope)
        guard()
        if self.version(scope) != version or grant['expiresAt'] <= self.config.clock()+60:
            raise ValueError('Grant changed or expired')
        return grant


def register_google_connection_routes(app, repo, *, config=None, revalidate=None):
    register_business_consent_routes(app, repo, GoogleConnection(repo, config), 'google', revalidate=revalidate)
