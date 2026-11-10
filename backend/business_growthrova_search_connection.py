"""Dedicated read-only Search Console consent and scoped property discovery.

Explicit host config only. The property roster is a reviewed tenant allowlist,
not a user-supplied query or an automatic binding for the search worker. Google
sites.list has no pagination; oversized rosters/responses fail without disclosure.
See https://developers.google.com/webmaster-tools/v1/sites/list.
"""
from dataclasses import dataclass, field
import json

import requests
from flask import jsonify, request
from business_growthrova_consent import register_business_consent_routes
from business_growthrova_google_connection import GoogleConnection, GoogleConnectionConfig
from business_marketing_drafts import MarketingDraftError
from business_search_property import normalise


@dataclass(frozen=True)
class SearchConnectionConfig(GoogleConnectionConfig):
    # Return a tuple of 1–50 exact properties reviewed for this business.
    # Rotate config.version when authority/roster policy changes.
    property_roster: object = field(default=None, repr=False)
    property_reads: object = field(default=None, repr=False)


class SearchConnection(GoogleConnection):
    provider = 'search'
    oauth_scope = 'https://www.googleapis.com/auth/webmasters.readonly'
    callback_path = '/growthrova-search-callback.html'

    def __init__(self, repo, config=None):
        super().__init__(repo, config or SearchConnectionConfig())

    def available(self):
        # Custom host vaults must explicitly identify this namespace too. An
        # accidentally supplied Ads vault must never become a search grant.
        return super().available() and getattr(self.config.vault, 'provider', None) == 'search'

    @staticmethod
    def make_vault(repo, key, authorised):
        from business_growthrova_google_vault import GoogleGrantVault
        return GoogleGrantVault(repo, key, authorised, provider='search')

    def roster(self, scope):
        self.permitted(scope)
        if not callable(self.config.property_roster):
            raise ValueError('Business property selection is not configured')
        values = self.config.property_roster(*scope)
        if (not isinstance(values, tuple) or not 1 <= len(values) <= 50
                or any(not isinstance(v, str) or not v for v in values)
                or len(set(values)) != len(values)):
            raise ValueError('Invalid business property selection')
        for value in values:
            if normalise(dict(propertyId=value, notes=''))['propertyId'] != value:
                raise ValueError('Property selection changed')
        return values

    def discover(self, scope, guard):
        self.permitted(scope)
        version = self.version(scope)
        roster = self.roster(scope)
        config_version = self.config.version
        if version is None:
            raise ValueError('Connect Search Console first')

        def checked():
            guard()
            self.permitted(scope)
            if (self.config.version != config_version or self.version(scope) != version
                    or self.roster(scope) != roster):
                raise ValueError('Search connection changed')

        grant = self.access_grant(scope, version, guard=checked)
        checked()
        with requests.Session() as session:
            session.trust_env = False
            transport = self.config.http or session
            with transport.get('https://www.googleapis.com/webmasters/v3/sites',
                    headers={'Authorization': 'Bearer '+grant['accessToken']},
                    timeout=(3, 10), allow_redirects=False, stream=True) as response:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 262144:
                        raise ValueError('Property response exceeds selection bound')
                if response.status_code != 200:
                    raise ValueError('Property discovery unconfirmed')
                value = json.loads(body)
        checked()
        if not isinstance(value, dict) or not isinstance(value.get('siteEntry', []), list):
            raise ValueError('Invalid property response')
        entries = value.get('siteEntry', [])
        if len(entries) > 500:
            raise ValueError('Property response exceeds selection bound')
        properties, seen = [], set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('Invalid property response')
            ident = entry.get('siteUrl')
            if not isinstance(ident, str) or ident not in roster:
                continue  # Never disclose unrelated properties from the account.
            permission = entry.get('permissionLevel')
            if ident in seen or permission not in ('siteOwner', 'siteFullUser', 'siteRestrictedUser', 'siteUnverifiedUser'):
                raise ValueError('Invalid selected property response')
            seen.add(ident)
            properties.append(dict(propertyId=ident, permission=permission,
                selectable=permission != 'siteUnverifiedUser'))
        checked()
        return dict(connectionVersion=version, observedAt=self.config.clock(), properties=properties,
                    source='google_search_console_sites_list')


def register_search_connection_routes(app, repo, *, config=None, revalidate=None):
    service = SearchConnection(repo, config)
    register_business_consent_routes(app, repo, service, 'search', revalidate=revalidate)

    @app.post('/api/growthrova/organisations/<organisation_id>/search-connection/properties')
    def search_connection_properties(organisation_id):
        scope = repo._scope(organisation_id)
        if request.get_json(silent=True) != {}:
            raise MarketingDraftError('Review properties for this business without credential or account overrides.')

        def checked():
            if revalidate and revalidate() is not None:
                raise MarketingDraftError('Business access changed.', 'access_denied', 403)
            if repo._scope(organisation_id) != scope:
                raise MarketingDraftError('Business access changed.', 'access_denied', 403)

        try:
            checked()
            result = service.discover(scope, checked)
            checked()
        except MarketingDraftError:
            raise
        except Exception:
            raise MarketingDraftError('Search properties could not be confirmed. Check the dedicated Search Console connection and business property setup. Saved preparation is preserved.', 'connection_unavailable', 503)
        return jsonify(result)
