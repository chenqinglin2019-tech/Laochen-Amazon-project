"""Wave dispatch for hosts without a JavaScript tool unit (V7.1).

The old manual loop cost ~5 agent calls per image (read prompt, transition, image
call, ingest, status). Here one shell call per wave does the bookkeeping:

    reserve       -> transition every dispatchable job (all existing checks, capacity
                     and anchor rules apply cumulatively) and return each one's bound
                     prompt text and absolute reference paths inline;
    (agent)       -> one image call per reservation, the whole wave back to back, or
                     in parallel when the host allows several calls in one turn;
    ingest-batch  -> ingest every returned image, record tool errors immediately (429
                     is not charged), optionally run the anchor quick check, then
                     reserve and return the next wave in the same call;
    release       -> give back a reservation whose image call never started, without
                     charging any retry or repair budget (at most twice per job).

Nothing here bypasses `transition_job` or `ingest`; invariants stay where they are.
"""
from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path

TIMEOUT_SECONDS = 1800
FREE_RELEASES_PER_JOB = 2
_UNDO_EXCLUDE = {"generation_attempts"}


def _p():
    import lc_image_pipeline as p
    return p


def sweep_timeouts(manifest, base):
    """Same rule as plan: an abandoned call must not hold a model slot forever."""
    p = _p()
    released = []
    for job in manifest["jobs"]:
        started = job.get("generation_started_at")
        if job.get("status") == "generating" and started and time.time() - float(started) > TIMEOUT_SECONDS:
            p.transition_job(manifest, job["id"], "pending",
                             "GENERATION_TIMEOUT: no ingest within 30 minutes; released as a transient timeout", base)
            released.append(job["id"])
    return released


def _active_attempt(job):
    return next((a for a in job.get("generation_attempts", []) if a.get("id") == job.get("active_attempt_id")), None)


def _reservation(manifest, base, job):
    p = _p()
    prompt, _required, _hidden, paths = p.compile_job_prompt(manifest, copy.deepcopy(job), base)
    stored = p.resolve_project_path(job.get("prompt_file"), base, "prompt_file") if job.get("prompt_file") else None
    if stored is None or not stored.is_file() or stored.read_text(encoding="utf-8").rstrip("\n") != prompt.rstrip("\n"):
        return None, "STALE_PROMPT_FILE: the stored prompt differs from the bound prompt; run plan"
    references = [str((base / path).resolve()) if not Path(path).is_absolute() else str(Path(path)) for path in paths]
    attempt = _active_attempt(job) or {}
    return {"job": job["id"], "attempt_id": job["active_attempt_id"], "kind": attempt.get("kind"),
            "speculative": bool(attempt.get("speculative")), "prompt_hash": job["prompt_hash"],
            "prompt": prompt, "prompt_chars": len(prompt), "references": references}, None


def reserve(manifest, base, *, max_count=None, jobs=None):
    p = _p()
    base = Path(base).resolve()
    timed_out = sweep_timeouts(manifest, base)
    plan = p.execution_plan(manifest, base)
    wave_id = "w-" + uuid.uuid4().hex[:8]
    reservations, refusals = [], []
    limit = max_count if isinstance(max_count, int) and max_count > 0 else None
    for entry in plan.get("dispatch", []):
        if entry.get("action") != "image_gen" or (jobs and entry["id"] not in jobs):
            continue
        if limit is not None and len(reservations) >= limit:
            break
        job = p.find_by_id(manifest["jobs"], entry["id"])
        undo = {key: copy.deepcopy(value) for key, value in job.items() if key not in _UNDO_EXCLUDE}
        try:
            p.transition_job(manifest, job["id"], "generating", f"Reserved in dispatch wave {wave_id}", base)
        except p.PipelineError as exc:
            refusals.append({"job": job["id"], "reason": str(exc)[:400]})
            continue
        if job.get("status") != "generating":
            refusals.append({"job": job["id"], "reason": job.get("blocked_reason") or job.get("failed_reason") or job["status"],
                             "persisted": True})
            continue
        attempt = _active_attempt(job)
        attempt["undo"], attempt["wave_id"] = undo, wave_id
        reservation, problem = _reservation(manifest, base, job)
        if problem:
            release(manifest, base, job["id"], job["active_attempt_id"], problem, force_free=True)
            refusals.append({"job": job["id"], "reason": problem})
            continue
        reservations.append(reservation)
    after = p.execution_plan(manifest, base)
    seen, view_once = set(), []
    for item in reservations:
        for path in item["references"]:
            if path not in seen:
                seen.add(path)
                view_once.append(path)
    return {"wave": {"id": wave_id, "anchor": after.get("anchor"), "anchor_passed": after.get("anchor_passed"),
                     "speculative": [r["job"] for r in reservations if r["speculative"]], "view_once": view_once},
            "reservations": reservations, "refusals": refusals, "timed_out": timed_out,
            "local": [d["id"] for d in after.get("dispatch", []) if d.get("action") == "compose"],
            "scheduler": after.get("scheduler"),
            "next": ("Call the image tool once per reservation with its prompt exactly and its references in order, "
                     "then ingest-batch all results in one call" if reservations else
                     "Nothing to generate now; see refusals/next_actions" )}


def release(manifest, base, job_id, attempt_id, reason, *, force_free=False):
    """Undo a reservation whose image call never started; charged after two free releases."""
    p = _p()
    job = p.find_by_id(manifest["jobs"], job_id)
    if job is None:
        raise p.PipelineError(f"Unknown job: {job_id}")
    attempt = _active_attempt(job)
    if job.get("status") != "generating" or attempt is None or attempt.get("id") != attempt_id:
        raise p.PipelineError(f"STALE_ATTEMPT: {job_id} has no active reservation {attempt_id}")
    started = any(key in attempt for key in ("tool_started_at", "tool_returned_at", "unpaired_tool_returned_at", "ingested_at"))
    undo = attempt.get("undo")
    if started or undo is None or (not force_free and job.get("free_releases", 0) >= FREE_RELEASES_PER_JOB):
        p.transition_job(manifest, job_id, "pending", f"RELEASED_AFTER_FREE_LIMIT: {reason}"[:300], base)
        attempt.pop("undo", None)
        return {"job": job_id, "attempt_id": attempt_id, "released": True, "charged": True}
    history = job.get("generation_attempts", [])
    attempt.pop("undo", None)
    # Attempt statuses are validated (dispatched/ingested); the flag marks a never-started reservation.
    attempt.update(released_unstarted=True, released_at=time.time(), release_reason=str(reason)[:300])
    free = job.get("free_releases", 0) + (0 if force_free else 1)
    job.clear()
    job.update(undo)
    job["generation_attempts"] = history
    job["free_releases"] = free
    return {"job": job_id, "attempt_id": attempt_id, "released": True, "charged": False}


def _store_annotations(base, job, annotations):
    p = _p()
    path = Path(base) / "review" / "annotations" / f"{job['id']}.json"
    p.write_json(path, {"bound_raw_sha256": job.get("bound_raw_sha256"), "annotations": annotations})
    return p.relpath(path, Path(base))


def load_stored_annotations(manifest, base, job_ids):
    """Annotations captured at ingest time, still bound to the current raw image."""
    p = _p()
    result = {}
    for job_id in job_ids:
        job = p.find_by_id(manifest["jobs"], job_id)
        path = Path(base) / "review" / "annotations" / f"{job_id}.json"
        if job is None or not path.is_file():
            continue
        try:
            record = p.read_json(path)
        except p.PipelineError:
            continue
        if record.get("bound_raw_sha256") and record.get("bound_raw_sha256") == job.get("bound_raw_sha256"):
            result[job_id] = record.get("annotations") or {}
    return result


def ingest_batch(manifest, base, items, *, anchor_notes=None, anchor_verdicts=None, reserve_next=True, max_count=None):
    import lc_workflow
    from lc_speculation import after_ingest
    p = _p()
    base = Path(base).resolve()
    ingested, failures, released, item_errors, annotations_stored = [], [], [], [], []
    artifacts = [i for i in items if i.get("artifact")]
    errors = [i for i in items if i.get("error") and not i.get("artifact")]
    unstarted = [i for i in items if i.get("not_started") and not i.get("artifact")]
    for item in artifacts:
        trial = copy.deepcopy(manifest)
        try:
            result = lc_workflow.ingest(trial, base, item["job"], Path(item["artifact"]), item["attempt_id"],
                                        tool_returned_at=item.get("tool_returned_at"))
        except (p.PipelineError, ValueError, OSError) as exc:
            item_errors.append({"job": item.get("job"), "error": str(exc)[:400]})
            continue
        manifest.clear()
        manifest.update(trial)
        job = p.find_by_id(manifest["jobs"], item["job"])
        attempt = next((a for a in job.get("generation_attempts", []) if a.get("id") == item["attempt_id"]), {})
        attempt.pop("undo", None)
        voided = after_ingest(manifest, job, attempt)
        if item.get("annotations") and not voided:
            annotations_stored.append(_store_annotations(base, job, item["annotations"]))
        ingested.append({"job": item["job"], "status": job["status"], "idempotent": result.get("idempotent", False),
                         "voided": voided})
    anchor = None
    anchor_id = manifest.get("anchor_job_id")
    if (anchor_notes or anchor_verdicts) and anchor_id:
        from lc_anchor import anchor_approve
        try:
            anchor = anchor_approve(manifest, base, anchor_id, notes=anchor_notes, verdicts=anchor_verdicts)
        except p.PipelineError as exc:
            item_errors.append({"job": anchor_id, "error": f"anchor check: {exc}"[:400]})
    for item in errors:
        job = p.find_by_id(manifest["jobs"], item.get("job"))
        attempt = _active_attempt(job) if job else None
        if job is None or job.get("status") != "generating" or attempt is None or attempt.get("id") != item.get("attempt_id"):
            item_errors.append({"job": item.get("job"), "error": "STALE_ATTEMPT: no matching active reservation"})
            continue
        attempt.pop("undo", None)
        try:
            p.transition_job(manifest, job["id"], "pending", f"TOOL_ERROR: {item['error']}"[:300], base,
                             retry_after_seconds=item.get("retry_after_seconds"))
            failures.append({"job": job["id"], "status": job["status"]})
        except (p.PipelineError, ValueError) as exc:
            item_errors.append({"job": job["id"], "error": str(exc)[:400]})
    for item in unstarted:
        try:
            released.append(release(manifest, base, item["job"], item["attempt_id"], item.get("reason") or "not started"))
        except p.PipelineError as exc:
            item_errors.append({"job": item.get("job"), "error": str(exc)[:400]})
    result = {"ingested": ingested, "anchor": anchor, "failures_recorded": failures, "released": released,
              "annotations_stored": annotations_stored, "item_errors": item_errors}
    if reserve_next:
        result.update(reserve(manifest, base, max_count=max_count))
    else:
        plan = p.execution_plan(manifest, base)
        result.update(scheduler=plan.get("scheduler"), anchor_passed=plan.get("anchor_passed"))
    from lc_workflow import review_candidate
    result["review_ready"] = [job["id"] for job in manifest["jobs"] if review_candidate(job) and job.get("status") != "qa_passed"]
    from lc_composition import applies, proof_valid
    result["composition_review_required"] = [job["id"] for job in manifest["jobs"]
        if applies(manifest, job) and job.get("status") in {"generated", "review_pending", "layout_repair_needed"}
        and not proof_valid(manifest, job, base)]
    return result


def items_from_args(args):
    """CLI: --item JOB ATTEMPT PATH, --failed JOB ATTEMPT ERROR, --not-started JOB ATTEMPT, or --results FILE."""
    items = []
    for job, attempt, artifact in getattr(args, "item", None) or []:
        items.append({"job": job, "attempt_id": attempt, "artifact": artifact, "tool_returned_at": time.time()})
    for job, attempt, error in getattr(args, "failed", None) or []:
        items.append({"job": job, "attempt_id": attempt, "error": error})
    for job, attempt in getattr(args, "not_started", None) or []:
        items.append({"job": job, "attempt_id": attempt, "not_started": True})
    if getattr(args, "results", None):
        payload = json.loads(Path(args.results).read_text(encoding="utf-8-sig"))
        items.extend(payload.get("items", payload) if isinstance(payload, dict) else payload)
    return items
