"""Publish browser-call deadlines for a process-external supervisor."""
from __future__ import annotations

import functools
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_local = threading.local()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".runtime-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


@contextmanager
def browser_call(name: str, seconds: float = 10.0):
    directory = os.environ.get("LC_CRAWL_WATCHDOG_DIR")
    if not directory:
        yield
        return
    path = Path(directory) / "runtime_watchdog.json"
    previous = getattr(_local, "call", None)
    now = time.monotonic()
    payload = {
        "attempt_id": os.environ.get("LC_CRAWL_ATTEMPT_ID", ""),
        "pid": os.getpid(), "thread_id": threading.get_ident(),
        "operation": name, "active": True,
        "started_monotonic": now,
        "deadline_monotonic": min(now + seconds, previous["deadline_monotonic"]) if previous else now + seconds,
    }
    _local.call = payload
    write_json(path, payload)
    try:
        yield
    finally:
        _local.call = previous
        write_json(path, previous or {**payload, "active": False, "finished_monotonic": time.monotonic()})


def bounded_call(name: str, seconds=10.0):
    def decorate(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            budget = seconds(args[0]) if callable(seconds) else seconds
            with browser_call(name, float(budget)):
                return function(*args, **kwargs)
        return wrapped
    return decorate
