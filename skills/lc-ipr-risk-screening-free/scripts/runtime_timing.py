"""Best-effort CLI wall timings, separate from every evidence/report snapshot.

Browser/API runners already provide monotonic action/dispatcher timings. This
helper covers local CLI stages only; a successful CLI may produce an incomplete
business assessment. Never derive elapsed time from source or evidence dates.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import json
import math
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

FILENAME = "runtime-timings.jsonl"

# Only these fixed labels may reach a human progress projection. Source text,
# exception details, paths and arbitrary log values never enter the CLI view.
STAGE_LABELS = {
    "source_operation_recording": "来源结果登记", "source_material_processing": "来源材料处理",
    "candidate_merge": "候选合并", "candidate_triage": "候选分流",
    "assessment_finalize": "风险评估定稿", "report_build": "报告构建",
    "report_validation": "报告校验", "report_publish": "报告发布",
    "publication_preflight": "发布前检查", "report_render_and_bundle": "报告渲染与打包",
    "review_preparation": "审阅准备", "freeze": "冻结材料", "model_review": "模型审阅",
    "independent_semantic_check": "独立语义校验", "delivery_copy": "报告复制",
    "actual_entry_check": "实际入口核验", "render": "渲染", "copy": "复制",
    "semantic_check": "语义校验", "entry_check": "入口核验",
}
WORK_LABELS = {
    "source_lookup": "来源查询或结果处理", "plan_repair": "检索计划修复",
    "product_analysis": "产品事实分析", "agent_investigation": "现有资料调查",
    "agent_read": "材料阅读", "professional_review": "专业复核",
    "triage": "候选分流", "scope_review": "范围审阅",
}


def _recent_rows(directory: Path, limit: int) -> list[dict]:
    path = directory / FILENAME
    if path.is_symlink() or not path.is_file():
        return []
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - 131072))
        raw = stream.read(131072)
    if size > len(raw):
        raw = raw.split(b"\n", 1)[-1]
    result = []
    for line in reversed(raw.splitlines()):
        if not line or len(line) > 4096:
            continue
        try:
            row = json.loads(line)
        except (UnicodeError, ValueError):
            continue
        if not isinstance(row, dict) or row.get("schema") != "IPR-RUNTIME-TIMING/1.0" or not row.get("auxiliary_only"):
            continue
        stage, status, elapsed = row.get("stage"), row.get("status"), row.get("elapsed_ms")
        if (not isinstance(stage, str) or stage not in STAGE_LABELS
                or not isinstance(status, str) or status not in {"success", "error", "interrupted"}
                or type(elapsed) not in (int, float) or not math.isfinite(elapsed)
                or elapsed < 0 or elapsed > 86400000):
            continue
        result.append({"stage": stage, "label": STAGE_LABELS[stage],
                       "elapsed_ms": elapsed, "outcome": status})
        if len(result) == limit:
            break
    return result


def progress_view(directory, work_view: dict | None = None, *, stage_hint: str | None = None) -> dict:
    """Read-only CLI projection of ended timings and the next pending work.

    A past timing never proves an operation is running or business-complete.
    Cross-process activity cannot be established from this JSONL, so no
    running state or live elapsed counter is inferred.
    """
    next_step = {"state": "unknown", "label": "当前活动未确认"}
    if isinstance(work_view, dict):
        entries = work_view.get("entries") or []
        review = work_view.get("review_work") or {}
        if isinstance(review, dict):
            entries = [*entries, *(review.get("entries") or [])] if isinstance(entries, list) else []
        for entry in entries if isinstance(entries, list) else []:
            if (not isinstance(entry, dict) or not isinstance(entry.get("kind"), str)
                    or entry["kind"] not in WORK_LABELS):
                continue
            state = entry.get("state")
            if state in {"ready", "awaiting_review"}:
                next_step = {"state": "pending", "label": WORK_LABELS[entry["kind"]], "kind": entry["kind"]}
                break
            if state in {"awaiting_access", "awaiting_user", "submission_unknown", "blocked"} and next_step["state"] == "unknown":
                next_step = {"state": "waiting", "label": WORK_LABELS[entry["kind"]], "kind": entry["kind"]}
    if next_step["state"] == "unknown" and stage_hint in {"independent_review", "publication", "validation", "delivery"}:
        labels = {"independent_review": "最终双审", "publication": "报告发布", "validation": "报告校验", "delivery": "实际入口交付"}
        next_step = {"state": "pending", "label": labels[stage_hint]}
    try:
        root = Path(directory).expanduser().resolve()
        recent = _recent_rows(root, 5)
    except (OSError, ValueError, TypeError):
        recent = []
    return {"schema": "IPR-RUNTIME-PROGRESS/1.0", "auxiliary_only": True,
            "current_activity": "unconfirmed", "next_step": next_step,
            "recent_ended_steps": recent}


def _argument(argv: list[str], flag: str) -> str | None:
    value = None
    for position, item in enumerate(argv):
        if item.startswith(flag + "="):
            value = item.split("=", 1)[1]
        elif item == flag and position + 1 < len(argv):
            value = argv[position + 1]
    return value


def _destination(argv: list[str]) -> Path | None:
    output = _argument(argv, "--output-dir")
    if output:
        return Path(output).expanduser().resolve()
    raw = _argument(argv, "--task-dir")
    if not raw:
        return None
    task_dir = Path(raw).expanduser().resolve()
    # Unmarked historical tasks remain read-only, including validation. Only
    # the current opt-in task workflow writes auxiliary timing beside inputs.
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    return task_dir if isinstance(task, dict) and task.get("specialty_workflow_revision") == "asset-scope-v1" else None


def _append(directory: Path, row: dict) -> None:
    # Never create a task/output directory merely to record failed invocation.
    if not directory.is_dir():
        return
    # Reuse the existing POSIX/Windows primitive, but never the evidence lock.
    # Lazy import keeps optional timing capabilities out of CLI import paths.
    from provider_utils import file_lock
    with file_lock(directory / ".runtime-timings.lock", timeout=0.1):
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(directory / FILENAME, flags, 0o600)
        try:
            data = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            while data:
                size = os.write(descriptor, data)
                if size <= 0:
                    raise OSError("RUNTIME_TIMING_SHORT_WRITE")
                data = data[size:]
        finally:
            os.close(descriptor)


@contextmanager
def _measure(destination, stage, scope):
    started = datetime.now(timezone.utc).isoformat()
    tick = time.perf_counter_ns()
    status, error_type = "success", None
    try:
        yield
    except BaseException as exc:
        if not isinstance(exc, SystemExit) or exc.code not in (None, 0):
            status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "error"
            error_type = type(exc).__name__
        raise
    finally:
        elapsed = time.perf_counter_ns() - tick
        if destination is not None:
            try:
                _append(destination, {
                    "schema": "IPR-RUNTIME-TIMING/1.0", "invocation_id": str(uuid4()),
                    "stage": stage, "elapsed_scope": scope, "clock": "perf_counter_ns",
                    "elapsed_ms": round(elapsed / 1_000_000, 3), "started_at": started,
                    "finished_at": datetime.now(timezone.utc).isoformat(), "status": status,
                    "error_type": error_type, "auxiliary_only": True})
            except Exception:
                # Auxiliary logging never changes the business result or logs
                # exception text, which can contain source secrets.
                pass


@contextmanager
def timed_step(directory, stage: str):
    """Measure one opted-in local step; no input reads or directory creation.

    Elapsed time includes nested calls. Neither this log nor a success status is
    a fact/review/delivery credential. A missing destination disables logging.
    """
    try:
        destination = Path(directory).expanduser().resolve() if directory is not None else None
    except (OSError, ValueError, TypeError):
        destination = None
    with _measure(destination, stage, "step_inclusive"):
        yield


def timed_cli(stage: str):
    """Measure main() only; preserve return value, stdout and original exception."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                destination = _destination(sys.argv[1:])
            except (OSError, ValueError, TypeError):
                destination = None
            with _measure(destination, stage, "cli_main_inclusive"):
                return function(*args, **kwargs)
        return wrapped
    return decorate
