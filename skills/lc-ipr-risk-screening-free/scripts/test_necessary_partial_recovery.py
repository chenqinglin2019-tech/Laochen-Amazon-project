"""Partial retrieval ends finitely without closing remaining candidate work."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
from necessary_completion import sanitize_snapshots
from workflow_v24 import browser_partial_recovery_state, work_view_from_dir
import workflow_v24 as workflow
import run_browser_plan as scheduler
import test_scenario_planning as scenario_tests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import test_browser_plan_v24 as browser_tests


def append_run(evidence, provider, row, *, truncated=True, status="success", code="", submitted="submitted"):
    number = len(evidence.setdefault("source_runs", [])) + 1
    run = {"run_id": "PARTIAL-RUN-" + str(number), "provider": provider,
        **{key: row[key] for key in ("query_id", "operation", "jurisdiction", "right_type")},
        "requirement_ids": row.get("requirement_ids", []), "plan_entry_sha256": sha256_json(row),
        "status": status, "submission_state": submitted, "error_code": code,
        "metadata": {"search_coverage": {"schema_valid": True, "truncated": truncated,
            "retrieved_hits": 1, "total_hits": 2 if truncated else 1,
            "stop_reason": code or ("incremental_load_not_confirmed" if truncated else "result_set_complete")}}}
    evidence["source_runs"].append(run)
    evidence.setdefault("collections", {}).setdefault("patents", []).append({**run,
        "evidence_id": "EV-" + run["run_id"], "source_run_id": run["run_id"], "payload": []})
    return run


class PartialStateTests(unittest.TestCase):
    def setUp(self):
        self.task = {"task_id": "TASK", "completion_policy_revision": "necessary-work-v1"}
        self.provider = "uspto_patent_browser"
        self.row = {"query_id": "Q1", "q": "toy", "operation": "patent_recall", "jurisdiction": "US", "right_type": "patent"}
        self.evidence = {"source_runs": [], "collections": {}}
        self.current = {"query_id": "Q1", "provider": self.provider, "plan_entry_sha256": sha256_json(self.row),
            "error_code": "BROWSER_RESULT_PARTIAL", "status": "incomplete", "dispatch": "executed",
            "partial_resume_attempts": 1, "partial_resume_limit": 1, "submission_state": "submitted"}

    def state(self, current=None):
        return browser_partial_recovery_state(self.task, self.evidence, self.provider, self.row, self.current if current is None else current)

    def test_initial_partial_is_ready_then_one_recovery_is_terminal(self):
        self.assertIsNone(self.state())  # A status row alone cannot invent partial evidence.
        append_run(self.evidence, self.provider, self.row)
        self.assertEqual(self.state()["reason"], "BROWSER_PARTIAL_RESUME_AVAILABLE")
        append_run(self.evidence, self.provider, self.row)
        state = self.state()
        self.assertEqual((state["state"], state["reason"], state["partial_resume_attempts"]), ("blocked", "BROWSER_PARTIAL_RESUME_LIMIT", 1))
        self.assertEqual(len(state["source_run_refs"]), 2)
        self.assertEqual(self.state({})["state"], "blocked")
        self.assertEqual(self.state({**self.current, "partial_resume_attempts": 0})["state"], "blocked")

    def test_lineage_and_nonbrowser_or_legacy_are_not_reinterpreted(self):
        append_run(self.evidence, self.provider, {**self.row, "q": "different"})
        self.assertIsNone(self.state())
        append_run(self.evidence, self.provider, self.row)
        self.evidence["collections"] = {}
        self.assertIsNone(self.state())
        self.task.pop("completion_policy_revision")
        self.assertIsNone(self.state())

    def test_nonproduction_partial_cannot_establish_real_source_blocker(self):
        for _ in range(2):
            run = append_run(self.evidence, self.provider, self.row)
            run["source_environment"] = "fixture"
        self.assertIsNone(self.state())

    def test_complete_capture_supersedes_partial_without_rewriting_old_runs(self):
        append_run(self.evidence, self.provider, self.row)
        append_run(self.evidence, self.provider, self.row)
        append_run(self.evidence, self.provider, self.row, truncated=False)
        self.assertIsNone(self.state())
        self.assertTrue(self.evidence["source_runs"][0]["metadata"]["search_coverage"]["truncated"])

    def test_unknown_rate_and_syntax_keep_existing_recovery_work(self):
        for code, submitted in (("BROWSER_RATE_LIMITED", "submitted"), ("USPTO_QUERY_REJECTED", "submitted"),
                                ("UNSUPPORTED_QUERY_SEMANTICS", "not_submitted"), ("BROWSER_ROW_FAILED", "unknown")):
            self.evidence = {"source_runs": [], "collections": {}}
            append_run(self.evidence, self.provider, self.row)
            append_run(self.evidence, self.provider, self.row, status="failed", code=code, submitted=submitted)
            self.assertIsNone(self.state(), code)

    def test_submitted_recovery_failure_preserves_partial_and_finishes_budget(self):
        append_run(self.evidence, self.provider, self.row)
        append_run(self.evidence, self.provider, self.row, status="failed", code="BROWSER_SEMANTIC_TIMEOUT")
        self.assertEqual(self.state()["state"], "blocked")

    def test_frozen_snapshot_roundtrip_uses_bound_runs_without_local_config(self):
        append_run(self.evidence, self.provider, self.row)
        raw = {"browser-execution-status.json": {"task_id": "TASK", "queries": [{**self.current, "partial_resume_limit": 0,
            "opaque_secret": "not retained"}]}}
        frozen = sanitize_snapshots(self.task, raw)
        row = frozen["browser-execution-status.json"]["queries"][0]
        self.assertNotIn("opaque_secret", row)
        self.assertEqual(row["partial_resume_limit"], 0)
        with patch.object(workflow, "load_skill_config", side_effect=AssertionError("No current credentials")), \
                patch.object(workflow, "load_json", side_effect=AssertionError("No current runtime settings")):
            self.assertEqual(self.state(row)["state"], "blocked")
            self.assertEqual(sha256_json(self.state(row)), sha256_json(self.state(deepcopy(row))))


class PartialProjectionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"LC_IPR_OFFLINE_TESTS": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.fixture = scenario_tests.ScenarioPlanningTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f = self.fixture
        f.task["completion_policy_revision"] = "necessary-work-v1"
        self.provider = "uspto_patent_browser"
        self.row = next(row for row in f.plan["queries"][self.provider] if row["right_type"] == "patent")
        for _ in range(2):
            append_run(f.evidence, self.provider, self.row)
        f.candidates["patents"].append({"candidate_id": "SYNTHETIC-PARTIAL-C1", "right_type": "patent", "jurisdiction": "US",
            "publication_number": "US11111111B2", "title": "Synthetic retained toy", "evidence_refs": ["EV-PARTIAL-RUN-1"]})
        f.save()
        atomic_write_json(f.path / "source-capabilities.json", {"task_id": f.task["task_id"], "sources": [
            {"provider": self.provider, "executable": False, "reason": "browser_adapter_requires_real_route_acceptance"}]})

    def test_rebuilt_work_view_keeps_partial_block_and_unreviewed_candidate(self):
        f = self.fixture
        with patch.object(workflow, "load_skill_config", side_effect=AssertionError("No current credentials")):
            view = work_view_from_dir(f.path)
        entry = next(item for item in view["entries"] if item.get("query_id") == self.row["query_id"])
        self.assertEqual((entry["state"], entry["reason"]), ("blocked", "BROWSER_PARTIAL_RESUME_LIMIT"))
        self.assertTrue(any(item.get("candidate_id") == "SYNTHETIC-PARTIAL-C1" and item["kind"] == "triage"
            and item["state"] == "awaiting_review" for item in view["entries"]))

    def test_retained_original_still_requires_agent_read_before_stopping(self):
        f = self.fixture
        groups = [{"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent", "obligations": [], "gaps": [],
            "queries": [{"query_id": self.row["query_id"], "complete": False}]}]
        with patch.object(workflow, "scenario_reading_material", return_value={"evidence_refs": ["EV-PARTIAL-RUN-1"]}):
            view = workflow.derive_work_view(f.task, f.evidence, f.candidates, f.plan, f.ledger, coverage=groups)
        entry = next(item for item in view["entries"] if item.get("query_id") == self.row["query_id"])
        self.assertEqual((entry["state"], entry["kind"]), ("awaiting_review", "agent_read"))


class PartialSchedulerTests(unittest.TestCase):
    setUp = browser_tests.BrowserPlanTests.setUp
    tearDown = browser_tests.BrowserPlanTests.tearDown
    entry = staticmethod(browser_tests.BrowserPlanTests.entry)
    write_plan = browser_tests.BrowserPlanTests.write_plan

    def configure(self):
        self.task.update(completion_policy_revision="necessary-work-v1", screening_revision="recall-integrity-v1")
        atomic_write_json(self.root / "task.json", self.task)
        self.rows = {"uspto_patent_browser": [self.entry("Q3", "patent", "patent_recall")]}
        self.write_plan()
        self.query = self.rows["uspto_patent_browser"][0]
        self.capture_path = self.root / "partial.json"
        atomic_write_json(self.root / "receipt.json", {"query_id": "Q3", "plan_entry_sha256": sha256_json(self.query)})
        atomic_write_json(self.capture_path, {"query_id": "Q3", "status": "success", "submission_state": "submitted",
            "query_execution": {"path": str(self.root / "receipt.json")}, "result_coverage": {
                "schema_valid": True, "truncated": True, "total_hits": 2, "retrieved_hits": 1, "stop_reason": "incremental_load_not_confirmed"}})
        self.executions = 0

    def runner(self, command, timeout=180):
        if "automation-capability" in command:
            return {"executor_available": True}
        if "run-planned-query" in command:
            self.executions += 1
            return {"status": "success", "submission_state": "submitted", "capture_path": str(self.capture_path)}
        evidence = load_json(self.root / "evidence.json")
        append_run(evidence, "uspto_patent_browser", self.query)
        atomic_write_json(self.root / "evidence.json", evidence)
        return {"status": "success"}

    def test_second_partial_directly_defers_and_status_deletion_does_not_reset(self):
        self.configure()
        with patch.object(scheduler, "validate_browser_execution", return_value={}):
            scheduler.execute_plan(self.root, runner=self.runner)
            second = scheduler.execute_plan(self.root, runner=self.runner)
            self.assertEqual(second["queries"][0]["dispatch"], "partial_deferred")
            self.assertEqual(second["queries"][0]["error_code"], "BROWSER_PARTIAL_RESUME_LIMIT")
            self.assertEqual(second["queries"][0]["submission_state"], "submitted")
            (self.root / "browser-execution-status.json").unlink()
            stopped = scheduler.execute_plan(self.root, runner=lambda *args: self.fail("budget cannot reset"))
        self.assertEqual(stopped["queries"][0]["submission_state"], "not_submitted")
        self.assertEqual(self.executions, 2)
        self.assertEqual(len(load_json(self.root / "evidence.json")["source_runs"]), 2)

    def test_changed_implementation_requires_explicit_query_and_remains_one_probe(self):
        self.configure()
        with patch.object(scheduler, "validate_browser_execution", return_value={}):
            scheduler.execute_plan(self.root, runner=self.runner)
            scheduler.execute_plan(self.root, runner=self.runner)
            with patch.object(scheduler, "browser_implementation_digest", return_value="repaired-implementation"):
                scheduler.execute_plan(self.root, runner=lambda *args: self.fail("automatic code-change retry prohibited"))
                probe = scheduler.execute_plan(self.root, query_id_filter="Q3", runner=self.runner)
                self.assertEqual(probe["queries"][0]["dispatch"], "partial_deferred")
                scheduler.execute_plan(self.root, query_id_filter="Q3", runner=lambda *args: self.fail("same repair cannot repeat"))
        self.assertEqual(self.executions, 3)


class PartialPublicationTests(unittest.TestCase):
    def test_frozen_partial_block_can_publish_stage_but_candidate_work_still_blocks(self):
        from test_necessary_completion import NecessaryCompletionTests
        fixture = NecessaryCompletionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        result = fixture.calculate(False)
        before = deepcopy(result["overall"])
        row = {"query_id": "Q-PARTIAL", "q": "mark", "operation": "trademark_recall", "jurisdiction": "US", "right_type": "trademark_word"}
        evidence = {"source_runs": [], "collections": {}}
        for _ in range(2):
            append_run(evidence, "uspto_tmsearch_browser", row)
        current = {"query_id": row["query_id"], "provider": "uspto_tmsearch_browser", "plan_entry_sha256": sha256_json(row),
            "dispatch": "partial_deferred", "status": "incomplete", "error_code": "BROWSER_PARTIAL_RESUME_LIMIT",
            "submission_state": "submitted", "partial_resume_attempts": 1, "partial_resume_limit": 1}
        snapshots = {"browser-execution-status.json": {"task_id": fixture.task["task_id"], "queries": [current]}}
        state = browser_partial_recovery_state(fixture.task, evidence, "uspto_tmsearch_browser", row, current)
        view = fixture.blocked_view(state["state"], state["reason"])
        for entry in view["entries"]:
            entry["source_run_refs"] = state["source_run_refs"]
        proof = fixture.proof(result, view, mode="stage", stop_reason="Retained partial source results exhausted one recovery", snapshots=snapshots)
        self.assertEqual(proof["snapshots"]["browser-execution-status.json"]["queries"][0]["partial_resume_limit"], 1)
        with patch.object(workflow, "load_skill_config", side_effect=AssertionError("No publishing-machine credentials")):
            rebuilt = fixture.proof(result, view, mode="stage", stop_reason=proof["stop_reason"], snapshots=proof["snapshots"])
        self.assertEqual(proof["work_view_sha256"], rebuilt["work_view_sha256"])
        self.assertEqual(result["overall"], before)
        view["entries"].append({"work_id": "WORK-CANDIDATE-READ", "scenario_id": "product_entry", "jurisdiction": "US",
            "right_type": "trademark_word", "kind": "agent_read", "state": "awaiting_review", "reason": "RETAINED_ORIGINAL_REQUIRES_READING"})
        with self.assertRaisesRegex(ValueError, "STAGE_AGENT_WORK_REMAINS"):
            fixture.proof(result, view, mode="stage", stop_reason=proof["stop_reason"], snapshots=snapshots)


if __name__ == "__main__":
    unittest.main()
