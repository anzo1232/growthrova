"""Admission regressions: fake providers only, never vendor requests."""
import os,unittest
from unittest.mock import patch
import tests.test_business_runway as runway_tests
import tests.test_business_runway_video as runway_video_tests
import tests.test_business_cinematic_video as cinematic_video_tests
import tests.test_business_restaurant_video_paid_test as restaurant_video_paid_test_tests
import tests.test_business_reel_provider_bridge as reel_provider_bridge_tests
import business_runway_video as video
import business_cinematic_video as cinema
import business_reel_provider_bridge as bridge


def remove_scene_records(con):
    # Fixture setup will later seed explicit internal approvals. This test
    # removes them to exercise the product's real absent-contract behaviour.
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='business_scene_contracts'").fetchone():
        con.execute('DELETE FROM business_scene_contracts');con.commit()

class AdmissionTests(unittest.TestCase):
    def fixture(self,cls):
        case=cls();case.setUp();self.addCleanup(case.doCleanups);return case
    def test_new_image_without_scene_contract_never_reaches_provider(self):
        c=self.fixture(runway_tests.RunwayTests);remove_scene_records(c.con)
        with self.assertRaises(c.api.RunwayError) as caught:
            c.api.start_job(c.con,c.payload,client=c.client,max_credits=20)
        self.assertEqual(caught.exception.code,'scene_contract_required')
        self.assertEqual(c.client.submissions,0)
    def test_new_image_to_video_without_contract_never_reaches_provider(self):
        c=self.fixture(runway_video_tests.VideoJobTests);remove_scene_records(c.con)
        with self.assertRaises(video.VideoError) as caught:
            video.start_job(c.con,runway_video_tests.DID,1,c.image,c.root,client=c.client,max_credits=25)
        self.assertEqual(caught.exception.code,'scene_contract_required')
        self.assertEqual(c.client.count,0)
    def test_direct_text_video_without_contract_never_reaches_provider(self):
        c=self.fixture(cinematic_video_tests.CinematicTests);remove_scene_records(c.db)
        with self.assertRaises(cinema.CinematicError) as caught:
            cinema.submit(c.db,'a'*32,1,'concierge_arrival',root=c.root,client=c.client,max_credits=96)
        self.assertEqual(caught.exception.code,'scene_contract_required')
        self.assertEqual(c.client.calls,0)
    def test_legacy_paid_benchmark_without_contract_is_blocked(self):
        c=self.fixture(restaurant_video_paid_test_tests.OneShotVideoTests);remove_scene_records(c.con)
        import business_restaurant_video_paid_test as paid
        with self.assertRaises(paid.SingleVideoTestError) as caught:c.send()
        self.assertEqual(caught.exception.code,'scene_contract_required')
        self.assertEqual(c.client.submits,0)
    def test_approved_reel_shot_still_requires_scene_contract(self):
        c=self.fixture(reel_provider_bridge_tests.BridgeTests)
        remove_scene_records(c.con)
        q=bridge.quote(c.con,c.project,'hook')
        bridge.record_exact_approval(c.con,c.project,'hook',q['fingerprint'],96,'offline-explicit-test-approval')
        remove_scene_records(c.con)
        with patch.dict(os.environ,{'CLIPPR_BUSINESS_RUNWAY_TEST_CAP':'96'}):
            with self.assertRaises(bridge.BridgeError) as caught:
                bridge.submit_preapproved(c.con,c.project,'hook',client=c.fake,allow_paid=True)
        self.assertEqual(caught.exception.code,'scene_contract_required')
        self.assertEqual(c.fake.calls,0)

class SharedAdmissionTests(unittest.TestCase):
    """Use both real admission adapters against ONE local budget and fake vendor."""
    def setUp(self):
        import sqlite3,uuid
        import business_runway as image
        import business_marketing_drafts as drafts
        import business_scene_contracts as contracts
        from tests.test_business_marketing_drafts import document
        from tests.test_business_scene_contracts import scene
        self.image,self.contracts=image,contracts
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        drafts.initialise(self.con);image.initialise(self.con);cinema.initialise(self.con)
        d=document();d['business']='Fixture concierge'
        d['observedFacts']=['The business offers VIP concierge, private transfers and travel coordination.']
        drafts.save_draft(self.con,{'id':'a'*32,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':d})
        contracts.open_envelope(self.con,'a'*32,maximum_credits=100,approval_reference='offline-test-budget-only')
        self.image_request=image._recipe(d,'creative-1')
        self.video_request={'model':cinema.MODEL,'duration':cinema.DURATION,'ratio':'720:1280','promptText':cinema.SHOTS['concierge_arrival'][1]}
        for name,request,cost in [('image',self.image_request,20),('video',self.video_request,96)]:
            spec=scene(name);spec['peoplePolicy']='illustrative_only'
            contracts.record(self.con,'a'*32,1,spec,request,cost,reviewer_reference='offline-fixture-no-creative-claim')
        class Fake:
            images=0;videos=0;balances=0
            def balance(inner):inner.balances+=1;return 1000
            def submit_image(inner,request):inner.images+=1;return {'id':str(uuid.uuid4())}
            def submit_text_video(inner,request):inner.videos+=1;return {'id':str(uuid.uuid4())}
        self.fake=Fake()
    def picture(self):
        return self.image.start_job(self.con,{'draftId':'a'*32,'creativeId':'creative-1','expectedRevision':1},client=self.fake,max_credits=20)
    def video(self):
        return cinema.submit(self.con,'a'*32,1,'concierge_arrival',root='/tmp/offline-unused',client=self.fake,max_credits=96)
    def test_image_then_video_cannot_exceed_shared_budget(self):
        self.picture()
        with self.assertRaises(cinema.CinematicError) as denied:self.video()
        self.assertEqual(denied.exception.code,'campaign_budget_exceeded')
        self.assertEqual((self.fake.images,self.fake.videos),(1,0))
        self.assertEqual(self.con.execute('SELECT SUM(credits) FROM business_scene_reservations').fetchone()[0],20)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0],0)
    def test_video_then_image_cannot_exceed_shared_budget(self):
        self.video()
        with self.assertRaises(self.image.RunwayError) as denied:self.picture()
        self.assertEqual(denied.exception.code,'campaign_budget_exceeded')
        self.assertEqual((self.fake.images,self.fake.videos),(0,1))
        self.assertEqual(self.con.execute('SELECT SUM(credits) FROM business_scene_reservations').fetchone()[0],96)
    def test_contract_removed_during_balance_read_blocks_atomic_admission(self):
        def raced_balance():
            self.con.execute('DELETE FROM business_scene_contracts');self.con.commit();return 1000
        self.fake.balance=raced_balance
        with self.assertRaises(self.image.RunwayError) as denied:self.picture()
        self.assertEqual(denied.exception.code,'scene_contract_required');self.assertEqual(self.fake.images,0)
        self.assertFalse(self.con.in_transaction)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_scene_reservations').fetchone()[0],0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM runway_image_jobs').fetchone()[0],0)
    def test_existing_job_retrieval_never_needs_new_contract_or_vendor_call(self):
        first=self.picture();remove_scene_records(self.con)
        self.fake.balance=lambda:self.fail('Existing receipt must not access the vendor')
        again=self.picture()
        self.assertEqual(first['id'],again['id']);self.assertEqual(self.fake.images,1)
        self.assertEqual(self.con.execute('SELECT SUM(credits) FROM business_scene_reservations').fetchone()[0],20)
    def test_missing_contract_prevents_even_vendor_balance_access(self):
        remove_scene_records(self.con)
        self.fake.balance=lambda:self.fail('No scene contract: must stop before vendor access')
        with self.assertRaises(self.image.RunwayError):self.picture()
        with self.assertRaises(cinema.CinematicError):self.video()
        self.assertEqual((self.fake.images,self.fake.videos),(0,0))
