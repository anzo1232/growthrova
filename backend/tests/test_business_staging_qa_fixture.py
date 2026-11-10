"""Staging credential fixture safety; no network, secrets or live account access."""
import unittest
from tests.business_staging_auth_live import validate_qa_accounts

class StagingQAFixtureTests(unittest.TestCase):
    def setUp(self):
        self.accounts=[
            {'email':'qa+first@example.test','password':'dummy','id':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'},
            {'email':'qa+second@example.test','password':'dummy','id':'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'},
        ]
    def test_two_distinct_accounts_pass(self):
        self.assertTrue(validate_qa_accounts(self.accounts))
    def test_duplicate_email_fails_before_login(self):
        self.accounts[1]['email']='QA+FIRST@example.test'
        with self.assertRaisesRegex(RuntimeError,'distinct staging QA emails'):
            validate_qa_accounts(self.accounts)
    def test_duplicate_identity_fails_before_login(self):
        self.accounts[1]['id']=self.accounts[0]['id']
        with self.assertRaisesRegex(RuntimeError,'distinct staging QA identities'):
            validate_qa_accounts(self.accounts)
    def test_invalid_identity_and_empty_password_fail(self):
        self.accounts[1]['id']='not-a-uuid'
        with self.assertRaisesRegex(RuntimeError,'identity is invalid'):
            validate_qa_accounts(self.accounts)
        self.accounts[1]['id']=None
        self.accounts[1]['password']=''
        with self.assertRaisesRegex(RuntimeError,'password missing'):
            validate_qa_accounts(self.accounts)
