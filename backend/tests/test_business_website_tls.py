"""TLS trust-store regressions. No network and no certificate bypass."""
import os
import ssl
import unittest
from unittest.mock import patch
import certifi
import business_website_analysis as website

def build_context():
    # Before the fix the fetcher directly used ssl.create_default_context.
    # Exercise that exact behavior until the dedicated trust helper exists.
    return getattr(website, "website_tls_context", website.ssl.create_default_context)()

class WebsiteTLSRegressionTests(unittest.TestCase):
    def test_missing_platform_roots_loads_verified_bundle(self):
        empty = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(empty.cert_store_stats()["x509_ca"], 0)
        with patch.dict(os.environ, {}, clear=True), patch.object(website.ssl, "create_default_context", return_value=empty):
            context = build_context()
        self.assertGreater(context.cert_store_stats()["x509_ca"], 0)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_platform_trust_is_preserved_when_available(self):
        trusted = ssl.create_default_context(cafile=certifi.where())
        with patch.object(website.ssl, "create_default_context", return_value=trusted), patch.object(certifi, "where", side_effect=AssertionError("Must preserve platform trust")):
            self.assertIs(build_context(), trusted)

    def test_bad_explicit_trust_configuration_fails_closed(self):
        empty = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with patch.dict(os.environ, {"SSL_CERT_FILE":"/nonexistent/explicit-ca.pem"}, clear=True), patch.object(website.ssl, "create_default_context", return_value=empty):
            with self.assertRaises(website.WebsiteSafetyError):
                build_context()

    def test_missing_fallback_bundle_fails_closed(self):
        empty = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with patch.dict(os.environ, {}, clear=True), patch.object(website.ssl, "create_default_context", return_value=empty), patch.dict("sys.modules", {"certifi":None}):
            with self.assertRaises(website.WebsiteSafetyError):
                build_context()

if __name__ == "__main__": unittest.main()
