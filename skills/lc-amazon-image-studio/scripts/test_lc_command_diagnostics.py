"""CLI observation/loop protection on isolated synthetic manifests only."""
import argparse
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lc_image_pipeline as p
import lc_command_diagnostics as d
import lc_runtime_status as r


class CommandDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-command-diagnostics-fixture-")
        self.base = Path(self.temp.name)
        self.path = self.base / "project_manifest.json"
        from pipeline_test_support import create_v3_fixture, MAIN_ID, SECONDARY_ID
        self.m = create_v3_fixture(self.base)
        self.source = self.base / self.m["references"][0]["path"]
        self.m["jobs"][0]["id"], self.m["jobs"][1]["id"] = "a", "b"
        for detail in self.m["critical_details"]:
            detail["visibility"] = {"a": detail["visibility"][MAIN_ID], "b": detail["visibility"][SECONDARY_ID]}
        p.write_json(self.path, self.m)
        self.args = argparse.Namespace(command="plan", manifest=self.path, json=True, jobs=["a"])

    def tearDown(self):
        self.temp.cleanup()

    def observe(self, operation):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return d.run_observed_command(self.args, operation)

    def fail(self):
        self.args._command_error = "synthetic a layout failure"
        return 2

    def test_two_actual_failures_stop_third_repeat_and_restored_input_unlocks(self):
        self.assertEqual(self.observe(self.fail), 2)
        self.assertEqual(self.observe(self.fail), 2)
        current = p.read_json(self.path)
        self.assertEqual(current["jobs"], self.m["jobs"])
        self.assertEqual(len(r.active_diagnostics(current, self.base)), 1)
        with patch.object(d, "persist_observation", side_effect=AssertionError("refusal must not create an attempt")):
            self.assertEqual(self.observe(lambda: self.fail()), 2)
        self.source.write_bytes(b"restored different fixture source")
        self.assertEqual(r.active_diagnostics(p.read_json(self.path), self.base), [])
        ran = []
        self.assertEqual(self.observe(lambda: ran.append(True) or 0), 0)
        self.assertEqual(ran, [True])

    def test_failed_stage_paths_are_canonicalized_before_grouping(self):
        for name in ("first", "second"):
            def failure():
                self.args._command_error = f"Missing: {self.base}/.lc-transactions/tx-{name}/workspace/synthetic.png"
                return 2
            self.assertEqual(self.observe(failure), 2)
        record = r.active_diagnostics(p.read_json(self.path), self.base)[0]
        self.assertEqual(record["consecutive_count"], 2)
        self.assertNotIn(".lc-transactions", record["error"])

    def test_success_resets_streak_without_replacing_other_writer_changes(self):
        self.observe(self.fail)
        def success():
            current = p.read_json(self.path)
            current["jobs"][1]["status"] = "generated"
            p.write_json(self.path, current)
            return 0
        self.assertEqual(self.observe(success), 0)
        current = p.read_json(self.path)
        self.assertEqual(current["jobs"][1]["status"], "generated")
        self.assertEqual(current["runtime_diagnostics"]["command_failures"][-1]["consecutive_count"], 0)
        self.assertEqual(len(current["runtime_diagnostics"]["intervals"]), 2)

    def test_different_job_can_continue_while_one_scope_requires_diagnosis(self):
        self.observe(self.fail)
        self.observe(self.fail)
        self.args.jobs = ["b"]
        ran = []
        self.assertEqual(self.observe(lambda: ran.append(True) or 0), 0)
        self.assertEqual(ran, [True])

    def test_partial_batch_records_actual_failed_jobs(self):
        self.args.command = "review-prepare"
        self.args.jobs = ["a", "b"]
        def partial():
            self.args._command_result = {"errors": [{"job": "a", "error": "synthetic a overflow"}],
                                         "packets": [{"job": "b", "packet": "/synthetic/b.json"}]}
            return 0
        self.observe(partial)
        self.observe(partial)
        record = r.active_diagnostics(p.read_json(self.path), self.base)[0]
        self.assertEqual(record["jobs"], ["a"])
        self.assertEqual(record["consecutive_count"], 2)

    def test_status_does_not_read_write_or_lock_manifest(self):
        self.args.command = "status"
        with patch.object(d, "capture_context", side_effect=AssertionError("read-only status delegates directly")), \
                patch("lc_workflow.manifest_lock", side_effect=AssertionError("no lock")):
            self.assertEqual(d.run_observed_command(self.args, lambda: 0), 0)
        self.assertEqual(p.read_json(self.path), self.m)

    def test_runtime_repair_unlocks_diagnosis_without_project_or_review_changes(self):
        binary = self.base / "synthetic-node"
        with patch.dict("os.environ", {"LC_LAYOUT_NODE": str(binary)}), \
                patch("lc_layout.doctor", side_effect=AssertionError("runtime fingerprint must not launch doctor")), \
                patch("subprocess.check_output", side_effect=AssertionError("no runtime subprocess")):
            self.observe(self.fail)
            self.observe(self.fail)
            self.assertTrue(r.active_diagnostics(p.read_json(self.path), self.base))
            binary.write_bytes(b"synthetic restored node identity; never executed")
            self.assertEqual(r.active_diagnostics(p.read_json(self.path), self.base), [])
            self.assertEqual(self.observe(lambda: 0), 0)
        self.assertEqual(p.read_json(self.path)["jobs"], self.m["jobs"])

    def test_invalid_structure_backend_or_scope_keeps_original_bytes(self):
        for change in (lambda m: m.update(concurrency=99),
                       lambda m: m.update(generation_backend="retired_backend"),
                       lambda m: m["jobs"][0].update(product_layers=7)):
            candidate = copy.deepcopy(self.m)
            change(candidate)
            p.write_json(self.path, candidate)
            before = self.path.read_bytes()
            self.assertEqual(self.observe(self.fail), 2)
            self.assertEqual(self.path.read_bytes(), before)
        p.write_json(self.path, self.m)
        self.args.jobs = ["unknown"]
        before = self.path.read_bytes()
        self.assertEqual(self.observe(self.fail), 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_source_reappearance_changes_fingerprint(self):
        self.source.unlink()
        before = d.capture_context(self.args)
        first = d.input_fingerprint(before["manifest"], self.base, self.args.command,
            before["jobs"], before["parameters"], file_hashes=before["file_hashes"])
        self.source.write_bytes(b"recovered fixture")
        after = d.capture_context(self.args)
        second = d.input_fingerprint(after["manifest"], self.base, self.args.command,
            after["jobs"], after["parameters"], file_hashes=after["file_hashes"])
        self.assertNotEqual(first, second)

    def test_real_cli_records_failed_staged_commands_then_refuses_repeat_and_status_is_readonly(self):
        from pipeline_test_support import create_v3_fixture
        fixture = create_v3_fixture(self.base)
        (self.base / fixture["references"][0]["path"]).unlink()  # Valid schema; a recoverable missing real input.
        p.write_json(self.path, fixture)
        command = [sys.executable, str(Path(p.__file__)), "prepare", "--manifest", str(self.path), "--json"]
        for _ in range(2):
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertNotIn("REPEATED_COMMAND_DIAGNOSIS_REQUIRED", result.stdout)
        third = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(third.returncode, 2, third.stdout + third.stderr)
        self.assertIn("REPEATED_COMMAND_DIAGNOSIS_REQUIRED", third.stdout)
        current = p.read_json(self.path)
        self.assertEqual(current["jobs"], fixture["jobs"])
        self.assertEqual(len(current["runtime_diagnostics"]["command_failures"]), 2)
        before = {str(path): (path.stat().st_mtime_ns, p.sha256_file(path))
                  for path in self.base.rglob("*") if path.is_file()}
        status = subprocess.run([sys.executable, str(Path(p.__file__)), "status", "--manifest", str(self.path), "--json"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertTrue(json.loads(status.stdout)["ok"])
        after = {str(path): (path.stat().st_mtime_ns, p.sha256_file(path))
                 for path in self.base.rglob("*") if path.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
