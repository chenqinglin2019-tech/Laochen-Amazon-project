"""Shared run-outcome contract: exit codes, run_summary status and item skipping.

Every crawler ends a real run in exactly one documented status so the calling
agent can choose the next step without guessing.  This module has no crawler,
browser or provider imports.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, MutableMapping, Optional


EXIT_COMPLETED = 0
EXIT_COMPLETED_WITH_SKIPS = 10
EXIT_RETRY_LATER = 20
EXIT_RISK_PAUSE = 21
EXIT_NEEDS_HUMAN = 30
EXIT_CONFIG_ERROR = 40
EXIT_LOCK_HELD = 50
EXIT_UNEXPECTED = 2

STATUS_BY_EXIT = {
    EXIT_COMPLETED: "completed",
    EXIT_COMPLETED_WITH_SKIPS: "completed_with_skips",
    EXIT_RETRY_LATER: "retry_later",
    EXIT_RISK_PAUSE: "risk_pause",
    EXIT_NEEDS_HUMAN: "needs_human",
    EXIT_CONFIG_ERROR: "config_error",
    EXIT_LOCK_HELD: "lock_held",
    EXIT_UNEXPECTED: "error",
}

DEFAULT_NEXT_ACTION = {
    "completed": "任务已完成，向用户交付输出表格。",
    "completed_with_skips": "采集队列已结束，存在跳过项；按 skipped_items 披露原因和未完成范围，不能宣称完整交付。",
    "retry_later": "临时故障，断点已保存。先查看 run_summary.json 的 resume_at；有恢复时间则等待到期，再重新运行同一命令。",
    "risk_pause": "平台风控暂停。不要重复运行；等到 resume_at 之后，请用户确认浏览器正常，再加 --resume-after-review 运行一次。",
    "needs_human": "需要用户在浏览器里处理（验证码 / 配送地址 / 卖家精灵登录等）。处理完成后重新运行同一命令。",
    "config_error": "配置或输入有误，按报错修改配置后先运行 dry-run。",
    "lock_held": "本机已有采集进程在运行。不要再启动新的进程；等待它结束或让用户确认后再运行。",
    "error": "未分类错误；把报错原文告诉用户，不要盲目重复运行。",
}

# Two consecutive failed retry cycles on the same item → skip it (user decision D2).
QUARANTINE_AFTER_FAILED_CYCLES = 2
# Environment-level failures (network, timeouts, 5xx, provider 429/5xx, plugin
# data not loading) say nothing about the item itself.  They never count toward
# the 2-run rule; an item is skipped for them only after 4 runs in which other
# items succeeded, or after 6 runs regardless, so nothing can loop forever.
ENVIRONMENT_SKIP_AFTER_RUNS = 4
ENVIRONMENT_SKIP_HARD_CAP = 6
ENVIRONMENT_RETRY_DELAY_SECONDS = 10 * 60

# One id per crawl run.  Crawlers call start_new_run() when a real run starts;
# "per run" bookkeeping (failure window, one counted cycle per item per run)
# compares against current_run_id().
_RUN_ID = {"value": f"{os.getpid()}-{time.time():.0f}-0"}
_RUN_COUNTER = {"value": 0}


def start_new_run() -> str:
    _RUN_COUNTER["value"] += 1
    _RUN_ID["value"] = f"{os.getpid()}-{time.time():.0f}-{_RUN_COUNTER['value']}"
    return _RUN_ID["value"]


def current_run_id() -> str:
    return _RUN_ID["value"]

ITEM_FAILURE_MARKERS = (
    "amazon_dog_error",
    "page not found",
    "expected_content_missing",
    "source_unavailable",
    "source_image_download_failed",
    "invalid_next_url",
    "malformed",
)
ENVIRONMENT_FAILURE_MARKERS = (
    "navigation_error",
    "net::err",
    "timeout",
    "timed out",
    "http_5",
    "http_429",
    "429",
    "blank_page",
    "plugin_data_timeout",
    "provider_error",
    "runtime_error",
    "webdriver_error",
    "source_time_budget",
    "connection",
    "temporarily",
    "dns",
    # Every Lens candidate unscorable usually means a page-structure change.
    "all_candidates_unscorable",
)


class CrawlStop(RuntimeError):
    """A categorized stop with a deterministic exit code and next action."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int = EXIT_UNEXPECTED,
        next_action: str = "",
        resume_at: str = "",
    ) -> None:
        super().__init__(message)
        self.exit_code = int(exit_code)
        self.status = STATUS_BY_EXIT.get(self.exit_code, "error")
        self.next_action = next_action or DEFAULT_NEXT_ACTION[self.status]
        self.resume_at = str(resume_at or "")


def retry_later(message: str, **kwargs: Any) -> CrawlStop:
    return CrawlStop(message, exit_code=EXIT_RETRY_LATER, **kwargs)


def needs_human(message: str, **kwargs: Any) -> CrawlStop:
    return CrawlStop(message, exit_code=EXIT_NEEDS_HUMAN, **kwargs)


def config_error(message: str, **kwargs: Any) -> CrawlStop:
    return CrawlStop(message, exit_code=EXIT_CONFIG_ERROR, **kwargs)


@dataclass(frozen=True)
class Outcome:
    exit_code: int
    status: str
    message: str
    next_action: str
    resume_at: str = ""


def classify_exception(exc: BaseException) -> Outcome:
    """Map any crawler exception to the shared contract."""

    message = str(exc)
    if isinstance(exc, CrawlStop):
        return Outcome(exc.exit_code, exc.status, message, exc.next_action, exc.resume_at)
    kind = str(getattr(exc, "kind", "") or "")
    if kind == "lock_held":
        return Outcome(EXIT_LOCK_HELD, "lock_held", message, DEFAULT_NEXT_ACTION["lock_held"])
    if kind in {"risk_pause", "review_not_due"}:
        return Outcome(
            EXIT_RISK_PAUSE,
            "risk_pause",
            message,
            DEFAULT_NEXT_ACTION["risk_pause"],
            str(getattr(exc, "resume_at", "") or ""),
        )
    return Outcome(EXIT_UNEXPECTED, "error", message, DEFAULT_NEXT_ACTION["error"])


def completed_outcome(skipped_count: int) -> Outcome:
    if skipped_count > 0:
        return Outcome(
            EXIT_COMPLETED_WITH_SKIPS,
            "completed_with_skips",
            f"采集队列已结束，{skipped_count} 个项目达到失败处理条件后已跳过。",
            DEFAULT_NEXT_ACTION["completed_with_skips"],
        )
    return Outcome(EXIT_COMPLETED, "completed", "任务完成。", DEFAULT_NEXT_ACTION["completed"])


def replace_with_retry(source: str, target: Path, attempts: int = 6) -> None:
    """os.replace that tolerates a short-lived Windows sharing violation.

    Antivirus scans or a concurrent reader (safety-status) can hold the target
    for a moment on Windows; failing the whole crawl for that is pointless.
    """

    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.1 * (attempt + 1))


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        replace_with_retry(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def finalize_run(job_dir: Optional[Path], outcome: Outcome) -> None:
    """Merge the final status into run_summary.json and close the heartbeat."""

    if job_dir is None:
        return
    job_dir = Path(job_dir)
    summary_path = job_dir / "run_summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary = summary if isinstance(summary, dict) else {}
    except (OSError, ValueError, TypeError):
        summary = {}
    try:
        state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
        state = state if isinstance(state, dict) else {}
    except (OSError, ValueError, TypeError):
        state = {}
    now = dt.datetime.now().isoformat(timespec="seconds")
    resume_at = outcome.resume_at
    next_action = outcome.next_action
    if outcome.status == "retry_later" and state.get("last_failure_environment") and not resume_at:
        resume_at = (dt.datetime.now() + dt.timedelta(seconds=ENVIRONMENT_RETRY_DELAY_SECONDS)).isoformat(
            sep=" ", timespec="seconds"
        )
        next_action = (
            "网络、Amazon、卖家精灵或模型服务暂时不可用（不是该项目本身的问题），断点已保存。"
            f"请等到 {resume_at} 之后再重新运行同一命令。"
        )
    summary.update(
        {
            "finished_at": now,
            "status": outcome.status,
            "exit_code": outcome.exit_code,
            "message": outcome.message[:1000],
            "next_action": next_action,
            "resume_at": resume_at or summary.get("risk_not_before") or "",
            "skipped_items": list(state.get("skipped_items") or [])[:200],
        }
    )
    if state.get("mode") in {"storefront", "keyword_search", "bsr_category"}:
        try:
            quality = json.loads((job_dir / "quality_report.json").read_text(encoding="utf-8"))
            if not isinstance(quality, dict) or quality.get("schema_version") != 2:
                quality = {"status": "not_evaluated"}
        except (OSError, ValueError, TypeError):
            quality = {"status": "not_evaluated"}
        reasons = dict(state.get("completed_source_reasons") or {})
        natural = [key for key, reason in reasons.items() if reason in {"no_next_page", "explicit_empty", "verified_empty", "explicit_no_results"}]
        limited = [key for key, reason in reasons.items() if reason in {"store_page_limit", "keyword_page_limit", "category_page_limit"}]
        abnormal = [key for key in reasons if key not in natural and key not in limited]
        requested = state.get("scope_requested", "limited")
        pending = bool(state.get("pending") or state.get("in_flight") or state.get("deferred_tasks"))
        expected = set(state.get("requested_source_ids") or [])
        all_sources_finished = bool(reasons) and (not expected or expected.issubset(reasons))
        scope_complete = all_sources_finished and not pending and not abnormal and (requested != "all" or not limited)
        scope = {"requested": requested, "complete": scope_complete, "source_reasons": reasons,
                 "natural_end_sources": natural, "page_limit_sources": limited, "abnormal_sources": abnormal}
        ready = (outcome.status == "completed" and quality.get("status") == "passed"
                 and scope_complete and not state.get("skipped_items") and quality.get("export_succeeded") is True)
        summary.update({"data_quality": quality, "scope_completion": scope, "delivery_ready": ready})
        if outcome.status in {"completed", "completed_with_skips"}:
            summary["message"] = "采集队列处理结束；" + ("数据与请求范围验收通过。" if ready else "存在数据或范围缺口。")
            summary["next_action"] = ("验收通过，可以完整交付表格。" if ready else
                                      "先披露 data_quality 和 scope_completion 中的缺口；按缺失字段或异常来源补采，不能宣称完整交付。")
    try:
        attempt = os.environ.get("LC_CRAWL_ATTEMPT_ID")
        if attempt:
            summary["attempt_id"] = attempt
        _atomic_write_json(summary_path, summary)
        _atomic_write_json(
            job_dir / "run_heartbeat.json",
            {"pid": os.getpid(), "phase": "exited", "updated_at": now, "status": outcome.status,
             **({"attempt_id": attempt} if attempt else {})},
        )
    except OSError:
        pass


def write_heartbeat(path: Optional[Path], phase: str, *, until: str = "", detail: str = "") -> None:
    """Small liveness record: the agent treats a fresh heartbeat as progress."""

    if path is None:
        return
    payload = {
        "pid": os.getpid(),
        "phase": phase,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    if os.environ.get("LC_CRAWL_ATTEMPT_ID"):
        payload["attempt_id"] = os.environ["LC_CRAWL_ATTEMPT_ID"]
    if until:
        payload["until"] = until
    if detail:
        payload["detail"] = detail[:300]
    try:
        _atomic_write_json(Path(path), payload)
    except OSError:
        pass


def is_environment_failure(text: str) -> bool:
    """True when a failure describes the environment rather than the item.

    Item-specific evidence (a not-found/dog page, a loaded page without the
    expected content, an unusable image) wins over incidental words such as
    "timeout" in the same message.
    """

    lowered = str(text or "").lower()
    if any(marker in lowered for marker in ITEM_FAILURE_MARKERS):
        return False
    return any(marker in lowered for marker in ENVIRONMENT_FAILURE_MARKERS)


def _current_run(data: MutableMapping[str, Any]) -> bool:
    return data.get("operation_run_id") == current_run_id()


def run_has_success(data: MutableMapping[str, Any]) -> bool:
    return _current_run(data) and True in list(data.get("operation_recent_outcomes") or [])


def _current_streak(data: MutableMapping[str, Any]) -> int:
    return int(data.get("operation_consecutive_failures") or 0) if _current_run(data) else 0


def note_item_failure(
    data: MutableMapping[str, Any],
    work_key: str,
    *,
    reason: str = "",
    detail: str = "",
) -> int:
    """Record one failed retry cycle and return a count for ``should_quarantine``.

    Rules (refinement of decision D2, see references/configuration.md):
    - at most one counted cycle per item per run (two failures must come from
      two different runs);
    - item-specific failures skip on the second counted run;
    - environment failures skip only after 4 runs with a success in the same
      run, or after 6 runs;
    - never skip while this failure would be the third in a row (an outage):
      the caller stops/defers instead.
    """

    failures = data.setdefault("item_failure_cycles", {})
    if not isinstance(failures, dict):
        failures = data["item_failure_cycles"] = {}
    meta = data.setdefault("item_failure_meta", {})
    if not isinstance(meta, dict):
        meta = data["item_failure_meta"] = {}
    entry = dict(meta.get(work_key) or {})
    environment = is_environment_failure(f"{reason} {detail}")
    data["last_failure_environment"] = environment
    if entry.get("last_run") == current_run_id():
        return 1
    entry["last_run"] = current_run_id()
    if environment:
        runs = int(entry.get("environment_runs") or 0) + 1
        entry["environment_runs"] = runs
        skip = (runs >= ENVIRONMENT_SKIP_AFTER_RUNS and run_has_success(data)) or runs >= ENVIRONMENT_SKIP_HARD_CAP
    else:
        count = int(failures.get(work_key) or 0) + 1
        failures[work_key] = count
        skip = count >= QUARANTINE_AFTER_FAILED_CYCLES
    meta[work_key] = entry
    if skip and _current_streak(data) >= 2:
        skip = False
    return QUARANTINE_AFTER_FAILED_CYCLES if skip else 1


def clear_item_failures(data: MutableMapping[str, Any], work_key: str) -> None:
    for key in ("item_failure_cycles", "item_failure_meta"):
        failures = data.get(key)
        if isinstance(failures, dict):
            failures.pop(work_key, None)


def should_quarantine(failed_cycles: int) -> bool:
    return int(failed_cycles) >= QUARANTINE_AFTER_FAILED_CYCLES


def record_skipped_item(
    data: MutableMapping[str, Any], work_key: str, *, reason: str, label: str = "", url: str = ""
) -> None:
    """Remember a skipped item so the final summary and workbook can show it."""

    skipped = data.setdefault("skipped_items", [])
    if not isinstance(skipped, list):
        skipped = data["skipped_items"] = []
    if any(isinstance(item, dict) and item.get("work_key") == work_key for item in skipped):
        return
    skipped.append(
        {
            "work_key": work_key,
            "label": str(label or "")[:200],
            "url": str(url or "").split("#", 1)[0][:500],
            "reason": str(reason or "")[:200],
            "skipped_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    )


def exit_with(exc: Optional[BaseException], job_dir: Optional[Path], *, skipped_count: int = 0) -> int:
    """Finalize the run summary and return the process exit code."""

    outcome = completed_outcome(skipped_count) if exc is None else classify_exception(exc)
    if outcome.exit_code != EXIT_LOCK_HELD:
        # The lock holder may be running this very job; never overwrite its
        # run_summary / heartbeat with this refused process's exit record.
        finalize_run(job_dir, outcome)
    return outcome.exit_code


__all__ = [
    "CrawlStop",
    "EXIT_COMPLETED",
    "EXIT_COMPLETED_WITH_SKIPS",
    "EXIT_CONFIG_ERROR",
    "EXIT_LOCK_HELD",
    "EXIT_NEEDS_HUMAN",
    "EXIT_RETRY_LATER",
    "EXIT_RISK_PAUSE",
    "EXIT_UNEXPECTED",
    "Outcome",
    "QUARANTINE_AFTER_FAILED_CYCLES",
    "classify_exception",
    "clear_item_failures",
    "completed_outcome",
    "config_error",
    "exit_with",
    "finalize_run",
    "is_environment_failure",
    "replace_with_retry",
    "run_has_success",
    "current_run_id",
    "start_new_run",
    "needs_human",
    "note_item_failure",
    "record_skipped_item",
    "retry_later",
    "should_quarantine",
    "write_heartbeat",
]
