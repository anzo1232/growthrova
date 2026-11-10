"""Explicit saved-grant bridge for existing exact-account discovery only.

No execution adapter, credential-wide roster or automatic grant is installed.
The host pins each roster to a reviewed consent version and rotates its own
version whenever developer configuration, accounts or read authority change.
"""
from dataclasses import dataclass, field
import re

from business_growthrova_paid_discovery import DiscoveryBinding, PaidAccountDiscovery


@dataclass(frozen=True)
class GoogleReadBinding:
    owner_id: str
    organisation_id: str
    version: str
    grant_version: str
    account_ids: tuple
    enabled: bool = False
    developer_token: str = field(default='', repr=False)
    manager_id: str = ''


@dataclass(frozen=True)
class GoogleAccountReadConfig:
    resolve: object = field(default=None, repr=False)
    authorised: object = field(default=None, repr=False)
    http: object = field(default=None, repr=False)


class GoogleGrantDiscovery:
    def __init__(self, connection, config, fallback=None):
        self.connection, self.config, self.fallback = connection, config, fallback

    def observe_pages(self, scope, platform):
        reader = getattr(self.fallback, 'observe_pages', None)
        return reader(scope, platform) if callable(reader) else dict(available=False, pages=[])

    def observe_linkage(self, scope, platform, account_id, page_id):
        reader = getattr(self.fallback, 'observe_linkage', None)
        return reader(scope, platform, account_id, page_id) if callable(reader) else dict(available=False)

    def selected(self, scope):
        cfg = self.config
        if not callable(cfg.resolve) or not callable(cfg.authorised):
            return None
        value = cfg.resolve(*scope)
        if (not isinstance(value, GoogleReadBinding) or value.enabled is not True
                or (value.owner_id, value.organisation_id) != scope
                or not isinstance(value.grant_version, str) or not re.fullmatch(r'[a-f0-9]{32}', value.grant_version)
                or not isinstance(value.version, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value.version)
                or not isinstance(value.account_ids, tuple) or not 1 <= len(value.account_ids) <= 5
                or any(not isinstance(v, str) or not re.fullmatch(r'[0-9]{10}', v) for v in value.account_ids)
                or len(set(value.account_ids)) != len(value.account_ids)
                or not isinstance(value.developer_token, str) or not value.developer_token
                or len(value.developer_token) > 8192 or any(ord(c) < 33 for c in value.developer_token)
                or not isinstance(value.manager_id, str) or value.manager_id and not re.fullmatch(r'[0-9]{10}', value.manager_id)):
            return None
        return value

    def permitted(self, scope, selected):
        self.connection.permitted(scope)
        if (self.selected(scope) != selected
                or self.config.authorised(*scope, selected) is not True
                or self.selected(scope) != selected
                or self.connection.version(scope) != selected.grant_version):
            raise ValueError('Google account read connection changed')

    def observe(self, scope, platform):
        if platform != 'google':
            return self.fallback.observe(scope, platform) if self.fallback else dict(available=False, accounts=[])
        selected = self.selected(scope)
        if selected is None:
            return dict(available=False, accounts=[])
        guard = lambda: self.permitted(scope, selected)
        guard()
        self.connection.access_grant(scope, selected.grant_version, guard=guard)

        def resolve(owner, organisation, target):
            if (owner, organisation, target) != (*scope, 'google'):
                return None
            guard()
            grant = self.connection.config.vault.load(scope, selected.grant_version)
            if grant['expiresAt'] <= self.connection.config.clock()+60:
                raise ValueError('Google permission needs refresh')
            return DiscoveryBinding(*scope, 'google', selected.version+'_'+selected.grant_version,
                selected.account_ids, enabled=True, access_token=grant['accessToken'],
                developer_token=selected.developer_token, manager_id=selected.manager_id)

        reader = PaidAccountDiscovery(resolve, lambda *args: (guard() is None), http=self.config.http)
        result = reader.observe(scope, platform)
        guard()
        return result
