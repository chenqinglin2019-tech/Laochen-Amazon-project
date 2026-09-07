"""Synthetic offline integrity tests; no fixtures here assert live source access."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import active_free_policy, atomic_write_json, sha256_file, sha256_json
from decision_workflow import REVISION, default_assessment_scenarios, product_identity_sha256
from historical_evidence import (historical_action_reuse, historical_action_reuse_errors,
                                 historical_evidence_root, observed_product_identity_sha256)


class HistoricalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / "old"
        self.old.mkdir()
        self.date = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.old_task = {"schema_version": "2.4-free", "task_id": "OLD-SYNTHETIC",
                         "free_policy_revision": "automation-first-v1", "free_policy": active_free_policy(),
                         "target_jurisdictions": ["US"], "product": {"requested_asin": "B012345678", "structure": ["strap"]}, "images": []}
        self.task = {**deepcopy(self.old_task), "task_id": "NEW-SYNTHETIC", "decision_workflow_revision": REVISION,
                     "assessment_scenarios": default_assessment_scenarios(), "primary_scenario_id": "product_entry"}
        self.original = {"query_id": "OLD-Q", "operation": "patent_search", "jurisdiction": "US", "right_type": "patent",
                         "q": "strap AND lid", "requirement_ids": ["REQ-OLD"], "search_dimension": "text", "search_language": "en"}
        self.provider = "epo_ops"
        self.row = {**deepcopy(self.original), "query_id": "NEW-Q", "requirement_ids": ["REQ-NEW"],
                    "decision_workflow_revision": REVISION, "scenario_id": "product_entry",
                    "scenario_sha256": self.task["assessment_scenarios"][0]["scenario_sha256"], "action_purpose": "recall"}
        self.plan = {"schema_version": "2.4-free", "task_id": self.old_task["task_id"],
                     "free_policy_revision": self.old_task["free_policy_revision"], "free_policy": self.old_task["free_policy"],
                     "queries": {self.provider: [self.original]}}
        self.records = [{"publication_number": "US11111111B2", "jurisdiction": "US", "right_type": "patent", "title": "Synthetic strap"},
                        {"publication_number": "US22222222B2", "jurisdiction": "US", "right_type": "patent", "title": "Synthetic lid"}]
        self.run = {"run_id": "OLD-RUN", "provider": self.provider, "query_id": self.original["query_id"],
                    "operation": self.original["operation"], "jurisdiction": "US", "right_type": "patent", "requirement_ids": ["REQ-OLD"],
                    "status": "success", "source_environment": "production", "authoritative_for_final_rating": True,
                    "finished_at": self.date, "metadata": {"search_coverage": {"schema_valid": True, "total_hits": 2,
                    "retrieved_hits": 2, "truncated": False, "stop_reason": "all_results_retrieved"}}}
        self.entry = {"evidence_id": "OLD-EV", "source_run_id": "OLD-RUN", "payload": {"candidates": self.records, "checked_at": self.date}}
        self.evidence = {"schema_version": "2.4-free", "task_id": self.old_task["task_id"], "source_runs": [self.run], "collections": {"patents": [self.entry]}}
        self.candidates = {"schema_version": "2.4-free", "task_id": self.task["task_id"], "patents": [
            {**deepcopy(record), "candidate_id": "C" + str(index), "evidence_refs": ["REUSE-EV"], "material": False, "disposition": "unreviewed"}
            for index, record in enumerate(self.records)]}
        self.item = {"evidence_id": "REUSE-EV", "kind": "historical_source_reuse", "checked_at": datetime.now(timezone.utc).isoformat(),
                     "checked_at_meaning": "retained_file_hash_verification", "source_checked_at": self.date,
                     "historical_source": {"run_id": "OLD-RUN", "query_id": "OLD-Q", "evidence_ids": ["OLD-EV"]},
                     "reuse_binding": {"product_identity_sha256": product_identity_sha256(self.task), "scenario_id": "product_entry",
                     "scenario_sha256": self.row["scenario_sha256"], "jurisdiction": "US", "right_type": "patent", "action_purpose": "recall",
                     "reviewer": "offline-test", "reasoning": "Exact synthetic query; all original records retained."}}
        self.supplement = {"schema": "IPR-EVIDENCE-SUPPLEMENT/1.0", "evidence": [self.item]}
        self.save()

    def binding(self, path):
        return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}

    def save(self):
        raw = self.old / "response.json"
        atomic_write_json(raw, self.entry["payload"])
        self.run.update(raw_paths=[str(raw)], payload_digest=sha256_file(raw), plan_entry_sha256=sha256_json(self.original))
        self.entry.update({key: self.run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "requirement_ids", "plan_entry_sha256")})
        for name, value in (("task.json", self.old_task), ("search-plan.json", self.plan), ("evidence.json", self.evidence)):
            atomic_write_json(self.old / name, value)
        self.item.update(self.binding(self.old / "evidence.json"), source_document=str(self.old / "evidence.json"))
        self.item["historical_source"].update(task=self.binding(self.old / "task.json"), plan=self.binding(self.old / "search-plan.json"), plan_entry_sha256=sha256_json(self.original))

    def reuse(self):
        return historical_action_reuse(self.task, self.provider, self.row, self.candidates, self.supplement, self.root)

    def rejected(self, code):
        self.assertIsNone(self.reuse())
        errors = historical_action_reuse_errors(self.task, self.provider, self.row, self.candidates, self.supplement, self.root)
        self.assertTrue(any(code in error for error in errors), errors)

    def test_exact_recall_reuses_original_identity_without_inheriting_review_or_mutation(self):
        before = deepcopy((self.task, self.candidates, self.supplement))
        hashes = {p: sha256_file(p) for p in self.old.iterdir()}
        result = self.reuse()
        self.assertIsNotNone(result, historical_action_reuse_errors(self.task, self.provider, self.row, self.candidates, self.supplement, self.root))
        self.assertTrue(result["retrieval_complete"])
        self.assertFalse(result["triage_complete"])
        self.assertEqual(result["source_query_id"], "OLD-Q")
        self.assertEqual(result["source_checked_at"], self.date)
        self.assertEqual(result["evidence_refs"], ["REUSE-EV"])
        self.assertEqual(before, (self.task, self.candidates, self.supplement))
        self.assertEqual(hashes, {p: sha256_file(p) for p in self.old.iterdir()})

    def test_new_metadata_can_change_but_external_parameters_cannot(self):
        self.row.update(wave=3, derived_from=["new-scenario"])
        self.assertIsNotNone(self.reuse())
        self.row["q"] = "lid AND strap"
        self.rejected("EXTERNAL_PARAMS_MISMATCH")

    def test_hash_bound_product_clue_locator_is_not_a_file_and_is_not_mutated(self):
        self.old_task["product"]["analysis"] = {"clue_dispositions": [{
            "source_path": "product.structure[0]", "source_sha256": sha256_json("strap"),
            "disposition": "mapped", "reason": "Synthetic analysis locator."}]}
        self.save()
        before = deepcopy(self.old_task)
        self.assertIsNotNone(self.reuse())
        self.assertEqual(self.old_task, before)
        self.old_task["product"]["analysis"]["clue_dispositions"][0]["source_sha256"] = "0" * 64
        self.save()
        self.rejected("PRODUCT_CLUE_HASH_MISMATCH")

    def test_product_clue_exemption_does_not_accept_unknown_or_real_missing_paths(self):
        for path in ("product.structure[99]", "missing.pdf", "../outside.pdf"):
            with self.subTest(path=path):
                self.old_task["product"]["analysis"] = {"clue_dispositions": [{
                    "source_path": path, "source_sha256": sha256_json("strap")}]}
                self.save()
                self.rejected("ARTIFACT_OUTSIDE_ROOT_OR_MISSING")

    def test_changed_scope_product_and_scenario_rejected(self):
        for field, replacement in (("jurisdiction", "GB"), ("right_type", "design"), ("scenario_sha256", "0" * 64)):
            with self.subTest(field=field):
                original = self.row[field]
                self.row[field] = replacement
                self.assertIsNone(self.reuse())
                self.row[field] = original
        self.task["product"]["structure"] = ["different product"]
        self.rejected("PRODUCT_MISMATCH")

    def test_retail_statistics_change_allows_reuse_but_material_change_does_not(self):
        specs = {"Best Sellers Rank": "45388", "Customer Reviews": "100 ratings", "Material": "Silicone",
                 "Product Dimensions": "10 x 2 inches", "Item Weight": "80 grams"}
        for task in (self.old_task, self.task):
            task["product"].update(specifications=deepcopy(specs), raw_capture={"specifications": deepcopy(specs)})
        for holder in (self.task["product"], self.task["product"]["raw_capture"]):
            holder["specifications"].update({"Best Sellers Rank": "43328", "Customer Reviews": "105 ratings"})
        self.item["reuse_binding"]["product_identity_sha256"] = product_identity_sha256(self.task)
        self.save()
        self.assertIsNotNone(self.reuse())
        self.task["product"]["raw_capture"]["specifications"]["Material"] = "Steel"
        # Even an explicit new-scope review cannot equate different old objects.
        self.item["reuse_binding"]["product_identity_sha256"] = product_identity_sha256(self.task)
        self.rejected("ORIGINAL_PRODUCT_MISMATCH")

    def test_original_document_byte_change_rejected(self):
        atomic_write_json(self.old / "evidence.json", {"changed": True})
        self.rejected("HASH_OR_SIZE_MISMATCH")

    def test_original_task_plan_and_run_binding_rejected(self):
        self.item["historical_source"]["plan_entry_sha256"] = "0" * 64
        self.rejected("PLAN_ENTRY_HASH_MISMATCH")
        self.save()
        self.entry["plan_entry_sha256"] = "0" * 64
        atomic_write_json(self.old / "evidence.json", self.evidence)
        self.item.update(self.binding(self.old / "evidence.json"))
        self.rejected("RUN_BINDING_MISMATCH")

    def test_raw_file_and_screenshot_hash_change_rejected(self):
        atomic_write_json(self.old / "response.json", {"changed": True})
        self.rejected("ORIGINAL_FILES_INVALID")
        image = self.old / "image.png"
        # The byte binding, not an invented visual interpretation, is under test.
        atomic_write_json(image, {"synthetic_bytes": 1})
        self.entry["payload"]["artifacts"] = [{**self.binding(image), "role": "original_document"}]
        self.save()
        atomic_write_json(image, {"synthetic_bytes": 2})
        self.rejected("ORIGINAL_FILES_INVALID")

    def test_nonproduction_and_unknown_providers_fail_closed(self):
        self.run["source_environment"] = "sandbox"
        self.save()
        self.rejected("NON_PRODUCTION")
        self.provider = "paid_or_unknown_source"
        self.rejected("PROVIDER_UNSUPPORTED")

    def test_old_payload_date_cannot_be_refreshed_by_new_finished_or_retention_date(self):
        self.entry["payload"]["checked_at"] = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        self.save()
        self.rejected("SOURCE_STALE")

    def test_future_and_missing_source_time_fail_closed(self):
        self.run["finished_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.save()
        self.rejected("SOURCE_STALE_OR_FUTURE")
        self.run.pop("finished_at")
        self.save()
        self.rejected("SOURCE_DATE_MISSING")

    def test_current_config_dynamic_window_is_applied(self):
        with patch("historical_evidence.load_skill_config", return_value={"performance": {"dynamic_evidence_max_age_hours": 0.5}}):
            self.rejected("SOURCE_STALE")

    def test_old_excluded_candidate_must_still_be_retained(self):
        self.records[1]["material"] = False
        self.records[1]["disposition"] = "excluded"
        self.save()
        self.candidates["patents"].pop()
        self.rejected("ORIGINAL_RESULT_NOT_RETAINED")

    def test_wrong_publication_kind_or_missing_provenance_is_not_retained(self):
        self.candidates["patents"][0]["publication_number"] = "US11111111A1"
        self.rejected("ORIGINAL_RESULT_NOT_RETAINED")
        self.candidates["patents"][0]["publication_number"] = "US11111111B2"
        self.candidates["patents"][0]["evidence_refs"] = []
        self.rejected("NEW_CANDIDATE_PROVENANCE_MISSING")

    def test_truncation_schema_and_duplicate_record_rejected(self):
        meta = self.run["metadata"]["search_coverage"]
        meta["truncated"] = True
        self.save()
        self.rejected("RETRIEVAL_INCOMPLETE")
        meta["truncated"], meta["schema_valid"] = False, False
        self.save()
        self.rejected("RETRIEVAL_INCOMPLETE")
        meta["schema_valid"] = True
        self.records[1] = deepcopy(self.records[0])
        self.save()
        self.rejected("DUPLICATE_ORIGINAL_RECORDS")

    def test_zero_result_requires_actual_empty_complete_envelope(self):
        self.records.clear()
        self.candidates["patents"].clear()
        self.run["status"] = "no_result"
        self.run["metadata"]["search_coverage"].update(total_hits=0, retrieved_hits=0)
        self.save()
        self.assertTrue(self.reuse()["retrieval_complete"])
        self.run["metadata"]["search_coverage"]["total_hits"] = None
        self.save()
        self.rejected("RETRIEVAL_INCOMPLETE")

    def test_original_evidence_subset_and_duplicate_manifest_fail_closed(self):
        self.item["historical_source"]["evidence_ids"] = ["not-the-original"]
        self.rejected("EVIDENCE_IDS_INCOMPLETE")
        self.item["historical_source"]["evidence_ids"] = ["OLD-EV"]
        self.supplement["evidence"].append(deepcopy(self.item))
        self.rejected("DUPLICATE_EVIDENCE_ID")

    def test_later_failed_attempt_cannot_be_hidden_by_earlier_bound_success(self):
        self.evidence["source_runs"].append({**deepcopy(self.run), "run_id": "LATER-FAILED", "status": "failed", "error_code": "TIMEOUT"})
        self.save()
        self.rejected("RUN_NOT_LATEST_SUCCESS")

    def test_malformed_evidence_id_fails_closed_without_exception(self):
        self.item["evidence_id"] = ["invalid"]
        self.rejected("SUPPLEMENT_EVIDENCE_INVALID")

    def test_path_escape_and_candidate_id_remap_fail_closed(self):
        self.item["historical_source"]["task"]["path"] = "/outside/task.json"
        self.rejected("FILE_OUTSIDE_ROOT_OR_MISSING")
        self.save()
        self.original["candidate_id"] = "old-id"
        self.row["candidate_id"] = "new-id"
        self.save()
        self.rejected("EXTERNAL_PARAMS_MISMATCH")

    def deep(self):
        self.original.update(operation="candidate_verification", q="US11111111B2", candidate_id="C0")
        self.row.update(operation="candidate_verification", q="US11111111B2", candidate_id="C0", action_purpose="official_verification")
        self.run["operation"] = "candidate_verification"
        self.item["reuse_binding"]["action_purpose"] = "official_verification"
        self.entry["payload"] = {**self.records[0], "candidate_id": "C0", "official_verification": {
            "status": "verified", "identity_match": True, "legal_status": "active", "checked_at": self.date}}
        self.save()

    def test_deep_requires_exact_verified_identity_status_and_original_date(self):
        self.deep()
        self.assertEqual(self.reuse()["authority_scope"], "original_official_verification")
        self.entry["payload"]["official_verification"]["identity_match"] = False
        self.save()
        self.rejected("OFFICIAL_VERIFICATION_INVALID")

    def test_publication_document_does_not_satisfy_official_status(self):
        self.deep()
        self.entry["payload"].update(authority_scope="published_document_only", claims=["synthetic claim"], document_identity_match=True)
        self.save()
        self.rejected("OFFICIAL_VERIFICATION_INVALID")
        self.row["action_purpose"] = self.item["reuse_binding"]["action_purpose"] = "document_content"
        self.assertEqual(self.reuse()["authority_scope"], "published_document_only")

    def test_original_observations_survive_new_assessment_wording(self):
        self.old_task["product"].update(input_role="actual_product", intended_use="old seller wording", analysis={"old": "description"})
        self.task["product"].update(input_role="reference_product", intended_use="new prospective scenario", analysis={"new": "analysis"})
        self.item["reuse_binding"]["product_identity_sha256"] = product_identity_sha256(self.task)
        self.save()
        self.assertEqual(observed_product_identity_sha256(self.task), observed_product_identity_sha256(self.old_task))
        self.assertIsNotNone(self.reuse())

    def test_original_asin_variant_and_raw_observation_changes_rejected(self):
        for field, value in (("actual_asin", "B999999999"), ("variant", {"color": "blue"}),
                             ("raw_capture", {"specifications": {"material": "steel"}})):
            with self.subTest(field=field):
                self.old_task["product"][field] = value
                self.save()
                self.rejected("ORIGINAL_PRODUCT_MISMATCH")
                self.old_task["product"].pop(field)

    def test_original_image_hash_change_rejected(self):
        photo = self.old / "photo.png"
        atomic_write_json(photo, {"synthetic_photo": 1})
        self.old_task["images"] = [self.binding(photo)]
        self.task["images"] = [deepcopy(self.binding(photo))]
        self.item["reuse_binding"]["product_identity_sha256"] = product_identity_sha256(self.task)
        self.save()
        self.assertIsNotNone(self.reuse())
        self.task["images"][0]["sha256"] = "b" * 64
        self.item["reuse_binding"]["product_identity_sha256"] = product_identity_sha256(self.task)
        self.rejected("ORIGINAL_PRODUCT_MISMATCH")

    def test_nested_test_marker_rejected_even_with_production_run(self):
        self.entry["payload"]["test_only"] = True
        self.save()
        self.rejected("NON_PRODUCTION")

    def test_immutable_eps_content_can_be_old_but_never_proves_status(self):
        self.deep()
        self.provider = "epo_publication_server"
        self.plan["queries"] = {self.provider: [self.original]}
        self.original["operation"] = self.row["operation"] = self.run["operation"] = "document_retrieval"
        self.run.update(provider=self.provider, authoritative_for_final_rating=False)
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        self.run["finished_at"] = old_date
        self.entry["payload"]["official_verification"]["checked_at"] = old_date
        self.entry["payload"].update(authority_scope="published_document_only", document_identity_match=True, claims=["original claim"])
        self.item["source_checked_at"] = old_date
        self.row["action_purpose"] = self.item["reuse_binding"]["action_purpose"] = "document_content"
        self.entry["payload"] = {"candidates": [self.entry["payload"]], "authority_scope": "published_document_only"}
        self.save()
        self.assertEqual(self.reuse()["authority_scope"], "published_document_only")
        self.row["action_purpose"] = self.item["reuse_binding"]["action_purpose"] = "official_verification"
        self.rejected("PUBLICATION_CANNOT_PROVE_STATUS_OR_RECALL")

    def browser(self):
        from record_browser_execution import planned_browser_query
        self.provider = "uspto_patent_browser"
        self.plan["queries"] = {self.provider: [self.original]}
        self.run["provider"] = self.provider
        screenshot = self.old / "screenshots" / "result.png"
        screenshot.parent.mkdir()
        atomic_write_json(screenshot, {"synthetic_screenshot_bytes": 1})
        self.entry["payload"]["browser_evidence"] = {"screenshot_path": str(screenshot), "screenshot_sha256": sha256_file(screenshot),
                                                       "screenshot_bytes": screenshot.stat().st_size, "checked_at": self.date}
        self.save()
        semantics = planned_browser_query(self.provider, self.original, self.old_task)
        capture = {"query_id": "OLD-Q", "status": "success", "final_url": "https://ppubs.uspto.gov/pubwebapp/",
                   "checked_at": self.date, "query_semantics": semantics, "result_coverage": self.run["metadata"]["search_coverage"],
                   "screenshot_path": str(screenshot), "candidates": deepcopy(self.records)}
        receipt = {"task_id": self.old_task["task_id"], "provider": self.provider, "query_id": "OLD-Q",
                   "operation": self.original["operation"], "jurisdiction": "US", "right_type": "patent", "query": self.original["q"],
                   "plan_entry_sha256": sha256_json(self.original), "mode": "automatic", "business_actions_by": "agent",
                   "outcome": "success", "final_url": capture["final_url"], "completed_at": self.date,
                   "query_semantics": semantics, "result_coverage_sha256": sha256_json(capture["result_coverage"]),
                   "media_coverage_sha256": sha256_json({}), "result_sha256": sha256_json(capture["candidates"]),
                   "events": [{"actor": "agent", "action": "submit_query", "at": self.date,
                               "rendered_query": semantics["rendered_query"], "input_value": semantics["rendered_query"]},
                              {"actor": "agent", "action": "observe_result", "at": self.date, "stable": True,
                               "screenshot_sha256": sha256_file(screenshot)}]}
        receipt_path = self.old / "raw" / "browser-execution" / "receipt.json"
        receipt_path.parent.mkdir(parents=True)
        atomic_write_json(receipt_path, receipt)
        capture["query_execution"] = self.binding(receipt_path)
        self.set_capture(capture)
        return capture, receipt, receipt_path

    def set_capture(self, capture):
        raw = self.old / "response.json"
        atomic_write_json(raw, capture)
        self.run["payload_digest"] = sha256_file(raw)
        atomic_write_json(self.old / "evidence.json", self.evidence)
        self.item.update(self.binding(self.old / "evidence.json"))

    def tsdr(self):
        """Build an original capture and its real recorder-sanitized retained JSON."""
        from provider_utils import sanitize_for_evidence
        from record_browser_execution import planned_browser_query
        self.deep()
        capture, receipt, receipt_path = self.browser()
        self.provider = "uspto_tsdr"
        self.plan["queries"] = {self.provider: [self.original]}
        for row in (self.original, self.row):
            row.update(q="11111111", serial_number="11111111", right_type="trademark_word")
        self.run.update(provider=self.provider, right_type="trademark_word")
        self.item["reuse_binding"]["right_type"] = "trademark_word"
        record = {"candidate_id": "C0", "serial_number": "11111111", "mark_text": "SYNTHETIC MARK",
                  "jurisdiction": "US", "right_type": "trademark_word"}
        self.candidates["patents"] = []
        self.candidates["trademarks"] = [{**record, "evidence_refs": ["REUSE-EV"]}]
        self.entry["payload"] = {**record, "official_verification": self.entry["payload"]["official_verification"],
                                 "browser_evidence": self.entry["payload"]["browser_evidence"]}
        self.save()
        capture.pop("candidates")
        capture.update(serial_number="11111111", page_case_number="11111111", candidate_id="C0",
                       right_type="trademark_word", mark_text="SYNTHETIC MARK", owner="Synthetic Owner",
                       cdp_session_id="synthetic-session-not-a-credential",
                       final_url="https://tsdr.uspto.gov/#caseNumber=11111111&caseSearchType=US_APPLICATION&searchType=statusSearch",
                       query_semantics=planned_browser_query(self.provider, self.original, self.old_task))
        receipt.update(provider=self.provider, query=self.original["q"], right_type="trademark_word",
                       final_url=capture["final_url"], query_semantics=capture["query_semantics"],
                       plan_entry_sha256=sha256_json(self.original),
                       result_sha256=sha256_json({"record_number": "11111111", "page_record_number": "11111111"}))
        receipt["events"][0] = {"actor": "agent", "action": "navigate_record", "at": self.date,
                                 "record_number": "11111111"}
        atomic_write_json(receipt_path, receipt)
        capture["query_execution"] = self.binding(receipt_path)
        original_path = self.old / "original-tsdr-capture.json"
        atomic_write_json(original_path, capture)
        self.item["historical_source"]["capture"] = self.binding(original_path)
        self.set_capture(sanitize_for_evidence(capture))
        return capture, receipt, receipt_path, original_path

    def test_tsdr_original_capture_restores_receipt_validation_without_mutation_or_rebinding(self):
        capture, _, _, original_path = self.tsdr()
        hashes = {path: sha256_file(path) for path in self.old.rglob("*") if path.is_file()}
        before = deepcopy((self.task, self.candidates, self.supplement))
        result = self.reuse()
        self.assertIsNotNone(result, historical_action_reuse_errors(
            self.task, self.provider, self.row, self.candidates, self.supplement, self.root))
        self.assertEqual(result["source_capture"], self.binding(original_path))
        self.assertEqual(result["source_capture_normalization"], "tsdr-retained-url-session-v1")
        self.assertEqual(result["source_query_id"], "OLD-Q")
        self.assertEqual(result["source_checked_at"], self.date)
        self.assertEqual(result["authority_scope"], "original_official_verification")
        self.assertEqual(before, (self.task, self.candidates, self.supplement))
        self.assertEqual(hashes, {path: sha256_file(path) for path in self.old.rglob("*") if path.is_file()})
        self.assertIn("#caseNumber=11111111", capture["final_url"])

    def test_tsdr_original_capture_is_explicit_not_auto_discovered(self):
        self.tsdr()
        self.item["historical_source"].pop("capture")
        self.rejected("AUTOMATIC_QUERY_EXECUTION_MISMATCH")

    def test_tsdr_original_capture_hash_size_and_old_directory_are_required(self):
        capture, _, _, original_path = self.tsdr()
        binding = self.binding(original_path)
        for field, value in (("sha256", "0" * 64), ("bytes", binding["bytes"] + 1)):
            with self.subTest(field=field):
                self.item["historical_source"]["capture"] = {**binding, field: value}
                self.rejected("HASH_OR_SIZE_MISMATCH")
        outside_old = self.root / "different-task-capture.json"
        atomic_write_json(outside_old, capture)
        self.item["historical_source"]["capture"] = self.binding(outside_old)
        self.rejected("ORIGINAL_CAPTURE_OUTSIDE_TASK")

    def test_tsdr_original_capture_never_masks_retained_body_or_query_changes(self):
        from provider_utils import sanitize_for_evidence
        capture, *_ = self.tsdr()
        for field, value in (("owner", "Different Owner"), ("mark_text", "Different mark"),
                             ("serial_number", "22222222"), ("query_id", "NEW-Q"),
                             ("status", "failed"), ("rendered_text", "invented document")):
            with self.subTest(field=field):
                retained = sanitize_for_evidence(capture)
                retained[field] = value
                self.set_capture(retained)
                self.rejected("ORIGINAL_CAPTURE_CONTENT_MISMATCH")
        retained = sanitize_for_evidence(capture)
        retained["query_execution"]["sha256"] = "0" * 64
        self.set_capture(retained)
        self.rejected("ORIGINAL_CAPTURE_RECEIPT_MISMATCH")

    def test_tsdr_original_capture_does_not_allow_other_sanitizer_content_redactions(self):
        from provider_utils import sanitize_for_evidence
        capture, _, _, original_path = self.tsdr()
        capture["rendered_text"] = "See https://example.com/document#substantive-section"
        atomic_write_json(original_path, capture)
        self.item["historical_source"]["capture"] = self.binding(original_path)
        self.set_capture(sanitize_for_evidence(capture))
        self.rejected("ORIGINAL_CAPTURE_CONTENT_MISMATCH")

    def test_tsdr_complete_original_receipt_is_still_revalidated(self):
        from provider_utils import sanitize_for_evidence
        capture, receipt, receipt_path, original_path = self.tsdr()
        receipt["query_id"] = "NEW-Q"
        atomic_write_json(receipt_path, receipt)
        capture["query_execution"] = self.binding(receipt_path)
        atomic_write_json(original_path, capture)
        self.item["historical_source"]["capture"] = self.binding(original_path)
        self.set_capture(sanitize_for_evidence(capture))
        self.rejected("AUTOMATIC_QUERY_EXECUTION_MISMATCH")

    def test_tsdr_original_capture_wrong_host_and_fixture_marker_are_rejected(self):
        from provider_utils import sanitize_for_evidence
        capture, receipt, receipt_path, original_path = self.tsdr()
        for field, value, error in (("final_url", "https://example.com/#caseNumber=11111111", "OFFICIAL_HOST_REQUIRED"),
                                    ("test_only", True, "BROWSER_CAPTURE_INVALID")):
            with self.subTest(field=field):
                changed = {**deepcopy(capture), field: value}
                receipt["final_url"] = changed["final_url"]
                atomic_write_json(receipt_path, receipt)
                changed["query_execution"] = self.binding(receipt_path)
                atomic_write_json(original_path, changed)
                self.item["historical_source"]["capture"] = self.binding(original_path)
                self.set_capture(sanitize_for_evidence(changed))
                self.rejected(error)

    def test_original_capture_extension_is_not_silently_applied_to_other_providers(self):
        capture, *_ = self.browser()
        original_path = self.old / "original-other-capture.json"
        atomic_write_json(original_path, capture)
        self.item["historical_source"]["capture"] = self.binding(original_path)
        self.rejected("ORIGINAL_CAPTURE_PROVIDER_UNSUPPORTED")

    def test_browser_original_execution_is_revalidated_not_rebound(self):
        capture, receipt, receipt_path = self.browser()
        self.assertIsNotNone(self.reuse(), historical_action_reuse_errors(self.task, self.provider, self.row, self.candidates, self.supplement, self.root))
        receipt["query_id"] = "NEW-Q"
        atomic_write_json(receipt_path, receipt)
        capture["query_execution"] = self.binding(receipt_path)
        self.set_capture(capture)
        self.rejected("AUTOMATIC_QUERY_EXECUTION_MISMATCH")

    def test_browser_missing_receipt_cannot_be_historical_success(self):
        capture, *_ = self.browser()
        capture.pop("query_execution")
        self.set_capture(capture)
        self.rejected("AUTOMATIC_QUERY_EXECUTION_REQUIRED")

    def test_normalized_browser_records_cannot_diverge_from_real_capture(self):
        capture, *_ = self.browser()
        self.entry["payload"]["candidates"][0]["publication_number"] = "US33333333B2"
        self.candidates["patents"][0]["publication_number"] = "US33333333B2"
        self.set_capture(capture)
        self.rejected("BROWSER_NORMALIZATION_MISMATCH")

    def test_retention_time_requires_original_source_date_and_meaning(self):
        self.item["source_checked_at"] = self.item["checked_at"]
        self.rejected("SOURCE_DATE_MISMATCH")
        self.item["source_checked_at"] = self.date
        self.item.pop("checked_at_meaning")
        self.rejected("CHECKED_AT_MEANING_REQUIRED")

    def test_root_is_explicit_without_task_directory_fallback(self):
        self.assertIsNone(historical_evidence_root(self.task, self.supplement))
        self.assertIsNone(historical_action_reuse(self.task, self.provider, self.row, self.candidates, self.supplement, None))
        self.supplement["evidence_root"] = str(self.root)
        self.assertEqual(historical_evidence_root(self.task, self.supplement), self.root.resolve())
        self.assertIsNotNone(historical_action_reuse(self.task, self.provider, self.row, self.candidates, self.supplement, None))

    def test_root_declarations_must_agree(self):
        self.task["historical_evidence_root"] = str(self.old)
        self.supplement["evidence_root"] = str(self.root)
        self.rejected("EVIDENCE_ROOT_CONFLICT")
        self.task["historical_evidence_root"] = str(self.root)
        self.assertIsNotNone(self.reuse())
        self.supplement["evidence_root"] = "relative-path"
        self.rejected("EVIDENCE_ROOT_MUST_BE_ABSOLUTE")


if __name__ == "__main__":
    unittest.main()
