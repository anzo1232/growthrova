"""Narrow synthetic route/SQLite/wire checks; no network or creative benchmark."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
import uuid

from business_growthrova_meta_ads import MetaAdsBinding, MetaTrafficPausedAdapter
from business_growthrova_paid_delivery import PaidDeliveryConfig
from business_social_delivery import _hash
from tests import test_business_paid_campaign as fixture
from tests.test_business_growthrova_preview import USER, ORG


class Response:
    status_code = 200
    def __init__(self, data): self.data = data
    def json(self): return deepcopy(self.data)


class MetaTransportTests(unittest.TestCase):
    def setUp(self):
        flow = fixture.PaidCampaignTests(); flow.setUp(); self.addCleanup(flow.doCleanups)
        self.flow = flow.flow
        flow.payload['document']['paidCampaign']['objective'] = 'traffic'
        self.assertEqual(flow.save().status_code, 200)
        self.plan = flow.payload['document']['paidCampaign']
        self.binding = MetaAdsBinding(USER, ORG, '1234', 'Dedicated account', '1', 'GBP',
            '5678', 'Workshop Page', _hash(self.plan), countries=('GB',), cta_text='Contact us',
            cta_type='CONTACT_US', beneficiary='Workshop', payor='Workshop',
            non_special_category_confirmed=True, verified=True, enabled=True, access_token='synthetic')
        self.calls, self.created = [], {}
        self.lost_edge, self.drift_edge = None, None
        self.adapter = MetaTrafficPausedAdapter(lambda *args: self.binding, lambda snap: True, http=self)
        self.clock = 1000
        self.config = PaidDeliveryConfig(adapters={'meta':self.adapter}, authorised=lambda *args:True,
                                         mode='live', clock=lambda:self.clock)
        self.app = self.flow.create(paid_delivery_config=self.config)
        self.client = self.app.test_client()
        self.delivery = self.app.extensions['growthrova_paid_delivery']
        self.url = self.flow.root+'/'+self.flow.ident+'/paid-provisioning/meta'
        review = self.get()['review']
        self.approval = dict(mutationId=uuid.uuid4().hex, expectedRevision=2, expectedMode='live',
                             expectedAccount=review['account'], expectedExecution=review['execution'])

    def get(self):
        response = self.client.get(self.url, headers=self.flow.headers)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def action(self, action):
        body = self.approval if action=='approve' else dict(mutationId=uuid.uuid4().hex,
                                                         jobIds=[j['jobId'] for j in self.get()['jobs']])
        return self.client.post(self.url+'/'+action, headers=self.flow.headers, json=body)

    def request(self, method, url, **options):
        self.assertFalse(options['allow_redirects'])
        path = url.removeprefix(self.adapter.API+'/')
        self.calls.append((method,path))
        if method == 'GET':
            if path=='act_1234':
                return Response(dict(account_id='1234',currency='GBP',account_status=1))
            if path=='5678': return Response(dict(id='5678',name='Workshop Page'))
            return Response(self.created[path])
        edge = path.split('/')[-1]
        step, ident = dict(campaigns=('campaignId','11'),adimages=('imageHash','a'*32),
            adcreatives=('creativeId','22'),adsets=('adSetId','33'),ads=('adId','44'))[edge]
        # Intent is committed and visible to a new connection before HTTP.
        job = self.get()['jobs'][0]
        self.assertEqual(job['receipt']['progress'], dict(step=step,state='intent'))
        data = options['data']
        if edge != 'adimages':
            data = {k:json.loads(v) if isinstance(v,str) and v[:1] in ('{','[') else v for k,v in data.items()}
            if edge in ('campaigns','adsets','ads'): self.assertEqual(data['status'],'PAUSED')
            self.created[ident] = dict(data,id=ident,account_id='1234')
            if edge=='ads':
                self.created[ident]['campaign_id']='11'
                self.created[ident]['creative']={'id':data['creative']['creative_id']}
        if self.drift_edge == edge:
            self.binding = replace(self.binding, version='2')
        if self.lost_edge == edge:
            raise TimeoutError('Lost response identity')
        return Response(dict(images={'original':dict(hash=ident)}) if edge=='adimages' else dict(id=ident))

    def test_exact_review_durable_steps_complete_and_terminal_replay(self):
        self.binding = replace(self.binding, countries=('FR',))
        self.assertEqual(self.action('approve').status_code,409)
        self.binding = replace(self.binding, countries=('GB',))
        self.assertEqual(self.action('approve').status_code,200)
        with self.app.test_request_context(headers=self.flow.headers):
            # Workers use the trusted repo callbacks installed by the preview factory.
            from flask import g
            g.growthrova_user={'id':USER}; g.growthrova_org={'id':ORG}
            self.assertTrue(self.delivery.run_one())
        job=self.get()['jobs'][0]
        self.assertEqual(job['state'],'created_paused',job)
        self.assertEqual(len(job['receipt']['resources']),5)
        self.action('approve')
        self.assertFalse(self.delivery.run_one())
        self.assertEqual(len([v for v in self.calls if v[0]=='POST']),5)

    def test_lost_image_response_survives_restart_lookup_without_resend(self):
        self.lost_edge='adimages'
        self.action('approve')
        with self.app.test_request_context(headers=self.flow.headers):
            from flask import g
            g.growthrova_user={'id':USER}; g.growthrova_org={'id':ORG}
            self.delivery.run_one()
        job=self.get()['jobs'][0]
        self.assertEqual(job['state'],'uncertain')
        self.assertEqual(job['receipt']['resources'],{'campaignId':'11'})
        self.assertEqual(job['receipt']['progress'],dict(step='imageHash',state='intent'))
        reopened=self.flow.create(paid_delivery_config=self.config)
        self.assertEqual(reopened.test_client().get(self.url,headers=self.flow.headers).json['jobs'][0]['receipt'],job['receipt'])
        self.action('reconcile')
        self.assertFalse(self.delivery.run_one())
        self.assertEqual(len([v for v in self.calls if v[0]=='POST']),2)
        self.approval['mutationId']=uuid.uuid4().hex
        self.assertEqual(self.action('approve').status_code,409)

    def test_binding_drift_after_ack_retains_identity_and_stops_next_write(self):
        self.drift_edge='campaigns'; self.action('approve')
        with self.app.test_request_context(headers=self.flow.headers):
            from flask import g
            g.growthrova_user={'id':USER}; g.growthrova_org={'id':ORG}
            self.delivery.run_one()
        job=self.get()['jobs'][0]
        self.assertEqual(job['state'],'uncertain')
        self.assertEqual(job['receipt']['resources'],{'campaignId':'11'})
        self.assertEqual(len([v for v in self.calls if v[0]=='POST']),1)
        self.binding=replace(self.binding,owner_id='other')
        self.assertIsNone(self.adapter.account(USER,ORG))


if __name__=='__main__': unittest.main()
