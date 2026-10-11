"""V8 one-pass production: planned designs, bounded attempts, direct delivery."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

from PIL import Image

from lc_one_pass_design import ID, adopt_templates, canvas_valid, compile_design, validate_project
from lc_one_pass_export import alpha_background, export_job, export_settings, normalize, open_image, verify_export
from lc_one_pass_io import (StudioError, digest, external_image, inside, project_lock, read_json,
                            sha256, write_bytes, write_json)
from lc_one_pass_main import BACKGROUND_ERRORS, PROCESSING_VERSION, prepare_artifact, verify_prepared

ROOT = Path(__file__).resolve().parents[1]
ATTEMPT_TTL = 1800
MAIN_BACKGROUND_REPAIR_LIMIT = 3
ACTIVE = {"generating", "awaiting_result"}
JOB_INPUTS = {"kind", "required", "canvas", "source_reference_ids", "design_brief", "approved_copy",
              "human_source", "export_keywords", "template_slot_role", "selling_job", "a_plus_module",
              "main_foreground_type"}
PROJECT_INPUTS = {"product_truth", "facts", "critical_details", "style_contract", "product_profile",
                  "design_template_library_dir", "design_template_set_id", "design_template_policy",
                  "concurrency", "marketplace", "language"}
SLOTS = [
    ("01_main", "Exact product and included components"),
    ("02_size_or_components", "Confirmed dimensions or included components"),
    ("03_primary_use_case", "The primary real use case"),
    ("04_compatibility_or_installation", "Supported compatibility or installation"),
    ("05_material_or_detail", "Evidence-backed material or structural details"),
    ("06_storage_or_package", "Storage, portability or included packaging"),
    ("07_problem_solution", "Resolve a real purchase concern"),
]


def require_auth():
    from lc_auth_pass import check_pass
    passed, _reason = check_pass(ROOT)
    if not passed:
        raise StudioError("AUTH_PASS_REQUIRED: run the original scripts/auth_gate.py")


def verify_runtime():
    import PIL
    if sys.version_info < (3, 11):
        raise StudioError("PYTHON_3_11_REQUIRED")
    return {"workflow_policy": "one_pass_v1", "commands": {"python": sys.executable},
            "python": sys.version.split()[0], "pillow": PIL.__version__,
            "requirements": ["Python>=3.11", "Pillow"], "browser_required": False}


def job_skeleton(identifier, goal, kind, canvas):
    return {"id": identifier, "kind": kind, "required": True, "canvas": list(canvas),
            "status": "pending", "design_brief": {"goal": goal,
                "scene": "Product only, transparent background" if kind == "main" else "",
                "composition": "Centered, fully visible, with clear margins" if kind == "main" else ""},
            "approved_copy": [], "human_source": "none", "generation_attempts": [],
            "transient_failures": 0, "free_releases": 0, "background_repairs": 0,
            **({"main_prompt_version": 2, "main_processing_version": PROCESSING_VERSION,
                "main_foreground_type": "unknown"} if kind == "main" else {})}


def init_project(args):
    if not ID.fullmatch(args.project_id):
        raise StudioError("INVALID_PROJECT_ID")
    if args.short_edge < 1600 or args.short_edge > 10000:
        raise StudioError("LISTING_SHORT_EDGE_MUST_BE_1600_TO_10000")
    if args.listing_aspect == "1:1.3" and args.short_edge % 10:
        raise StudioError("PORTRAIT_SHORT_EDGE_MUST_BE_MULTIPLE_OF_10")
    canvas = [args.short_edge, args.short_edge if args.listing_aspect == "1:1" else args.short_edge * 13 // 10]
    if not canvas_valid(canvas) or not 1 <= args.listing_count <= 30:
        raise StudioError("INVALID_LISTING_SPEC")
    jobs = []
    for i in range(args.listing_count):
        identifier, goal = SLOTS[i] if i < len(SLOTS) else (f"{i+1:02d}_secondary", "User planned image")
        jobs.append(job_skeleton(identifier, goal, "main" if i == 0 else "secondary", canvas))
    modules = args.a_plus_modules
    if modules:
        modules = [item for spec in modules for item in spec.split(",") if item]
    elif args.include_a_plus:
        if not 1 <= args.a_plus_count <= 20:
            raise StudioError("INVALID_A_PLUS_COUNT")
        modules = [args.a_plus_module or "feature"] * args.a_plus_count
    for i, spec in enumerate(modules or []):
        name, separator, size = spec.partition(":")
        try:
            module_canvas = [int(value) for value in size.lower().split("x")] if separator else (args.a_plus_canvas or [1464, 600])
        except ValueError:
            raise StudioError("INVALID_A_PLUS_CANVAS") from None
        if not name.strip() or not canvas_valid(module_canvas):
            raise StudioError("INVALID_A_PLUS_MODULE")
        job = job_skeleton(f"{len(jobs)+1:02d}_a_plus", f"A+ module: {name}", "a_plus", module_canvas)
        job["a_plus_module"] = name
        jobs.append(job)
    manifest = {"schema_version": "LC-ONE-PASS/1", "workflow_policy": "one_pass_v1",
                "project_id": args.project_id, "marketplace": args.marketplace, "language": args.language,
                "concurrency": args.concurrency, "references": [], "jobs": jobs,
                "product_truth": {"product": "", "geometry_lock": {}, "material_lock": {}, "scene_scale_lock": {}},
                "facts": [], "critical_details": [],
                "style_contract": {"direction": "Clean product photography, readable hierarchy and a consistent restrained palette"}}
    validate_project(manifest)
    path = Path(args.project_dir).expanduser().resolve() / "project_manifest.json"
    with project_lock(path):
        if path.exists():
            raise StudioError("PROJECT_ALREADY_EXISTS")
        write_json(path, manifest)
    return {"manifest": str(path), "workflow_policy": "one_pass_v1", "image_count": len(jobs)}


def find_job(manifest, identifier):
    job = next((item for item in manifest["jobs"] if item["id"] == identifier), None)
    if job is None:
        raise StudioError(f"JOB_NOT_FOUND:{identifier}")
    return job


def selected_jobs(manifest, identifiers):
    if identifiers:
        for identifier in identifiers:
            find_job(manifest, identifier)
    return [job for job in manifest["jobs"] if not identifiers or job["id"] in identifiers]


def configure(manifest, args):
    data = read_json(args.input)
    if not isinstance(data, dict) or set(data) - PROJECT_INPUTS - {"jobs"}:
        raise StudioError("CONFIGURE_ACCEPTS_PLANNING_INPUTS_ONLY")
    if not isinstance(data.get("jobs", []), list):
        raise StudioError("CONFIGURE_JOBS_MUST_BE_LIST")
    shared_changed = any(data[key] != manifest.get(key) for key in PROJECT_INPUTS & data.keys() if key != "concurrency")
    if shared_changed and any(job["status"] in ACTIVE for job in manifest["jobs"]):
        raise StudioError("INPUT_CHANGE_WHILE_ATTEMPT_ACTIVE: reconcile the existing call first")
    if "design_template_set_id" in data and data["design_template_set_id"] != manifest.get("design_template_set_id"):
        manifest.pop("template_snapshot", None)
    for key in PROJECT_INPUTS & data.keys():
        manifest[key] = copy.deepcopy(data[key])
    for patch in data.get("jobs", []):
        if not isinstance(patch, dict) or set(patch) - JOB_INPUTS - {"id"}:
            raise StudioError("CONFIGURE_JOB_ACCEPTS_PLANNING_INPUTS_ONLY")
        job = find_job(manifest, patch["id"])
        if any(value != job.get(key) for key, value in patch.items() if key != "id"):
            if job["status"] in ACTIVE:
                raise StudioError("INPUT_CHANGE_WHILE_ATTEMPT_ACTIVE: reconcile the existing call first")
        if ("main_foreground_type" in patch and job.get("main_processing") and
                patch["main_foreground_type"] != job.get("main_foreground_type", "unknown")):
            job.pop("main_background_check", None)
            job.pop("delivery", None)
            job.update(status="needs_input", blocked_reason="MAIN_PROCESSING_SETTINGS_CHANGED",
                       technical_failure_fingerprint=job.get("generation_fingerprint"))
        job.update(copy.deepcopy({key: value for key, value in patch.items() if key != "id"}))
    validate_project(manifest)
    return {"configured": True, "next_action": "plan"}


def add_references(manifest, base, args):
    added = []
    views = args.views or []
    if views and len(views) != len(args.photos):
        raise StudioError("REFERENCE_VIEW_COUNT_MISMATCH")
    for i, value in enumerate(args.photos):
        source = external_image(value)
        image = open_image(source)
        hashed = sha256(source)
        existing = next((ref for ref in manifest["references"] if ref["sha256"] == hashed and ref["role"] == args.role), None)
        if existing:
            added.append(existing)
            continue
        if any(job["status"] in ACTIVE for job in manifest["jobs"]):
            raise StudioError("REFERENCE_CHANGE_WHILE_ATTEMPT_ACTIVE: reconcile the existing call first")
        suffix = source.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise StudioError("UNSUPPORTED_REFERENCE_SUFFIX")
        identifier = f"{args.role}_{hashed[:16]}"
        relative = f"source/{identifier}{suffix}"
        write_bytes(inside(base, relative), source.read_bytes(), immutable=True)
        if sha256(inside(base, relative)) != hashed:
            raise StudioError("SOURCE_CHANGED_DURING_COPY")
        ref = {"id": identifier, "path": relative, "role": args.role,
               "sha256": hashed, "view": views[i] if views else "unspecified", "size": list(image.size)}
        manifest["references"].append(ref)
        added.append(ref)
    return {"references": added, "next_action": "configure/plan"}


def bind_job(manifest, job, base):
    if job.get("repair_requested"):
        original = compile_design(manifest, job, base, repair=False)["generation_fingerprint"]
        if original != job.get("background_repair_source_fingerprint"):
            if job["status"] in ACTIVE or job.get("active_attempt_id"):
                raise StudioError("INPUT_CHANGED_DURING_ACTIVE_ATTEMPT: reconcile the existing call first")
            for key in ("repair_requested", "repair_dispatched", "background_repair_target",
                        "background_repair_source_fingerprint"):
                job.pop(key, None)
            job["background_repairs"] = 0
    binding = compile_design(manifest, job, base, repair=bool(job.get("repair_requested")))
    previous = job.get("generation_fingerprint")
    if previous and previous != binding["generation_fingerprint"]:
        if job["status"] in ACTIVE or job.get("active_attempt_id"):
            raise StudioError("INPUT_CHANGED_DURING_ACTIVE_ATTEMPT: reconcile the existing call first")
        job.pop("delivery", None)
        job.pop("main_background_check", None)
        job.pop("main_processing", None)
        job.pop("blocked_reason", None)
        job.pop("technical_failure_fingerprint", None)
        job["status"] = "pending"
        # Input changes create a new generation revision, not a quality retry.
        job["transient_failures"] = 0
    prompt_file = f"prompts/{job['id']}-{binding['generation_fingerprint'][:16]}.txt"
    write_bytes(inside(base, prompt_file), binding["prompt"].encode(), immutable=True)
    job.update({key: value for key, value in binding.items() if key != "prompt"})
    job["prompt_file"] = prompt_file
    job.pop("plan_issues", None)
    if job["status"] == "needs_input" and job.get("technical_failure_fingerprint") != binding["generation_fingerprint"]:
        job["status"] = "pending"
    if (job["status"] == "ready_to_deliver" and
            job.get("delivery", {}).get("settings_hash") != digest(export_settings(job))):
        if sha256(inside(base, job["raw_output"])) != job["raw_sha256"]:
            raise StudioError("RAW_FILE_CHANGED")
        job["delivery"] = export_job(job, base)
    return binding


def plan(manifest, base, args):
    require_auth()
    adopt_templates(manifest, base)
    for job in selected_jobs(manifest, args.job):
        try:
            bind_job(manifest, job, base)
        except (OSError, ValueError, KeyError) as exc:
            job["plan_issues"] = [str(exc)]
            if job["status"] not in ACTIVE:
                job["status"] = "needs_input"
    return status(manifest, base)


def check_binding(manifest, job, base):
    if not job.get("generation_fingerprint") or job.get("plan_issues"):
        raise StudioError("PLAN_REQUIRED")
    binding = compile_design(manifest, job, base, repair=bool(job.get("repair_requested")))
    if binding["generation_fingerprint"] != job["generation_fingerprint"]:
        raise StudioError("INPUTS_CHANGED_RUN_PLAN")
    path = inside(base, job["prompt_file"])
    if path.read_text(encoding="utf-8") != binding["prompt"]:
        raise StudioError("BOUND_PROMPT_FILE_CHANGED")
    return binding


def status(manifest, base):
    jobs, actions = [], []
    for job in manifest["jobs"]:
        state = job["status"]
        errors = list(job.get("plan_issues", []))
        try:
            if job.get("generation_fingerprint"):
                check_binding(manifest, job, base)
            if state == "ready_to_deliver":
                verify_export(job, base)
            elif state == "main_background_pending" and job.get("main_processing_version"):
                verify_prepared(job, base)
        except (OSError, ValueError, KeyError) as exc:
            errors.append(str(exc))
        if job.get("blocked_reason") == "MAIN_PROCESSING_SETTINGS_CHANGED":
            action = "prepare-main"
        elif state == "main_background_pending":
            action = "main-background-check"
        elif state == "awaiting_result":
            action = "recover-attempt"
        elif state == "pending":
            action = "plan" if errors or not job.get("generation_fingerprint") else "reserve"
        elif state in {"needs_input", "blocked", "failed"}:
            action = "resolve_input_or_failure"
        elif errors:
            action = "resolve_integrity_error"
        else:
            action = None
        if action:
            actions.append({"job": job["id"], "action": action, "errors": errors,
                            "reason": job.get("blocked_reason"),
                            **(main_check_paths(job, base) if state == "main_background_pending" else {})})
        jobs.append({"id": job["id"], "kind": job["kind"], "status": state,
                     "attempt_id": job.get("active_attempt_id"), "errors": errors})
    active = sum(job["status"] in ACTIVE for job in manifest["jobs"])
    return {"workflow_policy": "one_pass_v1", "counts": dict(Counter(job["status"] for job in manifest["jobs"])),
            "jobs": jobs, "next_actions": actions,
            "scheduler": {"concurrency": manifest["concurrency"], "active": active,
                          "available": max(0, manifest["concurrency"] - active)}}


def reserve(manifest, base, args):
    require_auth()
    now = time.time()
    # Unknown/submitted calls retain their slot. Elapsed time never starts a duplicate call.
    for job in manifest["jobs"]:
        if job["status"] == "generating":
            attempt = active_attempt(job, job["active_attempt_id"], allow_expired=True)
            if now > attempt["expires_at"]:
                job["status"] = "awaiting_result"
    available = max(0, manifest["concurrency"] - sum(job["status"] in ACTIVE for job in manifest["jobs"]))
    limit = min(available, args.max or available)
    reservations, refusals = [], []
    for job in selected_jobs(manifest, args.job):
        if len(reservations) >= limit or job["status"] != "pending":
            continue
        if job.get("retry_after", 0) > now:
            refusals.append({"job": job["id"], "reason": "RATE_LIMITED", "retry_after_seconds": job["retry_after"] - now})
            continue
        try:
            binding = check_binding(manifest, job, base)
        except (OSError, ValueError, KeyError) as exc:
            refusals.append({"job": job["id"], "reason": str(exc)})
            continue
        repair = bool(job.get("repair_requested"))
        if repair and not job.get("repair_dispatched"):
            if job["background_repairs"] >= MAIN_BACKGROUND_REPAIR_LIMIT:
                job.update(status="blocked", blocked_reason="MAIN_BACKGROUND_REPAIR_LIMIT_REACHED")
                continue
            job["background_repairs"] += 1
            job["repair_dispatched"] = True
        identifier = uuid.uuid4().hex
        attempt = {"id": identifier, "job": job["id"], "kind": "background_repair" if repair else "generation",
                   "generation_fingerprint": job["generation_fingerprint"], "prompt_hash": job["prompt_hash"],
                   "references": copy.deepcopy(binding["references"]), "status": "reserved",
                   "reserved_at": now, "expires_at": now + ATTEMPT_TTL}
        job["generation_attempts"].append(attempt)
        job.update(status="generating", active_attempt_id=identifier)
        reservations.append({"job": job["id"], "attempt_id": identifier, "kind": attempt["kind"],
                             "prompt": binding["prompt"], "prompt_hash": binding["prompt_hash"],
                             "references": [str(inside(base, ref["path"])) for ref in binding["references"]],
                             "reference_roles": [ref["role"] for ref in binding["references"]],
                             "transparent_background": binding["transparent_background"]})
    return {"reservations": reservations, "refusals": refusals,
            "scheduler": {"concurrency": manifest["concurrency"], "available": available - len(reservations)}}


def active_attempt(job, identifier, *, allow_expired=False):
    attempt = next((item for item in job["generation_attempts"] if item["id"] == identifier), None)
    if attempt is None or attempt.get("job") != job["id"]:
        raise StudioError("ATTEMPT_NOT_FOUND_OR_WRONG_JOB")
    if job.get("active_attempt_id") != identifier or attempt["status"] not in {"reserved", "started", "unknown"}:
        raise StudioError("STALE_ATTEMPT")
    if not allow_expired and time.time() > attempt["expires_at"]:
        raise StudioError("EXPIRED_ATTEMPT: recover the existing result before ingest, do not regenerate")
    return attempt


def request_background_repair(manifest, job, base, reason):
    job.pop("main_background_check", None)
    job.pop("delivery", None)
    job.pop("main_processing", None)
    job["blocked_reason"] = reason
    if job["background_repairs"] >= MAIN_BACKGROUND_REPAIR_LIMIT:
        job["status"] = "blocked"
        return
    job["background_repair_target"] = {"path": job["raw_output"], "sha256": job["raw_sha256"]}
    job["background_repair_source_fingerprint"] = compile_design(manifest, job, base, repair=False)["generation_fingerprint"]
    job["repair_requested"] = True
    job["repair_dispatched"] = False
    job["status"] = "pending"
    bind_job(manifest, job, base)


def main_check_paths(job, base):
    result = {"path": str(inside(base, job["raw_output"])),
              "raw_path": str(inside(base, job["raw_output"]))}
    attempt = next((item for item in reversed(job["generation_attempts"])
                    if item.get("status") == "ingested" and item.get("raw_output") == job["raw_output"]
                    and item.get("raw_sha256") == job["raw_sha256"]), None)
    if attempt:
        result["attempt_id"] = attempt["id"]
    if job.get("main_processing"):
        record = job["main_processing"]
        result.update(path=str(inside(base, record["path"])), processing_id=record["processing_id"],
                      processing=record["transform"])
    return result


def prepare_main_job(manifest, job, base):
    """Shared by new-result ingest and explicit recovery, never starts a model call."""
    previous_id = job.get("main_processing", {}).get("processing_id")
    job["main_processing_version"] = PROCESSING_VERSION
    try:
        record = prepare_artifact(job, base)
    except StudioError as exc:
        if str(exc) not in BACKGROUND_ERRORS:
            raise
        request_background_repair(manifest, job, base, str(exc))
        return {"job": job["id"], "status": job["status"], "reason": str(exc)}
    job["main_processing"] = record
    if previous_id != record["processing_id"]:
        job.pop("main_background_check", None)
        job.pop("delivery", None)
    # Repeating preparation of an approved, unchanged artifact must not invalidate it.
    if job.get("main_background_check", {}).get("processing_id") != record["processing_id"]:
        job["status"] = "main_background_pending"
    job.pop("blocked_reason", None)
    job.pop("technical_failure_fingerprint", None)
    return {"job": job["id"], "status": job["status"],
            "next_action": "main-background-check" if job["status"] == "main_background_pending" else None,
            **main_check_paths(job, base)}


def prepare_main(manifest, base, args):
    require_auth()
    job = find_job(manifest, args.job)
    if job["kind"] != "main":
        raise StudioError("PREPARE_MAIN_REQUIRES_MAIN_JOB")
    if job["status"] in ACTIVE or job.get("active_attempt_id"):
        raise StudioError("PREPARE_MAIN_ATTEMPT_ACTIVE: reconcile the existing call first")
    if job["status"] == "failed":
        raise StudioError("PREPARE_MAIN_TRANSIENT_FAILURE_UNRESOLVED")
    check_binding(manifest, job, base)
    attempt = next((item for item in reversed(job["generation_attempts"])
                    if item.get("status") == "ingested" and item.get("raw_output") == job.get("raw_output")
                    and item.get("raw_sha256") == job.get("raw_sha256")), None)
    if not attempt:
        raise StudioError("PREPARE_MAIN_INGESTED_SOURCE_REQUIRED")
    if (attempt["generation_fingerprint"] != job["generation_fingerprint"] and
            not (job.get("repair_requested") and
                 job.get("background_repair_target", {}).get("sha256") == job["raw_sha256"])):
        raise StudioError("PREPARE_MAIN_STALE_SOURCE")
    result = prepare_main_job(manifest, job, base)
    result["attempt_id"] = attempt["id"]
    return result


def ingest_one(manifest, base, identifier, attempt_id, artifact):
    job = find_job(manifest, identifier)
    source = external_image(artifact)
    hashed = sha256(source)
    old = next((item for item in job["generation_attempts"] if item["id"] == attempt_id), None)
    if old and old.get("raw_sha256"):
        if old["raw_sha256"] != hashed:
            raise StudioError("ATTEMPT_RESULT_CONFLICT")
        if old.get("generation_fingerprint") != job.get("generation_fingerprint") and not (
                job.get("background_repair_target", {}).get("sha256") == hashed):
            raise StudioError("STALE_ATTEMPT")
        if sha256(inside(base, old["raw_output"])) != hashed:
            raise StudioError("RAW_FILE_CHANGED")
        return {"job": identifier, "status": job["status"], "reused": True}
    attempt = active_attempt(job, attempt_id)
    check_binding(manifest, job, base)
    if attempt["generation_fingerprint"] != job["generation_fingerprint"]:
        raise StudioError("STALE_ATTEMPT_INPUTS")
    image = open_image(source)
    with Image.open(source) as original:
        suffix = "." + {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[original.format]
    relative = f"raw/{identifier}/{attempt_id}{suffix}"
    write_bytes(inside(base, relative), source.read_bytes(), immutable=True)
    if sha256(inside(base, relative)) != hashed:
        raise StudioError("RESULT_CHANGED_DURING_COPY")
    attempt.update(status="ingested", raw_output=relative, raw_sha256=hashed, ingested_at=time.time())
    job.update(raw_output=relative, raw_sha256=hashed)
    job.pop("active_attempt_id", None)
    if job["kind"] == "main" and job.get("main_processing_version"):
        job.pop("main_processing", None)
        job.pop("main_background_check", None)
        job.pop("delivery", None)
        return {**prepare_main_job(manifest, job, base), "attempt_id": attempt_id}
    try:
        image = normalize(image, job["canvas"])
    except StudioError as exc:
        job.update(status="needs_input", blocked_reason=str(exc),
                   technical_failure_fingerprint=job["generation_fingerprint"])
        return {"job": identifier, "status": job["status"], "reason": str(exc)}
    if job["kind"] == "main":
        try:
            alpha_background(image)
        except StudioError as exc:
            request_background_repair(manifest, job, base, str(exc))
            return {"job": identifier, "status": job["status"], "reason": str(exc)}
        job["status"] = "main_background_pending"
        return {"job": identifier, "status": job["status"],
                "next_action": "main-background-check", "path": str(inside(base, relative))}
    job["delivery"] = export_job(job, base)
    job["status"] = "ready_to_deliver"
    return {"job": identifier, "status": job["status"]}


def record_failure(manifest, base, identifier, attempt_id, reason, outcome):
    job = find_job(manifest, identifier)
    attempt = active_attempt(job, attempt_id, allow_expired=True)
    if outcome == "unknown":
        attempt.update(status="unknown", error=reason)
        job.update(status="awaiting_result", blocked_reason="SUBMISSION_UNKNOWN_DO_NOT_REGENERATE")
        return {"job": identifier, "status": job["status"]}
    attempt.update(status=outcome, error=reason)
    job.pop("active_attempt_id", None)
    if outcome == "not_started":
        job["free_releases"] += 1
        if job["free_releases"] > 2:
            job["transient_failures"] += 1
    elif "429" in reason or "rate limit" in reason.lower():
        job["retry_after"] = time.time() + 30
    else:
        job["transient_failures"] += 1
    job["status"] = "failed" if job["transient_failures"] >= 3 else "pending"
    job["blocked_reason"] = reason
    return {"job": identifier, "status": job["status"]}


def ingest_batch(manifest, base, args):
    require_auth()
    operations = [("item", item) for item in args.item or []]
    operations += [("failed", item) for item in args.failed or []]
    operations += [("unknown", item) for item in args.unknown or []]
    operations += [("not_started", [*item, "Not submitted"]) for item in args.not_started or []]
    identifiers = [item[0] for _, item in operations]
    if len(identifiers) != len(set(identifiers)):
        raise StudioError("DUPLICATE_JOB_IN_BATCH")
    results, errors = [], []
    for operation, values in operations:
        before = copy.deepcopy(manifest)
        try:
            result = (ingest_one(manifest, base, *values) if operation == "item" else
                      record_failure(manifest, base, *values, operation))
            results.append(result)
        except (OSError, ValueError, KeyError) as exc:
            manifest.clear()
            manifest.update(before)
            errors.append({"job": values[0], "error": str(exc)})
    return {"results": results, "errors": errors, "next_actions": status(manifest, base)["next_actions"]}


def main_background_check(manifest, base, args):
    require_auth()
    job = find_job(manifest, args.job)
    if job["kind"] != "main" or job["status"] != "main_background_pending":
        raise StudioError("MAIN_BACKGROUND_NOT_PENDING")
    attempt = next((item for item in job["generation_attempts"] if item["id"] == args.attempt_id), None)
    if (not attempt or attempt.get("raw_sha256") != job["raw_sha256"] or
            (job.get("main_processing_version") and (attempt.get("status") != "ingested" or
                                                     attempt.get("raw_output") != job["raw_output"]))):
        raise StudioError("STALE_MAIN_BACKGROUND_CHECK")
    check_binding(manifest, job, base)
    if sha256(inside(base, job["raw_output"])) != job["raw_sha256"]:
        raise StudioError("RAW_FILE_CHANGED")
    if not args.observation.strip():
        raise StudioError("MAIN_BACKGROUND_OBSERVATION_REQUIRED")
    processing_id = None
    if job.get("main_processing_version"):
        verify_prepared(job, base)
        processing_id = job["main_processing"]["processing_id"]
        if args.processing_id != processing_id:
            raise StudioError("MAIN_PROCESSING_ID_REQUIRED_OR_STALE")
    elif args.processing_id:
        raise StudioError("UNEXPECTED_MAIN_PROCESSING_ID")
    if args.verdict == "repair":
        job.setdefault("background_history", []).append({"verdict": "repair", "raw_sha256": job["raw_sha256"],
                                                         "observation": args.observation,
                                                         **({"processing_id": processing_id} if processing_id else {})})
        request_background_repair(manifest, job, base, args.observation)
    else:
        job["main_background_check"] = {"verdict": "pass", "raw_sha256": job["raw_sha256"],
                                        "observation": args.observation,
                                        **({"processing_id": processing_id} if processing_id else {})}
        job["delivery"] = export_job(job, base)
        job["status"] = "ready_to_deliver"
    return {"job": job["id"], "status": job["status"]}


def recover_attempt(manifest, base, args):
    require_auth()
    job = find_job(manifest, args.job)
    attempt = active_attempt(job, args.attempt_id, allow_expired=True)
    check_binding(manifest, job, base)
    if not args.reason.strip():
        raise StudioError("RECOVERY_REASON_REQUIRED")
    attempt.setdefault("recoveries", []).append({"at": time.time(), "reason": args.reason})
    attempt.update(status="started", expires_at=time.time() + ATTEMPT_TTL)
    job["status"] = "generating"
    return {"job": job["id"], "attempt_id": attempt["id"], "next_action": "ingest existing result; do not call imagegen"}


def deliver(manifest, base):
    require_auth()
    images, missing = [], []
    for job in manifest["jobs"]:
        try:
            check_binding(manifest, job, base)
            path = verify_export(job, base)
            images.append({"id": job["id"], "path": str(path), "sha256": job["delivery"]["sha256"],
                           "canvas": job["canvas"]})
        except (OSError, ValueError, KeyError) as exc:
            missing.append({"id": job["id"], "required": job.get("required", True),
                            "status": job["status"], "reason": str(exc)})
    return {"workflow_policy": "one_pass_v1", "complete": not missing,
            "image_count": len(images), "expected_image_count": len(manifest["jobs"]),
            "images": images, "missing_jobs": missing}


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--json", action="store_true")
    subs = root.add_subparsers(dest="command", required=True)
    commands = {}
    for name in ("verify", "init", "configure", "add-references", "plan", "reserve", "ingest-batch",
                 "status", "deliver", "prepare-main", "main-background-check", "release", "recover-attempt", "reset-transient"):
        sub = subs.add_parser(name)
        sub.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        sub.add_argument("--workflow-policy", choices=("one_pass_v1",))
        if name not in {"verify", "init"}:
            sub.add_argument("--manifest", required=True)
        commands[name] = sub
    init = commands["init"]
    init.add_argument("--project-dir", required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--marketplace", required=True)
    init.add_argument("--language", required=True)
    init.add_argument("--listing-aspect", choices=("1:1", "1:1.3"), default="1:1")
    init.add_argument("--short-edge", type=int, default=2000)
    init.add_argument("--listing-count", type=int, default=7)
    init.add_argument("--concurrency", type=int, default=1)
    init.add_argument("--include-a-plus", action="store_true")
    init.add_argument("--a-plus-count", type=int, default=6)
    init.add_argument("--a-plus-canvas", type=int, nargs=2)
    init.add_argument("--a-plus-module")
    init.add_argument("--a-plus-modules", nargs="+")
    commands["configure"].add_argument("--input", required=True)
    refs = commands["add-references"]
    refs.add_argument("--photos", nargs="+", required=True)
    refs.add_argument("--views", nargs="+")
    refs.add_argument("--role", choices=("product", "style"), default="product")
    for name in ("plan", "reserve"):
        commands[name].add_argument("--job", action="append")
    commands["reserve"].add_argument("--max", type=int)
    for name, count in (("item", 3), ("failed", 3), ("unknown", 3), ("not-started", 2)):
        commands["ingest-batch"].add_argument("--" + name, nargs=count, action="append")
    for name in ("prepare-main", "main-background-check", "release", "recover-attempt", "reset-transient"):
        commands[name].add_argument("--job", required=True)
    for name in ("main-background-check", "release", "recover-attempt"):
        commands[name].add_argument("--attempt-id", required=True)
    main = commands["main-background-check"]
    main.add_argument("--verdict", choices=("pass", "repair"), required=True)
    main.add_argument("--observation", required=True)
    main.add_argument("--processing-id")
    for name in ("release", "recover-attempt", "reset-transient"):
        commands[name].add_argument("--reason", required=True)
    return root


def run(argv):
    args = parser().parse_args(argv)
    if args.command == "verify":
        result = verify_runtime()
    elif args.command == "init":
        result = init_project(args)
    else:
        path = Path(args.manifest).expanduser().resolve()
        base = path.parent
        if args.command in {"status", "deliver"}:
            manifest = read_json(path)
            validate_project(manifest)
            result = status(manifest, base) if args.command == "status" else deliver(manifest, base)
        else:
            with project_lock(path):
                manifest = read_json(path)
                validate_project(manifest)
                if args.command == "configure":
                    result = configure(manifest, args)
                elif args.command == "add-references":
                    result = add_references(manifest, base, args)
                elif args.command == "plan":
                    result = plan(manifest, base, args)
                elif args.command == "reserve":
                    if args.max is not None and args.max < 1:
                        raise StudioError("RESERVE_MAX_MUST_BE_POSITIVE")
                    result = reserve(manifest, base, args)
                elif args.command == "ingest-batch":
                    result = ingest_batch(manifest, base, args)
                elif args.command == "main-background-check":
                    result = main_background_check(manifest, base, args)
                elif args.command == "prepare-main":
                    result = prepare_main(manifest, base, args)
                elif args.command == "recover-attempt":
                    result = recover_attempt(manifest, base, args)
                elif args.command == "release":
                    require_auth()
                    result = record_failure(manifest, base, args.job, args.attempt_id, args.reason, "not_started")
                elif args.command == "reset-transient":
                    require_auth()
                    job = find_job(manifest, args.job)
                    if job["status"] != "failed" or not args.reason.strip():
                        raise StudioError("TRANSIENT_RESET_REQUIRES_FAILED_JOB_AND_REASON")
                    job.setdefault("retry_resets", []).append({"at": time.time(), "reason": args.reason})
                    job.update(status="pending", transient_failures=0)
                    result = {"job": job["id"], "status": job["status"]}
                else:
                    raise StudioError("UNKNOWN_COMMAND")
                write_json(path, manifest)
    ok = not bool(result.get("errors"))
    print(json.dumps({"ok": ok, **result}, ensure_ascii=False))
    return 0 if ok else 2
