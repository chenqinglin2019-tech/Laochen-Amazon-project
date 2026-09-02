from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from amazon_page_recovery import (
    AmazonPageRetryController,
    AmazonPageRetryExhausted,
    DEFAULT_RETRY_SCHEDULE_SECONDS,
    DomainCooldownRegistry,
    PAGE_KINDS,
    PageHealthStatus,
    PageSnapshot,
    RetryCallbacks,
    RetryConfigurationError,
    TransientAmazonPageUnavailable,
    classify_page_snapshot,
    parse_retry_schedule,
    redact_error,
    retry_schedule_from_config,
    sanitize_state_url,
)


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = float(now)
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    def wait(self, seconds: float) -> None:
        self.waits.append(float(seconds))
        self.now += float(seconds)


class LowerBoundRng:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    def uniform(self, minimum: float, maximum: float) -> float:
        self.calls.append((minimum, maximum))
        return minimum


class ForbiddenRng:
    def uniform(self, minimum: float, maximum: float) -> float:
        raise AssertionError("restart must not resample an already-persisted wait")


class ScheduleValidationTests(unittest.TestCase):
    def test_default_schedule_has_four_waits_for_five_attempts(self) -> None:
        self.assertEqual(
            DEFAULT_RETRY_SCHEDULE_SECONDS,
            ((180, 300), (180, 300), (1800, 1800), (3600, 3600)),
        )
        self.assertEqual(
            retry_schedule_from_config({}),
            ((180.0, 300.0), (180.0, 300.0), (1800.0, 1800.0), (3600.0, 3600.0)),
        )

    def test_valid_custom_schedule_is_normalized(self) -> None:
        self.assertEqual(
            parse_retry_schedule([[0, 0.5], [1, 2], [3.0, 3], [4, 5]]),
            ((0.0, 0.5), (1.0, 2.0), (3.0, 3.0), (4.0, 5.0)),
        )

    def test_present_null_is_not_treated_as_default(self) -> None:
        with self.assertRaises(RetryConfigurationError):
            retry_schedule_from_config(
                {"amazon_page_unavailable_retry_schedule_seconds": None}
            )

    def test_invalid_schedules_fail_closed(self) -> None:
        invalid_values = [
            "180,300",
            [],
            [[1, 1]] * 3,
            [[1, 1]] * 5,
            [[1]] * 4,
            [[1, 2, 3]] * 4,
            [[True, 1]] * 4,
            [[False, 1]] * 4,
            [[-1, 1]] * 4,
            [[2, 1]] * 4,
            [[math.nan, 1]] * 4,
            [[math.inf, math.inf]] * 4,
            [["1", 2]] * 4,
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(RetryConfigurationError):
                    parse_retry_schedule(value)


class PageHealthClassificationTests(unittest.TestCase):
    def assess(self, page_kind: str = "product", **values: object):
        return classify_page_snapshot(PageSnapshot(page_kind=page_kind, **values))

    def test_expected_dom_and_explicit_empty_are_supported_for_every_kind(self) -> None:
        self.assertEqual(
            PAGE_KINDS,
            {"product", "search_category", "lens_upload", "lens_results"},
        )
        for page_kind in PAGE_KINDS:
            with self.subTest(page_kind=page_kind, outcome="healthy"):
                assessment = self.assess(
                    page_kind,
                    title="ordinary page",
                    expected_content_present=True,
                )
                self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)
                self.assertFalse(assessment.retryable)
            with self.subTest(page_kind=page_kind, outcome="empty"):
                assessment = self.assess(
                    page_kind,
                    body_text="No matching results were found",
                    explicit_empty=True,
                )
                self.assertEqual(assessment.status, PageHealthStatus.VERIFIED_EMPTY)

    def test_product_content_that_contains_sorry_stays_healthy(self) -> None:
        assessment = self.assess(
            title="A real product",
            body_text="Sorry, this color is temporarily unavailable. Other colors ship now.",
            expected_content_present=True,
        )
        self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)

    def test_lone_sorry_is_not_an_amazon_error_signature(self) -> None:
        assessment = self.assess(title="Sorry", body_text="Sorry")
        self.assertEqual(assessment.status, PageHealthStatus.TRANSIENT_UNAVAILABLE)
        self.assertEqual(assessment.reason, "expected_content_missing")

    def test_amazon_dog_and_transport_failures_are_transient(self) -> None:
        cases = [
            ({"body_text": "Sorry, something went wrong on our end. Meet the dogs of Amazon."}, "amazon_dog_error"),
            ({"http_status": 503, "body_text": "maintenance"}, "http_503"),
            ({"http_status": 429}, "http_429"),
            ({"body_text": "Access Denied"}, "access_denied"),
            ({"body_text": "Your request has been blocked"}, "rate_limited"),
            ({"navigation_error": "net::ERR_TIMED_OUT"}, "navigation_error"),
            ({}, "blank_page"),
        ]
        for values, reason in cases:
            with self.subTest(reason=reason):
                assessment = self.assess(**values)
                self.assertEqual(
                    assessment.status, PageHealthStatus.TRANSIENT_UNAVAILABLE
                )
                self.assertEqual(assessment.reason, reason)
                self.assertTrue(assessment.retryable)

    def test_http_error_overrides_stale_expected_dom(self) -> None:
        assessment = self.assess(
            http_status=503,
            expected_content_present=True,
            body_text="stale product title",
        )
        self.assertEqual(assessment.status, PageHealthStatus.TRANSIENT_UNAVAILABLE)

    def test_strong_error_overrides_conflicting_explicit_empty(self) -> None:
        assessment = self.assess(
            body_text="Access Denied",
            explicit_empty=True,
        )
        self.assertEqual(assessment.status, PageHealthStatus.TRANSIENT_UNAVAILABLE)

    def test_captcha_is_interactive_and_not_automatic_retry(self) -> None:
        assessment = self.assess(
            url="https://www.amazon.com/errors/validateCaptcha",
            body_text="Robot Check: enter the characters you see",
        )
        self.assertEqual(
            assessment.status, PageHealthStatus.INTERACTIVE_VERIFICATION
        )
        self.assertFalse(assessment.retryable)

    def test_amazon_sign_in_requires_url_or_form_evidence(self) -> None:
        assessment = self.assess(
            url="https://www.amazon.co.uk/ap/signin?openid.return_to=x",
            title="Amazon Sign-In",
        )
        self.assertEqual(assessment.status, PageHealthStatus.AMAZON_SIGN_IN)

        product = self.assess(
            url="https://www.amazon.com/dp/B000000001",
            body_text="Sign in is optional for this product",
            expected_content_present=True,
        )
        self.assertEqual(product.status, PageHealthStatus.HEALTHY)

    def test_conflicting_dom_facts_and_bad_kinds_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.assess(expected_content_present=True, explicit_empty=True)
        with self.assertRaises(ValueError):
            self.assess("unknown")

    def test_transient_exception_can_be_created_only_from_retryable_assessment(self) -> None:
        transient = self.assess(navigation_error="timeout")
        error = TransientAmazonPageUnavailable.from_assessment(
            transient, url="https://www.amazon.com/dp/X"
        )
        self.assertEqual(error.reason, "navigation_error")
        with self.assertRaises(ValueError):
            TransientAmazonPageUnavailable.from_assessment(
                self.assess(expected_content_present=True)
            )


class RetryControllerTests(unittest.TestCase):
    def make_callbacks(
        self,
        *,
        loaded: dict | None = None,
        clock: FakeClock | None = None,
    ):
        writes: list[dict] = []
        clears: list[bool] = []
        cleanups: list[bool] = []
        cooldowns: list[tuple[str, str, float]] = []
        heartbeats: list[dict] = []
        order: list[str] = []

        def write(state):
            writes.append(dict(state))
            order.append(f"write:{state['status']}")

        def begin(domain, deadline):
            cooldowns.append(("begin", domain, deadline))
            order.append("cooldown:begin")

        def end(domain, deadline):
            cooldowns.append(("end", domain, deadline))
            order.append("cooldown:end")

        def wait(seconds):
            order.append("wait")
            assert clock is not None
            clock.wait(seconds)

        callbacks = RetryCallbacks(
            load_state=lambda: loaded,
            write_state=write,
            clear_state=lambda: clears.append(True),
            cleanup=lambda: cleanups.append(True),
            begin_domain_cooldown=begin,
            end_domain_cooldown=end,
            heartbeat=lambda state: heartbeats.append(dict(state)),
        )
        return callbacks, writes, clears, cleanups, cooldowns, heartbeats, order, wait

    def controller(
        self,
        clock: FakeClock,
        callbacks: RetryCallbacks,
        *,
        rng=None,
        schedule=((0, 0), (0, 0), (0, 0), (0, 0)),
        waiter=None,
    ) -> AmazonPageRetryController:
        return AmazonPageRetryController(
            domain="WWW.AMAZON.COM",
            work_key="asin:B000000001",
            stage="product",
            url="https://user:password@www.amazon.com/dp/B000000001#reviews",
            schedule=schedule,
            callbacks=callbacks,
            clock=clock,
            rng=rng or LowerBoundRng(),
            waiter=waiter or clock.wait,
        )

    def test_exactly_five_attempts_and_four_default_waits(self) -> None:
        clock = FakeClock()
        rng = LowerBoundRng()
        callbacks, writes, clears, cleanups, cooldowns, _, _, _ = self.make_callbacks(
            clock=clock
        )
        controller = self.controller(
            clock,
            callbacks,
            rng=rng,
            schedule=DEFAULT_RETRY_SCHEDULE_SECONDS,
        )
        attempts = []

        def always_fails(attempt):
            attempts.append((attempt.cycle, attempt.attempt_number))
            raise TransientAmazonPageUnavailable(
                "HTTP 503 token=very-secret", reason="http_503"
            )

        with self.assertRaises(AmazonPageRetryExhausted) as raised:
            controller.run(always_fails)

        self.assertEqual(attempts, [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5)])
        self.assertEqual(
            rng.calls,
            [(180.0, 300.0), (180.0, 300.0), (1800.0, 1800.0), (3600.0, 3600.0)],
        )
        self.assertAlmostEqual(sum(clock.waits), 5760.0)
        self.assertTrue(all(0 <= item <= 60 for item in clock.waits))
        self.assertEqual(len(cleanups), 5)
        self.assertFalse(clears)
        self.assertEqual([item[0] for item in cooldowns], ["begin", "end"] * 4)
        self.assertEqual(
            writes[-1]["status"], "manual_resume_required"
        )
        self.assertEqual(writes[-1]["attempts_completed"], 5)
        self.assertEqual(
            raised.exception.failure_code,
            "amazon_page_unavailable_retry_exhausted",
        )
        self.assertNotIn("very-secret", writes[-1]["error"])

    def test_preflight_first_failure_does_not_create_a_sixth_attempt(self) -> None:
        clock = FakeClock()
        callbacks, writes, _, cleanups, _, _, _, _ = self.make_callbacks(
            clock=clock
        )
        controller = self.controller(clock, callbacks)
        attempts = [1]

        def remaining_attempts(attempt):
            attempts.append(attempt.attempt_number)
            raise TransientAmazonPageUnavailable("dog page")

        with self.assertRaises(AmazonPageRetryExhausted):
            controller.run(
                remaining_attempts,
                initial_failure=TransientAmazonPageUnavailable("dog page"),
            )
        self.assertEqual(attempts, [1, 2, 3, 4, 5])
        self.assertEqual(len(cleanups), 5)
        waiting = [item for item in writes if item.get("status") == "waiting"]
        self.assertEqual([item["next_attempt"] for item in waiting], [2, 3, 4, 5])

    def test_selected_wait_is_persisted_before_cooldown_and_sleep(self) -> None:
        clock = FakeClock()
        callbacks, writes, clears, _, _, _, order, waiter = self.make_callbacks(
            clock=clock
        )
        controller = self.controller(
            clock,
            callbacks,
            schedule=((125, 125), (0, 0), (0, 0), (0, 0)),
            waiter=waiter,
        )
        calls = 0

        def succeeds_second_time(attempt):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TransientAmazonPageUnavailable("dog page")
            return "ok"

        self.assertEqual(controller.run(succeeds_second_time), "ok")
        waiting_write = order.index("write:waiting")
        cooldown = order.index("cooldown:begin")
        sleep = order.index("wait")
        self.assertLess(waiting_write, cooldown)
        self.assertLess(cooldown, sleep)
        waiting = next(state for state in writes if state["status"] == "waiting")
        self.assertEqual(waiting["selected_wait_seconds"], 125.0)
        self.assertEqual(waiting["next_retry_at"], 1125.0)
        self.assertEqual(len(clears), 1)

    def test_heartbeat_chunks_never_exceed_sixty_seconds(self) -> None:
        clock = FakeClock()
        callbacks, _, _, _, _, heartbeats, _, _ = self.make_callbacks(clock=clock)
        controller = self.controller(
            clock,
            callbacks,
            schedule=((125, 125), (0, 0), (0, 0), (0, 0)),
        )
        calls = 0

        def operation(attempt):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TransientAmazonPageUnavailable("temporary")
            return 42

        self.assertEqual(controller.run(operation), 42)
        self.assertEqual(clock.waits, [60.0, 60.0, 5.0])
        self.assertEqual(len(heartbeats), 3)
        self.assertEqual(heartbeats[-1]["remaining_wait_seconds"], 0.0)

    def test_restart_respects_saved_deadline_without_resampling(self) -> None:
        clock = FakeClock(now=1000)
        loaded = {
            "amazon_page_retry": {
                "status": "waiting",
                "domain": "www.amazon.com",
                "work_key": "asin:B000000001",
                "stage": "product",
                "cycle": 2,
                "attempts_completed": 1,
                "next_attempt": 2,
                "selected_wait_seconds": 200,
                "next_retry_at": 1150.0,
                "remaining_wait_seconds": 150,
                "url": "https://www.amazon.com/dp/B000000001",
                "error": "dog page",
            }
        }
        callbacks, _, clears, cleanups, _, _, _, _ = self.make_callbacks(
            loaded=loaded, clock=clock
        )
        controller = self.controller(
            clock,
            callbacks,
            rng=ForbiddenRng(),
        )
        seen = []

        def operation(attempt):
            seen.append((attempt.cycle, attempt.attempt_number))
            return "resumed"

        self.assertEqual(controller.run(operation), "resumed")
        self.assertEqual(clock.waits, [60.0, 60.0, 30.0])
        self.assertEqual(seen, [(2, 2)])
        self.assertEqual(len(cleanups), 1)
        self.assertEqual(len(clears), 1)

    def test_manual_resume_starts_a_fresh_cycle_for_same_work(self) -> None:
        clock = FakeClock()
        loaded = {
            "status": "manual_resume_required",
            "domain": "www.amazon.com",
            "work_key": "asin:B000000001",
            "stage": "product",
            "cycle": 4,
            "attempts_completed": 5,
            "next_attempt": 1,
        }
        callbacks, _, clears, _, _, _, _, _ = self.make_callbacks(
            loaded=loaded, clock=clock
        )
        controller = self.controller(clock, callbacks)
        seen = []
        result = controller.run(
            lambda attempt: seen.append((attempt.cycle, attempt.attempt_number))
            or "ok"
        )
        self.assertEqual(result, "ok")
        self.assertEqual(seen, [(5, 1)])
        # Once to remove the old manual pause, then once after success.
        self.assertEqual(len(clears), 2)

    def test_non_retry_exception_is_cleaned_and_retry_state_cleared(self) -> None:
        clock = FakeClock()
        callbacks, _, clears, cleanups, _, _, _, _ = self.make_callbacks(clock=clock)
        controller = self.controller(clock, callbacks)
        with self.assertRaisesRegex(RuntimeError, "terminal"):
            controller.run(lambda attempt: (_ for _ in ()).throw(RuntimeError("terminal")))
        self.assertEqual(len(cleanups), 1)
        self.assertEqual(len(clears), 1)

    def test_keyboard_interrupt_cleans_up_but_preserves_attempt_state(self) -> None:
        clock = FakeClock()
        callbacks, writes, clears, cleanups, _, _, _, _ = self.make_callbacks(
            clock=clock
        )
        controller = self.controller(clock, callbacks)
        with self.assertRaises(KeyboardInterrupt):
            controller.run(
                lambda attempt: (_ for _ in ()).throw(KeyboardInterrupt())
            )
        self.assertEqual(len(cleanups), 1)
        self.assertFalse(clears)
        self.assertEqual(writes[-1]["status"], "attempting")


class CooldownAndRedactionTests(unittest.TestCase):
    def test_newer_domain_cooldown_is_not_cleared_by_older_wait(self) -> None:
        clock = FakeClock(now=100)
        registry = DomainCooldownRegistry(clock=clock, waiter=clock.wait)
        registry.extend("WWW.AMAZON.COM", 200)
        registry.extend("www.amazon.com", 250)
        registry.release("www.amazon.com", 200)
        self.assertEqual(registry.deadline("www.amazon.com"), 250)
        heartbeats = []
        registry.wait(
            "www.amazon.com",
            lambda domain, remaining: heartbeats.append((domain, remaining)),
        )
        self.assertEqual(clock.waits, [60.0, 60.0, 30.0])
        self.assertEqual(registry.remaining("www.amazon.com"), 0)
        self.assertTrue(all(item[0] == "www.amazon.com" for item in heartbeats))

    def test_sensitive_error_and_url_parts_are_sanitized(self) -> None:
        value = redact_error(
            "HTTP failed Authorization: Bearer abc123 api_key=secret token=also-secret"
        )
        self.assertNotIn("abc123", value)
        self.assertNotIn("also-secret", value)
        self.assertNotIn("api_key=secret", value)
        self.assertEqual(
            sanitize_state_url("https://user:pass@amazon.com/dp/X?q=1#token"),
            "https://amazon.com/dp/X?q=1",
        )


if __name__ == "__main__":
    unittest.main()
