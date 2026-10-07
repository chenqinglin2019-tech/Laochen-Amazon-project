from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_outcome
from safety_control import SafetyPausedError, record_operational_outcome


class RunOutcomeTests(unittest.TestCase):
    def test_retry_guidance_honors_resume_time_without_promising_a_skip(self) -> None:
        outcome = run_outcome.classify_exception(run_outcome.retry_later("plugin_data_timeout"))
        self.assertIn("resume_at", outcome.next_action)
        self.assertIn("等待到期", outcome.next_action)
        self.assertNotIn("再次失败会", outcome.next_action)

    def test_skip_guidance_does_not_assume_two_item_failure_cycles(self) -> None:
        outcome = run_outcome.completed_outcome(2)
        self.assertNotIn("连续两轮", outcome.message + outcome.next_action)
        self.assertIn("skipped_items", outcome.next_action)
        self.assertIn("不能宣称完整交付", outcome.next_action)

    def test_exit_codes_are_distinct_per_status(self) -> None:
        cases = {
            run_outcome.retry_later("x"): (20, "retry_later"),
            run_outcome.needs_human("x"): (30, "needs_human"),
            run_outcome.config_error("x"): (40, "config_error"),
            SafetyPausedError("x", kind="lock_held"): (50, "lock_held"),
            SafetyPausedError("x", kind="risk_pause", resume_at="2026-10-03 12:00:00"): (21, "risk_pause"),
            RuntimeError("x"): (2, "error"),
        }
        for exc, expected in cases.items():
            outcome = run_outcome.classify_exception(exc)
            self.assertEqual((outcome.exit_code, outcome.status), expected)
            self.assertTrue(outcome.next_action)
        self.assertEqual(run_outcome.completed_outcome(0).exit_code, 0)
        self.assertEqual(run_outcome.completed_outcome(2).exit_code, 10)

    def test_finalize_writes_status_next_action_and_skips(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            (job / "state.json").write_text(json.dumps({"skipped_items": [{"work_key": "k"}]}), encoding="utf-8")
            (job / "run_summary.json").write_text(json.dumps({"pending_count": 3}), encoding="utf-8")
            code = run_outcome.exit_with(None, job, skipped_count=1)
            summary = json.loads((job / "run_summary.json").read_text(encoding="utf-8"))
            heartbeat = json.loads((job / "run_heartbeat.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 10)
        self.assertEqual(summary["status"], "completed_with_skips")
        self.assertEqual(summary["pending_count"], 3)
        self.assertEqual(summary["skipped_items"], [{"work_key": "k"}])
        self.assertEqual(heartbeat["phase"], "exited")

    def test_item_specific_failure_skips_on_the_second_run(self) -> None:
        data: dict = {}
        run_outcome.start_new_run()
        self.assertFalse(run_outcome.should_quarantine(run_outcome.note_item_failure(data, "a", reason="amazon_dog_error")))
        # A second failure in the same run never counts twice.
        self.assertFalse(run_outcome.should_quarantine(run_outcome.note_item_failure(data, "a", reason="amazon_dog_error")))
        run_outcome.start_new_run()
        self.assertTrue(run_outcome.should_quarantine(run_outcome.note_item_failure(data, "a", reason="expected_content_missing")))
        run_outcome.clear_item_failures(data, "a")
        run_outcome.start_new_run()
        self.assertFalse(run_outcome.should_quarantine(run_outcome.note_item_failure(data, "a", reason="amazon_dog_error")))
        run_outcome.record_skipped_item(data, "a", reason="r")
        run_outcome.record_skipped_item(data, "a", reason="r")
        self.assertEqual(len(data["skipped_items"]), 1)

    def test_outage_failures_do_not_skip_healthy_items(self) -> None:
        data: dict = {}
        decisions = []
        for _ in range(5):
            run_outcome.start_new_run()
            decisions.append(run_outcome.should_quarantine(
                run_outcome.note_item_failure(data, "k", reason="amazon_page_unavailable_retry_exhausted", detail="navigation_error net::ERR_INTERNET_DISCONNECTED")
            ))
        self.assertEqual(decisions, [False] * 5)
        self.assertTrue(data["last_failure_environment"])
        run_outcome.start_new_run()
        self.assertTrue(run_outcome.should_quarantine(run_outcome.note_item_failure(data, "k", reason="http_503")))

    def test_environment_failures_skip_after_four_runs_when_others_succeed(self) -> None:
        data: dict = {}
        state = SimpleNamespace(data=data, flush=lambda: None)
        results = []
        for _ in range(4):
            run_outcome.start_new_run()
            record_operational_outcome(state, True)  # another item succeeded in this run
            results.append(run_outcome.should_quarantine(run_outcome.note_item_failure(data, "k", reason="plugin_data_timeout")))
        self.assertEqual(results, [False, False, False, True])

    def test_no_skip_during_a_failure_streak(self) -> None:
        data: dict = {}
        state = SimpleNamespace(data=data, flush=lambda: None)
        run_outcome.start_new_run()
        run_outcome.note_item_failure(data, "a", reason="amazon_dog_error")
        run_outcome.start_new_run()
        record_operational_outcome(state, False)
        record_operational_outcome(state, False)
        self.assertFalse(run_outcome.should_quarantine(run_outcome.note_item_failure(data, "a", reason="amazon_dog_error")))

    def test_failure_classification_examples(self) -> None:
        self.assertTrue(run_outcome.is_environment_failure("all_candidates_unscorable"))
        self.assertTrue(run_outcome.is_environment_failure("amazon_page_unavailable_retry_exhausted navigation_error net::ERR_TIMED_OUT"))
        self.assertFalse(run_outcome.is_environment_failure("amazon_page_unavailable_retry_exhausted amazon_dog_error"))
        self.assertFalse(run_outcome.is_environment_failure("source_image_download_failed timeout"))

    def test_environment_retry_later_gets_a_resume_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            (job / "state.json").write_text(json.dumps({"last_failure_environment": True}), encoding="utf-8")
            run_outcome.exit_with(run_outcome.retry_later("x"), job)
            summary = json.loads((job / "run_summary.json").read_text(encoding="utf-8"))
        self.assertTrue(summary["resume_at"])
        self.assertIn(summary["resume_at"], summary["next_action"])

    def test_failure_window_resets_for_a_new_process(self) -> None:
        run_outcome.start_new_run()
        state = SimpleNamespace(data={"operation_consecutive_failures": 5, "operation_recent_outcomes": [False] * 5}, flush=lambda: None)
        self.assertFalse(record_operational_outcome(state, False))
        self.assertEqual(state.data["operation_consecutive_failures"], 1)


if __name__ == "__main__":
    unittest.main()
