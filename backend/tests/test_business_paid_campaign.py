"""Paid preparation through authenticated real document routes; no live provider."""
import copy
import unittest
from tests import test_business_growthrova_images as images
from tests.test_business_growthrova_preview import OTHER

class PaidCampaignTests(unittest.TestCase):
    def setUp(self):
        self.flow = images.GrowthrovaImageTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.flow.configured()
        image = self.flow.generate().json
        self.plan = dict(objective='leads', audience='Local bicycle owners',
            primaryText='Ask our workshop about a service.', headline='Plan your visit',
            callToAction='Contact us', destinationUrl='https://example.org/contact',
            currency='GBP', dailyBudget='12.50', durationDays=7,
            asset=dict(operationId=image['operationId'], sha256=image['sha256']))
        self.payload = dict(id=self.flow.ident, expectedRevision=1, mutationId='7'*32,
            document={**copy.deepcopy(self.flow.doc), 'paidCampaign':self.plan})

    def save(self, payload=None):
        return self.flow.client.post(self.flow.root, headers=self.flow.headers, json=payload or self.payload)

    def test_roundtrip_restart_replay_and_conflict_preserve_exact_plan(self):
        saved = self.save()
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json['document']['paidCampaign'], self.plan)
        self.assertTrue(self.save().json['replayed'])
        client = self.flow.create().test_client()
        reopened = client.get(self.flow.root+'/'+self.flow.ident, headers=self.flow.headers)
        self.assertEqual(reopened.json['document']['paidCampaign'], self.plan)
        self.assertFalse(reopened.json['document']['canSpend'])
        stale = copy.deepcopy(self.payload); stale['mutationId']='8'*32
        stale['document']['paidCampaign']['dailyBudget']='20'
        self.assertEqual(self.save(stale).status_code,409)
        self.assertEqual(len(self.flow.provider.calls),1)

    def test_invalid_budget_url_and_asset_cannot_replace_saved_work(self):
        self.assertEqual(self.save().status_code,200)
        for field, value in [('dailyBudget','-1'),('dailyBudget','1e3'),('dailyBudget','NaN'),
                             ('durationDays',True),('destinationUrl','javascript:alert(1)'),
                             ('asset',dict(operationId='f'*32,sha256='f'*64)),
                             ('asset',dict(operationId=self.plan['asset']['operationId'],sha256='f'*64))]:
            payload=copy.deepcopy(self.payload); payload.update(expectedRevision=2,mutationId='8'*32)
            payload['document']['paidCampaign'][field]=value
            response=self.save(payload)
            self.assertIn(response.status_code,(400,409),response.json)
        restored=self.flow.client.get(self.flow.root+'/'+self.flow.ident,headers=self.flow.headers)
        self.assertEqual(restored.json['document']['paidCampaign'],self.plan)

    def test_incomplete_preparation_saves_without_claimed_readiness(self):
        self.payload['document']['paidCampaign'].update(asset=None,destinationUrl='',dailyBudget='')
        result=self.save()
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['document']['paidCampaign']['dailyBudget'],'')
        self.flow.auth.owner=OTHER
        self.assertEqual(self.save().status_code,403)
