"""Business-completion regressions; these do not claim live patent recall."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from common import RECALL_INTEGRITY_REVISION, sha256_json
from assessment_estimate import compute_assessment, review_digest
from test_assessment_estimate import fixture
from workflow_v24 import build_coverage_requirements_v24, product_identity_digest


def strict_fixture(directory):
    values = fixture(directory)
    task, evidence, candidates, plan, ledger, first, second = values
    task["screening_revision"] = RECALL_INTEGRITY_REVISION
    plan["screening_revision"] = RECALL_INTEGRITY_REVISION
    task["coverage_requirements"] = build_coverage_requirements_v24(task["target_jurisdictions"], screening_revision=RECALL_INTEGRITY_REVISION)
    task["product"]["structure"] = ["Flexible loop strap"]
    task["query_terms"] = [{"value": "lid AND strap", "kind": "product", "language": "en", "derived_from": "product.structure[0]"}]
    task["product"]["analysis"] = {"status": "confirmed", "identity_sha256": product_identity_digest(task["product"])}
    refresh(values)
    return values


def refresh(values):
    task, evidence, candidates, plan, ledger, first, second = values
    digest = review_digest(evidence, candidates, ledger, plan, task)
    for review in (first, second):
        review["review_context"]["evidence_digest"] = digest


class RecallEstimateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.values = strict_fixture(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def rows(self, **changes):
        for review in self.values[-2:]:
            review["assessments"][0].update(deepcopy(changes))

    def calculate(self):
        return compute_assessment(*self.values)

    def negative_design(self):
        self.rows(candidate_id="", right_type="design", module_id="appearance_patent", risk="低",
                  evidence_confidence="低", supporting_evidence=[], no_supporting_evidence_reasoning="No candidate was returned.",
                  counter_evidence=[{"reasoning": "The product page has no patent number.", "evidence_refs": ["EV-PRODUCT"]}],
                  comparison={"criteria": [], "unresolved": ["Search not complete"]}, confidence_basis={}, findings=[])

    def add_query(self, status="no_result", right="design", total=0, retrieved=0, truncated=False):
        task, evidence, candidates, plan, *_ = self.values
        requirement = next(r for r in task["coverage_requirements"] if r["jurisdiction"] == "US" and r["right_type"] == right and r["phase"] == "official_recall")
        route = next(r for r in requirement["routes"] if r["provider"] == "epo_ops")
        query = {"query_id": "Q-RECALL", "provider": "epo_ops", "operation": route["operation"],
                 "jurisdiction": "US", "right_type": right, "requirement_ids": [requirement["requirement_id"]],
                 "q": "lid AND strap", "execute_by_default": True, "search_dimension": "text", "search_language": "en", "execution_phase": "initial"}
        plan["queries"]["epo_ops"] = [query]
        run = {"run_id": "R-RECALL", **query, "status": status, "plan_entry_sha256": sha256_json(query),
               "source_environment": "production", "authoritative_for_final_rating": True,
               "metadata": {"search_coverage": {"schema_valid": True, "total_hits": total, "retrieved_hits": retrieved,
                            "truncated": truncated, "stop_reason": "all_results_retrieved"}}}
        evidence["source_runs"].append(run)
        entry = {"evidence_id": "EV-RECALL", "source_run_id": run["run_id"], "payload": {"candidates": []},
                 **{key: run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "requirement_ids", "plan_entry_sha256")}}
        evidence["collections"]["patents"] = [entry]
        refresh(self.values)
        return query, run, entry

    def test_revision_is_bound_to_independent_review_digest(self):
        before = self.values[-1]["review_context"]["evidence_digest"]
        self.values[0].pop("screening_revision")
        task, evidence, candidates, plan, ledger, *_ = self.values
        self.assertNotEqual(before, review_digest(evidence, candidates, ledger, plan, task))

    def test_identity_planning_inputs_are_bound_without_changing_legacy_digest(self):
        task, evidence, candidates, plan, ledger, *_ = self.values
        before = review_digest(evidence, candidates, ledger, plan, task)
        task["recall_planning_revision"] = "identity-discovery-v1"
        baseline = review_digest(evidence, candidates, ledger, plan, task)
        self.assertNotEqual(before, baseline)
        task["query_terms"].append({"value": "product name patent", "kind": "ocr", "language": "en"})
        self.assertNotEqual(baseline, review_digest(evidence, candidates, ledger, plan, task))
        task["query_terms"].pop()
        task["discovery_followups"] = [{"reason": "Independent index recall required"}]
        self.assertNotEqual(baseline, review_digest(evidence, candidates, ledger, plan, task))
        task.pop("recall_planning_revision")
        self.assertEqual(before, review_digest(evidence, candidates, ledger, plan, task))

    def test_specific_high_survives_but_whole_task_is_not_complete(self):
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["risk"], "高")
        self.assertEqual(result["overall"]["known_scoped_risk"], "高")
        self.assertIsNone(result["overall"]["risk"])
        self.assertEqual(result["status"], "incomplete")

    def test_all_failed_design_cannot_publish_low(self):
        self.negative_design()
        self.add_query(status="access_limited")
        result = self.calculate()
        row = result["assessments"][0]
        self.assertIsNone(row["risk"])
        self.assertEqual(row["assessment_status"], "pending")
        self.assertFalse(row["aggregation_included"])
        self.assertEqual(row["counter_evidence"], [])
        self.assertIsNone(result["overall"]["known_scoped_risk"])
        self.assertIn("未取得降低风险", row["no_counter_evidence_reasoning"])

    def test_pending_is_not_a_sixth_risk_level(self):
        self.negative_design()
        self.rows(risk=None, assessment_status="pending", pending_reasoning="Not submitted.", evidence_refs=[], counter_evidence=[],
                  no_counter_evidence_reasoning="None available.", confidence_basis={})
        result = self.calculate()
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["assessments"][0]["risk"])

    def test_pending_label_cannot_hide_a_grade(self):
        self.rows(assessment_status="pending", pending_reasoning="Awaiting evidence")
        with self.assertRaisesRegex(ValueError, "PENDING_ASSESSMENT"):
            self.calculate()

    def test_valid_zero_with_bound_comparison_can_keep_scoped_low(self):
        self.negative_design()
        self.add_query()
        self.rows(evidence_refs=["EV-PRODUCT", "EV-RECALL"], search_comparison={"reasoning": "The retained result set was valid and contained zero designs for this grouped feature search.", "evidence_refs": ["EV-RECALL"]})
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["risk"], "低")
        self.assertEqual(result["overall"]["known_scoped_risk"], "低")
        self.assertIsNone(result["overall"]["risk"])

    def test_zero_without_comparison_does_not_become_low(self):
        self.negative_design()
        self.add_query()
        self.assertIsNone(self.calculate()["assessments"][0]["risk"])

    def test_literal_or_uncompiled_uspto_zero_is_not_qualified_recall(self):
        self.negative_design()
        query, run, entry = self.add_query()
        query.update(provider="uspto_patent_browser", operation="design_recall", strategy="advanced_literal_phrase",
                     q="This patented product fits every favorite pot in the kitchen", filters={"field": "product", "language": "en"})
        self.values[3]["queries"].pop("epo_ops")
        self.values[3]["queries"]["uspto_patent_browser"] = [query]
        for record in (run, entry):
            record.update(provider=query["provider"], operation=query["operation"], plan_entry_sha256=sha256_json(query))
        self.rows(evidence_refs=["EV-PRODUCT", "EV-RECALL"], search_comparison={"reasoning": "No rows found", "evidence_refs": ["EV-RECALL"]})
        refresh(self.values)
        self.assertIsNone(self.calculate()["assessments"][0]["risk"])
        query.update(strategy="boolean", q="lid AND strap")
        for record in (run, entry):
            record["plan_entry_sha256"] = sha256_json(query)
        refresh(self.values)
        # Even valid planned syntax cannot substitute for a retained execution
        # receipt proving that this syntax was actually used.
        self.assertIsNone(self.calculate()["assessments"][0]["risk"])

    def test_wrong_right_zero_cannot_support_design_low(self):
        self.negative_design()
        self.add_query(right="patent")
        self.rows(evidence_refs=["EV-PRODUCT", "EV-RECALL"], search_comparison={"reasoning": "No patents found", "evidence_refs": ["EV-RECALL"]})
        self.assertIsNone(self.calculate()["assessments"][0]["risk"])

    def test_truncated_or_unknown_result_cannot_support_negative_clearance(self):
        self.negative_design()
        self.add_query(total=20, retrieved=0, truncated=True, status="success")
        self.rows(evidence_refs=["EV-PRODUCT", "EV-RECALL"], search_comparison={"reasoning": "Only part of results retrieved", "evidence_refs": ["EV-RECALL"]})
        result = self.calculate()
        self.assertIsNone(result["assessments"][0]["risk"])
        self.assertEqual(result["coverage"]["execution_gaps"][0]["code"], "SEARCH_RESULT_TRUNCATED")

    def test_unexecuted_expansion_is_not_complete(self):
        query, _, _ = self.add_query()
        self.values[3]["queries"]["epo_ops"].append({**query, "query_id": "Q-EXPANSION", "q": "cover AND retainer", "execution_phase": "expansion"})
        refresh(self.values)
        result = self.calculate()
        self.assertIn("PLANNED_QUERY_NOT_EXECUTED:Q-EXPANSION", result["coverage"]["completion_gaps"])

    def test_marketing_claim_cannot_close_patent_followup(self):
        product = self.values[0]["product"]
        product["visible_ip_claims"] = ["PATENTED universal fit"]
        product["patent_claim_followup"] = {"status": "completed", "evidence_ids": ["EV-PRODUCT"], "findings": "The listing says patented."}
        refresh(self.values)
        result = self.calculate()
        self.assertIn("PATENT_CLAIM_FOLLOWUP_EVIDENCE_INVALID", result["coverage"]["completion_gaps"])

    def test_documented_decisive_exclusion_stays_scoped(self):
        self.rows(risk="极低", decisive_exclusion={"reasoning": "Retained licence excludes this specific artwork use.", "evidence_refs": ["EV-PROV"]})
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["risk"], "极低")
        self.assertEqual(result["overall"]["known_scoped_risk"], "极低")
        self.assertIn("已评范围最高为极低风险", result["overall"]["report_lead"])
        self.assertIsNone(result["overall"]["risk"])

    def test_optional_discovery_failure_does_not_remove_specific_risk(self):
        self.values[1]["source_runs"].append({"run_id": "OPTIONAL", "provider": "serper_images", "status": "failed"})
        refresh(self.values)
        result = self.calculate()
        self.assertEqual(result["overall"]["known_scoped_risk"], "高")
        self.assertFalse(result["coverage"]["execution_gaps"])


if __name__ == "__main__":
    unittest.main()
