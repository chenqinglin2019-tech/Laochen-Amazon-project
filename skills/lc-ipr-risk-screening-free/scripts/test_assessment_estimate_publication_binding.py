"""Offline publication-binding regression; not a live recall acceptance test."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from assessment_estimate import (_apply_recall_integrity, compute_assessment,
                                 review_digest, validate_supplement)
from common import now_iso, sha256_file, sha256_json
from test_assessment_estimate_recall import strict_fixture


class PublicationBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.values = strict_fixture(self.root)
        task, evidence, candidates, plan, *_ = self.values
        self.pdf = self.root / "retained-original.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\nOffline retained-file binding fixture.\n%%EOF\n")
        self.entry = {"evidence_id": "EV-INDEPENDENT-PDF", "kind": "patent_document",
                      "authority_scope": "published_document_only", "publication_number": "US D1,052,952 S",
                      "jurisdiction": "US", "right_type": "design", "path": self.pdf.name,
                      "sha256": sha256_file(self.pdf), "bytes": self.pdf.stat().st_size,
                      "checked_at": now_iso(), "source_url": "https://example.org/retained-original.pdf"}
        self.supplement = {"schema": "IPR-EVIDENCE-SUPPLEMENT/1.0", "evidence": [self.entry]}
        self.candidate = {"candidate_id": "CAND-INDEPENDENT", "publication_number": "USD1052952S",
                          "jurisdiction": "US", "right_type": "design", "right_state": "unknown",
                          "evidence_refs": ["EV-PARTIAL-PATENT-QUERY"], "verification_refs": [],
                          "disposition": "unreviewed", "material": False}
        candidates["patents"].append(self.candidate)
        requirement = next(r for r in task["coverage_requirements"] if r["jurisdiction"] == "US"
                           and r["right_type"] == "patent" and r["phase"] == "official_recall")
        route = next(r for r in requirement["routes"] if r["provider"] == "epo_ops")
        query = {"query_id": "Q-PARTIAL", "provider": "epo_ops", "operation": route["operation"],
                 "jurisdiction": "US", "right_type": "patent", "requirement_ids": [requirement["requirement_id"]],
                 "q": "lid AND strap", "execute_by_default": True, "search_dimension": "text",
                 "search_language": "en", "execution_phase": "initial"}
        plan["queries"]["epo_ops"] = [query]
        run = {"run_id": "R-PARTIAL", **query, "status": "success", "plan_entry_sha256": sha256_json(query),
               "source_environment": "production", "authoritative_for_final_rating": True,
               "metadata": {"search_coverage": {"schema_valid": True, "total_hits": 2, "retrieved_hits": 1,
                            "truncated": True, "stop_reason": "bounded_stop"}}}
        evidence["source_runs"].append(run)
        evidence["collections"]["patents"] = [{"evidence_id": "EV-PARTIAL-PATENT-QUERY",
            "source_run_id": run["run_id"], "payload": {"candidates": [deepcopy(self.candidate)]},
            **{k: run[k] for k in ("provider", "query_id", "operation", "jurisdiction", "right_type",
                                   "requirement_ids", "plan_entry_sha256")}}]
        for review in self.values[-2:]:
            review["assessments"][0].update(candidate_id=self.candidate["candidate_id"], right_type="design",
                module_id="appearance_patent", risk="低", right_state="unknown", right_state_evidence_refs=[],
                evidence_refs=["EV-PRODUCT", self.entry["evidence_id"]], supporting_evidence=[],
                no_supporting_evidence_reasoning="No corresponding solid-line component was found in the bounded comparison.",
                counter_evidence=[{"reasoning": "The original solid-line connector is a separate double-loop body.",
                                   "evidence_refs": [self.entry["evidence_id"]]}], confidence_basis={}, findings=[],
                comparison={"criteria": [{"criterion": "solid-line shape", "result": "excludes_risk",
                    "reasoning": "Specific component differs from the single strip.", "evidence_refs": [self.entry["evidence_id"]]}],
                    "unresolved": ["Current legal status unknown."]})

    def tearDown(self):
        self.temp.cleanup()

    def calculate(self):
        task, evidence, candidates, plan, ledger, first, second = self.values
        digest = review_digest(evidence, candidates, ledger, plan, task, self.supplement)
        for review in (first, second):
            review["review_context"]["evidence_digest"] = digest
        return compute_assessment(*self.values, supplement=self.supplement, evidence_root=self.root)

    def assert_pending(self):
        row = self.calculate()["assessments"][0]
        self.assertIsNone(row["risk"])
        self.assertEqual(row["assessment_status"], "pending")

    def test_independent_original_exactly_binds_design_from_patent_query(self):
        before = deepcopy(self.values[1:5])
        result = self.calculate()
        row = result["assessments"][0]
        self.assertEqual(row["risk"], "低")
        self.assertEqual(row["assessment_status"], "assessed")
        self.assertEqual(row["right_state"], "unknown")
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["overall"]["risk"])
        self.assertIn("SEARCH_RESULT_TRUNCATED", [g["code"] for g in result["coverage"]["execution_gaps"]])
        self.assertEqual(before, self.values[1:5])

    def test_design_drawings_kind_can_bind_exact_publication(self):
        self.entry["kind"] = "design_drawings"
        self.assertEqual(self.calculate()["assessments"][0]["risk"], "低")

    def test_exact_utility_document_supports_scoped_positive_without_status_upgrade(self):
        self.entry.update(publication_number="US11,401,089 B2", right_type="patent")
        self.candidate.update(publication_number="US11401089B2", right_type="patent")
        for review in self.values[-2:]:
            row = review["assessments"][0]
            row.update(right_type="patent", module_id="utility_patent", risk="中",
                       supporting_evidence=[{"reasoning": "Original publication supplies concrete comparison content.",
                                             "evidence_refs": [self.entry["evidence_id"]]}])
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["risk"], "中")
        self.assertEqual(result["assessments"][0]["right_state"], "unknown")
        self.assertEqual(result["status"], "incomplete")

    def test_different_publication_number_cannot_bind(self):
        self.entry["publication_number"] = "USD1052953S"
        self.assert_pending()

    def test_kind_code_is_not_dropped(self):
        self.entry["publication_number"] = "USD1052952S1"
        self.assert_pending()

    def test_missing_kind_code_is_not_guessed(self):
        self.entry["publication_number"] = "USD1052952"
        self.assert_pending()

    def test_same_family_or_related_publication_is_not_exact_identity(self):
        self.entry.pop("publication_number")
        self.entry.update(family_members=[self.candidate["publication_number"]],
                          publication_relations=[{"publication_number": self.candidate["publication_number"], "relation": "same_application"}])
        self.assert_pending()

    def test_wrong_scope_or_document_kind_is_rejected(self):
        for changes in ({"jurisdiction": "GB"}, {"right_type": "patent"}, {"kind": "agent_review"},
                        {"authority_scope": "discovery_only"}):
            with self.subTest(changes=changes):
                prior = deepcopy(self.entry)
                self.entry.update(changes)
                self.assert_pending()
                self.entry.clear()
                self.entry.update(prior)

    def test_mismatched_candidate_jurisdiction_does_not_bind(self):
        self.candidate["jurisdiction"] = "GB"
        self.assert_pending()

    def test_missing_or_wrong_file_hash_fails_validation(self):
        for digest in (None, "0" * 64):
            with self.subTest(digest=digest):
                self.entry["sha256"] = digest
                with self.assertRaisesRegex(ValueError, "SUPPLEMENT_EVIDENCE_INVALID|HASH_OR_SIZE_MISMATCH"):
                    self.calculate()

    def test_tampered_original_fails_before_publication_binding(self):
        self.pdf.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "HASH_OR_SIZE_MISMATCH"):
            self.calculate()

    def test_unvalidated_registry_record_does_not_gain_new_binding(self):
        task, evidence, candidates, plan, *_ = self.values
        row = deepcopy(self.values[-2]["assessments"][0])
        _apply_recall_integrity([row], task, evidence, candidates, plan, [], {self.entry["evidence_id"]: self.entry})
        self.assertIsNone(row["risk"])
        # Validation alone is not enough if a caller swaps the registry entry.
        validated = validate_supplement(self.supplement, self.root)
        changed = deepcopy(self.entry)
        changed["sha256"] = "0" * 64
        row = deepcopy(self.values[-2]["assessments"][0])
        _apply_recall_integrity([row], task, evidence, candidates, plan, [], {changed["evidence_id"]: changed},
                               validated_supplements=validated)
        self.assertIsNone(row["risk"])


if __name__ == "__main__":
    unittest.main()
