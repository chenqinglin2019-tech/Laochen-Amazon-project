from __future__ import annotations

import sys
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_front_crawler as front


ASIN = "B0H835TGDB"


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class StorefrontPluginReadinessTests(unittest.TestCase):
    def runtime(self) -> SimpleNamespace:
        return SimpleNamespace(
            include_sponsored=False,
            page_scroll_step_ratio=0.85,
            storefront_plugin_stable_seconds=10.0,
        )

    def test_snapshot_accepts_rendered_na_and_zero(self) -> None:
        class Driver:
            def execute_script(self, _script, asins, scroll, _step, labels):
                self.assertions = (asins, scroll, labels)
                return {
                    "at_bottom": True,
                    "scroll_height": 1000,
                    "results": {ASIN: {"reason": "complete", "values": {
                        "近30天销量(父体)": "N/A",
                        "近30天销量(子体)": "0",
                        "FBA费用": "N/A",
                        "毛利率": "N/A",
                    }}},
                }

        driver = Driver()
        with patch.object(front, "extract_front_product_cards", return_value=[
            {"asin": ASIN, "is_sponsored": "no"},
            {"asin": "B000000001", "is_sponsored": "yes"},
        ]):
            snapshot = front.inspect_storefront_plugin_page(driver, self.runtime(), scroll=True)
        self.assertEqual(snapshot["product_count"], 1)
        self.assertEqual(snapshot["complete_count"], 1)
        self.assertEqual(snapshot["pending"], {})
        self.assertEqual(driver.assertions[0], [ASIN])

    def test_waits_for_every_asin_and_ten_stable_seconds(self) -> None:
        clock = FakeClock()
        snapshots = [
            {"at_bottom": False, "product_count": 2, "complete_count": 1,
             "pending": {ASIN: "loading"}, "signature": "scrolling"},
            {"at_bottom": True, "product_count": 2, "complete_count": 1,
             "pending": {ASIN: "loading"}, "signature": "partial"},
        ]
        ready = {"at_bottom": True, "product_count": 2, "complete_count": 2,
                 "pending": {}, "signature": "complete"}
        snapshots.extend([ready] * 10)
        driver = SimpleNamespace(current_url="https://www.amazon.com/stores/test", execute_script=lambda *_: True)
        with (
            patch.object(front, "inspect_sellersprite_readiness", return_value={"status": "ready_candidate"}),
            patch.object(front, "inspect_storefront_plugin_page", side_effect=snapshots),
            patch.object(front.time, "monotonic", side_effect=clock.monotonic),
            patch.object(front.time, "sleep", side_effect=clock.sleep),
        ):
            result = front.wait_for_storefront_plugin_page(driver, self.runtime(), 140.0)
        self.assertEqual(result, "ok")
        self.assertGreaterEqual(clock.now, 112.5)
        self.assertEqual(front.get_sellersprite_readiness(driver)["status"], "ready")

    def test_timeout_keeps_pending_asin_and_budget_is_not_reset(self) -> None:
        clock = FakeClock()
        driver = SimpleNamespace(current_url="https://www.amazon.com/stores/test", execute_script=lambda *_: True)
        pending = {"at_bottom": True, "product_count": 2, "complete_count": 1,
                   "pending": {ASIN: "field_missing:毛利率"}, "signature": "partial"}
        with (
            patch.object(front, "inspect_sellersprite_readiness", return_value={"status": "data_loading"}),
            patch.object(front, "inspect_storefront_plugin_page", return_value=pending),
            patch.object(front.time, "monotonic", side_effect=clock.monotonic),
            patch.object(front.time, "sleep", side_effect=clock.sleep),
        ):
            result = front.wait_for_storefront_plugin_page(driver, self.runtime(), 140.0)
        self.assertEqual(result, "timeout")
        self.assertEqual(clock.now, 140.0)
        self.assertEqual(front.get_sellersprite_readiness(driver)["pending_asins"], pending["pending"])

    def test_scroll_uses_the_same_forty_second_budget(self) -> None:
        clock = FakeClock()
        driver = SimpleNamespace(current_url="https://www.amazon.com/stores/test", execute_script=lambda *_: False)
        with (
            patch.object(front.time, "monotonic", side_effect=clock.monotonic),
            patch.object(front.time, "sleep", side_effect=clock.sleep),
            patch.object(front, "inspect_storefront_plugin_page", return_value={
                "at_bottom": False, "asins": [ASIN], "product_count": 1,
                "complete_count": 1, "pending": {}, "signature": "incomplete_scroll",
            }) as inspect,
        ):
            result = front.wait_for_storefront_plugin_page(driver, self.runtime(), 140.0)
        self.assertEqual(result, "timeout")
        self.assertEqual(clock.now, 140.0)
        inspect.assert_called_once()
        self.assertEqual(
            front.get_sellersprite_readiness(driver)["pending_asins"],
            {ASIN: "page_not_at_bottom"},
        )

    def test_storefront_timeout_stops_before_extract_and_pagination(self) -> None:
        runtime = SimpleNamespace(
            mode="storefront",
            sellersprite_required=True,
            plugin_timeout=40,
            save_debug_snapshots=False,
            amazon_page_retry_schedule_seconds=((60.0, 60.0),),
        )
        driver = SimpleNamespace(current_url="https://www.amazon.com/stores/example")
        worker = front.FrontWorker(
            "tab-1", runtime, queue.Queue(), front.ManualActionCoordinator(),
            front.NavigationThrottle(0, 0), front.DeliveryDomainLocks(),
            Path(tempfile.gettempdir()),
        )
        task = {
            "source_type": "storefront", "source_id": "example", "page_number": 1,
            "page_url": driver.current_url,
        }
        with (
            patch.object(worker, "_begin_attempt_scope"),
            patch.object(worker, "_cleanup_attempt_scope"),
            patch.object(worker, "_open_page"),
            patch.object(worker, "_ensure_driver", return_value=driver),
            patch.object(worker, "_wait_for_page_or_manual", return_value=front.PageHealthStatus.HEALTHY),
            patch.object(worker, "_ensure_delivery_after_healthy_page"),
            patch.object(front, "prepare_storefront_page"),
            patch.object(front, "wait_for_storefront_plugin_page", return_value="timeout"),
            patch.object(front, "get_sellersprite_readiness", return_value={"pending_asins": {ASIN: "loading"}}),
            patch.object(front, "merge_front_product_data") as extract,
            patch.object(front, "build_next_front_task") as next_page,
            self.assertRaisesRegex(front.UserFacingError, "当前页未写入"),
        ):
            worker._process_attempt(task)
        extract.assert_not_called()
        next_page.assert_not_called()


if __name__ == "__main__":
    unittest.main()
