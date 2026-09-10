"""Read-only progress summaries and explicit orchestration diagnostics.

No authentication, rendering, model invocation, locking or filesystem writes.
Mutation helpers only update the supplied mapping; the existing command writer
owns persistence and its original authentication boundary.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from collections import Counter
from pathlib import Path


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _clean_error(error):
    value = str(error)
    value = re.sub(r"data:[^\s;,]+;base64,[A-Za-z0-9+/=]+", "[image data omitted]", value)
    value = re.sub(r"(?i)(bearer\s+|(?:token|api[_-]?key|authorization)\s*[:=]\s*)[^\s,;]+",
                   r"\1[redacted]", value)
    return value[:800]


def diagnostic_input_fingerprint(manifest, command, job_ids=(), parameters=None):
    """Ignore telemetry, not business inputs; identical failures can be grouped."""
    excluded = {"runtime_diagnostics", "timings", "transaction_timings", "metrics",
                "network_health", "concurrency"}
    def stable(value):
        if isinstance(value, dict):
            return {key: stable(child) for key, child in value.items() if key not in excluded}
        if isinstance(value, list):
            return [stable(child) for child in value]
        return value
    selected = set(job_ids)
    scope = {key: value for key, value in manifest.items() if key != "jobs"}
    scope["jobs"] = [job for job in manifest.get("jobs", []) if not selected or job.get("id") in selected]
    return _digest({"command": command, "jobs": sorted(selected), "parameters": parameters,
                    "inputs": stable(scope)})


def record_command_failure(manifest, command, input_fingerprint, error, *, job_ids=(), now=None):
    """Record an actual failed command; never change a job or invent QA results."""
    if not isinstance(input_fingerprint, str) or not input_fingerprint:
        raise ValueError("input_fingerprint is required for a command failure")
    when = time.time() if now is None else now
    if not _number(when):
        raise ValueError("failure timestamp must be finite nonnegative Unix seconds")
    jobs = sorted(set(job_ids))
    scope = _digest({"command": command, "jobs": jobs})
    error_hash = _digest(str(error))
    records = manifest.setdefault("runtime_diagnostics", {}).setdefault("command_failures", [])
    old = next((entry for entry in reversed(records) if entry.get("scope") == scope), None)
    same = old and old.get("input_fingerprint") == input_fingerprint and old.get("error_hash") == error_hash
    count = old.get("consecutive_count", 0) + 1 if same else 1
    record = {"scope": scope, "command": command, "jobs": jobs, "input_fingerprint": input_fingerprint,
              "error_hash": error_hash, "error": _clean_error(error), "consecutive_count": count,
              "recorded_at": when, "diagnosis_required": count >= 2}
    records.append(record)
    del records[:-64]
    return copy.deepcopy(record)


def record_command_success(manifest, command, *, job_ids=()):
    """A genuine success resets that scope's consecutive-failure streak."""
    scope = _digest({"command": command, "jobs": sorted(set(job_ids))})
    for record in manifest.get("runtime_diagnostics", {}).get("command_failures", []):
        if record.get("scope") == scope:
            record["consecutive_count"] = 0
            record["diagnosis_required"] = False


def active_diagnostics(manifest, base=None):
    latest = {}
    for record in manifest.get("runtime_diagnostics", {}).get("command_failures", []):
        latest[record.get("scope")] = record
    if base is not None:
        from lc_command_diagnostics import diagnostic_is_current
    return [copy.deepcopy(record) for record in latest.values() if record.get("diagnosis_required")
            and (base is None or diagnostic_is_current(manifest, base, record))]


def union_seconds(intervals):
    """Union observed intervals, so overlapping model calls count wall time once."""
    valid = sorted((start, end) for start, end in intervals
                   if _number(start) and _number(end) and end >= start)
    if not valid:
        return None
    total, left, right = 0.0, *valid[0]
    for start, end in valid[1:]:
        if start <= right:
            right = max(right, end)
        else:
            total += right - left
            left, right = start, end
    return round(total + right - left, 6)


def timing_summary(manifest):
    """Never turn missing historical start/stop events into zero elapsed time."""
    intervals = {"model": [], "local": [], "user_wait": []}
    attempts = 0
    missing = 0
    for job in manifest.get("jobs", []):
        for attempt in job.get("generation_attempts", []) + job.get("title_effect_attempts", []):
            attempts += 1
            start, end = attempt.get("tool_started_at"), attempt.get("tool_returned_at")
            if _number(start) and _number(end) and end >= start:
                intervals["model"].append((start, end))
            else:
                missing += 1
    runtime = manifest.get("runtime_diagnostics", {})
    # These optional spans are written only from real tool callbacks. Legacy
    # duration-only stages cannot be positioned on the wall clock retroactively.
    for event in runtime.get("intervals", []):
        category = event.get("category")
        start, end = event.get("started_at"), event.get("finished_at")
        if category in intervals and _number(start) and _number(end) and end >= start:
            intervals[category].append((start, end))
    observed = sum(intervals.values(), [])
    window = runtime.get("observation_window", {})
    start, end = window.get("started_at"), window.get("finished_at")
    window_valid = _number(start) and _number(end) and end >= start
    clipped = [(max(left, start), min(right, end)) for left, right in observed
               if window_valid and right >= start and left <= end]
    covered = union_seconds(clipped) if window_valid else None
    return {"model_wall_seconds": union_seconds(intervals["model"]),
            "model_call_seconds": round(sum(end-start for start, end in intervals["model"]), 6)
                                  if intervals["model"] else None,
            "local_wall_seconds": union_seconds(intervals["local"]),
            "user_wait_seconds": union_seconds(intervals["user_wait"]),
            "observed_union_seconds": union_seconds(observed),
            "observation_wall_seconds": round(end-start, 6) if window_valid else None,
            "unclassified_seconds": round(end-start-covered, 6) if covered is not None else None,
            "attempts": attempts, "attempts_without_complete_tool_events": missing,
            "coverage": "explicit_events_only",
            "unclassified_note": "Unclassified gaps are not measured agent reasoning or model service time."}


def record_interval(manifest, category, started_at, finished_at, *, event_id, job_id=None):
    """Idempotent observed interval recorder for the existing authorized writer."""
    if category not in {"model", "local", "user_wait"}:
        raise ValueError("interval category must be model, local or user_wait")
    if not (_number(started_at) and _number(finished_at) and finished_at >= started_at):
        raise ValueError("interval requires ordered finite nonnegative Unix timestamps")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id is required")
    record = {"id": event_id, "category": category, "started_at": started_at,
              "finished_at": finished_at, "job": job_id}
    records = manifest.setdefault("runtime_diagnostics", {}).setdefault("intervals", [])
    old = next((value for value in records if value.get("id") == event_id), None)
    if old is not None:
        if old != record:
            raise ValueError("an observed interval cannot be rewritten")
        return copy.deepcopy(old)
    records.append(record)
    return copy.deepcopy(record)


def build_status(manifest, base, *, now=None, detail=False):
    """Return current progress; no prepare, rendering, report, lock or mutation."""
    import lc_image_pipeline as p
    from lc_scheduler import state
    snapshot = copy.deepcopy(manifest)
    # execution_plan may select a candidate anchor. It may only touch this
    # private snapshot during status; the canonical manifest stays unchanged.
    plan = p.execution_plan(snapshot, base=Path(base))
    plan["scheduler"] = state(snapshot, now=now)
    jobs = snapshot.get("jobs", [])
    counts = dict(Counter(job.get("status", "unknown") for job in jobs))
    required = [job for job in jobs if job.get("required", True) and not p.is_hold(job)]
    inflight = [{"id": job["id"], "kind": "product", "attempt_id": job.get("active_attempt_id")}
                for job in jobs if job.get("status") == "generating"]
    inflight += [{"id": job["id"], "kind": "title_effect", "attempt_id": attempt.get("id")}
                 for job in jobs for attempt in job.get("title_effect_attempts", [])
                 if attempt.get("status") == "started"]
    diagnoses = active_diagnostics(manifest, base)
    next_actions = [{"action": "diagnose", "jobs": value["jobs"], "command": value["command"],
                     "error": value["error"], "consecutive_count": value["consecutive_count"]}
                    for value in diagnoses]
    next_actions += [{"action": entry["action"], "job": entry["id"]} for entry in plan["dispatch"]]
    next_actions += [{"action": "review-prepare", "job": value} for value in plan["deterministic_resume"]]
    next_actions += [{"action": "review", "job": value} for value in plan["review_pending"]]
    if required and all(job.get("status") == "qa_passed" for job in required):
        next_actions.append({"action": "finalize-and-deliver", "note": "Final delivery validation is still required."})
    if not next_actions and inflight:
        next_actions.append({"action": "await-inflight"})
    if not next_actions and plan["scheduler"]["retry_after_seconds"]:
        next_actions.append({"action": "retry-after", "seconds": plan["scheduler"]["retry_after_seconds"]})
    result = {"project_id": snapshot.get("project_id"), "counts": counts, "image_count": len(jobs),
              "required_count": len(required), "qa_passed_count": counts.get("qa_passed", 0),
              "inflight": inflight, "scheduler": plan["scheduler"], "anchor": plan["anchor"],
              "anchor_passed": plan["anchor_passed"], "dispatch": plan["dispatch"],
              "blocked": plan["blocked"], "deterministic_resume": plan["deterministic_resume"],
              "review_pending": plan["review_pending"], "next_actions": next_actions,
              "timing": timing_summary(manifest)}
    if detail:
        result["diagnostics"] = diagnoses
        result["jobs"] = [{key: copy.deepcopy(job[key]) for key in
                           ("id", "status", "blocked_reason", "active_attempt_id", "raw_output", "final_output")
                           if key in job} for job in jobs]
    return result
