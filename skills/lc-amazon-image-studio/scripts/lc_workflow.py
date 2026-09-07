"""Small transactional CLI helpers; no model calls and no automatic review verdicts."""
from __future__ import annotations

import copy
import hashlib
import io
import math
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from PIL import Image


@contextmanager
def manifest_lock(path: Path, timeout: float = 30):
    """One writer from read through commit. Lock files persist; the OS owns leases."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(handle, fcntl.LOCK_UN)
        started = time.perf_counter()
        while True:
            try:
                acquire()
                break
            except OSError:
                if time.perf_counter() - started >= timeout:
                    raise TimeoutError(f"Manifest is busy; retry after the active writer finishes: {path}")
                time.sleep(.05)
        try:
            wait_seconds = time.perf_counter() - started
            recovery_started = time.perf_counter()
            from lc_transactions import recover_pending
            recover_pending(path)
            yield {"wait_seconds": wait_seconds, "recovery_seconds": time.perf_counter() - recovery_started}
        finally:
            release()


def _job(manifest, job_id):
    import lc_image_pipeline as p
    job = p.find_by_id(manifest["jobs"], job_id)
    if job is None:
        raise p.PipelineError(f"Unknown job: {job_id}")
    return job


def _attempt(job, attempt_id):
    import lc_image_pipeline as p
    if not attempt_id or job.get("active_attempt_id") != attempt_id:
        raise p.PipelineError("STALE_ATTEMPT: result does not belong to the active attempt")
    attempt = next((a for a in job.get("generation_attempts", []) if isinstance(a, dict) and a.get("id") == attempt_id), None)
    if attempt is None:
        raise p.PipelineError("UNKNOWN_ATTEMPT: start generation with transition first")
    return attempt


def attempt_event(manifest, job_id, attempt_id, event, timestamp=None):
    """Record actual tool-boundary events; filesystem times are never substituted."""
    import lc_image_pipeline as p
    job = _job(manifest, job_id)
    attempt = _attempt(job, attempt_id)
    if event == "tool_started" and p.required_design_unresolved(job):
        raise p.PipelineError("Required design reference is missing or changed; tool events cannot authorize stale design work")
    if event not in {"tool_started", "tool_returned"}:
        raise p.PipelineError("Only tool_started and tool_returned events are supported")
    when = time.time() if timestamp is None else timestamp
    if isinstance(when, bool) or not isinstance(when, (float, int)) or not math.isfinite(when):
        raise p.PipelineError("Event timestamp must be a finite Unix timestamp")
    key = event + "_at"
    if key in attempt:
        if timestamp is None or attempt[key] == when:
            return copy.deepcopy(attempt)
        raise p.PipelineError("An existing tool event cannot be rewritten")
    if when < attempt["dispatched_at"] or when > time.time():
        raise p.PipelineError("Event timestamp is outside the dispatched attempt")
    if event == "tool_started" and "tool_returned_at" in attempt:
        raise p.PipelineError("tool_started must be recorded before tool_returned")
    if event == "tool_returned" and ("tool_started_at" not in attempt or when < attempt["tool_started_at"]):
        raise p.PipelineError("tool_returned requires a prior tool_started event")
    if attempt.get("ingested_at") is not None and when > attempt["ingested_at"]:
        raise p.PipelineError("Tool events cannot occur after ingestion")
    attempt[key] = when
    return copy.deepcopy(attempt)


def _atomic_bytes(path: Path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def ingest(manifest, base: Path, job_id, artifact: Path, attempt_id):
    import lc_image_pipeline as p
    started = time.monotonic()
    job = _job(manifest, job_id)
    attempt = _attempt(job, attempt_id)
    current = p.generation_fingerprint(manifest, job, base)
    bound = p.attempt_generation_binding(job, attempt)
    if current != bound or job.get("attempt_prompt_hash") not in {attempt.get("prompt_hash"), bound}:
        raise p.PipelineError("STALE_PROMPT: generated artifact belongs to old inputs")
    artifact = Path(artifact).expanduser().resolve()
    if not artifact.is_file():
        raise p.PipelineError(f"Generated artifact is missing: {artifact}")
    payload = artifact.read_bytes()
    artifact_hash = hashlib.sha256(payload).hexdigest()
    with Image.open(io.BytesIO(payload)) as image:
        image.verify()
    if attempt.get("status") == "ingested":
        raw = p.resolve_project_path(job.get("raw_output"), base, "raw_output")
        if (attempt.get("artifact_sha256") != artifact_hash or raw is None or not raw.is_file()
                or p.sha256_file(raw) != artifact_hash or job.get("bound_raw_sha256") != artifact_hash):
            raise p.PipelineError("INGEST_CONFLICT: attempt already has a different or modified artifact")
        return {"job": job_id, "attempt_id": attempt_id, "idempotent": True,
                "status": job["status"], "dispatch": p.execution_plan(manifest)["dispatch"]}
    if job.get("status") != "generating":
        raise p.PipelineError("Only a generating attempt can ingest a new artifact")
    raw = p.resolve_project_path(job.get("raw_output"), base, "raw_output")
    if raw is None:
        raise p.PipelineError("raw_output is required")
    # Keep earlier outputs recoverable. Repairs get an immutable attempt path.
    if raw.is_file() and p.sha256_file(raw) != artifact_hash:
        raw = base / "raw" / "attempts" / f"{job_id}-{attempt_id}{raw.suffix.lower()}"
        if raw.is_file() and p.sha256_file(raw) != artifact_hash:
            raise p.PipelineError("INGEST_CONFLICT: immutable attempt artifact already exists")
    if not raw.is_file():
        _atomic_bytes(raw, payload)
    job["raw_output"] = p.relpath(raw, base)
    p.transition_job(manifest, job_id, "generated", "Ingested the current model artifact", base)
    now = time.time()
    attempt.update(status="ingested", artifact_sha256=artifact_hash,
                   artifact_path=str(artifact), retained_artifact_path=p.relpath(raw, base), ingested_at=now)
    p.record_timing(job, "ingest", started)
    if "tool_started_at" in attempt and "tool_returned_at" in attempt:
        job.setdefault("timings", []).extend([
            {"stage": "tool", "seconds": round(attempt["tool_returned_at"]-attempt["tool_started_at"], 4),
             "cached": False, "attempt_id": attempt_id, "measurement": "explicit_tool_events"},
            {"stage": "handoff", "seconds": round(now-attempt["tool_returned_at"], 4),
             "cached": False, "attempt_id": attempt_id, "measurement": "tool_returned_to_ingested"}])
    else:
        attempt["tool_duration_unavailable"] = True
    return {"job": job_id, "attempt_id": attempt_id, "idempotent": False, "status": "generated",
            "raw_output": job["raw_output"], "dispatch": p.execution_plan(manifest)["dispatch"]}


def annotation_fingerprint(job):
    import lc_image_pipeline as p
    return p.digest({"image": job.get("image_sha256"), "raw_product": job.get("raw_product_bbox_norm"),
                     "product": job.get("output_product_bbox_norm"),
                     "details": job.get("detail_output_bbox_norms", {})})


def review_context(manifest, job, base):
    import lc_image_pipeline as p
    from lc_quality import assessment_context_fingerprint
    from lc_dependencies import evidence_dependencies, scoped_review_dependencies
    fps = p.current_fingerprints(manifest, job, base)
    artifacts = {name: p.sha256_file(path) if path.is_file() else None
                 for name, path in {"raw": p.resolve_path(job["raw_output"], base),
                                    "image": base / "review" / "image_layers" / f"{job['id']}.png",
                                    "mobile": base / "review" / "layouts" / f"{job['id']}-360.png",
                                    "layout": base / "review" / "layouts" / f"{job['id']}.png"}.items()}
    details = (p.critical_detail_dependencies(manifest, job) if job.get("generation_dependency_version", 1) == 2
               else manifest.get("critical_details", []))
    result = {"generation": fps["generation"], "layout": fps["layout"], "artifacts": artifacts,
            "image_sha256": job.get("image_sha256"), "visual": job.get("disclosure_visual_fingerprint"),
            "annotations": annotation_fingerprint(job), "source_context": assessment_context_fingerprint(manifest, job),
            "mobile_preview_binding": job.get("mobile_preview_binding"),
            "style_reference_selection": p.style_selection_hash(manifest, job, base),
            "evidence": p.digest({"references": manifest["references"], "facts": manifest.get("facts", []),
                                  "assessment": job.get("source_assessment", {}), "details": details}),
            "rules": {name: p.sha256_file(p.SCRIPT_DIR / name) for name in
                      ("lc_image_pipeline.py", "lc_workflow.py", "lc_assets.py", "lc_quality.py")}}
    if p.resolve_text_mode(job) == "model_native":
        result["model_copy"] = p.copy_blocks(job)
        result["design_rules"] = p.sha256_file(p.SCRIPT_DIR / "lc_design.py")
    if p.has_panel_sources(job):
        result["panel_contracts"] = p.panel_contracts(manifest, job, base)
        result["design_rules"] = p.sha256_file(p.SCRIPT_DIR / "lc_design.py")
    if "design_resolution" in job:
        result["design_resolution"] = job["design_resolution"]
        result["reference_issue"] = p.design_reference_issue(job)
    from lc_typography import enabled, proof_paths
    if enabled(job):
        result["typography_proofs"] = {name: p.sha256_file(path) if path.is_file() else None
                                       for name, path in proof_paths(base, job["id"]).items()}
        from lc_dependencies import title_effect_dependencies
        result["title_effect"] = title_effect_dependencies(job, base, phase="review")
    if scoped_review_dependencies(manifest, job):
        result["evidence"] = p.digest({"dependencies": evidence_dependencies(manifest, job, base),
                                       "assessment": job.get("source_assessment", {})})
        result["dependency_rules"] = p.sha256_file(p.SCRIPT_DIR / "lc_dependencies.py")
    return result


SEMANTIC = ("geometry", "material", "components", "scene_scale", "clarity", "visual_integrity")
POLICY = ("main_product_only", "claims", "competitor_copy", "text_readability", "mobile_readability")


def policy_keys(job):
    import lc_image_pipeline as p
    return POLICY + (("visual_design",) if p.requires_visual_design(job) else ())


ANNOTATIONS = {"raw_product_bbox_norm", "detail_output_bbox_norms"}


def normalize_annotations(manifest, selected, annotations, *, single_job=None):
    """Accept a project-wide job map; retain old flat input for single callers."""
    import lc_image_pipeline as p
    if annotations is None:
        return {}
    if not isinstance(annotations, dict):
        raise p.PipelineError("Annotations must be an object keyed by job id")
    if single_job and annotations and set(annotations).issubset(ANNOTATIONS):
        return {single_job: annotations}
    known = {job["id"] for job in manifest["jobs"]}
    unknown = set(annotations) - known
    if unknown:
        raise p.PipelineError("Unknown annotation job ids: " + ", ".join(sorted(unknown)))
    return {key: value for key, value in annotations.items() if key in selected}


def review_candidate(job):
    """Ready local source composites do not need a separate compose command."""
    import lc_image_pipeline as p
    return p.is_review_ready(job) or (job.get("render_mode") == "pixel_composite"
            and job.get("status") == "pending" and not p.is_hold(job))


@contextmanager
def _job_artifact_guard(manifest, base, job_id):
    """A caught batch failure must not publish that job's partial raster writes."""
    import lc_image_pipeline as p
    from lc_transactions import _artifact_owner, _clone
    base = Path(base).resolve()
    job = _job(manifest, job_id)
    exact = {p.resolve_project_path(job.get(key), base, key) for key in ("raw_output", "final_output")}
    exact.update(base / name for name in ("qa_report.json", "execution_plan.json"))

    def owned():
        result = {path for path in exact if path is not None and path.is_file()}
        for folder in ("review/layouts", "review/image_layers", "review/packets", "review/details",
                       "review/submissions", "prompts", "repairs", "title_effects"):
            directory = base / folder
            if directory.is_dir():
                for path in directory.rglob("*"):
                    if path.is_file() and (_artifact_owner(str(path.relative_to(base)), manifest) == job_id
                            or (folder == "review/submissions" and path.name.startswith(job_id + "-"))):
                        result.add(path)
        return result

    before = owned()
    with tempfile.TemporaryDirectory(prefix=".lc-review-backup-", dir=base) as directory:
        backup = Path(directory)
        metrics = {"cloned_files": 0, "copied_bytes": 0}
        for path in before:
            _clone(path, backup / path.relative_to(base), metrics)
        try:
            yield
        except BaseException:
            for path in owned() - before:
                path.unlink()
            for path in before:
                os.replace(backup / path.relative_to(base), path)
            raise


def product_review_context(manifest, job, base):
    """Exact unchanged visual/evidence context, excluding marketing typography."""
    import lc_image_pipeline as p
    from lc_dependencies import evidence_dependencies
    evidence = evidence_dependencies(manifest, job, base)
    image = base / "review" / "image_layers" / f"{job['id']}.png"
    raw = p.resolve_path(job.get("raw_output"), base)
    return {"generation": p.generation_fingerprint(manifest, job, base),
            "raw": p.sha256_file(raw) if raw and raw.is_file() else None,
            "image": p.sha256_file(image) if image.is_file() else None,
            "annotations": annotation_fingerprint(job), "evidence": evidence,
            "panels": p.panel_contracts(manifest, job, base) if p.has_panel_sources(job) else [],
            "rules": {name: p.sha256_file(p.SCRIPT_DIR / name) for name in
                      ("lc_workflow.py", "lc_dependencies.py", "lc_image_pipeline.py", "lc_quality.py", "lc_assets.py")}}


def _reusable_product_reviews(manifest, job, base, comparisons):
    """Only reuse observations from an intact, successful real submission."""
    import lc_image_pipeline as p
    from lc_dependencies import scoped_review_dependencies
    proof = job.get("product_review_proof") or {}
    if not scoped_review_dependencies(manifest, job) or not proof.get("path"):
        return {}, None
    path = p.resolve_project_path(proof["path"], base, "product review proof")
    if not path or not path.is_file() or p.sha256_file(path) != proof.get("sha256"):
        return {}, None
    record = p.read_json(path)
    if (record.get("job") != job["id"] or record.get("status") != "qa_passed"
            or record.get("product_context") != product_review_context(manifest, job, base)):
        return {}, None
    semantic = record.get("reviews", {}).get("semantic_qa_results", {})
    # Text or graphics may cover an unchanged product; visual_integrity and all
    # policy/layout verdicts always require inspection of the new final layout.
    reusable = {"semantic_qa_results": {key: copy.deepcopy(semantic[key]) for key in SEMANTIC
                if key != "visual_integrity" and isinstance(semantic.get(key), dict)
                and semantic[key].get("verdict") == "pass"}, "detail_qa_results": {}}
    prior_comparisons = {item["id"]: item["sha256"] for item in record.get("comparisons", [])}
    details = record.get("reviews", {}).get("detail_qa_results", {})
    for item in comparisons:
        value = details.get(item["id"])
        if prior_comparisons.get(item["id"]) == item["sha256"] and isinstance(value, dict) and value.get("verdict") == "pass":
            reusable["detail_qa_results"][item["id"]] = copy.deepcopy(value)
    return reusable, copy.deepcopy(proof)


def review_prepare(manifest, base: Path, job_id, annotations=None, *, force=False):
    from lc_stage_timing import record_stage
    started = time.perf_counter()
    annotations = normalize_annotations(manifest, {job_id}, annotations, single_job=job_id)
    result = _review_prepare_impl(manifest, base, job_id, annotations.get(job_id), force=force)
    record_stage(_job(manifest, job_id), "review_prepare", started=started, cached=result.get("cached", False),
        measurement="local_review_package_preparation_or_cache_validation",
        includes=["planning", "reference_compile", "image_prepare", "layout"])
    return result


def _review_prepare_impl(manifest, base: Path, job_id, annotations=None, *, force=False):
    import lc_image_pipeline as p
    job = _job(manifest, job_id)
    annotations = annotations or {}
    if not isinstance(annotations, dict) or set(annotations) - ANNOTATIONS:
        raise p.PipelineError("Annotations accept raw_product_bbox_norm and detail_output_bbox_norms only")
    errors = []
    if "raw_product_bbox_norm" in annotations:
        p.validate_bbox(annotations["raw_product_bbox_norm"], "raw_product_bbox_norm", errors)
    boxes = annotations.get("detail_output_bbox_norms", job.get("detail_output_bbox_norms", {}))
    if not isinstance(boxes, dict):
        errors.append("detail_output_bbox_norms must be an object")
    else:
        known = {d["id"] for d in manifest.get("critical_details", [])}
        for key, box in boxes.items():
            if key not in known:
                errors.append(f"Unknown detail: {key}")
            p.validate_bbox(box, key, errors)
    if errors:
        raise p.PipelineError("; ".join(errors))
    # Reuse an unsigned package only when every bound input and annotation is
    # unchanged. Missing/tampered previews fall through and are reconstructed.
    candidate = copy.deepcopy(job)
    candidate.update(annotations)
    request = job.get("review_request", {})
    output = base / "review" / "packets" / f"{job_id}.json"
    if not force and not request.get("submitted_hash") and output.is_file():
        context = review_context(manifest, candidate, base)
        saved = p.read_json(output)
        comparisons_ok = all((base / item["path"]).is_file() and p.sha256_file(base / item["path"]) == item["sha256"]
                             for item in request.get("comparisons", []))
        if (saved.get("review_id") == request.get("id") and p.digest(context) == request.get("context_hash")
                and p.digest(saved.get("context")) == request.get("context_hash") and comparisons_ok
                and (candidate.get("output_product_bbox_norm") or not candidate.get("raw_product_bbox_norm"))):
            return {"job": job_id, "status": "review_pending", "packet": str(output),
                    "missing_annotations": saved.get("missing_annotations", []), "cached": True}
    boxes = copy.deepcopy(boxes)
    if "raw_product_bbox_norm" in annotations:
        job["raw_product_bbox_norm"] = annotations["raw_product_bbox_norm"]
    p.prepare(manifest, base, [job_id])
    p.aspect_safe_postprocess(manifest, base, job_ids=[job_id], export=False)
    if job.get("status") != "review_pending" or not job.get("layout_result", {}).get("passed"):
        raise p.PipelineError(f"Cannot prepare review while {job_id} is {job.get('status')}")
    job["detail_output_bbox_norms"] = boxes
    new_annotations = annotation_fingerprint(job)
    if job.get("detail_review_context") != new_annotations:
        job["detail_qa_results"] = {}
    job["detail_review_context"] = new_annotations
    required = [d for d in manifest.get("critical_details", []) if d.get("visibility", {}).get(job_id) == "required"]
    comparisons, missing = [], []
    layout = base / "review" / "layouts" / f"{job_id}.png"
    # A cached layout must never leave a missing or altered mobile review image.
    # Re-derive this lightweight thumbnail from the bound layout, not from raw.
    preview = layout.with_name(f"{job_id}-360.png")
    with Image.open(layout) as image:
        thumbnail = image.convert("RGB")
        thumbnail.thumbnail((360, 10000), Image.Resampling.LANCZOS)
        payload = io.BytesIO()
        thumbnail.save(payload, format="PNG")
    preview_bytes = payload.getvalue()
    preview_hash = hashlib.sha256(preview_bytes).hexdigest()
    if not preview.is_file() or p.sha256_file(preview) != preview_hash:
        _atomic_bytes(preview, preview_bytes)
    job["mobile_preview_binding"] = {"sha256": preview_hash, "layout_sha256": p.sha256_file(layout)}
    if not job.get("output_product_bbox_norm"):
        missing.append("raw_product_bbox_norm")
    with Image.open(layout) as image:
        for detail in required:
            location, crop = p.evidence_for_job(detail, job)
            override = boxes.get(detail["id"])
            if (job.get("new_view") and override is None) or not location or not crop:
                if detail["priority"] in {"P0", "P1"}:
                    missing.append(f"detail_output_bbox_norms.{detail['id']}" if location and crop else f"evidence.{detail['id']}")
                continue
            if not override and not job.get("output_product_bbox_norm"):
                continue
            output_crop = p.crop_output_detail(image.convert("RGB"), job.get("output_product_bbox_norm") or [0, 0, 1, 1],
                                              location["bbox_in_product_norm"], override)
            path = base / "review" / "details" / job_id / f"{detail['id']}.png"
            with Image.open(p.resolve_path(crop["path"], base)) as reference:
                p.make_comparison(reference.convert("RGB"), output_crop, path)
            comparisons.append({"id": detail["id"], "path": p.relpath(path, base), "sha256": p.sha256_file(path)})
    context = review_context(manifest, job, base)
    requested = time.time()
    review_id = uuid.uuid4().hex
    def blank(keys):
        return {key: {"verdict": None, "notes": ""} for key in keys}
    packet = {"schema_version": 1, "job": job_id, "review_id": review_id, "context": context,
              "missing_annotations": missing, "preview": p.relpath(layout, base),
              "mobile_preview": p.relpath(preview, base), "comparisons": comparisons,
              "reviews": {"semantic_qa_results": blank(SEMANTIC), "policy_qa_results": blank(policy_keys(job)),
                          "detail_qa_results": blank(d["id"] for d in required if d["priority"] in {"P0", "P1"}),
                          "ai_disclosure": {"human_source": "unknown", "notes": ""}}}
    reused, proof = _reusable_product_reviews(manifest, job, base, comparisons)
    if proof:
        for field, values in reused.items():
            packet["reviews"][field].update(values)
        packet["reused_reviews"] = {"proof": proof, "fields": {field: list(values) for field, values in reused.items()}}
        packet["reuse_guidance"] = ("Prefilled observations come from the bound, unchanged product evidence. "
                                    "Inspect visual_integrity and every policy judgment again, including text/graphic occlusion. "
                                    "A changed detail crop is not reused. This packet remains unsigned.")
    if "visual_design" in policy_keys(job):
        packet["visual_design_guidance"] = "Review hierarchy, spacing/background treatment, image-text relationship and alignment with the supplied visual samples. Record all four in notes; geometry checks are not visual approval."
    if job.get("title_effect_state", {}).get("applied"):
        applied = job["title_effect_state"]["applied"]
        packet["reviews"]["title_effect_review"] = {
            "binding": applied["binding"], "verdict": None, "transcription": "", "unexpected_text": None,
            "bbox_norm": None, "observed_surface": "", "notes": "",
            **{key: None for key in ("readable_original", "readable_360", "carrier_surface_visible",
                                    "material_perspective_pass", "lighting_contact_pass", "product_unchanged",
                                    "other_text_unchanged", "decorative_only")}}
        packet["title_effect_guidance"] = "Transcribe the actual edited headline; inspect material, perspective, lighting and original/360px readability. Check the bound mask, product and other copy. Do not copy intended text as an observation."
    elif job.get("layout_result", {}).get("title_effect", {}).get("fallback_reason"):
        packet["title_effect_fallback"] = job["layout_result"]["title_effect"]["fallback_reason"]
    if p.resolve_text_mode(job) == "model_native":
        packet["approved_copy"] = p.copy_blocks(job)
        packet["reviews"]["model_text_review"] = {"verdict": None, "notes": "", "blocks": [], "unexpected_text": None}
        packet["model_text_guidance"] = ("Visually transcribe each actual marketing text block from the bound full-size image, "
                                        "including its id, text and bbox_norm [x,y,w,h]. Do not copy the intended text as an observation. "
                                        "Inventory unexpected marketing text/badges in unexpected_text (empty only after inspection). "
                                        "Compare exact spelling and punctuation; line wrapping may differ. Inspect the 360px preview separately.")
        if (job.get("embedding_decision") or {}).get("kind") == "surface_embedded_3d":
            packet["reviews"]["model_text_review"]["embedding"] = {
                "carrier_surface_visible": None, "material_perspective_pass": None,
                "lighting_contact_pass": None, "readable_original": None, "readable_360": None,
                "product_label_unchanged": None, "observed_surface": "", "notes": ""}
            packet["embedding_guidance"] = (
                "Confirm the intended carrier surface is visibly present and that the lettering has credible "
                "material, perspective, lighting and contact. Confirm it remains readable at original size and 360px, "
                "does not alter a product label, and does not add any unapproved text. Record actual observations; "
                "a failed embedded-text check can receive only the existing single controlled model repair.")
    if p.has_panel_sources(job):
        packet["panels"] = p.panel_contracts(manifest, job, base)
        packet["reviews"]["panel_reviews"] = {item["id"]: blank(("provenance", "product_identity", "crop")) for item in packet["panels"]}
        packet["panel_guidance"] = ("Inspect each bound source image and its actual crop in the layout. Record per-panel provenance, "
                                    "product identity and crop verdicts with specific observations. Generated images are not real source photos; "
                                    "confirm their linked original-photo evidence. A fact ID or valid file hash alone is not visual approval.")
    job["review_request"] = {"id": review_id, "context_hash": p.digest(context), "prepared_at": requested,
                             "comparisons": comparisons, "missing_annotations": missing}
    output = base / "review" / "packets" / f"{job_id}.json"
    p.write_json(output, packet)
    job["review_request"]["ready_at"] = time.time()
    return {"job": job_id, "status": "review_pending", "packet": str(output), "missing_annotations": missing}


def review_prepare_many(manifest, base: Path, job_ids=None, annotations=None, *, force=False):
    """Prepare ready jobs independently; review never occupies generation slots."""
    import lc_image_pipeline as p
    selected = p.job_selection(manifest, job_ids)
    annotations = normalize_annotations(manifest, selected, annotations)
    results, skipped, errors = [], [], []
    for job in manifest["jobs"]:
        if job["id"] not in selected:
            continue
        if not review_candidate(job):
            skipped.append({"job": job["id"], "status": job.get("status"), "reason": "not_ready_or_hold"})
            continue
        candidate = copy.deepcopy(manifest)
        try:
            with _job_artifact_guard(manifest, base, job["id"]):
                result = review_prepare(candidate, base, job["id"], annotations.get(job["id"]), force=force)
        except (p.PipelineError, ValueError, OSError) as exc:
            errors.append({"job": job["id"], "error": str(exc)})
            continue
        manifest.clear()
        manifest.update(candidate)
        results.append(result)
    return {"packets": results, "skipped": skipped, "errors": errors}


def review_submit(manifest, base: Path, packet):
    from lc_stage_timing import record_stage
    started, submit_started_at = time.perf_counter(), time.time()
    result = _review_submit_impl(manifest, base, packet)
    job = _job(manifest, result["job"])
    if not result.get("idempotent"):
        request = job["review_request"]
        ready = request.get("ready_at", request["prepared_at"])
        record_stage(job, "review_wait", seconds=submit_started_at-ready,
            measurement="packet_ready_to_submit_start" if "ready_at" in request else "legacy_prepared_to_submit_start",
            ready_at=ready, submit_started_at=submit_started_at,
            human_active_review_seconds=None, human_active_review_measurement="unavailable_mixed_with_waiting")
    record_stage(job, "review_submit", started=started, cached=result.get("idempotent", False),
        measurement="local_submit_validation_export_and_qa", includes=["export", "qa"],
        submit_started_at=submit_started_at)
    return result


def review_packet_map(manifest, packets, job_ids=None):
    """Normalize single, list or job-keyed packets before any batch mutation."""
    import lc_image_pipeline as p
    selected = p.job_selection(manifest, job_ids)
    if isinstance(packets, dict) and packets.get("schema_version") == 1 and "job" in packets:
        packets = {packets.get("job"): packets}
    elif isinstance(packets, list):
        mapped = {}
        for packet in packets:
            identifier = packet.get("job") if isinstance(packet, dict) else None
            if not isinstance(identifier, str) or identifier in mapped:
                raise p.PipelineError("Review packets require distinct job ids")
            mapped[identifier] = packet
        packets = mapped
    if not isinstance(packets, dict):
        raise p.PipelineError("Review packets must be a packet, list or object keyed by job id")
    known = {job["id"] for job in manifest["jobs"]}
    if set(packets) - known:
        raise p.PipelineError("Unknown review job ids: " + ", ".join(sorted(set(packets) - known)))
    for identifier, packet in packets.items():
        if not isinstance(packet, dict) or packet.get("job") != identifier:
            raise p.PipelineError(f"Review packet job does not match map key: {identifier}")
    return {key: value for key, value in packets.items() if key in selected}


def review_submit_many(manifest, base: Path, packets, job_ids=None):
    """Finish each valid review independently; report failures without rollback."""
    import lc_image_pipeline as p
    results, errors = [], []
    for job_id, packet in review_packet_map(manifest, packets, job_ids).items():
        candidate = copy.deepcopy(manifest)
        try:
            with _job_artifact_guard(manifest, base, job_id):
                result = review_submit(candidate, base, packet)
        except (p.PipelineError, ValueError, OSError) as exc:
            errors.append({"job": job_id, "error": str(exc)})
            continue
        manifest.clear()
        manifest.update(candidate)
        results.append(result)
    return {"results": results, "errors": errors}


def _review_submit_impl(manifest, base: Path, packet):
    import lc_image_pipeline as p
    if not isinstance(packet, dict) or packet.get("schema_version") != 1:
        raise p.PipelineError("Unsupported review packet")
    job = _job(manifest, packet.get("job"))
    request = job.get("review_request", {})
    context = review_context(manifest, job, base)
    if (packet.get("review_id") != request.get("id") or p.digest(packet.get("context")) != request.get("context_hash")
            or p.digest(context) != request.get("context_hash")):
        raise p.PipelineError("STALE_REVIEW_PACKET: inputs, layout, coordinates or rules changed; prepare a fresh review")
    if request.get("missing_annotations"):
        raise p.PipelineError("Review coordinates/evidence are incomplete; run review-prepare with annotations")
    for item in request.get("comparisons", []):
        path = p.resolve_project_path(item["path"], base, "review comparison")
        if not path.is_file() or p.sha256_file(path) != item["sha256"]:
            raise p.PipelineError("STALE_REVIEW_PACKET: comparison artifact changed")
    reviews = packet.get("reviews")
    expected_review_fields = {"semantic_qa_results", "policy_qa_results", "detail_qa_results", "ai_disclosure"}
    if p.resolve_text_mode(job) == "model_native":
        expected_review_fields.add("model_text_review")
    if p.has_panel_sources(job):
        expected_review_fields.add("panel_reviews")
    if job.get("title_effect_state", {}).get("applied"):
        expected_review_fields.add("title_effect_review")
    if not isinstance(reviews, dict) or set(reviews) != expected_review_fields:
        raise p.PipelineError("Review packet requires semantic, policy, detail and AI-source judgments")
    policies = reviews.get("policy_qa_results")
    if (p.design_reference_issue(job) and isinstance(policies, dict)
            and p.unpack_verdict(policies.get("visual_design")) == "pass"):
        raise p.PipelineError("Design reference needs_input: cannot approve visual_design until its reference is resolved")
    required_details = {d["id"] for d in manifest.get("critical_details", [])
                        if d.get("visibility", {}).get(job["id"]) == "required" and d["priority"] in {"P0", "P1"}}
    for field, keys in (("semantic_qa_results", SEMANTIC), ("policy_qa_results", policy_keys(job)), ("detail_qa_results", required_details)):
        values = reviews[field]
        if not isinstance(values, dict) or not set(keys).issubset(values):
            raise p.PipelineError(f"Incomplete real review: {field}")
        for key, result in values.items():
            if (not isinstance(result, dict) or result.get("verdict") not in p.VALID_QA_VERDICT
                    or not isinstance(result.get("notes"), str) or not result["notes"].strip()):
                raise p.PipelineError(f"Explicit verdict and notes required: {field}.{key}")
    ai = reviews["ai_disclosure"]
    if (not isinstance(ai, dict) or ai.get("human_source") not in {"none", "real", "synthetic", "non_photorealistic"}
            or not isinstance(ai.get("notes"), str) or not ai["notes"].strip()):
        raise p.PipelineError("Explicit human-source judgment and notes are required")
    if p.resolve_text_mode(job) == "model_native":
        text_review = reviews["model_text_review"]
        issues = p.native_text_review_issues(job, text_review)
        content_errors = {"MODEL_TEXT_COPY_MISMATCH", "MODEL_TEXT_UNEXPECTED_TEXT", "MODEL_TEXT_REVIEW_FAILED",
                          "SURFACE_EMBEDDING_REVIEW_FAILED"}
        if set(issues) - content_errors or (issues and text_review.get("verdict") == "pass"):
            raise p.PipelineError("Explicit actual model-text review required: " + "; ".join(issues))
    if p.has_panel_sources(job):
        issues = p.panel_review_issues(p.panel_contracts(manifest, job, base), reviews["panel_reviews"])
        invalid = [issue for issue in issues if not issue.endswith(":PANEL_REVIEW_FAILED")]
        if invalid:
            raise p.PipelineError("Explicit bound panel reviews required: " + "; ".join(invalid))
    if "title_effect_review" in expected_review_fields:
        from lc_title_effects import review_issues
        issues = review_issues(job, reviews["title_effect_review"])
        if issues:
            raise p.PipelineError("Explicit actual local-title review required: " + "; ".join(issues))
    # Validate against a candidate first: stale/incomplete submissions never alter state.
    candidate = copy.deepcopy(manifest)
    target = _job(candidate, job["id"])
    for key, value in reviews.items():
        target[key] = copy.deepcopy(value)
    if "title_effect_review" in expected_review_fields:
        from lc_title_effects import submit_review as submit_effect_review
        submit_effect_review(candidate, base, target, reviews["title_effect_review"])
    target["ai_disclosure"].update(reviewed_image_sha256=context["image_sha256"],
                                    reviewed_visual_fingerprint=context["visual"])
    target["detail_review_context"] = context["annotations"]
    if "visual_design" in policy_keys(target):
        target["visual_design_review_context"] = p.visual_design_context(candidate, target, base)
        target.pop("visual_design_review_invalidated_reason", None)
    if p.resolve_text_mode(target) == "model_native":
        target["model_text_review_context"] = p.native_text_context(candidate, target, base)
    if p.has_panel_sources(target):
        target["panel_review_context"] = p.panel_review_context(candidate, target, base)
    errors = p.validate_manifest(candidate, base, check_files=True)
    if errors:
        raise p.PipelineError("Invalid review submission: " + "; ".join(errors))
    submission_hash = p.digest(reviews)
    if request.get("submitted_hash"):
        if request["submitted_hash"] == submission_hash:
            final = p.resolve_project_path(job.get("final_output"), base, "final_output")
            report_path = base / "qa_report.json"
            report = p.read_json(report_path) if report_path.is_file() else {}
            current_result = next((r for r in report.get("jobs", []) if r.get("id") == job["id"]), {})
            if (final is None or not final.is_file() or p.sha256_file(final) != request.get("submitted_final_sha256")
                    or p.digest(current_result) != request.get("submitted_qa_report_fingerprint")
                    or p.qa_fingerprint(manifest, job, base) != request.get("submitted_qa_context")
                    or job.get("status") != request.get("submitted_status")
                    or job.get("final_sha256") != request.get("submitted_final_sha256")):
                raise p.PipelineError("STALE_SUBMITTED_REVIEW: final output, QA report or outcome changed")
            return {"job": job["id"], "status": job["status"], "idempotent": True}
        raise p.PipelineError("Review already submitted; prepare a fresh packet to change its verdicts")
    # Metadata changes do not invalidate the explicit policy judgments in this packet.
    target["fingerprints"] = p.current_fingerprints(candidate, target, base)
    p.aspect_safe_postprocess(candidate, base, job_ids=[job["id"]])
    p.quality_assurance(candidate, base, [job["id"]], update_overviews=False)
    submitted = time.time()
    target["review_request"].update(submitted_at=submitted, submitted_hash=submission_hash,
                                     submitted_final_sha256=target.get("final_sha256"),
                                     submitted_qa_report_fingerprint=target.get("qa_report_fingerprint"),
                                     submitted_qa_context=p.qa_fingerprint(candidate, target, base),
                                     submitted_status=target["status"])
    target.setdefault("timings", []).append({"stage": "review", "seconds": round(submitted-request["prepared_at"], 4),
                                              "cached": False, "measurement": "review_prepared_to_submitted"})
    from lc_dependencies import scoped_review_dependencies
    if scoped_review_dependencies(candidate, target) and target["status"] == "qa_passed":
        proof_path = base / "review" / "submissions" / f"{job['id']}-{packet['review_id']}.json"
        proof_record = {"schema_version": 1, "job": target["id"], "review_id": packet["review_id"],
                        "status": target["status"], "submitted_at": submitted,
                        "product_context": product_review_context(candidate, target, base),
                        "comparisons": request.get("comparisons", []), "reviews": copy.deepcopy(reviews),
                        "submission_hash": submission_hash, "context": copy.deepcopy(packet["context"])}
        if proof_path.exists():
            raise p.PipelineError("Product review proof already exists; historical submissions are immutable")
        p.write_json(proof_path, proof_record)
        target["product_review_proof"] = {"path": p.relpath(proof_path, base), "sha256": p.sha256_file(proof_path)}
    manifest.clear()
    manifest.update(candidate)
    return {"job": target["id"], "status": target["status"], "idempotent": False,
            "dispatch": p.execution_plan(manifest)["dispatch"]}
