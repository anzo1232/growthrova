"""Real scoped application + synthetic vault/provider; no account grants or posts."""
import unittest
from business_social_accounts import SocialAccountConfig
from tests import test_business_social_accounts as accounts
from tests import test_business_social_disconnect as disconnects

ORG = accounts.ORG


class SocialProfileRevocationTests(unittest.TestCase):
    setUp = accounts.SocialAccountTests.setUp
    create = accounts.SocialAccountTests.create

    def configure(self, provider):
        self.profile = 'synthetic-original-profile'
        self.provider = provider
        self.client = self.create(social_account_config=SocialAccountConfig(
            enabled=True, linking_enabled=True, disconnect_enabled=True,
            api_key='synthetic-master', profile_key_for_org=lambda org: self.profile),
            social_account_http=provider).test_client()

    def disconnect(self):
        return self.client.post(f'/api/growthrova/organisations/{ORG}/social-accounts/disconnect',
            json=dict(channel='x', destinationId='x42'), headers=self.headers)

    def test_revoked_or_replaced_mapping_during_inventory_blocks_unlink(self):
        for replacement in (None, 'synthetic-replacement-profile'):
            with self.subTest(replacement=replacement):
                self.configure(disconnects.DisconnectProvider())
                self.provider.on_read = lambda: setattr(self, 'profile', replacement)
                response = self.disconnect()
                self.assertEqual(response.status_code, 503, response.json)
                self.assertEqual(response.json['code'], 'social_disconnect_unavailable')
                self.assertEqual(self.provider.deletes, [], 'Do not mutate a revoked business profile')
                self.assertNotIn('synthetic-original-profile', response.get_data(as_text=True))

    def test_mapping_changes_after_dispatch_are_uncertain_and_never_retried(self):
        self.configure(disconnects.DisconnectProvider())
        self.provider.after_delete = lambda: setattr(self, 'profile', None)
        response = self.disconnect()
        self.assertEqual(response.status_code, 503, response.json)
        self.assertEqual(response.json['code'], 'social_disconnect_uncertain')
        self.assertEqual(len(self.provider.deletes), 1)

    def test_old_inventory_is_not_released_after_profile_replacement(self):
        self.configure(accounts.Provider(dict(activeSocialAccounts=['twitter'], displayNames=[
            dict(platform='twitter', id='old-account', displayName='Old Business')])))
        self.provider.on_read = lambda: setattr(self, 'profile', 'synthetic-replacement-profile')
        response = self.client.get(f'/api/growthrova/organisations/{ORG}/social-accounts', headers=self.headers)
        self.assertEqual(response.status_code, 503, response.json)
        self.assertNotIn('accounts', response.json)
        self.assertNotIn('Old Business', response.get_data(as_text=True))
        self.assertEqual(len(self.provider.calls), 1)

    def test_prepared_bearer_link_not_released_after_mapping_revocation_or_replacement(self):
        # Synthetic provider session only.
        from datetime import datetime, timedelta, timezone
        from tests.test_business_social_link_sessions import LinkProvider
        for replacement in (None, 'synthetic-replacement-profile'):
            with self.subTest(replacement=replacement):
                self.configure(LinkProvider(dict(status='success',
                    url='https://profile.ayrshare.com?session=ayr_ls_private&logout=true',
                    expiresAt=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())))
                self.provider.on_read = lambda: setattr(self, 'profile', replacement)
                response = self.client.post(f'/api/growthrova/organisations/{ORG}/social-accounts/link-session',
                    json={}, headers=self.headers)
                self.assertEqual(response.status_code, 503, response.json)
                self.assertNotIn('ayr_ls_', response.get_data(as_text=True))
                self.assertEqual(len(self.provider.calls), 1, 'Do not automatically create another session')
