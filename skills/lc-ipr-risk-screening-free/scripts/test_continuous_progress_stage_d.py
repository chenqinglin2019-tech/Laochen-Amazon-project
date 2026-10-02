"""08D per-action progress and stop regression contracts."""
import tempfile
import unittest
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_file
from continuous_progress_stage_d import REVISION, dispatch_block, project, record_event, status


class ProgressStageDTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.task = {"task_id": "T08D", "continuous_progress_revision": REVISION}
        self.evidence = {"task_id": "T08D", "source_runs": [], "other_facts": []}
        self.rows = [
            {"work_id": "W1", "issue_id": "ISSUE-1", "linked_action_id": "ACTION-1",
             "kind": "source_lookup", "state": "ready", "query_id": "Q1", "provider": "epo_ops",
             "right_type": "patent", "reason": "SOURCE_PENDING"},
            {"work_id": "W2", "issue_id": "ISSUE-2", "linked_action_id": "ACTION-2",
             "kind": "source_lookup", "state": "ready", "query_id": "Q2", "provider": "epo_ops",
             "right_type": "trademark_word", "reason": "SOURCE_PENDING"},
        ]
        atomic_write_json(self.path / "task.json", self.task)
        self.save()

    def save(self):
        atomic_write_json(self.path / "evidence.json", self.evidence)

    def view(self, *_args, **_):
        return {"entries": [dict(row) for row in self.rows], "status": "incomplete"}

    def event(self, kind, **fields):
        with patch("workflow_v24.work_view_from_dir", side_effect=self.view):
            row = record_event(self.path, {"kind": kind, "actor": "agent", "reasoning": "reviewed actual record",
                                           **fields})
        self.evidence = load_json(self.path / "evidence.json")
        return row

    def round(self, work_id="W1", update=None):
        begin = self.event("begin", work_id=work_id)
        if update:
            update()
            self.save()
        return self.event("finish", begin_id=begin["event_id"], action_taken="inspect original result")

    def test_wait_does_not_count_and_other_work_does_not_mask_stall(self):
        with self.assertRaisesRegex(ValueError, "ACTIONABLE"):
            self.rows[0]["state"] = "awaiting_user"
            self.event("begin", work_id="W1")
        self.rows[0]["state"] = "ready"
        self.assertFalse(self.round()["effective_progress"])
        def unrelated():
            self.evidence["other_facts"].append({"query_id": "Q2", "fact": "new"})
        self.assertFalse(self.round(update=unrelated)["effective_progress"])
        self.assertTrue(status(self.evidence, "ACTION-1")["diagnosis_required"])
        self.assertEqual(status(self.evidence, "ACTION-2")["rounds"], 0)

    def test_bound_fact_is_progress_and_resets_only_own_streak(self):
        self.round()
        def related():
            self.evidence["source_runs"].append({"run_id": "R1", "query_id": "Q1", "status": "success"})
        self.assertTrue(self.round(update=related)["effective_progress"])
        self.assertEqual(status(self.evidence, "ACTION-1")["consecutive_no_progress"], 0)

    def test_diagnose_repair_failed_round_stops_exact_action(self):
        self.round()
        self.round()
        with self.assertRaisesRegex(ValueError, "DIAGNOSIS_AND_REPAIR"):
            self.event("begin", work_id="W1")
        checks = {key: "checked original " + key for key in
                  ("command", "receipt", "retained_files", "adapter", "submission")}
        self.event("diagnosis", action_id="ACTION-1", checks=checks)
        repair = self.path / "adapter-fix.txt"
        repair.write_text("patched adapter", encoding="utf-8")
        self.event("repair", action_id="ACTION-1", evidence_ref={"path": str(repair), "sha256": sha256_file(repair)})
        self.round()
        stop = self.event("technical_stop", action_id="ACTION-1", recovery_condition="new adapter evidence")
        view = project(self.task, self.view(), self.evidence)
        self.assertEqual(view["entries"][0]["reason"], "TECHNICAL_EXECUTION_STOPPED")
        self.assertEqual(view["entries"][1]["state"], "ready")
        self.assertEqual(view["technical_stops"][0]["event_id"], stop["event_id"])
        self.assertEqual(dispatch_block(self.task, self.evidence, "epo_ops", {"query_id": "Q1"}),
                         "TECHNICAL_EXECUTION_STOPPED")
        self.assertIsNone(dispatch_block(self.task, self.evidence, "epo_ops", {"query_id": "Q2"}))
        with self.assertRaisesRegex(ValueError, "TECHNICAL_STOP"):
            self.event("begin", work_id="W1")
        new = self.path / "new-repair.txt"
        new.write_text("new basis after stop", encoding="utf-8")
        self.evidence["continuation_events"] = [{"kind": "reconcile", "event_id": "RECON-1"}]
        self.save()
        self.event("reopen", action_id="ACTION-1", reconciliation_id="RECON-1",
                   new_evidence_ref={"path": str(new), "sha256": sha256_file(new)})
        self.assertEqual(status(self.evidence, "ACTION-1")["rounds"], 3)
        self.assertEqual(status(self.evidence, "ACTION-1")["consecutive_no_progress"], 0)
        self.assertIsNone(dispatch_block(self.task, self.evidence, "epo_ops", {"query_id": "Q1"}))

    def test_read_only_completion_stage_preserves_stop_and_pause(self):
        from completion_check import workflow_stage
        packet = {"source": [], "agent": [], "repair": [], "review": [], "waiting": []}
        kwargs = {"first_review": None, "second_review": None, "adjudication": None,
                  "output_dir": None}
        self.assertEqual(workflow_stage({"active_pauses": [{"pause_id": "P1"}]}, packet, **kwargs),
                         "investigation")
        self.assertEqual(workflow_stage({"technical_stops": [{"event_id": "S1"}]}, packet, **kwargs),
                         "investigation")
        self.assertEqual(self.evidence.get("progress_events"), None)

    def test_dispatcher_repeated_read_does_not_count_work_round(self):
        from advance_work import main
        self.task["execution_policy_revision"] = "continuous-work-v2"
        atomic_write_json(self.path / "task.json", self.task)
        atomic_write_json(self.path / "search-plan.json", {"task_id": "T08D", "queries": {}})
        view = {"entries": [], "status": "incomplete", "counts": {}, "per_work_progress": []}
        printed = io.StringIO()
        with patch("sys.argv", ["advance_work.py", "--task-dir", str(self.path)]), \
             patch("advance_work.work_view_from_dir", return_value=view), \
             patch("advance_work.workflow_stage", return_value="investigation"), \
             redirect_stdout(printed):
            main()
            main()
        saved = load_json(self.path / "continuous-work-status.json")
        output = json.JSONDecoder().raw_decode(printed.getvalue())[0]
        self.assertEqual(output["runtime_progress"]["current_activity"], "unconfirmed")
        self.assertEqual(output["runtime_progress"]["next_step"]["state"], "unknown")
        self.assertNotIn("runtime_progress", saved)
        self.assertIsNone(saved["consecutive_no_progress"])
        self.assertNotIn("no_progress_diagnosis", saved)
        self.assertEqual(self.evidence.get("progress_events"), None)


if __name__ == "__main__":
    unittest.main()
