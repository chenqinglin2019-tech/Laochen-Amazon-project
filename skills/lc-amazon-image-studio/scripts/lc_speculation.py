"""Parallel first wave (V7.1, opt-in per project via `anchor_policy`).

Strict projects (no policy) keep the original rule: only the anchor generates until
its product check passes. With `anchor_policy={"version":1,"mode":"parallel_first_wave"}`
the anchor and up to (ceiling-1) siblings start together; their attempts are tagged
`speculative`. Once the anchor image is ingested, nothing new starts until its quick
check. If that check fails on geometry, material or components (a systematic product
misread would repeat in every sibling), the wave's siblings are voided back to
`pending`. A voided attempt is an ingested *initial* attempt, so it never consumes the
single quality-repair budget, and the next dispatch is again an initial generation.
A clarity-only failure keeps the siblings. After any anchor failure, no further
speculation happens for that anchor generation.
"""
from __future__ import annotations

import time

SYSTEMATIC_CHECKS = ("geometry", "material", "components")
VOIDABLE_STATUSES = {"generated", "review_pending", "generation_repair_needed", "layout_repair_needed",
                     "export_repair_needed", "repair_needed"}


def parallel(manifest) -> bool:
    policy = manifest.get("anchor_policy")
    return isinstance(policy, dict) and policy.get("mode") == "parallel_first_wave"


def _find(manifest, job_id):
    return next((job for job in manifest.get("jobs", []) if job.get("id") == job_id), None)


def _anchor_generation(anchor_job):
    return (anchor_job or {}).get("prompt_hash")


def speculative_attempts(manifest, anchor_job):
    """Live (not voided/released) speculative attempts tied to this anchor generation."""
    generation = _anchor_generation(anchor_job)
    found = []
    for job in manifest.get("jobs", []):
        for attempt in job.get("generation_attempts", []):
            tag = attempt.get("speculative") or {}
            if (tag.get("anchor_job_id") == anchor_job.get("id") and tag.get("anchor_generation") == generation
                    and attempt.get("speculative_outcome") not in {"voided"} and not attempt.get("released_unstarted")):
                found.append((job, attempt))
    return found


def candidates(manifest, ready, anchor_id, ceiling):
    """Siblings that may start alongside a not-yet-checked anchor (risk order kept)."""
    if not parallel(manifest) or not anchor_id:
        return []
    anchor_job = _find(manifest, anchor_id)
    if anchor_job is None or anchor_job.get("status") not in {"pending", "generating"}:
        return []   # anchor already ingested (awaiting its check) or blocked: nothing new starts
    generation = _anchor_generation(anchor_job)
    failure = anchor_job.get("anchor_product_failure") or {}
    if failure.get("generation") == generation or failure.get("any"):
        return []
    slots = max(0, ceiling - 1 - len(speculative_attempts(manifest, anchor_job)))
    picked = []
    for job in ready:
        if len(picked) >= slots:
            break
        if (job.get("id") == anchor_id or job.get("render_mode") == "pixel_composite"
                or job.get("status") != "pending" or job.get("pending_attempt_kind") == "quality_repair"
                or (job.get("speculative_voided") or {}).get("anchor_generation") == generation):
            continue
        picked.append(job)
    return picked


def eligible(manifest, job, ceiling) -> bool:
    anchor_id = manifest.get("anchor_job_id")
    return any(j.get("id") == job.get("id") for j in candidates(manifest, [job], anchor_id, ceiling))


def tag_attempt(manifest, job, attempt):
    anchor_job = _find(manifest, manifest.get("anchor_job_id"))
    if anchor_job is not None and anchor_job.get("id") != job.get("id"):
        attempt["speculative"] = {"anchor_job_id": anchor_job["id"], "anchor_generation": _anchor_generation(anchor_job),
                                  "anchor_attempt_id": anchor_job.get("active_attempt_id")}


def void_job(manifest, job, attempt, reason):
    """Return a speculative sibling to pending without charging any budget."""
    from lc_image_pipeline import clear_reviews
    attempt["speculative_outcome"] = "voided"
    attempt["voided_at"] = time.time()
    job["status"] = "pending"
    job["status_reason"] = reason
    job["repair_in_progress"] = False
    job.pop("pending_attempt_kind", None)
    clear_reviews(job, image_changed=True)
    for key in ("generated_prompt_hash", "bound_raw_sha256", "final_prompt_hash", "final_sha256",
                "rendered_layout_hash", "exported_hash", "generation_geometry_lock"):
        job.pop(key, None)
    job["speculative_voided"] = {"anchor_generation": (attempt.get("speculative") or {}).get("anchor_generation"),
                                 "attempt_id": attempt.get("id"), "at": attempt["voided_at"]}
    job["queued_at"] = time.time()


def record_anchor_failure(manifest, anchor_job, verdicts):
    """Called after a failed anchor product check; voids the wave on systematic failures."""
    failed = {name for name, value in (verdicts or {}).items() if (value or {}).get("verdict") == "fail"}
    generation = _anchor_generation(anchor_job)
    anchor_job["anchor_product_failure"] = {"generation": generation, "checks": sorted(failed), "at": time.time()}
    voided, deferred = [], []
    if not parallel(manifest) or not failed & set(SYSTEMATIC_CHECKS):
        return {"voided": voided, "void_on_ingest": deferred}
    for job, attempt in speculative_attempts(manifest, anchor_job):
        if attempt is not (job.get("generation_attempts") or [None])[-1]:
            continue  # a later attempt already replaced it
        if job.get("status") == "generating" and attempt.get("id") == job.get("active_attempt_id"):
            attempt["speculative_outcome"] = "void_on_ingest"
            deferred.append(job["id"])
        elif job.get("status") in VOIDABLE_STATUSES:
            void_job(manifest, job, attempt, "SPECULATIVE_VOIDED: the anchor product check failed "
                                             f"({', '.join(sorted(failed))}); regenerate after the anchor is fixed")
            voided.append(job["id"])
    return {"voided": voided, "void_on_ingest": deferred}


def after_ingest(manifest, job, attempt):
    """A sibling that was still running when its anchor failed is voided on return."""
    if attempt.get("speculative_outcome") == "void_on_ingest":
        void_job(manifest, job, attempt, "SPECULATIVE_VOIDED: the anchor product check failed while this image was generating")
        return True
    return False
