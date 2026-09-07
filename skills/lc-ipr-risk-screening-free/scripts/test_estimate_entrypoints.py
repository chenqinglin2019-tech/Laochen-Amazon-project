"""Real offline CLI round trips for policy selection and history isolation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common import sha256_file
from test_assessment_estimate import fixture
from test_assessment_v24 import setup_scope

K = Path(__file__).resolve().parent


class EstimateEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ipr-policy-cli-')
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, *args, ok=True):
        p = subprocess.run([sys.executable, str(K / name), *map(str, args)], capture_output=True, text=True)
        if ok:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0)
        return p

    def write_fixture(self, legacy=False):
        values = setup_scope(self.source) if legacy else fixture(self.source)
        values[0].pop('assessment_policy', None)
        for name, item in zip(('task', 'evidence', 'normalized-candidates', 'search-plan', 'materiality-annotations', 'first-review', 'second-review'), values):
            (self.source / (name + '.json')).write_text(json.dumps(item))
        return {p.name: sha256_file(p) for p in self.source.glob('*.json')}

    def reviews(self):
        return ('--first-review', self.source / 'first-review.json', '--second-review', self.source / 'second-review.json')

    def test_new_tasks_select_five_level_policy(self):
        self.call('create_task.py', '--url', 'https://www.amazon.com/dp/B012345678', '--jurisdictions', 'US', '--output-dir', self.root / 'new')
        task = json.loads((self.root / 'new/task.json').read_text())
        self.assertEqual(task['assessment_policy'], 'evidence-estimate-v1')
        self.assertEqual(task['schema_version'], '2.4-free')

    def test_strict_stage_roundtrip_separates_integrity_and_business(self):
        from test_assessment_estimate_recall import strict_fixture
        values = strict_fixture(self.source)
        for name, item in zip(('task', 'evidence', 'normalized-candidates', 'search-plan', 'materiality-annotations', 'first-review', 'second-review'), values):
            (self.source / (name + '.json')).write_text(json.dumps(item))
        done = self.call('finalize_assessment.py', '--task-dir', self.source, *self.reviews())
        self.assertIn('incomplete', done.stdout)
        self.call('build_report.py', '--task-dir', self.source)
        validated = self.call('validate_run.py', '--task-dir', self.source)
        self.assertIn('file_integrity: valid; business_completion: incomplete', validated.stdout)
        result = json.loads((self.source / 'assessment.json').read_text())
        self.assertIsNone(result['overall']['risk'])
        self.assertEqual(result['overall']['known_scoped_risk'], '高')

    def test_explicit_reassessment_roundtrip_preserves_old_inputs(self):
        before = self.write_fixture()
        historical_assessment = self.source / 'assessment.json'
        historical_assessment.write_text(json.dumps({'assessment_contract': 'SCOPED-IPR/1.0', 'overall': {'risk': '无法判断'}, 'history_sentinel': True}))
        before[historical_assessment.name] = sha256_file(historical_assessment)
        output = self.root / 'estimate'
        self.call('finalize_assessment.py', '--task-dir', self.source, '--assessment-policy', 'evidence-estimate-v1', *self.reviews(), '--output-dir', output)
        self.call('build_report.py', '--task-dir', self.source, '--output-dir', output)
        self.call('validate_run.py', '--task-dir', self.source, '--output-dir', output)
        self.call('validate_run.py', '--task-dir', output)
        self.call('build_report.py', '--task-dir', output)
        self.call('validate_run.py', '--task-dir', self.source, '--output-dir', output)
        self.assertTrue(all(sha256_file(self.source / n) == value for n, value in before.items()))
        self.assertEqual(json.loads((output / 'assessment.json').read_text())['assessment_policy'], 'evidence-estimate-v1')

    def test_historical_task_without_policy_keeps_legacy_evaluator(self):
        self.write_fixture(legacy=True)
        self.call('finalize_assessment.py', '--task-dir', self.source, *self.reviews())
        result = json.loads((self.source / 'assessment.json').read_text())
        self.assertEqual(result['assessment_contract'], 'SCOPED-IPR/1.0')
        self.assertNotIn('assessment_policy', result)

    def test_historical_upgrade_cannot_overwrite_source(self):
        before = self.write_fixture()
        for extra in ((), ('--output-dir', self.source)):
            self.call('finalize_assessment.py', '--task-dir', self.source, '--assessment-policy', 'evidence-estimate-v1', *self.reviews(), *extra, ok=False)
        self.assertTrue(all(sha256_file(self.source / n) == value for n, value in before.items()))

    def test_unknown_existing_policy_cannot_be_silently_replaced(self):
        self.write_fixture()
        path = self.source / 'task.json'
        task = json.loads(path.read_text())
        task['assessment_policy'] = 'future-policy'
        path.write_text(json.dumps(task))
        before = sha256_file(path)
        self.call('finalize_assessment.py', '--task-dir', self.source, '--assessment-policy', 'evidence-estimate-v1', *self.reviews(), ok=False)
        self.assertEqual(sha256_file(path), before)

    def test_actual_cli_rejects_report_identity_decision_and_attachment_overrides(self):
        self.write_fixture()
        output = self.root / 'estimate'
        self.call('finalize_assessment.py', '--task-dir', self.source, '--assessment-policy', 'evidence-estimate-v1', *self.reviews(), '--output-dir', output)
        outside = self.root / 'outside.txt'
        outside.write_text('not a frozen source')
        probes = [
            ({'product_facts': {'asin': 'B099999999'}}, 'PRODUCT_FACT_OVERRIDE'),
            ({'lead': '本产品极低风险'}, 'DECISION_TEXT_OVERRIDE'),
            ({'sections': [{'blocks': [{'type': 'p', 'html': '<a href="' + str(outside) + '">outside</a>'}]}]}, 'OUTSIDE_EVIDENCE_ROOT'),
        ]
        for content, code in probes:
            path = self.root / 'content.json'
            path.write_text(json.dumps(content))
            with self.subTest(code=code):
                result = self.call('build_report.py', '--task-dir', self.source, '--output-dir', output, '--report-content', path, ok=False)
                self.assertIn(code, result.stderr + result.stdout)
                self.assertFalse((output / 'report.html').exists())
        self.call('build_report.py', '--task-dir', self.source, '--output-dir', output)
        self.call('validate_run.py', '--task-dir', output)

    def test_report_rejects_conflicting_task_policy(self):
        self.write_fixture()
        output = self.root / 'estimate'
        self.call('finalize_assessment.py', '--task-dir', self.source, '--assessment-policy', 'evidence-estimate-v1', *self.reviews(), '--output-dir', output)
        self.call('build_report.py', '--task-dir', self.source, '--output-dir', output)
        path = output / 'task.json'
        task = json.loads(path.read_text())
        task['assessment_policy'] = 'future-policy'
        path.write_text(json.dumps(task))
        self.call('build_report.py', '--task-dir', self.source, '--output-dir', output, ok=False)
        self.call('validate_run.py', '--task-dir', self.source, '--output-dir', output, ok=False)


if __name__ == '__main__':
    unittest.main()
