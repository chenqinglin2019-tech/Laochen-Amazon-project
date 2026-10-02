"""05B minimum action, real request class, one-run binding and result review."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from common import atomic_write_json, load_json, sha256_json
from candidate_followup import (REVISION, action_errors, dispatch_error, events,
                                record_binding, record_review, request_class)
from discovery_budget import purpose_id
import test_triage_scope as base


class CandidateFollowupTests(unittest.TestCase):
    def setUp(self):
        fixture = base.TriageScopeTests()
        fixture.setUp()
        self.f = fixture
        self.task, self.candidate = fixture.task, fixture.candidate
        self.evidence, self.candidates, self.ledger = fixture.evidence, fixture.candidates, fixture.ledger
        self.task["triage_followup_revision"] = REVISION
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.plan = {"queries": {}}
        self.save()

    def save(self):
        for name, value in (("task", self.task), ("normalized-candidates", self.candidates),
                            ("evidence", self.evidence), ("materiality-annotations", self.ledger),
                            ("search-plan", self.plan)):
            atomic_write_json(self.path / (name + ".json"), value)

    def basis(self, *, refs=None):
        return {"missing_fact": "Whether the retained closure covers the fabric strap",
            "decision_effect": "Without the drawing, neither inclusion nor exclusion is supported",
            "evidence_needed": "The exact retained closure drawing",
            "existing_material_review": "E1 contains text but no readable drawing",
            "existing_evidence_refs": refs if refs is not None else ["E1"],
            "obligation_ids": ["OBL-STRAP-COMPARISON"],
            "completion_condition": "Compare the exact drawing to the scoped strap",
            "new_value": "This action supplies the missing drawing without repeating E1"}

    def exact(self, *, kind="record_number", value="US11111111B2"):
        return {"action_id": "LOOKUP-1", "kind": "source_lookup", "purpose": "read exact record",
            "provider": "uspto_patent_browser", "operation": "candidate_verification",
            "params": {"q": value, kind: value, "candidate_id": "C1"}, "max_attempts": 1,
            "required_facts": ["protection_content"], "reading_scope": {"level": "protection_content"},
            "target_locator": {"kind": kind, "value": value, "evidence_refs": ["E1"],
                "unique_reason": "E1 identifies exactly this source record"},
            "followup_basis": self.basis()}

    def annotate(self, actions):
        row = self.f.annotation("needs_info", missing_information=["Exact closure drawing"], next_actions=actions)
        self.ledger["annotations"].append(row)
        self.save()
        return row

    def test_actual_request_class_and_exact_source_evidence(self):
        self.assertEqual(request_class("uspto_patent_browser", "candidate_verification",
                         self.exact()["params"]), "targeted")
        broad = self.exact()
        broad["params"]["q"] = "common strap Applicant"
        self.assertEqual(request_class(broad["provider"], broad["operation"], broad["params"]), "mixed")
        self.assertIn("FOLLOWUP_DISCOVERY_ROUTE_REQUIRED", action_errors(broad, known_evidence={"E1"}))
        with self.assertRaisesRegex(ValueError, "FOLLOWUP_DISCOVERY_ROUTE_REQUIRED"):
            self.f.annotation("needs_info", missing_information=["Drawing"], next_actions=[broad])
        partial = self.exact(kind="source_record_id", value="SOURCE-ROW-17")
        self.assertEqual(action_errors(partial, known_evidence={"E1"}), [])
        unread = deepcopy(partial)
        unread["target_locator"]["evidence_refs"] = ["UNREAD"]
        with self.assertRaisesRegex(ValueError, "FOLLOWUP_LOCATOR_EVIDENCE_UNKNOWN"):
            self.f.annotation("needs_info", missing_information=["Drawing"], next_actions=[unread])

    def test_local_read_and_user_dependency_do_not_create_source_run(self):
        local = {"action_id": "LOCAL-1", "kind": "agent_read", "purpose": "read retained figure",
            "max_attempts": 1, "required_facts": ["representative_figures"],
            "reading_scope": {"level": "representative_figures", "page_numbers": [1]},
            "evidence_refs": ["E1"], "followup_basis": self.basis()}
        annotation = self.annotate([local])
        review = record_review(self.path, {"candidate_id": "C1", "scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent", "annotation_id": annotation["annotation_id"],
            "action_id": "LOCAL-1",
            "outcome": "waiting", "result_evidence_refs": ["E1"],
            "dependency": "Retained figure still unreadable", "resume_condition": "Readable local copy arrives",
            "reason": "The retained page is not legible", "reviewer": "offline-agent"})
        self.assertEqual(review["outcome"], "waiting")
        self.assertEqual(load_json(self.path / "evidence.json").get("source_runs", []), [])
        from workflow_v24 import derive_work_view
        view = derive_work_view(load_json(self.path / "task.json"), self.evidence,
            self.candidates, self.plan, self.ledger, coverage=[{
                "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent",
                "obligations": [], "queries": [], "gaps": []}])
        self.assertTrue(any(item.get("reason") == "FOLLOWUP_WAITING" and
            item.get("state") == "awaiting_user" for item in view["entries"]))
        user = {"action_id": "USER-1", "kind": "user_information", "purpose": "ask owner licence",
            "question": "Do you have the licence?", "user_exclusive_reason": "Only the user holds it",
            "followup_basis": self.basis()}
        self.assertEqual(action_errors(user, known_evidence={"E1"}), [])

    def test_professional_review_can_wait_on_external_opinion_without_fake_limit(self):
        professional = {"action_id": "PRO-1", "kind": "professional_review",
            "purpose": "Obtain an outside line-scope interpretation",
            "question": "Which contours are solid claimed design lines across the seven views?",
            "followup_basis": self.basis(refs=["E1"])}
        self.assertEqual(action_errors(professional, known_evidence={"E1"}), [])
        annotation = self.annotate([professional])
        request = {"candidate_id": "C1", "scenario_id": "product_entry", "jurisdiction": "US",
            "right_type": "patent", "annotation_id": annotation["annotation_id"],
            "action_id": "PRO-1", "outcome": "waiting", "result_evidence_refs": ["E1"],
            "dependency": "Qualified external line-scope opinion has not been obtained; no opinion is asserted",
            "resume_condition": "Resume when a line-legible official original or documented qualified opinion is registered and read",
            "reason": "The retained grant raster and all views were read, but line-type scope remains indeterminate",
            "reviewer": "offline-agent"}
        review = record_review(self.path, request)
        self.assertEqual(review["outcome"], "waiting")
        self.assertIsNone(review["run_id"])
        self.assertEqual(review["result_evidence_refs"], ["E1"])
        from workflow_v24 import derive_work_view
        view = derive_work_view(load_json(self.path / "task.json"), self.evidence,
            self.candidates, self.plan, self.ledger, coverage=[{
                "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent",
                "obligations": [], "queries": [], "gaps": []}])
        entry = next(item for item in view["entries"] if item.get("action_id") == "PRO-1")
        self.assertEqual(entry["kind"], "agent_investigation")
        self.assertEqual(entry["state"], "awaiting_access")
        self.assertEqual(entry["reason"], "FOLLOWUP_WAITING")
        from advance_work import actionable_packet
        self.assertIn(entry, actionable_packet(view)["waiting"])
        from necessary_completion import _delivery_limit_valid
        task = load_json(self.path / "task.json")
        def valid(item=entry, evidence=None, ledger=None):
            return _delivery_limit_valid(item, task, evidence or self.evidence, self.plan, {},
                candidates=self.candidates, ledger=ledger or self.ledger)
        self.assertTrue(valid())
        changed = deepcopy(self.evidence)
        changed["collections"][next(iter(changed["collections"]))][0]["tampered"] = True
        self.assertFalse(valid(evidence=changed))
        bad = deepcopy(entry)
        bad["delivery_limit"]["event_id"] = "other-event"
        self.assertFalse(valid(bad))
        bad = deepcopy(entry)
        bad["dependency"] = "different dependency"
        self.assertFalse(valid(bad))
        changed = deepcopy(self.ledger)
        changed["annotations"][0]["next_actions"][0]["question"] = "changed action"
        self.assertFalse(valid(ledger=changed))


    def test_professional_review_cannot_smuggle_source_request_or_unread_basis(self):
        invalid = {"action_id": "PRO-1", "kind": "professional_review",
            "question": "Which line is claimed?", "provider": "fake-provider",
            "followup_basis": self.basis(refs=["E1"])}
        self.assertIn("FOLLOWUP_PROFESSIONAL_MUST_NOT_BE_SOURCE_LOOKUP",
                      action_errors(invalid, known_evidence={"E1"}))
        invalid["provider"] = None
        invalid["followup_basis"] = self.basis(refs=["UNKNOWN"])
        self.assertIn("FOLLOWUP_EXISTING_EVIDENCE_UNKNOWN",
                      action_errors(invalid, known_evidence={"E1"}))

    def test_malformed_existing_refs_are_rejected_without_crashing(self):
        local = {"kind": "agent_read", "evidence_refs": ["E1"],
            "followup_basis": self.basis(refs=[{"bad": "E1"}])}
        self.assertIn("FOLLOWUP_MINIMUM_BASIS_REQUIRED",
                      action_errors(local, known_evidence={"E1"}))
        self.assertIn("FOLLOWUP_LOCAL_MATERIAL_REQUIRED",
                      action_errors(local, known_evidence={"E1"}))

    def test_sufficient_result_requires_new_decision_with_the_read_evidence(self):
        local = {"action_id": "LOCAL-1", "kind": "agent_read", "purpose": "read retained figure",
            "max_attempts": 1, "required_facts": ["representative_figures"],
            "reading_scope": {"level": "representative_figures", "page_numbers": [1]},
            "evidence_refs": ["E1"], "followup_basis": self.basis()}
        old = self.annotate([local])
        request = {"candidate_id": "C1", "scenario_id": "product_entry", "jurisdiction": "US",
            "right_type": "patent", "annotation_id": old["annotation_id"], "action_id": "LOCAL-1",
            "outcome": "sufficient", "result_evidence_refs": ["E1"],
            "reason": "The retained drawing now supports a concrete association", "reviewer": "offline-agent"}
        with self.assertRaisesRegex(ValueError, "FOLLOWUP_UPDATED_DECISION_REQUIRED"):
            record_review(self.path, request)
        selected = self.f.annotation("selected")
        self.ledger["annotations"].append(selected)
        self.save()
        result = record_review(self.path, request)
        self.assertEqual(result["outcome"], "sufficient")
        self.assertEqual(result["annotation_id"], old["annotation_id"])
        self.assertEqual(len(load_json(self.path / "evidence.json").get("source_runs", [])), 0)

    def test_unresolved_local_read_can_continue_only_with_new_value_and_boundary(self):
        local = {"action_id": "LOCAL-1", "kind": "agent_read", "purpose": "read retained figure",
            "max_attempts": 1, "required_facts": ["representative_figures"],
            "reading_scope": {"level": "representative_figures", "page_numbers": [1]},
            "evidence_refs": ["E1"], "followup_basis": self.basis()}
        old = self.annotate([local])
        request = {"candidate_id": "C1", "scenario_id": "product_entry", "jurisdiction": "US",
            "right_type": "patent", "annotation_id": old["annotation_id"], "action_id": "LOCAL-1",
            "outcome": "continue", "result_evidence_refs": ["E1"],
            "unresolved_fact": "The closure's protected contour is still unreadable",
            "next_value": "An official drawing could show that exact contour",
            "boundary_remaining": "One permitted exact-record route remains",
            "next_action_id": "LOOKUP-2", "reason": "Current local copy insufficient",
            "reviewer": "offline-agent"}
        self.assertEqual(record_review(self.path, request)["outcome"], "continue")
        from workflow_v24 import derive_work_view
        view = derive_work_view(load_json(self.path / "task.json"), self.evidence,
            self.candidates, self.plan, self.ledger, coverage=[{
                "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent",
                "obligations": [], "queries": [], "gaps": []}])
        self.assertTrue(any(item.get("reason") == "FOLLOWUP_NEXT_DECISION_REQUIRED"
                            for item in view["entries"]))

    def discovery_action(self, mode="mixed"):
        action = {"action_id": "DISC-1", "kind": "discovery_binding", "purpose": "find related unknown member",
            "query_id": "Q-DISC-1", "request_mode": mode,
            "request_scope_reason": "The real request searches beyond the known record",
            "verification_obligation_ids": ["OBL-EXACT-STATUS"] if mode == "mixed" else [],
            "followup_basis": self.basis()}
        if mode == "mixed":
            action["target_locator"] = {"kind": "record_number", "value": "US11111111B2",
                "evidence_refs": ["E1"], "unique_reason": "E1 identifies the exact record"}
        return action

    def discovery_row(self):
        basis = {"scenario_id": "product_entry", "clue_source": "candidate:C1:family",
                 "problem_id": None, "problem_reason": None, "different_from_purpose_id": None}
        return {"query_id": "Q-DISC-1", "operation": "search", "jurisdiction": "US",
            "q": "US11111111B2 related family members",
            "right_type": "patent", "action_purpose": "discovery", "search_dimension": "family",
            "discovery_intent_id": purpose_id("US", "patent", "family",
                {"derived_from": basis["clue_source"]}, "product_entry"),
            "refinement_round": 0, "discovery_role": "primary",
            "discovery_scope": {"purpose_basis": basis, "mode": "bounded", "max_pages": 1,
                "max_candidates": 25, "review_all_returned": True}}

    def test_mixed_request_binds_one_discovery_row_and_checks_existing_budget(self):
        self.task["discovery_budget_revision"] = "discovery-purpose-budget-v1"
        decision = self.annotate([self.discovery_action()])
        row = self.discovery_row()
        self.plan["queries"] = {"epo_ops": [row]}
        self.save()
        request = {"candidate_id": "C1", "scenario_id": "product_entry", "jurisdiction": "US",
                   "right_type": "patent", "action_id": "DISC-1", "query_id": row["query_id"],
                   "reviewer": "offline-agent", "reason": "One inseparable request serves discovery and exact status"}
        bound = record_binding(self.path, request)
        self.assertEqual(bound["request_mode"], "mixed")
        self.assertEqual(bound["verification_obligation_ids"], ["OBL-EXACT-STATUS"])
        self.assertEqual(record_binding(self.path, request)["event_id"], bound["event_id"])
        self.assertEqual(len(events(load_json(self.path / "task.json"))), 1)
        self.assertIsNone(dispatch_error(load_json(self.path / "task.json"), "epo_ops", row,
                                         self.candidates, self.ledger, self.evidence))
        self.evidence["source_runs"] = [{"run_id": f"RUN-{i}", "provider": "epo_ops",
            "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
            "status": "success", "submission_state": "submitted",
            "metadata": {"search_coverage": {"pages_retrieved": 1}}} for i in range(8)]
        self.task.pop("candidate_followup_events", None)
        self.save()
        with self.assertRaisesRegex(ValueError, "FOLLOWUP_BIND_BEFORE_EXECUTION_REQUIRED"):
            record_binding(self.path, request)
        from discovery_budget import dispatch_block
        self.assertEqual(dispatch_block(self.task, self.plan, self.evidence, "epo_ops", row),
                         "DISCOVERY_VERSION_PAGE_LIMIT")
        self.assertEqual(len(self.evidence["source_runs"]), 8)  # No quota refund or duplicate run.

    def test_mixed_result_review_reuses_the_one_real_run(self):
        annotation = self.annotate([self.discovery_action()])
        row = self.discovery_row()
        self.plan["queries"] = {"epo_ops": [row]}
        self.save()
        record_binding(self.path, {"candidate_id": "C1", "scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent", "action_id": "DISC-1",
            "query_id": row["query_id"], "reviewer": "offline-agent",
            "reason": "One request has both actual purposes"})
        self.task = load_json(self.path / "task.json")
        self.evidence["source_runs"] = [{"run_id": "RUN-MIXED", "provider": "epo_ops",
            "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
            "status": "no_result", "submission_state": "submitted"}]
        self.save()
        review = record_review(self.path, {"candidate_id": "C1", "scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent", "annotation_id": annotation["annotation_id"],
            "action_id": "DISC-1", "run_id": "RUN-MIXED", "outcome": "waiting",
            "result_evidence_refs": [], "dependency": "Source result reconciliation",
            "resume_condition": "Review a retained matching record", "reviewer": "offline-agent",
            "reason": "Zero search results do not exclude the retained candidate"})
        self.assertEqual(review["run_id"], "RUN-MIXED")
        self.assertEqual(len(load_json(self.path / "evidence.json")["source_runs"]), 1)
        self.assertEqual(load_json(self.path / "materiality-annotations.json")["annotations"][-1]["decision"],
                         "needs_info")

    def test_hard_limit_records_impact_but_keeps_needs_info(self):
        annotation = self.annotate([self.exact()])
        row = {"query_id": "Q-EXACT", "operation": "candidate_verification",
               "jurisdiction": "US", "right_type": "patent", "triage_action_id": "LOOKUP-1",
               "triage_decision_id": annotation["annotation_id"]}
        self.plan["queries"] = {"uspto_patent_browser": [row]}
        self.evidence["source_runs"] = [{"run_id": "RUN-LIMIT", "provider": "uspto_patent_browser",
            "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
            "status": "access_limited", "submission_state": "submitted",
            "error_code": "FREE_QUOTA_EXHAUSTED"}]
        self.save()
        result = record_review(self.path, {"candidate_id": "C1", "scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent", "annotation_id": annotation["annotation_id"],
            "action_id": "LOOKUP-1", "query_id": row["query_id"], "run_id": "RUN-LIMIT",
            "outcome": "limited", "result_evidence_refs": [],
            "limit_evidence": "FREE_QUOTA_EXHAUSTED", "no_recovery_pending": True,
            "impact": "The exact drawing remains unavailable",
            "resume_condition": "A newly authorized route becomes available",
            "reason": "The accepted source quota is exhausted and no recovery is pending",
            "reviewer": "offline-agent"})
        self.assertEqual(result["outcome"], "limited")
        self.assertEqual(self.evidence["source_runs"][0]["status"], "access_limited")
        self.assertEqual(load_json(self.path / "materiality-annotations.json")["annotations"][-1]["decision"],
                         "needs_info")

    def test_new_selection_does_not_hide_unreviewed_source_result(self):
        old = self.annotate([self.exact()])
        row = {"query_id": "Q-EXACT", "operation": "candidate_verification",
            "jurisdiction": "US", "right_type": "patent", "triage_action_id": "LOOKUP-1",
            "triage_decision_id": old["annotation_id"]}
        self.plan["queries"] = {"uspto_patent_browser": [row]}
        self.evidence["source_runs"] = [{"run_id": "RUN-OK", "provider": "uspto_patent_browser",
            "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
            "status": "success", "submission_state": "submitted", "evidence_ids": ["E2"]}]
        self.evidence["collections"]["public_sources"] = [{"evidence_id": "E2", "source_run_id": "RUN-OK",
            "payload": {"drawing": "synthetic exact contour"}}]
        selected = self.f.annotation("selected", evidence_refs=["E1", "E2"])
        self.ledger["annotations"].append(selected)
        self.save()
        from workflow_v24 import derive_work_view
        view = derive_work_view(self.task, self.evidence, self.candidates,
                                self.plan, self.ledger, coverage=[])
        self.assertTrue(any(item.get("reason") == "FOLLOWUP_RESULT_REVIEW_REQUIRED"
            and item.get("source_run_id") == "RUN-OK" for item in view["entries"]))
        record_review(self.path, {"candidate_id": "C1", "scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent", "annotation_id": old["annotation_id"],
            "action_id": "LOOKUP-1", "query_id": row["query_id"], "run_id": "RUN-OK",
            "outcome": "sufficient", "result_evidence_refs": ["E2"],
            "reason": "The retained drawing supports the new selection", "reviewer": "offline-agent"})
        view = derive_work_view(load_json(self.path / "task.json"), self.evidence,
                                self.candidates, self.plan, self.ledger, coverage=[])
        self.assertFalse(any(item.get("reason") == "FOLLOWUP_RESULT_REVIEW_REQUIRED"
            and item.get("source_run_id") == "RUN-OK" for item in view["entries"]))

    def test_failed_read_is_reviewed_without_excluding_candidate(self):
        annotation = self.annotate([self.exact()])
        row = {"query_id": "Q-EXACT", "operation": "candidate_verification",
               "jurisdiction": "US", "right_type": "patent", "triage_action_id": "LOOKUP-1",
               "triage_decision_id": annotation["annotation_id"]}
        self.plan["queries"] = {"uspto_patent_browser": [row]}
        self.evidence["source_runs"] = [{"run_id": "RUN-FAIL", "provider": "uspto_patent_browser",
            "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
            "status": "failed", "submission_state": "submitted"}]
        self.save()
        with self.assertRaisesRegex(ValueError, "FOLLOWUP_LIMIT_EVIDENCE_REQUIRED"):
            record_review(self.path, {"candidate_id": "C1", "scenario_id": "product_entry",
                "jurisdiction": "US", "right_type": "patent", "annotation_id": annotation["annotation_id"],
                "action_id": "LOOKUP-1",
                "query_id": row["query_id"], "run_id": "RUN-FAIL", "outcome": "limited",
                "result_evidence_refs": [], "limit_evidence": "Temporary timeout",
                "impact": "No drawing", "resume_condition": "Retry after timeout",
                "reason": "Temporary failure", "reviewer": "offline-agent"})
        review = record_review(self.path, {"candidate_id": "C1", "scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent", "annotation_id": annotation["annotation_id"],
            "action_id": "LOOKUP-1",
            "query_id": row["query_id"], "run_id": "RUN-FAIL", "outcome": "waiting",
            "result_evidence_refs": [], "dependency": "Source access recovery",
            "resume_condition": "Source accessible", "reason": "Failed request needs recovery review",
            "reviewer": "offline-agent"})
        self.assertEqual(review["outcome"], "waiting")
        self.assertEqual(load_json(self.path / "materiality-annotations.json")["annotations"][-1]["decision"],
                         "needs_info")


if __name__ == "__main__":
    unittest.main()
