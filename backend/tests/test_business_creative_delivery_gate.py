import unittest
from business_creative_delivery_gate import preflight,pack_delivery_status
class CreativeDeliveryGateTests(unittest.TestCase):
 def base(self):
  return {'width':720,'height':1280,
   'identity':{'name':'Cedar','expectedCity':'Portsmouth','sourceBusinessMismatch':False},
   'brand':{'logoSource':'none','brandingReviewedByOwner':True},
   'texts':[{'bbox':[56,745,594,900],'contrastChecked':True}],
   'claims':[],
   'shots':[
    {'sourceId':'hummus','kind':'video','phase':'opening','subjectTag':'mezze','licenseConfirmed':True,'stock':True,'illustrativeDisclosure':True},
    {'sourceId':'pita','kind':'video','phase':'experience','subjectTag':'mezze','licenseConfirmed':True,'stock':True,'illustrativeDisclosure':True},
    {'sourceId':'mezze','kind':'video','phase':'experience','subjectTag':'mezze','licenseConfirmed':True,'stock':True,'illustrativeDisclosure':True},
    {'sourceId':'baklava','kind':'video','phase':'experience','subjectTag':'dessert','licenseConfirmed':True,'stock':True,'illustrativeDisclosure':True},
    {'sourceId':'tea','kind':'video','phase':'close','subjectTag':'tea','licenseConfirmed':True,'stock':True,'illustrativeDisclosure':True}],
   'finalVideo':{'actualVideoDecoded':True,'technicalMotionPass':True}}
 def test_clean_structure_never_auto_approves(self):
  result=preflight(self.base())
  self.assertTrue(result['technicalAndProvenancePass'])
  self.assertFalse(result['publishReady']);self.assertFalse(result['paidAdReady'])
 def test_shop_sign_crop_and_overflow_block(self):
  broken=self.base();broken['brand']['logoSource']='storefront_photo_crop'
  broken['texts'][0]['bbox']=[52,920,810,1080]
  result=preflight(broken)
  self.assertIn('cropped_shop_sign_or_unapproved_logo',result['blockers'])
  self.assertTrue(any(x.startswith('mobile_text_overflow') for x in result['blockers']))
 def test_unrelated_steakhouse_london_brand_and_unlicensed_photo_block(self):
  m=self.base();m['identity']['sourceBusinessMismatch']=True
  m['shots'][0].update(subjectTag='steakhouse',licenseConfirmed=False)
  got=preflight(m)
  self.assertIn('wrong_business_website',got['blockers'])
  self.assertIn('off_brand_visual_source',got['blockers'])
  self.assertIn('source_usage_rights_unconfirmed',got['blockers'])
 def test_repetition_faux_footage_and_unconfirmed_claim_rejected(self):
  m=self.base()
  for s in m['shots']:s['sourceId']='one'
  m['shots'][0]['illustrativeDisclosure']=False
  m['claims']=[{'text':'From 1997 in Portsmouth','statedAsFact':True,'verifiedOwner':False}]
  got=preflight(m)
  self.assertIn('insufficient_shot_variety',got['blockers'])
  self.assertIn('excessive_reused_stock_shot',got['blockers'])
  self.assertIn('stock_masquerading_as_business_footage',got['blockers'])
  self.assertIn('unsupported_advertising_claim',got['blockers'])
 def test_missing_motion_is_not_success(self):
  m=self.base();m['finalVideo']['technicalMotionPass']=False
  self.assertIn('media_not_technically_verified',preflight(m)['blockers'])

class PackDeliveryHookTests(unittest.TestCase):
 def test_url_pack_never_claims_ad_ready_without_verified_brand_assets(self):
  status=pack_delivery_status({'business':'Cedar Portsmouth'},
       asset_origin='generated_scene_and_local_composites',
       video_origin='local_motion_concept')
  self.assertFalse(status['publishReady']);self.assertFalse(status['paidAdReady'])
  self.assertTrue(status['autoPublishBlocked'])
  self.assertIn('authentic_business_media_not_provided',status['blockingReasons'])
 def test_even_generated_motion_never_grants_approval(self):
  status=pack_delivery_status({'business':'Example'},
       asset_origin='owner_declared_website_photos',
       video_origin='runway_generated_scene_with_local_cta')
  self.assertFalse(status['publishReady'])
  self.assertIn('generated_video_requires_subject_and_motion_review',status['blockingReasons'])
