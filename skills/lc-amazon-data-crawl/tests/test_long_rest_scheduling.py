from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from safety_control import LocalSafetyController, RiskSignal, SafetyPausedError


class VirtualClock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 9, 24, 0, 0, 0)
        self.sleeps: list[float] = []

    def clock(self) -> dt.datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += dt.timedelta(seconds=seconds)


class LongRestSchedulingTests(unittest.TestCase):
    def controller(self, root: Path, clock: VirtualClock, mode: str = "supervised") -> LocalSafetyController:
        return LocalSafetyController(
            root, clock=clock.clock, mode=mode,
            batch_pause_pages_min=20 if mode == "supervised" else 10,
            batch_pause_pages_max=20 if mode == "supervised" else 10,
            batch_pause_seconds_min=180 if mode == "supervised" else 900,
            batch_pause_seconds_max=300 if mode == "supervised" else 1200,
        )

    def test_supervised_twenty_and_hundred_breaks_replace_not_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            clock = VirtualClock()
            controller = self.controller(Path(temp), clock)
            rests = {}
            with patch("safety_control.time.sleep", side_effect=clock.sleep), patch("safety_control.random.uniform", side_effect=lambda low, high: low):
                for attempt in range(1, 202):
                    before = clock.now
                    controller.before_remote_action("导航")
                    elapsed = (clock.now - before).total_seconds()
                    if elapsed >= 180:
                        rests[attempt] = elapsed
            self.assertEqual([21, 41, 61, 81, 101, 121, 141, 161, 181, 201], list(rests))
            self.assertEqual(rests[101], 600)
            self.assertEqual(rests[201], 600)
            self.assertTrue(all(value == 180 for key, value in rests.items() if key not in (101, 201)))
            self.assertEqual(json.loads(controller.traffic_path.read_text())["actions_count"], 201)

    def test_restart_interrupted_rest_and_mode_switch_preserve_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clock = VirtualClock()
            with patch("safety_control.time.sleep", side_effect=clock.sleep), patch("safety_control.random.uniform", side_effect=lambda low, high: low):
                first = self.controller(root, clock)
                for _ in range(20):
                    first.before_remote_action("导航")
                with patch("safety_control.time.sleep", side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        first.before_remote_action("导航")
                deadline = json.loads(first.traffic_path.read_text())["rest_until"]
                second = self.controller(root, clock, "unattended")
                second.before_remote_action("导航")
                self.assertGreaterEqual(clock.now, dt.datetime.fromisoformat(deadline))
                self.assertEqual(json.loads(second.traffic_path.read_text())["actions_count"], 21)

    def test_rate_probe_may_use_any_item_and_passes_on_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clock = VirtualClock()
            controller = self.controller(root, clock)
            controller.set_work_key("page-1")
            with self.assertRaises(SafetyPausedError):
                controller.trip(RiskSignal("amazon", "http_429", "限流"))
            with self.assertRaises(SafetyPausedError):
                controller.before_remote_action("导航")
            clock.now += dt.timedelta(minutes=30)
            restarted = self.controller(root, clock)
            with patch("safety_control.time.sleep", side_effect=clock.sleep):
                restarted.begin()
                restarted.set_work_key("page-2")
                restarted.before_remote_action("导航")
                self.assertTrue(restarted.pause_path.exists())
                restarted.note_risk_checked()
                restarted.before_remote_action("导航")
            self.assertFalse(restarted.pause_path.exists())

    def test_unverified_probe_never_clears_the_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clock = VirtualClock()
            controller = self.controller(root, clock)
            with self.assertRaises(SafetyPausedError):
                controller.trip(RiskSignal("amazon", "http_403", "拒绝访问"))
            clock.now += dt.timedelta(hours=25)
            restarted = self.controller(root, clock)
            with patch("safety_control.time.sleep", side_effect=clock.sleep):
                restarted.begin(resume_after_review=True)
                restarted.before_remote_action("导航")  # probe navigation raised before the risk check
                with self.assertRaises(SafetyPausedError):
                    restarted.before_remote_action("导航")  # retry: no second probe in this run
            restarted.fail_review()
            self.assertTrue(restarted.pause_path.exists())

    def test_restart_mid_rest_waits_only_the_remaining_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clock = VirtualClock()
            draws = iter([20.0] * 20 + [300.0, 20.0, 180.0, 20.0])
            with patch("safety_control.random.uniform", side_effect=lambda low, high: next(draws)):
                with patch("safety_control.time.sleep", side_effect=clock.sleep):
                    first = self.controller(root, clock)
                    for _ in range(20):
                        first.before_remote_action("导航")
                rest_started = clock.now
                calls = {"n": 0}

                def interrupt_after_170(seconds: float) -> None:
                    calls["n"] += 1
                    if calls["n"] > 1 and (clock.now - rest_started).total_seconds() >= 170:
                        raise KeyboardInterrupt
                    clock.sleep(seconds)

                with patch("safety_control.time.sleep", side_effect=interrupt_after_170):
                    with self.assertRaises(KeyboardInterrupt):
                        first.before_remote_action("导航")
                deadline = dt.datetime.fromisoformat(json.loads(first.traffic_path.read_text())["rest_until"])
                interrupted_at = clock.now
                with patch("safety_control.time.sleep", side_effect=clock.sleep):
                    self.controller(root, clock).before_remote_action("导航")
            self.assertEqual(clock.now, deadline)
            self.assertLessEqual((clock.now - interrupted_at).total_seconds(), 130)

if __name__ == "__main__":
    unittest.main()
