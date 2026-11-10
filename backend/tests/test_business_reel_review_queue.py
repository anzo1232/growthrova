"""Private internal Reel queue from genuine DB state, not fabricated approvals."""
import sqlite3,unittest,uuid,time,json
import business_marketing_drafts as drafts
import business_cinematic_video as cinematic
import business_reel_workbench as reel
import business_reel_review_queue as queue
from tests.test_business_marketing_drafts import document

class InternalQueueTests(unittest.TestCase):
 def setUp(self):
  self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
  self.addCleanup(self.con.close)
  drafts.initialise(self.con);cinematic.initialise(self.con);reel.initialise(self.con)
  self.project_ids={}
  for sector,business in [('restaurant','Example Persian Kababi'),('beauty','Example Beauty Clinic'),
   ('renovation','Example Construction'),('concierge','Example Concierge')]:
   did=uuid.uuid4().hex
   content=document();content['business']=business
   content['editorialShortlist']={'status':'three_directions_ready_for_asset_intake',
    'sector':sector,'candidates':[
     {'id':'kind'+str(i),'role':'Creative direction','media':'Reel','format':'9:16',
      'direction':sector+' distinctive service moment',
      'hook':business+' real business direction number '+str(i),
      'evidence':{'kind':('method','heritage','service')[i],'label':'website',
       'quote':business+' provides a carefully described service, with distinctive customer experience.'}}
     for i in range(3)]}
   drafts.save_draft(self.con,{'id':did,'mutationId':uuid.uuid4().hex,'expectedRevision':0,'document':content})
   self.project_ids[sector]=reel.create(self.con,did,1)
 def test_queue_keeps_sectors_distinct_and_never_authorises_payment(self):
  result=queue.queue(self.con)
  self.assertEqual(result['totalPending'],16)
  self.assertEqual(len(result['pending']),16)
  self.assertTrue(result['internalOnly'])
  self.assertFalse(result['customerCanApproveFromQueue'])
  self.assertFalse(result['paidGenerationStartedByQueue'])
  self.assertEqual({x['business'] for x in result['pending']},
   {'Example Persian Kababi','Example Beauty Clinic','Example Construction','Example Concierge'})
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM runway_cinematic_shots').fetchone()[0],0)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_allowances').fetchone()[0],0)
 def test_internal_queue_report_is_read_only_and_source_text_is_html_escaped(self):
  record=self.project_ids['restaurant']
  self.con.execute('UPDATE business_reel_projects SET brief_json=? WHERE id=?',
   (json.dumps({'business':'Test Restaurant <script>alert(1)</script>',
    'sourceUrl':'https://example.org','slots':[{'slot':'hook','sourceEvidence':'<img src=x onerror=alert(1)>',
      'sourceDirection':'Factual source not owner verified','productionStatus':'not_generated'}]}),record['id']))
  html=queue.render_staff_report(self.con,draft_id=record['draftId'])
  self.assertIn('&lt;script&gt;',html)
  self.assertIn('&lt;img src=x onerror=alert(1)&gt;',html)
  self.assertNotIn('<script>',html)
  self.assertNotIn('<button',html)
  self.assertNotIn('<form',html)
  self.assertIn('Private read-only queue',html)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_vision_jobs').fetchone()[0],0) if any(
    x[0]=='business_reel_vision_jobs' for x in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")) else None
 def test_priority_escalates_unknown_original_submission_before_new_work(self):
  project=self.project_ids['restaurant']
  did=project['draftId']
  self.con.execute('INSERT INTO runway_cinematic_shots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
   (uuid.uuid4().hex,did,1,'workbench:'+project['id']+':hook',uuid.uuid4().hex,
    'submission_unknown',None,'{}',96,None,None,'provider_connection_error',time.time(),time.time()))
  self.con.commit()
  result=queue.queue(self.con,draft_id=did)
  self.assertEqual(result['pending'][0]['status'],'reconcile_required')
  self.assertIn('do not retry',result['pending'][0]['nextAction'])
  self.assertEqual(result['pending'][0]['customerAllowanceConsumed'],0)
  self.assertFalse(result['pending'][0]['newPaidGenerationApproved'])
 def test_archived_revisions_not_returned_and_review_queue_is_readonly(self):
  before=queue.queue(self.con)
  self.assertEqual(before['totalPending'],16)
  project=self.project_ids['beauty']
  saved=drafts.read_draft(self.con,project['draftId'])
  drafts.save_draft(self.con,{'id':project['draftId'],'mutationId':uuid.uuid4().hex,
   'expectedRevision':1,'document':{**saved['document'],'name':'Updated real beauty brief'}})
  result=queue.queue(self.con)
  self.assertEqual(result['totalPending'],12)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_projects').fetchone()[0],4)
  self.assertEqual(self.con.execute('SELECT COUNT(*) FROM business_reel_visual_reviews').fetchone()[0],0)
