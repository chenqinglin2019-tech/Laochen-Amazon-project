"""Synthetic read-only progress, no-model timing and failure-loop regressions."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lc_image_pipeline as p
import lc_runtime_status as r
import lc_scheduler as s


class RuntimeStatusTests(unittest.TestCase):
    def test_status_uses_private_snapshot_without_writes_or_lock(self):
        manifest = {"project_id": "synthetic-status", "concurrency": 2, "jobs": [
            {"id": "a", "status": "pending", "render_mode": "reference_generate"}]}
        before = copy.deepcopy(manifest)
        def execution(snapshot, *, base):
            snapshot["anchor_job_id"] = "a"
            return {"anchor": "a", "anchor_passed": False, "dispatch": [],
                    "deterministic_resume": [], "review_pending": [], "blocked": []}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(p, "execution_plan", side_effect=execution), \
                patch.object(p, "write_json", side_effect=AssertionError("readonly")), \
                patch("lc_workflow.manifest_lock", side_effect=AssertionError("no lock")):
            result = r.build_status(manifest, Path(directory), now=100)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(manifest, before)
        self.assertEqual(result["image_count"], 1)
        self.assertEqual(result["anchor"], "a")
        self.assertIsNone(result["timing"]["model_wall_seconds"])

    def test_status_lists_product_and_title_effect_inflight_separately(self):
        manifest = {"concurrency": 2, "jobs": [
            {"id": "product", "status": "generating", "active_attempt_id": "p1"},
            {"id": "title", "status": "generated", "title_effect_attempts": [
                {"id": "t0", "status": "returned"}, {"id": "t1", "status": "started"}]}]}
        plan = {"anchor": "product", "anchor_passed": False, "dispatch": [],
                "deterministic_resume": [], "review_pending": [], "blocked": []}
        with patch.object(p, "execution_plan", return_value=plan):
            result = r.build_status(manifest, Path("/synthetic-fixture"))
        self.assertEqual(result["scheduler"]["active_model_calls"], 2)
        self.assertEqual(result["inflight"], [
            {"id": "product", "kind": "product", "attempt_id": "p1"},
            {"id": "title", "kind": "title_effect", "attempt_id": "t1"}])

    def test_same_input_and_error_twice_requests_diagnosis_without_changing_jobs(self):
        manifest = {"jobs": [{"id": "a", "status": "blocked"}, {"id": "b", "status": "pending"}]}
        before = copy.deepcopy(manifest["jobs"])
        fingerprint = r.diagnostic_input_fingerprint(manifest, "plan", ["a"])
        first = r.record_command_failure(manifest, "plan", fingerprint, "layout capacity", job_ids=["a"], now=100)
        self.assertFalse(first["diagnosis_required"])
        self.assertEqual(fingerprint, r.diagnostic_input_fingerprint(manifest, "plan", ["a"]))
        second = r.record_command_failure(manifest, "plan", fingerprint, "layout capacity", job_ids=["a"], now=101)
        self.assertTrue(second["diagnosis_required"])
        self.assertEqual(len(r.active_diagnostics(manifest)), 1)
        self.assertEqual(manifest["jobs"], before)
        r.record_command_success(manifest, "plan", job_ids=["a"])
        self.assertEqual(r.active_diagnostics(manifest), [])
        fresh = r.record_command_failure(manifest, "plan", fingerprint, "layout capacity", job_ids=["a"], now=103)
        self.assertEqual(fresh["consecutive_count"], 1)

    def test_changed_inputs_or_error_start_a_new_streak(self):
        manifest = {}
        for fingerprint, error in [("a", "error"), ("b", "error"), ("b", "other")]:
            result = r.record_command_failure(manifest, "review-prepare", fingerprint, error, now=100)
            self.assertEqual(result["consecutive_count"], 1)
        self.assertEqual(r.active_diagnostics(manifest), [])

    def test_error_summary_redacts_credential_like_values_and_image_data(self):
        value = r.record_command_failure({}, "plan", "a", "Authorization: secret token=secret2 data:image/png;base64,AAAA", now=100)
        self.assertNotIn("secret", value["error"])
        self.assertNotIn("AAAA", value["error"])

    def test_interval_union_and_unclassified_require_actual_events(self):
        manifest = {"jobs": [{"generation_attempts": [
            {"tool_started_at": 10, "tool_returned_at": 20},
            {"tool_started_at": 15, "tool_returned_at": 25},
            {"dispatched_at": 8, "ingested_at": 30}]}]}
        result = r.timing_summary(manifest)
        self.assertEqual(result["model_wall_seconds"], 15)
        self.assertEqual(result["model_call_seconds"], 20)
        self.assertEqual(result["attempts_without_complete_tool_events"], 1)
        self.assertIsNone(result["local_wall_seconds"])
        self.assertIsNone(result["unclassified_seconds"])
        r.record_interval(manifest, "local", 5, 12, event_id="local1")
        r.record_interval(manifest, "user_wait", 28, 30, event_id="wait1")
        manifest["runtime_diagnostics"]["observation_window"] = {"started_at": 0, "finished_at": 35}
        result = r.timing_summary(manifest)
        self.assertEqual(result["observed_union_seconds"], 22)
        self.assertEqual(result["unclassified_seconds"], 13)
        self.assertEqual(result["local_wall_seconds"], 7)
        self.assertEqual(result["user_wait_seconds"], 2)

    def test_intervals_are_idempotent_and_cannot_be_rewritten(self):
        manifest = {}
        r.record_interval(manifest, "local", 5, 10, event_id="a")
        before = copy.deepcopy(manifest)
        r.record_interval(manifest, "local", 5, 10, event_id="a")
        self.assertEqual(manifest, before)
        with self.assertRaises(ValueError):
            r.record_interval(manifest, "local", 5, 11, event_id="a")
        for value in (True, -1, float("nan"), float("inf"), 10**400):
            with self.assertRaises(ValueError):
                r.record_interval({}, "local", value, 100, event_id="a")

    def test_recorded_capacity_evidence_is_validated_without_changing_old_integer(self):
        manifest = {"scheduler_policy": s.default_policy(), "concurrency": 2, "jobs": []}
        s.set_tool_capacity(manifest, 4, source="tool_metadata", reason="Four concurrent calls supported", now=123)
        self.assertEqual(s.validate(manifest), [])
        self.assertEqual(manifest["network_health"]["tool_capacity"], 4)
        self.assertEqual(s.state(manifest)["tool_capacity_evidence"]["recorded_at"], 123)
        before = copy.deepcopy(manifest)
        with self.assertRaises(ValueError):
            s.set_tool_capacity(manifest, 1, source="unverified")
        self.assertEqual(manifest, before)
        s.set_tool_capacity(manifest, 1)
        self.assertNotIn("tool_capacity_evidence", manifest["network_health"])
        self.assertEqual(s.validate(manifest), [])


if __name__ == "__main__":
    unittest.main()
