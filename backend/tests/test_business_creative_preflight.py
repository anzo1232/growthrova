import unittest
import business_creative_preflight as gate
class CreativePreflightTests(unittest.TestCase):
    def check(self,prompt,**kw):
        return gate.inspect('roofing',prompt,evidence='Website confirms roof repairs and guttering in Portsmouth.',shot_purpose='Show the customer problem and its cause',estimated_credits=96,cap=96,**kw)
    def test_rejects_fake_worker(self):
        self.assertIn('synthetic_worker_or_hands',self.check('A lifelike roofer wearing gloves works on tiles and flashing on a house roof. A smooth moving camera tracks the roofer throughout an eight second video.')['issues'])
    def test_rejects_bad_geometry_risk(self):
        self.assertIn('interior_geometry_uncontrolled',self.check('Natural interior home scene with a leaking ceiling, close camera and a bucket with dripping water; dramatise the roof leak and make the room realistic.')['issues'])
    def test_accepts_no_humans_roof_only(self):
        self.assertTrue(self.check('Eight second roof shot, no people and no workers, dynamic believable rainwater dripping into a blocked gutter. Camera tracks along clay roof tiles and damaged flashing with correct UK roof physics.')['ready'])
    def test_cap_required(self):
        self.assertIn('spend_cap_not_approved',gate.inspect('roofing','A '*100,evidence='Enough clear evidence of roof repairs.',shot_purpose='Show damage clearly',estimated_credits=96,cap=0)['issues'])
if __name__=='__main__': unittest.main()
