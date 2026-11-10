"""Optional Meta Login for Business handoff; no discovery/execution installation.

The operator supplies a reviewed Meta login configuration. That configuration
controls token type, permissions and asset selection, not browser-supplied scopes.
Current app/configuration eligibility must be verified before enabling a host.
No automatic long-lived conversion or refresh: reconnect is an explicit owner act.
"""
from dataclasses import dataclass, field
import json
import re
import time
from urllib.parse import urlencode, urlsplit

import requests
from business_growthrova_consent import BusinessConsent, _plain, register_business_consent_routes
from business_growthrova_grants import BusinessGrantVault

CALLBACK = '/growthrova-meta-callback.html'


@dataclass(frozen=True)
class MetaConnectionConfig:
    enabled: bool = False
    client_id: str = ''
    client_secret: str = field(default='', repr=False)
    login_config_id: str = ''
    graph_version: str = ''  # Explicit reviewed version, no assumed latest.
    redirect_uri: str = ''
    version: str = ''  # Rotate on app/configuration/token-type/authority changes.
    vault: object = field(default=None, repr=False)
    vault_key: bytes = field(default=b'', repr=False)
    authorised: object = field(default=None, repr=False)
    clock: object = time.time
    http: object = field(default=None, repr=False)
    account_reads: object = field(default=None, repr=False)


class MetaConnection(BusinessConsent):
    def __init__(self, repo, config=None):
        super().__init__(repo, config or MetaConnectionConfig(), 'meta')

    @staticmethod
    def make_vault(repo, key, authorised):
        return BusinessGrantVault(repo, key, authorised, 'meta')

    def available(self):
        cfg = self.config
        parsed = urlsplit(cfg.redirect_uri)
        return (cfg.enabled is True and bool(re.fullmatch(r'[0-9]{1,40}', cfg.client_id))
                and bool(re.fullmatch(r'[0-9]{1,40}', cfg.login_config_id))
                and bool(re.fullmatch(r'v[1-9][0-9]{0,2}\.0', cfg.graph_version))
                and _plain(cfg.client_secret, 8192) and _plain(cfg.version, 100)
                and parsed.scheme == 'https' and bool(parsed.hostname)
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path == CALLBACK and callable(cfg.authorised)
                and callable(getattr(cfg.vault, 'status', None)) and callable(getattr(cfg.vault, 'replace', None)))

    def authorization_url(self, state, verifier):
        # Confidential server exchange, not implicit browser token delivery.
        # Do not add Google's PKCE/scope fields to this separate Meta protocol.
        return f'https://www.facebook.com/{self.config.graph_version}/dialog/oauth?' + urlencode(dict(
            client_id=self.config.client_id, redirect_uri=self.config.redirect_uri,
            response_type='code', override_default_response_type='true',
            config_id=self.config.login_config_id, state=state))

    def exchange(self, code, verifier):
        options = dict(params=dict(client_id=self.config.client_id, client_secret=self.config.client_secret,
            redirect_uri=self.config.redirect_uri, code=code),
            timeout=(3, 10), allow_redirects=False, stream=True)
        # Meta's documented token endpoint uses GET. Never log its query or
        # exception URL (app secret/code); transport/proxy logging needs review.
        with requests.Session() as session:
            session.trust_env = False
            transport = self.config.http or session
            with transport.get(f'https://graph.facebook.com/{self.config.graph_version}/oauth/access_token', **options) as response:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 32768:
                        raise ValueError('Invalid token response')
                if response.status_code != 200:
                    raise ValueError('Consent exchange unconfirmed')
                value = json.loads(body)
        if (not isinstance(value, dict) or 'error' in value
                or not _plain(value.get('access_token'), 8192)
                or not isinstance(value.get('token_type'), str) or value['token_type'].lower() != 'bearer'):
            raise ValueError('Required token not confirmed')
        expiry = value.get('expires_in')
        if expiry is not None and (type(expiry) is not int or not 0 <= expiry <= 315360000):
            raise ValueError('Invalid token expiry')
        # Absent/zero expiry does not mean permission or token lasts forever.
        return dict(accessToken=value['access_token'], expiresAt=self.config.clock()+expiry if expiry else None,
                    loginConfigId=self.config.login_config_id, graphVersion=self.config.graph_version)


def register_meta_connection_routes(app, repo, *, config=None, revalidate=None):
    register_business_consent_routes(app, repo, MetaConnection(repo, config), 'meta', revalidate=revalidate)
