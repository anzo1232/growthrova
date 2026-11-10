"""Decision fixtures are not held-out visual or marketing-quality benchmarks."""
import importlib.util,unittest
from pathlib import Path
class PreparationEvaluationTests(unittest.TestCase):
    def test_cross_niche_examples_are_offline_and_honest_about_scope(self):
        path=Path(__file__).resolve().parents[1]/'scripts/evaluate_business_preparation.py'
        self.assertTrue(path.is_file(),'Cross-niche preparation evaluator is missing')
        spec=importlib.util.spec_from_file_location('prep_evaluation',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        report=module.evaluate()
        self.assertGreaterEqual(report['caseCount'],12)
        self.assertEqual(report['failed'],0,report['cases'])
        self.assertEqual(report['networkAttempts'],0)
        self.assertFalse(report['commercialQualityProven']);self.assertFalse(report['fineTuningPerformed'])
        self.assertEqual(report['generationCalls'],0)
        self.assertTrue(any(x['mode']=='reuse_source_image' for x in report['cases']))
        self.assertTrue(any(x['mode']=='reference_image_to_video' for x in report['cases']))
        self.assertTrue(any(x['mode']=='hold' for x in report['cases']))
