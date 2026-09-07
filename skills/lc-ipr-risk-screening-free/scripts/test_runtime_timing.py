from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import runtime_timing as timing
from common import atomic_write_json


class RuntimeTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = self.root / 'task'
        self.task.mkdir()
        atomic_write_json(self.task / 'task.json', {'specialty_workflow_revision': 'asset-scope-v1'})

    def rows(self, root=None):
        return [json.loads(line) for line in ((root or self.task) / timing.FILENAME).read_text().splitlines()]

    def invoke(self, function, extra=()):
        with patch('sys.argv', ['test', '--task-dir', str(self.task), *extra]):
            return function()

    def test_append_elapsed_not_source_dates_or_business_state(self):
        result = {'status': 'incomplete', 'risk': None}
        @timing.timed_cli('assessment_finalize')
        def main():
            return result
        before = (self.task / 'task.json').read_bytes()
        with patch.object(timing.time, 'perf_counter_ns', side_effect=[100, 12_345_100, 20_000_000, 30_000_000]):
            self.assertIs(self.invoke(main), result)
            self.assertIs(self.invoke(main), result)
        rows = self.rows()
        self.assertEqual([row['elapsed_ms'] for row in rows], [12.345, 10.0])
        self.assertEqual(len({row['invocation_id'] for row in rows}), 2)
        self.assertTrue(all(row['status'] == 'success' and 'risk' not in row for row in rows))
        self.assertEqual(before, (self.task / 'task.json').read_bytes())

    def test_legacy_read_only_without_output_directory(self):
        atomic_write_json(self.task / 'task.json', {'schema_version': '2.4-free'})
        main = timing.timed_cli('report_validation')(lambda: 7)
        self.assertEqual(self.invoke(main), 7)
        self.assertFalse((self.task / timing.FILENAME).exists())

    def test_explicit_output_directory_keeps_source_read_only(self):
        atomic_write_json(self.task / 'task.json', {'schema_version': '2.4-free'})
        target = self.root / 'report'
        target.mkdir()
        main = timing.timed_cli('report_validation')(lambda: None)
        self.invoke(main, ['--output-dir=' + str(target)])
        self.assertFalse((self.task / timing.FILENAME).exists())
        self.assertEqual(self.rows(target)[0]['stage'], 'report_validation')

    def test_does_not_create_missing_output_directory(self):
        target = self.root / 'missing'
        self.invoke(timing.timed_cli('candidate_merge')(lambda: 1), ['--output-dir', str(target)])
        self.assertFalse(target.exists())

    def test_original_exception_and_return_survive_logging_failure(self):
        original = ValueError('private detail must not be logged')
        @timing.timed_cli('candidate_triage')
        def fail():
            raise original
        with patch.object(timing, '_append', side_effect=OSError('cannot write')):
            with self.assertRaises(ValueError) as captured:
                self.invoke(fail)
            self.assertIs(captured.exception, original)
            self.assertEqual(self.invoke(timing.timed_cli('candidate_merge')(lambda: 8)), 8)
        self.assertFalse((self.task / timing.FILENAME).exists())

    def test_failure_and_interrupt_records_do_not_leak_exception_text(self):
        for error in (ValueError('secret'), KeyboardInterrupt(), SystemExit(0)):
            def fail():
                raise error
            with self.assertRaises(type(error)):
                self.invoke(timing.timed_cli('report_build')(fail))
        self.assertEqual([row['status'] for row in self.rows()], ['error', 'interrupted', 'success'])
        self.assertNotIn('secret', (self.task / timing.FILENAME).read_text())

    def test_concurrent_lines_stay_complete(self):
        main = timing.timed_cli('candidate_merge')(lambda number: number)
        before = (self.task / 'task.json').read_bytes()
        with patch('sys.argv', ['test', '--task-dir', str(self.task)]):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(main, range(40)))
        self.assertEqual(results, list(range(40)))
        # Auxiliary timing deliberately drops contended writes after 100ms;
        # require complete, unique emitted JSONL rows, not lossless telemetry.
        rows = self.rows()
        self.assertGreater(len(rows), 0)
        self.assertLessEqual(len(rows), 40)
        self.assertEqual(len({row['invocation_id'] for row in rows}), len(rows))
        self.assertTrue(all(row['stage'] == 'candidate_merge' and row['status'] == 'success'
                            and row['auxiliary_only'] for row in rows))
        self.assertEqual(before, (self.task / 'task.json').read_bytes())

    def test_lock_contention_discards_timing_without_retry_or_business_change(self):
        import provider_utils
        busy = provider_utils.ProviderError('PROVIDER_LOCK_BUSY', 'access_limited', 'busy')
        before = (self.task / 'task.json').read_bytes()
        main = timing.timed_cli('candidate_merge')(lambda: 42)
        with patch.object(provider_utils, 'file_lock', side_effect=busy) as lock:
            self.assertEqual(self.invoke(main), 42)
        lock.assert_called_once_with(self.task.resolve() / '.runtime-timings.lock', timeout=0.1)
        self.assertFalse((self.task / timing.FILENAME).exists())
        self.assertEqual(before, (self.task / 'task.json').read_bytes())

    def test_symlink_log_cannot_overwrite_input(self):
        before = (self.task / 'task.json').read_bytes()
        (self.task / timing.FILENAME).symlink_to(self.task / 'task.json')
        self.assertEqual(self.invoke(timing.timed_cli('candidate_merge')(lambda: 8)), 8)
        self.assertEqual(before, (self.task / 'task.json').read_bytes())

    def test_three_real_cli_entrypoints_preserve_stdout_and_artifact_hashes(self):
        import build_report
        import finalize_assessment
        import validate_run
        task = {'assessment_policy': 'evidence-estimate-v1', 'specialty_workflow_revision': 'asset-scope-v1'}
        for name, value in {'task.json': task, 'assessment.json': {'assessment_policy': 'evidence-estimate-v1', 'status': 'incomplete'},
                            'evidence.json': {}, 'normalized-candidates.json': {}, 'search-plan.json': {}}.items():
            atomic_write_json(self.task / name, value)
        def digests():
            return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.task.glob('*.json')}
        before = digests()
        with patch('assessment_estimate.report_input_context', return_value=(self.task, task)), \
                patch('report_estimate.build_bundle') as build, patch('report_estimate.validate_run', return_value=[]) as validate, \
                patch('assessment_estimate.finalize', return_value={'status': 'incomplete'}) as finalize:
            for module, extra in ((build_report, []), (validate_run, []), (finalize_assessment, ['--first-review', str(self.root / 'first.json')])):
                plain, timed = io.StringIO(), io.StringIO()
                with patch('sys.argv', ['test', '--task-dir', str(self.task), *extra]):
                    with redirect_stdout(plain):
                        module.main.__wrapped__()
                    with redirect_stdout(timed):
                        module.main()
                self.assertEqual(plain.getvalue(), timed.getvalue())
            self.assertEqual((build.call_count, validate.call_count, finalize.call_count), (2, 2, 2))
        self.assertEqual(digests(), before)
        self.assertEqual([row['stage'] for row in self.rows()], ['report_build', 'report_validation', 'assessment_finalize'])

    def test_no_fcntl_platform_imports_all_five_clis_and_runs_without_logging(self):
        # A fresh process proves no already-imported POSIX module hides the
        # regression. Both lock backends absent is a supported best-effort miss.
        code = '''
import builtins, importlib, json, pathlib, sys
original_import = builtins.__import__
def without_locks(name, *args, **kwargs):
    if name in {'fcntl', 'msvcrt'}:
        raise ModuleNotFoundError('simulated unavailable native lock')
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_locks
sys.path.insert(0, sys.argv[1])
for name in ('build_report', 'validate_run', 'finalize_assessment', 'merge_candidates', 'annotate_materiality'):
    assert callable(importlib.import_module(name).main)
import runtime_timing
target = pathlib.Path(sys.argv[2])
sys.argv = ['test', '--task-dir', str(target)]
assert runtime_timing.timed_cli('candidate_merge')(lambda: 42)() == 42
assert not (target / runtime_timing.FILENAME).exists()
print('five imports and business return preserved')
'''
        before = (self.task / 'task.json').read_bytes()
        result = subprocess.run([sys.executable, '-c', code, str(Path(timing.__file__).parent),
                                 str(self.task)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'five imports and business return preserved')
        self.assertEqual(before, (self.task / 'task.json').read_bytes())

    def test_windows_lock_branch_appends_and_releases(self):
        import provider_utils
        backend = Mock(LK_NBLCK=1, LK_UNLCK=2)
        with patch.object(provider_utils, 'fcntl', None), patch.object(provider_utils, 'msvcrt', backend):
            self.assertEqual(self.invoke(timing.timed_cli('candidate_triage')(lambda: 9)), 9)
        self.assertEqual(self.rows()[0]['stage'], 'candidate_triage')
        self.assertEqual([call.args[1:] for call in backend.locking.call_args_list], [(1, 1), (2, 1)])


if __name__ == '__main__':
    unittest.main()
