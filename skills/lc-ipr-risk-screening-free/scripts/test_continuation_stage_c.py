"""08C pause, reconciliation, access deduplication, and direct source gate."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json
from continuation_stage_c import (REVISION, access_requests, active_pauses, dispatch_block,
                                  project, record_event)


class ContinuationStageCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.task = {"task_id": "T08C", "continuous_continuation_revision": REVISION,
                     "request": {"url": "original"}, "target_jurisdictions": ["US"],
                     "product": {"title": "Original item"}}
        self.evidence = {"task_id": "T08C", "source_runs": []}
        self.plan = {"task_id": "T08C", "queries": {}}
        self.save()

    def save(self):
        atomic_write_json(self.path / "task.json", self.task)
        atomic_write_json(self.path / "evidence.json", self.evidence)
        atomic_write_json(self.path / "search-plan.json", self.plan)

    def read(self):
        self.evidence = load_json(self.path / "evidence.json")

    def pause(self, scope=None, intent="pause"):
        event = record_event(self.path, {"kind": "pause", "actor": "user", "reasoning": "Explicit instruction",
            "intent": intent, "scope": scope or {"level": "task"}, "reason": "Stop this scope"})
        self.read()
        return event

    def reconcile(self, pause, view=None, **extra):
        view = view or {"entries": [{"work_id": "W1", "kind": "source_lookup", "right_type": "patent",
            "state": "blocked", "underlying_state": "ready"}]}
        request = {"kind": "reconcile", "actor": "reviewer", "reasoning": "Checked original request and receipt",
            "pause_id": pause["event_id"], "original_target_sha256": pause["original_snapshot"]["target_sha256"],
            "remaining_work": ["W1"], "dependency_checks": [],
            "material_review": "Original retained material and processing positions reviewed",
            "evidence_reuse_review": "Object, scope, version, use and dates checked",
            "historical_evidence_reviews": [],
            "retry_and_budget_review": "Historical attempts and unknown slots retained", **extra}
        with patch("workflow_v24.work_view_from_dir", return_value=view):
            result = record_event(self.path, request)
        self.read()
        return result

    def test_task_pause_blocks_all_work_and_requires_explicit_fresh_resume(self):
        pause = self.pause(intent="stop")
        view = {"status": "complete", "entries": [{"work_id": "W1", "kind": "source_lookup",
            "state": "ready", "right_type": "patent", "reason": "NECESSARY_ACTION_PENDING"}]}
        result = project(self.task, view, self.evidence)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["entries"][0]["reason"], "USER_ACTIVE_PAUSE")
        self.assertEqual(dispatch_block(self.task, self.evidence, {"right_type": "patent"}), "USER_ACTIVE_PAUSE")
        self.assertEqual(len(active_pauses(self.evidence)), 1)
        with self.assertRaisesRegex(ValueError, "FRESH_RECONCILIATION"):
            record_event(self.path, {"kind": "resume", "actor": "user", "reasoning": "Continue",
                "pause_id": pause["event_id"], "explicit_resume_intent": "Resume"})
        review = self.reconcile(pause)
        resume = record_event(self.path, {"kind": "resume", "actor": "user", "reasoning": "Resume original task",
            "pause_id": pause["event_id"], "reconciliation_id": review["event_id"],
            "explicit_resume_intent": "Resume this task"})
        self.read()
        self.assertEqual(resume["pause_id"], pause["event_id"])
        self.assertEqual(active_pauses(self.evidence), [])
        self.assertIsNone(dispatch_block(self.task, self.evidence, {"right_type": "patent"}))

    def test_direction_pause_does_not_stop_other_direction_or_clear_on_feedback(self):
        pause = self.pause({"level": "right_type", "right_type": "patent"})
        self.assertEqual(dispatch_block(self.task, self.evidence, {"right_type": "patent"}), "USER_ACTIVE_PAUSE")
        self.assertIsNone(dispatch_block(self.task, self.evidence, {"right_type": "trademark_word"}))
        view = {"entries": [{"work_id": "P", "kind": "source_lookup", "right_type": "patent",
            "state": "ready", "reason": "NECESSARY_ACTION_PENDING"},
            {"work_id": "T", "kind": "source_lookup", "right_type": "trademark_word",
             "state": "ready", "reason": "NECESSARY_ACTION_PENDING"}]}
        result = project(self.task, view, self.evidence)
        self.assertEqual(result["entries"][0]["state"], "blocked")
        self.assertEqual(result["entries"][1]["state"], "ready")
        self.assertEqual(result["active_pauses"][0]["pause_id"], pause["event_id"])

    def test_changed_target_and_stale_receipt_cannot_resume(self):
        pause = self.pause()
        self.task["product"]["title"] = "Different item"
        self.save()
        with self.assertRaisesRegex(ValueError, "TARGET_OR_VERSION_CHANGED"):
            self.reconcile(pause)
        self.task["product"]["title"] = "Original item"
        self.save()
        review = self.reconcile(pause)
        self.evidence["source_runs"].append({"run_id": "R1", "submission_state": "unknown", "status": "failed"})
        self.save()
        with self.assertRaisesRegex(ValueError, "FRESH_RECONCILIATION"):
            record_event(self.path, {"kind": "resume", "actor": "user", "reasoning": "Resume",
                "pause_id": pause["event_id"], "reconciliation_id": review["event_id"],
                "explicit_resume_intent": "Resume task"})

    def test_audited_upstream_product_change_can_be_reconciled(self):
        from common import sha256_json
        pause = self.pause()
        self.task["product"]["title"] = "Reviewed revised item"
        change = {"change_id": "CHG1", "kind": "fact_correction", "version": 2,
            "reason": "Upstream scope review accepted the changed title"}
        change["sha256"] = sha256_json(change)
        self.task["product_change_history"] = [change]
        self.save()
        with self.assertRaisesRegex(ValueError, "TARGET_OR_VERSION_CHANGED"):
            self.reconcile(pause)
        review = self.reconcile(pause, upstream_change_ids=["CHG1"])
        self.assertEqual(review["upstream_change_ids"], ["CHG1"])

    def test_unrelated_direction_plan_progress_does_not_rebind_paused_direction(self):
        pause = self.pause({"level": "right_type", "right_type": "patent"})
        self.plan["queries"] = {"registry": [{"query_id": "OTHER", "right_type": "trademark_word"}]}
        self.save()
        review = self.reconcile(pause)
        self.assertEqual(review["upstream_change_ids"], [])

    def test_retained_file_change_invalidates_reconciliation(self):
        from common import sha256_file, sha256_json
        raw = self.path / "raw" / "record.json"
        raw.parent.mkdir()
        raw.write_text('{"status":"old"}', encoding="utf-8")
        run = {"run_id": "R1", "status": "success", "submission_state": "submitted",
            "finished_at": "2026-01-01T00:00:00Z", "raw_paths": ["raw/record.json"],
            "payload_digest": sha256_file(raw)}
        self.evidence["source_runs"].append(run)
        self.save()
        pause = self.pause()
        historical = [{"source_run_id": "R1", "source_run_sha256": sha256_json(run),
            "object": "Record R1", "scope": "US patent", "version": "v1",
            "purpose": "Read old content", "captured_at": run["finished_at"],
            "assessment_at": "2026-09-25", "fact_dynamics": "stable_content",
            "disposition": "reuse", "basis": "Original content is unchanged"}]
        review = self.reconcile(pause, historical_evidence_reviews=historical)
        self.assertEqual(review["snapshot"]["retained_material"][0]["status"], "valid")
        raw.write_text('{"status":"changed"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "FRESH_RECONCILIATION"):
            record_event(self.path, {"kind": "resume", "actor": "user", "reasoning": "Resume",
                "pause_id": pause["event_id"], "reconciliation_id": review["event_id"],
                "explicit_resume_intent": "Continue"})

    def test_reconciliation_must_account_for_waiting_and_remaining_work(self):
        pause = self.pause()
        view = {"entries": [{"work_id": "W1", "kind": "source_lookup", "state": "blocked",
            "underlying_state": "awaiting_access", "right_type": "patent"}]}
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_INVENTORY_MISMATCH"):
            self.reconcile(pause, view)
        review = self.reconcile(pause, view, dependency_checks=[{"condition": "W1",
            "verified": False, "basis": "Login feedback did not restore query capability"}])
        self.assertEqual(review["dependency_checks"][0]["verified"], False)
        with self.assertRaisesRegex(ValueError, "REMAINING_WORK_MISMATCH"):
            self.reconcile(pause, view, remaining_work=[])

    def test_historical_dynamic_fact_needs_itemized_reuse_basis(self):
        from common import sha256_json
        run = {"run_id": "R1", "submission_state": "submitted", "status": "success",
            "checked_at": "2026-01-01T00:00:00Z", "raw_paths": ["raw/R1.json"]}
        self.evidence["source_runs"].append(run)
        self.save()
        pause = self.pause()
        with self.assertRaisesRegex(ValueError, "HISTORICAL_EVIDENCE_INVENTORY_MISMATCH"):
            self.reconcile(pause)
        review = {"source_run_id": "R1", "source_run_sha256": sha256_json(run),
            "object": "Patent P1", "scope": "US patent status", "version": "P1-v1",
            "purpose": "Current status check", "captured_at": run["checked_at"],
            "assessment_at": "2026-09-25", "fact_dynamics": "dynamic_fact", "disposition": "reuse",
            "basis": "Old status"}
        with self.assertRaisesRegex(ValueError, "EVIDENCE_REUSE_REVIEW_INVALID"):
            self.reconcile(pause, historical_evidence_reviews=[review])
        review["disposition"] = "recheck"
        event = self.reconcile(pause, historical_evidence_reviews=[review])
        self.assertEqual(event["snapshot"]["source_attempt_count"], 1)
        from continuation_stage_c import pending_rechecks
        self.assertEqual(pending_rechecks(self.task, self.evidence)[0]["source_run_id"], "R1")
        retained = self.path / "raw" / "R2.json"
        retained.parent.mkdir()
        retained.write_text('{"current_status":"active"}', encoding="utf-8")
        replacement = {"run_id": "R2", "submission_state": "submitted", "status": "success",
            "finished_at": "2026-09-25T00:00:00Z", "raw_paths": ["raw/R2.json"]}
        self.evidence["source_runs"].append(replacement)
        self.save()
        with self.assertRaisesRegex(ValueError, "DYNAMIC_RECHECK_NOT_PROVEN"):
            record_event(self.path, {"kind": "evidence_recheck_complete", "actor": "reviewer",
                "reasoning": "Current record examined", "reconciliation_id": event["event_id"],
                "source_run_id": "R1", "replacement_source_run_id": "R2",
                "replacement_source_run_sha256": sha256_json(replacement),
                "fact_review": "Current right status read", "material_review": "Raw record read"})
        record_event(self.path, {"kind": "evidence_recheck_complete", "actor": "reviewer",
            "reasoning": "Current record examined", "reconciliation_id": event["event_id"],
            "source_run_id": "R1", "replacement_source_run_id": "R2",
            "replacement_source_run_sha256": sha256_json(replacement),
            "fact_review": "Current right status read", "material_review": "Raw record read",
            "object_match_basis": "Same patent number", "scope_match_basis": "Same US right"})
        self.read()
        self.assertEqual(pending_rechecks(self.task, self.evidence), [])

    def test_access_request_is_grouped_and_notice_deduplicated(self):
        view = {"entries": [{"work_id": "W1", "issue_id": "I1", "kind": "source_lookup",
            "state": "awaiting_access", "reason": "LOGIN_REQUIRED", "provider": "registry"},
            {"work_id": "W2", "issue_id": "I2", "kind": "source_lookup",
             "state": "awaiting_access", "reason": "LOGIN_REQUIRED", "provider": "registry"},
            {"work_id": "W3", "kind": "source_lookup", "state": "ready", "reason": "INDEPENDENT"}]}
        groups = access_requests(view, self.evidence)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["work_ids"], ["W1", "W2"])
        key = groups[0]["dependency_key"]
        with patch("workflow_v24.work_view_from_dir", return_value=view):
            record_event(self.path, {"kind": "access_notice", "actor": "agent", "reasoning": "One access operation",
                "dependency_key": key})
            with self.assertRaisesRegex(ValueError, "ALREADY_SENT"):
                record_event(self.path, {"kind": "access_notice", "actor": "agent", "reasoning": "Repeat",
                    "dependency_key": key})
            record_event(self.path, {"kind": "access_feedback", "actor": "user", "reasoning": "Login done",
                "dependency_key": key, "query_capability_verified": False,
                "condition_basis": "Original query still blocked", "user_feedback": "Logged in"})
        self.read()
        self.assertEqual(access_requests(view, self.evidence)[0]["notification"], "already_notified")
        self.assertEqual(active_pauses(self.evidence), [])
        changed = {"entries": [*view["entries"], {"work_id": "W4", "issue_id": "I4",
            "kind": "source_lookup", "state": "awaiting_access", "reason": "LOGIN_REQUIRED",
            "provider": "registry"}]}
        self.assertEqual(access_requests(changed, self.evidence)[0]["notification"], "notify_update")

    def test_legacy_task_is_unchanged(self):
        view = {"status": "incomplete", "entries": []}
        self.assertIs(project({"task_id": "T08C"}, view, self.evidence), view)
        self.assertIsNone(dispatch_block({"task_id": "T08C"}, self.evidence, {}))

    def test_real_next_work_and_direct_dispatch_share_pause_gate(self):
        import test_scenario_planning as fixtures
        from advance_work import actionable_packet
        from workflow_v24 import scenario_dispatch_block_from_dir, work_view_from_dir
        fixture = fixtures.ScenarioPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        row = fixture.plan["queries"]["epo_ops"][0]
        record_event(fixture.path, {"kind": "pause", "actor": "user", "reasoning": "Stop original task",
            "intent": "stop", "scope": {"level": "task"}})
        view = work_view_from_dir(fixture.path)
        self.assertTrue(view["active_pauses"])
        self.assertEqual(view["status"], "incomplete")
        self.assertFalse(actionable_packet(view)["source"])
        self.assertEqual(scenario_dispatch_block_from_dir(fixture.path, "epo_ops", row)["reason"],
                         "USER_ACTIVE_PAUSE")


if __name__ == "__main__":
    unittest.main()
