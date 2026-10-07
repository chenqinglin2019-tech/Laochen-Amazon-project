"""Round-1b review fixes for the image-competitor crawler.

Covers review.md P1-1 (review probe verified only by a risk-checked page; Find
Similar -> Lens fallback rules), P1-3 (item vs environment failures), P1-5
(post-CAPTCHA cooldown not budgeted), P1-6 (mostly unscorable candidates fail
the cycle), P2-1, P2-2, P2-3a/b, P2-4, P2-5, P2-6, P2-12c, P2-14 and the
replace-with-retry atomic writer.  Offline fakes only: no browser, no provider.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import MagicMock, patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
for extra in (SKILL_ROOT / "scripts", SKILL_ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import amazon_image_competitor_crawler as image  # noqa: E402
import run_outcome  # noqa: E402
from amazon_category_rank_crawler import safety_before_remote_action  # noqa: E402
from amazon_page_recovery import PageHealthAssessment, PageHealthStatus  # noqa: E402
from safety_control import LocalSafetyController, SafetyPausedError  # noqa: E402
from selenium.common.exceptions import TimeoutException, WebDriverException  # noqa: E402
import test_round1_image as r1  # noqa: E402


HEALTHY = PageHealthAssessment(PageHealthStatus.HEALTHY, "expected_content_present", "product")
CAPTCHA = PageHealthAssessment(
    PageHealthStatus.INTERACTIVE_VERIFICATION, "captcha_or_robot_check", "product"
)
PRODUCT_URL = "https://www.amazon.com/dp/B012345678"


class FakePage:
    """A tab whose every navigation returns the same page."""

    def __init__(self, *, title: str = "", body: str = "", status: int | None = 200) -> None:
        self.page_title = title
        self.body = body
        self.status = status
        self.current_url = "about:blank"
        self.title = ""
        self.last_http_status = None
        self.last_retry_after = ""
        self.last_navigation_error = ""
        self.window_handles = ["main"]
        self.visited: list[str] = []

    def get(self, url: str) -> None:
        self.visited.append(url)
        self.current_url = url
        self.title = self.page_title
        self.last_http_status = self.status

    def execute_script(self, script: str, *args):
        if "document.body" in script and "innerText" in script:
            return self.body
        return None


class NeverWait:
    """WebDriverWait stand-in whose condition never becomes true."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def until(self, _predicate):
        raise TimeoutException("never")


class SafetyHomeTestCase(r1.IsolatedHomeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.now = [dt.datetime(2026, 10, 3, 12, 0, 0)]
        self.safety_root = self.root / "safety"
        page_text = patch.object(image, "safe_find_text", side_effect=lambda d: d.execute_script("document.body innerText"))
        page_text.start()
        self.addCleanup(page_text.stop)
        plugin_text = patch.object(image, "sellersprite_visible_text", return_value="")
        plugin_text.start()
        self.addCleanup(plugin_text.stop)

    def controller(self, mode: str = "supervised") -> LocalSafetyController:
        return LocalSafetyController(
            self.safety_root,
            clock=lambda: self.now[0],
            batch_pause_pages_min=1000,
            batch_pause_pages_max=1000,
            mode=mode,
        )

    def review_safety(self, kind: str = "manual_review", mode: str = "supervised") -> LocalSafetyController:
        self.controller(mode)._write_pause(
            {
                "schema_version": 1,
                "active": True,
                "platform": "amazon",
                "reason": "http_429" if kind == "rate_probe" else "http_403",
                "message": "x",
                "detected_at": (self.now[0] - dt.timedelta(days=2)).isoformat(),
                "not_before": (self.now[0] - dt.timedelta(minutes=1)).isoformat(),
                "kind": kind,
                "review_required": kind != "rate_probe",
            }
        )
        safety = self.controller(mode)
        safety.begin(resume_after_review=kind != "rate_probe")
        return safety

    def fs_runtime(self, safety: object = None, **overrides: object) -> SimpleNamespace:
        raw: dict = {
            "safety": safety,
            "search_strategy": "sellersprite_find_similar_first",
            "marketplace_domain": "amazon.com",
            "page_timeout": 90,
            "find_similar_timeout": 20,
            "delivery_location_enabled": False,
            "lens_url": "https://www.amazon.com/stylesnap?q=upload",
            "operation_mode": "supervised",
            "manual_pause_timeout": 900,
            "_find_similar_consecutive_failures": 0,
        }
        raw.update(overrides)
        return SimpleNamespace(**raw)

    @staticmethod
    def source() -> dict:
        return {
            "source_id": "B012345678#row-2",
            "source_asin": "B012345678",
            "source_product_url": PRODUCT_URL,
            "input_row": 2,
        }


# ---------------------------------------------------------------------------
# P1-1: note_risk_checked + Find Similar -> Lens fallback rules.
# ---------------------------------------------------------------------------


class ReviewProbeTests(SafetyHomeTestCase):
    def test_healthy_risk_checked_page_verifies_the_probe_and_the_next_action_clears_it(self) -> None:
        safety = self.review_safety()
        safety.before_remote_action("probe")
        page = FakePage(title="Amazon.com: Garden Hose", body="healthy product page " * 400)
        page.get(PRODUCT_URL)
        self.assertEqual(
            image.enforce_image_page_assessment(page, SimpleNamespace(safety=safety), None, HEALTHY),
            "healthy",
        )
        self.assertTrue(safety._probe_verified)
        safety.before_remote_action("next page")
        self.assertFalse(safety.pause_path.exists())

    def test_unhealthy_or_signalled_page_never_verifies_the_probe(self) -> None:
        safety = self.review_safety()
        safety.before_remote_action("probe")
        page = FakePage(title="Sorry! Something went wrong!", body="Sorry! Something went wrong on our end.", status=503)
        page.get(PRODUCT_URL)
        unavailable = PageHealthAssessment(PageHealthStatus.TRANSIENT_UNAVAILABLE, "http_503", "product")
        with self.assertRaises(image.TransientAmazonPageUnavailable):
            image.enforce_image_page_assessment(page, SimpleNamespace(safety=safety), None, unavailable)
        # A supervised CAPTCHA marker on a "healthy" page is not a clean page either.
        captcha_page = FakePage(title="Amazon.com", body="Enter the characters you see below. captcha")
        captcha_page.get(PRODUCT_URL)
        image.enforce_image_page_assessment(captcha_page, SimpleNamespace(safety=safety), None, HEALTHY)
        self.assertFalse(safety._probe_verified)
        with self.assertRaises(SafetyPausedError) as stop:
            safety.before_remote_action("second action")
        self.assertEqual(stop.exception.kind, "risk_pause")
        self.assertTrue(safety.pause_path.exists())

    def test_rate_probe_503_product_page_does_not_fall_back_to_lens(self) -> None:
        """review_image_probe_fs_fallback.py scenario A, inverted."""

        safety = self.review_safety(kind="rate_probe")
        self.assertTrue(safety.rate_probe_active)
        page = FakePage(title="Sorry! Something went wrong!", body="Sorry! Something went wrong on our end.", status=503)
        with self.assertRaises(image.TransientAmazonPageUnavailable) as raised:
            image.run_image_search(page, self.fs_runtime(safety), self.source(), Path("/nonexistent.jpg"))
        self.assertEqual(raised.exception.reason, "http_503")
        self.assertEqual(page.visited, [PRODUCT_URL])
        self.assertTrue(safety.pause_path.exists())

    def test_cloudfront_403_without_main_image_trips_before_any_lens_navigation(self) -> None:
        """review_image_probe_fs_fallback.py scenario B, inverted."""

        safety = self.review_safety()
        page = FakePage(
            title="ERROR: The request could not be satisfied",
            body="403 ERROR The request could not be satisfied. Request blocked. Generated by cloudfront",
            status=403,
        )
        with (
            patch.object(image, "WebDriverWait", NeverWait),
            patch.object(image, "extract_main_image_url", return_value=""),
            patch.object(image, "upload_image_to_lens") as upload,
        ):
            with self.assertRaises(SafetyPausedError):
                image.run_image_search(page, self.fs_runtime(safety), self.source(), Path("/nonexistent.jpg"))
        self.assertEqual(page.visited, [PRODUCT_URL])
        upload.assert_not_called()
        pause = json.loads(safety.pause_path.read_text(encoding="utf-8"))
        self.assertEqual(pause["reason"], "http_403")

    def test_missing_main_image_falls_back_only_when_no_probe_is_pending(self) -> None:
        page = FakePage(title="Amazon.com: thing", body="a product page without a usable main image")
        with (
            patch.object(image, "WebDriverWait", NeverWait),
            patch.object(image, "extract_main_image_url", return_value=""),
            patch.object(image, "upload_image_to_lens") as upload,
            redirect_stdout(io.StringIO()),
        ):
            normal = self.controller()
            current = self.source()
            self.assertEqual(
                image.run_image_search(page, self.fs_runtime(normal), current, Path("x.jpg")),
                "amazon_upload",
            )
            upload.assert_called_once()
            self.assertTrue(current["find_similar_failed"])

            upload.reset_mock()
            reviewing = self.review_safety()
            # A fresh tab: the product page navigation is the review probe.
            page = FakePage(title="Amazon.com: thing", body="a product page without a usable main image")
            with self.assertRaises(image.TransientAmazonPageUnavailable) as raised:
                image.run_image_search(page, self.fs_runtime(reviewing), self.source(), Path("x.jpg"))
        self.assertEqual(raised.exception.reason, "expected_content_missing")
        upload.assert_not_called()
        self.assertEqual(page.visited, [PRODUCT_URL])
        self.assertTrue(reviewing.pause_path.exists())

    def test_fallback_rule_table(self) -> None:
        normal = self.fs_runtime(self.controller())
        self.assertTrue(image.find_similar_fallback_allowed(normal, "expected_content_missing"))
        self.assertTrue(image.find_similar_fallback_allowed(normal, "blank_page"))
        for reason in ("http_503", "navigation_error", "page_timeout", "http_429", "amazon_dog_error"):
            self.assertFalse(image.find_similar_fallback_allowed(normal, reason), reason)
        safety = self.review_safety()
        reviewing = self.fs_runtime(safety)
        # Pending (LocalSafetyController.review_probe_pending) until a page
        # passed the risk check: no fallback navigation in between.
        self.assertFalse(image.find_similar_fallback_allowed(reviewing, "blank_page"))
        safety.before_remote_action("probe")
        self.assertFalse(image.find_similar_fallback_allowed(reviewing, "blank_page"))
        safety.note_risk_checked()
        self.assertTrue(image.find_similar_fallback_allowed(reviewing, "blank_page"))

    def test_find_similar_result_timeout_risk_checks_the_result_tab_first(self) -> None:
        driver = MagicMock()
        driver.window_handles = ["main"]
        driver.current_url = PRODUCT_URL
        driver.execute_script.return_value = True
        order: list[str] = []
        common = [
            patch.object(image, "open_find_similar_product_page", return_value=True),
            patch.object(image, "find_similar_control_present", return_value=True),
            patch.object(image, "WebDriverWait", NeverWait),
            patch.object(image, "crawler_action_window_baseline", return_value={"main"}),
            patch.object(image, "begin_crawler_page_action", return_value="token"),
            patch.object(image, "claim_crawler_action_pages", return_value=[]),
            patch.object(image, "end_crawler_page_action"),
            patch.object(image, "claim_new_crawler_window_handles", return_value=[]),
            patch.object(image, "close_claimed_crawler_windows", side_effect=lambda *a, **k: order.append("close")),
            patch.object(image, "check_image_page_risk", side_effect=lambda *a, **k: order.append("risk") or True),
            patch.object(image, "counted_remote_action"),
            patch.object(image.time, "sleep"),
        ]
        for item in common:
            item.start()
        try:
            self.assertFalse(image.trigger_sellersprite_find_similar(driver, self.fs_runtime(self.controller()), self.source()))
            self.assertEqual(order, ["risk", "close"])
            safety = self.review_safety()
            safety.before_remote_action("find similar click = probe")
            with self.assertRaises(image.TransientAmazonPageUnavailable):
                image.trigger_sellersprite_find_similar(driver, self.fs_runtime(safety), self.source())
        finally:
            for item in reversed(common):
                item.stop()


# ---------------------------------------------------------------------------
# P2-5: rows without ASIN / URL; P2-14: navigation error + solved CAPTCHA.
# ---------------------------------------------------------------------------


class SmallPathTests(SafetyHomeTestCase):
    def test_image_only_rows_skip_find_similar_without_counting_failures(self) -> None:
        runtime = self.fs_runtime(None)
        with (
            patch.object(image, "trigger_sellersprite_find_similar") as trigger,
            patch.object(image, "upload_image_to_lens") as upload,
        ):
            for index in range(4):
                current = {"source_id": f"row-{index}", "input_image_url": "https://x/y.jpg"}
                self.assertEqual(image.run_image_search(MagicMock(), runtime, current, Path("x.jpg")), "amazon_upload")
                self.assertNotIn("find_similar_failed", current)
        trigger.assert_not_called()
        self.assertEqual(upload.call_count, 4)
        self.assertEqual(runtime._find_similar_consecutive_failures, 0)

    def test_navigation_error_with_solved_captcha_is_a_navigation_failure_not_an_assertion(self) -> None:
        driver = MagicMock()
        driver.get.side_effect = WebDriverException("net::ERR_CONNECTION_RESET")
        runtime = SimpleNamespace(page_timeout=1, safety=None)
        with (
            patch.object(image, "assess_image_page", return_value=CAPTCHA),
            patch.object(image, "handle_image_verification"),
        ):
            with self.assertRaises(image.TransientAmazonPageUnavailable) as raised:
                image.open_image_amazon_page(driver, PRODUCT_URL, runtime)
        self.assertEqual(raised.exception.reason, "navigation_error")

    def test_atomic_json_writer_retries_a_windows_sharing_violation(self) -> None:
        real_replace = os.replace
        attempts: list[int] = []

        def flaky_replace(src, dst):
            attempts.append(1)
            if len(attempts) == 1:
                raise PermissionError(13, "sharing violation")
            return real_replace(src, dst)

        target = self.root / "progress" / "emb-x.json"
        with patch.object(run_outcome.os, "replace", side_effect=flaky_replace), patch.object(run_outcome.time, "sleep"):
            image._atomic_write_json_file(target, {"vector": [1.0]})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"vector": [1.0]})

    def test_gbk_csv_from_excel_is_read_and_undecodable_csv_is_a_clear_error(self) -> None:
        path = self.root / "image_competitors.csv"
        path.write_bytes("ASIN,商品URL,主图URL,本地图片路径,备注\r\nB0TEST0001,,,,中文备注\r\n".encode("gbk"))
        products = image.load_products(path, "amazon.com")
        self.assertEqual(products[0]["source_asin"], "B0TEST0001")
        self.assertEqual(products[0]["input_note"], "中文备注")
        path.write_bytes(b"ASIN\r\n\xff\xfe\xff\r\n")
        with self.assertRaises(image.UserFacingError) as raised:
            image.load_products(path, "amazon.com")
        self.assertIn("CSV UTF-8", str(raised.exception))


# ---------------------------------------------------------------------------
# P1-5 / P2-6: safety waits are not charged to the source budget.
# P2-1: the empty retry schedule applies only to the unverified rate probe.
# ---------------------------------------------------------------------------


class BudgetAndScheduleTests(SafetyHomeTestCase):
    def test_post_captcha_cooldown_is_excluded_from_the_source_budget(self) -> None:
        clock = {"now": 0.0}
        safety = self.controller()
        runtime = SimpleNamespace(
            safety=safety,
            operation_mode="supervised",
            _source_budget=image.SourceBudget(8 * 60, clock=lambda: clock["now"]),
        )

        def cooldown(*_args, **_kwargs):
            clock["now"] += 600.0

        page = FakePage(title="Robot Check", body="Enter the characters you see below")
        with (
            patch.object(image, "handle_image_verification"),
            patch.object(LocalSafetyController, "captcha_cleared", side_effect=cooldown),
        ):
            outcome = image.enforce_image_page_assessment(page, runtime, None, CAPTCHA)
        self.assertEqual(outcome, "manual_verification_cleared")
        self.assertLess(runtime._source_budget.elapsed(), 1.0)
        image.check_source_budget(runtime, "after captcha")  # does not raise

    def test_delivery_reopen_throttle_wait_is_excluded_and_method_restored(self) -> None:
        clock = {"now": 0.0}
        safety = self.controller()
        runtime = SimpleNamespace(
            safety=safety,
            delivery_location_enabled=True,
            _source_budget=image.SourceBudget(8 * 60, clock=lambda: clock["now"]),
        )

        def long_rest(_self, _action):
            clock["now"] += 700.0

        def reopen(_driver, rt, **_kwargs):
            # Category's _reopen_amazon_target calls this directly.
            safety_before_remote_action(rt, "重新导航 Amazon 页面")

        with (
            patch.object(LocalSafetyController, "before_remote_action", long_rest),
            patch.object(image, "ensure_amazon_delivery_location", side_effect=reopen),
        ):
            image.ensure_image_delivery_location(MagicMock(), runtime, None, PRODUCT_URL, "product")
            self.assertLess(runtime._source_budget.elapsed(), 1.0)
        self.assertNotIn("before_remote_action", safety.__dict__)

    def test_retry_schedule_is_empty_only_while_the_rate_probe_is_unverified(self) -> None:
        configured = ((60.0, 60.0),)
        normal = SimpleNamespace(
            safety=self.controller(), amazon_page_unavailable_retry_schedule_seconds=configured
        )
        self.assertEqual(image.page_retry_schedule(normal), configured)
        safety = self.review_safety(kind="rate_probe")
        probing = SimpleNamespace(safety=safety, amazon_page_unavailable_retry_schedule_seconds=configured)
        self.assertEqual(image.page_retry_schedule(probing), ())
        safety.before_remote_action("probe")
        safety.note_risk_checked()
        self.assertEqual(image.page_retry_schedule(probing), configured)
        safety.before_remote_action("next item")  # verified -> pause cleared
        self.assertFalse(safety.rate_probe_active)
        self.assertEqual(image.page_retry_schedule(probing), configured)

    def test_stage_retry_uses_the_per_stage_schedule(self) -> None:
        clock = {"now": 1000.0}

        def waiter(seconds: float) -> None:
            clock["now"] += seconds

        def runtime_for(safety: LocalSafetyController) -> SimpleNamespace:
            return SimpleNamespace(
                safety=safety,
                marketplace_domain="amazon.com",
                amazon_page_unavailable_retry_schedule_seconds=((0.0, 0.0),),
                _amazon_page_retry_clock=lambda: clock["now"],
                _amazon_page_retry_waiter=waiter,
                _amazon_page_retry_rng=SimpleNamespace(uniform=lambda a, b: a),
            )

        def attempts_for(runtime: SimpleNamespace) -> int:
            state = MagicMock()
            state.load_amazon_page_retry.return_value = None
            attempts: list[int] = []

            def failing(_attempt):
                attempts.append(1)
                raise image.TransientAmazonPageUnavailable("503", reason="http_503")

            with self.assertRaises(image.AmazonPageRetryExhausted), redirect_stdout(io.StringIO()):
                image.run_image_page_stage_with_recovery(
                    runtime, state, {"source_id": "S"}, "source_product", PRODUCT_URL, lambda: None, failing
                )
            return len(attempts)

        self.assertEqual(attempts_for(runtime_for(self.review_safety(kind="rate_probe"))), 1)
        self.assertEqual(attempts_for(runtime_for(self.controller())), 2)


# ---------------------------------------------------------------------------
# P1-6 + P2-3a/b + P2-4: paid-call accounting.
# ---------------------------------------------------------------------------


class PaidCallTests(r1.IsolatedHomeTestCase):
    def store(self, name: str = "S") -> image.SourceProgressStore:
        return image.SourceProgressStore(
            self.root / "progress" / name,
            {"source_id": name, "provider_sha256": "p", "crawl_plan_sha256": "c"},
        )

    def test_all_or_most_unscorable_candidates_fail_instead_of_verified_zero(self) -> None:
        all_blank = [{**r1.candidate(i), "candidate_image_url": ""} for i in range(1, 6)]
        with patch.object(image, "call_multimodal_embedding", return_value=[1.0, 0.0]) as emb:
            with self.assertRaises(image.CandidatesUnscorableError) as raised:
                image.run_cascade_match(r1.cascade_runtime(), self.source_image, "", all_blank)
        self.assertEqual(raised.exception.failure_reason, "all_candidates_unscorable")
        self.assertIn("5/5", str(raised.exception))
        self.assertEqual(emb.call_count, 1)  # source only
        image.EMBEDDING_CACHE.clear()
        three_of_five = [
            {**r1.candidate(i), "candidate_image_url": "" if i <= 3 else r1.candidate(i)["candidate_image_url"]}
            for i in range(1, 6)
        ]
        with (
            patch.object(image, "call_multimodal_embedding", return_value=[1.0, 0.0]),
            patch.object(image, "call_doubao_mini_verifier") as mini,
        ):
            with self.assertRaises(image.CandidatesUnscorableError):
                image.run_cascade_match(r1.cascade_runtime(), self.source_image, "", three_of_five)
        mini.assert_not_called()

    def test_classification_of_failure_reasons(self) -> None:
        unscorable = image.CandidatesUnscorableError("5/5 个 Lens 候选图片无法识别")
        reason, detail = image.item_failure_classification("all_candidates_unscorable", str(unscorable), unscorable)
        self.assertTrue(run_outcome.is_environment_failure(f"{reason} {detail}"))
        for last_reason, environment in (
            ("http_503", True),
            ("navigation_error", True),
            ("page_timeout", True),
            ("blank_page", True),
            ("expected_content_missing", False),
            ("amazon_dog_error", False),
        ):
            exhausted = image.AmazonPageRetryExhausted(
                {"stage": "lens_results"},
                image.TransientAmazonPageUnavailable("x", reason=last_reason),
            )
            reason, detail = image.item_failure_classification(exhausted.failure_code, "x", exhausted)
            self.assertEqual(run_outcome.is_environment_failure(f"{reason} {detail}"), environment, last_reason)
        malformed = image.MiniMalformedResponseError("豆包 Mini 连续 2 次未返回完整结构化结果")
        reason, detail = image.item_failure_classification(malformed.failure_reason, str(malformed), malformed)
        self.assertFalse(run_outcome.is_environment_failure(f"{reason} {detail}"))
        outage = image.EmbeddingProviderError("HTTP 503 after retries")
        reason, detail = image.item_failure_classification(outage.failure_reason, str(outage), outage)
        self.assertTrue(run_outcome.is_environment_failure(f"{reason} {detail}"))

    def test_memory_cache_hit_is_persisted_for_the_current_source(self) -> None:
        """review_image_cache_not_persisted.py, inverted."""

        calls: list[str] = []
        shared = "https://m.media-amazon.com/images/I/shared.jpg"

        def fake(_runtime, ref):
            calls.append(ref)
            return [0.1, 0.2]

        with patch.object(image, "call_multimodal_embedding", side_effect=fake):
            runtime_a = r1.cascade_runtime(_source_progress=self.store("A"))
            image.call_multimodal_embedding_cached(runtime_a, shared)
            runtime_a._source_progress.discard()
            image.call_multimodal_embedding_cached(r1.cascade_runtime(_source_progress=self.store("B")), shared)
            image.EMBEDDING_CACHE.clear()
            restarted = r1.cascade_runtime(_source_progress=self.store("B"))
            image.call_multimodal_embedding_cached(restarted, shared)
        self.assertEqual(len(calls), 1)
        self.assertEqual(restarted.provider_metrics.get("embedding_reused_from_checkpoint"), 1)

    def test_rejected_url_is_remembered_and_mini_gets_the_base64_form(self) -> None:
        records = [r1.candidate(1), r1.candidate(2)]
        rejected_url = records[0]["candidate_image_url"]
        inline = "data:image/jpeg;base64,QUJD"
        calls: list[str] = []

        def fake_emb(_runtime, ref):
            calls.append(ref)
            if ref == rejected_url:
                raise image.EmbeddingInputRejected("HTTP 400")
            return [1.0, 0.0] if ref.startswith("data:") else [0.0, 1.0]

        mini_payloads: list[dict] = []

        def fake_post(_url, **kwargs):
            mini_payloads.append(kwargs["json"])
            return r1.mini_content_response(json.dumps({"matches": [
                {"asin": records[0]["asin"], "is_same_product": True, "confidence": 0.93, "reason": "同款"},
            ]}))

        with (
            patch.object(image, "call_multimodal_embedding", side_effect=fake_emb),
            patch.object(image, "image_url_to_data_url", return_value=inline) as download,
            patch.object(image.requests, "post", side_effect=fake_post),
        ):
            runtime = r1.cascade_runtime(_source_progress=self.store())
            result = image.run_cascade_match(runtime, self.source_image, "", records)
            sent_urls = [
                part["image_url"]["url"]
                for part in mini_payloads[0]["messages"][0]["content"]
                if part.get("type") == "image_url"
            ]
            self.assertEqual(sent_urls[1:], [inline])  # [0] is the source image
            self.assertEqual(result.same_product_count, 1)
            self.assertEqual(result.accepted_records[0]["candidate_image_url"], rejected_url)
            self.assertEqual(calls.count(rejected_url), 1)

            # Restart of the same source: the rejected URL is not sent again
            # and the Mini verdict is reused.
            image.EMBEDDING_CACHE.clear()
            restarted = r1.cascade_runtime(_source_progress=self.store())
            image.run_cascade_match(restarted, self.source_image, "", records)
        self.assertEqual(calls.count(rejected_url), 1)
        self.assertEqual(download.call_count, 2)
        self.assertEqual(len(mini_payloads), 1)
        self.assertEqual(restarted.provider_metrics.get("mini_reused_from_checkpoint"), 1)


# ---------------------------------------------------------------------------
# Loop level: P1-3, P1-6, P2-2.
# ---------------------------------------------------------------------------


class LoopHarness(r1.IsolatedHomeTestCase):
    write_products = r1.LoopTests.write_products
    raw_config = r1.LoopTests.raw_config
    runtime = r1.LoopTests.runtime
    job_dir = r1.LoopTests.job_dir
    loop_patches = r1.LoopTests.loop_patches

    def setUp(self) -> None:
        super().setUp()
        self.embedding_config = self.root / "embedding.json"
        self.embedding_config.write_text(json.dumps({"api_key": "emb-secret"}), encoding="utf-8")
        self.mini_config = self.root / "mini.json"
        self.mini_config.write_text(json.dumps({"api_key": "mini-secret"}), encoding="utf-8")

    def crawl(self, runtime, extra=(), *, drop=()):
        patches = [p for p in self.loop_patches() if getattr(p, "attribute", "") not in drop] + list(extra)
        started = [p.start() for p in patches]
        try:
            with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                return image.run_image_competitor_crawl(runtime, dry_run=False), started
        finally:
            for p in reversed(patches):
                p.stop()

    def state(self, runtime) -> dict:
        return image.load_json(self.job_dir(runtime) / "state.json")


class LoopTests1b(LoopHarness):
    def emb(self, _runtime, ref):
        return [1.0, 0.0] if ref.startswith("data:") else [0.0, 1.0]

    def search_failing(self, reason: str):
        return patch.object(
            image,
            "run_image_search",
            side_effect=image.TransientAmazonPageUnavailable("lens page", reason=reason),
        )

    def test_item_page_failure_skips_on_second_run_but_outage_does_not(self) -> None:
        products = self.write_products(["B012345678,,,,x"])
        for reason, skipped in (("expected_content_missing", True), ("http_503", False)):
            with self.subTest(reason=reason):
                runtime = self.runtime(products, job_id=f"page-{reason}")
                with self.assertRaises(run_outcome.CrawlStop) as first:
                    self.crawl(runtime, [self.search_failing(reason)], drop={"run_image_search"})
                self.assertEqual(first.exception.exit_code, run_outcome.EXIT_RETRY_LATER)
                state = self.state(runtime)
                self.assertEqual(state["last_failure_environment"], not skipped)
                runtime = self.runtime(products, job_id=f"page-{reason}")
                if skipped:
                    result, _ = self.crawl(runtime, [self.search_failing(reason)], drop={"run_image_search"})
                    self.assertEqual(result, 0)
                    self.assertEqual(self.state(runtime)["skipped_items"][0]["reason"], image.QUARANTINE_REASON)
                else:
                    with self.assertRaises(run_outcome.CrawlStop) as second:
                        self.crawl(runtime, [self.search_failing(reason)], drop={"run_image_search"})
                    self.assertEqual(second.exception.exit_code, run_outcome.EXIT_RETRY_LATER)
                    state = self.state(runtime)
                    self.assertFalse(state.get("skipped_items"))
                    self.assertEqual(state["item_failure_meta"]["B012345678#row-2"]["environment_runs"], 2)

    def test_unscorable_lens_list_is_an_environment_failure_without_a_count(self) -> None:
        products = self.write_products(["B012345678,,,,x"])
        runtime = self.runtime(products)

        def blank_images(_d, _r, current, _s):
            return [
                {**r1.candidate(i, source_asin=current["source_asin"]), "source_id": current["source_id"], "candidate_image_url": ""}
                for i in range(1, 4)
            ]

        with self.assertRaises(run_outcome.CrawlStop) as stop:
            self.crawl(
                runtime,
                [
                    patch.object(image, "merge_lens_product_data", side_effect=blank_images),
                    patch.object(image, "call_multimodal_embedding", side_effect=self.emb),
                ],
                drop={"merge_lens_product_data"},
            )
        self.assertEqual(stop.exception.exit_code, run_outcome.EXIT_RETRY_LATER)
        job_dir = self.job_dir(runtime)
        state = self.state(runtime)
        source_id = state["current"]["source_id"]
        reasons = [row["reason"] for row in image.read_jsonl(job_dir / "failures.jsonl")]
        self.assertIn("all_candidates_unscorable", reasons)
        self.assertEqual(image.read_jsonl(job_dir / "counts.jsonl"), [])
        self.assertTrue(state["last_failure_environment"])
        self.assertEqual(state.get("item_failure_cycles") or {}, {})
        self.assertEqual(state["item_failure_meta"][source_id]["environment_runs"], 1)
        progress_dir = image.source_progress_dir(job_dir, state["current"])
        self.assertFalse(list(progress_dir.glob("lens-*.json")), "the suspect Lens list is collected again")

        # finalize_run turns the environment failure into a resume_at.
        run_outcome.finalize_run(job_dir, run_outcome.classify_exception(stop.exception))
        summary = json.loads((job_dir / "run_summary.json").read_text(encoding="utf-8"))
        self.assertTrue(summary["resume_at"])

    def test_locked_workbook_on_a_finished_run_is_needs_human_with_close_hint(self) -> None:
        products = self.write_products(["B012345678,,,,x"])
        runtime = self.runtime(products)
        with self.assertRaises(run_outcome.CrawlStop) as stop:
            self.crawl(
                runtime,
                [
                    patch.object(image, "call_multimodal_embedding", side_effect=self.emb),
                    patch.object(image, "write_count_only_workbook", side_effect=PermissionError(13, "locked")),
                ],
            )
        self.assertEqual(stop.exception.exit_code, run_outcome.EXIT_NEEDS_HUMAN)
        self.assertIn("关闭表格", stop.exception.next_action)
        self.assertEqual(len(image.read_jsonl(self.job_dir(runtime) / "counts.jsonl")), 1)

    def test_locked_workbook_never_replaces_a_retry_later_outcome(self) -> None:
        products = self.write_products(["B0AAAAAAAA,,,,x", "B0BBBBBBBB,,,,x"])
        runtime = self.runtime(products)

        def emb(_runtime, ref):
            if "B0BBBBBBBB" in ref:
                raise image.EmbeddingProviderError("HTTP 503 after retries")
            return self.emb(_runtime, ref)

        def merge(_d, _r, current, _s):
            row = {**r1.candidate(1, source_asin=current["source_asin"]), "source_id": current["source_id"]}
            row["candidate_image_url"] = f"https://m.media-amazon.com/images/I/{current['source_asin']}.jpg"
            return [row]

        workbook = MagicMock(side_effect=PermissionError(13, "locked"))
        with self.assertRaises(run_outcome.CrawlStop) as stop:
            self.crawl(
                runtime,
                [
                    patch.object(image, "merge_lens_product_data", side_effect=merge),
                    patch.object(image, "call_multimodal_embedding", side_effect=emb),
                    patch.object(image, "write_count_only_workbook", workbook),
                ],
                drop={"merge_lens_product_data"},
            )
        self.assertEqual(stop.exception.exit_code, run_outcome.EXIT_RETRY_LATER)
        workbook.assert_called_once()


if __name__ == "__main__":
    unittest.main()
