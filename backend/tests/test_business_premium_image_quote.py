"""Berenjak read-only paid-image preflight: no vendor calls or implicit purchase."""
import unittest,uuid
from tests.test_business_local_pilot import LocalPilotTests
from tests.test_business_marketing_drafts import document
import business_local_pilot as pilot
import business_marketing_drafts as drafts
class PremiumImageQuoteHTTPTests(unittest.TestCase):
 def test_read_only_quote_returns_source_locked_premium_prompt_and_zero_credit_authorisation(self):
  fixture=LocalPilotTests(methodName='test_only_allowed_local_origin_and_header')
  fixture.setUp()
  try:
   did='a'*32;content=document();content['business']='Berenjak'
   content['observedFacts']=['A Persian kababi inspired by Iranian traditions, with charcoal grilled kababs']
   content['editorialShortlist']={
    'status':'three_directions_ready_for_asset_intake','candidates':[
     {'id':'craft','role':'Editorial hero','media':'Reel','format':'9:16','direction':'Charcoal kitchen',
      'hook':'The mangal: how Berenjak grills koobideh','evidence':{'kind':'method','label':'paragraph','quote':'Koobideh, the minced lamb kabab grilled over the mangal by skilled hands.'}},
     {'id':'discover','role':'Restaurant story','media':'Carousel','format':'4:5','direction':'Charcoal inspired menu',
      'hook':"Inspired by Tehran's kabab houses",'evidence':{'kind':'heritage','label':'paragraph','quote':'The inspiration comes from Tehran hole-in-the-wall kababi culture.'}},
     {'id':'insider','role':'Bread','media':'Image','format':'4:5','direction':'Authentic bread making',
      'hook':'Sangak baked on hot stones','evidence':{'kind':'bread','label':'paragraph','quote':'Sangak Persian flatbread is baked on hot river stones, giving it a unique texture.'}}
    ]}
   with pilot.session() as con:
    drafts.save_draft(con,{'id':did,'expectedRevision':0,'mutationId':uuid.uuid4().hex,'document':content})
   code,quote=fixture.api('/api/pilot/premium-image-proposal?draftId='+did)
   self.assertEqual(code,200,quote)
   self.assertEqual(quote['estimatedCredits'],20)
   self.assertIn('traditional mangal',quote['exactPrompt'])
   self.assertIn('sangak Persian flatbread',quote['exactPrompt'])
   self.assertFalse(quote['automaticSpendApproved']);self.assertFalse(quote['retryAllowed'])
   self.assertEqual(quote['existingPaidAttemptCount'],0)
   with pilot.session() as con:
    self.assertEqual(con.execute('SELECT count(*) FROM runway_image_jobs').fetchone()[0],0)
   denied,_=fixture.api('/api/pilot/premium-image-proposal?draftId='+did,origin='https://attacker.example')
   self.assertEqual(denied,403)
  finally:fixture.doCleanups()
