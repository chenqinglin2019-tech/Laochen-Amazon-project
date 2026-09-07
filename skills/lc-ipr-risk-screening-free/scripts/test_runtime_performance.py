"""Offline scheduling, resumption, and bounded-failure regression tests."""
import json
import subprocess
import tempfile
import threading
import time
import unittest
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json, now_iso, sha256_file, sha256_json
import test_workflow_v24
from workflow_v24 import generate_plan, append_next_pages
import runtime_v24 as runtime
import run_browser_plan as browser


class SchedulingTests(unittest.TestCase):
    setUp = test_workflow_v24.WorkflowTests.setUp
    tearDown = test_workflow_v24.WorkflowTests.tearDown

    def test_deferred_owner_terms_reach_later_wave_without_rehashing(self):
        generate_plan(self.path)
        atomic_write_json(self.path / "normalized-candidates.json", {"patents": [
            {"candidate_id": f"C{i}", "material": True, "owner": f"Unique Owner {i}"} for i in range(5)]})
        first = generate_plan(self.path, expand=True)
        owners = lambda plan: {r["q"] for r in plan["queries"]["epo_ops"] if r.get("search_dimension") == "owner" and r["jurisdiction"] == "US" and r["right_type"] == "patent"}
        self.assertEqual(len(owners(first)), 3)
        self.assertGreater(first["term_counts"]["deferred_routes"], 0)
        hashes = {r["query_id"]: sha256_json(r) for rows in first["queries"].values() for r in rows}
        second = generate_plan(self.path, expand=True)
        self.assertEqual(len(owners(second)), 5)
        self.assertTrue(all(sha256_json(r) == hashes.get(r["query_id"], sha256_json(r)) for rows in second["queries"].values() for r in rows))
        self.assertEqual(second["queries"], generate_plan(self.path, expand=True)["queries"])

    def test_missing_credentials_resume_without_repeated_failure_evidence(self):
        generate_plan(self.path)
        with patch("runtime_v24.credential", return_value=""), patch("runtime_v24.subprocess.run") as network:
            first = runtime.execute_api_plan(self.path)
            count = len(load_json(self.path / "evidence.json")["source_runs"])
            second = runtime.execute_api_plan(self.path)
        network.assert_not_called()
        self.assertEqual(len(load_json(self.path / "evidence.json")["source_runs"]), count)
        self.assertEqual(len(first["results"]), second["counts"]["blocked_reused"])

    def test_task_lock_prevents_parallel_dispatch(self):
        with runtime.api_execution_lock(self.path):
            with self.assertRaisesRegex(ValueError, "API_EXECUTION_ALREADY_RUNNING"):
                runtime.execute_api_plan(self.path)

    def test_api_lanes_are_bounded_and_forward_one_deadline(self):
        plan = generate_plan(self.path)
        lookup = {r["query_id"]: (p, r) for p, rows in plan["queries"].items() for r in rows}
        mutex, active, maxima = threading.Lock(), {}, {"global": 0}
        barrier = threading.Barrier(3)
        first_lanes = set()
        def execute(command, **kwargs):
            provider, query_id = command
            row = lookup[query_id][1]
            lane = runtime._lane(provider)
            with mutex:
                active[lane] = active.get(lane, 0) + 1
                maxima[lane] = max(maxima.get(lane, 0), active[lane])
                maxima["global"] = max(maxima["global"], sum(active.values()))
                first = lane not in first_lanes
                first_lanes.add(lane)
            if first and len(first_lanes) <= 3:
                barrier.wait(timeout=5)
            deadline = float(kwargs["env"]["LC_IPR_OPERATION_DEADLINE_EPOCH"])
            self.assertGreater(deadline, time.time())
            self.assertLessEqual(kwargs["timeout"], 180)
            runtime.record_gap(self.path, provider, row, "OFFLINE_EXECUTION", "mocked provider result")
            with mutex:
                active[lane] -= 1
            return subprocess.CompletedProcess(command, 2, json.dumps({"status": "access_limited", "error_code": "OFFLINE_EXECUTION"}), "")
        caps = [{"provider": p, "executable": True} for p in plan["queries"] if p in runtime.API_CLIENTS]
        with patch("runtime_v24.capabilities", return_value=caps), patch("run_api_plan.command_for", side_effect=lambda root, task, p, r: [p, r["query_id"]]), patch("runtime_v24.subprocess.run", side_effect=execute):
            result = runtime.execute_api_plan(self.path, max_workers=3)
        self.assertEqual(result["workers"], 3)
        self.assertEqual(maxima["global"], 3)
        self.assertTrue(all(value == 1 for key, value in maxima.items() if key != "global"))
        self.assertTrue((self.path / "api-attempts.jsonl").is_file())

    def test_static_browser_failure_is_reused_until_implementation_changes(self):
        generate_plan(self.path)
        calls = []
        def execute(command, timeout=180):
            calls.append(command)
            return {"executor_available": False, "status": "access_limited", "error_code": "AUTOMATION_NOT_VALIDATED", "detail": "offline fixture"}
        first = browser.execute_plan(self.path, runner=execute)
        self.assertTrue(calls)
        count = len(load_json(self.path / "evidence.json")["source_runs"])
        calls.clear()
        second = browser.execute_plan(self.path, runner=execute)
        self.assertFalse(calls)
        self.assertEqual(len(load_json(self.path / "evidence.json")["source_runs"]), count)
        self.assertTrue(all(row["dispatch"] == "blocked_reused" for row in second["queries"]))
        with patch("run_browser_plan.sha256_file", return_value="changed"):
            browser.execute_plan(self.path, runner=execute)
        self.assertTrue(calls)

    def test_metered_repair_claim_is_persisted_and_reused_after_uncertain_attempt(self):
        plan = generate_plan(self.path)
        row = plan["queries"]["serpapi_google_patents"][0]
        evidence = load_json(self.path / "evidence.json")
        evidence["source_runs"] = [{"run_id": "OLD", "provider": "serpapi_google_patents", "query_id": row["query_id"], "status": "success", "plan_entry_sha256": sha256_json(row), "finished_at": now_iso(), "raw_paths": ["missing.json"], "payload_digest": "missing"}]
        atomic_write_json(self.path / "evidence.json", evidence)
        observed = []
        def execute(command, **kwargs):
            if command[1] == row["query_id"]:
                observed.append(command[command.index("--attempt-id") + 1])
                claims = load_json(self.path / "api-retry-claims.json")
                self.assertIn(observed[-1], claims["attempts"])
            return subprocess.CompletedProcess(command, 2, '{"status":"access_limited","error_code":"OFFLINE_UNKNOWN"}', "")
        with patch("runtime_v24.capabilities", return_value=[{"provider": "serpapi_google_patents", "executable": True}]), patch("run_api_plan.command_for", side_effect=lambda root, task, p, r: [p, r["query_id"]]), patch("runtime_v24.subprocess.run", side_effect=execute):
            runtime.execute_api_plan(self.path)
            runtime.execute_api_plan(self.path)
        self.assertEqual(len(observed), 2)
        self.assertEqual(observed[0], observed[1])

    def test_validated_capture_error_fills_incomplete_cli_summary(self):
        plan = generate_plan(self.path)
        row = plan["queries"]["uspto_patent_browser"][0]
        plan["queries"] = {"uspto_patent_browser": [row]}
        atomic_write_json(self.path / "search-plan.json", plan)
        capture_path = self.path / "capture.json"
        atomic_write_json(capture_path, {"status": "access_limited", "error_code": "AUTOMATIC_QUERY_PRE_SUBMIT_FAILED", "detail": "input mismatch", "phase": "prepare_input", "submission_state": "not_submitted"})
        def execute(command, timeout=180):
            if "automation-capability" in command:
                return {"executor_available": True}
            if "run-planned-query" in command:
                return {"status": "access_limited", "capture_path": str(capture_path)}
            return {"status": "success", "recorded_status": "access_limited"}
        with patch("run_browser_plan.validate_browser_execution") as validate:
            report = browser.execute_plan(self.path, runner=execute)
        validate.assert_called_once()
        result = report["queries"][0]
        self.assertEqual(result["error_code"], "AUTOMATIC_QUERY_PRE_SUBMIT_FAILED")
        self.assertEqual(result["detail"], "input mismatch")
        self.assertEqual(result["submission_state"], "not_submitted")

    def test_page_limit_remains_explicit_gap(self):
        plan = generate_plan(self.path)
        row = plan["queries"]["epo_ops"][0]
        row["range"] = "176-200"
        evidence = load_json(self.path / "evidence.json")
        evidence["source_runs"] = [{"provider": "epo_ops", "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row), "status": "success", "metadata": {"search_coverage": {"total_hits": 201, "retrieved_hits": 25, "schema_valid": True}}}]
        atomic_write_json(self.path / "evidence.json", evidence)
        append_next_pages(self.path, plan)
        self.assertEqual(plan["pagination_gaps"][0]["code"], "PAGE_LIMIT_REACHED")


class IntegrityTests(unittest.TestCase):
    def test_raw_and_declared_document_integrity_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, document = root / "response.json", root / "figure.png"
            raw.write_bytes(b"{}")
            document.write_bytes(b"fixture")
            run = {"run_id": "R1", "raw_paths": [str(raw)], "payload_digest": sha256_file(raw)}
            evidence = {"collections": {"patents": [{"source_run_id": "R1", "payload": {"path": str(document), "sha256": sha256_file(document), "bytes": 7}}]}}
            self.assertTrue(runtime.source_files_complete(root, evidence, run))
            self.assertTrue(runtime.source_files_complete(root, {}, {**run, "raw_paths": [raw.name]}))
            self.assertFalse(runtime.source_files_complete(root, {}, {**run, "raw_paths": [str(raw), str(raw)]}))
            document.write_bytes(b"changed")
            self.assertFalse(runtime.source_files_complete(root, evidence, run))
            self.assertFalse(runtime.source_files_complete(root, {}, {"payload_digest": "missing"}))
            raw.unlink()
            self.assertFalse(runtime.source_files_complete(root, evidence, run))

    def test_dynamic_records_expire_and_static_publications_keep_their_original_date(self):
        old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        self.assertFalse(runtime.source_fresh({"provider": "epo_ops", "finished_at": old}))
        self.assertTrue(runtime.source_fresh({"provider": "epo_ops", "finished_at": now_iso()}))
        self.assertTrue(runtime.source_fresh({"provider": "epo_publication_server", "operation": "document_retrieval", "finished_at": old}))
        self.assertFalse(runtime.source_fresh({"provider": "epo_ops", "finished_at": "invalid"}))

    def test_windows_lock_uses_nonblocking_byte_lock_and_releases_it(self):
        from execution_lock import execution_lock
        from unittest.mock import Mock
        locking = Mock()
        api = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("execution_lock.os.name", "nt"), patch.dict("sys.modules", {"msvcrt": api}):
                with execution_lock(root, "api"):
                    self.assertEqual(locking.call_args.args[1:], (1, 1))
                self.assertEqual(locking.call_args.args[1:], (2, 1))
        self.assertEqual(locking.call_count, 2)

    def test_browser_nonzero_exit_cannot_claim_success(self):
        with patch("run_browser_plan.subprocess.run", return_value=subprocess.CompletedProcess([], 2, '{"status":"success"}', "")):
            self.assertEqual(browser.run_process([])["error_code"], "BROWSER_EXIT_STATUS_MISMATCH")


if __name__ == "__main__":
    unittest.main()
