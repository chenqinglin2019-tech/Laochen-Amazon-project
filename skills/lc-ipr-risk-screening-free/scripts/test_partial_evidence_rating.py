"""Offline rating-only regressions; no authentication or source calls are made."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from assessment_estimate import (PARTIAL_EVIDENCE_REVISION, compute_assessment,
    finalize, partial_evidence_enabled, report_input_context, review_digest,
    validate_assessment)
from common import atomic_write_bytes, atomic_write_json, sha256_file
from test_assessment_estimate_recall import strict_fixture, refresh
from test_assessment_estimate_scenarios import scenario_fixture


class PartialEvidenceRatingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ipr-partial-rating-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.values = scenario_fixture(self.directory)
        self.enable()

    def enable(self):
        self.values[0]["assessment_revision"] = PARTIAL_EVIDENCE_REVISION
        refresh(self.values)

    def rows(self, **changes):
        for review in self.values[-2:]:
            review["assessments"][0].update(deepcopy(changes))

    def pending_without_rights_evidence(self):
        task, evidence, candidates, plan, ledger, *_ = self.values
        candidates["trademarks"] = []
        ledger["annotations"] = []
        evidence["source_runs"] = []
        evidence["collections"].pop("asset_provenance", None)
        plan["queries"] = {}
        self.rows(candidate_id="", risk=None, assessment_status="pending",
            pending_reasoning="No rights query has been executed.",
            evidence_refs=[], supporting_evidence=[], counter_evidence=[],
            no_supporting_evidence_reasoning="No rights evidence available.",
            no_counter_evidence_reasoning="No exclusion evidence available.",
            comparison={"criteria": [], "unresolved": ["Rights search not executed."]},
            confidence_basis={}, findings=[])
        refresh(self.values)

    def save_inputs(self):
        for name, value in zip(("task", "evidence", "normalized-candidates", "search-plan",
                               "materiality-annotations", "first-review", "second-review"), self.values):
            atomic_write_json(self.directory / (name + ".json"), value)

    def test_zero_effective_queries_falls_back_without_claiming_completion(self):
        self.pending_without_rights_evidence()
        originals = deepcopy(self.values)
        result = compute_assessment(*self.values)
        row = result["assessments"][0]
        self.assertEqual((result["overall"]["risk"], result["overall"]["confidence"], result["status"]), ("低", "低", "incomplete"))
        self.assertEqual((row["risk"], row["risk_basis"], row["assessment_status"]), ("低", "policy_fallback", "pending"))
        self.assertFalse(row["aggregation_included"])
        self.assertTrue(row["risk_aggregation_included"])
        self.assertTrue(result["coverage"]["completion_gaps"])
        self.assertIsNone(result["review"]["input_reviews"]["first"]["assessments"][0]["risk"])
        self.assertEqual(self.values, originals)

    def test_specific_medium_high_and_very_high_are_not_diluted(self):
        for risk in ("中", "高", "极高"):
            with self.subTest(risk=risk):
                self.rows(risk=risk)
                result = compute_assessment(*self.values)
                self.assertEqual(result["overall"]["risk"], risk)
                self.assertEqual(result["overall"]["risk_basis"], "evidence_supported")
                self.assertEqual(result["assessments"][0]["risk_basis"], "evidence_supported")
                self.assertEqual(result["assessments"][0]["evidence_confidence"], "低")
                self.assertEqual(result["overall"]["confidence"], "低")

    def test_incomplete_very_low_is_not_the_fallback_grade(self):
        self.rows(risk="极低", decisive_exclusion={"reasoning": "Retained licence excludes this artwork use.", "evidence_refs": ["EV-PROV"]})
        result = compute_assessment(*self.values)
        self.assertEqual(result["assessments"][0]["risk"], "低")
        self.assertEqual(result["assessments"][0]["evidence_supported_risk"], "极低")
        self.assertEqual(result["overall"]["risk"], "低")

    def test_evidence_supported_local_low_does_not_clear_incomplete_scenario(self):
        self.rows(risk="低", counter_evidence=[{"reasoning": "Specific scoped exclusion.", "evidence_refs": ["EV-PROV"]}])
        result = compute_assessment(*self.values)
        self.assertEqual(result["assessments"][0]["risk_basis"], "evidence_supported")
        self.assertEqual((result["overall"]["risk"], result["overall"]["risk_basis"]), ("低", "policy_fallback"))
        self.assertEqual(result["scenario_summaries"][0]["risk_basis"], "policy_fallback")
        self.assertEqual(result["status"], "incomplete")

    def test_unsupported_positive_assertion_is_not_confirmed_risk(self):
        self.rows(supporting_evidence=[{"reasoning": "The product is similar.", "evidence_refs": ["EV-PRODUCT"]}],
                  confidence_basis={})
        result = compute_assessment(*self.values)
        self.assertEqual(result["overall"]["risk"], "低")
        self.assertEqual(result["assessments"][0]["risk_basis"], "policy_fallback")
        self.assertEqual(result["assessments"][0]["reviewed_risk"], "高")

    def test_empty_positive_evidence_is_still_an_invalid_review(self):
        self.rows(supporting_evidence=[], no_supporting_evidence_reasoning="Only missing evidence.")
        with self.assertRaisesRegex(ValueError, "SPECIFIC_POSITIVE_CONFLICT_REQUIRED"):
            compute_assessment(*self.values)

    def test_revision_is_digest_bound_and_old_tasks_keep_original_semantics(self):
        task, evidence, candidates, plan, ledger, *_ = self.values
        revised_digest = review_digest(evidence, candidates, ledger, plan, task)
        task.pop("assessment_revision")
        self.assertFalse(partial_evidence_enabled(task))
        self.assertNotEqual(revised_digest, review_digest(evidence, candidates, ledger, plan, task))
        refresh(self.values)
        legacy = compute_assessment(*self.values)
        self.assertEqual(legacy["overall"]["risk"], "高")
        self.assertEqual(legacy["assessments"][0]["evidence_confidence"], "高")
        self.assertNotIn("risk_basis", legacy["assessments"][0])
        self.assertNotIn("assessment_revision", legacy)

    def test_unknown_or_null_revision_is_rejected(self):
        for revision in ("next-unknown", "", None):
            with self.subTest(revision=revision):
                self.values[0]["assessment_revision"] = revision
                with self.assertRaisesRegex(ValueError, "UNSUPPORTED_ASSESSMENT_REVISION"):
                    compute_assessment(*self.values)

    def test_older_workflow_requires_explicit_migration_not_silent_reinterpretation(self):
        self.values = strict_fixture(self.directory)
        self.enable()
        with self.assertRaisesRegex(ValueError, "REQUIRES_RECALL_INTEGRITY_AND_SCENARIO_WORKFLOW"):
            compute_assessment(*self.values)

    def test_unconfirmed_or_stale_identity_cannot_be_low_fallback(self):
        self.pending_without_rights_evidence()
        task = self.values[0]
        analysis = deepcopy(task["product"]["analysis"])
        for invalid in ({}, {**analysis, "status": "pending"}, {**analysis, "identity_sha256": "0" * 64}):
            with self.subTest(analysis=invalid):
                task["product"]["analysis"] = invalid
                refresh(self.values)
                with self.assertRaisesRegex(ValueError, "PRODUCT_IDENTITY_NOT_CONFIRMED"):
                    compute_assessment(*self.values)

    def test_missing_query_terms_remain_gap_not_identity_failure(self):
        self.pending_without_rights_evidence()
        self.values[0]["query_terms"] = []
        refresh(self.values)
        result = compute_assessment(*self.values)
        self.assertEqual(result["overall"]["risk"], "低")
        self.assertIn("QUERY_TERMS_MISSING", result["scenario_summaries"][0]["completion"]["gaps"])

    def test_future_and_out_of_scope_rows_are_not_low_fallbacks(self):
        scenario = self.values[0]["assessment_scenarios"][1]
        for review in self.values[-2:]:
            future = deepcopy(review["assessments"][0])
            future.update(scenario_id=scenario["scenario_id"], scenario_sha256=scenario["scenario_sha256"], future_signal=True)
            review["assessments"].append(future)
            review["assessments"].append({"jurisdiction": "US", "right_type": "trademark_word", "candidate_id": "", "module_id": "word_mark", "title": "Unknown user brand", "out_of_scope": True, "risk": None, "scope_exclusion_basis": "unknown_own_brand", "scope_reasoning": "User brand name was not supplied.",
                "scenario_id": future["scenario_id"], "scenario_sha256": future["scenario_sha256"]})
        result = compute_assessment(*self.values)
        excluded = [row for row in result["assessments"] if row.get("future_signal") or row.get("out_of_scope")]
        self.assertEqual(len(excluded), 2)
        self.assertTrue(all(not row["risk_aggregation_included"] for row in excluded))
        self.assertTrue(all("risk_basis" not in row for row in excluded))

    def test_complete_queries_keep_five_grade_evidence_and_confidence_rules(self):
        self.values[0]["assessment_scenarios"] = self.values[0]["assessment_scenarios"][:1]
        self.values[4]["annotations"] = self.values[4]["annotations"][:1]
        refresh(self.values)
        scenario = self.values[0]["assessment_scenarios"][0]
        coverage = [{"scenario_id": scenario["scenario_id"], "scenario_sha256": scenario["scenario_sha256"],
            "jurisdiction": "US", "right_type": "trademark_word", "status": "满足已定义要求", "gaps": [],
            "retrieval_status": "complete", "triage_status": "complete", "verification_status": "complete"}]
        for risk in ("极低", "低", "中", "高", "极高"):
            with self.subTest(risk=risk):
                self.rows(risk=risk, counter_evidence=[{"reasoning": "Specific scoped exclusion.", "evidence_refs": ["EV-PROV"]}])
                if risk == "极低":
                    self.rows(decisive_exclusion={"reasoning": "Licence for this artwork.", "evidence_refs": ["EV-PROV"]})
                with patch("assessment_estimate.coverage_by_scope", return_value=deepcopy(coverage)), patch("workflow_v24.scenario_execution_gaps", return_value=[]):
                    result = compute_assessment(*self.values)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["assessments"][0]["risk"], risk)
                self.assertEqual(result["assessments"][0]["evidence_confidence"], "高")
                self.assertEqual(result["overall"]["confidence"], "高")

    def test_original_reviews_and_missing_work_queues_are_preserved(self):
        self.values = scenario_fixture(self.directory)
        for review in self.values[-2:]:
            review["assessments"][0].update(risk=None, assessment_status="pending", pending_reasoning="Document review is incomplete.")
        refresh(self.values)
        original = compute_assessment(*self.values)
        self.enable()
        result = compute_assessment(*self.values)
        for old, new in zip(original["scenario_summaries"], result["scenario_summaries"]):
            self.assertEqual(old["completion"], new["completion"])
            self.assertEqual(new["risk"], "低")
            self.assertEqual(new["confidence"], "低")
        self.assertTrue(result["scenario_summaries"][0]["completion"]["queues"]["pending_assessments"])

    def test_secondary_scenario_risk_does_not_replace_primary(self):
        self.values = scenario_fixture(self.directory)
        self.enable()
        scenario = self.values[0]["assessment_scenarios"][1]
        for review in self.values[-2:]:
            row = deepcopy(review["assessments"][0])
            row.update(scenario_id=scenario["scenario_id"], scenario_sha256=scenario["scenario_sha256"], risk="极高")
            review["assessments"].append(row)
            review["assessments"][0]["risk"] = "中"
        result = compute_assessment(*self.values)
        self.assertEqual(result["overall"]["risk"], "中")
        self.assertEqual([row["risk"] for row in result["scenario_summaries"]], ["中", "极高"])
        self.assertTrue(all(row["confidence"] == "低" for row in result["scenario_summaries"]))

    def test_canonical_validation_rejects_edited_grade_or_basis(self):
        self.pending_without_rights_evidence()
        self.save_inputs()
        result = compute_assessment(*self.values, evidence_root=self.directory)
        self.assertEqual(validate_assessment(self.directory, self.values[0], result), [])
        for field, value in (("risk", "高"), ("risk_basis", "evidence_supported")):
            with self.subTest(field=field):
                altered = deepcopy(result)
                altered["overall"][field] = value
                self.assertIn("ASSESSMENT_CANONICAL_RECOMPUTATION_MISMATCH", validate_assessment(self.directory, self.values[0], altered))

    def test_evidence_tampering_remains_fatal_with_low_fallback_enabled(self):
        path = self.directory / "source.txt"
        atomic_write_bytes(path, b"Changed source after it was frozen.")
        with self.assertRaisesRegex(ValueError, "EVIDENCE_ARTIFACT_HASH_OR_SIZE_MISMATCH"):
            compute_assessment(*self.values)

    def test_reassessment_writes_new_context_without_mutating_historical_task(self):
        task = self.values[0]
        task.pop("assessment_revision")
        self.save_inputs()
        originals = {path: sha256_file(path) for path in self.directory.glob("*.json")}
        # Reassessment reviewers bind the explicitly selected new rating revision.
        effective = {**task, "assessment_revision": PARTIAL_EVIDENCE_REVISION}
        digest = review_digest(self.values[1], self.values[2], self.values[4], self.values[3], effective)
        review_dir = self.directory / "new-review-inputs"
        for name, review in zip(("first-review", "second-review"), deepcopy(self.values[-2:])):
            review["review_context"]["evidence_digest"] = digest
            atomic_write_json(review_dir / (name + ".json"), review)
        destination = self.directory / "reassessment"
        context = finalize(self.directory, task, review_dir / "first-review.json",
            review_dir / "second-review.json", output_dir=destination,
            assessment_revision=PARTIAL_EVIDENCE_REVISION, return_context=True)
        self.assertEqual({path: sha256_file(path) for path in originals}, originals)
        self.assertNotIn("assessment_revision", task)
        self.assertEqual(context.assessment["assessment_revision"], PARTIAL_EVIDENCE_REVISION)
        source, output_task = report_input_context(self.directory, task, destination)
        self.assertEqual(source, self.directory)
        self.assertEqual(output_task["assessment_revision"], PARTIAL_EVIDENCE_REVISION)
        self.assertEqual(validate_assessment(destination, output_task, context.assessment), [])
        context.validate(task_dir=self.directory, output_dir=destination)

    def test_standalone_reassessment_cannot_overwrite_source_or_existing_output(self):
        self.save_inputs()
        destination = self.directory / "existing"
        destination.mkdir()
        atomic_write_json(destination / "existing.json", {"retained": True})
        for output in (self.directory, destination):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "REQUIRES_NEW_OUTPUT_DIRECTORY"):
                finalize(self.directory, self.values[0], self.directory / "first-review.json",
                    self.directory / "second-review.json", output_dir=output,
                    assessment_revision=PARTIAL_EVIDENCE_REVISION)


if __name__ == "__main__":
    unittest.main()
