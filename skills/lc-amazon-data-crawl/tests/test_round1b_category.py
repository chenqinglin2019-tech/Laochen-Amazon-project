"""Round-1b (review fixes) regression tests for the category crawler.

Covers review.md P1-1 (verified review probe), P1-2 (detect_block false
positives), P1-3 (failure reason/detail for the skip rule), P1-4 (bounded
SellerSprite prompt loop), P2-1 (per-item retry schedule), P2-2 (workbook
export never replaces the outcome), P2-11 (legacy bsr fingerprint), P2-14
(Ctrl+C), the category half of P2-13 (job-lock refusal) and the Windows
replace retry.  Offline: fake drivers, temp safety
root, fake clocks; no browser, network or real sleeping.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
TESTS_DIR = Path(__file__).resolve().parent
for _path in (SCRIPTS_DIR, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import amazon_category_rank_crawler as category  # noqa: E402
import run_outcome  # noqa: E402
from amazon_page_recovery import (  # noqa: E402
    AmazonPageRetryExhausted,
    PageHealthAssessment,
    PageHealthStatus,
    TransientAmazonPageUnavailable,
)
from safety_control import LocalSafetyController, SafetyPausedError  # noqa: E402
from selenium.common.exceptions import WebDriverException  # noqa: E402
from test_round1_category import START, LoopHarness, child_url  # noqa: E402


HEALTHY = PageHealthAssessment(PageHealthStatus.HEALTHY, "ok", "search_category")
EMPTY = PageHealthAssessment(PageHealthStatus.VERIFIED_EMPTY, "explicit_empty", "search_category")
LISTING_FILLER = " ".join(
    f"Puzzle Book Volume {index} for Adults $9.99 4.5 out of 5 stars" for index in range(80)
)
HEALTHY_BODY = "Best Sellers in Home & Kitchen " + LISTING_FILLER


class Element:
    def __init__(self, text: str) -> None:
        self.text = text


class PageDriver:
    """Minimal WebDriver stand-in: title, body text, URL, HTTP status, DOM probe."""

    def __init__(
        self,
        *,
        title: str = "Amazon.com",
        body: str = "",
        url: str = START,
        status: Optional[int] = 200,
        dom: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.title = title
        self.body = body
        self.current_url = url
        self.last_http_status = status
        self.last_retry_after = ""
        self.dom = dom
        self.window_handles: List[str] = ["main"]
        self.current_window_handle = "main"

    def find_element(self, *_args: Any) -> Element:
        return Element(self.body)

    def execute_script(self, script: str, *_args: Any) -> Any:
        if script == category.BLOCK_PAGE_DOM_JS and self.dom is not None:
            return dict(self.dom)
        return None

    def quit(self) -> None:
        pass


def write_pause(root: Path, *, kind: str = "manual_review", platform: str = "amazon", reason: str = "http_403") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    past = (dt.datetime.now() - dt.timedelta(hours=1)).replace(microsecond=0).isoformat()
    pause = root / "risk-pause.json"
    pause.write_text(
        json.dumps({"active": True, "platform": platform, "reason": reason, "kind": kind, "not_before": past}),
        encoding="utf-8",
    )
    return pause


def review_controller(root: Path, *, mode: str = "supervised", kind: str = "manual_review") -> LocalSafetyController:
    write_pause(root, kind=kind)
    safety = LocalSafetyController(root, mode=mode, batch_pause_pages_min=1000, batch_pause_pages_max=1000)
    safety.begin(resume_after_review=True)
    return safety


class PageSiteHarness(LoopHarness):
    """Drives run_crawl through the REAL load_category_page_attempt.

    Navigation, observe_amazon_risk and handle_amazon_verification run for
    real against a PageDriver; only DOM-heavy helpers are patched.

    Behaviours per URL:
      records (default) | empty | nav_error (driver.get raises) |
      nav_error_once | blank (loads, no title/body) | http_503 |
      missing / missing_once (loads and passes the risk check, then the
      content check fails always / once)
    """

    def __init__(self, tmp: Path, site: Dict[str, Dict[str, Any]], **config: Any) -> None:
        super().__init__(tmp, site, **config)
        self.gets: Dict[str, int] = {}
        self.health_checks: Dict[str, int] = {}
        self.workbook_error: Optional[BaseException] = None
        self.driver = PageDriver()

    def run(self, *, resume_after_review: bool = False, **overrides: Any):
        config = dict(self.config, **overrides)
        runtime = category.build_runtime_config(config, SKILL_ROOT / "x.json", False, resume_after_review)
        fake_now = [1_000_000.0]
        runtime._amazon_page_retry_clock = lambda: fake_now[0]

        def wait(seconds: float) -> None:
            fake_now[0] += float(seconds)

        runtime._amazon_page_retry_waiter = wait
        harness = self
        driver = self.driver

        def fake_get(url: str) -> None:
            count = harness.gets.get(url, 0) + 1
            harness.gets[url] = count
            behaviour = harness.page(url).get("behaviour", "records")
            harness.navigations.append(url)
            harness.current_url = url
            driver.current_url = url
            if behaviour == "nav_error" or (behaviour == "nav_error_once" and count == 1):
                raise WebDriverException("unknown error: net::ERR_CONNECTION_RESET")
            driver.last_http_status = 503 if behaviour == "http_503" else 200
            if behaviour == "blank":
                driver.title, driver.body = "", ""
            elif behaviour == "http_503":
                driver.title, driver.body = "Service Unavailable", "Service Unavailable"
            else:
                driver.title, driver.body = "Amazon Best Sellers", HEALTHY_BODY

        driver.get = fake_get  # type: ignore[attr-defined]

        def fake_assessment(_driver, *, navigation_error: str = "") -> PageHealthAssessment:
            if navigation_error:
                return PageHealthAssessment(
                    PageHealthStatus.TRANSIENT_UNAVAILABLE, "navigation_error", "search_category"
                )
            return HEALTHY

        def fake_health(_driver, _runtime, *_args, **_kwargs) -> PageHealthAssessment:
            url = harness.current_url
            behaviour = harness.page(url).get("behaviour", "records")
            count = harness.health_checks.get(url, 0) + 1
            harness.health_checks[url] = count
            if behaviour == "blank":
                raise TransientAmazonPageUnavailable("blank_page", reason="blank_page", url=url)
            if behaviour == "http_503":
                raise TransientAmazonPageUnavailable("http_503", reason="http_503", url=url)
            if behaviour == "missing" or (behaviour == "missing_once" and harness.gets.get(url, 0) == 1):
                raise TransientAmazonPageUnavailable(
                    "expected_content_missing", reason="expected_content_missing", url=url
                )
            return EMPTY if behaviour == "empty" else HEALTHY

        def fake_children(_driver, node, strict=False):
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

        def fake_records(_driver, _runtime, _node, page_number, _status):
            digest = abs(hash((harness.current_url, page_number))) % 10**9
            return [{"asin": f"B{digest:09d}", "fulfillment_method": "FBA"}]

        def fake_next(_driver, strict=False):
            return harness.page(harness.current_url).get("next", "")

        def fake_workbook(*_args, **_kwargs) -> None:
            if harness.workbook_error is not None:
                raise harness.workbook_error

        patches = [
            patch.object(category, "start_driver", return_value=driver),
            patch.object(category, "category_page_assessment", side_effect=fake_assessment),
            patch.object(category, "wait_for_category_page_health", side_effect=fake_health),
            patch.object(category, "ensure_amazon_delivery_location"),
            patch.object(category, "extract_current_category_path", return_value=[]),
            patch.object(category, "discover_child_categories", side_effect=fake_children),
            patch.object(category, "wait_for_sellersprite_data_or_prompt", return_value="ok"),
            patch.object(category, "merge_product_data", side_effect=fake_records),
            patch.object(category, "find_next_page_url", side_effect=fake_next),
            patch.object(category, "write_workbook", side_effect=fake_workbook),
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


# ---------------------------------------------------------------- P1-2 ----


class DetectBlockTests(unittest.TestCase):
    """detect_block: prose markers count only on short pages without product DOM."""

    def test_long_listing_with_captcha_products_is_not_a_block(self) -> None:
        body = LISTING_FILLER + " Captcha Puzzle Book: 200 Brain Teasers $7.99 Robot Check Toy " + LISTING_FILLER
        self.assertGreater(len(body), category.RISK_BODY_MAX_CHARS)
        driver = PageDriver(title="Amazon.com : captcha puzzle book", body=body, url="https://www.amazon.com/s?k=captcha")
        self.assertIsNone(category.detect_block(driver))
        # The SellerSprite plugin brand on the page does not make it a plugin check either.
        driver.body = body + " 卖家精灵 BSR 月销量 "
        self.assertIsNone(category.detect_block(driver))

    def test_short_page_with_product_dom_is_not_a_block(self) -> None:
        driver = PageDriver(
            title="Amazon.com : captcha t shirt",
            body="1 result for captcha t shirt  Captcha T-Shirt $14.99",
            dom={"product_dom": True, "captcha_form": False, "captcha_input": False, "plugin_text": ""},
        )
        self.assertIsNone(category.detect_block(driver))

    def test_classic_short_captcha_page_is_detected(self) -> None:
        driver = PageDriver(
            title="Amazon.com",
            body="Enter the characters you see below Sorry, we just need to make sure you're not a robot.",
            url="https://www.amazon.com/s?k=lamp",
        )
        self.assertEqual(category.detect_block(driver), "amazon_robot_check")

    def test_dom_url_and_exact_title_evidence_win_on_long_pages(self) -> None:
        long_body = "Click the button below to continue shopping " + LISTING_FILLER
        form = PageDriver(body=long_body, dom={"captcha_form": True})
        self.assertEqual(category.detect_block(form), "amazon_robot_check")
        field = PageDriver(body=long_body, dom={"captcha_input": True, "product_dom": True})
        self.assertEqual(category.detect_block(field), "amazon_robot_check")
        url = PageDriver(body=long_body, url="https://www.amazon.com/errors/validateCaptcha?x=1")
        self.assertEqual(category.detect_block(url), "amazon_robot_check")
        title = PageDriver(title="Robot Check", body=long_body)
        self.assertEqual(category.detect_block(title), "amazon_robot_check")

    def test_plugin_owned_verification_text_counts_on_any_page(self) -> None:
        driver = PageDriver(
            body=HEALTHY_BODY,
            dom={"product_dom": True, "plugin_text": "卖家精灵 Slide to verify 请完成验证"},
        )
        self.assertEqual(category.detect_block(driver), "sellersprite_verification")
        # A product title inside the plugin table is not a verification.
        driver.dom = {"product_dom": True, "plugin_text": "卖家精灵 Captcha Puzzle Book BSR 1,234"}
        self.assertIsNone(category.detect_block(driver))
        short = PageDriver(title="", body="卖家精灵 robot check")
        self.assertEqual(category.detect_block(short), "sellersprite_verification")

    def test_sign_in_stays_url_gated(self) -> None:
        signin = PageDriver(title="Amazon Sign-In", body="Sign in Email or mobile phone number", url="https://www.amazon.com/ap/signin?x")
        self.assertEqual(category.detect_block(signin), "amazon_sign_in")
        nav = PageDriver(title="Amazon.com", body="Hello, sign in Account & Lists Returns", url=START)
        self.assertIsNone(category.detect_block(nav))

    def test_odd_execute_script_results_are_ignored(self) -> None:
        driver = PageDriver(body=HEALTHY_BODY)
        driver.execute_script = lambda *_a: ["not", "a", "dict"]  # type: ignore[assignment]
        self.assertIsNone(category.detect_block(driver))

        def boom(*_args: Any) -> Any:
            raise WebDriverException("no such window")

        driver.execute_script = boom  # type: ignore[assignment]
        self.assertIsNone(category.detect_block(driver))

    def test_unattended_listing_with_captcha_title_never_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch("safety_control.time.sleep"):
            root = Path(temp_dir)
            safety = LocalSafetyController(root, mode="unattended")
            runtime = SimpleNamespace(safety=safety, operation_mode="unattended", manual_pause_timeout=30)
            driver = PageDriver(
                title="Amazon.com : captcha puzzle book",
                body=LISTING_FILLER + " CAPTCHA Puzzle Book " + LISTING_FILLER,
            )
            category.observe_amazon_risk(driver, runtime)
            category.handle_amazon_verification(driver, runtime)
            self.assertFalse(safety.pause_path.exists())


# ---------------------------------------------------------------- P1-1 ----


class RiskCheckedProbeTests(unittest.TestCase):
    """observe_amazon_risk verifies a review probe only on a loaded, clean page."""

    def setUp(self) -> None:
        self._sleep = patch("safety_control.time.sleep")
        self._sleep.start()
        self._print = patch("builtins.print")
        self._print.start()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._print.stop()
        self._sleep.stop()
        self._tmp.cleanup()

    def probe(self, driver: PageDriver, *, mode: str = "supervised") -> LocalSafetyController:
        safety = review_controller(self.root, mode=mode)
        safety.before_remote_action("导航 Amazon 页面")
        category.observe_amazon_risk(driver, SimpleNamespace(safety=safety))
        return safety

    def test_clean_loaded_page_verifies_and_next_action_clears_pause(self) -> None:
        safety = self.probe(PageDriver(title="Amazon Best Sellers", body=HEALTHY_BODY))
        safety.before_remote_action("下一个页面")
        self.assertFalse(safety.pause_path.exists())

    def test_long_page_titled_access_denied_sign_verifies(self) -> None:
        driver = PageDriver(
            title="Amazon.com : access denied sign",
            body="1-48 of over 2,000 results for access denied sign " + LISTING_FILLER,
        )
        safety = self.probe(driver, mode="unattended")
        safety.before_remote_action("下一个页面")
        self.assertFalse(safety.pause_path.exists())

    def assert_not_verified(self, driver: PageDriver, *, mode: str = "supervised") -> None:
        safety = self.probe(driver, mode=mode)
        with self.assertRaises(SafetyPausedError) as caught:
            safety.before_remote_action("重试 / 下一个页面")
        self.assertEqual(caught.exception.kind, "risk_pause")
        self.assertTrue(safety.pause_path.exists())

    def test_blank_page_does_not_verify(self) -> None:
        self.assert_not_verified(PageDriver(title="", body=""))

    def test_5xx_page_does_not_verify(self) -> None:
        self.assert_not_verified(PageDriver(title="Service Unavailable", body="Service Unavailable", status=503))

    def test_supervised_captcha_page_does_not_verify(self) -> None:
        self.assert_not_verified(
            PageDriver(
                title="Amazon.com",
                body="Enter the characters you see below Sorry, we just need to make sure you're not a robot.",
            )
        )

    def test_verification_page_without_risk_marker_does_not_verify(self) -> None:
        # No classify_amazon_risk marker, but detect_block sees the CAPTCHA form.
        for mode in ("supervised", "unattended"):
            with self.subTest(mode=mode):
                self.assert_not_verified(
                    PageDriver(title="Amazon.com", body="Type the characters you see in this image", dom={"captcha_form": True}),
                    mode=mode,
                )

    def test_page_cleared_by_the_user_is_risk_checked(self) -> None:
        safety = review_controller(self.root)
        safety.before_remote_action("导航 Amazon 页面")
        driver = PageDriver(title="Amazon Best Sellers", body=HEALTHY_BODY)
        runtime = SimpleNamespace(safety=safety, operation_mode="supervised", manual_pause_timeout=30)
        # The CAPTCHA is shown first; after the user solved it the page is clean.
        blocks = iter(["amazon_robot_check"])
        with patch.object(category, "detect_block", side_effect=lambda _d: next(blocks, None)), patch.object(
            category, "wait_for_manual_clear", return_value=True
        ), patch.object(safety, "captcha_cleared") as cleared:
            category.handle_amazon_verification(driver, runtime)
        cleared.assert_called_once()
        safety.before_remote_action("下一个页面")
        self.assertFalse(safety.pause_path.exists())


class ReviewProbeLoopTests(unittest.TestCase):
    """The real category loop keeps the pause unless a probe page passed the check."""

    def run_review(self, behaviour: str, **site: Any):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        harness = PageSiteHarness(Path(temp.name), {START: {"behaviour": behaviour, **site}})
        pause = write_pause(harness.safety_root)
        rc, exc = harness.run(resume_after_review=True)
        return harness, pause, rc, exc

    def test_probe_navigation_errors_keep_pause_and_stop(self) -> None:
        harness, pause, _rc, exc = self.run_review("nav_error")
        self.assertIsInstance(exc, SafetyPausedError)
        self.assertEqual(run_outcome.classify_exception(exc).exit_code, run_outcome.EXIT_RISK_PAUSE)
        self.assertEqual(harness.navigations, [START], "the retry must not navigate")
        self.assertTrue(pause.exists())
        self.assertFalse(json.loads(pause.read_text(encoding="utf-8")).get("review_attempt_pending"))

    def test_blank_or_5xx_probe_keeps_pause(self) -> None:
        for behaviour in ("blank", "http_503"):
            with self.subTest(behaviour=behaviour):
                harness, pause, _rc, exc = self.run_review(behaviour)
                self.assertIsInstance(exc, SafetyPausedError)
                self.assertEqual(harness.navigations, [START])
                self.assertTrue(pause.exists())

    def test_verified_probe_may_retry_its_page_and_clears_pause(self) -> None:
        harness, pause, rc, exc = self.run_review("missing_once")
        self.assertIsNone(exc)
        self.assertEqual(rc, 0)
        self.assertEqual(harness.navigations, [START, START])
        self.assertFalse(pause.exists())

    def test_healthy_probe_continues_to_the_next_items(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        harness = PageSiteHarness(
            Path(temp.name),
            {START: {"children": ["2000001", "2000002"]}},
        )
        pause = write_pause(harness.safety_root)
        rc, exc = harness.run(resume_after_review=True)
        self.assertIsNone(exc)
        self.assertEqual(rc, 0)
        self.assertEqual(harness.navigations, [START, child_url("2000001"), child_url("2000002")])
        self.assertFalse(pause.exists())


# ---------------------------------------------------------------- P1-3 ----


class FailureDetailTests(unittest.TestCase):
    """fail_item passes the underlying reason/detail so outages are not item failures."""

    def exhausted(self, reason: str, message: str) -> AmazonPageRetryExhausted:
        last = TransientAmazonPageUnavailable(message, reason=reason, url=START)
        return AmazonPageRetryExhausted({"error": message, "status": "manual_resume_required"}, last)

    def test_retry_exhausted_uses_last_error(self) -> None:
        reason, detail = category.item_failure_details(
            self.exhausted("navigation_error", "unknown error: net::ERR_INTERNET_DISCONNECTED"),
            AmazonPageRetryExhausted.failure_code,
        )
        self.assertEqual(reason, "navigation_error")
        self.assertIn("net::ERR_INTERNET_DISCONNECTED", detail)
        self.assertTrue(run_outcome.is_environment_failure(f"{reason} {detail}"))

        reason, detail = category.item_failure_details(self.exhausted("amazon_dog_error", "amazon_dog_error"))
        self.assertEqual(reason, "amazon_dog_error")
        self.assertFalse(run_outcome.is_environment_failure(f"{reason} {detail}"))

    def test_plugin_timeout_is_environment(self) -> None:
        reason, detail = category.item_failure_details(
            category.PluginDataTimeout("卖家精灵字段等待到期"), "plugin_data_timeout"
        )
        self.assertEqual(reason, "plugin_data_timeout")
        self.assertTrue(run_outcome.is_environment_failure(f"{reason} {detail}"))

    def test_network_outage_is_not_skipped_on_the_second_run(self) -> None:
        bad = child_url("9000001")
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = PageSiteHarness(
                Path(temp_dir),
                {START: {"children": ["9000001", "9100001"]}, bad: {"behaviour": "nav_error"}},
            )
            for run_number in (1, 2):
                _rc, exc = harness.run()
                self.assertIsInstance(exc, run_outcome.CrawlStop, f"run {run_number}")
                self.assertEqual(exc.exit_code, run_outcome.EXIT_RETRY_LATER)
                state = harness.state()
                self.assertTrue(state.get("last_failure_environment"))
                self.assertFalse(state.get("skipped_items"), f"run {run_number} must not skip")
                self.assertEqual(state["current"]["node"]["url"], bad)
            self.assertEqual(state["item_failure_meta"][next(iter(state["item_failure_meta"]))]["environment_runs"], 2)
            # The run summary tells the agent to wait before rerunning.
            run_outcome.finalize_run(harness.job_dir, run_outcome.classify_exception(exc))
            summary = json.loads((harness.job_dir / "run_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "retry_later")
            self.assertTrue(summary["resume_at"])

    def test_item_failure_is_still_skipped_on_the_second_run(self) -> None:
        bad = child_url("9000001")
        good = child_url("9100001")
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = PageSiteHarness(
                Path(temp_dir),
                {START: {"children": ["9000001", "9100001"]}, bad: {"behaviour": "missing"}},
            )
            _rc, exc = harness.run()
            self.assertEqual(exc.exit_code, run_outcome.EXIT_RETRY_LATER)
            self.assertFalse(harness.state().get("last_failure_environment"))
            rc, exc = harness.run()
            self.assertIsNone(exc)
            self.assertEqual(rc, 0)
            self.assertIn(good, harness.navigations)
            self.assertEqual(len(harness.state()["skipped_items"]), 1)


# ---------------------------------------------------------------- P1-4 ----


class PluginPromptLoopTests(unittest.TestCase):
    """wait_for_sellersprite_data_or_prompt is bounded per page."""

    def run_prompt(
        self,
        *,
        status: str = "data_loading",
        manual_results: Optional[List[Any]] = None,
        manual_seconds: float = 5.0,
        data_seconds: float = 80.0,
        timeout: int = 900,
    ):
        clock = [10_000.0]
        calls: Dict[str, List[Any]] = {"data": [], "manual": []}
        results = list(manual_results or [])

        def fake_data(_driver, _runtime, timeout_seconds=None, stop_event=None):
            calls["data"].append(clock[0])
            if len(calls["data"]) > 50:
                raise AssertionError("prompt loop is unbounded")
            clock[0] += data_seconds
            return "data_loading"

        def fake_manual(_driver, _reason, before_refresh=None, manual_pause_timeout=900, stop_event=None, check=None):
            calls["manual"].append(manual_pause_timeout)
            clock[0] += manual_seconds
            result = results.pop(0) if results else "check"
            if result == "check":
                return bool(check and check())
            return bool(result)

        runtime = SimpleNamespace(sellersprite_required=True, operation_mode="supervised", manual_pause_timeout=timeout)
        with patch.object(category, "wait_for_sellersprite_data", side_effect=fake_data), patch.object(
            category, "get_sellersprite_readiness", return_value={"status": status}
        ), patch.object(
            category, "inspect_sellersprite_readiness", return_value={"status": "ready_candidate"}
        ), patch.object(category, "plugin_node_count", return_value=1), patch.object(
            category, "sellersprite_login_required", return_value=False
        ), patch.object(category, "category_page_assessment", return_value=HEALTHY), patch.object(
            category, "wait_for_amazon_products"
        ), patch.object(category, "wait_for_user_plugin_action", side_effect=fake_manual), patch.object(
            category, "time", SimpleNamespace(time=lambda: clock[0], sleep=lambda _s: None)
        ), patch("builtins.print"):
            result = category.wait_for_sellersprite_data_or_prompt(PageDriver(), runtime)
        return result, calls

    def test_ready_candidate_auto_continue_happens_once_then_timeout(self) -> None:
        result, calls = self.run_prompt()
        self.assertEqual(result, "timeout")
        self.assertEqual(len(calls["data"]), 2)
        self.assertEqual(len(calls["manual"]), 1)

    def test_user_continues_share_one_budget(self) -> None:
        # The user keeps continuing (CONTINUE file) without the fields settling.
        result, calls = self.run_prompt(manual_results=[True] * 10, manual_seconds=400.0)
        self.assertEqual(result, "timeout")
        self.assertEqual(calls["manual"], [900, 420])

    def test_manual_timeout_maps_by_cause(self) -> None:
        result, _calls = self.run_prompt(status="data_loading", manual_results=[False])
        self.assertEqual(result, "timeout")
        result, _calls = self.run_prompt(status="plugin_absent", manual_results=[False])
        self.assertEqual(result, "blocked")

    def test_plugin_absent_after_budget_needs_the_user(self) -> None:
        result, calls = self.run_prompt(status="plugin_absent", manual_seconds=500.0)
        self.assertEqual(result, "blocked")
        self.assertLessEqual(len(calls["manual"]), 2)


# ---------------------------------------------------------------- P2-1 ----


class RateProbeScheduleTests(unittest.TestCase):
    """Only the rate-probe item itself runs without retries."""

    def test_schedule_returns_after_probe_passed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            p2 = START + "?pg=2"
            harness = PageSiteHarness(
                Path(temp_dir),
                {START: {"next": p2}, p2: {"behaviour": "nav_error_once"}},
            )
            write_pause(harness.safety_root, kind="rate_probe", reason="http_429")
            rc, exc = harness.run()
            self.assertIsNone(exc)
            self.assertEqual(rc, 0)
            self.assertEqual(harness.navigations, [START, p2, p2])
            self.assertFalse(harness.state().get("item_failure_cycles"))
            self.assertFalse((harness.safety_root / "risk-pause.json").exists())

    def test_probe_item_itself_has_one_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = PageSiteHarness(Path(temp_dir), {START: {"behaviour": "nav_error"}})
            pause = write_pause(harness.safety_root, kind="rate_probe", reason="http_429")
            _rc, exc = harness.run()
            self.assertIsInstance(exc, run_outcome.CrawlStop)
            self.assertEqual(exc.exit_code, run_outcome.EXIT_RETRY_LATER)
            self.assertEqual(harness.navigations, [START])
            self.assertTrue(pause.exists())

    def test_effective_schedule_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch("safety_control.time.sleep"), patch("builtins.print"):
            root = Path(temp_dir)
            configured = ((60.0, 60.0),)
            self.assertEqual(
                category.effective_amazon_page_retry_schedule(SimpleNamespace(amazon_page_retry_schedule=configured)),
                configured,
            )
            safety = review_controller(root, kind="rate_probe")
            runtime = SimpleNamespace(safety=safety, amazon_page_retry_schedule=configured)
            self.assertEqual(category.effective_amazon_page_retry_schedule(runtime), ())
            safety.complete_review_success()
            self.assertEqual(category.effective_amazon_page_retry_schedule(runtime), configured)
            self.assertEqual(runtime.amazon_page_retry_schedule, configured)


# ---------------------------------------------------------------- P2-2 ----


class WorkbookExportTests(unittest.TestCase):
    """A workbook export error never replaces the run's own outcome."""

    def test_deferred_run_keeps_retry_later(self) -> None:
        bad = child_url("9000001")
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = PageSiteHarness(
                Path(temp_dir),
                {START: {"children": ["9000001", "9100001"]}, bad: {"behaviour": "nav_error"}},
                operation_mode="unattended",
            )
            harness.workbook_error = PermissionError(13, "Permission denied", "total_loop_merged.xlsx")
            _rc, exc = harness.run()
            self.assertIsInstance(exc, run_outcome.CrawlStop)
            self.assertEqual(exc.exit_code, run_outcome.EXIT_RETRY_LATER)

    def test_completed_run_with_locked_workbook_asks_to_close_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = PageSiteHarness(Path(temp_dir), {START: {}})
            harness.workbook_error = PermissionError(13, "Permission denied", "total_loop_merged.xlsx")
            _rc, exc = harness.run()
            self.assertIsInstance(exc, run_outcome.CrawlStop)
            self.assertEqual(exc.exit_code, run_outcome.EXIT_NEEDS_HUMAN)
            self.assertIn("请关闭表格后重新运行", exc.next_action)
            self.assertIsInstance(exc.__cause__, PermissionError)
            # Rerunning after closing the workbook only re-exports.
            harness.workbook_error = None
            harness.navigations.clear()
            rc, exc = harness.run()
            self.assertIsNone(exc)
            self.assertEqual(rc, 0)
            self.assertEqual(harness.navigations, [])

    def test_export_helper_prints_hint_and_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            job = Path(temp_dir)
            stderr = io.StringIO()
            error = PermissionError(13, "Permission denied")
            with patch.object(category, "write_workbook", side_effect=error), patch.object(
                category, "write_quality_report"
            ), contextlib.redirect_stderr(stderr):
                result = category.export_category_outputs(job / "r.jsonl", job / "f.jsonl", job / "o.xlsx", job)
            self.assertIs(result, error)
            self.assertIn("请关闭表格后重新运行", stderr.getvalue())


# ---------------------------------------------------------------- P2-11 ---


class LegacyBsrFingerprintTests(unittest.TestCase):
    def test_pre_d3_bsr_checkpoint_resumes(self) -> None:
        start = "https://www.amazon.com/gp/bestsellers/home-garden/1063238/"
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp = Path(temp_dir)
            config = {
                "mode": "bsr_category",
                "start_url": start,
                "job_id": "old",
                "outputs_root": str(tmp),
                "delivery_location_enabled": False,
            }
            runtime = category.build_runtime_config(dict(config), SKILL_ROOT / "x.json", False, False)
            self.assertTrue(runtime.include_root)
            old_fp = category.legacy_crawl_plan_fingerprint(start, False, None, None, runtime.field_selectors)
            self.assertIn(old_fp, runtime.crawl_plan_legacy_caps)
            job = tmp / "old"
            job.mkdir()
            (job / "state.json").write_text(
                json.dumps(
                    {
                        "state_version": 2,
                        "queue": [{"url": child_url("2000001"), "name": "C", "path": ["C"], "depth": 1}],
                        "current": None,
                        "done_categories": [start],
                        "completed_pages": [],
                        "processed_categories_count": 1,
                        "delivery_location_fingerprint": runtime.delivery_location_fingerprint,
                        "record_contract_fingerprint": runtime.record_contract_fingerprint,
                        "crawl_plan_fingerprint": old_fp,
                    }
                ),
                encoding="utf-8",
            )
            with patch("builtins.print"):
                store = category.StateStore(job / "state.json", runtime)
                store.load_or_create()
            self.assertEqual(store.data["crawl_plan_fingerprint"], runtime.crawl_plan_fingerprint)
            self.assertIn(old_fp, store.data["crawl_plan_fingerprint_aliases"])

    def test_non_bsr_jobs_get_no_extra_include_root_alias(self) -> None:
        runtime = category.build_runtime_config(
            {"start_url": START, "job_id": "x", "delivery_location_enabled": False},
            SKILL_ROOT / "x.json",
            False,
            False,
        )
        other = category.legacy_crawl_plan_fingerprint(START, True, None, None, runtime.field_selectors)
        self.assertNotIn(other, runtime.crawl_plan_legacy_caps)


# ---------------------------------------------------------------- P2-14 ---


class CtrlCTests(unittest.TestCase):
    def test_ctrl_c_is_retry_later(self) -> None:
        stop = category.categorize_crawl_exception(KeyboardInterrupt())
        self.assertIsInstance(stop, run_outcome.CrawlStop)
        self.assertEqual(stop.exit_code, run_outcome.EXIT_RETRY_LATER)

    def test_main_exits_20_on_ctrl_c(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp = Path(temp_dir)
            config_path = tmp / "cfg.json"
            config_path.write_text(
                json.dumps(
                    {
                        "start_url": START,
                        "job_id": "kb",
                        "outputs_root": str(tmp / "out"),
                        "delivery_location_enabled": False,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(category, "run_crawl", side_effect=KeyboardInterrupt()), patch(
                "builtins.print"
            ):
                code = category.main(["--config", str(config_path)])
            self.assertEqual(code, run_outcome.EXIT_RETRY_LATER)
            summary = json.loads((tmp / "out" / "kb" / "run_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "retry_later")


# ---------------------------------------------------------- P2-13 --------


class JobLockRefusalTests(unittest.TestCase):
    """A refused job lock never touches the holder's run_summary / heartbeat."""

    def test_refused_job_lock_keeps_holder_summary_and_exits_50(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp = Path(temp_dir)
            job_dir = tmp / "out" / "held"
            job_dir.mkdir(parents=True)
            holder_summary = {"status": "running", "holder": True}
            (job_dir / "run_summary.json").write_text(json.dumps(holder_summary), encoding="utf-8")
            (job_dir / "run_heartbeat.json").write_text(json.dumps({"phase": "navigating"}), encoding="utf-8")
            config_path = tmp / "cfg.json"
            config_path.write_text(
                json.dumps(
                    {
                        "start_url": START,
                        "job_id": "held",
                        "outputs_root": str(tmp / "out"),
                        "delivery_location_enabled": False,
                    }
                ),
                encoding="utf-8",
            )
            holder = category.JobRunLock(job_dir / ".run.lock")
            holder.acquire()
            try:
                with patch("safety_control.default_safety_root", return_value=tmp / "safety"), patch.object(
                    category, "_run_crawl_unlocked"
                ) as unlocked, patch("builtins.print"):
                    code = category.main(["--config", str(config_path)])
            finally:
                holder.release()
            unlocked.assert_not_called()
            self.assertEqual(code, run_outcome.EXIT_LOCK_HELD)
            self.assertEqual(json.loads((job_dir / "run_summary.json").read_text(encoding="utf-8")), holder_summary)
            self.assertEqual(
                json.loads((job_dir / "run_heartbeat.json").read_text(encoding="utf-8")), {"phase": "navigating"}
            )

    def test_refusal_is_still_a_user_facing_error_for_front(self) -> None:
        # Front's bsr path recognises the refusal by type + message.
        self.assertTrue(issubclass(category.JobLockHeldError, category.UserFacingError))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".run.lock"
            holder = category.JobRunLock(path)
            holder.acquire()
            try:
                with self.assertRaises(category.UserFacingError) as caught:
                    category.JobRunLock(path).acquire()
            finally:
                holder.release()
            self.assertIn("已有抓取进程运行", str(caught.exception))
            stop = category.categorize_crawl_exception(caught.exception)
            self.assertEqual(stop.exit_code, run_outcome.EXIT_LOCK_HELD)


# ---------------------------------------------------------- P2-12d -------


class ReplaceRetryTests(unittest.TestCase):
    def test_atomic_writers_survive_a_transient_sharing_violation(self) -> None:
        real_replace = os.replace
        failures = {"left": 0}

        def flaky(src: Any, dst: Any) -> None:
            if failures["left"] > 0:
                failures["left"] -= 1
                raise PermissionError(13, "sharing violation")
            real_replace(src, dst)

        with tempfile.TemporaryDirectory() as temp_dir, patch("os.replace", side_effect=flaky), patch(
            "run_outcome.time.sleep"
        ):
            tmp = Path(temp_dir)
            failures["left"] = 2
            category.dump_json(tmp / "state.json", {"a": 1})
            self.assertEqual(json.loads((tmp / "state.json").read_text(encoding="utf-8")), {"a": 1})
            failures["left"] = 1
            category.write_jsonl_atomic(tmp / "records.jsonl", [{"asin": "B000000001"}])
            self.assertEqual((tmp / "records.jsonl").read_text(encoding="utf-8").strip(), '{"asin": "B000000001"}')
            self.assertEqual(sorted(path.name for path in tmp.iterdir()), ["records.jsonl", "state.json"])


if __name__ == "__main__":
    unittest.main()
