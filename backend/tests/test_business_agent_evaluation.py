"""The reusable evaluation runs in a fresh process with network calls forbidden."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class AgentEvaluationTests(unittest.TestCase):
 def test_offline_cross_niche_evaluation_has_no_false_approvals(self):
  run=subprocess.run([sys.executable,str(ROOT/'scripts/evaluate_business_agent.py')],cwd=ROOT,capture_output=True,text=True,timeout=30)
  self.assertEqual(run.returncode,0,run.stderr+run.stdout)
  report=json.loads(run.stdout)
  self.assertGreaterEqual(report['caseCount'],60)
  self.assertEqual(report['failed'],0)
  self.assertEqual(report['networkAttempts'],0)
  self.assertEqual(report['generationAuthorisations'],0)
  self.assertFalse(report['fineTuningPerformed'])
  self.assertEqual(report['scope'],'offline_decision_regression_not_media_quality')
 def test_wrong_expected_trait_returns_a_nonzero_failure(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'cases.json'
   p.write_text(json.dumps({'schemaVersion':1,'provenance':'test','cases':[{'id':'bad','business':'Test','observations':['Local roof repairs and guttering services.'],'expectedTraits':['software']}]}))
   run=subprocess.run([sys.executable,str(ROOT/'scripts/evaluate_business_agent.py'),'--cases',str(p)],cwd=ROOT,capture_output=True,text=True,timeout=30)
   self.assertEqual(run.returncode,1,run.stderr+run.stdout)
   report=json.loads(run.stdout)
   self.assertEqual(report['failed'],1)
