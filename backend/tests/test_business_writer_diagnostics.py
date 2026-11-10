"""Nonbillable HTTP/SQLite diagnostics; never real model-quality evidence."""
import json
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

import requests

from tests import test_business_creative_plans as creative_tests
from tests import test_business_growthrova_writer as writer_tests


class WriterDiagnosticTests(unittest.TestCase):
    setUp = writer_tests.GrowthrovaWriterTests.setUp
    create = writer_tests.GrowthrovaWriterTests.create
    write = writer_tests.GrowthrovaWriterTests.write
    plan = creative_tests.CreativePlanTests.plan

    def check_saved_failure(self, category):
        result = self.plan().json
        self.assertEqual(result['state'], 'uncertain', result)
        self.assertEqual(result['concepts'], [])
        diagnostic = result['providerDiagnostic']
        self.assertEqual(diagnostic['category'], category)
        self.assertEqual(diagnostic['reconciliation'], 'operator_required_no_resubmit')
        self.assertRegex(diagnostic['clientRequestId'], r'^gw_[a-f0-9]{32}$')
        # Lost acknowledgement/restart is inspection, never a second paid attempt.
        reopened = self.create().test_client()
        replay = reopened.post(self.url, headers=self.headers,
            json={**self.request, 'creativePlan': {'mode':'initial','parentOperationId':'','conceptId':''}})
        self.assertEqual(replay.json, result)
        self.assertEqual(reopened.get(self.url, headers=self.headers).json['conceptPlans'], [result])
        with closing(sqlite3.connect(self.path)) as con:
            rows = con.execute('SELECT reservation FROM growthrova_writing_requests').fetchall()
        self.assertEqual(rows, [(result['reservedMicrousd'],)])
        self.assertGreater(rows[0][0], 0)
        return result

    def test_timeout_has_durable_support_identity_without_exception_leak(self):
        self.provider.failure = requests.Timeout('PRIVATE PROMPT '+self.config.key)
        reserved = []
        def before_transport():
            with closing(sqlite3.connect(self.path)) as con:
                reserved.append(json.loads(con.execute(
                    'SELECT result_json FROM growthrova_writing_requests').fetchone()[0]))
        self.provider.on_call = before_transport
        result = self.check_saved_failure('transport_timeout')
        self.assertEqual(len(self.provider.calls), 1)
        sent = self.provider.calls[0][1]['headers']['X-Client-Request-Id']
        self.assertEqual(sent, result['providerDiagnostic']['clientRequestId'])
        self.assertEqual(reserved[0]['providerDiagnostic']['clientRequestId'], sent)
        self.assertEqual(reserved[0]['providerDiagnostic']['category'], 'dispatch_reserved')
        self.assertNotIn('PRIVATE PROMPT', json.dumps(result))
        self.assertNotIn(self.config.key, json.dumps(result))
        self.assertIn('timed out', ' '.join(result['issues']))

    def test_incomplete_limit_retains_allowlisted_response_identity_and_reason(self):
        self.provider.sample = {'id':'resp_synthetic123', 'status':'incomplete',
            'incomplete_details':{'reason':'max_output_tokens'}, 'output':[],
            'error':None, 'privateDebug':'PRIVATE PROMPT'}
        result = self.check_saved_failure('provider_incomplete')
        self.assertEqual(result['providerDiagnostic']['responseId'], 'resp_synthetic123')
        self.assertEqual(result['providerDiagnostic']['incompleteReason'], 'max_output_tokens')
        self.assertNotIn('PRIVATE PROMPT', json.dumps(result))

    def test_stream_timeout_keeps_request_id_but_not_provider_body(self):
        response = writer_tests.ProviderResponse(None)
        response.headers = {'x-request-id':'req_synthetic123', 'Set-Cookie':'PRIVATE PROMPT'}
        def chunks(_):
            yield b'{"private":"PRIVATE PROMPT"'
            raise requests.Timeout('secret stream error')
        response.iter_content = chunks
        with patch.object(self.provider, 'post', return_value=response) as post:
            result = self.check_saved_failure('transport_timeout')
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['providerDiagnostic']['requestId'], 'req_synthetic123')
        self.assertNotIn('PRIVATE PROMPT', json.dumps(result))

    def test_http_failure_never_retains_body_or_untrusted_header(self):
        response = writer_tests.ProviderResponse(None)
        response.status_code = 429
        response.headers = {'x-request-id':self.config.key}
        with patch.object(self.provider, 'post', return_value=response):
            result = self.check_saved_failure('http_error')
        self.assertEqual(result['providerDiagnostic']['httpStatus'], 429)
        self.assertNotIn('requestId', result['providerDiagnostic'])
        self.assertNotIn(self.config.key, json.dumps(result))

    def test_malformed_envelope_is_distinct_from_timeout(self):
        self.provider.sample = {'output':[], 'status':'completed', 'id':'resp_synthetic123'}
        self.check_saved_failure('invalid_response')

    def test_validated_six_concepts_have_identity_and_do_not_change_owner_document(self):
        self.provider.sample = {'id':'resp_synthetic123', 'status':'completed', 'output':[
            {'type':'message', 'content':[{'type':'output_text','text':json.dumps(creative_tests.concepts())}]}]}
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        result = self.plan().json
        self.assertEqual(result['state'], 'proposed', result)
        self.assertEqual(len(result['concepts']), 6)
        self.assertEqual(result['providerDiagnostic']['category'], 'validated')
        self.assertEqual(result['providerDiagnostic']['responseId'], 'resp_synthetic123')
        self.assertEqual(result['providerDiagnostic']['reconciliation'], 'completed_review_required')
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)
