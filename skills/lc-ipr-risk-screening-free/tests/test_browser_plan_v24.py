"""Offline scheduler checks. These fixtures never become runtime acceptance evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_browser_plan as scheduler
from common import sha256_file
from record_browser_execution import canonical_digest
import test_browser_execution_v24 as execution_tests


class BrowserPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.task = {"schema_version": "2.4-free", "task_id": "T1"}
        (self.root / "task.json").write_text(json.dumps(self.task))
        (self.root / "evidence.json").write_text(json.dumps({**self.task, "source_runs": [], "collections": {}}))
        self.rows = {
            "uspto_tmsearch_browser": [self.entry("Q1", "trademark_word", "trademark_recall"), self.entry("Q2", "trademark_word", "trademark_recall")],
            "uspto_patent_browser": [self.entry("Q3", "patent", "patent_recall")],
            "tmview_browser": [self.entry("Q4", "trademark_word", "trademark_recall", "EU")],
        }
        self.write_plan()
        self.patches = [patch.object(scheduler, "assert_active_free_policy"), patch.object(scheduler, "plan_free_policy_matches_task", return_value=True),
                        patch.object(scheduler, "authorize_exact_plan_execution"), patch.object(scheduler, "record_failure", return_value="SRC-test"),
                        patch.object(scheduler.shutil, "which", return_value="node")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    @staticmethod
    def entry(query_id, right, operation, cc="US"):
        return {"query_id": query_id, "q": "TEST", "filters": {"field": "brand" if right.startswith("trademark") else "product", "language": "en"},
                "jurisdiction": cc, "right_type": right, "operation": operation, "wave": 1, "execute_by_default": True}

    def write_plan(self):
        (self.root / "search-plan.json").write_text(json.dumps({**self.task, "queries": self.rows}))

    def test_challenge_pauses_only_provider_and_other_sources_continue(self):
        executed = []
        def runner(command, timeout=180):
            if "automation-capability" in command:
                provider = command[command.index("--provider") + 1]
                return {"executor_available": provider != "tmview_browser", "error_code": "AUTOMATION_PROHIBITED"}
            query_id = command[command.index("--query-id") + 1]
            executed.append(query_id)
            self.assertIn("--acceptance-probe", command)
            return {"status": "needs_user_action" if query_id == "Q1" else "access_limited", "detail": "login required"}
        report = scheduler.execute_plan(self.root, 1, runner=runner)
        self.assertEqual(executed, ["Q1", "Q3"])
        self.assertEqual([r["status"] for r in report["queries"]], ["needs_user_action", "needs_user_action", "access_limited", "access_limited"])
        self.assertEqual(report["required_user_actions"], [{"provider": "uspto_tmsearch_browser", "actions": ["login", "captcha", "mfa", "consent", "qr"], "business_actions_by": "agent"}])
        self.assertTrue((self.root / "browser-execution-status.json").is_file())

    def test_wave_filter_and_success_without_capture_cannot_complete(self):
        self.rows["uspto_tmsearch_browser"][1]["wave"] = 2
        self.write_plan()
        def runner(command, timeout=180):
            return {"executor_available": True} if "automation-capability" in command else {"status": "success"}
        report = scheduler.execute_plan(self.root, 2, runner=runner)
        self.assertEqual(len(report["queries"]), 1)
        self.assertEqual(report["queries"][0]["error_code"], "BROWSER_ROW_FAILED")
        self.assertIn("lacks a plan-bound capture", report["queries"][0]["detail"])

    def test_rate_limit_pauses_provider_across_runs_without_consuming_partial_resume(self):
        self.rows = {"uspto_patent_browser": [self.entry("Q3", "patent", "patent_recall"), self.entry("Q5", "patent", "patent_recall")],
                     "uspto_tmsearch_browser": [self.entry("Q1", "trademark_word", "trademark_recall")]}
        self.write_plan()
        executed = []
        def runner(command, timeout=180):
            if "automation-capability" in command:
                return {"executor_available": True}
            query_id = command[command.index("--query-id") + 1]
            executed.append(query_id)
            return {"status": "access_limited", "error_code": "BROWSER_RATE_LIMITED" if query_id == "Q3" else "TEST_UNAVAILABLE"}
        report = scheduler.execute_plan(self.root, runner=runner)
        self.assertEqual(executed, ["Q3", "Q1"])
        self.assertEqual(report["provider_pauses"]["uspto_patent_browser"]["error_code"], "BROWSER_RATE_LIMITED")
        self.assertEqual(report["queries"][1]["dispatch"], "rate_limit_deferred")
        self.assertEqual(report["queries"][1]["submission_state"], "not_submitted")
        self.assertEqual(report["required_user_actions"], [])
        report["queries"][1].update(status="incomplete", partial_resume_attempts=0)
        (self.root / "browser-execution-status.json").write_text(json.dumps(report))
        again = scheduler.execute_plan(self.root, query_id_filter="Q5", runner=lambda *args: self.fail("cooldown must not dispatch"))
        self.assertEqual(again["queries"][1]["partial_resume_attempts"], 0)
        self.assertEqual(again["queries"][1]["status"], "incomplete")

    def test_exact_query_filter_uses_normal_execution_and_rejects_unknown(self):
        executed = []
        def runner(command, timeout=180):
            if "automation-capability" in command:
                return {"executor_available": True}
            executed.append(command[command.index("--query-id") + 1])
            return {"status": "failed", "error_code": "TEST_FAILURE"}
        report = scheduler.execute_plan(self.root, query_id_filter="Q3", runner=runner)
        self.assertEqual(executed, ["Q3"])
        self.assertEqual(report["queries"][0]["status"], "failed")
        with self.assertRaisesRegex(ValueError, "exact browser row"):
            scheduler.execute_plan(self.root, query_id_filter="UNKNOWN", runner=runner)

    def test_batch_exact_ids_execute_once_in_plan_order_and_preserve_individual_attempts(self):
        executed = []
        def runner(command, timeout=180):
            if "automation-capability" in command:
                return {"executor_available": True}
            executed.append(command[command.index("--query-id") + 1])
            return {"status": "failed", "error_code": "TEST_FAILURE"}
        with patch.object(scheduler, "reconcile_scenario_actions", wraps=scheduler.reconcile_scenario_actions) as reconcile:
            report = scheduler.execute_plan(self.root, query_ids_filter=["Q3", "Q1"], runner=runner)
            self.assertLessEqual(reconcile.call_count, 1)
        self.assertEqual(executed, ["Q1", "Q3"])
        attempts = [json.loads(line) for line in (self.root / "browser-attempts.jsonl").read_text().splitlines()]
        self.assertEqual([r["query_id"] for r in attempts], executed)
        self.assertTrue(all(r["plan_entry_sha256"] and r["elapsed_ms"] >= 0 for r in attempts))
        self.assertGreaterEqual(report["dispatcher_elapsed_ms"], report["initialization_elapsed_ms"])

    def test_batch_rejects_duplicates_unknown_ids_and_mixed_single_filter(self):
        for ids, single in (([], ""), (["Q1", "Q1"], ""), (["Q1", "UNKNOWN"], ""), (["Q1"], "Q3")):
            with self.subTest(ids=ids, single=single), self.assertRaisesRegex(ValueError, "exact browser row"):
                scheduler.execute_plan(self.root, query_ids_filter=ids, query_id_filter=single,
                    runner=lambda *args: self.fail("Invalid batch dispatched"))

    def test_batch_observes_cancellation_created_between_rows(self):
        self.task["screening_revision"] = "recall-integrity-v1"
        (self.root / "task.json").write_text(json.dumps(self.task))
        self.write_plan()
        executed = []
        def runner(command, timeout=180):
            if "automation-capability" in command:
                return {"executor_available": True}
            qid = command[command.index("--query-id") + 1]
            executed.append(qid)
            plan = json.loads((self.root / "search-plan.json").read_text())
            plan["execution_dispositions"] = [{"query_id": "Q2", "status": "cancelled", "reason": "New decision",
                "plan_entry_sha256": canonical_digest(self.rows["uspto_tmsearch_browser"][1])}]
            (self.root / "search-plan.json").write_text(json.dumps(plan))
            return {"status": "failed", "error_code": "TEST_FAILURE"}
        result = scheduler.execute_plan(self.root, query_ids_filter=["Q1", "Q2"], runner=runner)
        self.assertEqual(executed, ["Q1"])
        row = next(r for r in result["queries"] if r["query_id"] == "Q2")
        self.assertEqual(row["dispatch"], "cancelled")
        self.assertEqual(row["submission_state"], "not_submitted")

    def test_decoded_batch_inputs_use_bytes_not_mtime(self):
        import os
        path = self.root / "task.json"
        stat = path.stat()
        cache = scheduler._BatchInputs(self.root)
        self.assertEqual(cache.read("task.json")["task_id"], "T1")
        path.write_text(json.dumps({**self.task, "task_id": "T2"}))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(cache.read("task.json")["task_id"], "T2")

    def test_partial_success_rate_limit_preserves_hits_and_pauses_rest_of_batch(self):
        self.task["screening_revision"] = "recall-integrity-v1"
        (self.root / "task.json").write_text(json.dumps(self.task))
        self.rows = {"uspto_patent_browser": [self.entry("Q3", "patent", "patent_recall"), self.entry("Q5", "patent", "patent_recall")]}
        self.write_plan()
        capture = self.root / "partial-rate-limit.json"
        capture.write_text(json.dumps({"query_id": "Q3", "status": "success", "candidates": [{"publication_number": "US11111111B2"}],
            "result_coverage": {"retrieved_hits": 1, "total_hits": 2, "truncated": True,
                                "stop_reason": "BROWSER_RATE_LIMITED"}}))
        executed = []
        def runner(command, timeout=180):
            if "automation-capability" in command:
                return {"executor_available": True}
            if "run-planned-query" in command:
                executed.append(command[command.index("--query-id") + 1])
                return {"status": "success", "capture_path": str(capture)}
            return {"status": "success", "recorded_status": "success"}
        with patch.object(scheduler, "validate_browser_execution", return_value={}):
            result = scheduler.execute_plan(self.root, query_ids_filter=["Q3", "Q5"], runner=runner)
        self.assertEqual(executed, ["Q3"])
        rows = {row["query_id"]: row for row in result["queries"]}
        self.assertEqual(rows["Q3"]["status"], "incomplete")
        self.assertEqual(rows["Q3"]["capture_status"], "success")
        self.assertEqual(rows["Q3"]["result_coverage"]["retrieved_hits"], 1)
        self.assertEqual(rows["Q5"]["dispatch"], "rate_limit_deferred")
        self.assertEqual(result["provider_pauses"]["uspto_patent_browser"]["error_code"], "BROWSER_RATE_LIMITED")

    def test_only_hash_bound_explicit_cancellation_skips_dispatch_without_success(self):
        self.task["screening_revision"] = "recall-integrity-v1"
        (self.root / "task.json").write_text(json.dumps(self.task))
        self.write_plan()
        plan = json.loads((self.root / "search-plan.json").read_text())
        plan["execution_dispositions"] = [{"query_id": "Q3", "status": "cancelled", "reason": "Design class does not describe utility claims",
                                            "plan_entry_sha256": canonical_digest(self.rows["uspto_patent_browser"][0])}]
        (self.root / "search-plan.json").write_text(json.dumps(plan))
        report = scheduler.execute_plan(self.root, query_id_filter="Q3", runner=lambda *args: self.fail("cancelled query must not dispatch"))
        self.assertEqual(report["queries"][0]["status"], "cancelled")
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["queries"][0]["submission_state"], "not_submitted")
        plan["execution_dispositions"][0]["plan_entry_sha256"] = "stale"
        (self.root / "search-plan.json").write_text(json.dumps(plan))
        calls = []
        def runner(command, timeout=180):
            calls.append(command)
            return {"executor_available": False, "error_code": "AUTOMATION_NOT_VALIDATED"}
        report = scheduler.execute_plan(self.root, query_id_filter="Q3", runner=runner)
        self.assertTrue(calls)
        self.assertEqual(report["queries"][0]["status"], "access_limited")

    def test_foreign_task_evidence_is_rejected_before_dispatch(self):
        (self.root / "evidence.json").write_text(json.dumps({**self.task, "task_id": "OTHER", "source_runs": []}))
        with self.assertRaisesRegex(ValueError, "BROWSER_EVIDENCE_TASK_MISMATCH"):
            scheduler.execute_plan(self.root, runner=lambda *args: self.fail("foreign evidence must not dispatch"))

    def test_internal_route_error_is_recorded_as_failed_before_submission(self):
        self.rows = {"uspto_patent_browser": [self.entry("BAD", "design", "patent_recall")]}
        self.write_plan()
        def runner(command, timeout=180):
            self.assertIn("automation-capability", command)
            return {"executor_available": False, "error_code": "INTERNAL_ROUTE_CONTRACT_ERROR", "detail": "design requires design_recall"}
        report = scheduler.execute_plan(self.root, runner=runner)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["queries"][0]["status"], "failed")
        self.assertEqual(report["queries"][0]["submission_state"], "not_submitted")

    def test_process_timeout_and_secret_redaction(self):
        with patch.object(scheduler.subprocess, "run", side_effect=subprocess.TimeoutExpired("node", 1)):
            self.assertEqual(scheduler.run_process(["node"])["error_code"], "BROWSER_EXECUTION_TIMEOUT")
        with patch.object(scheduler.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "Authorization: Bearer secret-value")):
            self.assertNotIn("secret-value", scheduler.run_process(["node"])["detail"])

    def test_all_us_recorder_routes_are_explicit(self):
        for provider, operation, expected in [("uspto_tmsearch_browser", "trademark_recall", "record_uspto_tmsearch_browser_result.py"),
                                               ("uspto_patent_browser", "design_recall", "record_patent_browser_recall.py"),
                                               ("uspto_patent_browser", "candidate_verification", "record_uspto_patent_chrome_verification.py"),
                                               ("uspto_tsdr", "candidate_verification", "record_tsdr_browser_verification.py")]:
            command = scheduler.recorder_command(provider, {"operation": operation}, self.root, self.root / "capture.json")
            self.assertEqual(Path(command[1]).name, expected)
        with self.assertRaisesRegex(ValueError, "AUTOMATION_NOT_VALIDATED"):
            scheduler.recorder_command("jplatpat_browser", {"operation": "candidate_verification"}, self.root, self.root / "capture.json")

    def test_resume_validates_capture_receipt_screenshot_and_source_run(self):
        fixture = execution_tests.BrowserExecutionTests()
        fixture.setUp()
        try:
            capfile = fixture.root / "capture.json"
            capfile.write_text(json.dumps(fixture.capture))
            source_run = {"provider": fixture.provider, "query_id": fixture.entry["query_id"], "status": "success", "plan_entry_sha256": canonical_digest(fixture.entry)}
            (fixture.root / "evidence.json").write_text(json.dumps({"task_id": fixture.task["task_id"], "schema_version": fixture.task["schema_version"], "source_runs": [source_run]}))
            previous = {"status": "success", "plan_entry_sha256": canonical_digest(fixture.entry), "capture_path": str(capfile), "capture_sha256": sha256_file(capfile)}
            self.assertTrue(scheduler.completed_capture(fixture.root, fixture.task, fixture.provider, fixture.entry, previous))
            fixture.screenshot.write_bytes(b"changed")
            self.assertFalse(scheduler.completed_capture(fixture.root, fixture.task, fixture.provider, fixture.entry, previous))
        finally:
            fixture.tearDown()

    def test_partial_positive_remains_evidence_but_resumes_once_then_defers(self):
        self._partial_resume_case(fail_resume=False)

    def test_failed_partial_resume_preserves_original_evidence_and_does_not_loop(self):
        self._partial_resume_case(fail_resume=True)

    def _partial_resume_case(self, *, fail_resume):
        self.task["screening_revision"] = "recall-integrity-v1"
        (self.root / "task.json").write_text(json.dumps(self.task))
        self.rows = {"uspto_patent_browser": [self.entry("Q3", "patent", "patent_recall")]}
        self.write_plan()
        entry = self.rows["uspto_patent_browser"][0]
        capfile = self.root / "partial.json"
        capfile.write_text(json.dumps({"query_id": "Q3", "status": "success", "result_coverage": {
            "total_hits": 6, "retrieved_hits": 2, "schema_valid": True,
            "truncated": True, "completeness": "partial", "stop_reason": "family_members_unretrieved"}}))
        calls = []
        def runner(command, timeout=180):
            if "automation-capability" in command:
                return {"executor_available": True}
            if "run-planned-query" in command:
                calls.append(command)
                if fail_resume and len(calls) > 1:
                    return {"status": "failed", "error_code": "RESUME_FAILED"}
                return {"status": "success", "capture_path": str(capfile)}
            (self.root / "evidence.json").write_text(json.dumps({**self.task, "source_runs": [{
                "provider": "uspto_patent_browser", "query_id": "Q3", "status": "success", "plan_entry_sha256": canonical_digest(entry)}]}))
            return {"status": "success"}
        # Query/capture/source identity remains checked here. Receipt cryptography
        # is covered by test_resume_validates_capture_receipt_screenshot_and_source_run.
        with patch.object(scheduler, "validate_browser_execution", return_value={}):
            # Supply the immutable receipt reference required by the integrity check.
            receipt = self.root / "receipt.json"
            receipt.write_text(json.dumps({"query_id": "Q3", "plan_entry_sha256": canonical_digest(entry)}))
            cap = json.loads(capfile.read_text())
            cap["query_execution"] = {"path": str(receipt)}
            capfile.write_text(json.dumps(cap))
            first = scheduler.execute_plan(self.root, runner=runner)
            prior = first["queries"][0]
            self.assertEqual(first["status"], "incomplete")
            self.assertEqual(prior["capture_status"], "success")
            self.assertTrue(scheduler.completed_capture(self.root, self.task, "uspto_patent_browser", entry, prior))
            self.assertFalse(scheduler.completed_capture(self.root, self.task, "uspto_patent_browser", entry, prior, allow_partial=False))
            # A misleading scheduler summary cannot hide the original partial.
            prior["result_coverage"] = {"truncated": False, "completeness": "result_set_complete"}
            (self.root / "browser-execution-status.json").write_text(json.dumps(first))
            second = scheduler.execute_plan(self.root, runner=runner)
            self.assertEqual(second["queries"][0]["partial_resume_attempts"], 1)
            self.assertEqual(len(calls), 2)
            third = scheduler.execute_plan(self.root, runner=lambda *args: self.fail("partial retry budget must stop dispatch"))
            self.assertEqual(third["queries"][0]["dispatch"], "partial_deferred")
            self.assertEqual(third["status"], "failed" if fail_resume else "incomplete")
            self.assertTrue(capfile.is_file())


class BrowserPlanIntegrationTests(unittest.TestCase):
    def test_real_generated_plan_records_exact_gaps_without_network(self):
        from common import atomic_write_json, load_json
        from workflow_v24 import generate_plan, product_identity_digest, sha256_json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run([sys.executable, str(scheduler.ROOT / "scripts" / "create_task.py"),
                            "--url", "https://www.amazon.com/dp/B012345678", "--jurisdictions", "US,JP",
                            "--output-dir", directory], check=True, capture_output=True)
            task = load_json(root / "task.json")
            task["state"] = "collecting"
            task["product"].update(title="fixture product", brand="Fixture", language="en", structure=["fixture support"])
            task["product"]["analysis"] = {"status": "confirmed", "identity_sha256": product_identity_digest(task["product"], task=task)}
            task["query_terms"] = [{"kind": "design", "value": "fixture holder", "language": "en", "derived_from": "product.title"},
                                   {"kind": "brand", "value": "Fixture", "language": "en", "derived_from": "product.brand"}]
            task["product"]["analysis"]["clue_dispositions"] = [{"source_path": "product.structure[0]", "source_sha256": sha256_json("fixture support"),
                "disposition": "mapped", "query_term_sha256": [sha256_json(task["query_terms"][0])], "reason": "Fixture support is represented by the holder query."}]
            atomic_write_json(root / "task.json", task)
            plan = generate_plan(root)
            calls = []
            def unavailable(command, timeout=180):
                calls.append(command)
                return {"executor_available": False, "status": "unvalidated", "error_code": "AUTOMATION_NOT_VALIDATED", "detail": "Offline adapter test; no network query occurred."}
            report = scheduler.execute_plan(root, 1, runner=unavailable)
            self.assertTrue(report["queries"])
            self.assertTrue(all(r["status"] == "access_limited" and r.get("source_run_id") for r in report["queries"]))
            self.assertTrue(all("automation-capability" in command for command in calls))
            evidence = load_json(root / "evidence.json")
            self.assertEqual(len(evidence["source_runs"]), len(report["queries"]))
            by_id = {r["query_id"]: r for rows in plan["queries"].values() for r in rows}
            self.assertTrue(all(run["plan_entry_sha256"] == canonical_digest(by_id[run["query_id"]]) for run in evidence["source_runs"]))


if __name__ == "__main__":
    unittest.main()
