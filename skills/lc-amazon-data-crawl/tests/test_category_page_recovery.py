from __future__ import annotations

import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_category_rank_crawler as category
from amazon_page_recovery import (
    AmazonPageRetryExhausted,
    DEFAULT_RETRY_SCHEDULE_SECONDS,
    DomainCooldownRegistry,
    PageHealthStatus,
    RetryCallbacks,
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


class LowerRng:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    def uniform(self, minimum: float, maximum: float) -> float:
        self.calls.append((minimum, maximum))
        return minimum


class ForbiddenRng:
    def uniform(self, minimum: float, maximum: float) -> float:
        raise AssertionError("a persisted wait must not be sampled again")


class FakeElement:
    def __init__(self, text: str = "") -> None:
        self.text = text


class FakeCategoryDriver:
    def __init__(self, scenarios: list[dict]) -> None:
        self.scenarios = list(scenarios)
        self.current: dict = {}
        self.current_url = "about:blank"
        self.get_calls: list[str] = []
        self.snapshots: list[frozenset[str]] = []
        self.closed_since: list[frozenset[str]] = []
        self.restore_count = 0

    @property
    def title(self) -> str:
        return str(self.current.get("title") or "")

    def get(self, url: str) -> None:
        self.get_calls.append(url)
        index = min(len(self.get_calls) - 1, len(self.scenarios) - 1)
        self.current = dict(self.scenarios[index])
        self.current_url = str(self.current.get("url") or url)
        error = self.current.get("navigation_error")
        if error:
            raise category.WebDriverException(str(error))

    def find_element(self, by: str, value: str | None = None) -> FakeElement:
        if by == category.By.TAG_NAME and value == "body":
            return FakeElement(str(self.current.get("body") or ""))
        if by == category.By.CSS_SELECTOR and self.current.get("expected"):
            return FakeElement("product")
        raise category.NoSuchElementException("missing")

    def owned_handle_snapshot(self) -> frozenset[str]:
        snapshot = frozenset({"worker"})
        self.snapshots.append(snapshot)
        return snapshot

    def close_owned_since(self, snapshot: frozenset[str]) -> int:
        self.closed_since.append(snapshot)
        return 0

    def restore_worker_page(self) -> str:
        self.restore_count += 1
        return "worker"


def dog_page() -> dict:
    return {
        "title": "Amazon.com",
        "body": "Sorry, something went wrong on our end. Meet the dogs of Amazon.",
    }


def healthy_page() -> dict:
    return {
        "title": "Best Sellers",
        "body": "Real ranking content",
        "expected": True,
    }


def runtime(clock: FakeClock, rng=None, waiter=None, schedule=None) -> SimpleNamespace:
    return SimpleNamespace(
        page_timeout=1,
        manual_pause_timeout=1,
        delivery_location_enabled=False,
        amazon_page_retry_schedule=schedule or DEFAULT_RETRY_SCHEDULE_SECONDS,
        _amazon_page_retry_clock=clock,
        _amazon_page_retry_rng=rng or LowerRng(),
        _amazon_page_retry_waiter=waiter or clock.wait,
        save_debug_snapshots=False,
        start_url="https://www.amazon.com/gp/bestsellers/home/1000",
    )


class CategoryRecoveryConfigTests(unittest.TestCase):
    def base_config(self) -> dict:
        return {
            "start_url": "https://www.amazon.com/gp/bestsellers/home/1000",
            "browser_backend": "cdp",
            "browser_mode": "reuse",
            "browser_tab_concurrency": 1,
            "delivery_location_enabled": False,
        }

    def test_runtime_uses_shared_default_schedule(self) -> None:
        configured = category.build_runtime_config(
            self.base_config(),
            SKILL_ROOT / "unused.json",
            False,
        )
        self.assertEqual(
            configured.amazon_page_retry_schedule,
            tuple((float(a), float(b)) for a, b in DEFAULT_RETRY_SCHEDULE_SECONDS),
        )

    def test_runtime_rejects_non_strict_schedule_during_dry_run_config_build(self) -> None:
        invalid_values = (
            None,
            [[1, 1]] * 3,
            [[True, 1]] * 4,
            [[2, 1]] * 4,
            [[float("inf"), float("inf")]] * 4,
        )
        for value in invalid_values:
            raw = self.base_config()
            raw["amazon_page_unavailable_retry_schedule_seconds"] = value
            with self.subTest(value=value):
                with self.assertRaises(category.UserFacingError):
                    category.build_runtime_config(
                        raw,
                        SKILL_ROOT / "unused.json",
                        False,
                    )


class CategoryRecoveryIntegrationTests(unittest.TestCase):
    page_url = "https://www.amazon.com/gp/bestsellers/home/1000"
    work_key = "node:1000|page:1|https://www.amazon.com/gp/bestsellers/home/1000"

    def load(
        self,
        driver: FakeCategoryDriver,
        configured_runtime: SimpleNamespace,
        callbacks: RetryCallbacks | None = None,
        **kwargs,
    ):
        with patch.object(
            category,
            "wait_for_amazon_products",
            side_effect=category.TimeoutException("timeout"),
        ):
            return category.load_category_page_with_recovery(
                driver,
                self.page_url,
                configured_runtime,
                self.work_key,
                retry_callbacks=callbacks or RetryCallbacks(),
                **kwargs,
            )

    def test_four_dog_pages_back_off_then_fifth_attempt_succeeds(self) -> None:
        clock = FakeClock()
        rng = LowerRng()
        driver = FakeCategoryDriver([dog_page()] * 4 + [healthy_page()])
        assessment = self.load(driver, runtime(clock, rng=rng))

        self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)
        self.assertEqual(len(driver.get_calls), 5)
        self.assertEqual(
            rng.calls,
            [(180.0, 300.0), (180.0, 300.0), (1800.0, 1800.0), (3600.0, 3600.0)],
        )
        self.assertEqual(sum(clock.waits), 5760.0)
        self.assertTrue(all(seconds <= 60 for seconds in clock.waits))
        self.assertEqual(len(driver.snapshots), 5)
        self.assertEqual(len(driver.closed_since), 5)
        self.assertGreaterEqual(driver.restore_count, 5)

    def test_navigation_errors_and_blank_timeout_use_the_same_recovery(self) -> None:
        clock = FakeClock()
        scenarios = [
            {"navigation_error": "net::ERR_TIMED_OUT"},
            {},
            healthy_page(),
        ]
        driver = FakeCategoryDriver(scenarios)
        assessment = self.load(
            driver,
            runtime(
                clock,
                schedule=((0, 0), (0, 0), (0, 0), (0, 0)),
            ),
        )
        self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)
        self.assertEqual(len(driver.get_calls), 3)

    def test_delivery_reopen_dog_page_returns_to_shared_recovery(self) -> None:
        driver = FakeCategoryDriver([dog_page()])
        with self.assertRaises(category.TransientAmazonPageUnavailable) as caught:
            category._reopen_amazon_target(
                driver,
                self.page_url,
                runtime(FakeClock()),
                None,
                None,
            )
        self.assertEqual(caught.exception.reason, "amazon_dog_error")

    def test_429_and_503_pages_enter_automatic_recovery(self) -> None:
        clock = FakeClock()
        driver = FakeCategoryDriver(
            [
                {"title": "429 Too Many Requests", "body": "429 Too Many Requests"},
                {"title": "503 Service Unavailable", "body": "503 Service Unavailable"},
                healthy_page(),
            ]
        )
        assessment = self.load(
            driver,
            runtime(
                clock,
                schedule=((0, 0), (0, 0), (0, 0), (0, 0)),
            ),
        )
        self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)
        self.assertEqual(len(driver.get_calls), 3)

    def test_explicit_no_results_is_a_legal_empty_page_without_retry(self) -> None:
        clock = FakeClock()
        driver = FakeCategoryDriver(
            [{"title": "Amazon", "body": "There are no products in this category."}]
        )
        with patch.object(category, "wait_for_amazon_products") as wait_for_products:
            assessment = category.load_category_page_with_recovery(
                driver,
                self.page_url,
                runtime(clock),
                self.work_key,
                retry_callbacks=RetryCallbacks(),
            )
        self.assertEqual(assessment.status, PageHealthStatus.VERIFIED_EMPTY)
        wait_for_products.assert_not_called()
        self.assertEqual(len(driver.get_calls), 1)

    def test_normal_product_dom_with_sorry_is_healthy(self) -> None:
        clock = FakeClock()
        driver = FakeCategoryDriver(
            [
                {
                    "title": "Best Sellers",
                    "body": "Sorry, this color is unavailable, but the product is listed.",
                    "expected": True,
                }
            ]
        )
        assessment = self.load(driver, runtime(clock))
        self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)
        self.assertEqual(len(driver.get_calls), 1)

    def test_amazon_sign_in_is_terminal_and_never_backed_off(self) -> None:
        clock = FakeClock()
        driver = FakeCategoryDriver(
            [
                {
                    "url": "https://www.amazon.com/ap/signin",
                    "title": "Amazon Sign-In",
                    "body": "Sign in",
                }
            ]
        )
        paused = []
        with self.assertRaises(category.VerificationUnconfirmedError):
            self.load(
                driver,
                runtime(clock),
                on_manual_pause=lambda reason, url: paused.append((reason, url)),
            )
        self.assertEqual(len(driver.get_calls), 1)
        self.assertEqual(clock.waits, [])
        self.assertEqual(paused[0][0], "amazon_sign_in")

    def test_captcha_keeps_manual_flow_then_continues_same_attempt(self) -> None:
        clock = FakeClock()
        driver = FakeCategoryDriver(
            [
                {
                    "url": "https://www.amazon.com/errors/validateCaptcha",
                    "title": "Robot Check",
                    "body": "Enter the characters you see",
                }
            ]
        )
        paused = []
        resumed = []

        def clear_captcha(_driver, _reason, _timeout, **_kwargs):
            driver.current = healthy_page()
            driver.current_url = self.page_url
            return True

        with patch.object(category, "wait_for_manual_clear", side_effect=clear_captcha):
            assessment = self.load(
                driver,
                runtime(clock),
                on_manual_pause=lambda reason, url: paused.append((reason, url)),
                on_manual_resume=lambda: resumed.append(True),
            )
        self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)
        self.assertEqual(len(driver.get_calls), 1)
        self.assertEqual(paused[0][0], "amazon_robot_check")
        self.assertEqual(resumed, [True])

    def test_existing_domain_cooldown_finishes_before_new_navigation(self) -> None:
        clock = FakeClock()
        registry = DomainCooldownRegistry(clock=clock, waiter=clock.wait)
        registry.extend("www.amazon.com", 1125)
        driver = FakeCategoryDriver([healthy_page()])
        assessment = self.load(
            driver,
            runtime(clock),
            domain_cooldowns=registry,
        )
        self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)
        self.assertEqual(clock.waits, [60.0, 60.0, 5.0])
        self.assertEqual(len(driver.get_calls), 1)

    def test_whole_page_transaction_retries_extraction_and_pagination_failures(self) -> None:
        clock = FakeClock()
        driver = FakeCategoryDriver([healthy_page()])
        calls = []

        def operation(attempt):
            calls.append(attempt.attempt_number)
            if attempt.attempt_number < 5:
                raise category.WebDriverException("pagination context lost")
            return category.CategoryPageWorkResult(
                node={"url": self.page_url, "path": ["Home"]},
                next_url="",
            )

        result = category.run_category_page_work_with_recovery(
            runtime(clock),
            self.page_url,
            self.work_key,
            retry_callbacks=RetryCallbacks(),
            driver_provider=lambda: driver,
            operation=operation,
        )
        self.assertEqual(result.node["path"], ["Home"])
        self.assertEqual(calls, [1, 2, 3, 4, 5])
        self.assertEqual(sum(clock.waits), 5760.0)
        self.assertTrue(all(seconds <= 60 for seconds in clock.waits))
        self.assertEqual(len(driver.closed_since), 5)


class CategoryRetryPersistenceTests(unittest.TestCase):
    page_url = CategoryRecoveryIntegrationTests.page_url
    work_key = CategoryRecoveryIntegrationTests.work_key

    def make_state(self, root: Path) -> category.StateStore:
        state = category.StateStore(root / "state.json", SimpleNamespace())
        state.data = {
            "queue": [],
            "in_flight_categories": {},
            "done_categories": [],
            "completed_pages": [],
        }
        state.flush()
        return state

    def load(
        self,
        driver: FakeCategoryDriver,
        configured_runtime: SimpleNamespace,
        callbacks: RetryCallbacks,
    ):
        with patch.object(
            category,
            "wait_for_amazon_products",
            side_effect=category.TimeoutException("timeout"),
        ):
            return category.load_category_page_with_recovery(
                driver,
                self.page_url,
                configured_runtime,
                self.work_key,
                retry_callbacks=callbacks,
            )

    def test_fifth_failure_persists_manual_resume_and_logs_once(self) -> None:
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state = self.make_state(root)
            retry_key = category._retry_entry_key(self.work_key, "category_page")
            callbacks = category.state_retry_callbacks(state, retry_key)
            driver = FakeCategoryDriver([dog_page()] * 5)
            with self.assertRaises(AmazonPageRetryExhausted) as raised:
                self.load(driver, runtime(clock), callbacks)

            stored = state.data["amazon_page_retry"]
            self.assertEqual(stored["status"], "manual_resume_required")
            self.assertEqual(stored["attempts_completed"], 5)
            self.assertEqual(len(driver.get_calls), 5)

            failures_path = root / "failures.jsonl"
            node = {
                "url": self.page_url,
                "name": "Home",
                "path": ["Home"],
                "node_id": "1000",
            }
            configured_runtime = runtime(clock)
            self.assertTrue(
                category.log_amazon_retry_exhausted_once(
                    failures_path,
                    state,
                    configured_runtime,
                    node,
                    1,
                    self.page_url,
                    raised.exception,
                )
            )
            self.assertFalse(
                category.log_amazon_retry_exhausted_once(
                    failures_path,
                    state,
                    configured_runtime,
                    node,
                    1,
                    self.page_url,
                    raised.exception,
                )
            )
            failures = category.read_jsonl(failures_path)
            self.assertEqual(len(failures), 1)
            self.assertEqual(
                failures[0]["reason"],
                "amazon_page_unavailable_retry_exhausted",
            )
            self.assertEqual(state.data["failures_count"], 1)

    def test_exhaustion_deduplication_includes_page_stage(self) -> None:
        clock = FakeClock()
        node = {
            "url": self.page_url,
            "name": "Home",
            "path": ["Home"],
            "node_id": "1000",
        }
        base = {
            "status": "manual_resume_required",
            "domain": "www.amazon.com",
            "work_key": self.work_key,
            "cycle": 1,
            "attempts_completed": 5,
        }
        first = AmazonPageRetryExhausted(
            {**base, "stage": "category_page"},
            category.TransientAmazonPageUnavailable("dog"),
        )
        second = AmazonPageRetryExhausted(
            {**base, "stage": "category_page_work"},
            category.TransientAmazonPageUnavailable("dog"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "failures.jsonl"
            configured_runtime = runtime(clock)
            first_record = category.build_amazon_retry_exhausted_failure_record(
                configured_runtime, node, 1, self.page_url, first
            )
            second_record = category.build_amazon_retry_exhausted_failure_record(
                configured_runtime, node, 1, self.page_url, second
            )
            self.assertTrue(category.append_failure_record_once(path, first_record))
            self.assertTrue(category.append_failure_record_once(path, second_record))
            self.assertFalse(category.append_failure_record_once(path, second_record))
            self.assertEqual(len(category.read_jsonl(path)), 2)

    def test_same_command_after_manual_pause_starts_new_cycle(self) -> None:
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            state = self.make_state(Path(temp_dir))
            retry_key = category._retry_entry_key(self.work_key, "category_page")
            base = category.state_retry_callbacks(state, retry_key)
            written_cycles = []
            callbacks = RetryCallbacks(
                load_state=base.load_state,
                write_state=lambda value: (
                    written_cycles.append((value["status"], value["cycle"])),
                    base.write_state(value),
                ),
                clear_state=base.clear_state,
            )
            with self.assertRaises(AmazonPageRetryExhausted):
                self.load(
                    FakeCategoryDriver([dog_page()] * 5),
                    runtime(
                        clock,
                        schedule=((0, 0), (0, 0), (0, 0), (0, 0)),
                    ),
                    callbacks,
                )
            assessment = self.load(
                FakeCategoryDriver([healthy_page()]),
                runtime(clock),
                callbacks,
            )
            self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)
            self.assertIn(("attempting", 2), written_cycles)
            self.assertNotIn("amazon_page_retry", state.data)

    def test_keyboard_interrupt_during_wait_keeps_deadline_for_restart(self) -> None:
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            state = self.make_state(Path(temp_dir))
            retry_key = category._retry_entry_key(self.work_key, "category_page")
            callbacks = category.state_retry_callbacks(state, retry_key)

            def interrupt(_seconds):
                raise KeyboardInterrupt()

            first_runtime = runtime(clock, waiter=interrupt)
            with self.assertRaises(KeyboardInterrupt):
                self.load(
                    FakeCategoryDriver([dog_page()]),
                    first_runtime,
                    callbacks,
                )
            stored = state.load_amazon_page_retry(retry_key)
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored["status"], "waiting")
            self.assertEqual(stored["next_attempt"], 2)
            self.assertEqual(stored["next_retry_at"], 1180.0)

            resumed_runtime = runtime(clock, rng=ForbiddenRng(), waiter=clock.wait)
            assessment = self.load(
                FakeCategoryDriver([healthy_page()]),
                resumed_runtime,
                callbacks,
            )
            self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)
            self.assertEqual(clock.waits, [60.0, 60.0, 60.0])
            self.assertNotIn("amazon_page_retry", state.data)

    def test_concurrent_worker_events_ack_atomic_state_before_return(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = self.make_state(Path(temp_dir))
            events: "queue.Queue[dict]" = queue.Queue()
            stop_event = threading.Event()
            callbacks = category.worker_retry_callbacks(
                events,
                stop_event,
                "retry-entry",
            )
            sample = {
                "status": "waiting",
                "domain": "www.amazon.com",
                "work_key": "page-1",
                "stage": "category_page",
                "cycle": 1,
                "attempts_completed": 1,
                "next_attempt": 2,
                "selected_wait_seconds": 180,
                "next_retry_at": 1180,
                "url": self.page_url,
                "error": "dog",
            }
            finished = threading.Event()

            def writer() -> None:
                callbacks.write_state(sample)
                finished.set()

            thread = threading.Thread(target=writer)
            thread.start()
            self.assertFalse(finished.wait(0.05))
            category._drain_worker_events(events, state)
            thread.join(timeout=1)
            self.assertTrue(finished.is_set())
            self.assertEqual(
                state.load_amazon_page_retry("retry-entry")["next_retry_at"],
                1180,
            )

            loaded = []
            loader = threading.Thread(target=lambda: loaded.append(callbacks.load_state()))
            loader.start()
            category._drain_worker_events(events, state)
            loader.join(timeout=1)
            self.assertEqual(loaded[0]["work_key"], "page-1")


if __name__ == "__main__":
    unittest.main()
