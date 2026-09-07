"""Necessary work is not the allowed triage vocabulary or a clearance finding."""
from copy import deepcopy
import unittest

from assessment_v24 import coverage_by_scope
from decision_workflow import (REVISION, default_assessment_scenarios, scenario_right_types,
    necessary_scenario_right_types, triage_summary, triage_ledger_errors, make_annotation)
from common import active_free_policy, sha256_json
from workflow_v24 import (bind_scenario_action, necessary_scenario_row_bindings,
    scenario_row_bindings, scenario_dispatch_block, SCENARIO_META_KEYS)
from provider_utils import PLAN_META_KEYS, query_identity


class NecessaryScenarioScopeTests(unittest.TestCase):
    def setUp(self):
        self.task = {"schema_version": "2.4-free", "task_id": "NECESSARY-SCOPE", "free_policy": active_free_policy(),
            "free_policy_revision": "automation-first-v1", "decision_workflow_revision": REVISION,
            "primary_scenario_id": "product_entry", "assessment_scenarios": default_assessment_scenarios(),
            "target_jurisdictions": ["US"], "product": {"input_role": "reference_product", "brand": "REFERENCE"},
            "coverage_requirements": [{"requirement_id": "REQ-" + right, "jurisdiction": "US", "right_type": right,
                "phase": "official_recall", "required_axes": ["text"], "required_language": "en"}
                for right in ("patent", "trademark_word", "trademark_figurative")]}
        self.primary, self.brand = self.task["assessment_scenarios"]
        self.evidence = {"schema_version": "2.4-free", "task_id": self.task["task_id"], "source_runs": [],
            "collections": {"trademarks": [{"evidence_id": "E1", "payload": {"mark_text": "REFERENCE"}}]}}
        self.candidate = {"candidate_id": "TM1", "right_type": "trademark_word", "jurisdiction": "US", "evidence_refs": ["E1"]}
        self.candidates = {"schema_version": "2.4-free", "task_id": self.task["task_id"], "trademarks": [self.candidate]}
        self.ledger = {"schema_version": "2.0", "task_id": self.task["task_id"], "annotations": []}
        self.plan = {key: deepcopy(self.task[key]) for key in ("schema_version", "task_id", "free_policy", "free_policy_revision", "decision_workflow_revision")}
        self.plan["queries"] = {}

    def row(self, task=None):
        return bind_scenario_action(task or self.task, "uspto_tmsearch_browser", {
            "operation": "trademark_recall", "jurisdiction": "US", "right_type": "trademark_word", "q": "REFERENCE",
            "required_for": "low_risk", "requirement_ids": ["REQ-trademark_word"], "search_dimension": "text",
            "search_language": "en", "execute_by_default": True, "execution_phase": "initial"}, purpose="recall")

    def test_reference_brand_not_supplied_own_brand(self):
        self.assertIn("trademark_word", scenario_right_types(self.primary))
        self.assertNotIn("trademark_word", necessary_scenario_right_types(self.task, self.primary))
        self.assertNotIn("trademark_figurative", necessary_scenario_right_types(self.task, self.primary))
        self.assertIn("trade_dress", necessary_scenario_right_types(self.task, self.primary))
        self.assertEqual(necessary_scenario_right_types(self.task, self.brand), scenario_right_types(self.brand))

    def test_supplied_own_mark_variants_preserve_necessary_work(self):
        for field in ("own_brand", "own_brand_name", "own_brand_logo", "own_logo"):
            with self.subTest(field=field):
                task = deepcopy(self.task)
                task["product"][field] = "supplied-mark"
                self.assertIn("trademark_word", necessary_scenario_right_types(task, self.primary))
        self.task["product"]["brand_role"] = "own"
        self.assertIn("trademark_word", necessary_scenario_right_types(self.task, self.primary))

    def test_actual_product_and_genuine_resale_are_not_skipped(self):
        self.task["product"]["input_role"] = "actual_product"
        self.assertIn("trademark_word", necessary_scenario_right_types(self.task, self.primary))
        resale = default_assessment_scenarios(genuine_resale=True)[2]
        self.assertIn("trademark_word", necessary_scenario_right_types(self.task, resale))

    def test_legacy_does_not_adopt_new_scope_filter(self):
        self.task.pop("decision_workflow_revision")
        self.assertEqual(necessary_scenario_right_types(self.task, self.primary), scenario_right_types(self.primary))

    def test_new_reference_queries_bind_brand_only_without_duplicate_calls(self):
        row = self.row()
        self.assertEqual([b["scenario_id"] for b in row["scenario_bindings"]], ["brand_reuse"])

    def test_frozen_shared_query_remains_valid_and_unmodified(self):
        earlier = deepcopy(self.task)
        earlier["product"]["own_brand"] = "supplied"
        row = self.row(earlier)
        before = sha256_json(row)
        self.assertEqual(len(scenario_row_bindings(self.task, row)), 2)
        self.assertEqual([b["scenario_id"] for b in necessary_scenario_row_bindings(self.task, row)], ["brand_reuse"])
        self.plan["queries"] = {"uspto_tmsearch_browser": [row]}
        self.assertIsNone(scenario_dispatch_block(self.task, self.plan, "uspto_tmsearch_browser", row,
            self.candidates, self.ledger, self.evidence))
        self.assertEqual(sha256_json(row), before)

    def test_primary_only_unnecessary_action_is_not_submitted(self):
        row = self.row()
        row["scenario_bindings"] = [{"scenario_id": "product_entry", "scenario_sha256": self.primary["scenario_sha256"]}]
        identity = {key: value for key, value in row.items() if key not in PLAN_META_KEYS or key in SCENARIO_META_KEYS}
        identity["right_type"] = row["right_type"]
        row["query_id"] = query_identity("uspto_tmsearch_browser", row["operation"], "US", row["q"], identity)
        self.plan["queries"] = {"uspto_tmsearch_browser": [row]}
        blocked = scenario_dispatch_block(self.task, self.plan, "uspto_tmsearch_browser", row, self.candidates, self.ledger, self.evidence)
        self.assertEqual(blocked["code"], "SCENARIO_ACTION_NOT_NECESSARY")
        self.assertEqual(blocked["submission_state"], "not_submitted")
        self.assertEqual(self.evidence["source_runs"], [])

    def test_primary_has_no_reference_mark_obligations_but_brand_keeps_gaps(self):
        scopes = coverage_by_scope(self.task, self.evidence, self.candidates, self.plan, ledger=self.ledger)
        primary = [scope for scope in scopes if scope["scenario_id"] == "product_entry"]
        brand = [scope for scope in scopes if scope["scenario_id"] == "brand_reuse"]
        self.assertEqual([scope["right_type"] for scope in primary], ["patent"])
        self.assertEqual(len(brand), 2)
        self.assertTrue(all(scope["retrieval_status"] == "incomplete" and scope["gaps"] for scope in brand))

    def test_primary_triage_remains_valid_and_visible(self):
        self.ledger["annotations"] = [make_annotation(self.task, "trademarks", self.candidate, {
            "annotation_id": "D1", "scenario_id": "product_entry", "decision": "not_selected", "reason": "No mark reuse assumed",
            "reviewer": "offline", "annotated_at": "2026-09-07T00:00:00Z", "evidence_refs": ["E1"],
            "reading_level": "result_record", "basis_summary": "Reference mark identified", "reopen_conditions": ["Own mark supplied"]}, evidence=self.evidence)]
        before = sha256_json(self.ledger)
        self.assertEqual(triage_ledger_errors(self.task, self.ledger, self.candidates, evidence=self.evidence), [])
        summary = triage_summary(self.task, self.candidates, self.ledger, evidence=self.evidence)
        self.assertEqual(summary["by_scenario"]["product_entry"]["counts"]["not_selected"], 1)
        self.assertEqual(sha256_json(self.ledger), before)


if __name__ == "__main__":
    unittest.main()
