from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from safety_control import (  # noqa: E402
    LocalSafetyController,
    RiskSignal,
    SafetyPausedError,
    classify_amazon_risk,
    classify_sellersprite_risk,
)
from amazon_category_rank_crawler import (  # noqa: E402
    parse_field_from_text,
    sellersprite_field_status,
)


class SafetyControlTests(unittest.TestCase):
    def test_explicit_platform_risk_markers_are_classified(self) -> None:
        self.assertEqual(
            classify_amazon_risk(http_status=429).reason,
            "http_429",
        )
        self.assertEqual(
            classify_amazon_risk(
                http_status=200,
                body_text="Sorry, we just need to make sure you're not a robot",
            ).reason,
            "captcha_or_robot_check",
        )
        self.assertEqual(
            classify_sellersprite_risk("卖家精灵：配额已用完").reason,
            "quota_exhausted",
        )
        self.assertIsNone(classify_amazon_risk(http_status=503))

    def test_pause_survives_new_controller_and_needs_review_after_cooldown(self) -> None:
        now = [dt.datetime(2026, 9, 12, 10, 0, 0)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = LocalSafetyController(root, clock=lambda: now[0])
            with self.assertRaises(SafetyPausedError):
                controller.trip(
                    RiskSignal("amazon", "http_429", "限流", cooldown_seconds=60),
                    page_url="https://www.amazon.com/dp/B000000001?token=private",
                )
            pause = json.loads((root / "risk-pause.json").read_text(encoding="utf-8"))
            self.assertEqual(pause["platform"], "amazon")
            self.assertEqual(pause["reason"], "http_429")
            self.assertEqual(pause["page_url"], "https://www.amazon.com/dp/B000000001")

            restarted = LocalSafetyController(root, clock=lambda: now[0])
            with self.assertRaises(SafetyPausedError):
                restarted.begin()
            with self.assertRaises(SafetyPausedError):
                restarted.begin(resume_after_review=True)

            now[0] += dt.timedelta(minutes=30)
            restarted.begin(resume_after_review=True)
            with patch("safety_control.time.sleep"):
                restarted.before_remote_action("复核原页面")
            restarted.complete_review_success()
            self.assertFalse((root / "risk-pause.json").exists())

    def test_every_twenty_actions_forces_three_minute_break(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = LocalSafetyController(Path(temp_dir))
            with patch("safety_control.time.sleep") as sleep, patch("safety_control.random.uniform", side_effect=lambda low, high: low):
                for _index in range(21):
                    controller.before_remote_action("导航")
            self.assertIn(30.0, [call.args[0] for call in sleep.call_args_list])
            self.assertEqual(json.loads(controller.traffic_path.read_text())["actions_count"], 21)

    def test_one_local_process_lock_is_shared_by_all_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = LocalSafetyController(Path(temp_dir))
            second = LocalSafetyController(Path(temp_dir))
            first.acquire()
            try:
                with self.assertRaises(SafetyPausedError):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()

    def test_keyword_labels_do_not_cross_fill_and_zero_remains_unconfirmed(self) -> None:
        text = "Organic keywords: 12; Sponsored keywords: 7"
        self.assertEqual(parse_field_from_text("organic_keywords_count", text), "12")
        self.assertEqual(parse_field_from_text("ad_keywords_count", text), "7")
        self.assertEqual(
            sellersprite_field_status("organic_keywords_count", "0"),
            "zero_unconfirmed",
        )


if __name__ == "__main__":
    unittest.main()
