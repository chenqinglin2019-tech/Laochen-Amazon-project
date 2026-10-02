"""05C receipt batches, selected handoff, reopening and module completion."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from common import atomic_write_json, load_json
import decision_workflow as workflow
from candidate_triage_stage import (REVISION, events, light_triage_pending, project,
    prioritize_work, record_duplicate_reference, record_reopen, record_reopen_review,
    record_selected_handoff, record_batch_review)
from candidate_followup import record_review
import test_triage_scope as base


class TriageStageTests(unittest.TestCase):
    def setUp(self):
        fixture = base.TriageScopeTests()
        fixture.setUp()
        self.f = fixture
        self.task, self.candidate = fixture.task, fixture.candidate
        self.evidence, self.candidates, self.ledger = fixture.evidence, fixture.candidates, fixture.ledger
        self.task.update(triage_followup_revision="candidate-followup-v1",
                         triage_stage_revision=REVISION)
        self.candidate["sources"] = [{"evidence_id": "E1", "source_anchor": "import-row-1"}]
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.plan = {"queries": {}}
        self.save()

    def save(self):
        for name, value in (("task", self.task), ("evidence", self.evidence),
                            ("normalized-candidates", self.candidates),
                            ("materiality-annotations", self.ledger), ("search-plan", self.plan)):
            atomic_write_json(self.path / (name + ".json"), value)

    def selected(self):
        row = self.f.annotation("selected")
        self.ledger["annotations"].append(row)
        self.save()
        return row

    def scope(self):
        return {"candidate_id": "C1", "scenario_id": "product_entry",
                "jurisdiction": "US", "right_type": "patent"}

    def handoff(self, annotation):
        return record_selected_handoff(self.path, {**self.scope(),
            "annotation_id": annotation["annotation_id"], "evidence_refs": ["E1"],
            "reading_scope": {"level": "result_record", "sections": ["claims"]},
            "verification_gaps": ["current_status"], "reviewer": "agent",
            "reason": "Current association goes to specialist with status still open"})

    def test_selected_handoff_is_versioned_and_module_completion_is_separate(self):
        row = self.selected()
        before = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(before["status"], "in_progress")
        self.assertEqual(len(before["selected_pending_handoff"]), 1)
        event = self.handoff(row)
        self.task = load_json(self.path / "task.json")
        self.assertEqual(event["candidate_version_sha256"], row["candidate_content_sha256"])
        self.assertEqual(event["product_version_sha256"], row["product_identity_sha256"])
        self.assertEqual(self.handoff(row)["event_id"], event["event_id"])
        after = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(after["status"], "normal_complete")
        self.assertEqual(after["completion_meaning"],
                         "module_05_only; downstream_verification_and_publication_separate")
        self.assertEqual(after["batches"][0]["candidate_ids"], ["C1"])
        self.assertTrue(after["batches"][0]["batch_processed"])

    def test_unprocessed_second_receipt_does_not_block_first_selected_handoff(self):
        row = self.selected()
        self.handoff(row)
        self.task = load_json(self.path / "task.json")
        record_batch_review(self.path, {"batch_id": "import:E1", "reviewer": "agent",
            "reason": "First received batch has been triaged"})
        self.task = load_json(self.path / "task.json")
        self.evidence["source_runs"] = [{"run_id": "RUN-80", "evidence_type": "patent",
            "status": "success", "submission_state": "submitted", "payload_digest": "a" * 64,
            "result_processing": {"returned_count": 80, "rows": []}}]
        self.save()
        view = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(view["status"], "in_progress")
        self.assertEqual(view["selected_pending_handoff"], [])
        self.assertEqual(view["batches"][0]["batch_id"], "RUN-80")
        self.assertFalse(view["batches"][0]["batch_processed"])
        self.assertTrue(any(batch["batch_processed"] for batch in view["batches"][1:]))
        self.assertTrue(view["batch_review_history"][0]["batch_snapshot"]["batch_processed"])

    def test_eighty_acquired_candidates_keep_seventy_nine_light_triage_obligations(self):
        row = self.selected()
        self.handoff(row)
        self.task = load_json(self.path / "task.json")
        for number in range(2, 81):
            candidate = deepcopy(self.candidate)
            candidate["candidate_id"] = f"C{number}"
            candidate["normalization_key"] = f"synthetic:{number}"
            self.candidates["patents"].append(candidate)
            self.task["product_scope"]["candidate_links"].append({"candidate_id": candidate["candidate_id"],
                "object_ids": ["strap"], "source_refs": ["E1"], "reason": "Same acquired batch"})
        self.save()
        view = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(view["status"], "in_progress")
        self.assertEqual(len(view["batches"][0]["candidate_ids"]), 80)
        self.assertEqual(len(view["batches"][0]["triage_pending_candidate_ids"]), 79)
        self.assertEqual(view["selected_pending_handoff"], [])

    def test_content_change_reopens_only_affected_decision_even_if_conclusion_same(self):
        old = self.selected()
        self.handoff(old)
        self.task = load_json(self.path / "task.json")
        self.candidate["title"] = "Corrected strap protection content"
        self.save()
        request = {"change_kind": "candidate_content", "change_summary": "Corrected retained title and content",
            "change_evidence_refs": ["E1"], "dependency_ids": ["OBL-C1-PROTECTION"],
            "reviewer": "agent", "reason": "Prior selected association may rely on changed content",
            "affected": [{**self.scope(), "annotation_id": old["annotation_id"],
                "impact": "direct", "impact_reason": "C1's protected content changed"}]}
        reopened = record_reopen(self.path, request)
        self.task = load_json(self.path / "task.json")
        fresh = self.f.annotation("selected")
        self.ledger["annotations"].append(fresh)
        self.save()
        stale = workflow.effective_decision(self.task, self.ledger, "patents", self.candidate,
                                            "product_entry", "US", evidence=self.evidence)
        self.assertIn("TRIAGE_CHANGE_REVIEW_REQUIRED", stale["reopen_reasons"])
        with self.assertRaisesRegex(ValueError, "SAME_CONCLUSION_BASIS_REQUIRED"):
            record_reopen_review(self.path, {"reopen_event_id": reopened["event_id"],
                "old_annotation_id": old["annotation_id"], "new_annotation_id": fresh["annotation_id"],
                "reviewed_evidence_refs": ["E1"], "basis": "Re-read corrected content", "reviewer": "agent"})
        record_reopen_review(self.path, {"reopen_event_id": reopened["event_id"],
            "old_annotation_id": old["annotation_id"], "new_annotation_id": fresh["annotation_id"],
            "reviewed_evidence_refs": ["E1"], "basis": "Re-read corrected content", "reviewer": "agent",
            "same_conclusion_basis": "The exact strap association still holds in the corrected source"})
        self.task = load_json(self.path / "task.json")
        current = workflow.effective_decision(self.task, self.ledger, "patents", self.candidate,
                                              "product_entry", "US", evidence=self.evidence)
        self.assertTrue(current["current"])
        self.assertEqual(current["decision"], "selected")
        stage = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(stage["reopen_pending"], [])
        self.assertEqual(len(stage["selected_pending_handoff"]), 1)
        self.assertEqual(self.ledger["annotations"][0]["annotation_id"], old["annotation_id"])

    def test_split_with_unknown_attribution_stays_pending(self):
        old = self.selected()
        event = record_reopen(self.path, {"change_kind": "split", "change_summary": "Old merged key split",
            "change_evidence_refs": ["E1"], "dependency_ids": ["IDENTITY-C1"],
            "reviewer": "agent", "reason": "Source attribution has to be checked",
            "affected": [{**self.scope(), "annotation_id": old["annotation_id"],
                "impact": "direct", "impact_reason": "Merged source may belong to another object",
                "target_candidate_id": None, "attribution_reason": "Original E1 row cannot yet be assigned"}]})
        self.task = load_json(self.path / "task.json")
        stage = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(stage["reopen_pending"][0]["reason"], "TRIAGE_ATTRIBUTION_REQUIRED")
        with self.assertRaisesRegex(ValueError, "ATTRIBUTION_PENDING"):
            record_reopen_review(self.path, {"reopen_event_id": event["event_id"],
                "old_annotation_id": old["annotation_id"], "new_annotation_id": "D2"})

    def test_identity_alias_for_retired_decision_requires_explicit_impact(self):
        old = self.selected()
        self.candidate["candidate_id"] = "C2"
        self.candidate["normalization_key"] = "split:2"
        self.candidates["identity_aliases"] = [{"event_id": "IDCOR-SPLIT-1", "kind": "split",
            "old_candidate_ids": ["C1"], "current_candidate_ids": ["C2"],
            "evidence_refs": ["E1"]}]
        self.save()
        self.assertNotIn("TRIAGE_UNKNOWN_CANDIDATE", workflow.triage_ledger_errors(
            self.task, self.ledger, self.candidates, evidence=self.evidence))
        stage = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(stage["identity_change_impact_pending"][0]["unreviewed_annotation_ids"],
                         [old["annotation_id"]])
        request = {"change_kind": "split", "change_summary": "Old key split by source row",
            "change_evidence_refs": ["E1"], "dependency_ids": ["IDENTITY-C1"],
            "reviewer": "agent", "reason": "Old selection attribution is unresolved",
            "affected": [{**self.scope(), "annotation_id": old["annotation_id"],
                "impact": "direct", "impact_reason": "Old key retired after split",
                "target_candidate_id": None, "attribution_reason": "Source row needs assignment"}]}
        with self.assertRaisesRegex(ValueError, "IDENTITY_EVENT_REQUIRED"):
            record_reopen(self.path, request)
        request["identity_correction_event_id"] = "IDCOR-SPLIT-1"
        record_reopen(self.path, request)
        self.task = load_json(self.path / "task.json")
        stage = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(stage["identity_change_impact_pending"], [])
        self.assertEqual(stage["reopen_pending"][0]["reason"], "TRIAGE_ATTRIBUTION_REQUIRED")

    def test_source_only_duplicate_preserves_decision_and_count(self):
        old = self.selected()
        self.evidence["collections"]["patents"].append(deepcopy({"evidence_id": "E2",
            "payload": {"publication_number": "US11111111B2", "claims": "strap and hook"}}))
        self.candidate["sources"].append({"evidence_id": "E2", "source_anchor": "same-record-again"})
        self.save()
        before = workflow.effective_decision(self.task, self.ledger, "patents", self.candidate,
                                             "product_entry", "US", evidence=self.evidence)
        self.assertTrue(before["current"])
        record_duplicate_reference(self.path, {**self.scope(), "duplicate_evidence_refs": ["E2"],
            "same_content_basis": "Exact same publication and claims; only a second source wrapper",
            "reviewer": "agent"})
        self.task = load_json(self.path / "task.json")
        self.assertEqual(len(events(self.task)), 1)
        self.assertTrue(workflow.effective_decision(self.task, self.ledger, "patents", self.candidate,
                        "product_entry", "US", evidence=self.evidence)["current"])
        self.assertEqual(self.ledger["annotations"][0]["annotation_id"], old["annotation_id"])

    def test_changed_source_content_cannot_be_mislabeled_duplicate(self):
        self.selected()
        self.evidence["collections"]["patents"].append({"evidence_id": "E2",
            "payload": {"publication_number": "US11111111B2", "claims": "different protection"}})
        self.candidate["sources"].append({"evidence_id": "E2", "source_anchor": "conflicting-row"})
        self.save()
        with self.assertRaisesRegex(ValueError, "CONTENT_CHANGED"):
            record_duplicate_reference(self.path, {**self.scope(), "duplicate_evidence_refs": ["E2"],
                "same_content_basis": "Claimed duplicate", "reviewer": "agent"})

    def test_reopen_requires_material_change_or_new_evidence(self):
        old = self.selected()
        with self.assertRaisesRegex(ValueError, "MATERIAL_CHANGE_REQUIRED"):
            record_reopen(self.path, {"change_kind": "candidate_content", "change_summary": "Only timestamp changed",
                "change_evidence_refs": ["E1"], "dependency_ids": ["C1-CONTENT"],
                "reviewer": "agent", "reason": "Try to reopen without fact change",
                "affected": [{**self.scope(), "annotation_id": old["annotation_id"],
                    "impact": "direct", "impact_reason": "No factual change"}]})

    def test_uncertain_impact_requires_reasonable_widening_basis(self):
        old = self.selected()
        self.candidate["title"] = "Updated source content with uncertain reach"
        self.save()
        request = {"change_kind": "candidate_content", "change_summary": "Shared source changed",
            "change_evidence_refs": ["E1"], "dependency_ids": ["SHARED-CONTENT"],
            "reviewer": "agent", "reason": "Both product directions may rely on this passage",
            "affected": [{**self.scope(), "annotation_id": old["annotation_id"],
                "impact": "widened", "impact_reason": "The changed passage spans the shared strap feature"}]}
        with self.assertRaisesRegex(ValueError, "WIDENING_BASIS_REQUIRED"):
            record_reopen(self.path, request)
        request["affected"][0]["reasonable_scope_reason"] = "Only decisions citing the shared strap feature"
        event = record_reopen(self.path, request)
        self.assertEqual(event["affected"][0]["impact"], "widened")

    def test_stage_history_tampering_is_detected(self):
        row = self.selected()
        self.handoff(row)
        self.task = load_json(self.path / "task.json")
        self.task["candidate_triage_stage_events"][0]["reason"] = "silent rewrite"
        with self.assertRaisesRegex(ValueError, "EVENTS_CHANGED"):
            events(self.task)

    def test_unknown_identity_selection_can_handoff_with_explicit_gap(self):
        self.candidate["jurisdiction"] = "unknown"
        row = self.f.annotation("selected", candidate_relation=self.f.basis(
            gaps=["target_jurisdiction"]))
        self.ledger["annotations"].append(row)
        self.save()
        event = record_selected_handoff(self.path, {"candidate_id": "C1",
            "scenario_id": "product_entry", "jurisdiction": workflow.UNLOCATED,
            "right_type": "patent", "annotation_id": row["annotation_id"],
            "evidence_refs": ["E1"], "reading_scope": {"level": "result_record"},
            "verification_gaps": ["target_jurisdiction", "current_status"],
            "reviewer": "agent", "reason": "Concrete structure association, territory unresolved"})
        self.assertIn("target_jurisdiction", event["verification_gaps"])
        self.task = load_json(self.path / "task.json")
        self.assertEqual(project(self.task, self.evidence, self.candidates,
                         self.ledger, task_dir=self.path)["status"], "normal_complete")

    def test_priority_changes_order_without_dropping_any_work(self):
        view = {"entries": [{"kind": "source_lookup", "state": "ready", "reason": "NECESSARY_ACTION_PENDING"},
            {"kind": "triage", "state": "awaiting_review", "reason": "CANDIDATE_TRIAGE_REQUIRED"},
            {"kind": "agent_investigation", "state": "awaiting_review",
             "reason": "SOURCE_RESULTS_PENDING_PROCESSING"}]}
        self.assertTrue(light_triage_pending(view))
        self.assertEqual(len(view["entries"]), 3)
        self.assertFalse(light_triage_pending({"entries": [view["entries"][0]]}))
        ordered = prioritize_work(view["entries"], {"batches": []})
        self.assertEqual([row["reason"] for row in ordered],
            ["SOURCE_RESULTS_PENDING_PROCESSING", "CANDIDATE_TRIAGE_REQUIRED", "NECESSARY_ACTION_PENDING"])
        self.assertEqual(len(ordered), len(view["entries"]))
        shared = prioritize_work([{"kind": "agent_read", "state": "awaiting_review",
            "reason": "READ", "query_id": "Q-SHARED", "candidate_id": cid, "work_id": cid}
            for cid in ("C1", "C2")], {"batches": []})
        self.assertTrue(all(row["triage_priority"]["basis"] == "shared_dependency" for row in shared))
        from advance_work import source_entries_after_triage_priority
        source, deferred = source_entries_after_triage_priority(self.task, view)
        self.assertTrue(deferred)
        self.assertEqual(source, [])
        legacy, deferred = source_entries_after_triage_priority({}, view)
        self.assertFalse(deferred)
        self.assertEqual(len(legacy), 1)

    def test_needs_info_waiting_is_not_normal_completion(self):
        action = {"action_id": "LOCAL-1", "kind": "agent_read", "purpose": "read retained drawing",
            "max_attempts": 1, "required_facts": ["representative_figures"],
            "reading_scope": {"level": "representative_figures", "page_numbers": [1]},
            "evidence_refs": ["E1"], "followup_basis": {
                "missing_fact": "Exact contour", "decision_effect": "Cannot decide relevance",
                "evidence_needed": "Readable original drawing", "existing_material_review": "E1 is blurred",
                "existing_evidence_refs": ["E1"], "obligation_ids": ["DRAWING-C1"],
                "completion_condition": "Compare exact drawing", "new_value": "Read retained file"}}
        old = self.f.annotation("needs_info", missing_information=["Exact contour"],
                                next_actions=[action])
        self.ledger["annotations"].append(old)
        self.save()
        record_review(self.path, {**self.scope(), "annotation_id": old["annotation_id"],
            "action_id": "LOCAL-1", "outcome": "waiting", "result_evidence_refs": ["E1"],
            "dependency": "Readable original still needed", "resume_condition": "Readable copy arrives",
            "reviewer": "agent", "reason": "Current retained figure is blurred"})
        self.task = load_json(self.path / "task.json")
        view = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(view["status"], "waiting")
        self.assertEqual(view["waiting_count"], 1)

    def test_actual_hard_limit_can_close_stage_as_limited_without_exclusion(self):
        import test_candidate_followup as followup_fixture
        helper = followup_fixture.CandidateFollowupTests()
        helper.f = self.f
        helper.task, helper.candidate = self.task, self.candidate
        helper.evidence, helper.candidates, helper.ledger = self.evidence, self.candidates, self.ledger
        helper.path, helper.plan = self.path, self.plan
        action = helper.exact()
        old = self.f.annotation("needs_info", missing_information=["Exact drawing"],
                                next_actions=[action])
        self.ledger["annotations"].append(old)
        row = {"query_id": "Q-EXACT", "operation": "candidate_verification",
            "jurisdiction": "US", "right_type": "patent", "triage_action_id": "LOOKUP-1",
            "triage_decision_id": old["annotation_id"]}
        self.plan["queries"] = {"uspto_patent_browser": [row]}
        from common import sha256_json
        self.evidence["source_runs"] = [{"run_id": "RUN-LIMIT", "provider": "uspto_patent_browser",
            "query_id": "Q-EXACT", "plan_entry_sha256": sha256_json(row),
            "status": "access_limited", "submission_state": "submitted",
            "error_code": "FREE_QUOTA_EXHAUSTED"}]
        self.save()
        record_review(self.path, {**self.scope(), "annotation_id": old["annotation_id"],
            "action_id": "LOOKUP-1", "query_id": "Q-EXACT", "run_id": "RUN-LIMIT",
            "outcome": "limited", "result_evidence_refs": [], "limit_evidence": "FREE_QUOTA_EXHAUSTED",
            "no_recovery_pending": True, "impact": "Exact drawing unavailable",
            "resume_condition": "An authorized source becomes available",
            "reason": "Current free source exhausted", "reviewer": "agent"})
        self.task = load_json(self.path / "task.json")
        view = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(view["status"], "limited")
        self.assertEqual(view["triage_pending"][0]["decision"], "needs_info")

    def test_inflight_source_prevents_module_complete_but_keeps_batch_progress(self):
        row = self.selected()
        self.handoff(row)
        self.task = load_json(self.path / "task.json")
        view = project(self.task, self.evidence, self.candidates, self.ledger,
            source_work=[{"kind": "source_lookup", "state": "ready", "query_id": "Q-FUTURE"}],
            task_dir=self.path)
        self.assertEqual(view["status"], "in_progress")
        self.assertEqual(view["open_source_query_ids"], ["Q-FUTURE"])
        self.assertTrue(view["batches"][0]["batch_processed"])
        unreviewed = project(self.task, self.evidence, self.candidates, self.ledger,
            source_work=[{"kind": "agent_investigation", "state": "awaiting_review",
                "reason": "FOLLOWUP_RESULT_REVIEW_REQUIRED", "source_run_id": "RUN-OLD"}],
            task_dir=self.path)
        self.assertEqual(unreviewed["status"], "in_progress")
        self.assertEqual(unreviewed["unreviewed_followup_run_ids"], ["RUN-OLD"])
        specialist = project(self.task, self.evidence, self.candidates, self.ledger,
            plan={"queries": {"epo_ops": [{"query_id": "Q-STATUS",
                "action_purpose": "official_verification"}]}},
            source_work=[{"kind": "source_lookup", "state": "ready", "query_id": "Q-STATUS"}],
            task_dir=self.path)
        self.assertEqual(specialist["status"], "normal_complete")

    def test_new_candidate_reopens_stage_without_overwriting_old_batch(self):
        row = self.selected()
        self.handoff(row)
        self.task = load_json(self.path / "task.json")
        before = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(before["status"], "normal_complete")
        frozen = record_batch_review(self.path, {"batch_id": "import:E1", "reviewer": "agent",
            "reason": "Current import batch has been triaged"})
        self.task = load_json(self.path / "task.json")
        self.assertTrue(frozen["batch_snapshot"]["batch_processed"])
        newcomer = deepcopy(self.candidate)
        newcomer["candidate_id"] = "C2"
        newcomer["normalization_key"] = "US22222222B2"
        newcomer["sources"] = [{"evidence_id": "E1", "source_anchor": "new-row"}]
        self.candidates["patents"].append(newcomer)
        self.task["product_scope"]["candidate_links"].append({"candidate_id": "C2",
            "object_ids": ["strap"], "source_refs": ["E1"], "reason": "New source row is related"})
        self.save()
        after = project(self.task, self.evidence, self.candidates, self.ledger, task_dir=self.path)
        self.assertEqual(after["status"], "in_progress")
        self.assertEqual(after["batches"][0]["candidate_ids"], ["C1", "C2"])
        self.assertIn("C2", after["batches"][0]["triage_pending_candidate_ids"])
        self.assertEqual(after["batch_review_history"][0]["batch_snapshot"]["candidate_ids"], ["C1"])


if __name__ == "__main__":
    unittest.main()
