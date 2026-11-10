import unittest
from business_growthrova_images import ImageConfig, AUTHORISED_IMAGE_LIFETIME_MICROUSD
class AuthorisedImageSmokeBudgetTests(unittest.TestCase):
 def config(self,**updates):
  data=dict(enabled=True,key='test-only-not-a-real-key',model='gemini-3-pro-image',budget_microusd=1000000,call_cap_microusd=300000,input_rate_microusd_per_million=2000000,output_cost_microusd=234000)
  data.update(updates)
  return ImageConfig(**data)
 def test_explicit_small_smoke_budget_can_run(self):
  self.assertTrue(self.config().available())
 def test_larger_budgets_and_calls_stay_held(self):
  self.assertFalse(self.config(budget_microusd=AUTHORISED_IMAGE_LIFETIME_MICROUSD+1).available())
  self.assertFalse(self.config(call_cap_microusd=300001).available())
 def test_no_credential_or_disabled_setting_stays_held(self):
  self.assertFalse(self.config(key='').available())
  self.assertFalse(self.config(enabled=False).available())
if __name__=='__main__':unittest.main()
