"""Optional saved Meta grant bridge to bounded assigned-account reads.

The host reviews app/token/permission eligibility and pins an exact grant and
consent configuration. This installs no execution authority or account roster.
"""
from dataclasses import dataclass, field
import math
import re

from business_growthrova_consent import _plain
from business_growthrova_paid_discovery import DiscoveryBinding, PaidAccountDiscovery


@dataclass(frozen=True)
class MetaReadBinding:
    owner_id: str
    organisation_id: str
    version: str
    grant_version: str
    consent_version: str
    account_ids: tuple
    enabled: bool = False
    page_ids: tuple = ()
    linkage_checks: bool = False
    page_task_checks: bool = False  # Reviewed user-token Page edge; rotate version on enablement.


@dataclass(frozen=True)
class MetaAccountReadConfig:
    resolve: object = field(default=None, repr=False)
    authorised: object = field(default=None, repr=False)
    http: object = field(default=None, repr=False)


class MetaGrantDiscovery:
    def __init__(self, connection, config, fallback=None):
        self.connection, self.config, self.fallback = connection, config, fallback

    def selected(self, scope):
        cfg = self.config
        if not callable(cfg.resolve) or not callable(cfg.authorised):
            return None
        value = cfg.resolve(*scope)
        if (not isinstance(value, MetaReadBinding) or value.enabled is not True
                or (value.owner_id, value.organisation_id) != scope
                or not isinstance(value.version, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value.version)
                or not isinstance(value.grant_version, str) or not re.fullmatch(r'[a-f0-9]{32}', value.grant_version)
                or not _plain(value.consent_version, 100)
                or not isinstance(value.account_ids, tuple) or not 1 <= len(value.account_ids) <= 5
                or any(not isinstance(v, str) or not re.fullmatch(r'[0-9]{1,40}', v) for v in value.account_ids)
                or len(set(value.account_ids)) != len(value.account_ids)):
            return None
        if (not isinstance(value.page_ids, tuple) or len(value.page_ids) > 5
                or any(not isinstance(v, str) or not re.fullmatch(r'[0-9]{1,40}', v) for v in value.page_ids)
                or len(set(value.page_ids)) != len(value.page_ids)):
            return None
        return value

    def grant(self, scope, selected):
        connection = self.connection
        connection.permitted(scope)
        if (self.selected(scope) != selected
                or self.config.authorised(*scope, selected) is not True
                or self.selected(scope) != selected
                or connection.config.version != selected.consent_version
                or connection.version(scope) != selected.grant_version):
            raise ValueError('Meta account read connection changed')
        grant = connection.config.vault.load(scope, selected.grant_version)
        expiry = grant.get('expiresAt')
        if (not _plain(grant.get('accessToken'), 8192)
                or grant.get('loginConfigId') != connection.config.login_config_id
                or grant.get('graphVersion') != connection.config.graph_version
                or (expiry is not None and (type(expiry) not in (int, float)
                    or not math.isfinite(expiry) or expiry <= connection.config.clock()+60))):
            raise ValueError('Meta permission needs reconnection or review')
        # No expiry observation is not a perpetual-access claim. The assigned
        # account read still has to succeed; errors never trigger token retries.
        connection.permitted(scope)
        if (self.config.authorised(*scope, selected) is not True
                or self.selected(scope) != selected
                or connection.config.version != selected.consent_version
                or connection.version(scope) != selected.grant_version):
            raise ValueError('Meta account read connection changed')
        return grant

    def observe(self, scope, platform):
        return self._observe(scope, platform, pages=False)

    def observe_pages(self, scope, platform):
        return self._observe(scope, platform, pages=True)

    def observe_linkage(self, scope, platform, account_id, page_id):
        return self._observe(scope, platform, pages=False, pair=(account_id, page_id))

    def _observe(self, scope, platform, *, pages, pair=None):
        if platform != 'meta':
            if pair is not None:
                reader = getattr(self.fallback, 'observe_linkage', None)
                return reader(scope, platform, *pair) if callable(reader) else dict(available=False)
            if pages:
                reader = getattr(self.fallback, 'observe_pages', None)
                return reader(scope, platform) if callable(reader) else dict(available=False, pages=[])
            return self.fallback.observe(scope, platform) if self.fallback else dict(available=False, accounts=[])
        selected = self.selected(scope)
        if pair is not None and (selected is None or selected.linkage_checks is not True
                or pair[0] not in selected.account_ids or pair[1] not in selected.page_ids):
            return dict(available=False)
        if selected is None or (pages and not selected.page_ids):
            return dict(available=False, **{'pages' if pages else 'accounts': []})

        def resolve(owner, organisation, target):
            if (owner, organisation, target) != (*scope, 'meta'):
                return None
            grant = self.grant(scope, selected)
            return DiscoveryBinding(*scope, 'meta', selected.version+'_'+selected.grant_version,
                selected.account_ids, enabled=True, access_token=grant['accessToken'],
                graph_version=self.connection.config.graph_version, page_ids=selected.page_ids,
                linkage_checks=selected.linkage_checks, page_task_checks=selected.page_task_checks)

        reader = PaidAccountDiscovery(resolve, lambda *args: (self.grant(scope, selected) is not None),
                                      http=self.config.http)
        result = (reader.observe_linkage(scope, platform, *pair) if pair is not None
                  else reader.observe_pages(scope, platform) if pages else reader.observe(scope, platform))
        self.grant(scope, selected)
        return result
