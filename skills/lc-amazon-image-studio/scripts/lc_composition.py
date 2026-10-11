"""Opt-in layout-first composition and explicit visual review, without model calls.

Legacy prompts, renderers and review-rule source hashes stay unchanged. The CLI
and prepare API install guarded wrappers around the frozen visual workers.
"""
from __future__ import annotations

import copy
import functools
import math
import time
import uuid
from pathlib import Path

BASE_CHECKS = ("text_space", "subject_scale", "subject_complete", "natural_space")
FINAL_CHECKS = ("text_relationship", "subject_scale", "composition_integrity", "series_consistency")
POLICY = {"version": 1, "mode": "layout_first"}


def enabled(manifest):
    return manifest.get("composition_policy") == POLICY


def applies(manifest, job):
    from lc_design import has_marketing_text, resolve_text_mode
    return (enabled(manifest) and job.get("kind") != "main"
            and resolve_text_mode(job) == "local_overlay" and has_marketing_text(job))


def validate_policy(manifest):
    errors = []
    if "composition_policy" in manifest and not enabled(manifest):
        errors.append("composition_policy must be {version: 1, mode: layout_first}")
    if enabled(manifest) and manifest.get("anchor_policy") != {"version": 1, "mode": "full_review_first"}:
        errors.append("layout_first requires anchor_policy {version: 1, mode: full_review_first}")
    return errors


def _p():
    import lc_image_pipeline
    return lc_image_pipeline


def _overlap(a, b):
    return (max(0, min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0]))
            * max(0, min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1])))


def contract(job):
    """Derived from the live renderer layout, deliberately ignoring the old lock."""
    from lc_layout import layout_geometry, resolve_layout_defaults
    from lc_design import copy_blocks
    geometry = layout_geometry(job)
    layout = resolve_layout_defaults(job)
    return {"version": 1, "canvas": job["canvas"],
            "geometry": {key: geometry[key] for key in
                         ("image_region_norm", "product_region_norm", "text_regions_norm")},
            "recipe": layout.get("recipe"),
            "copy": [{**block, "text": " ".join(block["text"].split())} for block in copy_blocks(job)],
            "intent": job.get("composition_intent"),
            "panels": [{key: panel.get(key) for key in ("id", "box", "fit", "source_crop")}
                       for panel in layout.get("panels", [])],
            "items": [{key: item.get(key) for key in ("id", "box", "image_box", "text_box", "target", "image_shape")}
                      for item in layout.get("items", [])],
            "protected_regions": layout.get("protected_regions", []),
            "canvas_background": layout.get("canvas_background"),
            "product_layers": [{key: value for key, value in layer.items() if key != "source_binding"}
                               for layer in job.get("product_layers", [])]}


def check_plan(manifest, job):
    if not applies(manifest, job):
        return
    p = _p()
    current = contract(job)
    intent = current["intent"]
    if not isinstance(intent, dict) or not all(isinstance(intent.get(key), str) and intent[key].strip()
                                              for key in ("negative_space", "subject_scale", "layout_reason")):
        raise p.PipelineError("COMPOSITION_PLAN_REQUIRED: describe negative_space, subject_scale and layout_reason before generation")
    geometry = current["geometry"]
    if any(_overlap(geometry["product_region_norm"], box) > 1e-8 for box in geometry["text_regions_norm"]):
        raise p.PipelineError("COMPOSITION_PLAN_OVERLAP: planned product and text containers overlap")
    frozen = job.get("composition_contract")
    if frozen and (frozen.get("sha256") != p.digest(current) or frozen.get("snapshot") != current):
        raise p.PipelineError("COMPOSITION_LOCK_CHANGED: restore the planned canvas, copy and regions; do not crop or shrink the base to fit text")
    if job.get("generation_geometry_lock") and job["generation_geometry_lock"] != geometry:
        raise p.PipelineError("COMPOSITION_LOCK_CHANGED: prompt and renderer no longer use the same regions")


def freeze(manifest, job):
    if not applies(manifest, job):
        return
    check_plan(manifest, job)
    snapshot = contract(job)
    job["composition_contract"] = {"sha256": _p().digest(snapshot), "snapshot": copy.deepcopy(snapshot)}


def prompt_lines(manifest, job):
    if not applies(manifest, job):
        return []
    p = _p()
    return ["Composition policy: layout_first/1. Plan the photograph for the final copy, before any text is drawn.",
            "Recompose the camera and product placement to the specified containers. Preserve the product's physical proportions, "
            "structure and markings, not the source photo's framing or canvas position.",
            "Keep the complete subject prominent inside its product container; leave every text container calm and unobstructed. "
            "Use natural scene surfaces or the deliberately planned information area; do not paint a placeholder box, border or text.",
            "Composition intent: " + p.json.dumps(job.get("composition_intent", {}), ensure_ascii=False, sort_keys=True)]


def sample_id(manifest):
    candidates = [job for job in manifest.get("jobs", []) if applies(manifest, job) and not _p().is_hold(job)]
    primary = next((job for job in candidates if job["id"] == "03_primary_use_case"), None)
    return (primary or candidates[0])["id"] if candidates else None


def sample_passed(manifest, base):
    p = _p()
    identifier = sample_id(manifest)
    if identifier is None:
        return None  # Main-only and native-text-only projects retain their product gate.
    job = p.find_by_id(manifest["jobs"], identifier)
    if base is None or job.get("status") != "qa_passed":
        return False
    try:
        require_pass(manifest, job, Path(base))
        validate_final(job.get("policy_qa_results", {}).get("visual_design"), require_passed=True)
        final = p.resolve_project_path(job.get("final_output"), Path(base), "sample final")
        return (final is not None and final.is_file() and p.sha256_file(final) == job.get("qa_final_sha256")
                and job.get("qa_fingerprint") == p.qa_fingerprint(manifest, job, Path(base)))
    except (ValueError, OSError, p.PipelineError):
        return False


def context(manifest, job, base):
    p = _p()
    check_plan(manifest, job)
    raw = p.resolve_project_path(job.get("raw_output"), base, "composition raw")
    if raw is None or not raw.is_file() or p.sha256_file(raw) != job.get("bound_raw_sha256"):
        raise p.PipelineError("COMPOSITION_RAW_REQUIRED: ingest the current base image first")
    if job.get("generated_prompt_hash") != p.generation_fingerprint(manifest, job, base):
        raise p.PipelineError("COMPOSITION_RAW_STALE: base image belongs to different generation inputs")
    return {"version": 1, "raw": p.sha256_file(raw), "contract": p.digest(contract(job)),
            "generation": job["generated_prompt_hash"], "rules": p.sha256_file(Path(__file__)),
            "assets": scene_assets(job.get("layout", {}), base),
            "preview": scene_assets(job.get("composition_preview", {}), base),
            "background": {"settings": job.get("background_normalization"),
                           "assets": p.asset_dependencies(job.get("background_normalization", {}), base)}}


def scene_assets(value, base):
    """The legacy helper omits layout `image` and review `path` keys."""
    p = _p()
    result = {}
    def visit(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"image", "path", "asset_path", "mask_path", "background_asset"} and isinstance(child, str) and child:
                    path = p.resolve_project_path(child, base, "composition asset")
                    result[child] = p.sha256_file(path) if path and path.is_file() else "MISSING"
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    return result


def _checks(values, names):
    p = _p()
    if not isinstance(values, dict) or set(values) != set(names):
        raise p.PipelineError("Explicit composition judgments required: " + ", ".join(names))
    for key, value in values.items():
        if (not isinstance(value, dict) or value.get("verdict") not in {"pass", "fail"}
                or not isinstance(value.get("notes"), str) or not value["notes"].strip()):
            raise p.PipelineError(f"Explicit verdict and observed notes required: {key}")


def validate_final(design, *, require_passed=False):
    p = _p()
    if not isinstance(design, dict):
        raise p.PipelineError("Explicit visual_design with four checks is required")
    if not isinstance(design.get("notes"), str) or not design["notes"].strip():
        raise p.PipelineError("Explicit visual_design notes are required")
    _checks(design.get("checks"), FINAL_CHECKS)
    failed = [key for key, value in design["checks"].items() if value["verdict"] == "fail"]
    if design.get("verdict") != ("fail" if failed else "pass"):
        raise p.PipelineError("visual_design verdict must agree with its four explicit checks")
    if failed and design.get("failure_stage") not in {"base", "typography"}:
        raise p.PipelineError("Failed visual_design needs failure_stage base or typography")
    if require_passed and failed:
        raise p.PipelineError("COMPOSITION_FINAL_FAILED: " + ", ".join(failed))
    return failed


def proof_valid(manifest, job, base):
    p = _p()
    proof = job.get("composition_review") or {}
    try:
        path = p.resolve_project_path(proof.get("path"), base, "composition review")
        if path is None or not path.is_file() or p.sha256_file(path) != proof.get("sha256"):
            return False
        record = p.read_json(path)
        return (record.get("job") == job["id"] and record.get("passed") is True
                and record.get("context") == context(manifest, job, base)
                and record.get("observed_product_bbox_norm") == job.get("composition_observed_bbox_norm")
                and (bool(job.get("composition_preview")) or record.get("observed_product_bbox_norm") == job.get("raw_product_bbox_norm")))
    except (ValueError, OSError, p.PipelineError):
        return False


def require_pass(manifest, job, base):
    if applies(manifest, job):
        check_plan(manifest, job)
        if not proof_valid(manifest, job, base):
            raise _p().PipelineError(f"COMPOSITION_REVIEW_REQUIRED: {job['id']}; review-prepare --stage composition before rendering text")


def _prepare_local(manifest, job, base):
    """Produce only the real, text-free composite; never invoke the text renderer."""
    p = _p()
    if job.get("render_mode") != "pixel_composite":
        return
    if job.get("composition_failure"):
        raise p.PipelineError("QUALITY_COMPOSITION_LOCAL_REPLAN: use --repair-local after correcting product layers")
    sample = sample_id(manifest)
    if sample and sample != job["id"] and sample_passed(manifest, base) is not True:
        raise p.PipelineError("COMPOSITION_SAMPLE_REQUIRED: finish the representative image before composing siblings")
    p.prepare(manifest, base, [job["id"]])
    if job.get("status") in {"blocked", "failed"}:
        raise p.PipelineError("Local composite is blocked; resolve its source/design issues first")
    if job.get("render_mode") != "pixel_composite":
        raise p.PipelineError("Local composition source gate selected a model route; use the current dispatch plan")
    freeze(manifest, job)
    if job.get("generated_prompt_hash") == job.get("prompt_hash"):
        return
    composite, layers = p.compose_product_layers(manifest, job, base)
    raw = p.resolve_project_path(job["raw_output"], base, "local composite")
    raw.parent.mkdir(parents=True, exist_ok=True)
    composite.save(raw, format="PNG")
    boxes = [item["bbox_norm"] for item in layers]
    x, y = min(b[0] for b in boxes), min(b[1] for b in boxes)
    right, bottom = max(b[0]+b[2] for b in boxes), max(b[1]+b[3] for b in boxes)
    job.update(raw_product_bbox_norm=[x, y, right-x, bottom-y], product_layer_provenance=layers,
               generated_prompt_hash=job["prompt_hash"], bound_raw_sha256=p.sha256_file(raw), status="generated")


def review_image(job, base):
    """Show preplanned photographic panels/insets before any text is drawn."""
    from PIL import Image, ImageOps, ImageDraw
    from lc_layout import layout_geometry, resolve_layout_defaults
    from lc_layout_v3 import panel_placement
    p = _p()
    layout, geom = resolve_layout_defaults(job), layout_geometry(job)
    if not layout.get("panels") and not any(item.get("image") for item in layout.get("items", [])):
        job.pop("composition_preview", None)
        return job["raw_output"]
    with Image.open(base / job["raw_output"]) as opened:
        canvas = ImageOps.contain(ImageOps.exif_transpose(opened).convert("RGB"), tuple(job["canvas"]))
        background = Image.new("RGB", tuple(job["canvas"]), layout.get("canvas_background") or job.get("padding_color", "#ffffff"))
        if not layout.get("canvas_background"):
            background.paste(canvas, ((background.width-canvas.width)//2, (background.height-canvas.height)//2))
    for panel, slot in zip(layout.get("panels", []), geom.get("panels", [])):
        path = p.resolve_project_path(panel["image"], base, "composition panel")
        with Image.open(path) as opened:
            source = ImageOps.exif_transpose(opened).convert("RGBA")
            placement = panel_placement({**panel, "fit": panel.get("fit", "cover"), "box": slot["box"], "source_size":source.size}, job["canvas"])
            sx, sy, sw, sh = placement["source"]
            dx, dy, dw, dh = placement["destination"]
            raster = source.crop((sx, sy, sx+sw, sy+sh)).resize((max(1,round(dw)),max(1,round(dh))),Image.Resampling.LANCZOS)
            background.paste(raster,(round(dx),round(dy)),raster.getchannel("A"))
    for item, slot in zip(layout.get("items", []), geom.get("items", [])):
        if not item.get("image") or not slot.get("image"):
            continue
        path = p.resolve_project_path(item["image"], base, "composition inset")
        x,y,w,h = slot["image"]
        with Image.open(path) as opened:
            source = ImageOps.exif_transpose(opened).convert("RGBA")
            size = (max(1,round(w*background.width)),max(1,round(h*background.height)))
            left, top = round(x*background.width), round(y*background.height)
            if slot.get("image_shape", item.get("image_shape", "rect")) == "circle":
                from PIL import ImageChops
                raster = ImageOps.fit(source,size,method=Image.Resampling.LANCZOS)
                mask = Image.new("L",size,0)
                ImageDraw.Draw(mask).ellipse((0,0,size[0]-1,size[1]-1),fill=255)
                mask = ImageChops.multiply(mask,raster.getchannel("A"))
            else:
                raster = ImageOps.contain(source,size,method=Image.Resampling.LANCZOS)
                left += (size[0]-raster.width)//2
                top += (size[1]-raster.height)//2
                mask = raster.getchannel("A")
            background.paste(raster,(left,top),mask)
    path = base / "review" / "image_layers" / f"{job['id']}-composition.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    background.save(path)
    job["composition_preview"] = {"path":p.relpath(path,base)}
    return p.relpath(path,base)


def repair_local(manifest, job, base):
    """One bounded correction of product layers inside the unchanged design."""
    p = _p()
    failure = job.get("composition_failure") or {}
    frozen = job.get("composition_contract") or {}
    if (job.get("render_mode") != "pixel_composite" or not failure
            or job.get("quality_repairs", 0) >= manifest.get("max_quality_repairs", 1)):
        raise p.PipelineError("LOCAL_COMPOSITION_REPAIR_UNAVAILABLE: a failed local base and unused quality repair are required")
    old = frozen.get("snapshot", {})
    current = contract(job)
    if (p.digest(old) != frozen.get("sha256") or frozen.get("sha256") != failure.get("context", {}).get("contract")
            or {k:v for k,v in old.items() if k != "product_layers"}
               != {k:v for k,v in current.items() if k != "product_layers"}):
        raise p.PipelineError("COMPOSITION_LOCK_CHANGED: local repair may change product layers only, not canvas, text or panels")
    raw = p.resolve_project_path(job.get("raw_output"), base, "failed local base")
    if raw is None or not raw.is_file() or p.sha256_file(raw) != failure["context"]["raw"]:
        raise p.PipelineError("STALE_COMPOSITION_FAILURE: failed local base changed")
    candidate = copy.deepcopy(manifest)
    target = p.find_by_id(candidate["jobs"], job["id"])
    target.pop("composition_contract", None)
    target.pop("generated_prompt_hash", None)
    target.pop("composition_review", None)
    target.pop("composition_failure", None)
    target.pop("blocked_reason", None)
    target["status"] = "pending"
    # The normal source/design preflight still runs before creating any pixels.
    _prepare_local(candidate, target, base)
    target.setdefault("composition_repair_history", []).append(copy.deepcopy({"contract": frozen, "failure": failure}))
    target["quality_repairs"] = job.get("quality_repairs", 0) + 1
    p.clear_reviews(target, image_changed=True)
    target.pop("composition_failure", None)
    job.clear()
    job.update(target)


def prepare_review(manifest, base, job_ids=None, *, repair=False):
    p = _p()
    base = Path(base)
    selected = p.job_selection(manifest, job_ids)
    results, errors = [], []
    for job in manifest["jobs"]:
        if job["id"] not in selected or not applies(manifest, job) or p.is_hold(job):
            continue
        try:
            if repair:
                repair_local(manifest, job, base)
            _prepare_local(manifest, job, base)
            freeze(manifest, job)
            look_at = review_image(job, base)
            binding = context(manifest, job, base)
            path = base / "review" / "packets" / f"{job['id']}-composition.json"
            packet = {"schema_version": 1, "stage": "composition", "job": job["id"],
                      "context": binding, "look_at": look_at, "raw": job["raw_output"], "planned": contract(job),
                      "observed_product_bbox_norm": None, "observed_protected_regions": [],
                      "checks": {key: {"verdict": None, "notes": ""} for key in BASE_CHECKS}}
            if not path.is_file() or p.read_json(path).get("context") != binding:
                p.write_json(path, packet)
            results.append({"job": job["id"], "stage": "composition", "packet": str(path),
                            "look_at": str(base / look_at)})
        except (ValueError, OSError, p.PipelineError) as exc:
            errors.append({"job": job["id"], "error": str(exc)})
    return {"packets": results, "errors": errors}


def route_failure(manifest, job, base, failures, binding, record):
    p = _p()
    job.pop("composition_review", None)
    job.pop("qa_fingerprint", None)
    job["composition_failure"] = {"context": binding, "failures": failures, "record": record}
    used = max(job.get("quality_repairs", 0), sum(a.get("kind") == "quality_repair" and not a.get("released_unstarted")
               and a.get("speculative_outcome") != "voided" for a in job.get("generation_attempts", [])))
    if used >= manifest.get("max_quality_repairs", 1):
        job.update(status="blocked", blocked_reason="QUALITY_REPAIR_LIMIT_REACHED: composition still fails")
    elif job.get("render_mode") == "pixel_composite":
        job.update(status="blocked", blocked_reason="QUALITY_COMPOSITION_LOCAL_REPLAN: correct source/layer placement before another composition")
    else:
        job.update(status="generation_repair_needed", pending_attempt_kind="quality_repair", queued_at=time.time())
    return {"job": job["id"], "status": job["status"], "failures": failures, "stage": "composition"}


def submit_review(manifest, base, packet):
    p = _p()
    job = p.find_by_id(manifest["jobs"], packet.get("job"))
    if job is None or not applies(manifest, job):
        raise p.PipelineError("Composition review requires a layout-first text job")
    binding = context(manifest, job, base)
    if packet.get("context") != binding or packet.get("schema_version") != 1:
        raise p.PipelineError("STALE_COMPOSITION_REVIEW: base image or composition changed")
    _checks(packet.get("checks"), BASE_CHECKS)
    observed = packet.get("observed_product_bbox_norm")
    protected = packet.get("observed_protected_regions")
    errors = []
    p.validate_bbox(observed, "observed_product_bbox_norm", errors)
    if not isinstance(protected, list):
        errors.append("observed_protected_regions must be a list of observed boxes")
    else:
        for box in protected:
            p.validate_bbox(box, "observed_protected_regions", errors)
    if errors:
        raise p.PipelineError("; ".join(errors))
    failures = ["composition:"+key for key, value in packet["checks"].items() if value["verdict"] == "fail"]
    boxes = contract(job)["geometry"]
    if any(_overlap(region, text) > 1e-8 for region in [observed, *protected] for text in boxes["text_regions_norm"]):
        failures.append("composition:observed_text_overlap")
    product = boxes["product_region_norm"]
    tolerance = .02  # Generation placement tolerance, not permission to overlap text.
    if (observed[0] < product[0]-tolerance or observed[1] < product[1]-tolerance
            or observed[0]+observed[2] > product[0]+product[2]+tolerance
            or observed[1]+observed[3] > product[1]+product[3]+tolerance):
        failures.append("composition:subject_outside_container")
    from PIL import Image, ImageOps
    with Image.open(base / job["raw_output"]) as opened:
        width, height = ImageOps.exif_transpose(opened).size
    if not math.isclose(width/height, job["canvas"][0]/job["canvas"][1], rel_tol=.01):
        failures.append("composition:wrong_aspect_ratio")
    record = {**copy.deepcopy(packet), "passed": not failures, "failures": failures}
    digest = p.digest(record)
    old = job.get("composition_review") or {}
    if old.get("submission_hash") == digest and proof_valid(manifest, job, base):
        return {"job": job["id"], "stage": "composition", "passed": True, "idempotent": True}
    path = base / "review" / "submissions" / f"{job['id']}-composition-{uuid.uuid4().hex}.json"
    p.write_json(path, record)
    if failures:
        return route_failure(manifest, job, base, failures, binding, p.relpath(path, base))
    job["composition_observed_bbox_norm"] = copy.deepcopy(observed)
    if not job.get("composition_preview"):
        job["raw_product_bbox_norm"] = copy.deepcopy(observed)
    job["composition_review"] = {"path": p.relpath(path, base), "sha256": p.sha256_file(path), "submission_hash": digest}
    job.pop("composition_failure", None)
    return {"job": job["id"], "stage": "composition", "passed": True, "next": "review-prepare --stage final"}


def prepare_repair(manifest, job, base):
    if not applies(manifest, job) or not job.get("composition_failure"):
        return False
    p = _p()
    failure = job["composition_failure"]
    raw = p.resolve_project_path(job.get("raw_output"), base, "composition repair target")
    if (raw is None or not raw.is_file() or p.sha256_file(raw) != failure["context"]["raw"]
            or p.digest(contract(job)) != failure["context"]["contract"]):
        raise p.PipelineError("STALE_COMPOSITION_FAILURE: restore the reviewed base and design")
    job["prompt_edit"] = {"target_path": job["raw_output"], "failures": failure["failures"]}
    return True


def final_review(manifest, job, base, packet):
    if not applies(manifest, job):
        return None
    p = _p()
    require_pass(manifest, job, base)
    design = packet.get("reviews", {}).get("policy_qa_results", {}).get("visual_design")
    failed = validate_final(design)
    if failed and design["failure_stage"] == "base":
        from lc_workflow import review_context
        request = job.get("review_request", {})
        if (packet.get("review_id") != request.get("id") or p.digest(packet.get("context")) != request.get("context_hash")
                or p.digest(review_context(manifest, job, base)) != request.get("context_hash")):
            raise p.PipelineError("STALE_REVIEW_PACKET: prepare a fresh final review")
        path = base / "review" / "submissions" / f"{job['id']}-composition-final-{uuid.uuid4().hex}.json"
        p.write_json(path, packet)
        return route_failure(manifest, job, base, ["composition:"+key for key in failed],
                             context(manifest, job, base), p.relpath(path, base))
    return None


def install():
    """Guard frozen workers once; opt-out projects reach the originals unchanged."""
    p = _p()
    if getattr(p.aspect_safe_postprocess, "_composition_guard", False):
        return
    original_render, original_qa = p.aspect_safe_postprocess, p.quality_assurance

    @functools.wraps(original_render)
    def render(manifest, base, force=False, job_ids=None, *, export=True):
        selected = p.job_selection(manifest, job_ids)
        for job in manifest["jobs"]:
            if job["id"] in selected and applies(manifest, job):
                if p.is_hold(job) or job.get("status") in {"blocked", "failed", "generating", "generation_repair_needed"}:
                    selected.discard(job["id"])
                    continue
                if job.get("status") == "pending" and job.get("render_mode") != "pixel_composite":
                    selected.discard(job["id"])
                    continue
                require_pass(manifest, job, base)
        if selected:
            return original_render(manifest, base, force, selected, export=export)

    @functools.wraps(original_qa)
    def qa(manifest, base, job_ids=None, *, update_overviews=True):
        selected = p.job_selection(manifest, job_ids)
        for job in manifest["jobs"]:
            if job["id"] in selected and applies(manifest, job):
                if p.is_hold(job) or job.get("status") in {"blocked", "failed", "generating", "pending", "generation_repair_needed"}:
                    selected.discard(job["id"])
                    continue
                require_pass(manifest, job, base)
                design = job.get("policy_qa_results", {}).get("visual_design")
                if validate_final(design) and design.get("failure_stage") == "base":
                    raise p.PipelineError("COMPOSITION_FINAL_FAILED: submit the bound final review to route a base repair")
        if selected:
            return original_qa(manifest, base, selected, update_overviews=update_overviews)
        return {"jobs": [], "summary": {"passed": 0, "repair_needed": 0, "blocked": 0, "failed": 0, "review_pending": 0}}

    render._composition_guard = True
    p.aspect_safe_postprocess, p.quality_assurance = render, qa
