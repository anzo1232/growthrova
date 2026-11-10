"""Cost checks use real auth/store validation, never a provider or reservation."""
from contextlib import closing
import json
import sqlite3
import unittest
from tests import test_business_growthrova_images as image_fixtures
from tests.test_business_growthrova_preview import ORG, OTHER


class ImageEstimateTests(unittest.TestCase):
    def setUp(self):
        self.f = image_fixtures.GrowthrovaImageTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def estimate(self, **changes):
        f = self.f
        return f.client.post(f.url+'/estimate', headers=f.headers, json={**f.data, **changes})

    def ledger(self):
        with closing(sqlite3.connect(self.f.path)) as con:
            return con.execute('SELECT * FROM growthrova_image_requests').fetchall()

    def test_alternative_estimate_matches_reservation_without_mutating_any_work(self):
        f = self.f
        f.configured()
        parent = f.generate().json
        before = self.ledger()
        document = f.client.get(f.root+'/'+f.ident, headers=f.headers).json
        data = dict(operationId='4'*32, parentOperationId=parent['operationId'],
                    visualBrief='Illustrative wheel detail on a warm background with more space on the left.')
        estimate = self.estimate(**data)
        self.assertEqual(estimate.status_code, 200, estimate.json)
        self.assertEqual(estimate.json['state'], 'available')
        self.assertEqual(estimate.json['model'], f.config.model)
        self.assertEqual(estimate.json['proposedImageCredits'], 1)
        self.assertEqual(estimate.json['customerCreditsCharged'], 0)
        self.assertEqual(self.ledger(), before)
        self.assertEqual(len(f.provider.calls), 1)
        self.assertEqual(f.client.get(f.root+'/'+f.ident, headers=f.headers).json, document)
        child = f.generate(**data).json
        self.assertEqual(child['reservedMicrousd'], estimate.json['reservationMicrousd'])
        self.assertEqual(len(f.provider.calls), 2)

    def test_missing_funding_and_exhausted_cash_are_truthful_nonbillable_states(self):
        f = self.f
        result = self.estimate()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'unavailable')
        self.assertIsNone(result.json['reservationMicrousd'])
        f.configured()
        with closing(sqlite3.connect(f.path)) as con:
            con.execute('INSERT INTO growthrova_image_requests VALUES(?,?,?,?,?,NULL)',
                        (f.ident, '9'*32, '9'*64, f.config.budget_microusd, json.dumps({'state':'uncertain'})))
            con.commit()
        before = self.ledger()
        result = self.estimate()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['state'], 'budget_held')
        self.assertGreater(result.json['reservationMicrousd'], 0)
        self.assertNotIn('used', result.json, 'Do not expose other organisations ledger usage')
        self.assertEqual(self.ledger(), before)
        self.assertEqual(f.provider.calls, [])

    def test_foreign_scope_stale_revision_and_invalid_parent_are_denied_before_cost_check(self):
        f = self.f
        f.configured()
        foreign = f.client.post(f.url.replace('/'+ORG+'/', '/'+OTHER+'/')+'/estimate',
                                headers=f.headers, json=f.data)
        self.assertEqual(foreign.status_code, 403)
        self.assertEqual(self.estimate(expectedRevision=0).status_code, 409)
        self.assertEqual(self.estimate(parentOperationId='f'*32).status_code, 409)
        self.assertEqual(f.provider.calls, [])
        self.assertEqual(self.ledger(), [])

    def test_original_source_route_cannot_offer_generation_cost(self):
        f = self.f
        f.configured()
        result = f.client.put(f.url+'/source-choice', headers=f.headers,
                              json=dict(route='upload',expectedRevision=1,expectedSourceVersion=0))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.estimate().status_code, 409)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(f.provider.calls, [])
