"""Offline regression for bounded delivery; fixtures assert no live clearance."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from common import sha256_json
from offline_test_support import isolated_test_environment
import necessary_completion as completion
import test_necessary_completion as legacy_fixture
from test_assessment_estimate_scenarios import refresh


class EvidenceDeliveryCompletionTests(unittest.TestCase):
    def setUp(self):
        self.isolation = isolated_test_environment()
        self.isolation.__enter__()
        self.addCleanup(self.isolation.__exit__, None, None, None)
        self.f = legacy_fixture.NecessaryCompletionTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.task["completion_policy_revision"] = "necessary-work-v2"
        refresh(self.f.values)

    def test_auto_resolves_to_evidence_without_rewriting_assessment(self):
        result = self.f.calculate(False)
        before = deepcopy(result)
        proof = self.f.proof(result, self.f.blocked_view(), mode="auto")
        self.assertEqual(proof["mode"], "evidence")
        self.assertEqual(proof["delivery_status"], "ready")
        self.assertEqual(proof["delivery_basis"], "source_evidence")
        self.assertEqual(result, before)
        self.assertEqual(result["overall"]["risk"], "高")
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(all(row["official_verification"] == "not_verified" for row in proof["limitations"]))

    def test_explicit_final_stays_strict_and_legacy_auto_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "PUBLICATION_NECESSARY_WORK_INCOMPLETE"):
            self.f.proof(self.f.calculate(False), self.f.blocked_view(), mode="final")
        self.f.task["completion_policy_revision"] = completion.REVISION
        refresh(self.f.values)
        for mode in ("auto", "evidence"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "PUBLICATION_MODE_INVALID"):
                self.f.proof(self.f.calculate(False), self.f.blocked_view(), mode=mode)

    def test_agent_read_review_plan_and_unknown_submission_are_not_exempted(self):
        for state in ("ready", "awaiting_review", "submission_unknown"):
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, "EVIDENCE_AGENT_WORK_REMAINS"):
                self.f.proof(self.f.calculate(False), self.f.blocked_view(state), mode="evidence")
        for reason in ("API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP", "API_DISCOVERY_SOURCE_FILES_INVALID",
                       "API_DISCOVERY_ROUTE_UNAVAILABLE"):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, "EVIDENCE_(AGENT_WORK_REMAINS|LIMITATION_NOT_ESTABLISHED)"):
                self.f.proof(self.f.calculate(False), self.f.blocked_view("blocked", reason), mode="evidence")

    def test_pending_risk_can_be_delivered_but_missing_scope_review_cannot(self):
        for review in (self.f.first, self.f.second):
            for row in review["assessments"]:
                row.update(risk=None, assessment_status="pending", pending_reasoning="No qualified source evidence for a rating.")
        result = self.f.calculate(False)
        proof = self.f.proof(result, self.f.blocked_view(), mode="evidence")
        self.assertEqual(proof["delivery_status"], "ready")
        self.assertIsNone(result["overall"]["risk"])
        self.f.second["assessments"].pop()
        self.f.first["assessments"].pop()
        result = self.f.calculate(False)
        with self.assertRaisesRegex(ValueError, "PUBLICATION_SCOPE_REVIEW_REQUIRED"):
            self.f.proof(result, self.f.blocked_view(), mode="evidence")

    def test_auto_final_does_not_persist_auto_or_global_verified_claim(self):
        view = {"status": "complete", "entries": [], "counts": {}, "unresolved_scopes": []}
        proof = self.f.proof(self.f.calculate(), view)
        self.assertEqual(proof["mode"], "final")
        self.assertEqual(proof["delivery_status"], "ready")
        self.assertEqual(proof["limitations"], [])
        self.assertNotIn("official_verified", str(proof))

    def test_reviewed_unknown_fact_needs_substantive_source_not_a_stop_sentence(self):
        for review in (self.f.first, self.f.second):
            for row in review["assessments"]:
                row.update(risk=None, assessment_status="pending", pending_reasoning="Source read; exact right remains unknown.")
        result = self.f.calculate(False)
        view = self.f.blocked_view()
        view["entries"] = []
        proof = self.f.proof(result, view, mode="evidence")
        self.assertTrue(proof["limitations"])
        self.assertTrue(all(item["reason"] == "REVIEWED_FACT_REMAINS_UNCONFIRMED" for item in proof["limitations"]))
        for row in result["assessments"]:
            row["evidence_refs"] = ["EV-PRODUCT"]
        with self.assertRaisesRegex(ValueError, "EVIDENCE_(UNRESOLVED_SCOPE|PENDING_ASSESSMENT)_WITHOUT_LIMITATION"):
            self.f.proof(result, view, mode="evidence")

    def test_source_constraints_require_exact_frozen_proof(self):
        cap = {"provider": "uspto_tmsearch_browser", "executable": False, "reason": "optional_credentials_missing"}
        term = {"kind": "brand", "value": "Offline mark", "language": "en", "derived_from": "product.brand"}
        gap = {"code": "API_DISCOVERY_ROUTE_UNAVAILABLE", "jurisdiction": "US", "right_type": "trademark_word", "term_id": sha256_json(term)}
        plan = {"planning_gaps": [gap], "terms": [term]}
        row = {**gap, "reason": gap["code"], "delivery_limit": {"kind": "source_constraint", "reason": gap["code"],
            "official_verification": "not_verified", "planning_gap_sha256": sha256_json(gap),
            "source_run_refs": [], "capability_refs": [{"provider": cap["provider"], "sha256": sha256_json(cap)}]}}
        self.assertTrue(completion._delivery_limit_valid(row, self.f.task, self.f.evidence, plan, {cap["provider"]: cap}))
        changed = deepcopy(row)
        changed["delivery_limit"]["capability_refs"][0]["sha256"] = "changed"
        self.assertFalse(completion._delivery_limit_valid(changed, self.f.task, self.f.evidence, plan, {cap["provider"]: cap}))
        row["reason"] = row["delivery_limit"]["reason"] = "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP"
        self.assertFalse(completion._delivery_limit_valid(row, self.f.task, self.f.evidence, plan, {cap["provider"]: cap}))

    def test_snapshot_keeps_exact_operation_receipts_but_no_secret_payload(self):
        operation = {"jurisdiction": "US", "right_type": "patent", "operation": "patent_recall",
            "query_compiler_revision": "query-v1", "query_id": "Q", "plan_entry_sha256": "plan",
            "source_run_id": "R", "source_run_sha256": "run", "token": "must-not-leak"}
        snapshots = {"source-capabilities.json": {"task_id": self.f.task["task_id"], "sources": [
            {"provider": "uspto_patent_browser", "executable": False, "operations": [operation]}]},
            "browser-execution-status.json": {"task_id": self.f.task["task_id"], "queries": [
                {"query_id": "Q", "capture_path": "capture.json", "capture_sha256": "capture", "capture_status": "success", "cookie": "must-not-leak"}]}}
        cleaned = completion.sanitize_snapshots(self.f.task, snapshots)
        self.assertEqual(cleaned["source-capabilities.json"]["sources"][0]["operations"][0]["source_run_id"], "R")
        self.assertEqual(cleaned["browser-execution-status.json"]["queries"][0]["capture_path"], "capture.json")
        self.assertNotIn("must-not-leak", str(cleaned))


class EvidenceDeliveryBoundedProofTests(unittest.TestCase):
    def setUp(self):
        self.isolation = isolated_test_environment()
        self.isolation.__enter__()
        self.addCleanup(self.isolation.__exit__, None, None, None)
        from test_api_first_planning import ApiFirstPlanningTests
        self.f = ApiFirstPlanningTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.task["completion_policy_revision"] = "necessary-work-v2"
        self.f.save()
        self.scope = {"scenario_id": self.f.task["primary_scenario_id"], "jurisdiction": "US", "right_type": "patent"}

    def bounded_review(self):
        from api_first_planning import append_followup
        request = self.f.request(role="review")
        request.update(outcome="stop_bounded_discovery", reason="Synthetic bounded source sample has been reviewed.")
        append_followup(self.f.path, request)
        self.f.reload()

    def resolve(self, extras=(), capabilities=None):
        view = {"entries": [{**self.scope, "kind": "plan_repair", "state": "ready",
            "reason": "COV-US-PATENT-RECALL:AXIS_MISSING:text"}, *deepcopy(extras)]}
        caps = capabilities if capabilities is not None else {"epo_ops": {"provider": "epo_ops", "executable": False, "reason": "optional_credentials_missing"},
            "uspto_patent_browser": {"provider": "uspto_patent_browser", "executable": False, "reason": "automation_policy_incompatible"}}
        return completion._resolve_evidence_limits(self.f.task, view, self.f.plan, caps, self.f.evidence,
            self.f.candidates, self.f.ledger, task_dir=self.f.path)

    def test_only_current_retained_review_can_limit_official_gap(self):
        self.assertEqual(self.resolve()["entries"][0]["state"], "ready")
        self.bounded_review()
        item = self.resolve()["entries"][0]
        self.assertEqual(item["reason"], "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED")
        self.assertEqual(item["official_verification"], "not_verified")
        self.assertTrue(item["source_run_refs"] and item["evidence_refs"])
        self.f.task["discovery_followups"][-1]["source_run_sha256"] = "stale"
        self.assertEqual(self.resolve()["entries"][0]["state"], "ready")

    def test_other_scope_stop_and_unperformed_work_cannot_close_this_scope(self):
        self.bounded_review()
        for kind, state, reason in (("agent_read", "awaiting_review", "RETAINED_ORIGINAL_REQUIRES_READING"),
                ("agent_investigation", "ready", "AGENT_INVESTIGATION_REQUIRED"),
                ("plan_repair", "blocked", "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP")):
            extra = {**self.scope, "kind": kind, "state": state, "reason": reason}
            with self.subTest(kind=kind, reason=reason):
                self.assertEqual(self.resolve([extra])["entries"][0]["state"], "ready")
        self.scope["jurisdiction"] = "JP"
        self.assertEqual(self.resolve()["entries"][0]["state"], "ready")

    def test_bounded_review_cannot_skip_available_or_unchecked_official_route(self):
        self.bounded_review()
        for caps in ({}, {"uspto_patent_browser": {"provider": "uspto_patent_browser", "executable": True}}):
            with self.subTest(caps=caps):
                self.assertEqual(self.resolve(capabilities=caps)["entries"][0]["reason"], "AUTHORIZED_ALTERNATIVE_REQUIRES_PLANNING")

    def test_unknown_only_becomes_limitation_after_exact_receipt_review(self):
        from api_first_planning import append_followup, triage_digest
        from common import atomic_write_json
        row = self.f.primary()
        run = self.f.source(row, status="failed")
        run["submission_state"] = "unknown"
        atomic_write_json(self.f.path / "evidence.json", self.f.evidence)
        extra = {**self.scope, "query_id": row["query_id"], "provider": run["provider"],
            "kind": "source_lookup", "state": "submission_unknown", "reason": "VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY"}
        self.assertEqual(self.resolve([extra])["entries"][1]["state"], "submission_unknown")
        append_followup(self.f.path, {"role": "review", "parent_query_id": row["query_id"], "source_run_id": run["run_id"],
            "reviewer": "offline-receipt-agent", "outcome": "blocked", "blocker": "Receipt does not establish submission.",
            "reason": "Read the exact retained response; must not repeat this request.", "evidence_ids": ["EV-" + run["run_id"]],
            "triage_digest": triage_digest(self.f.task, self.f.evidence, self.f.candidates, self.f.ledger, query_id=row["query_id"]),
            "submission_review": {"state": "unknown_after_receipt_review", "reasoning": "Retained response lacks acknowledgement."}})
        self.f.reload()
        item = self.resolve([extra])["entries"][1]
        self.assertEqual(item["reason"], "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW")
        self.assertEqual(run["submission_state"], "unknown")
        self.assertTrue(completion._delivery_limit_valid(item, self.f.task, self.f.evidence, self.f.plan, {},
            candidates=self.f.candidates, ledger=self.f.ledger, task_dir=self.f.path))
        item["delivery_limit"]["submission_review_refs"][0]["review_sha256"] = "tampered"
        self.assertFalse(completion._delivery_limit_valid(item, self.f.task, self.f.evidence, self.f.plan, {},
            candidates=self.f.candidates, ledger=self.f.ledger, task_dir=self.f.path))
        atomic_write_json(self.f.path / run["raw_paths"][0], {"changed": True})
        self.assertEqual(self.resolve([extra])["entries"][1]["state"], "submission_unknown")

    def test_frozen_gap_cannot_hide_restored_api_capacity(self):
        from api_first_planning import next_work_entries
        from common import atomic_write_json
        caps = {provider: {"provider": provider, "executable": False, "reason": "automation_policy_incompatible"}
            for provider in ("serper_patents", "serper_web", "serper_images", "epo_ops", "uspto_patent_browser", "uspto_tmsearch_browser")}
        atomic_write_json(self.f.path / "source-capabilities.json", {"task_id": self.f.task["task_id"], "sources": list(caps.values())})
        self.f.regenerate()
        entries = next_work_entries(self.f.task, self.f.plan, self.f.evidence, self.f.candidates,
            self.f.ledger, task_dir=self.f.path, source_capabilities=caps)
        item = next(entry for entry in entries if entry.get("delivery_limit", {}).get("planning_gap_sha256")
            and entry.get("right_type") == "patent")
        self.assertTrue(completion._delivery_limit_valid(item, self.f.task, self.f.evidence, self.f.plan, caps,
            candidates=self.f.candidates, ledger=self.f.ledger, task_dir=self.f.path))
        restored = deepcopy(caps)
        restored["serper_patents"].update(executable=True, reason="first_real_query_checks_free_account_and_contract")
        # Rehashing a refreshed capability cannot make the obsolete gap current.
        changed = deepcopy(item)
        for ref in changed["delivery_limit"]["capability_refs"]:
            ref["sha256"] = sha256_json(restored[ref["provider"]])
        self.assertFalse(completion._delivery_limit_valid(changed, self.f.task, self.f.evidence, self.f.plan, restored,
            candidates=self.f.candidates, ledger=self.f.ledger, task_dir=self.f.path))
        unknown = deepcopy(caps)
        unknown["serper_patents"]["reason"] = "SOURCE_CAPABILITY_CHECK_REQUIRED"
        missing = deepcopy(caps)
        missing.pop("serper_patents")
        for current in (unknown, missing):
            updated = deepcopy(item)
            updated["delivery_limit"]["capability_refs"] = [{"provider": ref["provider"], "sha256": sha256_json(current[ref["provider"]])}
                for ref in item["delivery_limit"]["capability_refs"] if ref["provider"] in current]
            self.assertFalse(completion._delivery_limit_valid(updated, self.f.task, self.f.evidence, self.f.plan, current,
                candidates=self.f.candidates, ledger=self.f.ledger, task_dir=self.f.path))


class BrowserScopeCompletionTests(unittest.TestCase):
    def setUp(self):
        self.isolation = isolated_test_environment()
        self.isolation.__enter__()
        self.addCleanup(self.isolation.__exit__, None, None, None)
        from test_api_first_v2 import ApiFirstV2Tests
        self.f = ApiFirstV2Tests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.many_terms(3)
        snapshot = self.f.no_api()
        snapshot["sources"].append({"provider": "epo_ops", "executable": False, "reason": "optional_credentials_missing"})
        from common import atomic_write_json
        atomic_write_json(self.f.path / "source-capabilities.json", snapshot)
        self.f.regenerate()
        self.caps = completion.capability_map(self.f.task, snapshot)
        self.rows = [row for row in self.f.plan["queries"]["uspto_patent_browser"] if row["right_type"] == "patent"]
        self.assertEqual(len(self.rows), 2)
        self.assertTrue(all(row["search_dimension"] == "text" for row in self.rows))
        self.entry = {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent",
            "kind": "plan_repair", "state": "ready", "reason": "COV-US-PATENT-RECALL:AXIS_MISSING:classification"}

    def resolve(self):
        return completion._resolve_evidence_limits(self.f.task, {"entries": [deepcopy(self.entry)]}, self.f.plan,
            self.caps, self.f.evidence, self.f.candidates, self.f.ledger, task_dir=self.f.path)["entries"][0]

    def failed_attempt(self, row, *, review=True, submission="submitted"):
        from api_first_planning import append_review, triage_digest
        from common import atomic_write_json, load_json, sha256_file
        run = self.f.source(row, status="failed")
        raw_path = self.f.path / run["raw_paths"][0]
        atomic_write_json(raw_path, {"error_code": "BROWSER_SEMANTIC_TIMEOUT", "fixture_only": True,
            "message": "Retained synthetic browser response after attempted submission; no results are asserted."})
        run.update(error_code="BROWSER_SEMANTIC_TIMEOUT", payload_digest=sha256_file(raw_path), submission_state=submission)
        atomic_write_json(self.f.path / "evidence.json", self.f.evidence)
        if review:
            append_review(self.f.path, self.f.task, self.f.plan, self.f.evidence, row, {
                "source_run_id": run["run_id"], "reason": "Read this exact retained synthetic timeout receipt.",
                "reviewer": "offline-agent", "outcome": "blocked", "blocker": "The retained browser response reports a timeout, not an empty result.",
                "evidence_ids": ["EV-" + run["run_id"]],
                "triage_digest": triage_digest(self.f.task, self.f.evidence, self.f.candidates, self.f.ledger, query_id=row["query_id"])})
            self.f.task = load_json(self.f.path / "task.json")
        return run

    def test_reviewed_exhausted_submitted_failures_close_scope_without_zero_result_claim(self):
        from workflow_v24 import browser_submitted_failure_state, action_attempt_state, generate_plan
        for row in self.rows:
            self.failed_attempt(row)
            self.failed_attempt(row)
            self.assertEqual(action_attempt_state(self.f.evidence, "uspto_patent_browser", row)["state"], "submitted")
            recovery = browser_submitted_failure_state(self.f.task, self.f.evidence, "uspto_patent_browser", row)
            self.assertEqual((recovery["reason"], recovery["remaining_attempts"]), ("BROWSER_SUBMITTED_FAILURE_RECOVERY_EXHAUSTED", 0))
        result = self.resolve()
        self.assertEqual(result["reason"], "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED")
        bound = next(item for item in result["route_limit_refs"] if item["provider"] == "uspto_patent_browser")
        self.assertEqual(len(bound["attempts"]), 2)
        self.assertTrue(all(item["recovery_limit"]["failure_count"] == 2 for item in bound["attempts"]))
        self.assertTrue(all(len(item["recovery_limit"]["source_run_refs"]) == 2 for item in bound["attempts"]))
        self.assertEqual(result["official_verification"], "not_verified")
        expanded = generate_plan(self.f.path, expand=True)
        self.assertEqual(len([row for row in expanded["queries"]["uspto_patent_browser"] if row["right_type"] == "patent"]), 2)
        self.assertTrue(all(run["status"] == "failed" for run in self.f.evidence["source_runs"]))

    def test_mixed_success_and_exhausted_failure_close_scope(self):
        self.f.review_empty(self.rows[0])
        self.failed_attempt(self.rows[1])
        self.failed_attempt(self.rows[1])
        result = self.resolve()
        self.assertEqual(result["reason"], "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED")

    def test_audited_unknown_reserves_slot_without_completed_search_or_retry(self):
        from api_first_planning import append_review, triage_digest, dispatch_block
        from common import atomic_write_json, load_json
        from workflow_v24 import generate_plan
        self.f.review_empty(self.rows[0])
        row = self.rows[1]
        run = self.failed_attempt(row, review=False, submission="unknown")
        before = deepcopy(self.f.evidence)
        self.assertEqual(self.resolve()["state"], "ready")
        append_review(self.f.path, self.f.task, self.f.plan, self.f.evidence, row, {
            "source_run_id": run["run_id"], "reason": "Read the original receipt; submission remains unconfirmed.",
            "reviewer": "offline-agent", "outcome": "blocked", "blocker": "Unknown submission must retain its slot without another request.",
            "evidence_ids": ["EV-" + run["run_id"]],
            "triage_digest": triage_digest(self.f.task, self.f.evidence, self.f.candidates, self.f.ledger, query_id=row["query_id"]),
            "submission_review": {"state": "unknown_after_receipt_review", "reasoning": "The retained timeout receipt does not prove upstream acceptance."}})
        self.f.task = load_json(self.f.path / "task.json")
        result = self.resolve()
        self.assertEqual(result["reason"], "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED")
        bound = next(item for item in result["route_limit_refs"] if item["provider"] == "uspto_patent_browser")
        self.assertEqual(bound["reason"], "API_DISCOVERY_BROWSER_SCOPE_RESERVED_FOR_UNKNOWN_SUBMISSION")
        self.assertEqual((bound["known_attempt_slots"], bound["unknown_reserved_slots"]), (1, 1))
        reserved = next(item for item in bound["attempts"] if item.get("submission_reservation"))
        self.assertFalse(reserved["submission_reservation"]["completed_search"])
        self.assertNotIn("recovery_limit", reserved)
        self.assertEqual(dispatch_block(self.f.task, self.f.plan, self.f.evidence, self.f.candidates,
            self.f.ledger, "uspto_patent_browser", row), "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY")
        expanded = generate_plan(self.f.path, expand=True)
        self.assertEqual(len([item for item in expanded["queries"]["uspto_patent_browser"] if item["right_type"] == "patent"]), 2)
        self.assertEqual(self.f.evidence, before)
        atomic_write_json(self.f.path / run["raw_paths"][0], {"tampered": True})
        self.assertEqual(self.resolve()["state"], "ready")

    def test_recoverable_unsubmitted_unknown_unreviewed_or_tampered_failure_is_not_bound(self):
        from common import atomic_write_json
        self.f.review_empty(self.rows[0])
        self.failed_attempt(self.rows[1])
        self.assertEqual(self.resolve()["state"], "ready")
        run = self.failed_attempt(self.rows[1], review=False)
        self.assertEqual(self.resolve()["state"], "ready")
        # A current review is necessary, but it cannot make the original
        # unsubmitted/unknown attempt count or repair missing original bytes.
        from api_first_planning import append_review, triage_digest
        from common import load_json
        append_review(self.f.path, self.f.task, self.f.plan, self.f.evidence, self.rows[1], {
            "source_run_id": run["run_id"], "reason": "Read current retained failure.", "reviewer": "offline-agent",
            "outcome": "blocked", "blocker": "The browser response remains a timeout.", "evidence_ids": ["EV-" + run["run_id"]],
            "triage_digest": triage_digest(self.f.task, self.f.evidence, self.f.candidates, self.f.ledger, query_id=self.rows[1]["query_id"])})
        self.f.task = load_json(self.f.path / "task.json")
        prior = next(item for item in self.f.evidence["source_runs"] if item["query_id"] == self.rows[1]["query_id"])
        for state in ("not_submitted", "unknown"):
            with self.subTest(submission=state):
                prior["submission_state"] = state
                atomic_write_json(self.f.path / "evidence.json", self.f.evidence)
                self.assertEqual(self.resolve()["state"], "ready")
        prior["submission_state"] = "submitted"
        atomic_write_json(self.f.path / "evidence.json", self.f.evidence)
        atomic_write_json(self.f.path / prior["raw_paths"][0], {"tampered": True})
        self.assertEqual(self.resolve()["state"], "ready")

    def test_executed_reviewed_browser_scope_bound_resolves_unsearched_axis(self):
        self.assertTrue(any(gap.get("code") == "API_DISCOVERY_BROWSER_SCOPE_LIMIT"
            and gap.get("right_type") == "patent" for gap in self.f.plan["planning_gaps"]))
        for row in self.rows:
            self.f.review_empty(row)
        before = deepcopy((self.f.plan, self.f.evidence, self.f.candidates))
        result = self.resolve()
        self.assertEqual(result["reason"], "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED")
        bound = next(item for item in result["route_limit_refs"] if item["provider"] == "uspto_patent_browser")
        self.assertEqual(bound["reason"], "API_DISCOVERY_BROWSER_SCOPE_LIMIT")
        self.assertEqual(bound["limit"], 2)
        self.assertEqual(len(bound["attempts"]), 2)
        self.assertEqual((self.f.plan, self.f.evidence, self.f.candidates), before)
        self.assertEqual(result["official_verification"], "not_verified")

    def test_plan_reservations_unreviewed_and_unknown_do_not_exhaust_delivery(self):
        self.assertEqual(self.resolve()["state"], "ready")
        self.f.review_empty(self.rows[0])
        self.assertEqual(self.resolve()["state"], "ready")
        run = self.f.source(self.rows[1])
        self.assertEqual(self.resolve()["state"], "ready")
        from api_first_planning import append_review, triage_digest
        from common import atomic_write_json, load_json
        append_review(self.f.path, self.f.task, self.f.plan, self.f.evidence, self.rows[1], {
            "source_run_id": run["run_id"], "reason": "Read the retained bounded empty result", "reviewer": "offline-agent",
            "outcome": "stop_bounded_discovery", "evidence_ids": ["EV-" + run["run_id"]],
            "triage_digest": triage_digest(self.f.task, self.f.evidence, self.f.candidates, self.f.ledger, query_id=self.rows[1]["query_id"])})
        self.f.task = load_json(self.f.path / "task.json")
        run["submission_state"] = "unknown"
        atomic_write_json(self.f.path / "evidence.json", self.f.evidence)
        self.assertEqual(self.resolve()["state"], "ready")

    def test_renamed_or_tampered_queries_cannot_reuse_limit_proof(self):
        for row in self.rows:
            self.f.review_empty(row)
        self.rows[1]["query_id"] += "-renamed"
        self.assertEqual(self.resolve()["state"], "ready")
        self.rows[1]["query_id"] = self.rows[1]["query_id"].removesuffix("-renamed")
        self.rows[1]["q"] = "different words"
        self.assertEqual(self.resolve()["state"], "ready")

    def test_local_language_binds_real_query_and_missing_translation_is_specific_work(self):
        view = {"entries": [{**self.entry, "reason": "COV-US-PATENT-RECALL:LOCAL_LANGUAGE_MISSING"}]}
        def refine():
            result = completion.refine_work_view(self.f.task, view, self.f.plan, self.caps,
                evidence=self.f.evidence, candidates=self.f.candidates, ledger=self.f.ledger, task_dir=self.f.path)
            return next(item for item in result["entries"] if item.get("planning_gap", "").endswith(":LOCAL_LANGUAGE_MISSING"))
        result = refine()
        self.assertEqual(result["reason"], "LOCAL_LANGUAGE_BOUND_TO_PLANNED_QUERY")
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(len(result["query_refs"]), 2)
        self.assertEqual(result["official_verification"], "not_verified")
        for row in self.rows:
            row["search_language"] = "ja"
        result = refine()
        self.assertEqual(result["reason"], "LANGUAGE_TERM_REPAIR_REQUIRED")
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["required_language"], "en")
        self.assertTrue(result["source_terms"])

    def test_unmerged_source_card_does_not_turn_english_query_into_missing_translation(self):
        from api_first_planning import dispatch_block, next_work_entries
        from common import atomic_write_json, sha256_file
        row = self.rows[0]
        run = self.f.source(row, status="success")
        card = {"title": "Offline unmerged English browser card", "publication_number": "US1234567A"}
        atomic_write_json(self.f.path / run["raw_paths"][0], {"organic": [card], "fixture_only": True})
        run["payload_digest"] = sha256_file(self.f.path / run["raw_paths"][0])
        self.f.evidence["collections"]["patents"][-1]["payload"]["candidates"] = [{**card, "source_record_sha256": sha256_json(card)}]
        atomic_write_json(self.f.path / "evidence.json", self.f.evidence)
        self.assertEqual(dispatch_block(self.f.task, self.f.plan, self.f.evidence, self.f.candidates,
            self.f.ledger, "uspto_patent_browser", row), "API_DISCOVERY_MERGE_REQUIRED")
        linked = completion._planned_language_queries(self.f.task,
            {**self.entry, "reason": "COV-US-PATENT-RECALL:LOCAL_LANGUAGE_MISSING"}, self.f.plan,
            self.f.evidence, self.f.candidates, self.f.ledger)
        self.assertIn(row["query_id"], {item["query_id"] for item in linked})
        work = next_work_entries(self.f.task, self.f.plan, self.f.evidence, self.f.candidates,
            self.f.ledger, task_dir=self.f.path, source_capabilities=self.caps)
        self.assertTrue(any(item.get("query_id") == row["query_id"] and item["reason"] == "API_DISCOVERY_MERGE_REQUIRED"
            and item["state"] == "awaiting_review" for item in work))

    def test_empty_qualified_route_set_needs_frozen_policy_term_and_actual_snapshot(self):
        from api_first_planning import next_work_entries
        self.f.task["query_terms"].append({"kind": "product", "value": "strap", "language": "en", "derived_from": "product.title"})
        self.f.regenerate()
        work = next_work_entries(self.f.task, self.f.plan, self.f.evidence, self.f.candidates, self.f.ledger,
            task_dir=self.f.path, source_capabilities=self.caps)
        entry = next(item for item in work if item.get("right_type") == "copyright" and item["reason"] == "API_DISCOVERY_ROUTE_UNAVAILABLE")
        self.assertEqual(entry["delivery_limit"]["source_run_refs"], [])
        self.assertEqual(entry["delivery_limit"]["capability_refs"], [])
        def valid(item, caps=None):
            return completion._delivery_limit_valid(item, self.f.task, self.f.evidence, self.f.plan,
                self.caps if caps is None else caps, candidates=self.f.candidates, ledger=self.f.ledger, task_dir=self.f.path)
        self.assertFalse(valid(entry))
        refined = completion._resolve_evidence_limits(self.f.task, {"entries": [entry]}, self.f.plan, self.caps,
            self.f.evidence, self.f.candidates, self.f.ledger, task_dir=self.f.path)["entries"][0]
        self.assertEqual(refined["delivery_limit"]["route_absence"]["qualified_providers"], [])
        self.assertTrue(valid(refined))
        self.assertFalse(valid(refined, {}))
        forged = deepcopy(refined)
        forged["delivery_limit"]["route_absence"]["source_capabilities_sha256"] = "forged"
        self.assertFalse(valid(forged))
        self.f.plan["planning_gaps"] = [{**gap, "term_id": "nonexistent"} if sha256_json(gap) == refined["delivery_limit"]["planning_gap_sha256"] else gap
            for gap in self.f.plan["planning_gaps"]]
        self.assertFalse(valid(refined))


if __name__ == "__main__":
    unittest.main()
