"""Best-effort CLI wall timings, separate from every evidence/report snapshot.

Browser/API runners already provide monotonic action/dispatcher timings. This
helper covers local CLI stages only; a successful CLI may produce an incomplete
business assessment. Never derive elapsed time from source or evidence dates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

FILENAME = "runtime-timings.jsonl"


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


def timed_cli(stage: str):
    """Measure main() only; preserve return value, stdout and original exception."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                destination = _destination(sys.argv[1:])
            except (OSError, ValueError, TypeError):
                destination = None
            started = datetime.now(timezone.utc).isoformat()
            tick = time.perf_counter_ns()
            status, error_type = "success", None
            try:
                return function(*args, **kwargs)
            except BaseException as exc:
                if not isinstance(exc, SystemExit) or exc.code not in (None, 0):
                    status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "error"
                    error_type = type(exc).__name__
                raise
            finally:
                elapsed = time.perf_counter_ns() - tick
                if destination is not None:
                    row = {"schema": "IPR-RUNTIME-TIMING/1.0", "invocation_id": str(uuid4()),
                           "stage": stage, "elapsed_scope": "cli_main_inclusive",
                           "clock": "perf_counter_ns", "elapsed_ms": round(elapsed / 1_000_000, 3),
                           "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
                           "status": status, "error_type": error_type,
                           "auxiliary_only": True}
                    try:
                        _append(destination, row)
                    except Exception:
                        # Auxiliary logging must never replace a business
                        # exception, change its return, or print source secrets.
                        pass
        return wrapped
    return decorate
