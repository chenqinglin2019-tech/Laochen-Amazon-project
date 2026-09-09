"""Offline contracts for scenario triage. Synthetic fixtures are not IP evidence."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import annotate_materiality as materiality
import create_task
import decision_workflow as workflow
from common import atomic_write_json, load_json, sha256_json


class DecisionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.task = {"schema_version": "2.4-free", "task_id": "SYNTHETIC-TASK", "state": "pending",
                     "decision_workflow_revision": workflow.REVISION,
                     "assessment_scenarios": workflow.default_assessment_scenarios(),
                     "primary_scenario_id": "product_entry", "target_jurisdictions": ["US", "GB"],
                     "product": {"input_role": "reference_product", "requested_asin": "B012345678",
                                 "structure": ["synthetic flat strap"], "brand": "TEST"}, "images": []}
        self.candidate = {"candidate_id": "C1", "normalization_key": "US11111111B2",
                          "jurisdiction": "US", "right_type": "patent", "publication_number": "US11111111B2",
                          "title": "Synthetic strap", "claims": [{"claim_id": "1", "text": "strap and hook"}],
                          "material": True, "material_reason": "source_marked_material", "evidence_refs": ["E1"]}
        self.candidates = {"patents": [self.candidate], "trademarks": [], "copyright_assets": [], "enforcement": []}
        self.collection = "patents"
        self.evidence = {"collections": {"patents": [{"evidence_id": "E1", "provider": "synthetic",
                            "collected_at": "2026-01-01T00:00:00Z", "payload": {"publication_number": "US11111111B2",
                            "claims": "strap and hook", "source_url": "https://example.invalid/one"}}]}}
        self.ledger = materiality.empty_materiality_ledger(self.task["task_id"], task=self.task)

    def annotation(self, decision="selected", scenario="product_entry", **changes):
        request = {"annotation_id": "D" + str(len(self.ledger["annotations"]) + 1), "decision": decision,
                   "reason": "Synthetic actual feature comparison", "reviewer": "offline-reviewer",
                   "annotated_at": "2026-01-01T00:00:00Z", "scenario_id": scenario, "evidence_refs": ["E1"],
                   "reading_level": "result_record", "basis_summary": "Synthetic source contains strap and hook",
                   "reopen_conditions": ["Material protection text or product structure changes"]}
        request.update(changes)
        return workflow.make_annotation(self.task, self.collection, self.candidate, request, evidence=self.evidence)

    def effective(self, scenario="product_entry", jurisdiction=None):
        return workflow.effective_decision(self.task, self.ledger, self.collection, self.candidate, scenario,
                                           jurisdiction, evidence=self.evidence)

    def use_trademark(self):
        self.collection = "trademarks"
        self.candidate["right_type"] = "trademark_word"
        self.candidate["mark_text"] = "TEST"
        self.candidates = {"trademarks": [self.candidate]}

    def test_revision_is_only_opt_in(self):
        old = copy.deepcopy(self.task)
        old.pop("decision_workflow_revision")
        self.assertFalse(workflow.decision_workflow_enabled(old))
        self.assertEqual(workflow.scenario_index(old), {})
        self.assertEqual(workflow.validate_decision_workflow(old), [])
        self.assertEqual(materiality.empty_materiality_ledger("old")["schema_version"], "1.0")
        self.assertEqual(workflow.effective_selected_candidates(old, self.candidates, self.ledger), [])

    def test_scenario_hash_stable_and_assumption_bound(self):
        self.assertEqual(workflow.validate_decision_workflow(self.task), [])
        scenario = self.task["assessment_scenarios"][0]
        before = workflow.scenario_sha256(scenario)
        scenario["updated_at"] = "later"
        scenario["assumptions"].reverse()
        self.assertEqual(workflow.scenario_sha256(scenario), before)
        scenario["assumptions"].append("New material scope assumption")
        self.assertIn("SCENARIO_SHA256_MISMATCH", workflow.validate_decision_workflow(self.task))

    def test_genuine_resale_requires_explicit_request(self):
        self.task["assessment_scenarios"] = workflow.default_assessment_scenarios(genuine_resale=True)
        self.assertIn("GENUINE_RESALE_EXPLICIT_REQUEST_REQUIRED", workflow.validate_decision_workflow(self.task))
        self.task["request"] = {"genuine_resale": True}
        self.assertEqual(workflow.validate_decision_workflow(self.task), [])
        self.task["primary_scenario_id"] = "brand_reuse"
        self.assertIn("PRIMARY_PRODUCT_ENTRY_SCENARIO_REQUIRED", workflow.validate_decision_workflow(self.task))

    def test_source_material_is_priority_not_selection(self):
        self.assertEqual(self.effective()["decision"], "unreviewed")
        materiality.apply_materiality_annotations(self.ledger, self.task["task_id"], self.candidates,
                                                  task=self.task, evidence=self.evidence)
        self.assertFalse(self.candidate["material"])
        self.assertEqual(self.candidate["disposition"], "unreviewed")
        self.assertEqual(self.candidate["priority_signals"][0]["kind"], "source_material")
        self.assertEqual(workflow.effective_selected_candidates(self.task, self.candidates, self.ledger, evidence=self.evidence), [])

    def test_selection_is_scenario_and_country_specific(self):
        self.use_trademark()
        self.ledger["annotations"].append(self.annotation("not_selected"))
        self.ledger["annotations"].append(self.annotation("selected", "brand_reuse"))
        self.assertEqual(self.effective()["decision"], "not_selected")
        self.assertEqual(self.effective("brand_reuse")["decision"], "selected")
        self.assertEqual(self.effective("brand_reuse", "GB")["decision"], "unreviewed")
        selected = workflow.effective_selected_candidates(self.task, self.candidates, self.ledger, evidence=self.evidence)
        self.assertEqual([(r["candidate_id"], r["scenario_id"]) for r in selected], [("C1", "brand_reuse")])

    def test_latest_record_wins_without_overwriting_history(self):
        self.ledger["annotations"].append(self.annotation())
        first = copy.deepcopy(self.ledger["annotations"][0])
        self.ledger["annotations"].append(self.annotation("not_selected"))
        self.assertEqual(self.effective()["decision"], "not_selected")
        self.assertEqual(self.ledger["annotations"][0], first)

    def test_needs_info_requires_specific_gap_bounded_action_and_refs(self):
        with self.assertRaisesRegex(ValueError, "MISSING_INFORMATION"):
            self.annotation("needs_info")
        action = {"action_id": "A1", "kind": "source_lookup", "purpose": "read exact claims",
                  "provider": "synthetic", "operation": "patent_document", "params": {"number": "US11111111B2"}, "max_attempts": 1}
        row = self.annotation("needs_info", missing_information=["independent claim text"], next_actions=[action])
        self.ledger["annotations"].append(row)
        self.assertEqual(self.effective()["next_actions"], [action])
        self.assertEqual(self.effective()["decision"], "needs_info")
        action["max_attempts"] = 2
        with self.assertRaisesRegex(ValueError, "BOUNDED_SOURCE"):
            self.annotation("needs_info", missing_information=["claim text"], next_actions=[action])
        with self.assertRaisesRegex(ValueError, "EVIDENCE_REFS_INVALID"):
            self.annotation("needs_info", evidence_refs=[], missing_information=["claim text"],
                            next_actions=[{"action_id": "A2", "kind": "user_information", "purpose": "product fact", "question": "Does kit contain a hook?"}])

    def test_evidence_refs_are_structured_and_resolvable(self):
        for refs in ("E1", ["E1", "E1"], ["UNKNOWN"], [{"id": "E1"}]):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                self.annotation(evidence_refs=refs)

    def test_substantive_changes_reopen_but_metadata_and_reposts_do_not(self):
        self.ledger["annotations"].append(self.annotation("not_selected"))
        self.candidate["updated_at"] = "2030-01-01"
        self.candidate["sources"] = ["a new repost"]
        self.evidence["collections"]["patents"][0]["collected_at"] = "2030-01-01"
        self.assertTrue(self.effective()["current"])
        repost = copy.deepcopy(self.evidence["collections"]["patents"][0])
        repost.update(evidence_id="E2", provider="another-wrapper")
        repost["payload"]["source_url"] = "https://example.invalid/repost"
        self.evidence["collections"]["patents"].append(repost)
        self.candidate["evidence_refs"].append("E2")
        self.assertTrue(self.effective()["current"])
        self.candidate["claims"][0]["text"] = "strap without hook"
        self.assertEqual(self.effective()["decision"], "unreviewed")
        self.assertIn("TRIAGE_BASIS_CHANGED: candidate_content_sha256", self.effective()["reopen_reasons"])

    def test_document_basis_and_status_changes_reopen(self):
        self.ledger["annotations"].append(self.annotation())
        self.evidence["collections"]["patents"][0]["payload"]["claims"] = "materially revised claim"
        self.assertFalse(self.effective()["current"])
        self.ledger["annotations"].append(self.annotation())
        self.candidate["official_verification"] = {"legal_status": "expired", "checked_at": "later"}
        self.assertFalse(self.effective()["current"])

    def test_goods_completeness_change_reopens_even_when_visible_text_is_unchanged(self):
        self.candidate["goods_services"] = ["Containers"]
        self.candidate["goods_services_truncated"] = True
        self.ledger["annotations"].append(self.annotation("not_selected"))
        self.candidate["goods_services_truncated"] = False
        self.assertFalse(self.effective()["current"])

    def test_scope_tampering_cannot_create_cross_right_or_country_selection(self):
        row = self.annotation()
        row["right_type"] = "design"
        self.ledger["annotations"].append(row)
        result = workflow.effective_decision(self.task, self.ledger, "patents", self.candidate,
                                             "product_entry", "US", "design", evidence=self.evidence)
        self.assertFalse(result["current"])
        self.assertEqual(result["decision"], "unreviewed")
        self.assertIn("TRIAGE_CONTEXT_MISMATCH", result["reopen_reasons"])
        self.assertFalse(self.effective(jurisdiction="JP")["current"])

    def test_empty_source_wrapper_is_not_actual_basis(self):
        self.evidence["collections"]["patents"][0]["payload"] = {"checked_at": "later", "source_url": "https://example.invalid"}
        with self.assertRaisesRegex(ValueError, "EMPTY_EVIDENCE_CONTENT"):
            self.annotation()

    def test_official_timestamp_only_does_not_reopen(self):
        self.candidate["official_verification"] = {"legal_status": "active", "checked_at": "before"}
        self.ledger["annotations"].append(self.annotation())
        self.candidate["official_verification"]["checked_at"] = "after"
        self.assertTrue(self.effective()["current"])

    def test_product_and_scenario_changes_reopen_without_invalidating_history(self):
        self.ledger["annotations"].append(self.annotation())
        self.task["product"]["structure"].append("added hook")
        self.assertFalse(self.effective()["current"])
        self.assertEqual(workflow.triage_ledger_errors(self.task, self.ledger, self.candidates, evidence=self.evidence), [])
        self.ledger["annotations"].append(self.annotation())
        scenario = self.task["assessment_scenarios"][0]
        scenario["assumptions"].append("now evaluating a different use")
        scenario["scenario_sha256"] = workflow.scenario_sha256(scenario)
        self.assertIn("TRIAGE_BASIS_CHANGED: scenario_sha256", self.effective()["reopen_reasons"])

    def test_retail_statistics_do_not_reopen_but_physical_product_facts_do(self):
        from historical_evidence import observed_product_identity_sha256
        specs = {"Best Sellers Rank": "45388", "Customer Reviews": "4.5 stars, 100 reviews",
                 "Product Dimensions": "10 x 2 x 0.2 inches", "Material": "Silicone", "Item Weight": "80 grams"}
        self.task["product"].update(specifications=copy.deepcopy(specs), raw_capture={"specifications": copy.deepcopy(specs)})
        self.task["images"] = [{"sha256": "1" * 64}]
        self.ledger["annotations"].append(self.annotation())
        before = workflow.product_identity_sha256(self.task)
        observed = observed_product_identity_sha256(self.task)
        for holder in (self.task["product"], self.task["product"]["raw_capture"]):
            holder["specifications"].update({"Best Sellers Rank": "43328", "Customer Reviews": "4.6 stars, 105 reviews"})
        self.assertEqual(workflow.product_identity_sha256(self.task), before)
        self.assertEqual(observed_product_identity_sha256(self.task), observed)
        self.assertTrue(self.effective()["current"])
        stable = copy.deepcopy(self.task)
        for location in ("product", "raw_capture"):
            for field, value in (("Product Dimensions", "12 x 2 x 0.2 inches"), ("Material", "Steel"), ("Item Weight", "95 grams")):
                with self.subTest(location=location, field=field):
                    self.task = copy.deepcopy(stable)
                    holder = self.task["product"] if location == "product" else self.task["product"]["raw_capture"]
                    holder["specifications"][field] = value
                    self.assertNotEqual(workflow.product_identity_sha256(self.task), before)
                    self.assertFalse(self.effective()["current"])
                    if location == "raw_capture":
                        self.assertNotEqual(observed_product_identity_sha256(self.task), observed)
        self.task = copy.deepcopy(stable)
        self.task["images"][0]["sha256"] = "2" * 64
        self.assertFalse(self.effective()["current"])
        self.assertNotEqual(observed_product_identity_sha256(self.task), observed)
        self.task = copy.deepcopy(stable)
        scenario = self.task["assessment_scenarios"][0]
        scenario["assumptions"].append("New assessed use")
        scenario["scenario_sha256"] = workflow.scenario_sha256(scenario)
        self.assertIn("TRIAGE_BASIS_CHANGED: scenario_sha256", self.effective()["reopen_reasons"])

    def test_product_statistic_filter_is_exact_scoped_and_nonmutating(self):
        product = {"specifications": {"Best Sellers Rank": "12", "Customer Reviews": "100"},
                   "raw_capture": {"specifications": {"Best Sellers Rank": "13", "Material": "Silicone"}},
                   "Customer Reviews": "A literal product field is retained", "review_count": 42}
        original = copy.deepcopy(product)
        value = workflow.product_identity_content(product)
        self.assertNotIn("specifications", value)
        self.assertEqual(value["raw_capture"]["specifications"], {"Material": "Silicone"})
        self.assertEqual(value["Customer Reviews"], product["Customer Reviews"])
        self.assertEqual(value["review_count"], 42)
        self.assertEqual(product, original)

    def test_foreign_and_unknown_recall_cannot_escape_triage(self):
        for origin in ("WO", "EP", "", "CA"):
            self.candidate["jurisdiction"] = origin
            summary = workflow.triage_summary(self.task, self.candidates, self.ledger, evidence=self.evidence)
            self.assertEqual(summary["counts"]["unreviewed"], 2)
            self.assertEqual({r["jurisdiction"] for r in summary["records"]}, {"US", "GB"})

    def test_legacy_ledger_application_is_unchanged(self):
        legacy = materiality.empty_materiality_ledger("LEGACY")
        legacy["annotations"].append({"annotation_id": "M1", "candidate_id": "C1", "candidate_identity_fingerprint": materiality.candidate_identity_fingerprint("patents", self.candidate),
                                     "material": True, "decision": "material", "material_reason": "legacy reason", "reviewer": "old",
                                     "annotated_at": "2026-01-01T00:00:00Z"})
        materiality.apply_materiality_annotations(legacy, "LEGACY", self.candidates)
        self.assertTrue(self.candidate["material"])
        self.assertEqual(self.candidate["disposition"], "material")
        self.assertEqual(materiality.materiality_ledger_errors(legacy, "LEGACY", self.candidates), [])
        self.assertEqual(materiality.candidate_identity_fingerprint("patents", self.candidate), sha256_json({
            "collection": "patents", "candidate_id": "C1", "normalization_key": "US11111111B2", "jurisdiction": "US", "right_type": "patent"}))

    def test_ledger_two_requires_revision_and_append_integrity(self):
        self.ledger["annotations"].append(self.annotation())
        self.assertEqual(materiality.materiality_ledger_errors(self.ledger, self.task["task_id"], self.candidates), ["TRIAGE_TASK_CONTEXT_REQUIRED"])
        self.ledger["annotations"].append(copy.deepcopy(self.ledger["annotations"][0]))
        self.assertIn("TRIAGE_DUPLICATE_ANNOTATION_ID", workflow.triage_ledger_errors(self.task, self.ledger, self.candidates, evidence=self.evidence))

    def test_cli_batch_is_validated_before_write_and_preserves_per_item_audit(self):
        self.use_trademark()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, value in (("task", self.task), ("evidence", self.evidence), ("normalized-candidates", self.candidates), ("materiality-annotations", self.ledger)):
                atomic_write_json(root / (name + ".json"), value)
            request = {"candidate_id": "C1", "decision": "selected", "reason": "read the actual source", "reviewer": "test", "evidence_refs": ["E1"], "scenario_id": "product_entry",
                       "reading_level": "registry_record", "basis_summary": "Synthetic mark goods record", "reopen_conditions": ["The protected mark or goods change"]}
            atomic_write_json(root / "batch.json", {"decisions": [request, {**request, "candidate_id": "BAD"}]})
            args = ["annotate_materiality.py", "--task-dir", str(root), "--input", str(root / "batch.json")]
            with patch.object(sys, "argv", args), patch.object(materiality, "assert_active_free_policy"), self.assertRaises(SystemExit):
                materiality.main()
            self.assertEqual(load_json(root / "materiality-annotations.json")["annotations"], [])
            atomic_write_json(root / "batch.json", {"decisions": [request, {**request, "scenario_id": "brand_reuse", "decision": "not_selected"}]})
            with patch.object(sys, "argv", args), patch.object(materiality, "assert_active_free_policy"):
                materiality.main()
            saved = load_json(root / "materiality-annotations.json")
            self.assertEqual(len(saved["annotations"]), 2)
            self.assertNotEqual(saved["annotations"][0]["annotation_id"], saved["annotations"][1]["annotation_id"])
            self.assertEqual(workflow.triage_ledger_errors(self.task, saved, self.candidates, evidence=self.evidence), [])

    def test_new_task_defaults_and_legacy_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = ["create_task.py", "--url", "https://www.amazon.com/dp/B012345678", "--jurisdictions", "US", "--output-dir", str(root / "new")]
            runtime = json.loads((Path(__file__).resolve().parents[1] / "references/runtime-config.json").read_text())
            with patch.object(sys, "argv", args), patch.object(create_task, "load_skill_config", return_value=runtime):
                create_task.main()
            task = load_json(root / "new/task.json")
            self.assertEqual(task["product"]["input_role"], "reference_product")
            self.assertEqual(task["primary_scenario_id"], "product_entry")
            self.assertEqual(task["workflow_correction_revision"], workflow.CORRECTION_REVISION)
            self.assertEqual(task["retrieval_workflow_revision"], "api-first-v1")
            self.assertEqual(task["retrieval_policy"], runtime["api_first"])
            self.assertEqual(task["serper_free_enhancement"]["max_queries_per_task"], 30)
            self.assertEqual(task["serpapi_free_enhancement"]["max_queries_per_task"], 10)
            self.assertEqual(workflow.validate_decision_workflow(task), [])
            self.assertEqual(load_json(root / "new/materiality-annotations.json")["schema_version"], "2.0")
            args[-1] = str(root / "old")
            args += ["--schema-version", "2.3-free"]
            with patch.object(sys, "argv", args), patch.object(create_task, "load_skill_config", return_value={}), patch.dict("os.environ", {"LC_IPR_TEST_MODE": "1"}):
                create_task.main()
            old = load_json(root / "old/task.json")
            self.assertNotIn("decision_workflow_revision", old)
            self.assertNotIn("workflow_correction_revision", old)
            self.assertNotIn("retrieval_workflow_revision", old)
            self.assertEqual(load_json(root / "old/materiality-annotations.json")["schema_version"], "1.0")

    def test_unknown_nonempty_revision_fails_instead_of_legacy_fallback(self):
        self.task["decision_workflow_revision"] = "unrecognized-revision"
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_DECISION_WORKFLOW_REVISION"):
            workflow.decision_workflow_enabled(self.task)
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_DECISION_WORKFLOW_REVISION"):
            materiality.apply_materiality_annotations(self.ledger, self.task["task_id"], self.candidates, task=self.task)

    def test_all_decisions_require_reading_basis_and_reopen_conditions(self):
        for field, value in (("reading_level", None), ("reading_level", "unread"), ("basis_summary", ""), ("reopen_conditions", [])):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.annotation(**{field: value})

    def test_brand_reuse_only_has_trademark_triage(self):
        scenario = workflow.scenario_index(self.task)["brand_reuse"]
        self.assertEqual(workflow.scenario_right_types(scenario), {"trademark_word", "trademark_figurative"})
        self.assertIn("patent", workflow.scenario_right_types(workflow.scenario_index(self.task)["product_entry"]))
        with self.assertRaisesRegex(ValueError, "SCENARIO_RIGHT_MISMATCH"):
            self.annotation(scenario="brand_reuse")
        summary = workflow.triage_summary(self.task, self.candidates, self.ledger, evidence=self.evidence)
        self.assertEqual(sum(summary["by_scenario"]["brand_reuse"]["counts"].values()), 0)

    def test_other_candidate_in_shared_payload_does_not_reopen(self):
        source = self.evidence["collections"]["patents"][0]
        source["payload"] = {"candidates": [{"publication_number": "US11111111B2", "claims": "strap and hook"},
                                             {"publication_number": "US22222222B2", "claims": "coffee maker"}],
                             "artifacts": [{"role": "query_screenshot", "sha256": "a" * 64}]}
        self.ledger["annotations"].append(self.annotation())
        source["payload"]["candidates"][1]["claims"] = "new unrelated claims"
        source["payload"]["artifacts"][0]["sha256"] = "b" * 64
        self.assertTrue(self.effective()["current"])
        source["payload"]["candidates"][0]["claims"] = "materially changed exact-candidate claim"
        self.assertFalse(self.effective()["current"])

    def test_new_substantive_artifact_hash_reopens_but_reacquisition_does_not(self):
        source = self.evidence["collections"]["patents"][0]
        source["payload"]["artifacts"] = [{"role": "original_drawing", "sha256": "a" * 64, "path": "/first.png", "checked_at": "before"}]
        self.ledger["annotations"].append(self.annotation("not_selected"))
        artifact = source["payload"]["artifacts"][0]
        artifact.update(path="/reacquired.png", checked_at="later")
        self.assertTrue(self.effective()["current"])
        artifact["sha256"] = "b" * 64
        self.assertFalse(self.effective()["current"])


if __name__ == "__main__":
    unittest.main()
