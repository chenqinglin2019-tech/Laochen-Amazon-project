"""Offline cross-layer reuse tests. Synthetic data are not live IP evidence."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from annotate_materiality import empty_materiality_ledger
from assessment_v24 import coverage_by_scope
from common import atomic_write_json, load_json, sha256_file
from decision_workflow import make_annotation
import test_historical_evidence as source_fixtures
from workflow_v24 import bind_scenario_action, scenario_historical_reuse, scenario_historical_reuse_from_dir


class ScenarioHistoricalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.source = source_fixtures.HistoricalEvidenceTests()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.task = self.source.task
        self.task["coverage_requirements"] = [{"requirement_id": "REQ-NEW", "jurisdiction": "US", "right_type": "patent",
            "phase": "official_recall", "required_axes": ["text"], "required_language": "en", "expansion_required": False}]
        self.row = bind_scenario_action(self.task, self.source.provider,
            {**self.source.original, "requirement_ids": ["REQ-NEW"], "execute_by_default": True}, purpose="recall")
        self.plan = {**self.source.plan, "task_id": self.task["task_id"],
                     "decision_workflow_revision": self.task["decision_workflow_revision"],
                     "queries": {self.source.provider: [self.row]}}
        self.candidates = self.source.candidates
        self.evidence = {"schema_version": self.task["schema_version"], "task_id": self.task["task_id"],
                         "collections": {}, "source_runs": []}
        self.ledger = empty_materiality_ledger(self.task["task_id"], task=self.task)
        self.supplement = self.source.supplement
        self.supplement["evidence_root"] = str(self.source.root)
        self.new = self.source.root / "new"
        self.new.mkdir()
        self.save()

    def save(self):
        for name, value in (("task.json", self.task), ("search-plan.json", self.plan), ("evidence.json", self.evidence),
                            ("normalized-candidates.json", self.candidates), ("materiality-annotations.json", self.ledger),
                            ("supplemental-evidence.json", self.supplement)):
            atomic_write_json(self.new / name, value)

    def coverage(self):
        return coverage_by_scope(self.task, self.evidence, self.candidates, self.plan, ledger=self.ledger,
                                 supplement=self.supplement, evidence_root=self.source.root)[0]

    def scheduler_task_contract(self):
        from common import serper_free_enhancement, signa_free_enhancement, serpapi_free_enhancement
        from workflow_v24 import build_coverage_requirements_v24
        self.task.update(serper_free_enhancement=serper_free_enhancement(), signa_free_enhancement=signa_free_enhancement(),
                         serpapi_free_enhancement=serpapi_free_enhancement(), coverage_requirements=build_coverage_requirements_v24(["US"]))
        self.plan.update({key: self.task[key] for key in ("serper_free_enhancement", "signa_free_enhancement", "serpapi_free_enhancement")})
        self.plan["execution_policy"] = {"commercial_freemium_allowlist": [], "commercial_providers_enabled": False,
                                         "paid_execution_enabled": False}
        self.save()

    def test_retained_retrieval_requires_current_triage_and_does_not_create_a_run(self):
        original = {path: sha256_file(path) for path in self.source.old.iterdir()}
        result = self.coverage()
        self.assertEqual(result["retrieval_status"], "complete")
        self.assertEqual(result["triage_status"], "incomplete")
        self.assertFalse(result["queries"][0]["complete"])
        self.assertEqual(result["queries"][0]["historical_reuse"]["source_query_id"], "OLD-Q")
        for index, candidate in enumerate(self.candidates["patents"]):
            self.ledger["annotations"].append(make_annotation(self.task, "patents", candidate,
                {"annotation_id": "CURRENT-" + str(index), "scenario_id": "product_entry", "jurisdiction": "US",
                 "decision": "not_selected", "reason": "Synthetic unrelated geometry", "reviewer": "offline-test",
                 "annotated_at": self.source.date, "evidence_refs": ["REUSE-EV"], "reading_level": "result_record",
                 "basis_summary": "Synthetic original title read", "reopen_conditions": ["New claims evidence"]},
                evidence=self.evidence, supplement=self.supplement))
        self.assertEqual(self.coverage()["gaps"], [])
        self.assertEqual(self.evidence["source_runs"], [])
        self.assertEqual(original, {path: sha256_file(path) for path in self.source.old.iterdir()})

    def test_api_scheduler_reuses_without_client_or_new_source_receipt(self):
        from runtime_v24 import execute_api_plan
        self.scheduler_task_contract()
        self.assertIsNotNone(scenario_historical_reuse_from_dir(self.new, self.source.provider, self.row))
        before = sha256_file(self.new / "evidence.json")
        with patch("runtime_v24.capabilities", return_value=[]), patch("runtime_v24.subprocess.run") as network:
            result = execute_api_plan(self.new, max_workers=1)
        network.assert_not_called()
        self.assertEqual(result["results"][0]["dispatch"], "historical_reused")
        self.assertFalse(result["results"][0]["source_query_performed"])
        self.assertEqual(before, sha256_file(self.new / "evidence.json"))

    def test_browser_scheduler_revalidates_original_receipt_without_new_query(self):
        from run_browser_plan import execute_plan
        capture, receipt, receipt_path = self.source.browser()
        original_receipt_hash = sha256_file(receipt_path)
        self.row = bind_scenario_action(self.task, self.source.provider,
            {**self.source.original, "requirement_ids": ["REQ-NEW"], "execute_by_default": True}, purpose="recall")
        self.plan["queries"] = {self.source.provider: [self.row]}
        self.scheduler_task_contract()
        before = sha256_file(self.new / "evidence.json")
        with patch("run_browser_plan.authorize_exact_plan_execution") as authorize:
            result = execute_plan(self.new, runner=lambda *args, **kwargs: self.fail("No new browser query expected"))
        authorize.assert_not_called()
        self.assertEqual(result["queries"][0]["dispatch"], "historical_reused")
        self.assertNotIn("capture_path", result["queries"][0])
        self.assertEqual(before, sha256_file(self.new / "evidence.json"))
        self.assertEqual(original_receipt_hash, sha256_file(receipt_path))

    def test_shared_query_needs_separate_scope_reviews_before_skipping_network(self):
        from decision_workflow import scenario_sha256
        alternative = deepcopy(self.task["assessment_scenarios"][0])
        alternative.update(scenario_id="alternate_product_entry", title="Second explicitly scoped product decision")
        alternative["scenario_sha256"] = scenario_sha256(alternative)
        self.task["assessment_scenarios"].append(alternative)
        self.row = bind_scenario_action(self.task, self.source.provider,
            {**self.source.original, "requirement_ids": ["REQ-NEW"], "execute_by_default": True}, purpose="recall")
        self.assertIsNone(scenario_historical_reuse(self.task, self.source.provider, self.row, self.candidates, self.supplement))
        self.assertIsNotNone(scenario_historical_reuse(self.task, self.source.provider, self.row, self.candidates,
                                                      self.supplement, scenario_id="product_entry"))
        second = deepcopy(self.source.item)
        second["evidence_id"] = "REUSE-EV-SECOND"
        second["reuse_binding"].update(scenario_id=alternative["scenario_id"], scenario_sha256=alternative["scenario_sha256"])
        for candidate in self.candidates["patents"]:
            candidate["evidence_refs"].append(second["evidence_id"])
        self.supplement["evidence"].append(second)
        self.assertIsNotNone(scenario_historical_reuse(self.task, self.source.provider, self.row, self.candidates, self.supplement))
        second["evidence_id"] = "REUSE-EV"
        self.assertIsNone(scenario_historical_reuse(self.task, self.source.provider, self.row, self.candidates, self.supplement))

    def test_no_root_conflicting_root_tampered_source_and_cancelled_action_cannot_reuse(self):
        without = {key: value for key, value in self.supplement.items() if key != "evidence_root"}
        self.assertIsNone(scenario_historical_reuse(self.task, self.source.provider, self.row, self.candidates, without))
        self.assertIsNone(scenario_historical_reuse(self.task, self.source.provider, self.row, self.candidates,
                                                   self.supplement, evidence_root=self.new))
        atomic_write_json(self.source.old / "response.json", {"tampered": True})
        self.assertIsNone(scenario_historical_reuse_from_dir(self.new, self.source.provider, self.row))
        self.source.save()
        self.save()
        from common import sha256_json
        self.task["screening_revision"] = "recall-integrity-v1"
        self.plan["screening_revision"] = self.task["screening_revision"]
        self.plan["execution_dispositions"] = [{"query_id": self.row["query_id"], "plan_entry_sha256": sha256_json(self.row),
                                                "status": "cancelled", "reason": "Explicitly superseded"}]
        self.save()
        self.assertIsNone(scenario_historical_reuse_from_dir(self.new, self.source.provider, self.row))


if __name__ == "__main__":
    unittest.main()
