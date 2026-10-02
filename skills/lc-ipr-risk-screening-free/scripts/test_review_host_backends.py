"""Isolation backends and per-session resume of the module review host (fake native CLI, no network)."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from common import load_json, sha256_json
import final_review
import module_review as mod
import review_isolation as ri


class FakeNative:
    """Stands in for ``report_review_host.run_native_logged``: writes a valid tool-free trace."""

    def __init__(self, fail_slots=()):
        self.calls, self.fail_slots = [], set(fail_slots)

    def __call__(self, command, prompt, workspace, trace_path, stderr_path, timeout):
        group, chain = trace_path.parent.name, trace_path.parent.parent.name
        self.calls.append(chain + "/" + group)
        session = "native-" + chain + "-" + group + "-" + str(len(self.calls))
        if group == "summary":
            digests = json.loads(re.search(r"module_review_digests=(\[.*?\])\n", prompt).group(1))
            raw = {"assessments": [], "future_applications": [], "enforcement_signals": [],
                   "module_review_digests": digests, "coverage_confidence_cap": "低",
                   "coverage_confidence_reasoning": "fixture",
                   "final_review_statement": {"overall": "o", "scope": "s", "limitations": "l"}}
        else:
            raw = {"assessments": [], "future_applications": [], "enforcement_signals": []}
        events = [{"type": "thread.started", "thread_id": session}, {"type": "turn.started"},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(raw)}}]
        if (chain + "/" + group) not in self.fail_slots:
            events.append({"type": "turn.completed"})
        trace_path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        if (chain + "/" + group) in self.fail_slots:
            raise ValueError("REPORT_REVIEW_HOST_TIMEOUT_NO_AUTOMATIC_RETRY")
        stdout = trace_path.read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0, pid=4242), stdout, ""


class HostBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task_dir = self.root / "task"
        self.task_dir.mkdir()
        self.task = {"task_id": "OFFLINE", "target_jurisdictions": ["US"], "review_policy_revision": final_review.REVISION,
                     "final_review_execution_revision": mod.REVISION, "assessment_revision": "known-findings-risk-v1",
                     "assessment_scenarios": [{"scenario_id": "S", "type": "product_entry"}], "product": {"title": "x"}}
        self.frozen = {"task": self.task, "evidence_digest": "DIGEST", "evidence": {}, "candidates": {},
                       "materiality_ledger": {}, "search_plan": {}}
        self.binary = self.root / "codex"
        self.binary.write_bytes(b"#!/bin/sh\necho codex-fixture 1.0\n")
        self.binary.chmod(0o755)

    def run_pair(self, output, isolation, native, *, resume=False):
        context = MagicMock()
        self.login, self.mac_login = MagicMock(), MagicMock()
        def build_review(task_dir, aggregate, execution, prepared_context=None):
            return {"review_context": {"session_id": execution["session_id"], "evidence_digest": "DIGEST",
                                       "execution": {"module_execution": execution["module_execution"]}}}
        patches = [
            patch("report_review_host.run_native_logged", native),
            patch("report_review_host.review_prompt", lambda packet, chain: "prompt-" + str(chain) + json.dumps(packet.get("module_scope", {}).get("module_id"))),
            patch("report_review_host._probe", return_value=[]),
            patch("macos_review_host.require_chatgpt_auth", self.mac_login),
            patch("review_isolation.login_status", self.login),
            patch("module_review._validate_module_judgment"),
            patch("record_independent_review.build_review", build_review),
            patch("final_review.pair_summary"),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        return mod.run_module_pair(self.task_dir, output, self.binary, self.frozen, {"ready": True}, context,
                                   timeout=30, max_parallel=6, resume_existing=resume, isolation=isolation)

    def test_tool_free_run_records_isolation_and_checks_login_once(self):
        output = self.root / "out"; output.mkdir()
        native = FakeNative()
        self.run_pair(output, ri.TOOL_FREE, native)
        self.assertEqual(len(native.calls), 8)
        self.assertEqual(self.login.call_count, 1)
        self.assertEqual(self.mac_login.call_count, 0)
        audit = load_json(output / "1" / "technical" / "audit.json")
        self.assertEqual(audit["isolation_method"], "tool_free_process")
        self.assertFalse(audit["kernel_read_boundary"])
        self.assertEqual(audit["controls"], [])
        self.assertNotIn("sandbox-exec", " ".join(audit["native_command"]))
        policy = output / "1" / "technical" / "isolation-policy.json"
        self.assertTrue(policy.is_file())
        ri.validate_policy(policy, audit)
        self.assertFalse((output / "1" / "technical" / "sandbox.sb").exists())
        receipt = load_json(output / "freeze-receipt.json")
        self.assertEqual(receipt["isolation"], "tool-free-process")
        self.assertNotIn("resume_attempts", receipt)

    def test_macos_backend_still_writes_a_sandbox_profile_and_no_isolation_fields(self):
        output = self.root / "out"; output.mkdir()
        native = FakeNative()
        self.run_pair(output, ri.MACOS, native)
        self.assertEqual(self.mac_login.call_count, 1)
        self.assertEqual(self.login.call_count, 0)
        directory = output / "2" / "expression"
        self.assertTrue((directory / "sandbox.sb").is_file())
        audit = load_json(directory / "audit.json")
        self.assertNotIn("isolation_method", audit)
        self.assertEqual(audit["native_command"][:2], ["/usr/bin/sandbox-exec", "-f"])
        self.assertNotIn("isolation", load_json(output / "freeze-receipt.json"))

    def test_resume_reruns_only_the_failed_session_and_records_the_attempt(self):
        output = self.root / "out"; output.mkdir()
        first = FakeNative(fail_slots={"1/technical"})
        with self.assertRaisesRegex(ValueError, "TIMEOUT"):
            self.run_pair(output, ri.TOOL_FREE, first)
        self.assertEqual(len(first.calls), 6)
        second = FakeNative()
        paths = self.run_pair(output, ri.TOOL_FREE, second, resume=True)
        self.assertEqual(sorted(second.calls), ["1/summary", "1/technical", "2/summary"])
        self.assertTrue((output / "1" / "technical.attempt-1" / "events.jsonl").is_file())
        receipt = load_json(output / "freeze-receipt.json")
        self.assertEqual(receipt["resume_attempts"], [{"slot": "1/technical", "archived_as": "1/technical.attempt-1"}])
        self.assertEqual(len(receipt["module_sessions"]["1"]), 3)
        self.assertEqual(len(paths), 2)

    def test_resume_never_mixes_isolation_backends_inside_a_retained_session(self):
        output = self.root / "out"; output.mkdir()
        first = FakeNative(fail_slots={"1/technical"})
        with self.assertRaises(ValueError):
            self.run_pair(output, ri.TOOL_FREE, first)
        with self.assertRaisesRegex(ValueError, "ISOLATION_BACKEND_CHANGED|RETAINED_HOST_FILES_MISSING"):
            self.run_pair(output, ri.MACOS, FakeNative(), resume=True)

    def test_parallel_limit_allows_six(self):
        jobs = [{"command": [str(i)], "prompt": "", "workspace": self.root, "trace_path": self.root / "t",
                 "stderr_path": self.root / "e"} for i in range(6)]
        with patch("report_review_host.run_native_logged", side_effect=lambda command, *a: command[0]):
            self.assertEqual(mod.run_jobs(jobs, 30, 6), [str(i) for i in range(6)])
            with self.assertRaisesRegex(ValueError, "MAX_PARALLEL_INVALID"):
                mod.run_jobs(jobs, 30, 7)


class TextEncodingTests(unittest.TestCase):
    def test_prompt_and_trace_use_utf8_regardless_of_locale(self):
        import report_review_host as host
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "echo.py"
            script.write_text("import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n", encoding="utf-8")
            proc, stdout, _ = host.run_native_logged([__import__("sys").executable, str(script)], "中文提示：专利 ✓", root,
                                                     root / "trace", root / "err", 30)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(stdout, "中文提示：专利 ✓")


if __name__ == "__main__":
    unittest.main()
