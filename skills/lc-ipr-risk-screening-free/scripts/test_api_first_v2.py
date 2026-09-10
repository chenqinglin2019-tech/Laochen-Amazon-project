"""Synthetic offline convergence tests; fixtures are not live IP evidence."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json, sha256_file, serper_free_enhancement, serpapi_free_enhancement
from api_first_planning import (append_review, append_followup, dispatch_block, make_row, next_work_entries,
    _capacity_rows, _preferred_providers, _figurative_not_applicable, reviewed_unknown_submission,
    gap_limit_still_current, triage_digest, retained_discovery_work, source_files_error)
from workflow_v24 import generate_plan, scenario_dispatch_block_from_dir, product_identity_digest, build_coverage_requirements_v24
import test_api_first_planning as fixture


class ApiFirstV2Tests(unittest.TestCase):
    regenerate = fixture.ApiFirstPlanningTests.regenerate
    primary = fixture.ApiFirstPlanningTests.primary
    source = fixture.ApiFirstPlanningTests.source
    save = fixture.ApiFirstPlanningTests.save
    reload = fixture.ApiFirstPlanningTests.reload
    tearDown = fixture.ApiFirstPlanningTests.tearDown

    def setUp(self):
        fixture.ApiFirstPlanningTests.setUp(self)
        self.task["completion_policy_revision"] = "necessary-work-v2"
        self.regenerate()

    def many_terms(self, count=14):
        self.task["query_terms"] = [{"kind": "structural_feature", "value": "adjustable strap " + word,
            "language": "en", "derived_from": "product.structure[0]"}
            for word in ("clamp", "stop", "ring", "guide", "ratchet", "lock", "buckle", "lever", "hinge",
                "arm", "disc", "shaft", "spring", "wheel")[:count]]
        self.task["query_terms"].append({"kind": "design", "value": "strap bracket", "language": "en", "derived_from": "product.structure[0]"})

    def review_empty(self, row):
        run = self.source(row)
        self.task = load_json(self.path / "task.json")
        append_review(self.path, self.task, self.plan, self.evidence, row, {
            "source_run_id": run["run_id"], "reason": "Read the complete synthetic bounded empty result",
            "reviewer": "offline-agent", "outcome": "stop_bounded_discovery", "evidence_ids": ["EV-" + run["run_id"]],
            "triage_digest": triage_digest(self.task, self.evidence, self.candidates, self.ledger, query_id=row["query_id"])})
        self.task = load_json(self.path / "task.json")

    def no_api(self):
        self.task["serper_free_enhancement"] = serper_free_enhancement(False, "api-first-v1")
        self.task["serpapi_free_enhancement"] = serpapi_free_enhancement(False, "api-first-v1")
        self.task["signa_free_enhancement"]["enabled"] = False
        snapshot = {"schema_version": "2.4-free", "task_id": self.task["task_id"], "sources": [
            {"provider": provider, "state": "unvalidated", "reason": "browser_adapter_requires_real_route_acceptance",
                "executable": False, "checked_at": "2026-01-01T00:00:00Z", "cost_ceiling_usd": 0}
            for provider in ("uspto_patent_browser", "uspto_tmsearch_browser")]}
        atomic_write_json(self.path / "source-capabilities.json", snapshot)
        self.regenerate()
        return snapshot

    def audited_unknown(self):
        row = self.primary()
        run = self.source(row, status="failed")
        run["submission_state"] = "unknown"
        atomic_write_json(self.path / "evidence.json", self.evidence)
        before = deepcopy(run)
        record = append_review(self.path, self.task, self.plan, self.evidence, row, {
            "source_run_id": run["run_id"], "reason": "Inspected the retained receipt without finding confirmation of upstream submission",
            "reviewer": "offline-agent", "outcome": "blocked", "blocker": "The retained response does not establish whether the request was accepted",
            "evidence_ids": ["EV-" + run["run_id"]],
            "triage_digest": triage_digest(self.task, self.evidence, self.candidates, self.ledger, query_id=row["query_id"]),
            "submission_review": {"state": "unknown_after_receipt_review", "reasoning": "Read the source-run metadata and raw JSON; neither records a submission confirmation"}})
        self.task = load_json(self.path / "task.json")
        self.assertEqual(run, before)
        return row, run, record

    def retained_card(self, *, status="success"):
        row = self.primary()
        run = self.source(row, status=status)
        card = {"title": "Offline retained card awaiting merge", "publication_number": "US1234567A"}
        atomic_write_json(self.path / run["raw_paths"][0], {"organic": [card]})
        run["payload_digest"] = sha256_file(self.path / run["raw_paths"][0])
        self.evidence["collections"]["patents"][-1]["payload"]["candidates"] = [
            {**card, "source_record_sha256": sha256_json(card), "source_index": "google_patents"}]
        atomic_write_json(self.path / "evidence.json", self.evidence)
        return row, run

    def test_two_slots_cover_patent_and_design_instead_of_two_structure_synonyms(self):
        self.many_terms()
        self.task["serper_free_enhancement"]["max_queries_per_task"] = 2
        self.regenerate()
        rows = [r for p, values in self.plan["queries"].items() if p.startswith("serper_") for r in values]
        self.assertEqual([r["right_type"] for r in rows], ["patent", "design"])

    def test_country_right_round_robin_under_small_shared_budget(self):
        self.many_terms(4)
        self.task["target_jurisdictions"] = ["US", "GB", "DE"]
        self.task["coverage_requirements"] = build_coverage_requirements_v24(["US", "GB", "DE"],
            screening_revision="recall-integrity-v1", specialty_workflow_revision="asset-scope-v1")
        self.task["query_terms"].extend([
            {"kind": kind, "value": value, "language": "de", "derived_from": "product.structure[0]"}
            for kind, value in (("structural_feature", "Riemen Klemme"), ("design", "Riemen Halterung"))])
        self.task["serper_free_enhancement"]["max_queries_per_task"] = 4
        self.regenerate()
        rows = [r for p, values in self.plan["queries"].items() if p.startswith("serper_") for r in values]
        self.assertGreater(len({r["right_type"] for r in rows}), 1)
        self.assertGreater(len({r["jurisdiction"] for r in rows}), 1)
        self.assertEqual(len(rows), 4)

    def test_reserve_is_released_only_after_current_wave_reviews(self):
        self.many_terms()
        self.task["serper_free_enhancement"]["max_queries_per_task"] = 10
        self.regenerate()
        before = deepcopy(self.plan["queries"])
        rows = [r for p, values in before.items() if p.startswith("serper_") for r in values]
        self.assertEqual(len(rows), 8)
        unchanged = generate_plan(self.path, expand=True)
        self.assertEqual(unchanged["queries"], before)
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger)
        self.assertTrue(any(r["reason"] == "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP" and r["state"] == "ready" for r in entries))
        for row in rows:
            self.review_empty(row)
        self.plan = generate_plan(self.path, expand=True)
        all_rows = [r for p, values in self.plan["queries"].items() if p.startswith("serper_") for r in values]
        self.assertEqual(len(all_rows), 10)
        released = [r for r in all_rows if r["discovery_scope"].get("reserve_release")]
        self.assertEqual(len(released), 2)
        for provider, old_rows in before.items():
            self.assertEqual(self.plan["queries"][provider][:len(old_rows)], old_rows)
        for row in released:
            provider = next(p for p, values in self.plan["queries"].items() if row in values)
            self.assertIsNone(dispatch_block(self.task, self.plan, self.evidence, self.candidates, self.ledger, provider, row))
            bad = deepcopy(row)
            bad["discovery_scope"]["reserve_release"][0]["review_sha256"] = "0" * 64
            self.assertEqual(dispatch_block(self.task, self.plan, self.evidence, self.candidates, self.ledger, provider, bad),
                "API_DISCOVERY_RESERVE_RELEASE_INVALID")

    def test_selected_lens_supports_design_and_figurative_images(self):
        self.task["serpapi_free_enhancement"] = serpapi_free_enhancement(True, "api-first-v1")
        term = {"kind": "design", "value": "strap", "language": "en", "derived_from": "product.structure[0]",
            "discovery_channel": "image", "image_url": "https://example.com/product.png"}
        for right in ("design", "trademark_figurative", "copyright"):
            self.assertEqual(next(_preferred_providers(self.task, right, term, {}, "US")), "serpapi_google_lens")
        self.task["completion_policy_revision"] = "necessary-work-v1"
        self.assertNotIn("serpapi_google_lens", list(_preferred_providers(self.task, "design", term, {}, "US")))

    def test_official_api_requires_matching_country_right_and_executable_capability(self):
        self.task["coverage_requirements"] = build_coverage_requirements_v24(["FR", "EU"],
            screening_revision="recall-integrity-v1", specialty_workflow_revision="asset-scope-v1")
        caps = {p: {"executable": True} for p in ("inpi_api", "euipo_design", "euipo_trademark")}
        term = {"kind": "design", "value": "strap", "language": "en", "derived_from": "product.structure[0]"}
        self.assertIn("euipo_design", list(_preferred_providers(self.task, "design", term, caps, "EU")))
        self.assertNotIn("euipo_design", list(_preferred_providers(self.task, "design", term, caps, "US")))
        self.assertIn("inpi_api", list(_preferred_providers(self.task, "patent", term, caps, "FR")))
        caps["inpi_api"]["executable"] = False
        self.assertNotIn("inpi_api", list(_preferred_providers(self.task, "patent", term, caps, "FR")))

    def test_no_selected_api_can_use_bounded_browser_with_snapshot_bound_basis(self):
        snapshot = self.no_api()
        browser_rows = [(p, r) for p, values in self.plan["queries"].items() if p.endswith("browser") for r in values]
        self.assertTrue(browser_rows)
        for provider, row in browser_rows:
            self.assertEqual(row["discovery_scope"]["capability_basis"]["snapshot_sha256"], sha256_json(snapshot))
            self.assertEqual(row["required_for"], "discovery_only")
            self.assertNotIn("parent_query_id", row)
            self.assertIsNone(scenario_dispatch_block_from_dir(self.path, provider, row))
        before = deepcopy(self.plan["queries"])
        self.assertEqual(generate_plan(self.path, expand=True)["queries"], before)
        snapshot["sources"][0]["reason"] = "automation_policy_incompatible"
        atomic_write_json(self.path / "source-capabilities.json", snapshot)
        provider, row = next((p, r) for p, r in browser_rows if p == "uspto_patent_browser")
        self.assertEqual(scenario_dispatch_block_from_dir(self.path, provider, row)["code"], "API_DISCOVERY_CAPABILITY_SNAPSHOT_CHANGED")

    def test_missing_capability_snapshot_never_forges_no_api_proof(self):
        self.no_api()
        (self.path / "source-capabilities.json").unlink()
        self.regenerate()
        self.assertFalse(any(p.endswith("browser") and rows for p, rows in self.plan["queries"].items()))

    def test_snapshot_refresh_requires_explicit_append_only_repair(self):
        snapshot = self.no_api()
        provider = "uspto_patent_browser"
        row = self.plan["queries"][provider][0]
        before = deepcopy(row)
        snapshot["sources"][0]["checked_at"] = "2026-01-02T00:00:00Z"
        atomic_write_json(self.path / "source-capabilities.json", snapshot)
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertTrue(any(r.get("query_id") == row["query_id"] and r["reason"] == "API_DISCOVERY_CAPABILITY_SNAPSHOT_CHANGED"
            and r["state"] == "ready" for r in entries))
        replacement = append_followup(self.path, {"role": "plan_repair", "parent_query_id": row["query_id"],
            "provider": provider, "reviewer": "offline-agent", "reason": "Revalidated the same unsubmitted route against the updated capability snapshot"})
        self.reload()
        self.assertEqual(self.plan["queries"][provider][0], before)
        self.assertNotEqual(row["query_id"], replacement["query_id"])
        self.assertIsNone(scenario_dispatch_block_from_dir(self.path, provider, replacement))
        self.assertTrue(any(d["query_id"] == row["query_id"] and d["status"] == "cancelled" for d in self.plan["execution_dispositions"]))

    def test_cancelled_unsubmitted_releases_capacity_but_unknown_does_not(self):
        row = self.primary()
        self.plan.setdefault("execution_dispositions", []).append({"query_id": row["query_id"],
            "plan_entry_sha256": sha256_json(row), "status": "cancelled", "reason": "Corrected unsupported syntax before submission"})
        run = self.source(row, status="failed")
        run["submission_state"] = "not_submitted"
        self.assertNotIn(("serper_patents", row), _capacity_rows(self.task, self.plan, self.evidence))
        run["submission_state"] = "unknown"
        self.assertIn(("serper_patents", row), _capacity_rows(self.task, self.plan, self.evidence))
        self.task["completion_policy_revision"] = "necessary-work-v1"
        run["submission_state"] = "not_submitted"
        self.assertIn(("serper_patents", row), _capacity_rows(self.task, self.plan, self.evidence))

    def test_unknown_api_submission_is_never_misreported_as_reviewable_failure(self):
        row = self.primary()
        self.source(row)  # A prior submitted success cannot hide a later unknown submission.
        run = self.source(row, status="failed")
        run["submission_state"] = "unknown"
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger)
        current = [r for r in entries if r.get("query_id") == row["query_id"]]
        self.assertTrue(current)
        self.assertEqual({r["state"] for r in current}, {"submission_unknown"})

    def test_reviewed_unknown_has_bound_disclosable_limit_without_rewriting_run(self):
        row, run, record = self.audited_unknown()
        audited = reviewed_unknown_submission(self.task, self.plan, self.evidence, self.candidates, self.ledger, row, task_dir=self.path)
        self.assertEqual(audited[0]["review_sha256"], sha256_json(record))
        self.assertEqual(audited[0]["submission_state"], "unknown")
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        item = next(r for r in entries if r.get("query_id") == row["query_id"])
        self.assertEqual((item["state"], item["reason"]), ("blocked", "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW"))
        self.assertEqual(item["delivery_limit"]["submission_review_refs"], audited)
        self.assertEqual(run["submission_state"], "unknown")

    def test_prior_success_keeps_merge_work_alongside_reviewed_unknown_and_blocks_delivery(self):
        row, prior = self.retained_card()
        self.assertIsNone(source_files_error(self.path, self.evidence, prior))
        row, unknown, audit = self.audited_unknown()
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        current = [item for item in entries if item.get("query_id") == row["query_id"]]
        self.assertEqual({item["reason"] for item in current},
            {"API_DISCOVERY_MERGE_REQUIRED", "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW"})
        merge = next(item for item in current if item["reason"] == "API_DISCOVERY_MERGE_REQUIRED")
        self.assertEqual(merge["state"], "awaiting_review")
        self.assertEqual(merge["retained_source_run_ids"], [prior["run_id"]])
        self.assertEqual(unknown["submission_state"], "unknown")
        self.assertEqual(dispatch_block(self.task, self.plan, self.evidence, self.candidates, self.ledger,
            "serper_patents", row), "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY")
        # Isolate scope-review setup, not the real retained-work or publication gate.
        from necessary_completion import publication_context
        assessment = {"status": "incomplete", "coverage": {"scopes": []},
            "review": {"input_reviews": {"first": {}, "second": {}}}}
        with patch("necessary_completion.review_work",
                return_value={"entries": [], "evidence_digest": "offline-only"}):
            with self.assertRaisesRegex(ValueError, "EVIDENCE_AGENT_WORK_REMAINS"):
                publication_context(self.task, self.evidence, self.candidates, self.plan, self.ledger, assessment,
                    mode="evidence", task_dir=self.path)

    def test_later_empty_result_cannot_authorize_stop_over_prior_unmerged_cards(self):
        row, prior = self.retained_card()
        with self.assertRaisesRegex(ValueError, "API_DISCOVERY_MERGE_REQUIRED"):
            self.review_empty(row)
        current = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertTrue(any(item.get("query_id") == row["query_id"] and item["reason"] == "API_DISCOVERY_MERGE_REQUIRED"
            for item in current))

    def test_partial_prior_cards_and_changed_old_receipt_survive_latest_empty_attempt(self):
        row, prior = self.retained_card(status="failed")
        self.source(row)
        current = retained_discovery_work(self.task, self.evidence, self.candidates, self.ledger,
            "serper_patents", row, task_dir=self.path)
        self.assertEqual(current["reason"], "API_DISCOVERY_MERGE_REQUIRED")
        atomic_write_json(self.path / prior["raw_paths"][0], {"organic": []})
        current = retained_discovery_work(self.task, self.evidence, self.candidates, self.ledger,
            "serper_patents", row, task_dir=self.path)
        self.assertEqual(current["reason"], "API_DISCOVERY_SOURCE_FILES_INVALID")
        self.assertTrue(current["integrity_failure"])

    def test_cancelled_query_keeps_prior_card_work_and_v1_behavior_is_unchanged(self):
        row, prior = self.retained_card()
        self.plan.setdefault("execution_dispositions", []).append({"query_id": row["query_id"],
            "plan_entry_sha256": sha256_json(row), "status": "cancelled", "reason": "Offline replacement retained old query bytes"})
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertTrue(any(item.get("query_id") == row["query_id"] and item["reason"] == "API_DISCOVERY_MERGE_REQUIRED"
            for item in entries))
        self.assertIn(("serper_patents", row), _capacity_rows(self.task, self.plan, self.evidence))
        self.task["completion_policy_revision"] = "necessary-work-v1"
        self.assertIsNone(retained_discovery_work(self.task, self.evidence, self.candidates, self.ledger,
            "serper_patents", row, task_dir=self.path))

    def test_pending_card_reconcile_and_api_dispatch_defer_without_cancelling_then_allow_review(self):
        from workflow_v24 import reconcile_scenario_actions, validated_query_cancellation, work_view_from_dir
        from runtime_v24 import execute_api_plan
        row, run = self.retained_card()
        disposition = scenario_dispatch_block_from_dir(self.path, "serper_patents", row)
        self.assertEqual((disposition["reason"], disposition["cause"]),
            ("TRIAGE_REVIEW_REQUIRED", "API_DISCOVERY_MERGE_REQUIRED"))
        reconcile_scenario_actions(self.path, self.task, self.plan, self.candidates, self.ledger, self.evidence)
        self.assertIsNone(validated_query_cancellation(self.task, self.plan, row))
        before_evidence = (self.path / "evidence.json").read_bytes()
        with patch("runtime_v24.subprocess.run", side_effect=AssertionError("Offline test cannot submit any source request")):
            result = execute_api_plan(self.path, query_ids_filter=[row["query_id"]], phase="discovery")
        self.reload()
        self.assertEqual(result["results"][0]["dispatch"], "deferred")
        self.assertEqual(result["results"][0]["reason"], "TRIAGE_REVIEW_REQUIRED")
        self.assertEqual((self.path / "evidence.json").read_bytes(), before_evidence)
        self.assertIsNone(validated_query_cancellation(self.task, self.plan, row))
        current = work_view_from_dir(self.path)
        self.assertTrue(any(item.get("query_id") == row["query_id"] and item["reason"] == "API_DISCOVERY_MERGE_REQUIRED"
            for item in current["entries"]))
        from merge_candidates import merge, apply_candidate_contract, candidate_verification_view
        from decision_workflow import make_annotation
        merged = merge("patent", self.evidence["collections"]["patents"], {r["run_id"]: r for r in self.evidence["source_runs"]})
        apply_candidate_contract("patent", merged)
        self.candidates["patents"] = [candidate_verification_view(self.task, "patents", candidate, self.evidence, {}) for candidate in merged]
        self.assertEqual(len(self.candidates["patents"]), 1)
        candidate = self.candidates["patents"][0]
        self.ledger["annotations"].append(make_annotation(self.task, "patents", candidate, {
            "annotation_id": "READ-RETAINED-OFFLINE", "decision": "not_selected", "scenario_id": "product_entry",
            "reason": "Read the retained fixture card and compared its scope", "reviewer": "offline-agent",
            "annotated_at": "2026-01-01T00:00:00Z", "evidence_refs": ["EV-" + run["run_id"]],
            "reading_level": "result_record", "basis_summary": "The complete fixture title and record identity were read",
            "reopen_conditions": ["New original protection-content evidence"]}, evidence=self.evidence))
        self.save()
        self.assertIsNone(scenario_dispatch_block_from_dir(self.path, "serper_patents", row))
        append_review(self.path, self.task, self.plan, self.evidence, row, {
            "source_run_id": run["run_id"], "reason": "All retained cards merged and reviewed", "reviewer": "offline-agent",
            "outcome": "stop_bounded_discovery", "evidence_ids": ["EV-" + run["run_id"]],
            "triage_digest": triage_digest(self.task, self.evidence, self.candidates, self.ledger, query_id=row["query_id"])})
        self.reload()
        self.assertIsNone(validated_query_cancellation(self.task, self.plan, row))
        self.assertFalse(any(item.get("query_id") == row["query_id"] for item in next_work_entries(
            self.task, self.plan, self.evidence, self.candidates, self.ledger, task_dir=self.path)))

    def test_prior_submitted_success_cannot_make_later_unknown_a_permanent_cancellation(self):
        from workflow_v24 import reconcile_scenario_actions, validated_query_cancellation
        row = self.primary()
        self.source(row)
        unknown = self.source(row, status="failed")
        unknown["submission_state"] = "unknown"
        atomic_write_json(self.path / "evidence.json", self.evidence)
        block = scenario_dispatch_block_from_dir(self.path, "serper_patents", row)
        self.assertEqual((block["reason"], block["cause"]),
            ("TRIAGE_ATTEMPT_STATE_UNKNOWN", "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY"))
        reconcile_scenario_actions(self.path, self.task, self.plan, self.candidates, self.ledger, self.evidence)
        self.assertIsNone(validated_query_cancellation(self.task, self.plan, row))
        self.assertEqual(unknown["submission_state"], "unknown")

    def test_unknown_review_never_allows_redispatch_or_releases_consumption_reservation(self):
        row, run, record = self.audited_unknown()
        self.assertEqual(dispatch_block(self.task, self.plan, self.evidence, self.candidates, self.ledger,
            "serper_patents", row), "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY")
        self.assertIsNotNone(scenario_dispatch_block_from_dir(self.path, "serper_patents", row))
        self.plan.setdefault("execution_dispositions", []).append({"query_id": row["query_id"],
            "plan_entry_sha256": sha256_json(row), "status": "cancelled", "reason": "No further requests allowed"})
        self.assertIn(("serper_patents", row), _capacity_rows(self.task, self.plan, self.evidence))

    def test_unknown_receipt_or_review_tampering_reopens_the_unresolved_work(self):
        row, run, record = self.audited_unknown()
        atomic_write_json(self.path / run["raw_paths"][0], {"organic": [], "changed_receipt": True})
        self.assertIsNone(reviewed_unknown_submission(self.task, self.plan, self.evidence, self.candidates, self.ledger,
            row, task_dir=self.path))
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(next(r for r in entries if r.get("query_id") == row["query_id"])["state"], "submission_unknown")
        record["submission_review"]["source_run_sha256"] = "0" * 64
        self.task["discovery_followups"][-1] = record
        self.assertIsNone(reviewed_unknown_submission(self.task, self.plan, self.evidence, self.candidates, self.ledger, row))

    def test_account_stop_preserves_native_lane_stop_and_does_not_spawn_more_requests(self):
        self.many_terms()
        self.task["serper_free_enhancement"]["max_queries_per_task"] = 10
        self.regenerate()
        row = self.primary()
        run = self.source(row, status="failed")
        run.update(error_code="FREE_QUOTA_EXHAUSTED", quota={"network_request_attempted": True})
        atomic_write_json(self.path / "evidence.json", self.evidence)
        before = deepcopy(self.plan["queries"])
        self.plan = generate_plan(self.path, expand=True)
        self.assertEqual(self.plan["queries"], before)
        self.assertTrue(any(g["code"] == "API_DISCOVERY_ACCOUNT_STOPPED" for g in self.plan["planning_gaps"]))
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertTrue(any(r.get("query_id") == row["query_id"] and r["reason"] == "API_DISCOVERY_REVIEW_REQUIRED" for r in entries))
        stopped = [r for r in entries if r["reason"] == "API_DISCOVERY_ACCOUNT_STOPPED"]
        self.assertTrue(stopped)
        self.assertTrue(all(r["state"] == "blocked" and r["delivery_limit"]["source_run_refs"] for r in stopped))

    def test_unreviewed_real_response_remains_actionable_and_bound_review_closes_it(self):
        row = self.primary()
        self.source(row)
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertTrue(any(r.get("query_id") == row["query_id"] and r["reason"] == "API_DISCOVERY_REVIEW_REQUIRED" for r in entries))
        self.review_empty(row)
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertFalse(any(r.get("query_id") == row["query_id"] for r in entries))

    def test_capability_missing_credentials_is_access_state_with_canonical_proof(self):
        cap = {"provider": "serper_patents", "executable": False, "state": "unavailable",
            "reason": "optional_credentials_missing", "human_actions": ["login"]}
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger,
            source_capabilities={"serper_patents": cap})
        current = next(r for r in entries if r.get("query_id") == self.primary()["query_id"])
        self.assertEqual(current["state"], "awaiting_access")
        self.assertEqual(current["delivery_limit"]["capability_refs"][0]["sha256"],
            sha256_json({k: v for k, v in cap.items() if k != "human_actions"}))
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger,
            source_capabilities={"serper_patents": {**cap, "reason": "unknown"}})
        current = next(r for r in entries if r.get("query_id") == self.primary()["query_id"])
        self.assertEqual(current["state"], "ready")
        self.assertNotIn("delivery_limit", current)

    def test_recovered_capability_reopens_a_stale_route_gap_and_filters_unrelated_proof(self):
        unavailable = {"provider": "serper_patents", "executable": False, "state": "unavailable", "reason": "optional_credentials_missing"}
        old_caps = {"serper_patents": unavailable,
            "epo_ops": {"provider": "epo_ops", "executable": False, "state": "unavailable", "reason": "optional_credentials_missing"},
            "uspto_patent_browser": {"provider": "uspto_patent_browser", "executable": False,
                "state": "blocked", "reason": "automation_policy_incompatible"},
            "serper_images": {"provider": "serper_images", "executable": True, "reason": "ready", "state": "automatic"}}
        atomic_write_json(self.path / "source-capabilities.json", {"task_id": self.task["task_id"], "sources": list(old_caps.values())})
        self.regenerate()
        gap = next(g for g in self.plan["planning_gaps"] if g.get("right_type") == "patent" and g["code"] == "API_DISCOVERY_ROUTE_UNAVAILABLE")
        self.assertTrue(gap_limit_still_current(self.task, self.plan, self.evidence, self.candidates, self.ledger, gap, old_caps))
        old_view = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, source_capabilities=old_caps)
        item = next(r for r in old_view if r.get("discovery_intent_id") == gap["discovery_intent_id"])
        self.assertEqual({r["provider"] for r in item["delivery_limit"]["capability_refs"]},
            {"serper_patents", "epo_ops", "uspto_patent_browser"})
        recovered = {**old_caps, "serper_patents": {**unavailable, "executable": True, "state": "automatic", "reason": "ready"}}
        missing = {k: v for k, v in old_caps.items() if k != "uspto_patent_browser"}
        unknown = {**old_caps, "uspto_patent_browser": {**old_caps["uspto_patent_browser"], "reason": "unknown"}}
        for label, changed in (("recovered", recovered), ("missing", missing), ("unknown", unknown)):
            with self.subTest(capability=label):
                self.assertFalse(gap_limit_still_current(self.task, self.plan, self.evidence, self.candidates, self.ledger, gap, changed))
                current = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger, source_capabilities=changed)
                reopened = next(r for r in current if r.get("discovery_intent_id") == gap["discovery_intent_id"])
                self.assertEqual((reopened["state"], reopened["reason"]), ("ready", "API_DISCOVERY_REPLAN_REQUIRED"))
                self.assertNotIn("delivery_limit", reopened)

    def test_empty_inventory_alone_does_not_suppress_missing_figurative_search(self):
        before = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger)
        self.assertTrue(any(r.get("right_type") == "trademark_figurative" and r["reason"] == "API_DISCOVERY_TERMS_MISSING" for r in before))
        with patch("record_asset_provenance.asset_scope", return_value={"inventory_reviewed": True, "asset_ids": []}):
            self.assertFalse(_figurative_not_applicable(self.task, {"queries": {}}, self.evidence, self.candidates,
                self.ledger, "brand_reuse", "US"))
        with patch("api_first_planning._figurative_not_applicable", return_value=True):
            entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger)
            self.assertFalse(any(r.get("right_type") == "trademark_figurative" for r in entries))


if __name__ == "__main__":
    from offline_test_support import isolated_test_environment
    with isolated_test_environment():
        unittest.main()
