"""best-estimate-risk-v1: a reviewed scoped 低 survives finalization capped, institutions that do not exist are
declared not applicable, an unsupplied own brand never blocks the product grade; tasks without the marker are
byte-for-byte unchanged."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from assessment_estimate import (BEST_ESTIMATE_REVISION, KNOWN_FINDINGS_REVISION, best_estimate_enabled,
                                 compute_assessment, review_digest)
from test_assessment_estimate_scenarios import ScenarioEstimateTests, refresh

INSTITUTION = {"evidence_id": "EV-INST-US-UTILITY_MODEL", "provider": "institution_reference",
    "operation": "jurisdiction_rights_table", "kind": "institution_reference", "jurisdiction": "US",
    "right_type": "utility_model", "collected_at": "2026-10-11T00:00:00+00:00",
    "source_environment": "skill_reference", "authority_scope": "institution_statement_only",
    "reference_revision": "jurisdiction-rights-v1",
    "payload": {"jurisdiction": "US", "right_type": "utility_model", "applicable": False,
                "statement_zh": "美国专利法只设发明、外观与植物三种专利，没有实用新型制度。",
                "statement_en": "USPTO grants utility, design and plant patents; there is no utility model.",
                "source_title": "USPTO - Patents", "source_url": "https://www.uspto.gov/patents"}}


class BestEstimateTests(ScenarioEstimateTests):
    """Reuses the scenario fixture (one selected US trademark_word candidate row per review)."""

    def enable(self):
        self.values[0]["assessment_revision"] = KNOWN_FINDINGS_REVISION
        self.values[0]["best_estimate_revision"] = BEST_ESTIMATE_REVISION
        refresh(self.values)

    def product_low(self, **extra):
        """Turn the candidate row into a product-level 低 without any retrieval receipt behind it."""
        self.rows(candidate_id="", risk="低", evidence_confidence="中", supporting_evidence=[],
                  no_supporting_evidence_reasoning="The bounded search returned no concrete conflicting mark.",
                  counter_evidence=[], no_counter_evidence_reasoning="No exclusion evidence beyond the bounded search.",
                  comparison={"criteria": [], "unresolved": ["Only the first page was reviewed"]},
                  confidence_basis={}, findings=[], **extra)

    def add_row(self, **changes):
        """Append a row derived from the fixture row; nested references default to none so the row's own
        evidence_refs can be set freely."""
        for review in self.values[-2:]:
            row = deepcopy(review["assessments"][0])
            row.update(findings=[], confidence_basis={}, comparison={"criteria": []})
            row.update(deepcopy(changes))
            review["assessments"].append(row)

    # ----- marker ---------------------------------------------------------------------------------------
    def test_marker_requires_known_findings_and_rejects_unknown_values(self):
        task = self.values[0]
        self.assertFalse(best_estimate_enabled(task))
        task["best_estimate_revision"] = BEST_ESTIMATE_REVISION
        self.assertFalse(best_estimate_enabled(task))          # inert without known-findings grading
        task["assessment_revision"] = KNOWN_FINDINGS_REVISION
        self.assertTrue(best_estimate_enabled(task))
        task["best_estimate_revision"] = "best-estimate-risk-v9"
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_BEST_ESTIMATE_REVISION"):
            best_estimate_enabled(task)

    def test_marker_is_bound_into_the_review_digest(self):
        task, evidence, candidates, plan, ledger, *_ = self.values
        task["assessment_revision"] = KNOWN_FINDINGS_REVISION
        before = review_digest(evidence, candidates, ledger, plan, task)
        task["best_estimate_revision"] = BEST_ESTIMATE_REVISION
        self.assertNotEqual(before, review_digest(evidence, candidates, ledger, plan, task))
        with self.assertRaisesRegex(ValueError, "REVIEW_CONTEXT_INVALID"):
            self.calculate()                      # old reviews are not silently re-bound to the new policy

    # ----- scoped 低 ------------------------------------------------------------------------------------
    def test_scoped_low_without_receipt_is_kept_and_capped_under_the_marker(self):
        self.enable()
        self.product_low()
        result = self.calculate()
        row = result["assessments"][0]
        self.assertEqual((row["risk"], row["assessment_status"]), ("低", "assessed"))
        self.assertTrue(row["coverage_limited"])
        self.assertEqual((row["evidence_confidence"], row["reviewed_evidence_confidence"]), ("低", "中"))
        self.assertEqual(result["overall"]["risk"], "低")
        self.assertEqual(result["overall"]["risk_basis"], "known_findings_screening")
        self.assertEqual(result["best_estimate"]["coverage_limited_rows"][0]["right_type"], "trademark_word")

    def test_scoped_low_without_receipt_is_still_erased_without_the_marker(self):
        self.values[0]["assessment_revision"] = KNOWN_FINDINGS_REVISION
        refresh(self.values)
        self.product_low()
        result = self.calculate()
        row = result["assessments"][0]
        self.assertIsNone(row["risk"])
        self.assertEqual((row["assessment_status"], row["reviewed_risk"]), ("pending", "低"))
        self.assertNotIn("coverage_limited", row)
        self.assertNotIn("best_estimate", result)
        self.assertIsNone(result["overall"]["risk"])

    def test_candidate_low_and_extremely_low_keep_their_binding_requirements(self):
        self.enable()
        self.rows(risk="低", supporting_evidence=[], no_supporting_evidence_reasoning="No conflict seen.",
                  counter_evidence=[], no_counter_evidence_reasoning="No bound exclusion.", comparison={"criteria": []})
        row = self.calculate()["assessments"][0]
        self.assertIsNone(row["risk"])                      # a candidate 低 still needs bound counter-evidence
        self.assertEqual(row["reviewed_risk"], "低")
        self.rows(risk="极低", decisive_exclusion={"reasoning": "unbound", "evidence_refs": ["EV-PRODUCT"]})
        row = self.calculate()["assessments"][0]
        self.assertIsNone(row["risk"])

    def test_candidate_high_with_bound_positive_evidence_is_kept(self):
        self.enable()
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["risk"], "高")
        self.assertEqual(result["overall"]["risk"], "高")
        self.assertEqual(result["overall"]["listing_recommendation"], "不建议上架")

    # ----- institution not applicable -------------------------------------------------------------------
    def with_institution(self):
        self.values[1]["collections"]["institution_references"] = [deepcopy(INSTITUTION)]
        refresh(self.values)

    def test_not_applicable_citing_the_shipped_statement_leaves_the_grade_to_other_scopes(self):
        self.enable(); self.with_institution()
        self.add_row(candidate_id="", right_type="utility_model", module_id="utility_patent", risk="低",
                     evidence_confidence="高", supporting_evidence=[], no_supporting_evidence_reasoning="No such right in the US.",
                     counter_evidence=[], no_counter_evidence_reasoning="Institution absent.", comparison={"criteria": []},
                     confidence_basis={}, evidence_refs=["EV-INST-US-UTILITY_MODEL"],
                     scope_applicability={"status": "not_applicable", "reasoning": "该国无此制度，非检索结论。",
                                          "evidence_refs": ["EV-INST-US-UTILITY_MODEL"]})
        result = self.calculate()
        row = result["assessments"][-1]
        self.assertEqual(row["applicability_basis"], "institution_reference")
        self.assertEqual(row["known_finding_status"], "not_applicable")
        self.assertFalse(row["risk_aggregation_included"])
        scope = next(s for s in result["known_findings"]["by_scope"] if s["right_type"] == "utility_model")
        self.assertEqual(scope["applicability"], "not_applicable")
        self.assertEqual(result["overall"]["risk"], "高")      # the candidate row drives the grade, not the 低
        self.assertEqual(result["overall"]["pending_count"], 0)
        self.assertEqual(result["best_estimate"]["institution_not_applicable_scopes"][0]["right_type"], "utility_model")

    def test_program_fills_a_missing_declaration_from_the_table_and_marks_an_unbound_citation(self):
        self.enable(); self.with_institution()
        self.add_row(candidate_id="", right_type="utility_model", module_id="utility_patent", risk=None,
                     assessment_status="pending", pending_reasoning="No institution source in the package.",
                     evidence_confidence="低", supporting_evidence=[], no_supporting_evidence_reasoning="none",
                     counter_evidence=[], no_counter_evidence_reasoning="none", comparison={"criteria": []},
                     confidence_basis={}, evidence_refs=[], scope_applicability=None)
        result = self.calculate()
        row = result["assessments"][-1]
        self.assertEqual(row["applicability_basis"], "program_default")
        self.assertEqual(row["scope_applicability"]["status"], "not_applicable")
        self.assertIn("EV-INST-US-UTILITY_MODEL", row["evidence_refs"])
        self.assertNotIn("ASSESSMENT_PENDING:US:utility_model:", json.dumps(result["coverage"]["completion_gaps"]))
        self.assertEqual(next(s for s in result["known_findings"]["by_scope"] if s["right_type"] == "utility_model")["applicability"],
                         "not_applicable")
        # a declaration citing something that is not the statement for this country/right is kept but flagged
        for review in self.values[-2:]:
            review["assessments"][-1].update(scope_applicability={"status": "not_applicable", "reasoning": "x",
                                                                   "evidence_refs": ["EV-PRODUCT"]},
                                             evidence_refs=["EV-PRODUCT"])
        row = self.calculate()["assessments"][-1]
        self.assertEqual(row["applicability_basis"], "unbound")

    # ----- own brand and enforcement -----------------------------------------------------------------
    def complete_low_task(self):
        """Both scenarios fully assessed 低: the candidate row with bound counter-evidence (fixture comparison),
        the conditional brand scenario likewise, plus a scoped product 低 without a retrieval receipt."""
        self.rows(risk="低", counter_evidence=[{"reasoning": "Documented expression differs.", "evidence_refs": ["EV-PROV"]}])
        self.add_brand_row(risk="低")
        self.add_row(candidate_id="", risk="低", evidence_confidence="中", supporting_evidence=[],
                     no_supporting_evidence_reasoning="The bounded search returned no concrete conflicting mark.",
                     counter_evidence=[], no_counter_evidence_reasoning="No exclusion evidence beyond the bounded search.")

    def test_unsupplied_own_brand_is_disclosed_but_does_not_block_the_recommendation(self):
        self.enable()
        self.complete_low_task()
        self.add_row(candidate_id="", assessment_object="own_brand", risk=None, assessment_status="pending",
                     pending_reasoning="自有品牌名称未提供。", evidence_refs=[], supporting_evidence=[],
                     no_supporting_evidence_reasoning="none", counter_evidence=[], no_counter_evidence_reasoning="none")
        result = self.calculate(complete=True)
        self.assertEqual(result["overall"]["pending_count"], 0)
        own = next(row for row in result["assessments"] if row.get("assessment_object") == "own_brand")
        self.assertEqual(own["known_finding_status"], "own_brand_not_supplied")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["overall"]["risk"], "低")
        self.assertEqual(result["overall"]["listing_recommendation"], "可考虑上架")
        self.assertIn("自有品牌名称／Logo 尚未提供", result["overall"]["listing_reason"])
        self.assertEqual(result["best_estimate"]["own_brand_not_supplied"][0]["right_type"], "trademark_word")
        # the same task with the own brand supplied: the row is ordinary pending work again
        self.values[0]["product"]["own_brand"] = "NOVA"
        refresh(self.values)
        result = self.calculate(complete=True)
        self.assertEqual(result["overall"]["pending_count"], 1)
        self.assertEqual(result["overall"]["listing_recommendation"], "暂缓上架")

    def test_complete_low_task_without_the_marker_keeps_the_historical_recommendation(self):
        self.values[0]["assessment_revision"] = KNOWN_FINDINGS_REVISION
        refresh(self.values)
        self.rows(risk="低", counter_evidence=[{"reasoning": "Documented expression differs.", "evidence_refs": ["EV-PROV"]}])
        self.add_brand_row(risk="低")
        result = self.calculate(complete=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["overall"]["risk"], "低")
        self.assertEqual(result["overall"]["listing_recommendation"], "暂缓上架")   # historical, unchanged

    def test_enforcement_row_participates_in_the_grade_under_the_marker(self):
        self.enable()
        self.product_low()
        self.add_row(candidate_id="", right_type="enforcement", module_id="enforcement", risk="低", evidence_confidence="低",
                     supporting_evidence=[], no_supporting_evidence_reasoning="No confirmed enforcement signal in the bounded search.",
                     counter_evidence=[], no_counter_evidence_reasoning="none", evidence_refs=["EV-PROV", "EV-PRODUCT"])
        result = self.calculate()
        enforcement = next(row for row in result["assessments"] if row["right_type"] == "enforcement")
        self.assertEqual(enforcement["known_finding_status"], "scoped_assessment")
        self.assertTrue(enforcement["risk_aggregation_included"])
        self.assertEqual(result["overall"]["risk"], "低")
        scope = next(s for s in result["known_findings"]["by_scope"] if s["right_type"] == "enforcement")
        self.assertEqual(scope["risk"], "低")
        # without the marker the same row is a signal that never grades
        self.values[0].pop("best_estimate_revision"); refresh(self.values)
        result = self.calculate()
        enforcement = next(row for row in result["assessments"] if row["right_type"] == "enforcement")
        self.assertEqual(enforcement["known_finding_status"], "signal")
        self.assertFalse(enforcement["risk_aggregation_included"])


# the inherited scenario cases are run by their own module
for _name in [name for name in dir(ScenarioEstimateTests) if name.startswith("test_") and name not in vars(BestEstimateTests)]:
    setattr(BestEstimateTests, _name, None)

if __name__ == "__main__":
    unittest.main()


class FeedbackGateTests(unittest.TestCase):
    def test_structure_the_user_cannot_provide_no_longer_blocks_a_graded_candidate(self):
        import product_feedback as pf
        identity = "p" * 64
        task = {"best_estimate_revision": "best-estimate-risk-v1", "assessment_revision": "known-findings-risk-v1",
                "product_feedback_revision": pf.REVISION, "product_structure_policy": pf.STRUCTURE_POLICY,
                "product_identity": {"sha256": identity},
                "product_feedback_history": [{"kind": "unavailable", "request_id": "R1", "target_sha256": identity,
                    "candidate_id": "CAND-1", "structure_classification": {"basis": "explicit_information_category",
                                                                            "category": "actual_structure"}}]}
        rows = [{"candidate_id": "CAND-1", "risk": "高"}, {"candidate_id": "CAND-2", "risk": "低"}]
        pf.assessment_gate(task, rows)                                   # disclosed limitation, grade kept
        with self.assertRaisesRegex(ValueError, "PRODUCT_FEEDBACK_COMPARISON_PENDING"):
            pf.assessment_gate({**task, "best_estimate_revision": None}, rows)     # historical policy unchanged
        task["product_feedback_history"].append({"kind": "requested", "request_id": "R2", "target_sha256": identity,
                                                 "candidate_id": "CAND-1", "information_category": "other"})
        with self.assertRaisesRegex(ValueError, "PRODUCT_FEEDBACK_COMPARISON_PENDING"):
            pf.assessment_gate(task, rows)                               # a question still awaiting the user blocks
