"""Round-1b review fixes, front crawler: P1-3 (environment vs item failures),
P2-1 (per-item rate-probe schedule), P2-2 (export never replaces the outcome),
P2-7, P2-8, P2-9, P2-12c, P2-13a/b, P2-14 and replace_with_retry.

Offline only: fake drivers/workers, temp dirs, no browser, no network.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import queue
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_front_crawler as front
import run_outcome
from safety_control import LocalSafetyController, SafetyPausedError
from selenium.common.exceptions import TimeoutException


REAL_RETRY_CONTROLLER = front.AmazonPageRetryController
EXHAUSTED = front.AmazonPageRetryExhausted.failure_code


# ---------------------------------------------------------------------------
# helpers


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def wait(self, seconds: float) -> None:
        self.now += float(seconds)


def fast_controller():
    clock = FakeClock()

    def build(**kwargs: Any):
        kwargs["clock"] = clock
        kwargs["waiter"] = clock.wait
        return REAL_RETRY_CONTROLLER(**kwargs)

    return patch.object(front, "AmazonPageRetryController", side_effect=build)


def worker_runtime(schedule=((0.0, 0.0),), *, safety=None, mode: str = "supervised") -> SimpleNamespace:
    return SimpleNamespace(
        mode="keyword_search",
        include_sponsored=False,
        sellersprite_required=False,
        field_selectors={},
        product_filters=front.ProductFilterConfig(),
        save_debug_snapshots=False,
        manual_pause_timeout=1,
        amazon_page_retry_schedule_seconds=schedule,
        operation_mode=mode,
        safety=safety,
    )


def make_task(keyword: str = "alpha") -> Dict[str, Any]:
    return {
        "source_type": "keyword_search",
        "source_id": f"{keyword}|sort:Featured",
        "keyword": keyword,
        "search_sort_order": "Featured",
        "page_number": 1,
        "page_url": f"https://www.amazon.com/s?k={keyword}",
    }


def make_worker(runtime: Any, driver: Any = None) -> front.FrontWorker:
    worker = front.FrontWorker(
        "tab-1",
        runtime,
        queue.Queue(),
        front.ManualActionCoordinator(),
        front.NavigationThrottle(0, 0),
        front.DeliveryDomainLocks(),
        Path(tempfile.gettempdir()),
    )
    worker.driver = driver
    return worker


def transient(reason: str = "page_timeout", message: str = "Message: timeout") -> front.TransientAmazonPageUnavailable:
    return front.TransientAmazonPageUnavailable(message, reason=reason, url="https://www.amazon.com/s?k=alpha")


def counting_failure(attempts: List[int], error_factory: Callable[[], BaseException], before: Optional[Callable[[], None]] = None):
    def fail(_task: Dict[str, Any]) -> front.FrontPageResult:
        attempts.append(len(attempts) + 1)
        if before is not None and len(attempts) == 1:
            before()
        raise error_factory()

    return fail


def safety_with_pause(root: Path, kind: str, *, mode: str = "unattended", resume_after_review: bool = False) -> LocalSafetyController:
    safety = LocalSafetyController(root, mode=mode)
    safety._wait_until = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    past = (dt.datetime.now() - dt.timedelta(hours=1)).replace(microsecond=0).isoformat()
    safety._write_pause({
        "active": True, "platform": "amazon", "reason": "http_429" if kind == "rate_probe" else "http_403",
        "kind": kind, "not_before": past, "review_required": kind != "rate_probe",
    })
    safety.begin(resume_after_review=resume_after_review)
    return safety


def loop_runtime(tmp: str, mode: str, keywords: List[str], **extra: Any) -> front.FrontRuntimeConfig:
    keywords_file = Path(tmp) / "keywords.csv"
    keywords_file.write_text("keyword\n" + "\n".join(keywords) + "\n", encoding="utf-8")
    raw = {
        "mode": "keyword_search",
        "job_id": "round1b-job",
        "outputs_root": str(Path(tmp) / "outputs"),
        "keywords_file": str(keywords_file),
        "operation_mode": mode,
        "delivery_location_enabled": False,
    }
    raw.update(extra)
    return front.build_front_runtime_config(raw, no_resume=False)


def ok_result(worker_id: str, task: Dict[str, Any]) -> front.FrontPageResult:
    url = str(task.get("page_url") or "")
    record = {"asin": "B0" + task["keyword"].upper().ljust(8, "X")[:8], "keyword": task["keyword"]}
    return front.FrontPageResult(
        worker_id=worker_id, task=task, page_key=front.front_page_key(task, url), page_url=url,
        raw_records=[record], accepted_records=[record], plugin_status="ok", finish_reason="no_next_page",
    )


def failed_result(worker_id: str, task: Dict[str, Any], reason: str, detail: str = "",
                  message: str = "页面失败。") -> front.FrontPageResult:
    return front.FrontPageResult(
        worker_id=worker_id, task=task, page_url=str(task.get("page_url") or ""),
        error_reason=reason, error_message=message, error_detail=detail, fatal=True,
    )


def fake_worker_class(behaviour: Callable[[str, Dict[str, Any]], front.FrontPageResult], seen: List[str]):
    class FakeWorker:
        def __init__(self, worker_id, runtime, results, *_args, **_kwargs) -> None:  # noqa: ARG002
            self.worker_id = worker_id
            self.results = results

        def start(self) -> None:
            pass

        def submit(self, task) -> None:
            seen.append(task["keyword"])
            self.results.put(behaviour(self.worker_id, task))

        def stop(self) -> None:
            pass

        def join(self, timeout=None) -> bool:
            return True

        def is_alive(self) -> bool:
            return True

    return FakeWorker


class NoBatchPause:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def after_completed_page(self) -> None:
        pass


def run_loop(runtime, behaviour, *extra_patches) -> tuple[Optional[BaseException], List[str], str, str]:
    seen: List[str] = []
    out, err = io.StringIO(), io.StringIO()
    error: Optional[BaseException] = None
    with (
        patch.object(front, "FrontWorker", fake_worker_class(behaviour, seen)),
        patch.object(front, "BatchPauseScheduler", NoBatchPause),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        for extra in extra_patches:
            extra.start()
        try:
            front._run_front_modes_unlocked({}, runtime, dry_run=False)
        except BaseException as exc:  # noqa: BLE001 - asserted by callers
            error = exc
        finally:
            for extra in extra_patches:
                extra.stop()
    return error, seen, out.getvalue(), err.getvalue()


def job_state(runtime) -> Dict[str, Any]:
    return json.loads((runtime.outputs_root / runtime.job_id / "state.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# P1-3: reason/detail reach the D2 classifier


class EnvironmentVsItemFailureTests(unittest.TestCase):
    def test_retry_exhaustion_carries_the_last_transient_reason(self) -> None:
        for reason, environment in (("page_timeout", True), ("navigation_error", True),
                                    ("expected_content_missing", False)):
            with self.subTest(reason=reason):
                worker = make_worker(worker_runtime())
                attempts: List[int] = []
                with fast_controller(), redirect_stdout(io.StringIO()), patch.object(
                    worker, "_process_attempt", side_effect=counting_failure(attempts, lambda: transient(reason))
                ):
                    result = worker._process(make_task())
                self.assertEqual(result.error_reason, EXHAUSTED)
                self.assertTrue(result.error_detail.startswith(reason), result.error_detail)
                self.assertEqual(
                    run_outcome.is_environment_failure(f"{result.error_reason} {result.error_detail}"),
                    environment,
                )

    def test_network_outage_never_skips_on_the_second_run(self) -> None:
        def outage(worker_id, task):
            return failed_result(worker_id, task, EXHAUSTED, "navigation_error net::ERR_INTERNET_DISCONNECTED")

        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "supervised", ["alpha", "beta"])
            for _run in range(3):
                error, seen, _out, _err = run_loop(runtime, outage)
                self.assertEqual(error.exit_code, run_outcome.EXIT_RETRY_LATER)
                self.assertEqual(seen, ["alpha"])
            state = job_state(runtime)
            self.assertFalse(state.get("skipped_items"))
            self.assertTrue(state["last_failure_environment"])
            work_key = front.front_task_identity(front.build_initial_queue(runtime)[0])
            self.assertEqual(state["item_failure_meta"][work_key]["environment_runs"], 3)
            self.assertFalse(state.get("item_failure_cycles"))
            # finalize_run turns the env failure into a dated retry.
            job_dir = runtime.outputs_root / runtime.job_id
            run_outcome.exit_with(error, job_dir)
            summary = json.loads((job_dir / "run_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["resume_at"])

    def test_plugin_data_timeout_is_an_environment_failure(self) -> None:
        def stall(worker_id, task):
            return failed_result(worker_id, task, "plugin_data_timeout", "plugin_data_timeout 卖家精灵字段等待到期")

        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "supervised", ["alpha"])
            run_loop(runtime, stall)
            error, _seen, _out, _err = run_loop(runtime, stall)
            self.assertEqual(error.exit_code, run_outcome.EXIT_RETRY_LATER)
            self.assertIn("resume_at", str(error))
            self.assertNotIn("再次失败会自动跳过", str(error))
            self.assertFalse(job_state(runtime).get("skipped_items"))

    def test_item_failure_still_skips_on_the_second_run(self) -> None:
        def broken(worker_id, task):
            if task["keyword"] == "alpha":
                return failed_result(worker_id, task, EXHAUSTED, "expected_content_missing")
            return ok_result(worker_id, task)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "supervised", ["alpha", "beta"])
            error, _seen, _out, _err = run_loop(runtime, broken)
            self.assertEqual(error.exit_code, run_outcome.EXIT_RETRY_LATER)
            error, seen, out, _err = run_loop(runtime, broken)
            self.assertIsNone(error)
            self.assertEqual(seen, ["alpha", "beta"])
            self.assertEqual(len(job_state(runtime)["skipped_items"]), 1)
            self.assertIn("2 次运行均失败", out)

    def test_saved_retry_error_counts_as_detail(self) -> None:
        def generic(worker_id, task):
            return failed_result(worker_id, task, EXHAUSTED)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "supervised", ["alpha"])
            work_key = front.front_task_identity(front.build_initial_queue(runtime)[0])

            def seed_retry_state(*_args, **_kwargs):
                return {"status": "manual_resume_required", "work_key": work_key, "error": "net::ERR_NAME_NOT_RESOLVED"}

            run_loop(runtime, generic, patch.object(front.FrontStateStore, "amazon_page_retry_state", seed_retry_state))
            self.assertTrue(job_state(runtime)["last_failure_environment"])

    def test_unattended_outage_skips_nothing_across_six_runs(self) -> None:
        keywords = [f"kw{i:02d}" for i in range(10)]
        outage = {"on": True}

        def behaviour(worker_id, task):
            if outage["on"]:
                return failed_result(worker_id, task, EXHAUSTED, "navigation_error net::ERR_INTERNET_DISCONNECTED")
            return ok_result(worker_id, task)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "unattended", keywords)
            for _run in range(6):
                error, seen, _out, _err = run_loop(runtime, behaviour)
                self.assertEqual(error.exit_code, run_outcome.EXIT_RETRY_LATER)
                self.assertEqual(len(seen), 3)  # failure window stops the run
            self.assertFalse(job_state(runtime).get("skipped_items"))
            outage["on"] = False
            error, seen, _out, _err = run_loop(runtime, behaviour)
            self.assertIsNone(error)
            self.assertEqual(sorted(seen), keywords)
            self.assertFalse(job_state(runtime).get("skipped_items"))

    def test_last_failure_environment_is_reset_each_run(self) -> None:
        calls = {"n": 0}

        def behaviour(worker_id, task):
            calls["n"] += 1
            if calls["n"] == 1:
                return failed_result(worker_id, task, EXHAUSTED, "page_timeout Message: timeout")
            return ok_result(worker_id, task)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "supervised", ["alpha"])
            run_loop(runtime, behaviour)
            self.assertTrue(job_state(runtime)["last_failure_environment"])
            error, _seen, _out, _err = run_loop(runtime, behaviour)
            self.assertIsNone(error)
            self.assertNotIn("last_failure_environment", job_state(runtime))


# ---------------------------------------------------------------------------
# P2-1 per-item schedule and P1-1 front integration


class RateProbeScheduleTests(unittest.TestCase):
    def test_probe_item_gets_one_attempt_later_items_the_normal_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            safety = safety_with_pause(Path(tmp) / "safety", "rate_probe")
            self.assertTrue(safety.rate_probe_active)
            worker = make_worker(worker_runtime(((0.0, 0.0),), safety=safety, mode="unattended"))
            probe_attempts: List[int] = []
            with fast_controller(), redirect_stdout(io.StringIO()), patch.object(
                worker, "_process_attempt", side_effect=counting_failure(probe_attempts, transient)
            ):
                probe = worker._process(make_task("alpha"))
            self.assertEqual(probe.error_reason, EXHAUSTED)
            self.assertEqual(probe_attempts, [1])

            safety.complete_review_success()  # the probe passed (pause cleared)
            later_attempts: List[int] = []
            with fast_controller(), redirect_stdout(io.StringIO()), patch.object(
                worker, "_process_attempt", side_effect=counting_failure(later_attempts, transient)
            ):
                worker._process(make_task("beta"))
            self.assertEqual(later_attempts, [1, 2])

    def test_schedule_is_chosen_after_the_first_navigation(self) -> None:
        """The next item's first navigation clears a verified probe; its retry
        cycle must then use the normal schedule, not the probe's empty one."""
        with tempfile.TemporaryDirectory() as tmp:
            safety = safety_with_pause(Path(tmp) / "safety", "rate_probe")
            worker = make_worker(worker_runtime(((0.0, 0.0),), safety=safety, mode="unattended"))
            attempts: List[int] = []
            with fast_controller(), redirect_stdout(io.StringIO()), patch.object(
                worker, "_process_attempt",
                side_effect=counting_failure(attempts, transient, before=safety.complete_review_success),
            ):
                worker._process(make_task())
            self.assertEqual(attempts, [1, 2])

    def test_run_front_modes_no_longer_empties_the_runtime_schedule(self) -> None:
        class ProbeSafety:
            rate_probe_active = True

            def __init__(self, *_args, **_kwargs) -> None:
                self.job_label = ""
                self.status_path = None

            def acquire(self) -> None:
                pass

            def begin(self, **_kwargs) -> None:
                pass

            def fail_review(self) -> None:
                pass

            def release(self) -> None:
                pass

            def heartbeat(self, *_args, **_kwargs) -> None:
                pass

        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "supervised", ["alpha"])
            normal = runtime.amazon_page_retry_schedule_seconds
            with (
                patch.object(front, "LocalSafetyController", ProbeSafety),
                patch.object(front, "write_run_summary"),
                patch.object(front, "configure_manual_waits"),
                patch.object(front, "_run_front_modes_unlocked", return_value=0),
            ):
                front.run_front_modes({}, runtime, False)
            self.assertEqual(runtime.amazon_page_retry_schedule_seconds, normal)
            self.assertTrue(normal)

    def test_review_probe_without_verdict_keeps_the_pause(self) -> None:
        """review_front_review_probe_cleared_without_verdict: two page-load
        timeouts during --resume-after-review now stop with the pause kept."""

        class TimeoutDriver:
            current_url = "about:blank"
            title = ""

            def __init__(self) -> None:
                self.gets = 0

            def get(self, _url) -> None:
                self.gets += 1
                raise TimeoutException(f"page load timeout #{self.gets}")

        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "supervised", ["alpha"], save_debug_snapshots=False)
            safety = safety_with_pause(Path(tmp) / "safety", "manual_review", mode="supervised", resume_after_review=True)
            runtime.safety = safety
            driver = TimeoutDriver()
            worker = make_worker(runtime, driver)
            with fast_controller(), redirect_stdout(io.StringIO()):
                result = worker._process(front.build_initial_queue(runtime)[0])
            self.assertIsInstance(result.stop, SafetyPausedError)
            self.assertEqual(driver.gets, 1)
            self.assertTrue(safety.pause_path.exists())


# ---------------------------------------------------------------------------
# P2-2 / P2-13: exports and job-lock refusals never replace the outcome


class ExportNeverReplacesOutcomeTests(unittest.TestCase):
    def locked_workbook(self):
        return patch.object(front, "write_front_workbook", side_effect=PermissionError(13, "Permission denied"))

    def test_interrupt_exports_committed_pages_and_resumes_pending_page(self) -> None:
        def behaviour(worker_id, task):
            if task["keyword"] == "beta":
                raise KeyboardInterrupt()
            return ok_result(worker_id, task)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "supervised", ["alpha", "beta"])
            error, seen, _out, _err = run_loop(runtime, behaviour)
            self.assertEqual(error.exit_code, run_outcome.EXIT_RETRY_LATER)
            self.assertEqual(seen, ["alpha", "beta"])
            job = runtime.outputs_root / runtime.job_id
            records = front.read_jsonl(job / "records.jsonl")
            self.assertEqual([row["keyword"] for row in records], ["alpha"])
            self.assertTrue((job / "dedup_total.xlsx").exists())
            quality = json.loads((job / "quality_report.json").read_text())
            self.assertTrue(quality["export_succeeded"])
            self.assertEqual(quality["total_records"], 1)
            state = job_state(runtime)
            self.assertFalse(state.get("item_failure_cycles"))
            self.assertFalse(state.get("skipped_items"))
            error, seen, _out, _err = run_loop(runtime, ok_result)
            self.assertIsNone(error)
            self.assertEqual(seen, ["beta"])
            self.assertEqual(len(front.read_jsonl(job / "records.jsonl")), 2)

    def test_interrupt_outcome_survives_workbook_export_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "supervised", ["alpha"])

            def behaviour(_worker_id, _task):
                raise KeyboardInterrupt()

            error, _seen, _out, err = run_loop(runtime, behaviour, self.locked_workbook())
            self.assertEqual(error.exit_code, run_outcome.EXIT_RETRY_LATER)
            self.assertIn("手动中断", str(error))
            self.assertIn("请关闭表格后重新运行", err)

    def test_stop_and_risk_pause_survive_a_locked_workbook(self) -> None:
        stops = [
            run_outcome.needs_human("login", next_action=front.NEXT_ACTION_SELLERSPRITE_LOGIN),
            SafetyPausedError("risk", kind="risk_pause"),
        ]
        for stop in stops:
            with self.subTest(stop=type(stop).__name__), tempfile.TemporaryDirectory() as tmp:
                runtime = loop_runtime(tmp, "supervised", ["alpha"])

                def behaviour(worker_id, task, stop=stop):
                    return front.FrontPageResult(worker_id=worker_id, task=task, error_reason="x",
                                                 error_message=str(stop), fatal=True, stop=stop)

                error, _seen, _out, err = run_loop(runtime, behaviour, self.locked_workbook())
                self.assertIs(error, stop)
                self.assertIn("请关闭表格后重新运行", err)

    def test_deferred_run_stays_retry_later(self) -> None:
        def behaviour(worker_id, task):
            if task["keyword"] == "alpha":
                return failed_result(worker_id, task, EXHAUSTED, "expected_content_missing")
            return ok_result(worker_id, task)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "unattended", ["alpha", "beta"])
            error, _seen, _out, _err = run_loop(runtime, behaviour, self.locked_workbook())
            self.assertEqual(error.exit_code, run_outcome.EXIT_RETRY_LATER)

    def test_completed_run_with_locked_workbook_asks_to_close_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = loop_runtime(tmp, "supervised", ["alpha"])
            error, _seen, _out, _err = run_loop(runtime, ok_result, self.locked_workbook())
            self.assertEqual(error.exit_code, run_outcome.EXIT_NEEDS_HUMAN)
            self.assertIn("workbook_export_failed", str(error))
            self.assertIn("dedup_total.xlsx", error.next_action)
            # records were committed; a rerun only re-exports.
            error, seen, _out, _err = run_loop(runtime, ok_result)
            self.assertIsNone(error)
            self.assertEqual(seen, [])
            self.assertTrue((runtime.outputs_root / runtime.job_id / "dedup_total.xlsx").exists())

    def bsr(self, tmp: str, crawl_side_effect, *extra):
        category_runtime = SimpleNamespace(outputs_root=Path(tmp), job_id="bsr-job", include_root=True,
                                           max_depth=3, max_pages_per_category=2)
        job_dir = Path(tmp) / "bsr-job"
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "records.jsonl").write_text(json.dumps({"asin": "B000000001"}) + "\n", encoding="utf-8")
        with (
            patch.object(front, "build_category_runtime_config", return_value=category_runtime),
            patch.object(front, "run_category_crawl", side_effect=crawl_side_effect),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            for item in extra:
                item.start()
            try:
                return front.run_bsr_category_mode({"mode": "bsr_category"}, SimpleNamespace(resume_after_review=False),
                                                   False, False, context={})
            finally:
                for item in extra:
                    item.stop()

    def test_bsr_risk_pause_survives_locked_workbook_and_completed_run_reports_it(self) -> None:
        pause = SafetyPausedError("risk", kind="risk_pause")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SafetyPausedError) as raised:
                self.bsr(tmp, pause, self.locked_workbook())
            self.assertIs(raised.exception, pause)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(run_outcome.CrawlStop) as raised:
                self.bsr(tmp, [0], self.locked_workbook())
            self.assertEqual(raised.exception.exit_code, run_outcome.EXIT_NEEDS_HUMAN)

    def test_bsr_job_lock_refusal_is_exit_50_and_leaves_the_workbook_alone(self) -> None:
        refusal = front.UserFacingError("同一 job_id 已有抓取进程运行：bsr-job。请等待其结束或使用新的 job_id。")
        self.assertEqual(front.front_stop_for(refusal).exit_code, run_outcome.EXIT_LOCK_HELD)
        self.assertEqual(
            front.front_stop_for(front.UserFacingError("断点不一致；请更换 job_id。")).exit_code,
            run_outcome.EXIT_CONFIG_ERROR,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(run_outcome.CrawlStop) as raised:
                self.bsr(tmp, refusal)
            self.assertEqual(raised.exception.exit_code, run_outcome.EXIT_LOCK_HELD)
            self.assertFalse((Path(tmp) / "bsr-job" / "dedup_total.xlsx").exists())

    def test_front_job_lock_refusal_keeps_the_holders_run_summary(self) -> None:
        class FakeSafety:
            rate_probe_active = False

            def __init__(self, *_args, **_kwargs) -> None:
                self.job_label = ""
                self.status_path = None

            def acquire(self) -> None:
                pass

            def begin(self, **_kwargs) -> None:
                pass

            def fail_review(self) -> None:
                pass

            def release(self) -> None:
                pass

            def heartbeat(self, *_args, **_kwargs) -> None:
                pass

        with tempfile.TemporaryDirectory() as tmp:
            keywords = Path(tmp) / "keywords.csv"
            keywords.write_text("keyword\nalpha\n", encoding="utf-8")
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps({
                "mode": "keyword_search", "job_id": "held-job", "outputs_root": str(Path(tmp) / "outputs"),
                "keywords_file": str(keywords), "delivery_location_enabled": False,
            }), encoding="utf-8")
            job_dir = Path(tmp) / "outputs" / "held-job"
            job_dir.mkdir(parents=True)
            holder_summary = {"status": "running", "owner": "holder"}
            (job_dir / "run_summary.json").write_text(json.dumps(holder_summary), encoding="utf-8")
            holder = front.JobRunLock(job_dir / ".run.lock")
            holder.acquire()
            try:
                with (
                    patch.object(front, "LocalSafetyController", FakeSafety),
                    patch.object(front, "configure_manual_waits"),
                    redirect_stdout(io.StringIO()),
                    redirect_stderr(io.StringIO()),
                ):
                    code = front.main(["--config", str(config)])
            finally:
                holder.release()
            self.assertEqual(code, run_outcome.EXIT_LOCK_HELD)
            self.assertEqual(json.loads((job_dir / "run_summary.json").read_text(encoding="utf-8")), holder_summary)


# ---------------------------------------------------------------------------
# P2-7 / P2-8 storefront


class StorefrontFilterAndSignatureTests(unittest.TestCase):
    def test_plugin_not_loaded_records_are_kept_by_product_filters(self) -> None:
        filters = front.ProductFilterConfig(allowed_fulfillment_methods=("FBM",), require_subcategory_rank=True)
        ranked = [{"rank": 3, "category_name": "Bowls"}]
        records = [
            {"asin": "A1", "fulfillment_method": "FBA", "subcategory_bsr_ranks": ranked, "plugin_fields_status": "完整"},
            {"asin": "A2", "fulfillment_method": "", "subcategory_bsr_ranks": [],
             "plugin_fields_status": front.PLUGIN_FIELDS_NOT_LOADED, "note": "卖家精灵未在等待时间内加载此商品，插件字段留空"},
            {"asin": "A3", "fulfillment_method": "FBM", "subcategory_bsr_ranks": ranked, "plugin_fields_status": "完整"},
            {"asin": "A4", "fulfillment_method": "FBM", "subcategory_bsr_ranks": [], "plugin_fields_status": "完整"},
        ]
        accepted, counts = front.filter_front_records(records, filters)
        self.assertEqual([record["asin"] for record in accepted], ["A2", "A3"])
        self.assertEqual(counts, {"fulfillment_method_not_allowed": 1, "subcategory_bsr_rank_missing": 1})
        self.assertIn(front.PLUGIN_NOT_LOADED_FILTER_NOTE, accepted[0]["note"])
        # Without filters nothing changes.
        unfiltered, none = front.filter_front_records(records, front.ProductFilterConfig())
        self.assertEqual(len(unfiltered), 4)
        self.assertEqual(none, {})

    def snapshot(self, observed: Dict[str, Any]) -> Dict[str, Any]:
        driver = SimpleNamespace(execute_script=lambda *_args: observed)
        runtime = SimpleNamespace(include_sponsored=False, page_scroll_step_ratio=0.85)
        cards = [{"asin": "B000000001", "is_sponsored": "no"}, {"asin": "B000000002", "is_sponsored": "no"}]
        with patch.object(front, "extract_front_product_cards", return_value=cards):
            return front.inspect_storefront_plugin_page(driver, runtime, scroll=False)

    def test_signature_uses_only_required_label_values(self) -> None:
        values = {"近30天销量(父体)": "1,234", "近30天销量(子体)": "300", "FBA费用": "$3.10", "毛利率": "31%"}
        base = {"at_bottom": True, "scroll_height": 5000, "results": {
            "B000000001": {"reason": "complete", "values": values, "text": "box A"},
            "B000000002": {"reason": "loading"},
        }}
        late_optional = {"at_bottom": True, "scroll_height": 5600, "results": {
            "B000000001": {"reason": "complete", "values": dict(values), "text": "box A + 上架时间: 2024-01-01"},
            "B000000002": {"reason": "field_missing", "fields": ["毛利率"]},
        }}
        changed_value = json.loads(json.dumps(base))
        changed_value["results"]["B000000001"]["values"]["毛利率"] = "29%"
        completed = json.loads(json.dumps(base))
        completed["results"]["B000000002"] = {"reason": "complete", "values": dict(values)}
        first = self.snapshot(base)["signature"]
        self.assertEqual(first, self.snapshot(late_optional)["signature"])
        self.assertNotEqual(first, self.snapshot(changed_value)["signature"])
        self.assertNotEqual(first, self.snapshot(completed)["signature"])


# ---------------------------------------------------------------------------
# P2-9 CAPTCHA cooldown in front's own branches


class RecordingSafety(LocalSafetyController):
    def __init__(self, root: Path) -> None:
        super().__init__(root, mode="supervised")
        self.cleared: List[str] = []

    def captcha_cleared(self, *, page_url: str = "") -> None:
        self.cleared.append(page_url)


class CaptchaCooldownTests(unittest.TestCase):
    URL = "https://www.amazon.com/s?k=alpha"

    def worker(self, safety) -> front.FrontWorker:
        return make_worker(worker_runtime(safety=safety), SimpleNamespace(current_url=self.URL))

    def test_detect_block_branch_calls_captcha_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            safety = RecordingSafety(Path(tmp))
            worker = self.worker(safety)
            with (
                patch.object(front, "detect_block", return_value="amazon_robot_check"),
                patch.object(front, "wait_for_manual_clear", return_value=True),
                patch.object(front, "wait_for_product_cards", return_value=True),
            ):
                status = worker._wait_for_page_or_manual(make_task())
            self.assertIs(status, front.PageHealthStatus.HEALTHY)
            self.assertEqual(safety.cleared, [self.URL])
            safety.cleared.clear()
            with (
                patch.object(front, "detect_block", return_value="sellersprite_verification"),
                patch.object(front, "wait_for_manual_clear", return_value=True),
                patch.object(front, "wait_for_product_cards", return_value=True),
            ):
                worker._wait_for_page_or_manual(make_task())
            self.assertEqual(safety.cleared, [])

    def test_assessment_branch_calls_captcha_cleared(self) -> None:
        captcha = front.classify_page_snapshot(front.PageSnapshot(
            page_kind="search_category", title="Robot Check", body_text="Enter the characters you see below"))
        self.assertIs(captcha.status, front.PageHealthStatus.INTERACTIVE_VERIFICATION)
        with tempfile.TemporaryDirectory() as tmp:
            safety = RecordingSafety(Path(tmp))
            with (
                patch.object(front, "detect_block", return_value=None),
                patch.object(front, "wait_for_product_cards", side_effect=[False, True]),
                patch.object(front, "assess_front_page", return_value=captcha),
                patch.object(front, "wait_for_manual_clear", return_value=True),
            ):
                self.worker(safety)._wait_for_page_or_manual(make_task())
            self.assertEqual(safety.cleared, [self.URL])

    def test_second_captcha_within_a_day_hard_pauses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            safety = LocalSafetyController(Path(tmp), mode="supervised")
            safety._wait_until = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            worker = self.worker(safety)
            with (
                patch.object(front, "detect_block", return_value="amazon_robot_check"),
                patch.object(front, "wait_for_manual_clear", return_value=True),
                patch.object(front, "wait_for_product_cards", return_value=True),
            ):
                worker._wait_for_page_or_manual(make_task())
                self.assertFalse(safety.pause_path.exists())
                with self.assertRaises(SafetyPausedError):
                    worker._wait_for_page_or_manual(make_task())
            self.assertTrue(safety.pause_path.exists())


# ---------------------------------------------------------------------------
# P2-12c input encodings


class InputTableTests(unittest.TestCase):
    def test_gbk_and_utf8_bom_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gbk = Path(tmp) / "keywords_gbk.csv"
            gbk.write_bytes("关键词\r\n收纳盒\r\n厨房置物架\r\n".encode("gbk"))
            self.assertEqual(front.load_keywords(gbk), ["收纳盒", "厨房置物架"])
            bom = Path(tmp) / "keywords_bom.csv"
            bom.write_bytes("keyword\nstorage box\n".encode("utf-8-sig"))
            self.assertEqual(front.load_keywords(bom), ["storage box"])

    def test_unreadable_inputs_give_a_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            utf16 = Path(tmp) / "keywords.csv"
            utf16.write_bytes("keyword\nstorage box\n".encode("utf-16"))
            with self.assertRaises(front.UserFacingError) as raised:
                front.read_input_rows(utf16)
            self.assertIn("CSV UTF-8", str(raised.exception))
            fake_xlsx = Path(tmp) / "stores.xlsx"
            fake_xlsx.write_text("store_url\nhttps://www.amazon.com/s?me=A\n", encoding="utf-8")
            with self.assertRaises(front.UserFacingError) as raised:
                front.read_input_rows(fake_xlsx)
            self.assertIn(".xlsx", str(raised.exception))
            with self.assertRaises(front.UserFacingError) as raised:
                front.read_input_rows(Path(tmp) / "keywords.xls")
            self.assertIn("CSV UTF-8", str(raised.exception))

    def test_xlsx_handle_is_closed(self) -> None:
        closed: List[bool] = []

        class FakeWorkbook:
            active = SimpleNamespace(iter_rows=lambda **_kwargs: iter([("keyword",), ("alpha",)]))

            def close(self) -> None:
                closed.append(True)

        with patch.object(front, "load_workbook", return_value=FakeWorkbook()):
            rows = front.read_input_rows(Path("keywords.xlsx"))
        self.assertEqual(rows, [{"keyword": "alpha"}])
        self.assertEqual(closed, [True])

    def test_gbk_keywords_pass_the_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            keywords = Path(tmp) / "keywords.csv"
            keywords.write_bytes("关键词\r\n收纳盒\r\n".encode("gbk"))
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps({
                "mode": "keyword_search", "job_id": "gbk-job", "outputs_root": str(Path(tmp) / "outputs"),
                "keywords_file": str(keywords), "delivery_location_enabled": False,
            }), encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(front.main(["--config", str(config), "--dry-run"]), 0)


# ---------------------------------------------------------------------------
# P2-14 countdown and Windows-safe replace


class CountdownAndReplaceTests(unittest.TestCase):
    def countdown_output(self, schedule) -> str:
        worker = make_worker(worker_runtime(schedule))
        out = io.StringIO()
        with fast_controller(), redirect_stdout(out), patch.object(
            worker, "_process_attempt", side_effect=counting_failure([], transient)
        ):
            worker._process(make_task())
        return out.getvalue()

    def test_countdown_shows_the_real_maximum(self) -> None:
        supervised = self.countdown_output(((60.0, 60.0),))
        unattended = self.countdown_output(((120.0, 120.0), (300.0, 300.0)))
        self.assertIn("尝试 2/2", supervised)
        self.assertIn("尝试 3/3", unattended)
        self.assertNotIn("/5", supervised + unattended)

    def test_write_jsonl_atomic_retries_a_sharing_violation(self) -> None:
        real_replace = run_outcome.os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(13, "sharing violation")
            return real_replace(src, dst)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "records.jsonl"
            with patch.object(run_outcome.os, "replace", side_effect=flaky_replace):
                front.write_jsonl_atomic(target, [{"asin": "B000000001"}])
            self.assertEqual(calls["n"], 2)
            self.assertEqual(target.read_text(encoding="utf-8").strip(), '{"asin": "B000000001"}')
            self.assertEqual([path.name for path in Path(tmp).iterdir()], ["records.jsonl"])


if __name__ == "__main__":
    unittest.main()
