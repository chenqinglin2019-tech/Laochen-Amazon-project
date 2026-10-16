"""Temporary execution ownership, including failure and retained-session recovery."""
from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import native_review_jobs as jobs
from common import atomic_write_json
from offline_test_support import isolated_test_environment


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ipr-workspace-tests-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scratch = self.root / 'owned temporary'; self.scratch.mkdir()
        self.task = self.root / 'task'; self.task.mkdir()
        self.output = self.root / 'review'; self.output.mkdir()
        self.binary = self.root / 'unused-native'; self.binary.write_bytes(b'never run')
        self.created = []
        original = tempfile.mkdtemp
        def create(suffix=None, prefix=None, dir=None):
            path = original(suffix=suffix, prefix=prefix, dir=self.scratch)
            if (prefix or '').startswith(('ipr-module-review-', 'ipr-review-control-')):
                self.created.append(Path(path))
            return path
        self.create = create
        mocked = patch.object(jobs.tempfile, 'mkdtemp', side_effect=create)
        self.mkdir = mocked.start(); self.addCleanup(mocked.stop)
        isolated = isolated_test_environment(); isolated.__enter__()
        self.addCleanup(isolated.__exit__, None, None, None)

    def factory(self, slots, **kwargs):
        return jobs.make_job_factory(self.task, self.output, self.binary,
            'macos-sandbox', slots, **kwargs)

    def assert_clean(self):
        self.assertTrue(all(not path.exists() for path in self.created), self.created)

    def test_default_slot_order_and_single_slot_control_are_preserved(self):
        _, workspaces = self.factory([('visual-slot', '0')])
        self.assertEqual(workspaces, self.created)
        self.assertEqual(len(workspaces), 2)
        self.assertTrue(workspaces[0].name.startswith('ipr-module-review-'))
        self.assertTrue(workspaces[1].name.startswith('ipr-review-control-'))
        jobs.cleanup_workspaces(workspaces)
        self.assert_clean()

    def test_partial_eager_and_lazy_allocation_failure_cleans_created_paths(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                calls = []
                def fail_second(*args, **kwargs):
                    calls.append(None)
                    if len(calls) == 2:
                        raise OSError('synthetic allocation failure')
                    return self.create(*args, **kwargs)
                with patch.object(jobs.tempfile, 'mkdtemp', side_effect=fail_second):
                    with self.assertRaisesRegex(OSError, 'allocation failure'):
                        make, workspaces = self.factory([(1, 'a'), (2, 'a')], resume_existing=resume)
                        make(1, 'a', {'task': {}}, {}, 'prompt')
                self.assert_clean()

    def test_control_allocation_failure_cleans_the_primary_workspace(self):
        def fail_control(*args, **kwargs):
            if kwargs['prefix'] == 'ipr-review-control-':
                raise OSError('synthetic control failure')
            return self.create(*args, **kwargs)
        with patch.object(jobs.tempfile, 'mkdtemp', side_effect=fail_control):
            with self.assertRaisesRegex(OSError, 'control failure'):
                self.factory([('visual-slot', '0')])
        self.assert_clean()

    def test_retained_factory_reads_original_files_without_allocating(self):
        packet, prompt = {'task': {}, 'evidence': {}}, 'retained prompt'
        directory = self.output / '1' / 'a'; directory.mkdir(parents=True)
        atomic_write_json(directory / 'packet.json', packet)
        for name, text in [('prompt.txt', prompt), ('sandbox.sb', 'retained profile'),
                           ('events.jsonl', 'retained events'), ('stderr.log', 'retained stderr')]:
            (directory / name).write_text(text, encoding='utf-8')
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        make, workspaces = self.factory([(1, 'a'), (2, 'a')], resume_existing=True)
        job = make(1, 'a', packet, {}, prompt, retained=True)
        self.assertEqual(workspaces, [])
        self.assertEqual(self.mkdir.call_count, 0)
        self.assertNotIn('workspace', job)
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_first_fresh_resume_allocates_every_peer_before_probe(self):
        make, workspaces = self.factory([(1, 'a'), (2, 'a')], resume_existing=True)
        checked = []
        def probe(binary, workspace, peer, task, output, *, blocked_peers):
            self.assertEqual(len(workspaces), 2)
            self.assertEqual(blocked_peers, [p for p in workspaces if p != workspace])
            self.assertTrue(peer.is_dir())
            checked.append(peer)
            return []
        try:
            with patch.object(jobs, '_probe', side_effect=probe), patch('macos_review_host.require_chatgpt_auth'):
                make(2, 'a', {'task': {}}, {}, 'fresh prompt')
            self.assertEqual(len(checked), 1)
        finally:
            jobs.cleanup_workspaces(workspaces)
        self.assert_clean()

    def test_cleanup_is_owned_idempotent_and_keeps_formal_audit(self):
        _, workspaces = self.factory([(1, 'a'), (2, 'a')])
        permanent = self.output / 'audit.json'; permanent.write_bytes(b'formal audit')
        jobs.cleanup_workspaces(workspaces)
        jobs.cleanup_workspaces(workspaces)
        self.assert_clean()
        self.assertEqual(permanent.read_bytes(), b'formal audit')

    def test_cleanup_failure_reports_without_masking_primary_error(self):
        _, workspaces = self.factory([(1, 'a'), (2, 'a')])
        output = StringIO()
        with redirect_stderr(output), patch.object(jobs.shutil, 'rmtree', side_effect=PermissionError('synthetic file in use')):
            with self.assertRaisesRegex(ValueError, 'primary failure'):
                try:
                    raise ValueError('primary failure')
                finally:
                    jobs.cleanup_workspaces(workspaces)
        failures = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([row['path'] for row in failures], list(map(str, workspaces)))
        self.assertTrue(all(row['code'] == 'NATIVE_REVIEW_WORKSPACE_CLEANUP_INCOMPLETE'
            and row['error_type'] == 'PermissionError' and row['reason'] == 'synthetic file in use'
            for row in failures))
        jobs.cleanup_workspaces(workspaces)
        self.assert_clean()

    def test_small_and_large_success_cleanup_and_completed_resume_allocates_nothing(self):
        from test_adaptive_review_host import HostFixture
        for kind in ('visual', 'seven-country-large'):
            with self.subTest(kind=kind):
                fixture = HostFixture(self.root / kind, kind=kind)
                fixture.run()
                self.assert_clean()
                before = {str(p): p.read_bytes() for p in fixture.output.rglob('*')
                          if p.is_file() and p.name in {'audit.json', 'events.jsonl'}}
                count, calls = len(self.created), len(fixture.calls)
                fixture.run(resume=True)
                self.assertEqual((len(self.created), len(fixture.calls)), (count, calls))
                self.assertEqual(before, {str(p): p.read_bytes() for p in fixture.output.rglob('*')
                    if p.is_file() and p.name in {'audit.json', 'events.jsonl'}})
                self.assert_clean()

    def test_failed_session_and_its_partial_resume_cleanup(self):
        from test_adaptive_review_host import HostFixture
        fixture = HostFixture(self.root / 'failed', fail_slot=('2', 'integrated'))
        with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'):
            fixture.run()
        self.assert_clean()
        fixture.run(resume=True)
        self.assertEqual(fixture.calls[2:], [('2', 'integrated')])
        self.assertTrue((fixture.output / '2/integrated.attempt-1/events.jsonl').is_file())
        self.assert_clean()

    def test_preparation_mkdir_image_write_and_validation_failure_cleanup(self):
        from test_adaptive_review_host import HostFixture
        for phase in ('preparation', 'mkdir', 'image', 'validation'):
            with self.subTest(phase=phase):
                fixture = HostFixture(self.root / phase, adaptive=phase != 'preparation')
                if phase == 'preparation':
                    fault = patch('module_review.attach_originals', side_effect=ValueError('preparation failure'))
                elif phase == 'validation':
                    fault = patch('final_review.pair_summary', side_effect=ValueError('validation failure'))
                else:
                    method = 'mkdir' if phase == 'mkdir' else 'write_bytes'
                    original = getattr(Path, method)
                    def fail(path, *args, **kwargs):
                        if (phase == 'mkdir' and path == fixture.output / '1/integrated'
                                or phase == 'image' and path.parent in self.created and path.suffix == '.png'):
                            raise OSError(phase + ' failure')
                        return original(path, *args, **kwargs)
                    fault = patch.object(Path, method, fail)
                with fault, self.assertRaisesRegex((OSError, ValueError), phase + ' failure'):
                    fixture.run()
                self.assert_clean()

    def test_cleanup_waits_for_other_running_worker_when_one_fails(self):
        from test_adaptive_review_host import HostFixture
        fixture = HostFixture(self.root / 'parallel')
        original = fixture.native
        active, finished = threading.Event(), threading.Event()
        def native(*args):
            trace = args[3]
            if trace.parent.parent.name == '1':
                self.assertTrue(active.wait(2))
                raise ValueError('synthetic worker failure')
            active.set()
            try:
                return original(*args)
            finally:
                finished.set()
        fixture.native = native
        cleanup = jobs.cleanup_workspaces
        def checked(workspaces):
            self.assertTrue(finished.is_set())
            cleanup(workspaces)
        with patch.object(jobs, 'cleanup_workspaces', side_effect=checked):
            with self.assertRaisesRegex(ValueError, 'worker failure'):
                fixture.run()
        self.assert_clean()

    def test_probe_and_login_failure_cleanup(self):
        from module_review import run_module_pair
        from test_adaptive_review_host import HostFixture
        for phase in ('probe', 'login'):
            with self.subTest(phase=phase):
                fixture = HostFixture(self.root / phase)
                with patch('report_review_host.run_native_logged', side_effect=fixture.native), \
                     patch.object(jobs, '_probe', side_effect=ValueError('probe failure') if phase == 'probe' else None,
                                  return_value=[]), \
                     patch('macos_review_host.require_chatgpt_auth',
                           side_effect=ValueError('login failure') if phase == 'login' else None), \
                     self.assertRaisesRegex(ValueError, phase + ' failure'):
                    run_module_pair(fixture.source, fixture.output, fixture.binary, fixture.frozen,
                        fixture.meta, fixture.context, timeout=10, isolation='macos-sandbox')
                self.assert_clean()

    def test_timeout_closes_actual_child_and_logs_before_workspace_cleanup(self):
        import sys
        from report_review_host import run_native_logged
        from test_adaptive_review_host import HostFixture
        from common import load_json
        fixture = HostFixture(self.root / 'timeout')
        closed = []
        def timeout_native(command, prompt, workspace, trace, stderr, timeout):
            try:
                return run_native_logged([sys.executable, '-c', 'import time; time.sleep(5)'],
                    '', workspace, trace, stderr, .1)
            finally:
                self.assertIsNotNone(load_json(trace.with_suffix('.execution.json'))['exit_code'])
                with trace.open('ab'), stderr.open('ab'):
                    closed.append(workspace)
        fixture.native = timeout_native
        cleanup = jobs.cleanup_workspaces
        def checked(workspaces):
            self.assertEqual(len(closed), 2)
            cleanup(workspaces)
        with patch.object(jobs, 'cleanup_workspaces', side_effect=checked):
            with self.assertRaisesRegex(ValueError, 'TIMEOUT_NO_AUTOMATIC_RETRY'):
                fixture.run()
        self.assert_clean()

    def test_visual_success_and_failure_reuse_cleanup_after_workers(self):
        from test_visual_triage_host import VisualHostTests
        fixture = VisualHostTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.fail_ids = {fixture.entries()[0]['candidate_id']}
        fixture.run_host()
        self.assert_clean()
        self.assertTrue((fixture.root / 'visual-triage/last-run.json').is_file())


if __name__ == '__main__':
    unittest.main()
