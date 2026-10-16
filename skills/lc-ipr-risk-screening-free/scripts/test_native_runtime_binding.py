"""Offline runtime identity/recovery tests; never execute native CLI or login."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_file
from execution_efficiency import REVISION
from macos_review_host import sandbox_profile
from native_runtime_binding import (FILENAME, ensure_fresh_runtime, retained_runtime, resume_runtime)
from review_isolation import MACOS, TOOL_FREE


class RuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ipr-runtime-binding-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / 'review'; self.output.mkdir()
        self.binary = self.root / 'old-native'; self.binary.write_bytes(b'offline native original')
        self.task = {'execution_efficiency_revision': REVISION}
        self.environment = patch.dict(os.environ, {'LC_IPR_CODEX_BINARY': ''})
        self.environment.start(); self.addCleanup(self.environment.stop)

    def mac_profile(self, binary=None):
        directory = self.output / '1' / 'integrated'; directory.mkdir(parents=True)
        profile = directory / 'sandbox.sb'
        profile.write_text(sandbox_profile(binary or self.binary, []), encoding='utf-8')
        return profile

    def test_new_binding_keeps_exact_path_hash_and_backend_without_changing_task(self):
        before = dict(self.task)
        ensure_fresh_runtime(self.output, self.binary, MACOS, self.task)
        value = load_json(self.output / FILENAME)
        self.assertEqual(value['binary'], str(self.binary))
        self.assertEqual(value['binary_sha256'], sha256_file(self.binary))
        self.assertEqual(value['backend'], MACOS)
        self.assertEqual(before, self.task)

    def test_legacy_execution_gets_no_retroactive_binding(self):
        ensure_fresh_runtime(self.output, self.binary, MACOS, {'execution_efficiency_revision': 'execution-efficiency-v1'})
        self.assertFalse((self.output / FILENAME).exists())
        self.mac_profile()
        recorded = retained_runtime(self.output)
        self.assertIsNone(recorded['binary_sha256'])
        ensure_fresh_runtime(self.output, self.binary, MACOS, {}, resume_existing=True)
        self.assertFalse((self.output / FILENAME).exists())

    def test_resume_uses_old_path_without_discovery_or_capability_probe(self):
        ensure_fresh_runtime(self.output, self.binary, MACOS, self.task)
        with patch('review_isolation.resolve_codex_binary', side_effect=AssertionError('discovery forbidden')), \
             patch('native_runtime_discovery.inspect_capability', side_effect=AssertionError('probe forbidden')):
            self.assertEqual(resume_runtime(self.output), (self.binary, MACOS))

    def test_missing_binary_does_not_prevent_reading_retained_runtime_but_prevents_new_slot(self):
        ensure_fresh_runtime(self.output, self.binary, MACOS, self.task)
        self.binary.unlink()
        self.assertEqual(resume_runtime(self.output), (self.binary, MACOS))
        with self.assertRaisesRegex(ValueError, 'RUNTIME_UNAVAILABLE'):
            ensure_fresh_runtime(self.output, self.binary, MACOS, self.task, resume_existing=True)

    def test_changed_bytes_or_explicit_path_or_backend_rejected(self):
        ensure_fresh_runtime(self.output, self.binary, MACOS, self.task)
        other = self.root / 'new-native'; other.write_bytes(self.binary.read_bytes())
        with self.assertRaisesRegex(ValueError, 'RUNTIME_CHANGED'):
            resume_runtime(self.output, other)
        with self.assertRaisesRegex(ValueError, 'ISOLATION_BACKEND_CHANGED'):
            resume_runtime(self.output, requested=TOOL_FREE)
        self.binary.write_bytes(b'updated cli bytes')
        with self.assertRaisesRegex(ValueError, 'RUNTIME_CHANGED'):
            ensure_fresh_runtime(self.output, self.binary, MACOS, self.task, resume_existing=True)

    def test_unknown_legacy_runtime_never_picks_automatic_or_explicit_replacement(self):
        with patch('native_runtime_binding.select_backend', return_value=MACOS):
            self.assertEqual(resume_runtime(self.output, self.binary), (None, MACOS))
        with self.assertRaisesRegex(ValueError, 'RUNTIME_UNCONFIRMED'):
            ensure_fresh_runtime(self.output, self.binary, MACOS, {}, resume_existing=True)

    def test_conflicting_profile_or_changed_signed_profile_rejected(self):
        ensure_fresh_runtime(self.output, self.binary, MACOS, self.task)
        other = self.root / 'other-native'; other.write_bytes(b'other')
        profile = self.mac_profile(other)
        with self.assertRaisesRegex(ValueError, 'RUNTIME_CONFLICT'):
            retained_runtime(self.output)
        atomic_write_json(profile.parent / 'audit.json', {'profile_sha256': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'RETAINED_AUDIT_CHANGED'):
            retained_runtime(self.output)

    def test_windows_policy_preserves_existing_binary_hash(self):
        directory = self.output / '1' / 'technical'; directory.mkdir(parents=True)
        atomic_write_json(directory / 'isolation-policy.json', {'codex_binary': str(self.binary),
            'codex_binary_sha256': sha256_file(self.binary)})
        self.assertEqual(retained_runtime(self.output), {'binary': str(self.binary),
            'binary_sha256': sha256_file(self.binary), 'backend': TOOL_FREE})

    def test_completed_integrated_slots_recover_without_existing_cli_and_keep_audits(self):
        from test_adaptive_review_host import HostFixture
        from offline_test_support import isolated_test_environment
        with isolated_test_environment():
            fixture = HostFixture(self.root / 'host')
            fixture.run()
            audit = fixture.output / '1' / 'integrated' / 'audit.json'
            trace = audit.parent / 'events.jsonl'
            previous = (audit.read_bytes(), trace.read_bytes(), len(fixture.calls))
            fixture.binary.unlink()
            fixture.run(resume=True)
            self.assertEqual(previous, (audit.read_bytes(), trace.read_bytes(), len(fixture.calls)))

    def test_failed_resume_rejects_updated_cli_before_touching_previous_logs(self):
        from test_adaptive_review_host import HostFixture
        from offline_test_support import isolated_test_environment
        with isolated_test_environment():
            fixture = HostFixture(self.root / 'failed-host', fail_slot=('2', 'integrated'))
            with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'):
                fixture.run()
            first = fixture.output / '1' / 'integrated'
            second = fixture.output / '2' / 'integrated'
            before = {str(path): path.read_bytes() for directory in (first, second)
                      for path in directory.iterdir() if path.is_file()}
            calls = list(fixture.calls)
            fixture.binary.write_bytes(b'new CLI update installed')
            with self.assertRaisesRegex(ValueError, 'RUNTIME_CHANGED'):
                fixture.run(resume=True)
            self.assertEqual(calls, fixture.calls)
            self.assertEqual(before, {str(path): path.read_bytes() for directory in (first, second)
                                     for path in directory.iterdir() if path.is_file()})
            self.assertFalse((fixture.output / '2' / 'integrated.attempt-1').exists())


if __name__ == '__main__':
    unittest.main()
