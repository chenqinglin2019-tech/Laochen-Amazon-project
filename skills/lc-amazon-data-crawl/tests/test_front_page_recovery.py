from __future__ import annotations

import copy
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_front_crawler as front


ZERO_RETRY_SCHEDULE = ((0.0, 0.0),) * 4
REAL_RETRY_CONTROLLER = front.AmazonPageRetryController


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = float(now)
        self.waits: list[float] = []
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self.now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.now += float(seconds)

    def wait(self, seconds: float) -> None:
        self.waits.append(float(seconds))
        self.advance(seconds)


class LowerBoundRng:
    def uniform(self, minimum: float, _maximum: float) -> float:
        return float(minimum)


class FakeOwnedDriver:
    def __init__(self, url: str) -> None:
        self.current_url = url
        self.ensure_calls = 0
        self.snapshot_calls = 0
        self.cleanup_snapshots: list[frozenset[str]] = []
        self.restore_calls = 0
        self.quit_calls = 0

    def ensure_worker_page(self) -> str:
        self.ensure_calls += 1
        return "worker"

    def owned_handle_snapshot(self) -> frozenset[str]:
        self.snapshot_calls += 1
        return frozenset({"worker", f"existing-{self.snapshot_calls}"})

    def close_owned_since(self, snapshot: frozenset[str]) -> int:
        self.cleanup_snapshots.append(frozenset(snapshot))
        return 0

    def restore_worker_page(self) -> str:
        self.restore_calls += 1
        return "worker"

    def quit(self) -> None:
        self.quit_calls += 1


class FakeThrottle:
    def __init__(self) -> None:
        self.calls = 0

    def wait(self, _stop_event: object = None) -> None:
        self.calls += 1


class GateStopEvent:
    """A stop-event double that exposes cooldown waiting without real sleep."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.entered = threading.Event()
        self.release = threading.Event()
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return False

    def wait(self, seconds: float) -> bool:
        self.waits.append(float(seconds))
        self.entered.set()
        if not self.release.wait(timeout=2.0):
            return True
        self.clock.advance(seconds)
        return False


def make_runtime(root: Optional[Path] = None) -> SimpleNamespace:
    return SimpleNamespace(
        mode="keyword_search",
        job_id="front-recovery-test",
        outputs_root=root or Path(tempfile.gettempdir()),
        include_sponsored=False,
        max_pages_per_keyword=1,
        store_page_limit=1,
        sellersprite_required=False,
        field_selectors={},
        product_filters=front.ProductFilterConfig(),
        record_contract_fingerprint="front-recovery-contract-v1",
        delivery_location_fingerprint="front-recovery-delivery-v1",
        resume=False,
        save_debug_snapshots=False,
        manual_pause_timeout=1,
        amazon_page_retry_schedule_seconds=ZERO_RETRY_SCHEDULE,
    )


def make_task(source_id: str = "test|sort:Featured") -> dict[str, Any]:
    return {
        "source_type": "keyword_search",
        "source_id": source_id,
        "keyword": "test",
        "search_sort_order": "Featured",
        "page_number": 1,
        "page_url": "https://www.amazon.com/s?k=test",
    }


def make_success_result(
    worker_id: str,
    task: dict[str, Any],
    *,
    finish_reason: str = "page_limit_reached",
) -> front.FrontPageResult:
    return front.FrontPageResult(
        worker_id=worker_id,
        task=copy.deepcopy(task),
        page_key=front.front_page_key(task, str(task["page_url"])),
        page_url=str(task["page_url"]),
        raw_records=[{"asin": "B000000001"}],
        accepted_records=[{"asin": "B000000001"}],
        rejection_counts={},
        plugin_status="not_required",
        next_task=None,
        finish_reason=finish_reason,
    )


def make_worker(
    runtime: SimpleNamespace,
    *,
    worker_id: str = "tab-1",
    driver: Optional[FakeOwnedDriver] = None,
    cooldowns: Optional[front.DomainCooldownRegistry] = None,
    throttle: Optional[object] = None,
) -> front.FrontWorker:
    worker = front.FrontWorker(
        worker_id,
        runtime,
        queue.Queue(),
        front.ManualActionCoordinator(),
        throttle or front.NavigationThrottle(0, 0),
        front.DeliveryDomainLocks(),
        Path(tempfile.gettempdir()),
        domain_cooldowns=cooldowns,
    )
    worker.driver = driver
    return worker


def controller_patch(clock: FakeClock):
    def build_controller(**kwargs: Any):
        kwargs["clock"] = clock
        kwargs["waiter"] = clock.wait
        kwargs["rng"] = LowerBoundRng()
        return REAL_RETRY_CONTROLLER(**kwargs)

    return patch.object(
        front,
        "AmazonPageRetryController",
        side_effect=build_controller,
    )


class FrontPageRecoveryIntegrationTests(unittest.TestCase):
    def test_first_failure_counts_as_attempt_one_and_exhausts_after_total_five(self) -> None:
        clock = FakeClock()
        worker = make_worker(make_runtime())
        task = make_task()
        attempts: list[int] = []

        def fail(_task: dict[str, Any]) -> front.FrontPageResult:
            attempts.append(len(attempts) + 1)
            raise front.TransientAmazonPageUnavailable(
                "dog page",
                reason="amazon_dog_error",
                url=str(task["page_url"]),
            )

        with (
            controller_patch(clock),
            patch.object(worker, "_process_attempt", side_effect=fail),
        ):
            result = worker._process(task)

        self.assertEqual(attempts, [1, 2, 3, 4, 5])
        self.assertEqual(
            result.error_reason,
            "amazon_page_unavailable_retry_exhausted",
        )
        self.assertTrue(result.fatal)
        self.assertTrue(worker.recovery_halted.is_set())
        self.assertEqual(worker._local_retry_state["status"], "manual_resume_required")
        self.assertEqual(worker._local_retry_state["attempts_completed"], 5)
        self.assertEqual(
            worker._local_retry_state["failure_code"],
            result.error_reason,
        )
        self.assertEqual(clock.waits, [])

    def test_owned_attempt_scope_is_cleaned_after_each_of_five_failures(self) -> None:
        clock = FakeClock()
        task = make_task()
        driver = FakeOwnedDriver(str(task["page_url"]))
        worker = make_worker(make_runtime(), driver=driver)

        def transient(_current: dict[str, Any]) -> front.PageHealthStatus:
            raise front.TransientAmazonPageUnavailable(
                "blank page",
                reason="blank_page",
                url=str(task["page_url"]),
            )

        with (
            controller_patch(clock),
            patch.object(worker, "_open_page"),
            patch.object(worker, "_wait_for_page_or_manual", side_effect=transient),
        ):
            result = worker._process(task)

        self.assertEqual(
            result.error_reason,
            "amazon_page_unavailable_retry_exhausted",
        )
        self.assertEqual(driver.ensure_calls, 5)
        self.assertEqual(driver.snapshot_calls, 5)
        self.assertEqual(len(driver.cleanup_snapshots), 5)
        self.assertEqual(
            driver.cleanup_snapshots,
            [
                frozenset({"worker", f"existing-{index}"})
                for index in range(1, 6)
            ],
        )

    def test_explicit_empty_commits_zero_records_but_ambiguous_empty_retries(self) -> None:
        explicit = front.classify_page_snapshot(
            front.PageSnapshot(
                page_kind="search_category",
                body_text="No results for test",
                explicit_empty=True,
            )
        )
        ambiguous = front.classify_page_snapshot(
            front.PageSnapshot(
                page_kind="search_category",
                title="Amazon search",
                body_text="navigation shell",
            )
        )
        self.assertEqual(explicit.status, front.PageHealthStatus.VERIFIED_EMPTY)
        self.assertEqual(
            ambiguous.status,
            front.PageHealthStatus.TRANSIENT_UNAVAILABLE,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = make_runtime(root)
            task = make_task("explicit|sort:Featured")
            state = front.FrontStateStore(root / "state.json", runtime, [task])
            state.load_or_create()
            leased = state.lease_next("tab-explicit")
            self.assertIsNotNone(leased)
            driver = FakeOwnedDriver(str(task["page_url"]))
            worker = make_worker(
                runtime,
                worker_id="tab-explicit",
                driver=driver,
            )
            with (
                controller_patch(FakeClock()),
                patch.object(worker, "_open_page"),
                patch.object(front, "detect_block", return_value=None),
                patch.object(front, "wait_for_product_cards", return_value=False),
                patch.object(front, "assess_front_page", return_value=explicit),
            ):
                result = worker._process(leased or task)

            self.assertFalse(result.error_reason)
            self.assertEqual(result.raw_records, [])
            self.assertEqual(result.accepted_records, [])
            self.assertEqual(result.finish_reason, "explicit_no_results")
            self.assertTrue(state.commit_page_result(result))
            payload = state.iter_page_results()[0]
            self.assertEqual(payload["scanned_count"], 0)
            self.assertEqual(payload["records"], [])
            self.assertEqual(payload["finish_reason"], "explicit_no_results")

        ambiguous_task = make_task("ambiguous|sort:Featured")
        ambiguous_driver = FakeOwnedDriver(str(ambiguous_task["page_url"]))
        ambiguous_worker = make_worker(
            make_runtime(),
            worker_id="tab-ambiguous",
            driver=ambiguous_driver,
        )
        with (
            controller_patch(FakeClock()),
            patch.object(ambiguous_worker, "_open_page"),
            patch.object(front, "detect_block", return_value=None),
            patch.object(front, "wait_for_product_cards", return_value=False),
            patch.object(
                front,
                "assess_front_page",
                return_value=ambiguous,
            ) as assessor,
        ):
            ambiguous_result = ambiguous_worker._process(ambiguous_task)

        self.assertEqual(assessor.call_count, 5)
        self.assertEqual(
            ambiguous_result.error_reason,
            "amazon_page_unavailable_retry_exhausted",
        )
        self.assertEqual(ambiguous_result.page_key, "")
        self.assertEqual(ambiguous_result.raw_records, [])
        self.assertEqual(
            ambiguous_worker._local_retry_state["status"],
            "manual_resume_required",
        )

    def test_transient_page_is_classified_before_delivery_setup(self) -> None:
        runtime = make_runtime()
        runtime.delivery_location_enabled = True
        task = make_task("dog-before-delivery|sort:Featured")
        driver = FakeOwnedDriver(str(task["page_url"]))
        worker = make_worker(
            runtime,
            worker_id="tab-dog-before-delivery",
            driver=driver,
        )
        with (
            controller_patch(FakeClock()),
            patch.object(worker, "_open_page"),
            patch.object(
                worker,
                "_wait_for_page_or_manual",
                side_effect=front.TransientAmazonPageUnavailable(
                    "amazon dog page",
                    reason="amazon_dog_error",
                    url=str(task["page_url"]),
                ),
            ),
            patch.object(worker, "_ensure_delivery_after_healthy_page") as delivery,
        ):
            result = worker._process(task)

        self.assertEqual(
            result.error_reason,
            "amazon_page_unavailable_retry_exhausted",
        )
        self.assertEqual(delivery.call_count, 0)

    def test_saved_waiting_deadline_and_manual_resume_are_honored(self) -> None:
        task = make_task()
        identity = front.front_task_identity(task)
        stage = "front_search_or_category_page"

        waiting_clock = FakeClock(now=100.0)
        waiting_worker = make_worker(make_runtime(), worker_id="tab-waiting")
        waiting_worker._local_retry_state = {
            "status": "waiting",
            "domain": "www.amazon.com",
            "work_key": identity,
            "stage": stage,
            "cycle": 2,
            "attempts_completed": 1,
            "next_attempt": 2,
            "selected_wait_seconds": 25.0,
            "next_retry_at": 125.0,
            "remaining_wait_seconds": 25.0,
            "url": str(task["page_url"]),
            "error": "dog page",
        }
        waiting_writes: list[dict[str, Any]] = []
        original_waiting_request = waiting_worker._retry_request

        def record_waiting(event_type: str, **kwargs: Any):
            if event_type == "write":
                waiting_writes.append(copy.deepcopy(kwargs.get("value") or {}))
            return original_waiting_request(event_type, **kwargs)

        waiting_worker._retry_request = record_waiting  # type: ignore[method-assign]
        waiting_success = make_success_result("tab-waiting", task)
        with (
            controller_patch(waiting_clock),
            patch.object(
                waiting_worker,
                "_process_attempt",
                return_value=waiting_success,
            ) as operation,
        ):
            result = waiting_worker._process(task)

        self.assertIs(result, waiting_success)
        self.assertEqual(waiting_clock.waits, [25.0])
        self.assertEqual(operation.call_count, 1)
        attempting = [
            value for value in waiting_writes if value.get("status") == "attempting"
        ]
        self.assertEqual(attempting[-1]["cycle"], 2)
        self.assertEqual(attempting[-1]["next_attempt"], 2)
        self.assertIsNone(waiting_worker._local_retry_state)

        resume_clock = FakeClock(now=500.0)
        resume_worker = make_worker(make_runtime(), worker_id="tab-resume")
        resume_worker._local_retry_state = {
            "status": "manual_resume_required",
            "domain": "www.amazon.com",
            "work_key": identity,
            "stage": stage,
            "cycle": 4,
            "attempts_completed": 5,
            "next_attempt": 1,
            "url": str(task["page_url"]),
            "failure_code": "amazon_page_unavailable_retry_exhausted",
        }
        resume_writes: list[dict[str, Any]] = []
        resume_clears: list[bool] = []
        original_resume_request = resume_worker._retry_request

        def record_resume(event_type: str, **kwargs: Any):
            if event_type == "write":
                resume_writes.append(copy.deepcopy(kwargs.get("value") or {}))
            elif event_type == "clear":
                resume_clears.append(True)
            return original_resume_request(event_type, **kwargs)

        resume_worker._retry_request = record_resume  # type: ignore[method-assign]
        resume_success = make_success_result("tab-resume", task)
        with (
            controller_patch(resume_clock),
            patch.object(
                resume_worker,
                "_process_attempt",
                return_value=resume_success,
            ),
        ):
            resumed = resume_worker._process(task)

        self.assertIs(resumed, resume_success)
        attempting = [
            value for value in resume_writes if value.get("status") == "attempting"
        ]
        self.assertEqual(attempting[-1]["cycle"], 5)
        self.assertEqual(attempting[-1]["next_attempt"], 1)
        self.assertEqual(len(resume_clears), 2)
        self.assertIsNone(resume_worker._local_retry_state)

    def test_domain_cooldown_blocks_new_navigation_not_local_result_commit(self) -> None:
        clock = FakeClock(now=100.0)
        cooldowns = front.DomainCooldownRegistry(clock=clock, waiter=clock.wait)
        cooldowns.extend("www.amazon.com", 102.0)
        throttle = FakeThrottle()
        worker = make_worker(
            make_runtime(),
            worker_id="tab-navigation",
            cooldowns=cooldowns,
            throttle=throttle,
        )
        gate = GateStopEvent(clock)
        worker.stop_event = gate  # type: ignore[assignment]
        errors: list[BaseException] = []

        def navigate() -> None:
            try:
                worker._before_navigation("https://www.amazon.com/s?k=blocked")
            except BaseException as exc:  # pragma: no cover - diagnostic path
                errors.append(exc)

        thread = threading.Thread(target=navigate, daemon=True)
        thread.start()
        self.assertTrue(gate.entered.wait(timeout=1.0))
        self.assertTrue(thread.is_alive())
        self.assertEqual(throttle.calls, 0)

        # A result whose page is already loaded performs only local atomic
        # state/file work, so it remains committable while new navigation waits.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = make_runtime(root)
            ready_task = make_task("ready|sort:Featured")
            state = front.FrontStateStore(root / "state.json", runtime, [ready_task])
            state.load_or_create()
            leased = state.lease_next("tab-ready")
            self.assertIsNotNone(leased)
            ready_result = make_success_result("tab-ready", leased or ready_task)
            self.assertTrue(state.commit_page_result(ready_result))
            self.assertEqual(state.data["records_count"], 1)

        gate.release.set()
        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(gate.waits, [1.0, 1.0])
        self.assertEqual(throttle.calls, 1)


if __name__ == "__main__":
    unittest.main()
