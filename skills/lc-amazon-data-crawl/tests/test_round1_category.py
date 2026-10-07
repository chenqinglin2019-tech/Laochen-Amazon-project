"""Round-1 regression tests for the sequential category page loop and shared helpers.

The production loop (`_run_crawl_unlocked`) is driven offline: every DOM-facing
function is patched, the safety root is a temp dir and retry waits use a fake
clock, so no browser, network or real sleeping is involved.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_category_rank_crawler as category  # noqa: E402
import run_outcome  # noqa: E402
from amazon_page_recovery import (  # noqa: E402
    PageHealthAssessment,
    PageHealthStatus,
    TransientAmazonPageUnavailable,
)


START = "https://www.amazon.com/gp/new-releases/home-garden/1063238/"
HEALTHY = PageHealthAssessment(PageHealthStatus.HEALTHY, "ok", "search_category")
EMPTY = PageHealthAssessment(PageHealthStatus.VERIFIED_EMPTY, "explicit_empty", "search_category")


def child_url(node_id: str) -> str:
    return f"https://www.amazon.com/gp/new-releases/home-garden/{node_id}/"


class DummyDriver:
    current_url = START
    title = ""

    def quit(self) -> None:
        pass


class LoopHarness:
    """Runs `run_crawl` with a scripted fake site.

    `site` maps a URL to a dict:
      children: list of child node ids (page 1 only)
      behaviour: "records" (default) | "transient" | "empty" | "verify"
      next: next-page URL returned by find_next_page_url
    """

    def __init__(self, tmp: Path, site: Dict[str, Dict[str, Any]], **config: Any) -> None:
        self.tmp = tmp
        self.site = site
        self.safety_root = tmp / "safety"
        self.safety_root.mkdir(exist_ok=True)
        self.config = {
            "start_url": START,
            "job_id": "loop",
            "outputs_root": str(tmp / "out"),
            "delivery_location_enabled": False,
            "operation_mode": "supervised",
        }
        self.config.update(config)
        self.navigations: List[str] = []
        self.current_url = START

    @property
    def job_dir(self) -> Path:
        return self.tmp / "out" / "loop"

    def state(self) -> Dict[str, Any]:
        return json.loads((self.job_dir / "state.json").read_text(encoding="utf-8"))

    def failures(self) -> List[Dict[str, Any]]:
        path = self.job_dir / "failures.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def page(self, url: str) -> Dict[str, Any]:
        return self.site.get(url, {})

    def run(self, *, resume_after_review: bool = False, **overrides: Any):
        config = dict(self.config, **overrides)
        runtime = category.build_runtime_config(config, SKILL_ROOT / "x.json", False, resume_after_review)
        fake_now = [1_000_000.0]
        runtime._amazon_page_retry_clock = lambda: fake_now[0]

        def wait(seconds: float) -> None:
            fake_now[0] += float(seconds)

        runtime._amazon_page_retry_waiter = wait
        harness = self

        def fake_load(driver, page_url, runtime_arg, **_kwargs):
            behaviour = harness.page(page_url).get("behaviour", "records")
            if behaviour == "verify":
                raise category.VerificationUnconfirmedError(
                    "amazon_robot_check_unconfirmed: 人工处理超时，任务已停止且未提取当前页数据。"
                )
            category.safety_before_remote_action(runtime_arg, "导航 Amazon 页面")
            harness.navigations.append(page_url)
            harness.current_url = page_url
            if behaviour == "transient":
                raise TransientAmazonPageUnavailable("dog page", reason="dog", url=page_url)
            return EMPTY if behaviour == "empty" else HEALTHY

        def fake_children(driver, node, strict=False):
            ids = harness.page(node["url"]).get("children") or []
            return [
                {
                    "url": child_url(node_id),
                    "name": f"C{node_id}",
                    "node_id": node_id,
                    "path": list(node.get("path") or []) + [f"C{node_id}"],
                    "depth": int(node.get("depth") or 0) + 1,
                }
                for node_id in ids
            ]

        def fake_records(driver, runtime_arg, node, page_number, plugin_status):
            digest = abs(hash((harness.current_url, page_number))) % 10**9
            return [{"asin": f"B{digest:09d}", "fulfillment_method": "FBA"}]

        def fake_next(driver, strict=False):
            return harness.page(harness.current_url).get("next", "")

        patches = [
            patch.object(category, "start_driver", return_value=DummyDriver()),
            patch.object(category, "load_category_page_attempt", side_effect=fake_load),
            patch.object(category, "extract_current_category_path", return_value=[]),
            patch.object(category, "discover_child_categories", side_effect=fake_children),
            patch.object(category, "wait_for_sellersprite_data_or_prompt", return_value="ok"),
            patch.object(category, "wait_for_category_page_health", return_value=HEALTHY),
            patch.object(category, "merge_product_data", side_effect=fake_records),
            patch.object(category, "find_next_page_url", side_effect=fake_next),
            patch.object(category, "write_workbook"),
            patch.object(category, "save_debug_snapshot"),
            patch("safety_control.time.sleep"),
            patch("amazon_category_rank_crawler.time.sleep"),
            patch("safety_control.default_safety_root", return_value=self.safety_root),
            patch("builtins.print"),
        ]
        for item in patches:
            item.start()
        try:
            return category.run_crawl(runtime, dry_run=False), None
        except Exception as exc:  # noqa: BLE001 - the tests assert on it
            return None, exc
        finally:
            for item in reversed(patches):
                item.stop()


class ReviewCompletionTests(unittest.TestCase):
    """C1: a review clears after any page work item finishes without a risk trip."""

    def write_pause(self, harness: LoopHarness) -> Path:
        past = (dt.datetime.now() - dt.timedelta(hours=1)).replace(microsecond=0).isoformat()
        pause = harness.safety_root / "risk-pause.json"
        pause.write_text(
            json.dumps(
                {
                    "active": True,
                    "platform": "amazon",
                    "reason": "captcha_or_robot_check",
                    "kind": "manual_review",
                    "not_before": past,
                    "work_key": "node:999|page:1|x",
                }
            ),
            encoding="utf-8",
        )
        return pause

    def test_intermediate_node_completes_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = LoopHarness(
                Path(temp_dir),
                {
                    START: {"children": ["2000001"]},
                    # The next item stops before any navigation, so only the
                    # intermediate root could have completed the review.
                    child_url("2000001"): {"behaviour": "verify"},
                },
            )
            pause = self.write_pause(harness)
            _rc, exc = harness.run(resume_after_review=True)
            self.assertIsInstance(exc, category.VerificationUnconfirmedError)
            self.assertEqual(harness.navigations, [START])
            self.assertFalse(pause.exists(), "risk pause must clear after the intermediate page")

    def test_verified_empty_page_completes_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = LoopHarness(Path(temp_dir), {START: {"behaviour": "empty"}})
            pause = self.write_pause(harness)
            rc, exc = harness.run(resume_after_review=True)
            self.assertIsNone(exc)
            self.assertEqual(rc, 0)
            self.assertFalse(pause.exists())


class DeferAndQuarantineTests(unittest.TestCase):
    """C2/C3/D2: deferred work goes last, two failed cycles quarantine an item."""

    def test_restore_deferred_appends_to_queue_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = SimpleNamespace(
                start_url=START,
                job_id="j",
                resume=False,
                delivery_location_fingerprint="d",
                record_contract_fingerprint="r",
                crawl_plan_fingerprint="p",
            )
            store = category.StateStore(Path(temp_dir) / "state.json", runtime)
            store.load_or_create()
            store.data["queue"] = [{"url": child_url("1")}]
            store.data["deferred_pages"] = [{"current": {"node": {"url": child_url("2")}}, "reason": "x"}]
            store.restore_deferred()
            self.assertEqual(store.data["queue"][0], {"url": child_url("1")})
            self.assertIn("_deferred_current", store.data["queue"][-1])

    def test_unattended_defer_then_quarantine_and_continue(self) -> None:
        bad = child_url("9000001")
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = LoopHarness(
                Path(temp_dir),
                {
                    START: {"children": ["9000001", "9100001", "9100002"]},
                    bad: {"behaviour": "transient"},
                },
                operation_mode="unattended",
            )
            # Run 1: the bad page is deferred, healthy pages are crawled, and
            # the run must not end as "completed".
            _rc, exc = harness.run()
            self.assertIsInstance(exc, run_outcome.CrawlStop)
            self.assertEqual(exc.exit_code, run_outcome.EXIT_RETRY_LATER)
            self.assertIn(child_url("9100001"), harness.navigations)
            self.assertIn(child_url("9100002"), harness.navigations)
            state = harness.state()
            self.assertEqual(len(state["deferred_pages"]), 1)
            self.assertEqual(list(state["item_failure_cycles"].values()), [1])

            # Run 2: retried at the end of the queue, fails again → quarantined.
            harness.navigations.clear()
            rc, exc = harness.run()
            self.assertIsNone(exc)
            self.assertEqual(rc, 0)
            self.assertEqual(set(harness.navigations), {bad})
            state = harness.state()
            self.assertFalse(state.get("deferred_pages"))
            self.assertEqual(len(state["skipped_items"]), 1)
            self.assertEqual(state["skipped_items"][0]["reason"], "quarantined_after_repeated_failures")
            reasons = [item["reason"] for item in harness.failures()]
            self.assertIn("quarantined_after_repeated_failures", reasons)

            # Run 3: the quarantined page is never re-queued.
            harness.navigations.clear()
            rc, exc = harness.run()
            self.assertIsNone(exc)
            self.assertEqual(harness.navigations, [])

    def test_supervised_retry_exhausted_first_cycle_retry_later_then_skip(self) -> None:
        bad = child_url("9000001")
        good = child_url("9100001")
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = LoopHarness(
                Path(temp_dir),
                {START: {"children": ["9000001", "9100001"]}, bad: {"behaviour": "transient"}},
            )
            _rc, exc = harness.run()
            self.assertIsInstance(exc, run_outcome.CrawlStop)
            self.assertEqual(exc.exit_code, run_outcome.EXIT_RETRY_LATER)
            self.assertNotIn(good, harness.navigations)
            self.assertEqual(harness.state()["current"]["node"]["url"], bad)

            harness.navigations.clear()
            rc, exc = harness.run()
            self.assertIsNone(exc)
            self.assertEqual(rc, 0)
            self.assertEqual(harness.navigations, [bad, bad, good])
            self.assertEqual(len(harness.state()["skipped_items"]), 1)
            self.assertEqual(category._state_skipped_count(harness.job_dir), 1)


class ScopeAndCapTests(unittest.TestCase):
    """D3/C4/C5/C6/C7."""

    def build(self, **config: Any) -> category.RuntimeConfig:
        base = {"start_url": START, "job_id": "caps", "delivery_location_enabled": False}
        base.update(config)
        return category.build_runtime_config(base, SKILL_ROOT / "x.json", False)

    def test_cap_defaults_apply_only_when_absent_or_empty(self) -> None:
        self.assertEqual((self.build().max_depth, self.build().max_pages_per_category), (3, 2))
        empty = self.build(max_depth="", max_pages_per_category="")
        self.assertEqual((empty.max_depth, empty.max_pages_per_category), (3, 2))
        explicit = self.build(max_depth=5, max_pages_per_category=7)
        self.assertEqual((explicit.max_depth, explicit.max_pages_per_category), (5, 7))
        unbounded = self.build(max_depth=None, max_pages_per_category=None)
        self.assertEqual((unbounded.max_depth, unbounded.max_pages_per_category), (None, None))

    def test_bsr_category_mode_always_includes_start_url(self) -> None:
        self.assertTrue(self.build(mode="bsr_category", include_root=False).include_root)
        self.assertFalse(self.build(include_root=False).include_root)

    def test_policy_keys_absent_still_builds(self) -> None:
        runtime = self.build()
        self.assertGreater(runtime.page_scroll_max_rounds, 0)
        self.assertEqual(runtime.amazon_page_retry_schedule, ((60.0, 60.0),))

    def test_include_root_crawls_root_and_recurses_within_depth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = LoopHarness(
                Path(temp_dir),
                {
                    START: {"children": ["2000001"]},
                    child_url("2000001"): {"children": ["3000001"]},
                },
                include_root=True,
                max_depth=1,
            )
            rc, exc = harness.run()
            self.assertIsNone(exc)
            self.assertEqual(rc, 0)
            # Root crawled, depth-1 child crawled, depth-2 grandchild never queued.
            self.assertEqual(harness.navigations, [START, child_url("2000001")])
            state = harness.state()
            self.assertEqual(len(state["completed_pages"]), 2)
            self.assertEqual(state["crawled_categories_count"], 2)

    def test_tightening_caps_on_progressed_job_keeps_job_and_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            page2 = START + "?pg=2"
            page3 = START + "?pg=3"
            harness = LoopHarness(
                Path(temp_dir),
                {START: {"next": page2}, page2: {"next": page3}, page3: {"behaviour": "verify"}},
                max_pages_per_category=3,
            )
            _rc, exc = harness.run()
            self.assertIsInstance(exc, category.VerificationUnconfirmedError)
            self.assertEqual(harness.state()["current"]["page_number"], 3)

            harness.navigations.clear()
            rc, exc = harness.run(max_pages_per_category=2)
            self.assertIsNone(exc, exc)
            self.assertEqual(rc, 0)
            self.assertEqual(harness.navigations, [])
            self.assertEqual(harness.state()["crawl_caps"]["max_pages_per_category"], 2)

            # Loosening afterwards is rejected as a config error.
            _rc, exc = harness.run(max_pages_per_category=5)
            self.assertIsInstance(exc, run_outcome.CrawlStop)
            self.assertEqual(exc.exit_code, run_outcome.EXIT_CONFIG_ERROR)

    def test_legacy_fingerprint_checkpoint_is_still_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = LoopHarness(Path(temp_dir), {START: {"children": ["2000001"]}}, include_root=True)
            harness.job_dir.mkdir(parents=True)
            legacy = category.legacy_crawl_plan_fingerprint(START, True, None, None, {})
            runtime = category.build_runtime_config(
                dict(harness.config, include_root=True, max_depth="", max_pages_per_category=""),
                SKILL_ROOT / "x.json",
                False,
            )
            store = category.StateStore(harness.job_dir / "state.json", runtime)
            store.data = store._new_data()
            store.data["crawl_plan_fingerprint"] = legacy
            store.data.pop("crawl_caps")
            store.data["done_categories"] = ["node:1"]
            store.flush()
            resumed = category.StateStore(harness.job_dir / "state.json", runtime)
            with patch("builtins.print"):
                resumed.load_or_create()
            self.assertEqual(resumed.data["crawl_plan_fingerprint"], runtime.crawl_plan_fingerprint)
            self.assertIn(legacy, resumed.data["crawl_plan_fingerprint_aliases"])
            self.assertEqual(resumed.data["done_categories"], ["node:1"])

    def test_max_categories_is_a_persisted_total_of_crawled_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = LoopHarness(
                Path(temp_dir),
                {START: {"children": ["2000001", "2000002", "2000003"]}},
                max_categories=1,
            )
            rc, exc = harness.run()
            self.assertIsNone(exc)
            self.assertEqual(rc, 0)
            # The skipped intermediate root does not count; one leaf is crawled.
            self.assertEqual(harness.navigations, [START, child_url("2000001")])
            harness.navigations.clear()
            harness.run()
            self.assertEqual(harness.navigations, [])
            harness.run(max_categories=2)
            self.assertEqual(harness.navigations, [child_url("2000002")])

    def test_root_without_children_sets_warning_flag_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = LoopHarness(Path(temp_dir), {START: {}})
            rc, exc = harness.run()
            self.assertIsNone(exc)
            self.assertTrue(harness.state()["children_discovery_zero"])
            summary = json.loads((harness.job_dir / "run_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["children_discovery_zero"])

    def test_repeated_next_url_stops_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            page2 = START + "?pg=2"
            harness = LoopHarness(
                Path(temp_dir),
                {START: {"next": page2}, page2: {"next": START}},
                max_pages_per_category=None,
            )
            rc, exc = harness.run()
            self.assertIsNone(exc)
            self.assertEqual(harness.navigations, [START, page2])

    def test_unbounded_pages_stop_at_safety_cap(self) -> None:
        runtime = SimpleNamespace(max_pages_per_category=None)
        current = {"seen_page_urls": []}
        reason = category.category_next_page_stop_reason(
            runtime, current, category.CATEGORY_HARD_PAGE_CAP, START, START + "?pg=99", None
        )
        self.assertEqual(reason, "page_cap")
        self.assertEqual(
            category.category_next_page_stop_reason(
                runtime, current, 1, START, "https://evil.example.com/next", None
            ),
            "cross_host_next_url",
        )


class ManualWaitTests(unittest.TestCase):
    """L8: manual waits poll the page, accept a CONTINUE file and never need stdin."""

    def tearDown(self) -> None:
        category.configure_manual_waits()

    def test_condition_poll_continues_without_stdin(self) -> None:
        calls = {"n": 0}

        def check() -> bool:
            calls["n"] += 1
            return calls["n"] >= 2

        beats: List[str] = []
        with patch("builtins.print"), patch.object(category, "_stdin_is_interactive", return_value=False):
            self.assertTrue(
                category.wait_for_manual_continue(
                    20,
                    check=check,
                    heartbeat=lambda phase, **_kw: beats.append(phase),
                    poll_seconds=0.5,
                )
            )
        self.assertEqual(calls["n"], 2)
        self.assertIn("manual_wait", beats)

    def test_continue_file_signal_is_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            signal = Path(temp_dir) / "CONTINUE"
            signal.write_text("", encoding="utf-8")
            category.configure_manual_waits(continue_file=signal)
            self.assertFalse(signal.exists(), "a stale signal from an earlier run is discarded")
            signal.write_text("", encoding="utf-8")
            with patch("builtins.print"), patch.object(category, "_stdin_is_interactive", return_value=False):
                self.assertTrue(category.wait_for_manual_continue(20))
            self.assertFalse(signal.exists())

    def test_timeout_and_windows_never_call_select(self) -> None:
        with (
            patch("builtins.print"),
            patch.object(category.os, "name", "nt"),
            patch.object(category.select, "select") as select_mock,
            patch.object(category.time, "sleep"),
        ):
            self.assertFalse(category.wait_for_manual_continue(0))
            self.assertFalse(category._stdin_is_interactive())
        select_mock.assert_not_called()

    def test_delivery_manual_wait_polls_delivery_condition(self) -> None:
        location = {"amazon.com": {"city": "New York", "postal_code": "10001", "strategy": "postal"}}
        runtime = SimpleNamespace(
            delivery_location_enabled=True,
            delivery_locations=location,
            delivery_location_fingerprint="f",
            delivery_location_timeout=1,
            operation_mode="supervised",
            manual_pause_timeout=30,
        )
        driver = SimpleNamespace(current_url="https://www.amazon.com/")
        confirmed = iter([False, True, True])

        def fake_wait(_remaining):
            check = category._MANUAL_WAIT_LOCAL.check
            self.assertIsNotNone(check)
            return bool(check())

        with (
            patch("builtins.print"),
            patch.object(category, "_attempt_delivery_value", return_value=False),
            patch.object(category, "delivery_location_is_confirmed", side_effect=lambda *_a: next(confirmed)),
            patch.object(category, "category_page_assessment", return_value=HEALTHY),
            patch.object(category, "wait_for_manual_continue", side_effect=fake_wait),
        ):
            category.ensure_amazon_delivery_location(driver, runtime, original_url=driver.current_url)

    def test_captcha_wait_polls_block_condition(self) -> None:
        # The polled condition sees the cleared page, then the post-wait check agrees.
        blocks = iter([None, None])

        def fake_wait(_remaining):
            return bool(category._MANUAL_WAIT_LOCAL.check())

        with (
            patch("builtins.print"),
            patch.object(category, "detect_block", side_effect=lambda *_a: next(blocks)),
            patch.object(category, "wait_for_manual_continue", side_effect=fake_wait),
        ):
            self.assertTrue(category.wait_for_manual_clear(SimpleNamespace(), "amazon_robot_check", 30))


class ScrollAndHeartbeatTests(unittest.TestCase):
    """W1 adaptive pre-scroll and plugin-wait heartbeat."""

    class ScrollDriver:
        def __init__(self, page_height: int, step: int = 800, viewport: int = 900) -> None:
            self.height = page_height
            self.step = step
            self.viewport = viewport
            self.top = 0
            self.calls = 0

        def execute_script(self, script: str, *args: Any) -> Any:
            if script.startswith("window.scrollTo"):
                self.top = 0
                return None
            self.calls += 1
            jump = bool(args[1]) if len(args) > 1 else False
            self.top = self.height if jump else min(self.top + self.step, self.height)
            cards = min(50, 3 + self.top // 300)
            return {
                "asinCount": cards,
                "pluginNodes": cards,
                "tableRows": 0,
                "scrollTop": self.top,
                "scrollHeight": self.height,
                "atBottom": self.top + self.viewport >= self.height - 20,
            }

    def runtime(self, wait: float = 2.0) -> SimpleNamespace:
        return SimpleNamespace(
            page_scroll_before_extract=True,
            page_scroll_max_rounds=18,
            page_scroll_step_ratio=0.85,
            page_scroll_wait_seconds=wait,
            page_scroll_stable_rounds=2,
            activate_plugin=False,
        )

    def test_typical_page_scroll_finishes_well_under_ten_seconds(self) -> None:
        driver = self.ScrollDriver(12_000)
        sleeps: List[float] = []
        with (
            patch("builtins.print"),
            patch.object(category, "detect_block", return_value=None),
            patch.object(category.time, "sleep", side_effect=sleeps.append),
        ):
            category.preload_page_data_with_scroll(driver, self.runtime())
        self.assertLess(sum(sleeps), 10.0)
        self.assertTrue(all(value <= 2.0 for value in sleeps))
        self.assertGreaterEqual(driver.top + driver.viewport, driver.height - 20)

    def test_tall_page_jumps_to_bottom_after_round_cap(self) -> None:
        driver = self.ScrollDriver(60_000)
        with (
            patch("builtins.print"),
            patch.object(category, "detect_block", return_value=None),
            patch.object(category.time, "sleep"),
        ):
            category.preload_page_data_with_scroll(driver, self.runtime())
        self.assertEqual(driver.top, driver.height)
        self.assertLessEqual(driver.calls, 18 + 2 + 2)

    def test_plugin_wait_writes_heartbeat(self) -> None:
        beats: List[str] = []
        safety = SimpleNamespace(heartbeat=lambda phase, **_kw: beats.append(phase))
        runtime = SimpleNamespace(
            sellersprite_required=True,
            activate_plugin=False,
            page_scroll_before_extract=False,
            plugin_timeout=40,
            sellersprite_stable_checks=1,
            operation_mode="supervised",
            safety=safety,
        )
        report = {"status": "ready_candidate", "signature": "s", "product_count": 1}
        with patch.object(category, "inspect_sellersprite_readiness", return_value=report):
            self.assertEqual(category.wait_for_sellersprite_data(SimpleNamespace(), runtime), "ok")
        self.assertIn("plugin_wait", beats)


class EntryPointTests(unittest.TestCase):
    """Exit-code contract for the category entry point."""

    def test_missing_config_is_config_error(self) -> None:
        with patch("builtins.print"):
            code = category.main(["--config", "/nonexistent/category.json", "--dry-run"])
        self.assertEqual(code, run_outcome.EXIT_CONFIG_ERROR)

    def test_invalid_config_is_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "c.json"
            config.write_text(json.dumps({"start_url": "https://example.com/"}), encoding="utf-8")
            with patch("builtins.print"):
                code = category.main(["--config", str(config), "--dry-run"])
        self.assertEqual(code, run_outcome.EXIT_CONFIG_ERROR)

    def test_valid_dry_run_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "c.json"
            config.write_text(
                json.dumps({"start_url": START, "outputs_root": temp_dir, "delivery_location_enabled": False}),
                encoding="utf-8",
            )
            with patch("builtins.print"):
                code = category.main(["--config", str(config), "--dry-run"])
        self.assertEqual(code, run_outcome.EXIT_COMPLETED)

    def test_manual_timeouts_map_to_needs_human(self) -> None:
        for exc in (
            category.VerificationUnconfirmedError(category.verification_unconfirmed_message("amazon_sign_in")),
            category.VerificationUnconfirmedError("sellersprite_verification_unconfirmed: x"),
            category.DeliveryLocationUnconfirmedError("delivery_location_unconfirmed: x"),
        ):
            outcome = run_outcome.classify_exception(category.categorize_crawl_exception(exc))
            self.assertEqual(outcome.exit_code, run_outcome.EXIT_NEEDS_HUMAN, exc)
            self.assertTrue(outcome.next_action)
        unsupported = category.DeliveryLocationUnconfirmedError("delivery_location_unsupported: x")
        self.assertEqual(
            run_outcome.classify_exception(category.categorize_crawl_exception(unsupported)).exit_code,
            run_outcome.EXIT_CONFIG_ERROR,
        )

    def test_job_label_is_set_before_lock(self) -> None:
        labels: List[str] = []

        def fake_acquire(controller) -> None:
            labels.append(controller.job_label)
            raise category.SafetyPausedError("held", kind="lock_held")

        runtime = SimpleNamespace(
            outputs_root=Path(tempfile.gettempdir()),
            job_id="label-job",
            batch_pause_pages_min=20,
            batch_pause_pages_max=20,
            batch_pause_seconds_min=180,
            batch_pause_seconds_max=300,
            operation_mode="supervised",
        )
        with patch.object(category.LocalSafetyController, "acquire", fake_acquire):
            with self.assertRaises(category.SafetyPausedError):
                category.run_crawl(runtime, dry_run=False)
        self.assertEqual(labels, ["label-job"])


def _jsdom_module() -> Optional[str]:
    """Path of a jsdom install for the optional DOM tests (LC_JSDOM_MODULE or global)."""

    if not shutil.which("node"):
        return None
    candidate = os.environ.get("LC_JSDOM_MODULE") or "jsdom"
    # Resolve to an absolute path: the runner script executes from a temp
    # directory where a cwd-relative node_modules would not be found.
    probe = subprocess.run(
        ["node", "-e", f"process.stdout.write(require.resolve({json.dumps(candidate)}))"],
        capture_output=True,
        text=True,
    )
    return probe.stdout.strip() or None if probe.returncode == 0 else None


JSDOM_MODULE = _jsdom_module()
JS_RUNNER = r"""
const { JSDOM } = require(process.env.JSDOM_MODULE);
let input = '';
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
  const { html, url, script, args } = JSON.parse(input);
  const dom = new JSDOM(html, { url, runScripts: 'outside-only', pretendToBeVisual: true });
  dom.window.__args = args || [];
  const result = dom.window.eval('(function(){' + script + '\n}).apply(null, window.__args)');
  process.stdout.write(JSON.stringify(result === undefined ? null : result));
});
"""


@unittest.skipUnless(JSDOM_MODULE, "node + jsdom unavailable (set LC_JSDOM_MODULE)")
class DomScriptTests(unittest.TestCase):
    """C6/C7/item 11 DOM scripts executed in jsdom."""

    def run_js(self, html: str, url: str, script: str, args: Optional[list] = None) -> Any:
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = Path(temp_dir) / "run.js"
            runner.write_text(JS_RUNNER, encoding="utf-8")
            out = subprocess.run(
                ["node", str(runner)],
                input=json.dumps({"html": html, "url": url, "script": script, "args": args or []}),
                capture_output=True,
                text=True,
                env=dict(os.environ, JSDOM_MODULE=str(JSDOM_MODULE)),
            )
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        return json.loads(out.stdout)

    def test_next_page_requires_pagination_controls(self) -> None:
        url = "https://www.amazon.com/gp/bestsellers/electronics/1234567/"
        zg = (
            '<ul class="a-pagination"><li class="a-last">'
            '<a href="/gp/bestsellers/electronics/1234567/ref=zg_bs_pg_2?pg=2">Next page</a></li></ul>'
        )
        self.assertTrue(self.run_js(zg, url, category.NEXT_PAGE_JS).endswith("pg=2"))
        disabled = (
            '<ul class="a-pagination"><li class="a-disabled a-last">Next page</li></ul>'
            '<a href="/dp/B0NEXTBASE">Nextbase 622GW Dash Cam next</a>'
            '<div class="a-carousel-container"><a href="/x?y=1">Next</a></div>'
        )
        self.assertEqual(self.run_js(disabled, url, category.NEXT_PAGE_JS), "")

    def test_amazon_nav_sprite_is_not_a_sellersprite_node(self) -> None:
        script = category.SELLERSPRITE_NODES_JS + "return sellerSpriteNodes().length;"
        amazon_only = '<div id="navbar"><span class="nav-sprite"></span><div class="cross-sell"></div></div>'
        self.assertEqual(self.run_js(amazon_only, START, script), 0)
        plugin = '<div id="seller-sprite-extension-root"><table class="vxe-table"></table></div>'
        self.assertEqual(self.run_js(plugin, START, script), 2)

    def test_child_discovery_does_not_walk_into_siblings(self) -> None:
        import inspect

        source = inspect.getsource(category.discover_child_categories)
        start = source.index('script = r"""') + len('script = r"""')
        script = source[start:source.index('"""', start)]
        root = "https://www.amazon.com/gp/bestsellers/home-garden/1063498/"
        nested = (
            '<div id="zg_browseRoot"><ul><li><span class="zg_selected">Home</span><ul>'
            '<li><a href="/gp/bestsellers/home-garden/2000001/">Bath</a></li></ul></li>'
            '<li><a href="/gp/bestsellers/home-garden/3000001/">Kitchen</a></li></ul></div>'
        )
        self.assertEqual([c["node_id"] for c in self.run_js(nested, root, script)], ["2000001"])
        siblings = (
            '<div id="zg_browseRoot"><ul><li><span class="zg_selected">Home</span></li>'
            '<li><a href="/gp/bestsellers/home-garden/3000001/">Kitchen</a></li></ul></div>'
        )
        self.assertEqual(self.run_js(siblings, root, script), [])


if __name__ == "__main__":
    unittest.main()
