"""Real local contract/SQLite behaviour, entirely synthetic images and evidence."""
import base64,copy,hashlib,importlib,importlib.util,io,json,sqlite3,tempfile,threading,unittest,uuid
from pathlib import Path
from PIL import Image
import business_marketing_drafts as drafts
from tests.test_business_marketing_drafts import document

DID='a'*32

def image_uri(colour='gray'):
    data=io.BytesIO();Image.new('RGB',(320,480),colour).save(data,'PNG')
    return 'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()

def request(text='A documentary illustration of a specific customer problem with stable lighting, coherent perspective and natural materials. Camera movement should preserve object proportions throughout.'):
    return {'model':'gen4.5','ratio':'720:1280','duration':8,'promptText':text}

def scene(ident='opening'):
    return {'sceneId':ident,'purpose':'Show the documented service and customer need',
        'customerAction':'Request a quote for the documented service','sourceFactIndices':[0],
        'origin':'illustrative_ai','useAsProof':False,'peoplePolicy':'none',
        'expectedAction':'The intended subject remains clearly visible with physically credible movement.',
        'failureChecks':['Reject distorted object scale and unnatural physics.','Reject unrelated or invented business proof.'],
        'referenceIds':[],'continuity':None}

class SceneContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('business_scene_contracts'),'Scene contracts are not implemented')
        self.api=importlib.import_module('business_scene_contracts')
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        drafts.initialise(self.con);self.api.initialise(self.con)
        self.save(DID,'https://example.org/')
        self.api.open_envelope(self.con,DID,maximum_credits=100,approval_reference='offline-test-authority')
    def save(self,did,url):
        d=document();d['sourceUrl']=url
        drafts.save_draft(self.con,{'id':did,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':d})
    def record(self,s=None,r=None,cost=96,did=DID):
        return self.api.record(self.con,did,1,s or scene(),r or request(),cost,reviewer_reference='offline-fixture-review')
    def ref(self,ident='roof',colour='gray',did=DID,parent=None):
        return self.api.register_reference(self.con,did,ident,image_uri(colour),origin='illustrative_ai',
            rights_reference='synthetic-test-fixture-no-client',reviewer_reference='offline-fixture-review',parent_reference_id=parent)
    def check(self,r=None,cost=96):return self.api.check(self.con,DID,1,r or request(),cost)
    def reserve(self,r=None,cost=96,job='job-1',did=DID):
        return self.api.reserve(self.con,did,1,r or request(),cost,job)
    def test_missing_contract_is_read_only_and_fails_closed(self):
        before=self.con.total_changes
        with self.assertRaises(self.api.ContractError) as denied:self.check()
        self.assertEqual(denied.exception.code,'scene_contract_required');self.assertEqual(self.con.total_changes,before)
    def test_recorded_scene_binds_request_and_never_claims_creative_acceptance(self):
        result=self.record();checked=self.check()
        self.assertEqual(result['id'],checked['id']);self.assertFalse(checked['approvedForPublishing'])
        self.assertFalse(checked['visualQualityVerified']);self.assertFalse(checked['spendAuthorised'])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_scene_reservations').fetchone()[0],0)
    def test_missing_evidence_or_failure_checks_is_not_a_scene(self):
        for key,value in [('sourceFactIndices',[]),('sourceFactIndices',[-1]),('sourceFactIndices',[True]),('sourceFactIndices',[99]),('failureChecks',[]),('purpose','nice')]:
            with self.subTest(key=key,value=value):
                s=scene();s[key]=value
                with self.assertRaises(self.api.ContractError):self.record(s)
    def test_synthetic_work_cannot_become_real_business_proof(self):
        for field,value in [('useAsProof',True),('origin','actual_client_work')]:
            s=scene();s[field]=value
            with self.assertRaises(self.api.ContractError):self.record(s)
    def test_none_people_policy_rejects_positive_people_instruction(self):
        with self.assertRaises(self.api.ContractError):
            self.record(r=request('No people in the background. A foreground worker demonstrates the roofing service with gloved hands, clearly showing materials and the roof repair in natural daylight.'))
    def test_changed_payload_or_credit_cost_invalidates_contract(self):
        self.record()
        for key,value in [('duration',5),('promptText',request()['promptText']+' New wording.'),('ratio','1280:720')]:
            r=request();r[key]=value
            with self.assertRaises(self.api.ContractError):self.check(r)
        with self.assertRaises(self.api.ContractError):self.check(cost=95)
    def test_changed_revision_cannot_reuse_contract(self):
        self.record();saved=drafts.read_draft(self.con,DID)
        drafts.save_draft(self.con,{'id':DID,'expectedRevision':1,'mutationId':uuid.uuid4().hex,'document':saved['document']})
        with self.assertRaises(self.api.ContractError):self.check()
    def test_record_is_idempotent_but_scene_cannot_be_overwritten(self):
        a=self.record();self.assertEqual(a['id'],self.record()['id'])
        s=scene();s['expectedAction']+=' Change the subject.'
        with self.assertRaises(self.api.ContractError):self.record(s)
    def test_continuity_requires_actual_provider_reference(self):
        s=scene();s['continuity']={'groupId':'roof-identity','previousSceneId':None}
        with self.assertRaises(self.api.ContractError) as denied:self.record(s)
        self.assertEqual(denied.exception.code,'continuity_reference_required')
    def test_reference_bytes_must_match_the_sent_image(self):
        self.ref();s=scene();s['referenceIds']=['roof']
        r=request();r['promptImage']=image_uri('red')
        with self.assertRaises(self.api.ContractError):self.record(s,r)
        r['promptImage']=image_uri();self.record(s,r);self.check(r)
    def test_unregistered_reference_and_url_only_reference_fail(self):
        s=scene();s['referenceIds']=['invented'];r=request();r['promptImage']=image_uri()
        with self.assertRaises(self.api.ContractError):self.record(s,r)
        self.ref();s['referenceIds']=['roof'];r['promptImage']='https://example.org/a.png'
        with self.assertRaises(self.api.ContractError):self.record(s,r)
    def test_registered_reference_cannot_be_silently_replaced(self):
        self.ref()
        with self.assertRaises(self.api.ContractError):self.ref(colour='red')
    def test_foreign_business_reference_is_not_reusable(self):
        self.save('b'*32,'https://other.example/');self.ref(did='b'*32)
        s=scene();s['referenceIds']=['roof'];r=request();r['promptImage']=image_uri()
        with self.assertRaises(self.api.ContractError):self.record(s,r)
    def first_continuity_scene(self):
        self.ref();s=scene();s['referenceIds']=['roof'];s['continuity']={'groupId':'identity','previousSceneId':None}
        r=request();r['promptImage']=image_uri();self.record(s,r)
    def test_same_group_cannot_change_to_unrelated_house(self):
        self.first_continuity_scene();self.ref('other-roof','red')
        s=scene('repaired');s['referenceIds']=['other-roof'];s['continuity']={'groupId':'identity','previousSceneId':'opening'}
        r=request();r['promptImage']=image_uri('red')
        with self.assertRaises(self.api.ContractError) as denied:self.record(s,r)
        self.assertEqual(denied.exception.code,'continuity_identity_mismatch')
    def test_reviewed_derivative_keeps_identity_lineage(self):
        self.first_continuity_scene();self.ref('reviewed-repair','red',parent='roof')
        s=scene('repaired');s['referenceIds']=['reviewed-repair'];s['continuity']={'groupId':'identity','previousSceneId':'opening'}
        r=request();r['promptImage']=image_uri('red')
        self.record(s,r);self.assertEqual(self.check(r)['identityRoot'],'roof')
    def test_fake_predecessor_does_not_establish_continuity(self):
        self.ref();s=scene();s['referenceIds']=['roof'];s['continuity']={'groupId':'identity','previousSceneId':'not-existing'}
        r=request();r['promptImage']=image_uri()
        with self.assertRaises(self.api.ContractError):self.record(s,r)
    def test_shared_envelope_survives_duplicate_draft_and_path(self):
        self.record();self.con.execute('BEGIN IMMEDIATE');self.reserve();self.con.commit()
        self.save('b'*32,'https://www.example.org/landing')
        self.api.open_envelope(self.con,'b'*32,maximum_credits=100,approval_reference='offline-test-authority')
        other=request();other['promptText']+=' Different ad.';self.record(scene('other'),other,did='b'*32)
        self.con.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaises(self.api.ContractError) as denied:self.reserve(other,job='job-2',did='b'*32)
            self.assertEqual(denied.exception.code,'campaign_budget_exceeded')
        finally:self.con.rollback()
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_campaign_envelopes').fetchone()[0],1)
    def test_mixed_media_share_one_envelope(self):
        image={'model':'gpt_image_2','ratio':'1536:1920','outputCount':1,'quality':'high','promptText':request()['promptText']}
        self.record(scene('image'),image,20);self.record()
        self.con.execute('BEGIN IMMEDIATE');self.reserve(image,20,'image-job');self.con.commit()
        self.con.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaises(self.api.ContractError):self.reserve()
        finally:self.con.rollback()
    def test_reservation_requires_transaction_and_cannot_replay_as_another_job(self):
        self.record()
        with self.assertRaises(self.api.ContractError):self.reserve()
        self.con.execute('BEGIN IMMEDIATE');one=self.reserve();self.con.commit()
        self.con.execute('BEGIN IMMEDIATE');two=self.reserve();self.con.commit()
        self.assertEqual(one,two)
        self.con.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaises(self.api.ContractError):self.reserve(job='different-job')
        finally:self.con.rollback()
    def test_failed_job_transaction_rolls_back_debit(self):
        self.record();self.con.execute('BEGIN IMMEDIATE');self.reserve();self.con.rollback()
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_scene_reservations').fetchone()[0],0)
    def test_envelope_limit_cannot_be_reopened_as_a_topup(self):
        with self.assertRaises(self.api.ContractError):self.api.open_envelope(self.con,DID,maximum_credits=200,approval_reference='offline-test-authority')
    def test_invalid_boolean_and_nonfinite_costs_are_rejected(self):
        for cost in [True,0,-1,96.0,float('nan')]:
            with self.subTest(cost=cost):
                with self.assertRaises(self.api.ContractError):self.record(cost=cost)
    def test_tampered_scene_json_fails_integrity_check(self):
        self.record();self.con.execute("UPDATE business_scene_contracts SET scene_json='{}'");self.con.commit()
        with self.assertRaises(self.api.ContractError):self.check()
    def test_legacy_reservations_are_not_reset_by_new_envelope(self):
        self.save('c'*32,'https://legacy.example/')
        self.con.execute('CREATE TABLE runway_image_jobs(draft_id TEXT,reserved_credits INTEGER)')
        self.con.execute('INSERT INTO runway_image_jobs VALUES(?,?)',('c'*32,96));self.con.commit()
        value=self.api.open_envelope(self.con,'c'*32,maximum_credits=100,approval_reference='offline-test-authority')
        self.assertEqual(value['legacyReservedCredits'],96)

    def test_textual_same_property_claim_cannot_omit_reference_plan(self):
        r=request('Show the same roof and same house before and after the proposed repair. Track along the chimney and retain all surroundings while showing the repaired tiles in a realistic documentary sequence.')
        with self.assertRaises(self.api.ContractError) as denied:self.record(r=r)
        self.assertEqual(denied.exception.code,'continuity_reference_required')
    def test_illustration_label_does_not_excuse_actual_client_claim_in_prompt(self):
        r=request('Show our actual staff beside the completed roofing work for a real customer, with a professionally photographed documentary camera angle and very believable natural light and precise materials.')
        s=scene();s['peoplePolicy']='illustrative_only'
        with self.assertRaises(self.api.ContractError) as denied:self.record(s,r)
        self.assertEqual(denied.exception.code,'synthetic_proof_forbidden')
    def test_reference_without_identity_group_is_insufficient_for_same_house(self):
        self.ref();s=scene();s['referenceIds']=['roof']
        r=request('Show the same house following the repair, preserving its roof, chimney, wall and surroundings throughout a smooth documentary shot with realistic lighting, materials and natural movement.')
        r['promptImage']=image_uri()
        with self.assertRaises(self.api.ContractError):self.record(s,r)
    def test_unneeded_before_after_prohibition_does_not_block_standalone_scene(self):
        self.record(r=request(request()['promptText']+' No before-after claims.'))
    def test_two_connections_cannot_reserve_over_shared_limit(self):
        first=request();first['promptText']+=' First shot.'
        second=request();second['promptText']+=' Second shot.'
        self.record(scene('race-one'),first,60);self.record(scene('race-two'),second,60)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'race.db'
            mirror=sqlite3.connect(path);self.con.backup(mirror);mirror.close()
            ready=threading.Barrier(2);results=[]
            def attempt(index,req):
                con=sqlite3.connect(path,timeout=5);con.row_factory=sqlite3.Row
                try:
                    self.api.check(con,DID,1,req,60);ready.wait(timeout=5)
                    con.execute('BEGIN IMMEDIATE')
                    self.api.reserve(con,DID,1,req,60,'race-job-'+str(index));con.commit();results.append('reserved')
                except self.api.ContractError as exc:con.rollback();results.append(exc.code)
                except Exception as exc:con.rollback();results.append(type(exc).__name__)
                finally:con.close()
            threads=[threading.Thread(target=attempt,args=(i,r)) for i,r in enumerate((first,second))]
            for thread in threads:thread.start()
            for thread in threads:thread.join(timeout=8)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertCountEqual(results,['reserved','campaign_budget_exceeded'])
            verify=sqlite3.connect(path)
            try:self.assertEqual(verify.execute('SELECT SUM(credits) FROM business_scene_reservations').fetchone()[0],60)
            finally:verify.close()

    def test_explicit_prohibition_of_fake_job_proof_is_not_a_positive_claim(self):
        self.record(r=request(request()['promptText']+' Never imply that fictional properties, fictional customers or generated scenes show real completed work.'))
    def test_negative_claim_clause_cannot_hide_later_positive_assertion(self):
        text=request()['promptText']+' Never claim actual staff, but show our completed work as the actual business result.'
        s=scene();s['peoplePolicy']='illustrative_only'
        with self.assertRaises(self.api.ContractError):self.record(s,request(text))

    def test_dns_spelling_cannot_reset_website_envelope(self):
        for i,url in enumerate(['https://www.example.org./page','https://EXAMPLE.ORG:443/another']):
            did=str(i+2)*32;self.save(did,url)
            self.api.open_envelope(self.con,did,maximum_credits=100,approval_reference='offline-test-authority')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_campaign_envelopes').fetchone()[0],1)
    def test_international_domain_spelling_shares_one_scope(self):
        for i,url in enumerate(['https://b\u00fccher.example/','https://xn--bcher-kva.example/']):
            did=str(i+4)*32;self.save(did,url)
            self.api.open_envelope(self.con,did,maximum_credits=100,approval_reference='offline-test-authority')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_campaign_envelopes').fetchone()[0],2)

    def test_do_not_depict_real_clients_is_a_prohibition(self):
        self.record(r=request(request()['promptText']+' Do not depict real clients or testimonials.'))
    def test_saved_browser_campaign_prompt_is_not_misread_as_fake_client_claim(self):
        r=json.loads((Path(__file__).parent/'fixtures/business-scene-browser-request.json').read_text())
        s=scene();s['peoplePolicy']='illustrative_only'
        self.record(s,r,20);self.check(r,20)
