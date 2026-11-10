"""Offline reviewer handoff. Fixture observations are not actual creative proof."""
import copy,json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import business_scene_preparation as planner
import business_scene_contracts as contracts
import business_creative_learning as learning
import business_marketing_drafts as drafts
import tests.test_business_scene_preparation as fixtures
intent=fixtures.intent
DID=fixtures.DID

class ReviewedPreparationTests(unittest.TestCase):
    setUp=fixtures.PreparationTests.setUp
    save=fixtures.PreparationTests.save
    asset=fixtures.PreparationTests.asset
    def prep(self,s=None,pool=()):return planner.prepare(self.con,DID,1,s or intent(),reference_pool=pool)
    def proposal(self):
        a=self.asset();return a,self.prep(pool=[a])
    def assessment(self,p):
        self.assertIn('preproductionChecks',p)
        return {'reviewerReference':'offline-fixture-director-not-commercial-review',
            'checks':[{'id':c['id'],'verdict':'pass','evidence':'Fixture-only '+c['id']+' observation for the exact reference and intended action; not generated media approval.'} for c in p['preproductionChecks']]}
    def record(self,p,a,review=None,s=None):
        self.assertTrue(callable(getattr(planner,'record_reviewed',None)),'Reviewed handoff is not implemented')
        return planner.record_reviewed(self.con,DID,1,s or intent(),reference_pool=[a],expected_fingerprint=p['fingerprint'],assessment=review or self.assessment(p))
    def test_preproduction_does_not_pretend_final_export_review_is_done(self):
        _,p=self.proposal();self.assertIn('preproductionChecks',p)
        self.assertNotIn('finished_asset',{x['id'] for x in p['preproductionChecks']})
        self.assertIn('finished_asset',{x['id'] for x in p['reviewChecks']})
        self.assertFalse(p['visualQualityVerified'])
    def test_explicit_review_reaches_existing_contract_without_spend(self):
        a,p=self.proposal();contracts.open_envelope(self.con,DID,maximum_credits=100,approval_reference='offline-bounded-test-only')
        result=self.record(p,a)
        checked=contracts.check(self.con,DID,1,p['request'],25)
        self.assertEqual(result['id'],checked['id']);self.assertFalse(checked['visualQualityVerified'])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_scene_reservations').fetchone()[0],0)
    def test_generic_pass_without_per_check_evidence_is_rejected(self):
        a,p=self.proposal()
        with self.assertRaises(planner.PreparationError):self.record(p,a,{'reviewerReference':'test-reviewer','checks':[]})
    def test_uncertain_and_rejected_checks_never_record(self):
        a,p=self.proposal()
        for verdict in ('unknown','reject','not_applicable'):
            r=self.assessment(p);r['checks'][0]['verdict']=verdict
            with self.subTest(verdict=verdict):
                with self.assertRaises(planner.PreparationError):self.record(p,a,r)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_scene_contracts').fetchone()[0],0)
    def test_missing_duplicate_and_extra_check_fail(self):
        a,p=self.proposal()
        for kind in ('missing','duplicate','extra'):
            r=self.assessment(p)
            if kind=='missing':r['checks'].pop()
            elif kind=='duplicate':r['checks'][-1]=r['checks'][0]
            else:r['checks'].append({'id':'imaginary','verdict':'pass','evidence':'This is irrelevant invented reviewer evidence.'})
            with self.assertRaises(planner.PreparationError):self.record(p,a,r)
    def test_changed_intent_invalidates_review(self):
        a,p=self.proposal()
        with self.assertRaises(planner.PreparationError):self.record(p,a,s=intent(action='Small drops fall into a different bucket near the window.'))
    def test_changed_policy_invalidates_review(self):
        a,p=self.proposal();r=self.assessment(p)
        with tempfile.TemporaryDirectory() as folder:
            library=json.loads(learning.LIBRARY.read_text());library['policyVersion']='changed';library['lessons'][0]['check']+=' Additional source requirement.'
            path=Path(folder)/'lessons.json';path.write_text(json.dumps(library))
            with patch.object(learning,'LIBRARY',path):
                with self.assertRaises(planner.PreparationError):self.record(p,a,r)
    def test_missing_envelope_is_not_created_by_review(self):
        a,p=self.proposal()
        with self.assertRaises(planner.PreparationError):self.record(p,a)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_campaign_envelopes').fetchone()[0],0)
    def test_reuse_does_not_create_ai_contract(self):
        a=self.asset(origin='owner_asset');s=intent(format='image');p=self.prep(s,[a])
        with self.assertRaises(planner.PreparationError):self.record(p,a,s=s)
    def test_source_hash_change_blocks_same_revision_review(self):
        a,p=self.proposal();r=self.assessment(p)
        saved=drafts.read_draft(self.con,DID)['document'];saved['observedFacts'][0]+=' Changed description.'
        self.con.execute('UPDATE marketing_drafts SET document_json=? WHERE id=?',(json.dumps(saved),DID));self.con.commit()
        with self.assertRaises(planner.PreparationError):self.record(p,a,r)
    def test_zero_provider_calls_during_successful_handoff(self):
        a,p=self.proposal();contracts.open_envelope(self.con,DID,maximum_credits=100,approval_reference='offline-bounded-test-only')
        with patch('business_runway.RunwayClient',side_effect=AssertionError('No network or credential access')):
            self.record(p,a)
    def test_review_evidence_is_durably_bound_not_discarded(self):
        a,p=self.proposal();contracts.open_envelope(self.con,DID,maximum_credits=100,approval_reference='offline-bounded-test-only')
        self.record(p,a)
        self.assertTrue(callable(getattr(planner,'read_review',None)),'Review evidence persistence is missing')
        review=planner.read_review(self.con,DID,p['fingerprint'])
        self.assertEqual(review['proposalFingerprint'],p['fingerprint'])
        self.assertEqual(len(review['assessment']['checks']),len(p['preproductionChecks']))
        self.assertFalse(review['outputQualityApproved'])

class QuotePreparationTests(unittest.TestCase):
    def test_live_quote_exposes_preparation_without_recording_contract(self):
        from tests.test_business_reel_provider_bridge import BridgeTests
        import business_reel_provider_bridge as bridge
        BridgeTests.setUp(self)
        before=self.con.total_changes;q=bridge.quote(self.con,self.project,'hook')
        self.assertIn('scenePreparation',q)
        p=q['scenePreparation'];self.assertFalse(p['canSpend']);self.assertFalse(p['outputQualityApproved'])
        self.assertEqual(self.con.total_changes,before)
        self.assertIn('reference',json.dumps(p).lower())
        self.assertEqual(self.fake.calls,0)

class PreparedProductionTests(unittest.TestCase):
    setUp=fixtures.PreparationTests.setUp
    save=fixtures.PreparationTests.save
    asset=fixtures.PreparationTests.asset
    assessment=ReviewedPreparationTests.assessment
    def prepared(self,folder):
        from PIL import Image
        import business_runway_video as video
        path=Path(folder)/'source.png';Image.new('RGB',(720,1280),(112,116,120)).save(path)
        _,baseline=video.prepare_request(path)
        uri=baseline['promptImage']
        contracts.register_reference(self.con,DID,'provider-ready',uri,origin='illustrative_ai',
            rights_reference='offline-synthetic-test-only',reviewer_reference='offline-pixel-review-only')
        pool=[{'id':'provider-ready','sourceFactIndices':[0],'providerImage':uri}]
        p=planner.prepare(self.con,DID,1,intent(),reference_pool=pool)
        contracts.open_envelope(self.con,DID,maximum_credits=100,approval_reference='offline-explicit-test-no-live-model')
        planner.record_reviewed(self.con,DID,1,intent(),reference_pool=pool,expected_fingerprint=p['fingerprint'],assessment=self.assessment(p))
        return path,p,pool
    def test_real_adapter_receives_reviewed_scene_not_old_generic_luxury_prompt(self):
        import business_runway_video as video
        import inspect
        self.assertIn('scene_request',inspect.signature(video.start_job).parameters)
        with tempfile.TemporaryDirectory() as folder:
            video.initialise(self.con);path,p,_=self.prepared(folder)
            class Fake:
                calls=0
                def balance(self):return 100
                def submit_video(inner,request):
                    inner.calls+=1
                    self.assertEqual(request,p['request'])
                    self.assertIn('bucket',request['promptText'])
                    self.assertNotIn('luxury-advert still',request['promptText'])
                    return {'id':str(uuid.uuid4())}
            client=Fake()
            first=video.start_job(self.con,DID,1,path,folder,client=client,max_credits=25,scene_request=p['request'])
            again=video.start_job(self.con,DID,1,path,folder,client=client,max_credits=25,scene_request=p['request'])
            self.assertEqual(first['id'],again['id']);self.assertEqual(client.calls,1)
            self.assertEqual(self.con.execute('SELECT SUM(credits) FROM business_scene_reservations').fetchone()[0],25)
    def test_tampered_reference_or_unsupported_model_never_reaches_provider(self):
        import business_runway_video as video,inspect
        self.assertIn('scene_request',inspect.signature(video.start_job).parameters)
        with tempfile.TemporaryDirectory() as folder:
            video.initialise(self.con);path,p,_=self.prepared(folder)
            class Fake:
                def balance(self):raise AssertionError('Invalid request must fail before provider access')
            for key,value in [('model','unreviewed-model'),('duration',8),('promptImage',fixtures.image_uri('red')),('promptText','Changed instructions with no matching reviewed contract.'*3)]:
                request={**p['request'],key:value}
                with self.assertRaises(video.VideoError):video.start_job(self.con,DID,1,path,folder,client=Fake(),max_credits=25,scene_request=request)
    def test_source_change_between_preparation_and_record_is_not_accepted(self):
        a=self.asset();p=planner.prepare(self.con,DID,1,intent(),reference_pool=[a])
        review=self.assessment(p);contracts.open_envelope(self.con,DID,maximum_credits=100,approval_reference='offline-explicit-test-no-live-model')
        original=contracts.record
        def change_source(*args,**kwargs):
            d=drafts.read_draft(self.con,DID)['document'];d['observedFacts'][0]+=' Changed while awaiting lock.'
            self.con.execute('UPDATE marketing_drafts SET document_json=? WHERE id=?',(json.dumps(d),DID));self.con.commit()
            return original(*args,**kwargs)
        with patch.object(contracts,'record',side_effect=change_source):
            with self.assertRaises(planner.PreparationError):
                planner.record_reviewed(self.con,DID,1,intent(),reference_pool=[a],expected_fingerprint=p['fingerprint'],assessment=review)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_scene_contracts').fetchone()[0],0)
    def test_review_and_contract_write_rollback_together(self):
        a=self.asset();p=planner.prepare(self.con,DID,1,intent(),reference_pool=[a]);contracts.open_envelope(self.con,DID,maximum_credits=100,approval_reference='offline-explicit-test-no-live-model')
        self.con.execute("CREATE TRIGGER deny_review BEFORE INSERT ON business_scene_preparation_reviews BEGIN SELECT RAISE(ABORT,'fixture failure'); END;")
        with self.assertRaises(Exception):
            planner.record_reviewed(self.con,DID,1,intent(),reference_pool=[a],expected_fingerprint=p['fingerprint'],assessment=self.assessment(p))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_scene_contracts').fetchone()[0],0)
