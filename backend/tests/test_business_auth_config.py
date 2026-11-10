"""Business login issuer must match JWT-scoped Business PostgREST."""
import unittest
from business_auth_config import business_auth_projects_match

STAGING="https://zbncuxizmjinexifcshe.supabase.co"
LIVE="https://uxfvagyhnstwncbclgaf.supabase.co"

class AuthAlignmentTests(unittest.TestCase):
    def test_exact_project_match_required(self):
        self.assertTrue(business_auth_projects_match(STAGING,STAGING,"public"))
        self.assertFalse(business_auth_projects_match(STAGING,LIVE,"public"))
        self.assertFalse(business_auth_projects_match(LIVE,STAGING,"public"))
    def test_missing_key_config_or_unsafe_url_fails_closed(self):
        for value in ("","http://zbncuxizmjinexifcshe.supabase.co",
                      "https://evil.example.com","https://a.supabase.co/path",
                      "https://a.supabase.co:9999","https://user@a.supabase.co"):
            self.assertFalse(business_auth_projects_match(value,value,"public"))
        self.assertFalse(business_auth_projects_match(STAGING,STAGING,""))
        self.assertFalse(business_auth_projects_match(STAGING,None,"public"))

if __name__=="__main__": unittest.main()
