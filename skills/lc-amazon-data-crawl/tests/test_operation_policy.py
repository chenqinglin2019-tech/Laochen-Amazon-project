from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from migrate_operation_config import migrate
from safety_control import LocalSafetyController, RiskSignal, SafetyPausedError, apply_operation_policy, parse_retry_after, record_operational_outcome


class OperationPolicyTests(unittest.TestCase):
    def test_modes_override_old_managed_values(self) -> None:
        for mode in ("supervised", "unattended"):
            runtime = SimpleNamespace(page_timeout=10, delay_seconds_min=1, batch_pause_seconds_min=600, plugin_timeout=120, page_scroll_wait_seconds=9, amazon_page_retry_schedule_seconds=((3600, 3600),))
            apply_operation_policy(runtime, mode)
            self.assertEqual(runtime.page_timeout, 90)
            self.assertEqual(runtime.delay_seconds_min, 20 if mode == "supervised" else 45)
            self.assertEqual(runtime.plugin_timeout, 40 if mode == "supervised" else 180)
            self.assertEqual(runtime.page_scroll_wait_seconds, 2 if mode == "supervised" else 1)
            self.assertEqual(runtime.amazon_page_retry_schedule_seconds, ((60, 60),) if mode == "supervised" else ((120, 120), (300, 300)))
            self.assertEqual(runtime.manual_pause_timeout, 900 if mode == "supervised" else 0)
            image = SimpleNamespace(page_timeout=10, amazon_page_unavailable_retry_schedule_seconds=((3600, 3600),))
            apply_operation_policy(image, mode, image=True)
            self.assertEqual((image.find_similar_timeout, image.lens_results_timeout, image.plugin_timeout), (20, 40, 20) if mode == "supervised" else (12, 60, 180))

    def test_unattended_tenth_attempt_rests_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            now = [dt.datetime(2026, 9, 24)]
            sleeps = []
            def sleep(seconds):
                sleeps.append(seconds)
                now[0] += dt.timedelta(seconds=seconds)
            controller = LocalSafetyController(Path(temp), clock=lambda: now[0], mode="unattended", batch_pause_pages_min=10, batch_pause_pages_max=10, batch_pause_seconds_min=900, batch_pause_seconds_max=1200)
            with patch("safety_control.time.sleep", side_effect=sleep), patch("safety_control.random.uniform", side_effect=lambda low, high: low):
                for _ in range(10):
                    controller.before_remote_action("导航")
                before = now[0]
                controller.before_remote_action("失败后的重试导航")
            self.assertEqual((now[0] - before).total_seconds(), 900)
            self.assertEqual(json.loads(controller.traffic_path.read_text())["actions_count"], 11)

    def test_rate_after_and_recurrence_do_not_shorten_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            now = [dt.datetime(2026, 9, 24)]
            controller = LocalSafetyController(Path(temp), clock=lambda: now[0])
            self.assertEqual(parse_retry_after("3600"), 3600)
            controller.set_work_key("original")
            with self.assertRaises(SafetyPausedError):
                controller.trip(RiskSignal("amazon", "http_429", "限流", retry_after_seconds=3600))
            first = json.loads(controller.pause_path.read_text())
            self.assertEqual(first["not_before"], (now[0] + dt.timedelta(hours=1)).isoformat())
            now[0] += dt.timedelta(minutes=5)
            with self.assertRaises(SafetyPausedError):
                controller.trip(RiskSignal("amazon", "http_429", "再次限流"))
            second = json.loads(controller.pause_path.read_text())
            self.assertEqual(second["kind"], "manual_review")
            self.assertGreaterEqual(dt.datetime.fromisoformat(second["not_before"]), now[0] + dt.timedelta(hours=24))

    def test_failed_rate_probe_becomes_manual_24_hour_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            now = [dt.datetime(2026, 9, 24)]
            controller = LocalSafetyController(Path(temp), clock=lambda: now[0])
            controller.set_work_key("original")
            with self.assertRaises(SafetyPausedError):
                controller.trip(RiskSignal("amazon", "http_429", "限流"))
            now[0] += dt.timedelta(minutes=30)
            restarted = LocalSafetyController(Path(temp), clock=lambda: now[0])
            restarted.begin()
            self.assertTrue(restarted.rate_probe_active)
            restarted.set_work_key("original")
            restarted.fail_review()
            self.assertFalse(restarted.rate_probe_active)
            pause = json.loads(restarted.pause_path.read_text())
            self.assertEqual(pause["reason"], "rate_probe_failed")
            self.assertEqual(pause["kind"], "manual_review")
            self.assertEqual(pause["not_before"], (now[0] + dt.timedelta(hours=24)).isoformat())
            with self.assertRaises(SafetyPausedError):
                restarted.begin()

    def test_migration_preserves_business_values_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "amazon_front_keyword_search.json"
            path.write_text(json.dumps({"job_id": "keep", "inputs_file": "private.csv", "plugin_timeout": 120}), encoding="utf-8")
            self.assertTrue(migrate(path))
            first = path.read_bytes()
            self.assertFalse(migrate(path))
            self.assertEqual(path.read_bytes(), first)
            value = json.loads(first)
            self.assertEqual((value["job_id"], value["inputs_file"]), ("keep", "private.csv"))
            self.assertEqual((value["operation_mode"], value["plugin_timeout"]), ("supervised", 40))

    def test_failure_window_survives_checkpoint_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            class State:
                def __init__(self):
                    self.data = json.loads(path.read_text()) if path.exists() else {}
                def flush(self):
                    path.write_text(json.dumps(self.data), encoding="utf-8")
            first = State()
            self.assertFalse(record_operational_outcome(first, False))
            second = State()
            self.assertFalse(record_operational_outcome(second, False))
            third = State()
            self.assertTrue(record_operational_outcome(third, False))
            self.assertEqual(third.data["operation_consecutive_failures"], 3)

    def test_interrupted_captcha_cooldown_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            now = [dt.datetime(2026, 9, 24)]
            controller = LocalSafetyController(Path(temp), clock=lambda: now[0])
            with patch("safety_control.time.sleep", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    controller.captcha_cleared()
            restarted = LocalSafetyController(Path(temp), clock=lambda: now[0])
            def advance(seconds):
                now[0] += dt.timedelta(seconds=seconds)
            with patch("safety_control.time.sleep", side_effect=advance), patch("safety_control.random.uniform", side_effect=lambda low, high: low):
                restarted.before_remote_action("复核")
            self.assertGreaterEqual(now[0], dt.datetime(2026, 9, 24, 0, 10))


if __name__ == "__main__":
    unittest.main()
