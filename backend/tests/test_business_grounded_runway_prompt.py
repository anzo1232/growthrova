import unittest
import business_runway as r
from tests.test_business_marketing_drafts import document
class RunwayGroundingTests(unittest.TestCase):
 def test_beranjak_research_becomes_specific_not_generic_restaurant_shot(self):
  doc=document();doc['business']='Berenjak'
  doc['observedFacts']=['Berenjak Persian kababi in Soho: food from Iranian family traditions']
  doc['editorialShortlist']={
   'status':'three_directions_ready_for_asset_intake','candidates':[
    {'evidence':{'quote':'Popular Persian koobideh ground lamb kabab shaped on a skewer, grilled over the mangal.'}},
    {'evidence':{'quote':'Tehran hole-in-the-wall kababi traditions shaped this restaurant.'}},
    {'evidence':{'quote':'Sangak flatbread is baked on hot river stones and has an uneven texture.'}}
   ]}
  prompt=r._recipe(doc,'creative-1')['promptText']
  self.assertIn('traditional mangal',prompt)
  self.assertIn('sangak Persian flatbread',prompt)
  self.assertIn('Tehran kababi',prompt)
  self.assertIn('not generic steakhouse steak',prompt)
  self.assertIn('fictional',prompt.lower())
  self.assertEqual(r._recipe(doc,'creative-1')['outputCount'],1)
  self.assertEqual(r._recipe(doc,'creative-1')['ratio'],'1536:1920')
 def test_unverified_shortlist_with_empty_evidence_cannot_add_fake_specifics(self):
  doc=document();doc['business']='Example Dining Room'
  doc['editorialShortlist']={'status':'blocked_insufficient_unique_brand_evidence','candidates':[]}
  prompt=r._recipe(doc,'creative-1')['promptText']
  self.assertNotIn('traditional mangal',prompt)
  self.assertNotIn('sangak Persian flatbread',prompt)
 def test_no_paid_job_created_by_recipe_review(self):
  doc=document();doc['business']='Berenjak'
  assert r._recipe(doc,'creative-1')['model']=='gpt_image_2'
