"""Ordinary submitted failure budgets use retained runs, never status overrides."""
from copy import deepcopy
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
from workflow_v24 import browser_submitted_failure_state, derive_work_view, scenario_dispatch_block_from_dir
import workflow_v24 as workflow
import run_browser_plan as scheduler
import test_scenario_planning as scenario_tests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import test_browser_plan_v24 as browser_tests


def failed_run(provider, row, number=1, **extra):
    return {"run_id": f"RUN-{number}", "provider": provider, "query_id": row["query_id"],
        "plan_entry_sha256": sha256_json(row), "status": "failed", "submission_state": "submitted",
        "error_code": "BROWSER_SEMANTIC_TIMEOUT", "metadata": {"search_coverage": {
            "retrieved_hits": 0, "schema_valid": False, "truncated": True}}, **extra}


class SubmittedFailureStateTests(unittest.TestCase):
    def setUp(self):
        self.task = {"completion_policy_revision": "necessary-work-v1"}
        self.provider = "uspto_patent_browser"
        self.row = {"query_id": "Q1", "jurisdiction": "US", "right_type": "patent", "q": "ring AND toy"}
        self.evidence = {"source_runs": []}

    def state(self):
        return browser_submitted_failure_state(self.task, self.evidence, self.provider, self.row)

    def test_initial_plus_one_recovery_and_legacy_unchanged(self):
        self.assertIsNone(self.state())
        self.evidence["source_runs"].append(failed_run(self.provider, self.row))
        self.assertEqual((self.state()["state"], self.state()["remaining_attempts"]), ("ready", 1))
        self.evidence["source_runs"].append(failed_run(self.provider, self.row, 2))
        state = self.state()
        self.assertEqual((state["state"], state["failure_count"], state["remaining_attempts"]), ("blocked", 2, 0))
        self.assertEqual(len(state["source_run_refs"]), 2)
        self.task.pop("completion_policy_revision")
        self.assertIsNone(self.state())

    def test_plan_hash_provider_query_and_scope_are_isolated(self):
        for key, value in (("q", "other AND terms"), ("jurisdiction", "JP"), ("right_type", "design"), ("query_id", "Q2")):
            self.evidence["source_runs"].append(failed_run(self.provider, {**self.row, key: value}))
        self.evidence["source_runs"].append(failed_run("other_browser", self.row))
        self.assertIsNone(self.state())
        self.evidence["source_runs"].append(failed_run(self.provider, self.row))
        self.assertEqual(self.state()["failure_count"], 1)

    def test_limits_syntax_and_unsubmitted_do_not_spend_ordinary_budget(self):
        for code in ("USPTO_QUERY_REJECTED", "UNSUPPORTED_QUERY_SEMANTICS", "BROWSER_RATE_LIMITED",
                     "BROWSER_RATE_LIMIT_COOLDOWN", "BROWSER_RATE_LIMIT_RECOVERY_EXHAUSTED", "BROWSER_PARTIAL_RESUME_LIMIT"):
            self.evidence["source_runs"].append(failed_run(self.provider, self.row, error_code=code))
        self.evidence["source_runs"].append(failed_run(self.provider, self.row, submission_state="not_submitted"))
        self.evidence["source_runs"].append(failed_run(self.provider, self.row, status="needs_user_action"))
        self.evidence["source_runs"].append(failed_run(self.provider, self.row, metadata={"search_coverage": {"stop_reason": "browser_rate_limited"}}))
        self.assertIsNone(self.state())
        self.evidence["source_runs"].append(failed_run(self.provider, self.row, 20))
        self.assertEqual(self.state()["failure_count"], 1)

    def test_success_and_partial_success_remain_in_existing_completion_policy(self):
        for status in ("success", "no_result"):
            self.evidence["source_runs"] = [failed_run(self.provider, self.row), failed_run(self.provider, self.row, 2),
                failed_run(self.provider, self.row, 3, status=status, error_code="")]
            self.assertIsNone(self.state())

    def test_unknown_after_submitted_failure_requires_verification(self):
        self.evidence["source_runs"] = [failed_run(self.provider, self.row),
            failed_run(self.provider, self.row, 2, submission_state="unknown")]
        self.assertEqual(self.state()["state"], "submission_unknown")
        self.assertEqual(self.state()["source_run_refs"][0]["run_id"], "RUN-2")

    def test_only_shared_non_secret_runtime_config_sets_limit(self):
        self.evidence["source_runs"] = [failed_run(self.provider, self.row)]
        for limit, expected in ((0, "blocked"), (1, "ready"), (8, "ready"), (True, "ready")):
            with patch.object(workflow, "load_json", return_value={"cdp": {"submitted_failure_resume_limit": limit}}) as read:
                self.assertEqual(self.state()["state"], expected)
                self.assertEqual(read.call_args.args[0].name, "runtime-config.json")


class SubmittedFailureProjectionTests(unittest.TestCase):
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
        f.save()

    def view(self, row=None, provider=None, result=None):
        f = self.fixture
        row, provider = row or self.row, provider or self.provider
        scope = {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": row["right_type"],
            "queries": [{"query_id": row["query_id"], "complete": False, **(result or {})}], "obligations": [], "gaps": []}
        return derive_work_view(f.task, f.evidence, f.candidates, f.plan, f.ledger, coverage=[scope], task_dir=f.path,
            source_capabilities={provider: {"executable": False, "reason": "browser_adapter_requires_real_route_acceptance"}})

    def selected(self, view):
        return next(row for row in view["entries"] if row.get("query_id") == self.row["query_id"])

    def test_projection_and_direct_guard_agree_and_no_cancellation_is_added(self):
        f = self.fixture
        f.evidence["source_runs"] = [failed_run(self.provider, self.row)]
        f.save()
        self.assertEqual(self.selected(self.view())["state"], "ready")
        self.assertIsNone(scenario_dispatch_block_from_dir(f.path, self.provider, self.row))
        f.evidence["source_runs"].append(failed_run(self.provider, self.row, 2))
        f.save()
        item = self.selected(self.view())
        self.assertEqual(item["state"], "blocked")
        self.assertEqual(item["failure_count"], 2)
        self.assertEqual(scenario_dispatch_block_from_dir(f.path, self.provider, self.row)["code"], item["reason"])
        before = deepcopy(f.plan.get("execution_dispositions", []))
        workflow.reconcile_scenario_actions(f.path, f.task, f.plan, f.candidates, f.ledger, f.evidence)
        self.assertEqual(before, f.plan.get("execution_dispositions", []))

    def test_semantic_rejection_stays_agent_plan_repair(self):
        from necessary_completion import refine_work_view
        f = self.fixture
        f.evidence["source_runs"] = [failed_run(self.provider, self.row, error_code="USPTO_QUERY_REJECTED")]
        view = refine_work_view(f.task, self.view(), f.plan, {})
        item = self.selected(view)
        self.assertEqual((item["state"], item["kind"], item["reason"]), ("ready", "plan_repair", "USPTO_QUERY_REJECTED"))

    def test_validated_supplier_questions_project_to_user_information(self):
        f = self.fixture
        row = next(row for row in f.plan["queries"]["asset_provenance"] if row["right_type"] == "copyright")
        action = {"action_id": "INFO1", "purpose": "Confirm image rights", "question": "Who owns the source images?",
            "owner": "supplier", "evidence_needed": ["supply_chain_authorization"], "reasoning": "Public records cannot establish a private license.",
            "evidence_refs": ["EV-INVESTIGATION"]}
        result = {"retrieval_complete": True, "investigation_status": "completed", "external_information_actions": [action],
            "evidence_refs": ["EV-PUBLIC-RESEARCH"]}
        with patch.object(workflow, "scenario_dispatch_block", return_value=None):
            view = self.view(row, "asset_provenance", result)
            projected = next(item for item in view["entries"] if item.get("query_id") == row["query_id"])
            self.assertEqual((projected["state"], projected["kind"]), ("awaiting_user", "user_information"))
            self.assertEqual(projected["question"], action["question"])
            self.assertEqual(projected["evidence_refs"], ["EV-PUBLIC-RESEARCH", "EV-INVESTIGATION"])
            self.assertEqual(projected["action_id"], "INFO1")
            result.update(retrieval_complete=False, investigation_status="incomplete", external_information_actions=[])
            view = self.view(row, "asset_provenance", result)
            pending = next(item for item in view["entries"] if item.get("query_id") == row["query_id"])
            self.assertEqual((pending["state"], pending["kind"]), ("ready", "agent_investigation"))


class SubmittedFailureSchedulerTests(unittest.TestCase):
    setUp = browser_tests.BrowserPlanTests.setUp
    tearDown = browser_tests.BrowserPlanTests.tearDown
    entry = staticmethod(browser_tests.BrowserPlanTests.entry)
    write_plan = browser_tests.BrowserPlanTests.write_plan

    def configure(self):
        self.task["completion_policy_revision"] = "necessary-work-v1"
        atomic_write_json(self.root / "task.json", self.task)
        self.rows = {"uspto_patent_browser": [self.entry("Q3", "patent", "patent_recall")]}
        self.write_plan()
        self.executed = []

    def record(self, task_dir, task, provider, entry, result):
        evidence = load_json(task_dir / "evidence.json")
        run = failed_run(provider, entry, len(evidence["source_runs"]) + 1, status=result["status"],
            submission_state=result.get("submission_state", "unknown"), error_code=result["error_code"])
        evidence["source_runs"].append(run)
        atomic_write_json(task_dir / "evidence.json", evidence)
        return run["run_id"]

    def runner(self, command, timeout=180):
        if "automation-capability" in command:
            return {"executor_available": True}
        self.executed.append(command)
        return {"status": "failed", "submission_state": "submitted", "error_code": "BROWSER_SEMANTIC_TIMEOUT"}

    def test_two_failures_stop_across_status_deletion_and_implementation_change(self):
        self.configure()
        with patch.object(scheduler, "record_failure", side_effect=self.record):
            scheduler.execute_plan(self.root, runner=self.runner)
            second = scheduler.execute_plan(self.root, runner=self.runner)
            self.assertEqual(second["queries"][0]["submitted_failure_recovery"]["failure_count"], 1)
            (self.root / "browser-execution-status.json").unlink()
            with patch.object(scheduler, "browser_implementation_digest", return_value="new-implementation"):
                third = scheduler.execute_plan(self.root, runner=lambda *args: self.fail("third attempt must not dispatch"))
        self.assertEqual(len(self.executed), 2)
        self.assertEqual(len(load_json(self.root / "evidence.json")["source_runs"]), 2)
        self.assertEqual(third["queries"][0]["error_code"], "BROWSER_SUBMITTED_FAILURE_RECOVERY_EXHAUSTED")

    def test_cooldown_does_not_consume_recovery_and_other_rows_keep_running(self):
        self.configure()
        with patch.object(scheduler, "record_failure", side_effect=self.record):
            first = scheduler.execute_plan(self.root, runner=self.runner)
            first["provider_pauses"] = {"uspto_patent_browser": {"error_code": "BROWSER_RATE_LIMITED",
                "resume_after_epoch": time.time() + 100, "recovery_attempts": 0}}
            atomic_write_json(self.root / "browser-execution-status.json", first)
            cooled = scheduler.execute_plan(self.root, runner=lambda *args: self.fail("cooldown must not dispatch"))
            self.assertEqual(cooled["queries"][0]["error_code"], "BROWSER_RATE_LIMIT_COOLDOWN")
            evidence = load_json(self.root / "evidence.json")
            self.assertEqual(len(evidence["source_runs"]), 1)
            self.assertEqual(browser_submitted_failure_state(self.task, evidence, "uspto_patent_browser", self.rows["uspto_patent_browser"][0])["remaining_attempts"], 1)
            # Exhaust one row, while another exact row retains its own budget.
            evidence["source_runs"].append(failed_run("uspto_patent_browser", self.rows["uspto_patent_browser"][0], 2))
            atomic_write_json(self.root / "evidence.json", evidence)
            cooled["provider_pauses"] = {}
            atomic_write_json(self.root / "browser-execution-status.json", cooled)
            self.rows["uspto_patent_browser"].append(self.entry("Q4", "patent", "patent_recall"))
            self.write_plan()
            scheduler.execute_plan(self.root, runner=self.runner)
            self.assertEqual(len(self.executed), 2)
            self.assertIn("Q4", self.executed[-1])


class SubmittedFailurePublicationTests(unittest.TestCase):
    def test_stage_only_after_exhaustion_and_known_risk_is_retained(self):
        import test_necessary_completion as completion_tests
        fixture = completion_tests.NecessaryCompletionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        result = fixture.calculate(False)
        before = deepcopy(result["overall"])
        provider, row = "uspto_patent_browser", {"query_id": "Q-BLOCKED", "q": "toy"}
        evidence = {"source_runs": [failed_run(provider, row)]}
        state = browser_submitted_failure_state(fixture.task, evidence, provider, row)
        with self.assertRaisesRegex(ValueError, "STAGE_AGENT_WORK_REMAINS"):
            fixture.proof(result, fixture.blocked_view(state["state"], state["reason"]),
                mode="stage", stop_reason="The source remains unavailable")
        evidence["source_runs"].append(failed_run(provider, row, 2))
        state = browser_submitted_failure_state(fixture.task, evidence, provider, row)
        view = fixture.blocked_view(state["state"], state["reason"])
        for entry in view["entries"]:
            entry["source_run_refs"] = state["source_run_refs"]
        proof = fixture.proof(result, view, mode="stage", stop_reason="Two retained submitted attempts failed to load results")
        self.assertEqual(proof["mode"], "stage")
        self.assertEqual(result["overall"], before)


if __name__ == "__main__":
    unittest.main()
