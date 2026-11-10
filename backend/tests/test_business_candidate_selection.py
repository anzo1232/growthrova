import unittest,json
from business_candidate_selection import parse_response,select_candidates,CandidateError
class CandidateSelectionTest(unittest.TestCase):
 def test_fenced_provider_response_and_overlap(self):
  a={'clips':[{'start_s':10,'end_s':40,'title':'Transformation Reveal','why':'Actual reveal'},
   {'start_s':12,'end_s':37,'title':'Transformation Reveal duplicate','why':'Duplicate'}]}
  b='```json\n'+json.dumps({'clips':[{'start_s':55,'end_s':85,'title':'Precision razor technique','why':'Shows real work'}]})+'\n```'
  r=select_candidates([a,b],120)
  self.assertEqual(len(r['clips']),2)
  self.assertEqual(r['clips'][1]['use'],'supporting_footage')
  self.assertFalse(r['quality_verified'])
 def test_out_of_bounds_hallucinations_and_overlength_excluded(self):
  x={'clips':[{'start_s':120,'end_s':150,'title':'x','why':'x'},
   {'start_s':2,'end_s':90,'title':'x','why':'x'},
   {'start_s':0,'end_s':25,'title':'Finished result','why':'Visual check needed'}]}
  self.assertEqual(len(select_candidates([x],130)['clips']),1)
 def test_invalid_and_excessive_provider_input(self):
  for value in ('garbled','{"wrong":1}'):
   with self.assertRaises(CandidateError):parse_response(value)
  with self.assertRaises(CandidateError):select_candidates([{}]*6,200)
if __name__=='__main__':unittest.main()
