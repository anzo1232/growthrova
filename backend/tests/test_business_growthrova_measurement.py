"""Narrow offline private-route/SQLite check; no actual performance or provider."""
import copy
import unittest
from tests import test_business_growthrova_preview as fixture


class MeasurementTests(unittest.TestCase):
    def test_report_correction_recovery_overlap_and_private_scope(self):
        flow = fixture.GrowthrovaPreviewTests(); flow.setUp(); self.addCleanup(flow.doCleanups)
        self.assertEqual(flow.save().status_code, 200)
        url = flow.root + '/' + flow.payload['id'] + '/measurement'
        payload = dict(id='a'*32, mutationId='b'*32, expectedRevision=0, data=dict(
            platform='google', accountId='123-456-7890', campaignId='1234', currency='GBP',
            timezone='Europe/London', sourceReference='synthetic protocol fixture, not performance evidence',
            rows=[dict(date='2026-01-01', impressions=12, clicks=2, spend='0.100001')]))
        def save(value): return flow.client.post(url, json=value, headers=flow.headers)
        first = save(payload)
        self.assertEqual(first.status_code, 200, first.json)
        self.assertEqual(first.json['data']['accountId'], '1234567890')
        self.assertEqual(first.json['data']['rows'][0]['spend'], '0.100001')
        self.assertTrue(save(payload).json['replayed'])
        restarted = flow.create().test_client()
        read = restarted.get(url, headers=flow.headers)
        self.assertEqual(read.json['reports'][0]['data'], first.json['data'])
        self.assertFalse(read.json['connected'])
        overlap = copy.deepcopy(payload); overlap.update(id='c'*32, mutationId='d'*32)
        overlap['data'].update(accountId='1234567890', currency='USD', timezone='UTC')
        self.assertEqual(save(overlap).json['code'], 'overlapping_report')
        correction = copy.deepcopy(payload); correction.update(expectedRevision=1, mutationId='e'*32)
        correction['data']['rows'][0]['spend'] = '0.200002'
        self.assertEqual(save(correction).json['revision'], 2)
        self.assertEqual(save(payload).status_code, 409)
        self.assertTrue(save(correction).json['replayed'])
        invalid = copy.deepcopy(correction); invalid.update(expectedRevision=2, mutationId='f'*32)
        invalid['data']['rows'][0]['clicks'] = True
        self.assertEqual(save(invalid).status_code, 400)
        flow.transport.owner = fixture.OTHER
        self.assertEqual(flow.client.get(url, headers=flow.headers).status_code, 403)
        self.assertEqual(save(correction).status_code, 403)


class MeasurementRefreshTests(unittest.TestCase):
    """Controlled wire observations are fixtures, never performance evidence."""
    def setup_flow(self):
        from business_growthrova_measurement_refresh import MeasurementConfig
        from business_growthrova_measurement_adapters import GoogleReportingAdapter, ReportingBinding
        from dataclasses import replace
        flow = fixture.GrowthrovaPreviewTests(); flow.setUp(); self.addCleanup(flow.doCleanups)
        self.assertEqual(flow.save().status_code, 200)
        self.binding = ReportingBinding(fixture.USER, fixture.ORG, 'google', '1234567890',
            'Dedicated fixture account', 'v1', 'GBP', 'Europe/London', verified=True, enabled=True, access_token='fixture-only')
        self.calls = []
        outer = self
        class Wire:
            def post(self, url, **options):
                outer.calls.append(options)
                if 'FROM customer' in options['json']['query']:
                    return fixture.Response([dict(results=[dict(customer=dict(id='1234567890',currencyCode='GBP',timeZone='Europe/London'))])])
                return fixture.Response([dict(results=[dict(campaign=dict(id='1234'),segments=dict(date='2026-01-01'),
                    metrics=dict(impressions='12',clicks='2',costMicros='100001'))])])
        adapter = GoogleReportingAdapter(lambda *args:self.binding, http=Wire())
        self.clock = [1793836800.0]  # 2026-11-05 UTC; completed-date validation uses this clock.
        config = MeasurementConfig(adapters=dict(google=adapter), enabled=True,
            authorised=lambda owner,business,account:(owner,business)==(fixture.USER,fixture.ORG), clock=lambda:self.clock[0])
        flow.app = flow.create(measurement_config=config); flow.client = flow.app.test_client()
        self.url = flow.root+'/'+flow.payload['id']+'/measurement'
        self.payload = dict(id='a'*32,reportId='b'*32,expectedRevision=0,account=adapter.account(fixture.USER,fixture.ORG),
            campaignId='1234', **{'from':'2026-01-01','to':'2026-01-02'})
        self.flow,self.config,self.adapter = flow,config,adapter
        self.replace = replace
        return flow.app.extensions['growthrova_measurement_refresh']

    def post(self, payload):
        return self.flow.client.post(self.url+'/refresh',json=payload,headers=self.flow.headers)

    def test_durable_refresh_replay_correction_and_foreign_scope(self):
        service = self.setup_flow()
        queued = self.post(self.payload)
        self.assertEqual(queued.status_code,200,queued.json)
        self.assertEqual(queued.json['state'],'queued')
        self.assertTrue(self.post(self.payload).json['replayed'])
        app = self.flow.create(measurement_config=self.config)
        self.assertTrue(app.extensions['growthrova_measurement_refresh'].run_one())
        self.assertFalse(service.run_one())
        self.assertEqual(len(self.calls),2)
        report = app.test_client().get(self.url,headers=self.flow.headers).json['reports'][0]
        self.assertEqual(report['provenance'],'provider_read')
        self.assertEqual(report['observation']['returnedDates'],['2026-01-01'])
        self.assertEqual(report['observation']['requestedTo'],'2026-01-02')
        self.assertEqual(report['data']['rows'][0]['spend'],'0.100001')
        self.assertEqual(self.post(self.payload).json['state'],'completed')
        correction=dict(id=report['id'],mutationId='c'*32,expectedRevision=1,data=copy.deepcopy(report['data']))
        correction['data']['rows'][0]['clicks']=3
        saved=self.flow.client.post(self.url,json=correction,headers=self.flow.headers)
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(saved.json['provenance'],'owner_supplied_export')
        self.assertNotIn('observation',saved.json)
        self.flow.transport.owner=fixture.OTHER
        self.assertEqual(self.flow.client.get(self.url+'/refresh',headers=self.flow.headers).status_code,403)
        self.assertEqual(self.post(self.payload).status_code,403)

    def test_binding_drift_and_expired_claim_do_not_read_or_overwrite(self):
        service = self.setup_flow()
        self.assertEqual(self.post(self.payload).status_code,200)
        self.binding=self.replace(self.binding,version='v2')
        self.assertTrue(service.run_one()); self.assertEqual(self.calls,[])
        self.assertEqual(self.flow.client.get(self.url,headers=self.flow.headers).json['reports'],[])
        payload=copy.deepcopy(self.payload);payload['id']='c'*32;payload['account']=self.adapter.account(fixture.USER,fixture.ORG)
        self.assertEqual(self.post(payload).status_code,200)
        original=self.adapter.read
        def expired(snap):
            value=original(snap);self.clock[0]+=181;return value
        self.adapter.read=expired
        self.assertTrue(service.run_one())
        status=self.flow.client.get(self.url+'/refresh',headers=self.flow.headers).json
        self.assertTrue(all(j['state']=='failed' for j in status['jobs']))
        self.assertEqual(self.flow.client.get(self.url,headers=self.flow.headers).json['reports'],[])
        self.assertFalse(service.run_one());self.assertEqual(len(self.calls),2)

    def test_meta_read_identity_and_incomplete_page(self):
        from business_growthrova_measurement_adapters import MetaReportingAdapter, ReportingBinding
        binding=ReportingBinding(fixture.USER,fixture.ORG,'meta','1234','Dedicated Meta fixture','v1','GBP','Europe/London',
            verified=True,enabled=True,access_token='fixture-only')
        calls=[]
        class Wire:
            incomplete=False
            def get(self,url,**options):
                calls.append((url,options))
                if not url.endswith('/insights'):
                    return fixture.Response(dict(account_id='1234',currency='GBP',timezone_name='Europe/London'))
                return fixture.Response(dict(data=[dict(account_id='1234',campaign_id='5678',account_currency='GBP',
                    date_start='2026-01-01',date_stop='2026-01-01',impressions='12',clicks='2',spend='0.10')],
                    paging=dict(next='https://must-never-follow.example') if self.incomplete else {}))
        wire=Wire();adapter=MetaReportingAdapter(lambda *args:binding,http=wire)
        snap=dict(ownerId=fixture.USER,organisationId=fixture.ORG,account=adapter.account(fixture.USER,fixture.ORG),
            campaignId='5678',**{'from':'2026-01-01','to':'2026-01-02'})
        self.assertEqual(adapter.read(snap)['rows'][0]['spend'],'0.10')
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1][1]['params']['time_increment'],1)
        wire.incomplete=True
        with self.assertRaises(ValueError):adapter.read(snap)
        self.assertEqual(len(calls),4)
