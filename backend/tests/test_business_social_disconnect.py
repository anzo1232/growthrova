"""Disconnected synthetic provider, actual auth/application; never real revocation."""
import unittest
import requests
from tests import test_business_social_accounts as accounts


class DisconnectProvider(accounts.Provider):
    def __init__(self):
        super().__init__(dict(activeSocialAccounts=['twitter'], displayNames=[
            dict(platform='twitter', id='x42', displayName='QA Workshop')]))
        self.deletes = []
        self.delete_error = None
        self.after_delete = lambda: None
        self.ack = None

    def delete(self, url, **options):
        self.deletes.append((url, options))
        self.after_delete()
        if self.delete_error:
            raise self.delete_error
        old = self.payload
        self.payload = self.ack if self.ack is not None else dict(status='success', platform=options['json']['platform'], refId='synthetic-receipt')
        try:
            return super().get(url, **options)
        finally:
            self.payload = old


class SocialDisconnectTests(unittest.TestCase):
    setUp = accounts.SocialAccountTests.setUp
    create = accounts.SocialAccountTests.create

    def configure(self, **changes):
        from business_social_accounts import SocialAccountConfig
        self.provider = DisconnectProvider()
        self.keys = []
        def resolve(org):
            self.keys.append(org)
            return 'synthetic-profile'
        config = SocialAccountConfig(**{**dict(enabled=True, disconnect_enabled=True,
            api_key='synthetic-master', profile_key_for_org=resolve), **changes})
        self.client = self.create(social_account_config=config, social_account_http=self.provider).test_client()

    def disconnect(self, payload=None):
        return self.client.post(f'/api/growthrova/organisations/{accounts.ORG}/social-accounts/disconnect',
            json=dict(channel='x', destinationId='x42') if payload is None else payload, headers=self.headers)

    def test_explicit_scoped_disconnect_requires_matching_destination_and_reports_ack_only(self):
        self.configure()
        response = self.disconnect()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['state'], 'disconnect_acknowledged')
        self.assertFalse(response.json['canPublish'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        url, options = self.provider.deletes[0]
        self.assertEqual(url, 'https://api.ayrshare.com/api/profiles/social')
        self.assertEqual(options['json'], {'platform': 'twitter'})
        self.assertEqual(options['headers']['Profile-Key'], 'synthetic-profile')
        self.assertFalse(options['allow_redirects'])
        self.assertEqual(len(self.provider.deletes), 1)
        self.assertNotIn('synthetic-profile', response.get_data(as_text=True))

    def test_disabled_invalid_missing_and_changed_identity_never_disconnect(self):
        self.configure(disconnect_enabled=False)
        self.assertEqual(self.disconnect().status_code, 503)
        self.assertEqual(self.keys, [])
        self.configure(profile_key_for_org=lambda org: None)
        self.assertEqual(self.disconnect().status_code, 409)
        self.assertEqual(self.provider.deletes, [])
        self.configure()
        for payload in ({}, [], {'channel': 'twitter', 'destinationId': 'x42'},
                        {'channel': 'x', 'destinationId': 'x42', 'profileKey': 'foreign'}):
            self.assertEqual(self.disconnect(payload).status_code, 400)
        self.assertEqual(self.disconnect(dict(channel='x', destinationId='other')).status_code, 409)
        self.assertEqual(self.provider.deletes, [])

    def test_scope_revoked_before_dispatch_and_after_ack_never_releases_success(self):
        self.configure()
        self.transport.allowed = False
        self.assertEqual(self.disconnect().status_code, 403)
        self.assertEqual(self.keys, [])
        self.configure()
        self.transport.allowed = True
        self.provider.on_read = lambda: setattr(self.transport, 'allowed', False)
        self.assertEqual(self.disconnect().status_code, 403)
        self.assertEqual(self.provider.deletes, [])
        self.configure()
        self.transport.allowed = True
        self.provider.after_delete = lambda: setattr(self.transport, 'allowed', False)
        self.assertEqual(self.disconnect().status_code, 403)
        self.assertEqual(len(self.provider.deletes), 1)

    def test_unknown_outcome_never_retried_or_reported_disconnected(self):
        self.configure()
        self.provider.delete_error = requests.Timeout('private-profile-token')
        response = self.disconnect()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['code'], 'social_disconnect_uncertain')
        self.assertNotIn('private-profile-token', response.get_data(as_text=True))
        self.assertEqual(len(self.provider.deletes), 1)

    def test_each_required_channel_maps_exactly_and_campaign_survives_reopen(self):
        self.configure()
        saved = self.client.post(self.root, json=self.payload, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.json)
        for channel in ('instagram', 'facebook', 'linkedin', 'tiktok', 'x'):
            platform = 'twitter' if channel == 'x' else channel
            self.provider.payload = dict(activeSocialAccounts=[platform], displayNames=[
                dict(platform=platform, id='account42', displayName='QA Destination')])
            result = self.disconnect(dict(channel=channel, destinationId='account42'))
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(self.provider.deletes[-1][1]['json'], {'platform': platform})
        reopened = self.create().test_client().get(self.root+'/'+self.payload['id'], headers=self.headers)
        self.assertEqual(reopened.json['document'], saved.json['document'])

    def test_rejected_or_malformed_acknowledgement_is_uncertain_without_retry(self):
        self.configure()
        for ack in ({}, [], dict(status='error'), dict(status='success', platform='facebook')):
            self.provider.ack = ack
            before = len(self.provider.deletes)
            response = self.disconnect()
            self.assertEqual(response.status_code, 503, response.json)
            self.assertEqual(response.json['code'], 'social_disconnect_uncertain')
            self.assertEqual(len(self.provider.deletes), before+1)

    def test_revocation_during_vault_resolution_blocks_inventory_and_unlink(self):
        def revoke(org):
            self.transport.allowed = False
            return 'synthetic-profile'
        self.configure(profile_key_for_org=revoke)
        self.assertEqual(self.disconnect().status_code, 403)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.provider.deletes, [])
