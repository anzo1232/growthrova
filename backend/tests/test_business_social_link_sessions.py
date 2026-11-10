"""Synthetic link-session transport; actual authenticated application, no account grants."""
from datetime import datetime, timedelta, timezone
import unittest
from tests import test_business_social_accounts as account_tests


class LinkProvider(account_tests.Provider):
    def post(self, url, **options):
        return self.get(url, **options)


class SocialLinkSessionTests(unittest.TestCase):
    setUp = account_tests.SocialAccountTests.setUp
    create = account_tests.SocialAccountTests.create

    def configure(self, **changes):
        from business_social_accounts import SocialAccountConfig
        self.keys = []
        def resolve(org):
            self.keys.append(org)
            return 'synthetic-profile'
        self.provider = LinkProvider(dict(status='success', sessionId='qa-session',
            url='https://profile.ayrshare.com?session=ayr_ls_synthetic&domain=qa&logout=true',
            expiresAt=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),
            secret='MUST-NOT-RETURN'))
        config = SocialAccountConfig(**dict(dict(enabled=True, linking_enabled=True,
            api_key='synthetic-master', profile_key_for_org=resolve), **changes))
        self.client = self.create(social_account_config=config, social_account_http=self.provider).test_client()

    def link(self, payload=None):
        return self.client.post('/api/growthrova/organisations/cccccccc-cccc-4ccc-8ccc-cccccccccccc/social-accounts/link-session',
                                json={} if payload is None else payload, headers=self.headers)

    def test_scoped_link_is_short_lived_no_store_no_publish_no_email(self):
        self.configure()
        result = self.link()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['url'], self.provider.payload['url'])
        self.assertFalse(result.json['canPublish'])
        self.assertEqual(result.headers['Cache-Control'], 'no-store')
        self.assertEqual(result.headers['Referrer-Policy'], 'no-referrer')
        self.assertNotIn('MUST-NOT-RETURN', result.get_data(as_text=True))
        self.assertNotIn('synthetic-profile', result.get_data(as_text=True))
        self.assertEqual(len(self.provider.calls), 1)
        url, options = self.provider.calls[0]
        self.assertEqual(url, 'https://api.ayrshare.com/api/profiles/link-sessions')
        self.assertEqual(options['headers']['Profile-Key'], 'synthetic-profile')
        self.assertEqual(options['json'], dict(logout=True,
            allowedSocial=['instagram', 'facebook', 'linkedin', 'tiktok', 'twitter']))
        self.assertFalse(options['allow_redirects'])
        self.assertTrue(options['stream'])
        self.assertEqual(self.keys, [account_tests.ORG, account_tests.ORG])

    def test_disabled_missing_profile_and_client_selectors_never_create_session(self):
        self.configure(linking_enabled=False)
        self.assertEqual(self.link().status_code, 503)
        self.assertEqual(self.keys, [])
        self.assertEqual(self.provider.calls, [])
        self.configure(profile_key_for_org=lambda org: None)
        self.assertEqual(self.link().status_code, 409)
        self.assertEqual(self.provider.calls, [])
        self.configure()
        for payload in ({'profileKey':'foreign'}, {'email':{'to':'test@example.org'}}, {'redirect':'https://evil.example'}, []):
            self.assertEqual(self.link(payload).status_code, 400)
        self.assertEqual(self.provider.calls, [])

    def test_foreign_or_revoked_access_never_releases_link(self):
        self.configure()
        self.transport.allowed = False
        self.assertEqual(self.link().status_code, 403)
        self.assertEqual(self.keys, [])
        self.assertEqual(self.provider.calls, [])
        self.transport.allowed = True
        self.provider.on_read = lambda: setattr(self.transport, 'allowed', False)
        result = self.link()
        self.assertEqual(result.status_code, 403)
        self.assertNotIn('ayr_ls_', result.get_data(as_text=True))

    def test_revoked_during_vault_resolution_does_not_create_a_session(self):
        def revoked(org):
            self.transport.allowed = False
            return 'synthetic-profile'
        self.configure(profile_key_for_org=revoked)
        self.assertEqual(self.link().status_code, 403)
        self.assertEqual(self.provider.calls, [])

    def test_untrusted_urls_expiry_errors_redirects_and_timeout_held_without_retry(self):
        import requests
        self.configure()
        good = dict(self.provider.payload)
        for url in ('http://profile.ayrshare.com?session=x',
                    'https://profile.ayrshare.com.evil.example?session=x',
                    'https://user@profile.ayrshare.com?session=x',
                    'https://profile.ayrshare.com:444?session=x',
                    'https://profile.ayrshare.com?session=x&redirect=https://evil.example',
                    'https://profile.ayrshare.com?session=x&logout=false',
                    'https://profile.ayrshare.com?session=x&session=y&logout=true',
                    'https://profile.ayrshare.com?domain=qa&logout=true',
                    'https://profile.ayrshare.com/foreign?session=x&logout=true'):
            with self.subTest(url=url):
                self.provider.payload = {**good, 'url':url}
                self.assertEqual(self.link().status_code, 503)
        for expiry in ('invalid', '2099-01-01T00:00:00Z', '2020-01-01T00:00:00Z'):
            self.provider.payload = {**good, 'expiresAt':expiry}
            self.assertEqual(self.link().status_code, 503)
        self.provider.payload = {**good, 'status':'error'}
        self.assertEqual(self.link().status_code, 503)
        self.provider.payload = good
        self.provider.status = 302
        self.assertEqual(self.link().status_code, 503)
        self.provider.status = 200
        self.provider.on_read = lambda: (_ for _ in ()).throw(requests.Timeout('private-response'))
        before = len(self.provider.calls)
        result = self.link()
        self.assertEqual(result.status_code, 503)
        self.assertEqual(len(self.provider.calls), before+1, 'No automatic retries')
        self.assertNotIn('private-response', result.get_data(as_text=True))
