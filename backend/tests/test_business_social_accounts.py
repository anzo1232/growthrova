"""Read-only account discovery: synthetic provider/auth, actual application routes."""
from tests import test_business_growthrova_preview as preview
ORG = preview.ORG
import unittest


class SocialAccountTests(unittest.TestCase):
    setUp = preview.GrowthrovaPreviewTests.setUp
    create = preview.GrowthrovaPreviewTests.create
    # Reuse the actual isolated application/auth factory, without inheriting its tests.
    def test_unconfigured_accounts_are_separately_unavailable(self):
        response = self.client.get(f'/api/growthrova/organisations/{ORG}/social-accounts', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual([a['channel'] for a in response.json['accounts']],
                         ['instagram', 'facebook', 'linkedin', 'tiktok', 'x'])
        self.assertTrue(all(a['state'] == 'unavailable' and not a['canPublish'] for a in response.json['accounts']))

    def configured(self, payload):
        self.provider = Provider(payload)
        self.keys = []
        def resolve(organisation_id):
            self.keys.append(organisation_id)
            return 'synthetic-profile' if organisation_id == ORG else None
        self.client = self.create(social_account_config=self.config(resolve),
                                  social_account_http=self.provider).test_client()

    def config(self, resolve):
        from business_social_accounts import SocialAccountConfig
        return SocialAccountConfig(enabled=True, api_key='synthetic-master', profile_key_for_org=resolve)

    def get_accounts(self):
        return self.client.get(f'/api/growthrova/organisations/{ORG}/social-accounts', headers=self.headers)

    def test_exact_destinations_types_expiry_and_secret_redaction(self):
        self.configured(dict(activeSocialAccounts=['instagram', 'facebook', 'linkedin', 'tiktok', 'twitter'],
            displayNames=[dict(platform='instagram', id='ig-42', userId='WRONG-FACEBOOK-USER', displayName='Workshop', type='business'),
                          dict(platform='facebook', id='page-42', displayName='Workshop Page'),
                          dict(platform='linkedin', id='member-42', displayName='Workshop Owner', type='personal'),
                          dict(platform='tiktok', id='tt-42', displayName='Workshop Films', refreshDaysRemaining=-1),
                          dict(platform='twitter', id='x-42', username='workshop')],
            secret='synthetic-master', email='private@example.org'))
        result = self.get_accounts()
        self.assertEqual(result.status_code, 200, result.json)
        accounts = {a['channel']: a for a in result.json['accounts']}
        self.assertEqual(accounts['instagram']['destination']['id'], 'ig-42')
        self.assertEqual(accounts['facebook']['destination']['accountType'], 'page')
        self.assertEqual(accounts['linkedin']['destination']['accountType'], 'personal')
        self.assertEqual(accounts['tiktok']['state'], 'needs_reconnect')
        self.assertEqual(accounts['x']['destination']['id'], 'x-42')
        self.assertTrue(all(not a['canPublish'] for a in accounts.values()))
        text = result.get_data(as_text=True)
        for private in ('synthetic-master', 'synthetic-profile', 'WRONG-FACEBOOK-USER', 'private@example.org'):
            self.assertNotIn(private, text)
        options = self.provider.calls[0][1]
        self.assertEqual(options['headers']['Profile-Key'], 'synthetic-profile')
        self.assertEqual(options['params'], {'instagramDetails': 'true'})
        self.assertFalse(options['allow_redirects'])
        self.assertEqual(self.keys, [ORG, ORG])  # Resolve, then verify mapping before release.

    def test_ambiguous_missing_identity_and_inactive_account_never_pass(self):
        self.configured(dict(activeSocialAccounts=['facebook', 'linkedin', 'instagram'], displayNames=[
            dict(platform='facebook', id='a', displayName='First'), dict(platform='facebook', id='b', displayName='Second'),
            dict(platform='linkedin', id='c', displayName='Company', type='corporate'),
            dict(platform='instagram', displayName='Missing ID'),
            dict(platform='twitter', id='old', displayName='Disconnected')]))
        accounts = {a['channel']: a for a in self.get_accounts().json['accounts']}
        self.assertEqual(accounts['facebook']['state'], 'identity_unverified')
        self.assertIsNone(accounts['facebook']['destination'])
        self.assertEqual(accounts['instagram']['state'], 'identity_unverified')
        self.assertEqual(accounts['linkedin']['destination']['accountType'], 'company')
        self.assertEqual(accounts['x']['state'], 'not_linked')
        self.assertIsNone(accounts['x']['destination'])
        self.provider.payload = {}
        accounts = self.get_accounts().json['accounts']
        self.assertTrue(all(a['state'] == 'not_linked' for a in accounts))

    def test_account_type_holds_preserve_identity_without_granting_publishing(self):
        # A linked identity is not proof that it is a publishing-eligible account.
        self.configured(dict(activeSocialAccounts=['instagram', 'facebook', 'linkedin', 'tiktok', 'twitter'],
            displayNames=[dict(platform='instagram', id='ig-personal', displayName='Personal account', type='personal'),
                          dict(platform='facebook', id='fb-personal', displayName='Personal profile', type='personal'),
                          dict(platform='linkedin', id='li-unknown', displayName='Unknown destination'),
                          dict(platform='tiktok', id='tt1', displayName='Photo account'),
                          dict(platform='twitter', id='x1', displayName='X account')]))
        response = self.get_accounts()
        self.assertEqual(response.status_code, 200, response.json)
        accounts = {a['channel']: a for a in response.json['accounts']}
        for channel in ('instagram', 'facebook'):
            self.assertEqual(accounts[channel]['accountTypeCheck']['state'], 'unsupported')
            self.assertEqual(accounts[channel]['destination']['accountType'], 'personal')
        self.assertEqual(accounts['linkedin']['accountTypeCheck']['state'], 'unverified')
        for channel in ('tiktok', 'x'):
            self.assertEqual(accounts[channel]['accountTypeCheck']['state'], 'unverified')
        self.assertEqual(accounts['instagram']['destination']['id'], 'ig-personal')
        self.assertTrue(all(not a['canPublish'] for a in accounts.values()))

    def test_reported_types_are_separate_from_permissions_and_unknown_types_hold_locally(self):
        self.configured({})
        for platform, kind, expected in [('instagram', 'business', 'business'),
                                         ('instagram', 'creator', 'creator'),
                                         ('facebook', None, 'page'),
                                         ('linkedin', 'personal', 'personal'),
                                         ('linkedin', 'corporate', 'company')]:
            with self.subTest(platform=platform, kind=kind):
                item = dict(platform=platform, id='destination-1', displayName='Destination')
                if kind is not None:
                    item['type'] = kind
                self.provider.payload = dict(activeSocialAccounts=[platform], displayNames=[item])
                account = next(a for a in self.get_accounts().json['accounts'] if a['channel'] == platform)
                self.assertEqual(account['destination']['accountType'], expected)
                self.assertEqual(account['accountTypeCheck']['state'], 'reported')
                self.assertFalse(account['canPublish'])
        # Unexpected provider types must hold one destination, not lose all five.
        for kind in (None, 'new-provider-type', {}, []):
            with self.subTest(kind=kind):
                self.provider.payload = dict(activeSocialAccounts=['linkedin', 'facebook'], displayNames=[
                    dict(platform='linkedin', id='li1', displayName='Unknown LinkedIn', type=kind),
                    dict(platform='facebook', id='page1', displayName='Intact Page')])
                response = self.get_accounts()
                self.assertEqual(response.status_code, 200, response.json)
                accounts = {a['channel']: a for a in response.json['accounts']}
                self.assertEqual(accounts['linkedin']['accountTypeCheck']['state'], 'unverified')
                self.assertEqual(accounts['facebook']['destination']['id'], 'page1')

    def test_denied_owner_and_expired_session_never_resolve_provider_credentials(self):
        self.configured({})
        self.transport.allowed = False
        self.assertEqual(self.get_accounts().status_code, 403)
        self.transport.allowed = True
        self.headers = {'Authorization': 'Bearer expired'}
        self.assertEqual(self.get_accounts().status_code, 403)
        self.assertEqual(self.keys, [])
        self.assertEqual(self.provider.calls, [])

    def test_provider_error_is_safe_and_recovery_replaces_old_inventory(self):
        self.configured(dict(activeSocialAccounts=['twitter'], displayNames=[dict(platform='twitter', id='x1', displayName='Old')]))
        self.assertEqual(self.get_accounts().json['accounts'][-1]['state'], 'reported')
        self.provider.status = 403
        response = self.get_accounts()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('accounts', response.json)
        self.assertNotIn('synthetic-profile', response.get_data(as_text=True))
        self.provider.status = 200
        self.provider.payload = dict(activeSocialAccounts=['twitter'], displayNames=[dict(platform='twitter', id='x2', displayName='New')])
        self.assertEqual(self.get_accounts().json['accounts'][-1]['destination']['id'], 'x2')

    def test_only_explicit_boolean_enablement_and_nonblank_identity_are_accepted(self):
        from business_social_accounts import SocialAccountConfig, account_inventory
        inventory = account_inventory(dict(activeSocialAccounts=['twitter'], displayNames=[
            dict(platform='twitter', id='x-42', displayName='   ')]))
        self.assertEqual(inventory[-1]['state'], 'identity_unverified')
        self.configured({})
        self.client = self.create(social_account_config=SocialAccountConfig(
            enabled='false', api_key='synthetic-master', profile_key_for_org=lambda org: 'synthetic-profile'),
            social_account_http=self.provider).test_client()
        self.assertEqual(self.get_accounts().json['accounts'][0]['state'], 'unavailable')
        self.assertEqual(self.provider.calls, [])

    def test_missing_scoped_profile_never_uses_primary_account(self):
        self.configured({})
        self.client = self.create(social_account_config=self.config(lambda org: None),
                                  social_account_http=self.provider).test_client()
        response = self.get_accounts()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertTrue(all(a['state'] == 'not_linked' for a in response.json['accounts']))
        self.assertEqual(self.provider.calls, [])

    def test_disabled_configuration_never_reads_vault_or_provider(self):
        from business_social_accounts import SocialAccountConfig
        def forbidden(org):
            self.fail('Disabled configuration must not consult credentials')
        self.configured({})
        self.client = self.create(social_account_config=SocialAccountConfig(
            enabled=False, api_key='synthetic-master', profile_key_for_org=forbidden),
            social_account_http=self.provider).test_client()
        self.assertEqual(self.get_accounts().json['accounts'][0]['state'], 'unavailable')
        self.assertEqual(self.provider.calls, [])

    def test_malformed_oversized_redirect_and_timeout_are_recoverable_without_identity(self):
        import requests
        self.configured({})
        for payload in ([], {'displayNames': 'wrong shape'}, {'activeSocialAccounts': [None]},
                        {'secret': 'x' * 65537}):
            self.provider.payload = payload
            response = self.get_accounts()
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('accounts', response.json)
        self.provider.status = 302
        self.assertEqual(self.get_accounts().status_code, 503)
        self.provider.on_read = lambda: (_ for _ in ()).throw(requests.Timeout('synthetic-profile'))
        response = self.get_accounts()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('synthetic-profile', response.get_data(as_text=True))

    def test_revocation_during_provider_lookup_denies_returned_identity(self):
        self.configured({})
        self.provider.on_read = lambda: setattr(self.transport, 'allowed', False)
        self.assertEqual(self.get_accounts().status_code, 403)


class Provider:
    def __init__(self, payload):
        self.payload = payload
        self.status = 200
        self.calls = []
        self.on_read = lambda: None

    def get(self, url, **options):
        import json
        from requests import Response
        self.calls.append((url, options))
        self.on_read()
        response = Response()
        response.status_code = self.status
        response._content = json.dumps(self.payload).encode()
        response._content_consumed = True
        response.iter_content = lambda chunk_size: iter([response._content])
        return response
