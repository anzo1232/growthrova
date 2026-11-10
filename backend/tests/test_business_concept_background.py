"""Normal concept controls reuse durable background writing; no paid calls."""
import json
import sqlite3
import unittest
from unittest.mock import patch
from contextlib import closing
from pathlib import Path

import requests

from tests import test_business_growthrova_writer as writer
from tests import test_business_creative_plans as plans
from tests.test_business_ad_agent import BackgroundProvider


class ConceptBackgroundTests(unittest.TestCase):
    setUp = writer.GrowthrovaWriterTests.setUp
    create = writer.GrowthrovaWriterTests.create

    def start(self):
        return self.client.post(self.url+'/concept-plans', headers=self.headers, json={
            **self.request, 'creativePlan': {'mode':'initial', 'conceptCount':6,
                                           'parentOperationId':'', 'conceptId':''}})

    def prepare(self):
        self.provider = BackgroundProvider()
        self.provider.sample = plans.concepts()
        self.client = self.create().test_client()

    def test_slow_initial_plan_reopens_checks_same_response_and_preserves_campaign(self):
        self.prepare()
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        started = self.start()
        self.assertEqual(started.status_code, 200, started.json)
        self.assertEqual(started.json['state'], 'pending')
        self.assertTrue(self.provider.calls[0][1]['json']['background'])
        self.assertEqual(self.start().json, started.json)
        self.client = self.create().test_client()
        self.assertEqual(self.client.get(self.url, headers=self.headers).json['conceptPlans'], [started.json])
        refresh = self.url+'/'+self.request['operationId']+'/refresh'
        completed = self.client.post(refresh, headers=self.headers, json={})
        self.assertEqual(completed.status_code, 200, completed.json)
        self.assertEqual(completed.json['state'], 'proposed', completed.json)
        self.assertEqual(len(completed.json['concepts']), 6)
        self.assertEqual(completed.json['providerDiagnostic']['category'], 'validated')
        self.assertEqual(completed.json['providerDiagnostic']['providerStatus'], 'completed')
        self.assertEqual(completed.json['providerDiagnostic']['reconciliation'], 'completed_review_required')
        self.assertEqual(self.client.post(refresh, headers=self.headers, json={}).json, completed.json)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_writing_requests').fetchone()[0], 1)

    def test_poll_failure_is_recoverable_without_submission_or_new_reservation(self):
        self.prepare()
        self.assertEqual(self.start().status_code, 200)
        original = self.provider.get
        def fail(*args, **kwargs):
            raise requests.Timeout('private transport details')
        self.provider.get = fail
        refresh = self.url+'/'+self.request['operationId']+'/refresh'
        pending = self.client.post(refresh, headers=self.headers, json={})
        self.assertEqual(pending.json['state'], 'pending')
        self.assertNotIn('private transport details', json.dumps(pending.json))
        self.provider.get = original
        self.assertEqual(self.client.post(refresh, headers=self.headers, json={}).json['state'], 'proposed')
        self.assertEqual(len(self.provider.calls), 1)

    def test_slow_submission_stops_consuming_and_keeps_one_uncertain_reservation(self):
        self.check_slow_response(submitting=True)

    def test_slow_status_check_keeps_response_and_recovers_without_resubmission(self):
        self.check_slow_response(submitting=False)

    def check_slow_response(self, *, submitting):
        self.prepare()
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        refresh = self.url+'/'+self.request['operationId']+'/refresh'
        if not submitting:
            started = self.start().json
        elapsed = [0]
        consumed = []
        original = self.provider.post if submitting else self.provider.get

        def slow(*args, **kwargs):
            response = original(*args, **kwargs)
            complete = b''.join(response.iter_content(8192))

            def chunks(_):
                # Each read arrives within the existing 25s inactivity timeout,
                # but the complete response takes over 40s. No sleep/network.
                for part in (b' ', b' ', b' ', complete):
                    elapsed[0] += 10
                    consumed.append(part)
                    yield part
            response.iter_content = chunks
            return response

        if submitting:
            self.provider.post = slow
        else:
            self.provider.get = slow
        with patch('time.monotonic', side_effect=lambda: elapsed[0]):
            result = (self.start() if submitting else self.client.post(
                refresh, headers=self.headers, json={})).json
        diagnostic = result['providerDiagnostic' if submitting else 'providerCheckDiagnostic']
        self.assertEqual(diagnostic['category'], 'transport_timeout', result)
        self.assertEqual(len(consumed), 3, 'Stop reading once the elapsed response budget is exhausted')
        self.assertEqual(result['state'], 'uncertain' if submitting else 'pending')
        self.assertIn('timed out', ' '.join(result['issues']))
        self.assertEqual(self.start().json, result)
        self.assertEqual(self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans'], [result])
        if not submitting:
            self.assertEqual(result['providerResponseId'], started['providerResponseId'])
            self.provider.get = original
            completed = self.client.post(refresh, headers=self.headers, json={}).json
            self.assertEqual(completed['state'], 'proposed', completed)
            self.assertEqual(len(completed['concepts']), 6)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT reservation FROM growthrova_writing_requests').fetchall(),
                             [(result['reservedMicrousd'],)])

    def test_more_ideas_recovers_same_response_and_holds_repeated_history(self):
        self.check_more_ideas(repeated=True)

    def test_distinct_more_ideas_reopens_as_six_proposals_preserving_original(self):
        self.check_more_ideas(repeated=False)

    def check_more_ideas(self, *, repeated):
        self.prepare()
        initial = self.start().json
        self.client.post(self.url+'/'+initial['operationId']+'/refresh', headers=self.headers, json={})
        initial = self.client.get(self.url, headers=self.headers).json['conceptPlans'][0]
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        data = {**self.request, 'operationId': 'b'*32, 'creativePlan': {
            'mode': 'more_ideas', 'conceptCount': 6, 'parentOperationId': initial['operationId'],
            'conceptId': '', 'instruction': 'Explore other supported customer needs and compositions.'}}
        started = self.client.post(self.url+'/concept-plans', headers=self.headers, json=data)
        self.assertEqual(started.status_code, 200, started.json)
        self.assertEqual(started.json['state'], 'pending')
        self.assertTrue(self.provider.calls[-1][1]['json']['background'])
        self.assertEqual(started.json['comparisonConcepts'], initial['concepts'])
        self.assertEqual(self.client.post(self.url+'/concept-plans', headers=self.headers, json=data).json, started.json)
        self.client = self.create().test_client()
        if not repeated:
            self.provider.sample = json.loads((Path(__file__).parent/
                'fixtures/growthrova-concept-recovery-synthetic.json').read_text())
        refresh = self.url+'/'+data['operationId']+'/refresh'
        completed = self.client.post(refresh, headers=self.headers, json={}).json
        self.assertEqual(completed['state'], 'held' if repeated else 'proposed', completed)
        self.assertEqual(len(completed['concepts']), 6)
        self.assertEqual(any('repeats saved concepts' in issue for issue in completed['issues']), repeated)
        self.assertEqual(completed['diversityReview']['comparedOperationIds'], [initial['operationId']])
        self.assertEqual(self.client.post(refresh, headers=self.headers, json={}).json, completed)
        reopened = self.client.get(self.url, headers=self.headers).json['conceptPlans']
        self.assertIn(initial, reopened)
        self.assertIn(completed, reopened)
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)
        self.assertEqual(len(self.provider.calls), 2)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT reservation FROM growthrova_writing_requests ORDER BY rowid').fetchall(),
                             [(initial['reservedMicrousd'],), (started.json['reservedMicrousd'],)])

    def test_poll_http_failure_keeps_identity_and_recovers_same_response(self):
        self.check_poll_diagnostics('http', 'http_error', 'HTTP error')

    def test_poll_timeout_keeps_submission_identity(self):
        self.check_poll_diagnostics('timeout', 'transport_timeout', 'timed out')

    def test_poll_invalid_json_preserves_campaign_and_reservation(self):
        self.check_poll_diagnostics('invalid_json', 'invalid_response', 'could not be validated')

    def test_poll_discards_unsafe_request_header(self):
        self.check_poll_diagnostics('unsafe_header', 'http_error', 'HTTP error')

    def check_poll_diagnostics(self, failure, category, phrase):
        self.prepare()
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        started = self.start().json
        original_get = self.provider.get
        response = writer.ProviderResponse(None)
        response.status_code = 429 if failure in ('http', 'unsafe_header') else 200
        response.headers = {'x-request-id': self.config.key if failure == 'unsafe_header' else 'req_saved_check',
                            'Set-Cookie': 'PRIVATE POLL BODY'}
        def chunks(_):
            yield b'{"private":"PRIVATE POLL BODY"'
            if failure == 'timeout':
                raise requests.Timeout('PRIVATE POLL BODY '+self.config.key)
        response.iter_content = chunks
        self.provider.get = lambda *a, **kw: response
        refresh = self.url+'/'+self.request['operationId']+'/refresh'
        result = self.client.post(refresh, headers=self.headers, json={}).json
        self.assertIn(phrase, ' '.join(result['issues']))
        diagnostic = result['providerCheckDiagnostic']
        self.assertEqual(diagnostic['category'], category)
        self.assertEqual(diagnostic['httpStatus'], response.status_code)
        if failure == 'unsafe_header':
            self.assertNotIn('requestId', diagnostic)
        else:
            self.assertEqual(diagnostic['requestId'], 'req_saved_check')
        self.assertEqual(result['state'], 'pending')
        self.assertEqual(result['providerDiagnostic'], started['providerDiagnostic'])
        self.assertEqual(result['providerResponseId'], started['providerResponseId'])
        self.assertEqual(result['reservedMicrousd'], started['reservedMicrousd'])
        self.assertNotIn('PRIVATE POLL BODY', json.dumps(result))
        self.assertNotIn(self.config.key, json.dumps(result))
        self.assertEqual(self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans'], [result])
        self.assertEqual(self.start().json, result)
        self.provider.get = original_get
        completed = self.client.post(refresh, headers=self.headers, json={}).json
        self.assertEqual(completed['state'], 'proposed', completed)
        self.assertEqual(len(completed['concepts']), 6)
        self.assertEqual(completed['providerCheckDiagnostic']['category'], 'response_received')
        self.assertNotIn('requestId', completed['providerCheckDiagnostic'])
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT reservation FROM growthrova_writing_requests').fetchall(),
                             [(started['reservedMicrousd'],)])

    def test_completed_submission_keeps_six_concepts_without_another_provider_read(self):
        self.check_terminal_submission('completed', 'proposed', 'validated')

    def test_incomplete_submission_is_held_immediately_without_discarding_its_reason(self):
        self.check_terminal_submission('incomplete', 'held', 'provider_incomplete')

    def test_invalid_completed_submission_is_held_without_presenting_usable_concepts(self):
        self.check_terminal_submission('invalid_output', 'held', 'invalid_response')

    def check_terminal_submission(self, status, state, category):
        self.prepare()
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        original = self.provider.post
        def terminal_post(*args, **kwargs):
            original(*args, **kwargs)
            envelope = {'id': 'resp_syntheticagent123456', 'status': status, 'output': []}
            if status == 'completed':
                envelope['output'] = [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': json.dumps(self.provider.sample)}]}]
            elif status == 'incomplete':
                envelope['incomplete_details'] = {'reason': 'max_output_tokens'}
            else:
                envelope['status'] = 'completed'
            return writer.ProviderResponse(envelope)
        self.provider.post = terminal_post
        self.provider.get = lambda *a, **kw: self.fail('Terminal output must not require another provider read')
        result = self.start().json
        self.assertEqual(result['state'], state, result)
        self.assertEqual(result['providerDiagnostic']['category'], category)
        self.assertEqual(result['providerDiagnostic']['responseId'], 'resp_syntheticagent123456')
        self.assertEqual(len(result['concepts']), 6 if state == 'proposed' else 0)
        if status == 'incomplete':
            self.assertEqual(result['providerDiagnostic']['incompleteReason'], 'max_output_tokens')
        self.assertEqual(self.start().json, result)
        self.assertEqual(self.client.post(self.url+'/'+self.request['operationId']+'/refresh',
                                         headers=self.headers, json={}).json, result)
        self.assertEqual(self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans'], [result])
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)
        self.assertEqual(len(self.provider.calls), 1)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT reservation FROM growthrova_writing_requests').fetchall(),
                             [(result['reservedMicrousd'],)])

    def test_incomplete_response_retains_reason_without_claiming_completion(self):
        self.check_terminal_failure('incomplete', 'provider_incomplete', 'incomplete output')

    def test_failed_response_is_distinct_from_invalid_output(self):
        self.check_terminal_failure('failed', 'provider_failed', 'failed response')

    def test_cancelled_response_is_distinct_from_invalid_output(self):
        self.check_terminal_failure('cancelled', 'provider_cancelled', 'cancelled response')

    def test_malformed_completed_response_requires_reconciliation(self):
        self.check_terminal_failure('completed', 'invalid_response', 'could not be validated')

    def check_terminal_failure(self, status, category, phrase):
        self.prepare()
        self.request['operationId'] = 'a'*32
        started = self.start().json
        envelope = {'id': started['providerResponseId'], 'status': status, 'output': [],
                    'error': {'message': 'PRIVATE BODY '+self.config.key}}
        if status == 'incomplete':
            envelope['incomplete_details'] = {'reason': 'max_output_tokens'}
        self.provider.get = lambda *a, **kw: writer.ProviderResponse(envelope)
        refresh = self.url+'/'+started['operationId']+'/refresh'
        result = self.client.post(refresh, headers=self.headers, json={}).json
        self.assertEqual(result['state'], 'held', result)
        diagnostic = result['providerDiagnostic']
        self.assertEqual(diagnostic['category'], category)
        self.assertEqual(diagnostic['providerStatus'], status)
        self.assertEqual(diagnostic['responseId'], started['providerResponseId'])
        self.assertEqual(diagnostic['reconciliation'], 'operator_required_no_resubmit')
        if status == 'incomplete':
            self.assertEqual(diagnostic['incompleteReason'], 'max_output_tokens')
        self.assertIn(phrase, ' '.join(result['issues']))
        self.assertNotIn('PRIVATE BODY', json.dumps(result))
        self.assertNotIn(self.config.key, json.dumps(result))
        self.assertEqual(result['reservedMicrousd'], started['reservedMicrousd'])
        self.assertEqual(result['concepts'], [])
        self.assertEqual(self.client.post(refresh, headers=self.headers, json={}).json, result)
        self.assertEqual(self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans'], [result])
        self.assertEqual(len(self.provider.calls), 1)

    def test_late_poll_failure_cannot_erase_concepts_completed_by_another_check(self):
        self.check_overlapping_refresh(failure=True)

    def test_late_queued_response_returns_newer_completed_plan(self):
        self.check_overlapping_refresh(failure=False)

    def check_overlapping_refresh(self, *, failure):
        self.prepare()
        started = self.start().json
        refresh = self.url+'/'+self.request['operationId']+'/refresh'
        original = self.provider.get
        completed = []

        def overlapping_check(*args, **kwargs):
            # A second tab finishes while this earlier status request is in flight.
            self.provider.get = original
            with self.create().test_client() as other_tab:
                completed.append(other_tab.post(refresh, headers=self.headers, json={}).json)
            if failure:
                raise requests.Timeout('late status timeout')
            return writer.ProviderResponse({'id': started['providerResponseId'],
                                            'status': 'queued', 'output': []})

        self.provider.get = overlapping_check
        late = self.client.post(refresh, headers=self.headers, json={})
        self.assertEqual(completed[0]['state'], 'proposed', completed[0])
        self.assertEqual(late.json, completed[0])
        reopened = self.create().test_client().get(self.url, headers=self.headers).json
        self.assertEqual(reopened['conceptPlans'], completed)
        self.assertEqual(len(completed[0]['concepts']), 6)
        self.assertEqual(completed[0]['reservedMicrousd'], started['reservedMicrousd'])
        self.assertEqual(len(self.provider.calls), 1)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM growthrova_writing_requests').fetchone()[0], 1)

    def test_legacy_uncertain_operation_is_returned_without_resubmission(self):
        self.provider.failure = requests.Timeout()
        request = {**self.request, 'creativePlan': {'mode':'initial','conceptCount':6,'parentOperationId':'','conceptId':''}}
        uncertain = self.client.post(self.url, headers=self.headers, json=request).json
        response = self.start()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, uncertain)
        self.assertEqual(len(self.provider.calls), 1)

    def test_changed_favourites_cannot_duplicate_a_pending_initial_plan(self):
        self.prepare()
        # A completed older plan stays editable while a new one is running.
        original = self.client.post(self.url, headers=self.headers, json={
            **self.request, 'creativePlan': {'mode': 'initial', 'conceptCount': 6,
                                           'parentOperationId': '', 'conceptId': ''}}).json
        self.assertEqual(original['state'], 'proposed', original)
        selection_url = self.url+'/'+original['operationId']+'/concept-selection'
        def favourite(index, revision):
            response = self.client.put(selection_url, headers=self.headers, json={
                'expectedRevision': 1, 'expectedSelectionRevision': revision,
                'selectedConceptIds': [original['concepts'][index]['id']]})
            self.assertEqual(response.status_code, 200, response.json)
        favourite(0, 0)
        self.request['operationId'] = 'a'*32
        pending = self.start().json
        self.assertEqual(pending['state'], 'pending', pending)
        favourite(1, 1)
        with closing(sqlite3.connect(self.path)) as con:
            reserved = con.execute('SELECT SUM(reservation) FROM growthrova_writing_requests').fetchone()[0]
        # Neither the background control nor the legacy route can create a
        # second submission by using changed feedback and a fresh operation ID.
        for route in (self.url+'/concept-plans', self.url):
            response = self.client.post(route, headers=self.headers, json={
                **self.request, 'operationId': 'b'*32,
                'creativePlan': {'mode': 'initial', 'conceptCount': 6,
                                 'parentOperationId': '', 'conceptId': ''}})
            self.assertEqual(response.status_code, 409, response.json)
            self.assertEqual(response.json['code'], 'operation_conflict')
        self.assertEqual(len(self.provider.calls), 2)
        reopened = self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans']
        self.assertIn(pending, reopened)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*), SUM(reservation) FROM growthrova_writing_requests').fetchone(), (2, reserved))
        # Recover the existing request after the conflict, without another POST.
        completed = self.client.post(self.url+'/'+pending['operationId']+'/refresh',
                                     headers=self.headers, json={})
        self.assertEqual(completed.json['state'], 'proposed', completed.json)
        self.assertEqual(len(completed.json['concepts']), 6)
        self.assertEqual(len(self.provider.calls), 2)

    def test_lost_background_ack_retains_pre_dispatch_support_identity(self):
        self.prepare()
        reserved = []
        def capture():
            with closing(sqlite3.connect(self.path)) as con:
                reserved.append(json.loads(con.execute('SELECT result_json FROM growthrova_writing_requests').fetchone()[0]))
        self.provider.on_call = capture
        self.provider.failure = requests.Timeout('private body '+self.config.key)
        result = self.start().json
        self.assertEqual(result['state'], 'uncertain')
        diagnostic = result['providerDiagnostic']
        self.assertEqual(diagnostic['category'], 'transport_timeout')
        self.assertEqual(diagnostic['clientRequestId'], reserved[0]['providerDiagnostic']['clientRequestId'])
        self.assertEqual(self.provider.calls[0][1]['headers']['X-Client-Request-Id'], diagnostic['clientRequestId'])
        self.assertNotIn('private body', json.dumps(result))
        self.assertNotIn(self.config.key, json.dumps(result))
        self.assertEqual(self.start().json, result)
        self.assertEqual(len(self.provider.calls), 1)

    def test_background_http_failure_retains_safe_provider_identity(self):
        self.check_submission_failure('http', 'http_error')

    def test_background_invalid_json_is_distinct_from_connection_failure(self):
        self.check_submission_failure('invalid_json', 'invalid_response')

    def test_background_stream_timeout_retains_received_request_identity(self):
        self.check_submission_failure('timeout', 'transport_timeout')

    def test_background_http_failure_discards_credential_in_request_header(self):
        self.check_submission_failure('unsafe_header', 'http_error')

    def check_submission_failure(self, failure, category):
        self.prepare()
        before = self.client.get(self.root+'/'+self.ident, headers=self.headers).json
        response = writer.ProviderResponse(None)
        response.status_code = 429 if failure in ('http', 'unsafe_header') else 200
        response.headers = {'x-request-id': self.config.key if failure == 'unsafe_header' else 'req_synthetic_background',
                            'Set-Cookie': 'PRIVATE BODY'}
        def chunks(_):
            yield b'{"private":"PRIVATE BODY"'
            if failure == 'timeout':
                raise requests.Timeout('PRIVATE BODY '+self.config.key)
        response.iter_content = chunks
        original = self.provider.post
        def failed_post(*args, **kwargs):
            original(*args, **kwargs)
            return response
        self.provider.post = failed_post
        result = self.start().json
        self.assertEqual(result['state'], 'uncertain', result)
        diagnostic = result['providerDiagnostic']
        self.assertEqual(diagnostic['category'], category)
        self.assertEqual(diagnostic['httpStatus'], response.status_code)
        if failure == 'unsafe_header':
            self.assertNotIn('requestId', diagnostic)
        else:
            self.assertEqual(diagnostic['requestId'], 'req_synthetic_background')
        self.assertEqual(diagnostic['reconciliation'], 'operator_required_no_resubmit')
        self.assertNotIn('PRIVATE BODY', json.dumps(result))
        self.assertNotIn(self.config.key, json.dumps(result))
        self.assertEqual(self.start().json, result)
        self.assertEqual(self.create().test_client().get(self.url, headers=self.headers).json['conceptPlans'], [result])
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.client.get(self.root+'/'+self.ident, headers=self.headers).json, before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT reservation FROM growthrova_writing_requests').fetchall(),
                             [(result['reservedMicrousd'],)])

    def test_foreign_owner_cannot_start_or_poll_and_invalid_scope_never_spends(self):
        self.prepare()
        self.auth.owner = writer.OTHER
        self.assertEqual(self.start().status_code, 403)
        self.assertEqual(self.client.post(self.url+'/'+self.request['operationId']+'/refresh', headers=self.headers, json={}).status_code, 403)
        self.assertEqual(self.provider.calls, [])
        self.auth.owner = writer.USER
        bad = self.client.post(self.url+'/concept-plans', headers=self.headers, json={**self.request,
            'creativePlan': {'mode':'more_ideas','parentOperationId':'a'*32,'conceptId':''}})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.provider.calls, [])
