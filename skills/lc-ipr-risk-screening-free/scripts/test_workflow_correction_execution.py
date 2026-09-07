"""Offline correction contract checks. Synthetic cases never count as live acceptance."""
import copy
import unittest
from unittest.mock import patch

from common import atomic_write_json, atomic_write_bytes, load_json, sha256_json, sha256_file, now_iso
from decision_workflow import decision_snapshot
from run_browser_plan import _BatchInputs, execute_plan, record_failure
from workflow_v24 import (append_candidate_actions, action_attempt_state, reconcile_scenario_actions,
    scenario_dispatch_block_from_dir, record_action_recovery, requested_facts_satisfied, reading_contract_valid,
    derive_work_view, bind_scenario_action)
from workflow_v24 import review_pre_source_guard_failure
import test_scenario_planning


class WorkflowCorrectionExecutionTests(unittest.TestCase):
    def setUp(self):
        self.f = test_scenario_planning.ScenarioPlanningTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        f = self.f
        self.params = {"q": f.candidate["serial_number"], "serial_number": f.candidate["serial_number"],
            "candidate_id": f.candidate["candidate_id"], "strategy": "record_number", "mode": "agent"}
        f.annotate("needs_info", missing_information=["Complete goods"], next_actions=[{
            "action_id": "MINIMAL-GOODS", "kind": "source_lookup", "purpose": "read_goods", "provider": "uspto_tsdr",
            "operation": "candidate_verification", "params": self.params, "max_attempts": 1,
            "required_facts": ["goods_services"], "reading_scope": {"level": "goods_services"}}])
        append_candidate_actions(f.path, f.task, f.candidates)
        f.plan = load_json(f.path / "search-plan.json")
        self.row = f.plan["queries"]["uspto_tsdr"][0]

    def failure(self, state):
        f = self.f
        result = {"status": "failed", "error_code": "AUTOMATIC_QUERY_INPUT_MISMATCH", "phase": "prepare_input"}
        if state is not None:
            result["submission_state"] = state
        record_failure(f.path, f.task, "uspto_tsdr", self.row, result)
        f.evidence = load_json(f.path / "evidence.json")

    def test_pre_submit_failure_is_retryable_and_recovery_is_append_only(self):
        f = self.f
        self.failure("not_submitted")
        run = f.evidence["source_runs"][-1]
        self.assertEqual(run["submission_state"], "not_submitted")
        self.assertEqual(run["execution_phase"], "prepare_input")
        self.assertIsNone(scenario_dispatch_block_from_dir(f.path, "uspto_tsdr", self.row))
        reconcile_scenario_actions(f.path, f.task, f.plan)
        self.assertFalse(any(item.get("query_id") == self.row["query_id"] for item in f.plan.get("execution_dispositions", [])))
        original = copy.deepcopy(f.plan)
        first = record_action_recovery(f.path, "uspto_tsdr", self.row, implementation_sha256="v1")
        self.assertEqual(first, record_action_recovery(f.path, "uspto_tsdr", self.row, implementation_sha256="v1"))
        second = record_action_recovery(f.path, "uspto_tsdr", self.row, implementation_sha256="v2")
        self.assertNotEqual(first["recovery_id"], second["recovery_id"])
        self.assertEqual(len(load_json(f.path / "action-recoveries.json")["records"]), 2)
        self.assertEqual(original, load_json(f.path / "search-plan.json"))

    def test_unknown_and_submitted_are_deferred_never_cancelled_or_automatically_retried(self):
        f = self.f
        self.failure(None)
        self.assertEqual(f.evidence["source_runs"][-1]["submission_state"], "unknown")
        self.assertEqual(scenario_dispatch_block_from_dir(f.path, "uspto_tsdr", self.row)["reason"], "TRIAGE_ATTEMPT_STATE_UNKNOWN")
        reconcile_scenario_actions(f.path, f.task, f.plan)
        self.assertFalse(f.plan.get("execution_dispositions"))
        self.assertIsNone(record_action_recovery(f.path, "uspto_tsdr", self.row))
        with patch("run_browser_plan.shutil.which", return_value="node"):
            result = execute_plan(f.path, query_ids_filter=[self.row["query_id"]], runner=lambda *_: self.fail("must not execute"))
        self.assertEqual(result["batch_status"], "incomplete")
        self.assertEqual(next(row for row in result["queries"] if row["query_id"] == self.row["query_id"])["dispatch"], "deferred")
        self.assertEqual(result["work_view"]["counts"]["submission_unknown"], 1)

    def test_submission_priority_is_conservative_and_exact_row_bound(self):
        evidence = {"source_runs": [
            {"provider": "uspto_tsdr", "query_id": self.row["query_id"], "plan_entry_sha256": sha256_json(self.row), "status": "failed", "submission_state": state}
            for state in ("submitted", "not_submitted")]}
        self.assertEqual(action_attempt_state(evidence, "uspto_tsdr", self.row)["state"], "submitted")
        self.assertFalse(action_attempt_state(evidence, "other", self.row)["attempted"])

    def test_review_of_exact_guard_failure_preserves_original_and_allows_recovery(self):
        f = self.f
        record_failure(f.path, f.task, "uspto_tsdr", self.row, {
            "status": "access_limited", "error_code": "BROWSER_EXECUTION_FAILED",
            "detail": "SCENARIO_DISPATCH_INPUT_INVALID: current scenario/triage does not authorize this action"})
        evidence = load_json(f.path / "evidence.json")
        original = copy.deepcopy(evidence["source_runs"][-1])
        self.assertEqual(action_attempt_state(evidence, "uspto_tsdr", self.row)["state"], "unknown")
        review_pre_source_guard_failure(f.path, original["run_id"], reviewer="test-agent",
            reasoning="Inspected original stderr and shared pre-source guard control flow.")
        evidence = load_json(f.path / "evidence.json")
        self.assertEqual(original, evidence["source_runs"][-1])
        self.assertEqual(action_attempt_state(evidence, "uspto_tsdr", self.row)["state"], "not_submitted")
        self.assertIsNone(scenario_dispatch_block_from_dir(f.path, "uspto_tsdr", self.row))
        self.assertTrue(record_action_recovery(f.path, "uspto_tsdr", self.row)["submission_review_ids"])
        evidence["submission_state_reviews"][0]["source_run_sha256"] = "wrong"
        self.assertEqual(action_attempt_state(evidence, "uspto_tsdr", self.row)["state"], "unknown")

    def test_generic_unknown_cannot_use_guard_review(self):
        self.failure(None)
        with self.assertRaisesRegex(ValueError, "NOT_A_PRE_SOURCE"):
            review_pre_source_guard_failure(self.f.path, self.f.evidence["source_runs"][-1]["run_id"],
                reviewer="test-agent", reasoning="A generic timeout does not prove no submission.")

    def test_selected_unknown_is_blocked_as_well_as_needs_info(self):
        f = self.f
        f.annotate("selected")
        append_candidate_actions(f.path, f.task, f.candidates)
        f.plan = load_json(f.path / "search-plan.json")
        row = next(r for r in reversed(f.plan["queries"]["uspto_tsdr"])
                   if r.get("action_purpose") == "official_verification")
        record_failure(f.path, f.task, "uspto_tsdr", row, {
            "status": "failed", "error_code": "BROWSER_EXECUTION_TIMEOUT", "submission_state": "unknown"})
        self.assertEqual(scenario_dispatch_block_from_dir(f.path, "uspto_tsdr", row)["code"], "TRIAGE_ATTEMPT_STATE_UNKNOWN")

    def test_content_contract_does_not_promote_abstract_to_official_status(self):
        row = {"candidate_id": "P1", "q": "US11401089B2", "required_facts": ["abstract"], "reading_scope": {"level": "abstract"}}
        payload = {"candidate_id": "P1", "publication_number": row["q"], "satisfied_facts": ["abstract"]}
        self.assertTrue(requested_facts_satisfied(row, payload))
        self.assertFalse(requested_facts_satisfied({**row, "required_facts": ["current_status"]}, payload))
        self.assertFalse(requested_facts_satisfied(row, {**payload, "publication_number": "US20190315539A1"}))
        self.assertFalse(reading_contract_valid({**row, "reading_scope": {"level": []}}))
        self.assertFalse(requested_facts_satisfied(row, {**payload, "satisfied_facts": [{}]}))
        self.assertFalse(reading_contract_valid({**row, "required_facts": ["representative_figures"]}))

    def test_work_view_includes_unexecuted_lightweight_source_action(self):
        f = self.f
        view = derive_work_view(f.task, f.evidence, f.candidates, f.plan, f.ledger, task_dir=f.path)
        work = next(item for item in view["entries"] if item.get("query_id") == self.row["query_id"])
        self.assertEqual(work["state"], "ready")
        self.assertEqual(work["required_facts"], ["goods_services"])
        self.assertEqual(view["status"], "incomplete")
        self.assertFalse(any(item.get("query_id") == self.row["query_id"] for item in f.plan.get("triage_action_queue", [])))

    def test_selected_batch_is_not_poisoned_by_removed_historical_access_failure(self):
        f = self.f
        atomic_write_json(f.path / "browser-execution-status.json", {"task_id": f.task["task_id"], "queries": [
            {"query_id": "REMOVED-HISTORY", "provider": "other_browser", "status": "needs_user_action"}]})
        with patch("run_browser_plan.completed_capture", return_value=True), patch("run_browser_plan.shutil.which", return_value="node"):
            # A fully retained selected row is represented by a prior success;
            # the mock here isolates only batch summary, not evidence credit.
            prior = load_json(f.path / "browser-execution-status.json")
            prior["queries"].append({"query_id": self.row["query_id"], "provider": "uspto_tsdr", "status": "success",
                "capture_path": str(f.path / "empty-capture.json")})
            atomic_write_json(f.path / "empty-capture.json", {})
            atomic_write_json(f.path / "browser-execution-status.json", prior)
            output = execute_plan(f.path, query_ids_filter=[self.row["query_id"]], runner=lambda *_: self.fail("must not execute"))
        self.assertEqual(output["batch_status"], "success")
        self.assertEqual(output["required_user_actions"], [])
        self.assertEqual(output["work_status"], "incomplete")
        self.assertIn("REMOVED-HISTORY", {row["query_id"] for row in output["queries"]})

    def test_batch_memo_reuses_identical_inputs_but_rechecks_content(self):
        f = self.f
        batch = _BatchInputs(f.path)
        self.assertEqual(batch.disposition("uspto_tsdr", self.row), (None, None, None))
        memo = batch.memo_state["snapshot"]["memo"]
        self.assertEqual(batch.disposition("uspto_tsdr", self.row), (None, None, None))
        self.assertIs(batch.memo_state["snapshot"]["memo"], memo)
        ledger = load_json(f.path / "materiality-annotations.json")
        ledger["annotations"][-1]["basis_summary"] = "Changed decision bytes"
        atomic_write_json(f.path / "materiality-annotations.json", ledger)
        block, _, _ = batch.disposition("uspto_tsdr", self.row)
        self.assertIsNotNone(block)
        self.assertIsNot(batch.memo_state["snapshot"]["memo"], memo)

    def test_registered_original_becomes_agent_read_work_not_fake_query_or_status(self):
        from decision_workflow import make_annotation, effective_decision
        from generate_search_plan import entry
        from workflow_v24 import scenario_reading_material
        f = self.f
        patent = {"candidate_id": "P-ORIGINAL", "publication_number": "US11401089B2", "jurisdiction": "US",
                  "right_type": "patent", "title": "Lid retainer", "evidence_refs": ["EV-PDF"]}
        f.candidates["patents"].append(patent)
        document = f.path / "original.pdf"
        # A byte fixture is available to read; it is not asserted to be a live
        # patent or sufficient evidence for any conclusion.
        atomic_write_bytes(document, b"%PDF-1.4\n% synthetic original fixture\n%%EOF\n")
        item = {"evidence_id": "EV-PDF", "kind": "patent_document", "publication_number": patent["publication_number"],
            "jurisdiction": "US", "right_type": "patent", "authority_scope": "published_document_only",
            "path": str(document), "sha256": sha256_file(document), "bytes": document.stat().st_size, "checked_at": now_iso(), "source_document": str(document)}
        supplement = {"schema": "IPR-EVIDENCE-SUPPLEMENT/1.0", "evidence_root": str(f.path), "evidence": [item]}
        params = {"q": patent["publication_number"], "record_number": patent["publication_number"],
                  "candidate_id": patent["candidate_id"], "strategy": "record_number"}
        action = {"action_id": "READ-ABSTRACT", "kind": "source_lookup", "purpose": "abstract", "max_attempts": 1,
                  "provider": "uspto_patent_browser", "operation": "candidate_verification", "params": params,
                  "required_facts": ["abstract"], "reading_scope": {"level": "abstract"}}
        annotation = make_annotation(f.task, "patents", patent, {"annotation_id": "D-ORIGINAL", "decision": "needs_info",
            "scenario_id": "product_entry", "reason": "Read the abstract before choosing relevance", "reviewer": "offline-agent",
            "annotated_at": now_iso(), "evidence_refs": ["EV-PDF"], "reading_level": "result_record",
            "basis_summary": "Title is insufficient", "missing_information": ["Abstract"],
            "reopen_conditions": ["New abstract"], "next_actions": [action]}, evidence=f.evidence, supplement=supplement)
        f.ledger["annotations"].append(annotation)
        f.save()
        atomic_write_json(f.path / "supplemental-evidence.json", supplement)
        append_candidate_actions(f.path, f.task, f.candidates)
        f.plan = load_json(f.path / "search-plan.json")
        row = next(row for row in f.plan["queries"]["uspto_patent_browser"] if row.get("candidate_id") == patent["candidate_id"])
        material = scenario_reading_material(f.task, f.plan, f.evidence, f.candidates, f.ledger,
            "uspto_patent_browser", row, supplement=supplement, task_dir=f.path)
        self.assertIsNotNone(material)
        self.assertEqual(material["dispatch"], "agent_read_required")
        self.assertFalse(material["complete"])
        self.assertEqual(material["satisfied_facts"], [])
        before = copy.deepcopy(f.evidence)
        output = execute_plan(f.path, query_ids_filter=[row["query_id"]], runner=lambda *_: self.fail("must use retained original"))
        self.assertEqual(next(item for item in output["queries"] if item["query_id"] == row["query_id"])["dispatch"], "agent_read_required")
        self.assertEqual(load_json(f.path / "evidence.json"), before)
        atomic_write_bytes(document, b"%PDF-1.4\nchanged\n%%EOF")
        self.assertIsNone(scenario_reading_material(f.task, f.plan, f.evidence, f.candidates, f.ledger,
            "uspto_patent_browser", row, supplement=supplement, task_dir=f.path))

    def test_exact_api_batch_selects_only_requested_rows_and_preserves_capability_gap(self):
        from runtime_v24 import execute_api_plan
        f = self.f
        selected = f.plan["queries"]["epo_ops"][0]["query_id"]
        with patch("runtime_v24.capabilities", return_value=[{"provider": "epo_ops", "executable": False, "reason": "credentials_missing"}]), \
                patch("runtime_v24.subprocess.run") as network:
            output = execute_api_plan(f.path, wave="2", query_ids_filter=[selected])
        network.assert_not_called()
        self.assertEqual([row["query_id"] for row in output["results"]], [selected])
        self.assertEqual(output["results"][0]["submission_state"], "not_submitted")
        self.assertEqual(output["batch_status"], "access_limited")
        self.assertEqual(output["work_status"], "incomplete")
        self.assertEqual(output["agent_browser_queue"], [])
        with patch("runtime_v24.capabilities", return_value=[]), patch("runtime_v24.subprocess.run") as network:
            with self.assertRaisesRegex(ValueError, "distinct exact API"):
                execute_api_plan(f.path, query_ids_filter=[self.row["query_id"]])
        network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
