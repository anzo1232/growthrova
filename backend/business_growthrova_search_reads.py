"""Explicit saved-search-grant bridge; selection/consent never grants execution.

Host bindings pin a verified property to one grant. Rotate binding version for
authority changes. Status/queue use metadata only; refresh happens in the worker
through the existing durable refresh reservation. No host or worker is installed.
"""
from dataclasses import dataclass, field
import hashlib
import json
import re

import requests

from business_growthrova_search import SearchBinding, SearchConfig, SearchConsoleAdapter
from business_search_property import normalise


@dataclass(frozen=True)
class SearchReadBinding:
    owner_id: str
    organisation_id: str
    property_id: str
    label: str
    version: str
    grant_version: str
    enabled: bool = False
    verified: bool = False


@dataclass(frozen=True)
class SearchPropertyReadConfig:
    resolve: object = field(default=None, repr=False)
    authorised: object = field(default=None, repr=False)
    http: object = field(default=None, repr=False)


class SearchGrantAdapter(SearchConsoleAdapter):
    def __init__(self, connection, config):
        self.connection, self.config = connection, config
        super().__init__(self.resolve_grant, http=config.http)

    def selected(self, scope):
        if not callable(self.config.resolve) or not callable(self.config.authorised):
            raise ValueError('Search read authority is not configured')
        value = self.config.resolve(*scope)
        if (not isinstance(value, SearchReadBinding) or value.enabled is not True or value.verified is not True
                or (value.owner_id, value.organisation_id) != scope
                or not isinstance(value.grant_version, str) or not re.fullmatch(r'[a-f0-9]{32}', value.grant_version)
                or not isinstance(value.version, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value.version)
                or not isinstance(value.label, str) or not value.label.strip() or len(value.label) > 200
                or any(ord(c) < 32 for c in value.label)
                or normalise(dict(propertyId=value.property_id, notes=''))['propertyId'] != value.property_id):
            raise ValueError('Search read binding is unavailable')
        return value

    def permitted(self, scope, selected):
        self.connection.permitted(scope)
        if (self.selected(scope) != selected
                or self.config.authorised(*scope, selected) is not True
                or selected.property_id not in self.connection.roster(scope)
                or self.connection.version(scope) != selected.grant_version
                or self.selected(scope) != selected):
            raise ValueError('Search read connection changed')

    def metadata(self, scope, selected):
        # Include every public binding field and OAuth policy version. Consent
        # rotation or property/policy changes fence already-queued snapshots.
        version = hashlib.sha256(json.dumps([
            selected.owner_id, selected.organisation_id, selected.property_id,
            selected.label, selected.version, selected.grant_version,
            self.connection.config.version], separators=(',', ':')).encode()).hexdigest()
        return SearchBinding(*scope, selected.property_id, selected.label, version,
                             enabled=True, verified=True)

    def account(self, owner, business):
        scope = (owner, business)
        try:
            selected = self.selected(scope)
            self.permitted(scope, selected)
            return self.identity(self.metadata(scope, selected))
        except Exception:
            return None

    def authorised(self, owner, business, account):
        current = self.account(owner, business)
        return current is not None and current == account

    def resolve_grant(self, owner, business, platform):
        if platform != self.platform:
            return None
        scope = (owner, business)
        selected = self.selected(scope)
        self.permitted(scope, selected)
        grant = self.connection.config.vault.load(scope, selected.grant_version)
        if grant['expiresAt'] <= self.connection.config.clock()+60:
            raise ValueError('Search grant needs refresh')
        self.permitted(scope, selected)
        from dataclasses import replace
        return replace(self.metadata(scope, selected), access_token=grant['accessToken'])

    def read(self, snap):
        scope = (snap['ownerId'], snap['organisationId'])
        selected = self.selected(scope)
        expected = self.identity(self.metadata(scope, selected))
        if expected != snap['account']:
            raise ValueError('Search read connection changed')

        def checked():
            self.permitted(scope, selected)
            if self.identity(self.metadata(scope, selected)) != expected:
                raise ValueError('Search read policy changed')

        checked()
        self.connection.access_grant(scope, selected.grant_version, guard=checked)
        checked()
        result = super().read(snap)
        checked()
        return result

    def wire(self, method, url, binding, **options):
        # Streaming bounds allocation as well as accepted response size. No
        # redirects, ambient auth, pagination or automatic retry.
        with requests.Session() as session:
            session.trust_env = False
            transport = self.http or session
            with getattr(transport, method)(url, headers={'Authorization': 'Bearer '+binding.access_token},
                    timeout=(3, 10), allow_redirects=False, stream=True, **options) as response:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 262144:
                        raise ValueError('Search response exceeds bound')
                if response.status_code != 200:
                    raise ValueError('Search read unconfirmed')
                return json.loads(body)

    def search_config(self):
        return SearchConfig(enabled=True, adapter=self, authorised=self.authorised,
                            clock=self.connection.config.clock)
