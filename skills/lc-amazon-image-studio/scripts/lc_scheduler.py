"""Shared model capacity and transport health; never change visual dependencies."""
from __future__ import annotations

import copy
import json
import math
import re
import time
from pathlib import Path


def default_policy():
    return {"version": 1, "mode": "adaptive", "max_concurrency": 4}


def adaptive(manifest):
    policy = manifest.get("scheduler_policy")
    return isinstance(policy, dict) and policy.get("mode") == "adaptive"


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _seconds(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def validate(manifest):
    errors = []
    policy = manifest.get("scheduler_policy")
    if "scheduler_policy" in manifest:
        if (not isinstance(policy, dict) or policy.get("version") != 1
                or type(policy.get("version")) is not int or policy.get("mode") != "adaptive"
                or not _integer(policy.get("max_concurrency"), 2, 4)):
            errors.append("scheduler_policy requires version 1, mode adaptive and max_concurrency 2..4")
    maximum = policy.get("max_concurrency", 4) if adaptive(manifest) else 2
    if not _integer(maximum, 2, 4):
        maximum = 4
    if not _integer(manifest.get("concurrency"), 1, maximum):
        errors.append(f"concurrency must be an integer in 1..{maximum}")
    health = manifest.get("network_health", {})
    if not isinstance(health, dict):
        errors.append("network_health must be an object")
        return errors
    if "tool_capacity" in health and not _integer(health["tool_capacity"], 1, 4):
        errors.append("network_health.tool_capacity must be an integer in 1..4")
    for name in ("adaptive_successes", "scheduler_epoch", "consecutive_timeouts"):
        if name in health and (type(health[name]) is not int or health[name] < 0):
            errors.append(f"network_health.{name} must be a nonnegative integer")
    for name in ("last_backoff_at", "cooldown_until", "retry_after_until"):
        if name in health and not _seconds(health[name]):
            errors.append(f"network_health.{name} must be finite nonnegative Unix seconds")
    return errors


def set_tool_capacity(manifest, capacity):
    if not _integer(capacity, 1, 4):
        raise ValueError("tool_capacity must be an integer in 1..4")
    manifest.setdefault("network_health", {})["tool_capacity"] = capacity


def retry_after(value):
    if value is not None and not _seconds(value):
        raise ValueError("retry_after_seconds must be finite nonnegative seconds")
    return value


def active_count(manifest, *, exclude_product=None):
    from lc_image_pipeline import active_model_count
    return active_model_count(manifest, exclude_product=exclude_product)


def state(manifest, *, now=None, exclude_product=None):
    now = time.time() if now is None else now
    health = manifest.get("network_health", {})
    configured = manifest.get("concurrency", 2)
    maximum = manifest.get("scheduler_policy", {}).get("max_concurrency", 4) if adaptive(manifest) else 2
    ceiling = min(configured, maximum, health.get("tool_capacity", maximum))
    wait = max(0.0, health.get("retry_after_until", 0) - now)
    active = active_count(manifest, exclude_product=exclude_product)
    return {"concurrency": configured, "effective_concurrency": ceiling,
            "active_model_calls": active, "model_capacity": 0 if wait else max(0, ceiling - active),
            "retry_after_seconds": round(wait, 3), "cooldown_until": health.get("cooldown_until", 0)}


def anchor_passed(manifest):
    anchor = manifest.get("anchor_job_id")
    return any(job.get("id") == anchor and job.get("status") == "qa_passed"
               for job in manifest.get("jobs", []))


def require_capacity(manifest, job, *, exclude_product=None):
    current = state(manifest, exclude_product=exclude_product)
    if current["retry_after_seconds"]:
        raise ValueError(f"MODEL_RETRY_AFTER: wait {current['retry_after_seconds']} seconds before dispatch")
    if current["model_capacity"] < 1:
        raise ValueError("Generation concurrency is full; finish an active image before dispatching another")
    if adaptive(manifest):
        if manifest.get("generation_gate", {}).get("status") != "open":
            raise ValueError("MODEL_GENERATION_GATE_CLOSED: run plan before dispatch")
        if not anchor_passed(manifest):
            if manifest.get("anchor_job_id") != job.get("id"):
                raise ValueError("MODEL_ANCHOR_REQUIRED: only the selected anchor may run before its QA passes")
            if active_count(manifest, exclude_product=exclude_product):
                raise ValueError("MODEL_ANCHOR_REQUIRED: finish the active anchor call first")
    return current


def bind_attempt(manifest, attempt):
    if adaptive(manifest):
        attempt["scheduler_concurrency"] = manifest.get("concurrency", 2)
        attempt["scheduler_epoch"] = manifest.get("network_health", {}).get("scheduler_epoch", 0)


def failure_kind(reason):
    reason = str(reason or "").lower()
    if re.search(r"\b429\b|rate[ _-]?limit", reason):
        return "rate_limit"
    if "timeout" in reason or "timed out" in reason:
        return "timeout"
    return "other"


def record_failure(manifest, attempt, reason, *, retry_after_seconds=None, now=None):
    delay = retry_after(retry_after_seconds)
    now = time.time() if now is None else now
    kind = failure_kind(reason)
    if not adaptive(manifest):
        if kind == "rate_limit":
            manifest["concurrency"] = 1
        elif kind == "timeout":
            health = manifest.setdefault("network_health", {})
            health["consecutive_timeouts"] = health.get("consecutive_timeouts", 0) + 1
            if health["consecutive_timeouts"] >= 2:
                manifest["concurrency"] = 1
        if delay is not None:
            health = manifest.setdefault("network_health", {})
            health["retry_after_until"] = max(health.get("retry_after_until", 0), now + delay)
        return
    if attempt is None or attempt.get("scheduler_outcome"):
        return
    attempt["scheduler_outcome"] = "failed"
    attempt["scheduler_failure_kind"] = kind
    health = manifest.setdefault("network_health", {})
    health["adaptive_successes"] = 0
    if kind == "timeout":
        health["consecutive_timeouts"] = health.get("consecutive_timeouts", 0) + 1
    else:
        health["consecutive_timeouts"] = 0
    if kind in {"rate_limit", "timeout"}:
        manifest["concurrency"] = (1 if kind == "rate_limit" or health.get("consecutive_timeouts", 0) >= 2
                                   else max(1, manifest.get("concurrency", 2) - 1))
    if kind in {"rate_limit", "timeout"} or (delay is not None and delay > 0):
        health["scheduler_epoch"] = health.get("scheduler_epoch", 0) + 1
        health["last_backoff_at"] = now
        health["cooldown_until"] = max(health.get("cooldown_until", 0), now + 60)
    if delay is not None:
        health["retry_after_until"] = max(health.get("retry_after_until", 0), now + delay)
        health["cooldown_until"] = max(health.get("cooldown_until", 0), now + delay)


def record_success(manifest, attempt, *, now=None):
    if not adaptive(manifest):
        manifest.setdefault("network_health", {})["consecutive_timeouts"] = 0
        return
    if attempt.get("scheduler_outcome"):
        return
    attempt["scheduler_outcome"] = "success"
    now = time.time() if now is None else now
    health = manifest.setdefault("network_health", {})
    if (attempt.get("scheduler_epoch") != health.get("scheduler_epoch", 0)
            or attempt.get("scheduler_concurrency") != manifest.get("concurrency", 2)):
        return  # A late return cannot heal a newer backoff or grow a newer tier.
    health["consecutive_timeouts"] = 0
    if (not anchor_passed(manifest)
            or now < max(health.get("cooldown_until", 0), health.get("retry_after_until", 0))):
        return
    ceiling = min(manifest["scheduler_policy"]["max_concurrency"], health.get("tool_capacity", 4))
    if manifest["concurrency"] >= ceiling:
        health["adaptive_successes"] = 0
        return
    health["adaptive_successes"] = health.get("adaptive_successes", 0) + 1
    if health["adaptive_successes"] >= 2:
        manifest["concurrency"] += 1
        health["adaptive_successes"] = 0
        health["scheduler_epoch"] = health.get("scheduler_epoch", 0) + 1


def source_dispatch_decision(manifest, job, base):
    """Verify prepared evidence from real bytes without decoding or writing previews."""
    import lc_image_pipeline as p
    import lc_quality as q

    candidate = copy.deepcopy(manifest)
    target = next(value for value in candidate["jobs"] if value["id"] == job["id"])
    refs = {value["id"]: value for value in candidate.get("references", [])}
    selected = q._reference_ids(candidate, target)
    try:
        index = json.loads((Path(base) / "review/source_quality/index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {}
    if not isinstance(index, dict):
        index = {}
    entries = index.get("entries", {})
    if not isinstance(entries, dict):
        entries = {}
    extra = []
    for rid in selected:
        ref = refs.get(rid)
        if ref is None:
            continue
        path = p.resolve_path(ref.get("path"), base)
        actual = p.sha256_file(path) if path and path.is_file() else "MISSING"
        if actual != ref.get("sha256"):
            extra.append(f"SOURCE_REVIEW_STALE:{rid}")
        ref["sha256"] = actual
        region = q.source_region_fingerprint(ref)
        prepared = entries.get("source_" + region, {})
        if not isinstance(prepared, dict):
            prepared = {}
        # Prepared metadata may survive compact delivery; normal plan refreshes
        # this JSON even when reviewed raster previews are intentionally absent.
        if (index.get("version") != q.VERSION or not prepared
                or ref.get("quality_metrics", {}).get("region_fingerprint") != region
                or ref.get("image_size") != prepared.get("image_size")
                or ref.get("product_pixel_size") != prepared.get("product_pixel_size")):
            extra.append(f"SOURCE_PREPARATION_STALE:{rid}")
    for record in target.get("layer_asset_hashes", []):
        for field, hash_field in (("asset_input", "asset_sha256"), ("mask_input", "mask_sha256")):
            if not record.get(field):
                continue
            path = p.resolve_path(record[field], base)
            actual = p.sha256_file(path) if path and path.is_file() else "MISSING"
            if actual != record.get(hash_field):
                extra.append(f"SOURCE_LAYER_ASSET_STALE:{record.get('index')}:{field}")
    result = q.decide_job(candidate, target)
    result["blocked_reasons"] = list(dict.fromkeys(result["blocked_reasons"] + extra))
    return result
