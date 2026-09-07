"""Local wall-clock stage telemetry; never a business/cache dependency.

perf_counter spans measure work executed in this process. External agent visual
analysis/planning has no observable start/stop event here and is explicitly
unavailable, not zero. Batch spans live only on the first participating job.
Parent spans name contained phases so reports do not add overlapping durations.
"""
from __future__ import annotations

import time
import uuid


def record_stage(owner, stage, *, started=None, seconds=None, cached=False, **fields):
    if seconds is None:
        seconds = time.perf_counter() - started
    record = {"id": uuid.uuid4().hex, "stage": stage, "seconds": round(max(0.0, seconds), 6), "recorded_at": time.time(),
              "cached": bool(cached), **fields}
    owner.setdefault("timings", []).append(record)
    return record


def record_batch_stage(manifest, selected, stage, **fields):
    selected = set(selected)
    participating = [job for job in manifest.get("jobs", []) if job["id"] in selected]
    if not participating:
        return None
    return record_stage(participating[0], stage, scope="batch", jobs=[job["id"] for job in participating],
                        shared_costs_recorded_once=True, **fields)
