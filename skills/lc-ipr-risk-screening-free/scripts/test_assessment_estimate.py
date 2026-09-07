"""Offline regressions for the versioned five-level estimate policy."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from common import atomic_write_json, now_iso, sha256_file, sha256_json
from assessment_estimate import (POLICY, compute_assessment, finalize,
                                 review_digest, validate_assessment, validate_supplement,
                                 _row_conflicts)
from assessment_v24 import compute_assessment as legacy_compute
from test_assessment_v24 import setup_scope


def fixture(directory):
    values = list(setup_scope(directory))
    task, evidence, candidates, plan, ledger, first, second = values
    task["assessment_policy"] = POLICY
    row = first["assessments"][0]
    row.update(module_id="copyright_ip", title="Specific artwork", scope="US proposed matching product expression",
               supporting_evidence=[{"reasoning": "The retained source and proposed product reproduce specific expression.", "evidence_refs": ["EV-PROV", "EV-PRODUCT"]}],
               counter_evidence=[], no_counter_evidence_reasoning="No exclusion was found in the retained evidence.",
               assumptions=["The proposed product retains the linked design."],
               confidence_reasoning="The source and comparison are directly retained.",
               human_checks=[{"priority": "normal", "owner": "US copyright counsel", "question": "Confirm the licence scope.", "evidence_needed": "Signed licence", "raise_if": [], "lower_if": ["Valid licence found"]}],
               raise_if=["Additional applicable rights are confirmed."], lower_if=["An applicable licence is obtained."])
    second["assessments"] = deepcopy(first["assessments"])
    for review in (first, second):
        review.update(coverage_confidence_cap="中", coverage_confidence_reasoning="Limited scopes were examined; remaining scopes may affect the conclusion.")
        review["review_context"]["evidence_digest"] = review_digest(evidence, candidates, ledger, plan, task)
    return values


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.values = fixture(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def calculate(self, **kwargs):
        return compute_assessment(*self.values, **kwargs)

    def refresh(self, supplement=None):
        task, evidence, candidates, plan, ledger, first, second = self.values
        digest = review_digest(evidence, candidates, ledger, plan, task, supplement)
        for review in (first, second):
            review["review_context"]["evidence_digest"] = digest

    def change_rows(self, **changes):
        for review in self.values[-2:]:
            review["assessments"][0].update(deepcopy(changes))

    def adjudication(self, row=None):
        first, second = self.values[-2:]
        decision = deepcopy(row or first["assessments"][0])
        decision.update(adjudication_reasoning="The specific correspondence remains material, while the documented differences limit the strength of that inference.",
                        review_refs={"first": sha256_json(first), "second": sha256_json(second)})
        return {"reviewer": "chief", "review_context": {"session_id": "chief-session", "evidence_digest": first["review_context"]["evidence_digest"]}, "decisions": [decision]}

    def test_keeps_grade_with_real_coverage_gaps(self):
        result = self.calculate()
        self.assertEqual(result["overall"]["risk"], "高")
        self.assertEqual(result["overall"]["confidence"], "中")
        self.assertEqual(result["status"], "completed")
        self.assertTrue(any(scope["gaps"] for scope in result["coverage"]["scopes"]))
        self.assertFalse(result["overall"]["all_scope_clearance"])

    def test_failed_query_does_not_automatically_become_medium(self):
        self.change_rows(risk="低", evidence_confidence="低", supporting_evidence=[],
                         no_supporting_evidence_reasoning="The limited completed search found no concrete conflicting right.")
        self.values[1]["source_runs"].append({"run_id": "FAIL", "provider": "public_web_browser", "status": "access_limited"})
        self.refresh()
        self.assertEqual(self.calculate()["overall"]["risk"], "低")

    def test_similarity_metadata_does_not_automatically_become_high(self):
        self.change_rows(risk="中", evidence_confidence="低", similarity_percent=100)
        self.assertEqual(self.calculate()["overall"]["risk"], "中")

    def test_many_low_rows_do_not_dilute_high(self):
        for review in self.values[-2:]:
            low = deepcopy(review["assessments"][0])
            low.update(jurisdiction="GB", candidate_id="", risk="低", evidence_confidence="低", supporting_evidence=[],
                       no_supporting_evidence_reasoning="No specific conflicting candidate found in limited GB review.")
            review["assessments"].append(low)
        self.assertEqual(self.calculate()["overall"]["risk"], "高")

    def test_confidence_basis_conflicts_have_stable_order(self):
        left = {"risk": "低", "confidence_basis": {"z": {"satisfied": True}, "a": {"satisfied": True}}}
        right = {"risk": "低", "confidence_basis": {}}
        self.assertEqual(_row_conflicts(left, right), ["confidence_basis:a", "confidence_basis:z"])

    def test_same_source_and_application_metadata_adds_no_weight(self):
        self.change_rows(risk="低", application_number="17/234059", duplicate_sources=["page-1"] * 100)
        self.assertEqual(self.calculate()["overall"]["risk"], "低")

    def test_unknown_own_brand_is_explicitly_outside_scope(self):
        for review in self.values[-2:]:
            review["assessments"].append({"jurisdiction": "US", "right_type": "trademark_word", "candidate_id": "", "module_id": "word_mark", "title": "Unknown user brand", "out_of_scope": True, "risk": None, "scope_exclusion_basis": "unknown_own_brand", "scope_reasoning": "User brand name was not supplied."})
        result = self.calculate()
        self.assertEqual(result["overall"]["risk"], "高")
        self.assertFalse(result["assessments"][-1]["aggregation_included"])

    def test_historical_enforcement_is_not_a_current_risk_driver(self):
        self.change_rows(risk="低")
        for review in self.values[-2:]:
            review["enforcement_signals"] = [{"reasoning": "An unrelated historical complaint exists.", "evidence_refs": ["EV-PROV"], "risk": "极高"}]
        self.assertEqual(self.calculate()["overall"]["risk"], "低")

    def test_future_signal_is_not_a_current_risk_driver(self):
        for review in self.values[-2:]:
            current = deepcopy(review["assessments"][0])
            current.update(jurisdiction="GB", candidate_id="", risk="低", supporting_evidence=[], no_supporting_evidence_reasoning="Limited GB findings are negative.")
            review["assessments"].append(current)
            review["assessments"][0]["future_signal"] = True
        self.assertEqual(self.calculate()["overall"]["risk"], "低")

    def test_disagreement_requires_explicit_chief_judgment(self):
        self.values[-1]["assessments"][0]["risk"] = "低"
        with self.assertRaisesRegex(ValueError, "ADJUDICATION_REQUIRED"):
            self.calculate()
        row = deepcopy(self.values[-2]["assessments"][0])
        row.update(risk="中", evidence_confidence="低")
        result = self.calculate(adjudication=self.adjudication(row))
        self.assertEqual(result["overall"]["risk"], "中")
        self.assertEqual(result["overall"]["confidence"], "低")
        self.assertEqual(result["assessments"][0]["review_resolution"]["method"], "chief_adjudication")

    def test_chief_can_select_lower_not_mechanical_maximum(self):
        self.values[-1]["assessments"][0]["risk"] = "低"
        row = deepcopy(self.values[-1]["assessments"][0])
        self.assertEqual(self.calculate(adjudication=self.adjudication(row))["overall"]["risk"], "低")

    def test_adjudication_is_bound_to_both_exact_reviews(self):
        adjudication = self.adjudication()
        self.values[-1]["assessments"][0]["reasoning"] = "Changed independent explanation"
        with self.assertRaisesRegex(ValueError, "REVIEW_BINDING_INVALID"):
            self.calculate(adjudication=adjudication)

    def test_no_positive_evidence_cannot_be_medium(self):
        self.change_rows(risk="中", supporting_evidence=[], no_supporting_evidence_reasoning="Only a failed query exists.")
        with self.assertRaisesRegex(ValueError, "SPECIFIC_POSITIVE_CONFLICT_REQUIRED"):
            self.calculate()

    def test_very_low_requires_decisive_scoped_exclusion(self):
        self.change_rows(risk="极低", evidence_confidence="高")
        with self.assertRaisesRegex(ValueError, "DECISIVE_SCOPED_EXCLUSION_REQUIRED"):
            self.calculate()
        self.change_rows(decisive_exclusion={"reasoning": "This specific right has a documented terminal exclusion.", "evidence_refs": ["EV-PROV"]})
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["evidence_confidence"], "高")
        self.assertEqual(result["assessments"][0]["risk"], "极低")
        self.assertEqual(result["overall"]["risk"], "低")
        self.assertEqual(result["overall"]["confidence"], "低")

    def test_scoped_expiry_cannot_become_product_clearance(self):
        self.change_rows(risk="极低", evidence_confidence="高", decisive_exclusion={"reasoning": "The specific patent expired.", "evidence_refs": ["EV-PROV"]})
        for review in self.values[-2:]:
            review["coverage_confidence_cap"] = "高"
        result = self.calculate()
        self.assertEqual(result["overall"]["risk"], "低")
        self.assertEqual(result["overall"]["confidence"], "低")
        self.assertIn("决定性排除仅针对", " ".join(result["overall"]["reasons"]))

    def test_overall_very_low_needs_bound_chief_exclusion(self):
        self.change_rows(risk="极低", evidence_confidence="高", decisive_exclusion={"reasoning": "The specific right expired.", "evidence_refs": ["EV-PROV"]})
        chief = self.adjudication()
        chief["overall_decisive_exclusion"] = {"scope": "Only the explicitly reviewed right is evaluated.", "reasoning": "The overall declared evaluation scope is limited to this expired right.", "evidence_refs": ["EV-PROV"]}
        result = self.calculate(adjudication=chief)
        self.assertEqual(result["overall"]["risk"], "极低")
        self.assertEqual(result["overall"]["confidence"], "低")

    def test_global_confidence_override_requires_exact_review_binding(self):
        chief = self.adjudication()
        chief.update(decisions=[], coverage_confidence_cap="高", coverage_confidence_reasoning="Reviewed the whole declared scope.")
        with self.assertRaisesRegex(ValueError, "GLOBAL_ADJUDICATION_REVIEW_BINDING_REQUIRED"):
            self.calculate(adjudication=chief)
        chief["review_refs"] = {"first": sha256_json(self.values[-2]), "second": sha256_json(self.values[-1])}
        self.assertEqual(self.calculate(adjudication=chief)["overall"]["confidence"], "高")

    def test_no_candidate_cannot_receive_high(self):
        self.change_rows(candidate_id="")
        with self.assertRaisesRegex(ValueError, "SPECIFIC_POSITIVE_CONFLICT_REQUIRED"):
            self.calculate()

    def test_old_unknown_label_is_not_an_estimate(self):
        self.change_rows(risk="无法判断")
        with self.assertRaisesRegex(ValueError, "FIVE_LEVEL_RISK"):
            self.calculate()

    def test_independent_identity_and_digest_required(self):
        self.values[-1]["review_context"]["session_id"] = self.values[-2]["review_context"]["session_id"]
        with self.assertRaisesRegex(ValueError, "SECOND_REVIEW_NOT_INDEPENDENT"):
            self.calculate()
        self.values[-1]["review_context"]["session_id"] = "different"
        self.values[3]["generated_at"] = "changed"
        with self.assertRaisesRegex(ValueError, "REVIEW_CONTEXT_INVALID"):
            self.calculate()

    def test_policy_requires_explicit_selection_for_old_tasks(self):
        del self.values[0]["assessment_policy"]
        with self.assertRaisesRegex(ValueError, "POLICY_NOT_SELECTED"):
            self.calculate()

    def test_original_artifact_hash_tampering_rejected(self):
        (self.directory / "source.txt").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "HASH_OR_SIZE_MISMATCH"):
            self.calculate()

    def test_unknown_argument_reference_rejected(self):
        self.values[-2]["assessments"][0]["supporting_evidence"][0]["evidence_refs"] = ["FAKE"]
        with self.assertRaisesRegex(ValueError, "EVIDENCE_ARGUMENT_INVALID"):
            self.calculate()

    def supplement(self):
        path = self.directory / "native-source.txt"
        path.write_text("Retained original status capture")
        return {"schema": "IPR-EVIDENCE-SUPPLEMENT/1.0", "evidence": [{"evidence_id": "EV-NATIVE", "path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size, "source_url": "https://example.org/status", "kind": "official_record", "checked_at": now_iso()}], "coverage_notes": ["Native evidence has not been imported as an adapter receipt."]}

    def test_real_native_supplement_is_hashed_not_promoted_to_adapter(self):
        supplement = self.supplement()
        self.refresh(supplement)
        result = self.calculate(supplement=supplement, evidence_root=self.directory)
        self.assertFalse(result["supplement_provenance"]["adapter_acceptance_claimed"])
        self.assertEqual(result["supplement_provenance"]["evidence_count"], 1)
        (self.directory / "native-source.txt").write_text("changed")
        with self.assertRaisesRegex(ValueError, "HASH_OR_SIZE_MISMATCH"):
            self.calculate(supplement=supplement, evidence_root=self.directory)

    def test_supplement_path_cannot_escape_evidence_root(self):
        supplement = self.supplement()
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaisesRegex(ValueError, "OUTSIDE_EVIDENCE_ROOT"):
                validate_supplement(supplement, other)

    def test_local_original_has_document_source_without_invented_url(self):
        supplement = self.supplement()
        item = supplement["evidence"][0]
        del item["source_url"]
        item.update(source_document=item["path"], kind="historical_review",
                    source_checked_at="2026-09-06", checked_at_meaning="retained_file_hash_verification")
        self.assertEqual(len(validate_supplement(supplement, self.directory)), 1)
        del item["source_document"]
        with self.assertRaisesRegex(ValueError, "SOURCE_URL_OR_DOCUMENT_REQUIRED"):
            validate_supplement(supplement, self.directory)

    def test_mock_sources_cannot_be_promoted_as_real_evidence(self):
        self.values[1]["source_runs"][0]["source_environment"] = "mock"
        self.refresh()
        with self.assertRaisesRegex(ValueError, "NON_PRODUCTION_EVIDENCE"):
            self.calculate()

    def test_broken_original_claim_refs_are_rejected(self):
        self.change_rows(comparison={"claims": [{"claim_id": "1", "elements": [], "claim_evidence_refs": ["MISSING"]}]})
        with self.assertRaisesRegex(ValueError, "CLAIM_ORIGINAL_EVIDENCE_REQUIRED"):
            self.calculate()

    def test_supplement_cannot_shadow_existing_evidence(self):
        supplement = self.supplement()
        supplement["evidence"][0]["evidence_id"] = "EV-PRODUCT"
        self.refresh(supplement)
        with self.assertRaisesRegex(ValueError, "EVIDENCE_ID_COLLISION"):
            self.calculate(supplement=supplement, evidence_root=self.directory)

    def test_finalization_to_new_output_preserves_inputs_and_recomputes(self):
        task, evidence, candidates, plan, ledger, first, second = self.values
        for name, value in (("task", task), ("evidence", evidence), ("normalized-candidates", candidates), ("search-plan", plan), ("materiality-annotations", ledger), ("first", first), ("second", second)):
            atomic_write_json(self.directory / (name + ".json"), value)
        original_hash = sha256_file(self.directory / "task.json")
        destination = self.directory / "new-output"
        result = finalize(self.directory, task, self.directory / "first.json", self.directory / "second.json", output_dir=destination, evidence_root=self.directory)
        self.assertEqual(original_hash, sha256_file(self.directory / "task.json"))
        self.assertEqual(validate_assessment(self.directory, task, result), [])
        result["overall"]["risk"] = "低"
        self.assertTrue(validate_assessment(self.directory, task, result))

    def test_historical_engine_behavior_is_unchanged(self):
        values = setup_scope(self.directory)
        result = legacy_compute(*values)
        self.assertEqual(result["overall"]["risk"], "")
        self.assertEqual(result["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
