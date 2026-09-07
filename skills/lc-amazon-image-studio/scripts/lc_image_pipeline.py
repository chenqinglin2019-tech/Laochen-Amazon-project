#!/usr/bin/env python3
"""Resumable local pipeline for Lc Amazon Image Studio v3.

The script never calls an image model. It prepares manifests and prompts, extracts
critical-detail references, performs aspect-safe post-processing, and enforces QA
gates around source resolution and micro-detail preservation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
import time
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat
except ImportError as exc:  # pragma: no cover - environment-specific failure
    raise SystemExit(
        "Pillow is required. Use the Codex bundled Python runtime or install pillow."
    ) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if __name__ == "__main__":
    sys.modules.setdefault("lc_image_pipeline", sys.modules[__name__])
from lc_assets import (POLICY_VERSION, digest, pixel_hash, compose_product_layers,
                       export_image, check_export, disclosure_issues, file_hash, file_hash_context)
from lc_design import (resolve_text_mode, copy_blocks, has_marketing_text, needs_local_layout,
                       requires_visual_design, design_prompt_lines, design_layout_payload,
                       native_text_review_issues, validate_design, panel_contracts, panel_review_issues,
                       required_design_unresolved, design_reference_issue, has_panel_sources)
from lc_dependencies import critical_detail_dependencies, attempt_generation_binding
from lc_project_contracts import (default_style_contract, default_copy_budget, resolved_style_contract,
                                  validate_project_contracts, project_contract_report, preflight_project_contracts,
                                  preflight_layout_fit, apply_adaptive_typography)
from lc_delivery import resolve_delivery_profile, apply_delivery_profile, artifact_sha256

SCHEMA_VERSION = 3
PIPELINE_VERSION = "3.0.0"
# The original source/box cache-key schema is algorithm v1. Preserve its bytes
# (and existing generation dependencies); later crop algorithms must version it.
DETAIL_CROP_ALGORITHM_VERSION = 1
VALID_RUN_MODES = {"risk_gated_auto", "confirm_each_stage"}
VALID_BACKENDS = {"built_in_image_gen"}
VALID_SOURCE_QUALITY = {"unknown", "sufficient", "marginal", "insufficient"}
VALID_MASTER_MODES = {"original_pixels", "restored_master", "blocked"}
VALID_RENDER_MODES = {"pixel_composite", "reference_edit", "reference_generate"}
VALID_PRIORITIES = {"P0", "P1", "P2"}
VALID_DETAIL_STATUS = {"unknown", "confirmed", "unverifiable"}
VALID_VISIBILITY = {"required", "optional", "hidden"}
VALID_EVIDENCE_LEVEL = {"visual_confirmed", "user_claim_only", "listing_fact", "unknown"}
VALID_QA_VERDICT = {"pass", "fail", "not_applicable"}
VALID_JOB_STATUS = {
    "pending",
    "generating",
    "generated",
    "qa_passed",
    "repair_needed",
    "blocked",
    "failed",
    "review_pending",
    "layout_repair_needed",
    "generation_repair_needed",
    "export_repair_needed",
}
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DERIVED_BLOCK_PREFIXES = (
    "DESIGN_REFERENCE_REQUIRED:",
    "DESIGN_COPY:",
    "SOURCE_",
    "FINE_DETAIL_",
    "RESTORED_MASTER_",
    "DETAIL_UNVERIFIABLE:",
    "DETAIL_VIEW_UNVERIFIABLE:",
    "QUALITY_",
    "CENSUS_",
)
ALLOWED_TRANSITIONS = {
    "pending": {"pending", "generating", "blocked", "failed", "review_pending"},
    "generating": {"generating", "generated", "pending", "failed", "blocked"},
    "generated": {"generated", "review_pending", "repair_needed", "blocked", "failed"},
    "qa_passed": {"qa_passed", "pending"},
    "repair_needed": {"repair_needed", "generating", "blocked", "failed"},
    "blocked": {"blocked", "pending"},
    "failed": {"failed", "pending", "blocked"},
    "review_pending": {"review_pending", "generated", "pending", "blocked"},
    "layout_repair_needed": {"layout_repair_needed", "generated", "blocked"},
    "generation_repair_needed": {"generation_repair_needed", "generating", "blocked"},
    "export_repair_needed": {"export_repair_needed", "generated", "blocked"},
}


class PipelineError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PipelineError(f"Manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == encoded:
        return
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def job_selection(manifest: dict, job_ids: Iterable[str] | None = None) -> set[str]:
    available = {j["id"] for j in manifest["jobs"]}
    selected = available if job_ids is None else set(job_ids)
    if not selected or selected - available:
        raise PipelineError(f"Unknown or empty job selection: {sorted(selected - available)}")
    return selected


def assess_sources_scoped(manifest: dict, base: Path, selected: set[str]) -> None:
    """Shared evidence is refreshed, but unrelated job state is not rewritten."""
    from lc_quality import assess_sources
    untouched = {j["id"]: copy.deepcopy(j) for j in manifest["jobs"] if j["id"] not in selected}
    try:
        assess_sources(manifest, base, materialize=not (manifest.get("review_evidence")
            and resolve_delivery_profile(manifest)["name"] == "compact_jpg"), job_ids=selected)
    finally:
        for job in manifest["jobs"]:
            if job["id"] in untouched:
                snapshot = untouched[job["id"]]
                job.clear()
                job.update(snapshot)


def is_hold(job: dict) -> bool:
    return (job.get("hold") is True or job.get("publication_status") == "hold"
            or (not job.get("required", True) and "specs_hold" in job.get("id", "")))


def active_model_count(manifest, *, exclude_product=None):
    """Product generation and local effects share the same model service slots."""
    return sum((job.get("status") == "generating" and job.get("id") != exclude_product)
               + sum(a.get("status") == "started" for a in job.get("title_effect_attempts", []))
               for job in manifest.get("jobs", []))


def resolve_path(value: str | None, base: Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def resolve_project_path(value: str | None, base: Path, label: str) -> Path | None:
    if not value:
        return None
    raw = Path(value).expanduser()
    if raw.is_absolute() or ".." in raw.parts:
        raise PipelineError(f"{label} must be a project-relative path without '..': {value!r}")
    resolved = (base / raw).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise PipelineError(f"{label} escapes the project directory: {value!r}") from exc
    return resolved


def relpath(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def sha256_file(path: Path) -> str:
    return file_hash(path)


def require_enum(value: Any, allowed: set[str], label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or value not in allowed:
        errors.append(f"{label} must be one of {sorted(allowed)}, got {value!r}")


def validate_id(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        errors.append(f"{label} must use lowercase letters, digits, underscores, or hyphens")


def validate_bbox(value: Any, label: str, errors: list[str], nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, list) or len(value) != 4:
        errors.append(f"{label} must be [x, y, width, height]")
        return
    if not all(isinstance(number, (int, float)) and not isinstance(number, bool)
               and (isinstance(number, int) or math.isfinite(number)) for number in value):
        errors.append(f"{label} must contain finite numbers")
        return
    x, y, width, height = value
    if any(number < 0 or number > 1 for number in value) or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        errors.append(f"{label} must stay inside normalized range 0..1")


def validate_manifest(manifest: dict[str, Any], base: Path, check_files: bool = True) -> list[str]:
    """Validate structure before any image work; unknown reviews remain valid input."""
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]

    def obj(parent, key, label, required=False):
        value = parent.get(key, None if required else {})
        if not isinstance(value, dict):
            errors.append(f"{label} must be an object")
            return {}
        return value

    def array(parent, key, label, required=False):
        value = parent.get(key, None if required else [])
        if not isinstance(value, list):
            errors.append(f"{label} must be an array")
            return []
        return value

    def text(parent, key, label, required=False):
        value = parent.get(key, "")
        if not isinstance(value, str) or (required and not value.strip()):
            errors.append(f"{label} must be {'nonempty ' if required else ''}text")
            return ""
        return value

    def strings(parent, key, label):
        values = array(parent, key, label)
        if any(not isinstance(v, str) or not v.strip() for v in values):
            errors.append(f"{label} must contain nonempty strings")
        return [v for v in values if isinstance(v, str) and v.strip()]

    def number(value, label, minimum, maximum, integer=False):
        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                 and minimum <= value <= maximum and (isinstance(value, int) or math.isfinite(value))
                 and (not integer or isinstance(value, int)))
        if not valid:
            errors.append(f"{label} must be a finite {'integer' if integer else 'number'} in {minimum}..{maximum}")
        return valid

    def boolean(parent, key, label, default=False):
        if not isinstance(parent.get(key, default), bool):
            errors.append(f"{label} must be boolean")

    def color(value, label):
        valid_hex = isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value)
        valid_rgb = (isinstance(value, list) and len(value) == 3
                     and all(type(v) is int and 0 <= v <= 255 for v in value))
        if not valid_hex and not valid_rgb:
            errors.append(f"{label} must be #RRGGBB or three integer RGB channels in 0..255")

    def path_value(value, label, project=False, existing=False):
        if not isinstance(value, str) or not value.strip() or "\x00" in value or "://" in value:
            errors.append(f"{label} must be a nonempty local filesystem path")
            return None
        try:
            path = resolve_project_path(value, base, label) if project else resolve_path(value, base)
            if path is not None and path.exists() and path.is_dir():
                errors.append(f"{label} must name a file, not a directory")
            elif existing and check_files and (path is None or not path.is_file()):
                errors.append(f"{label} does not exist: {value!r}")
            return path
        except (PipelineError, ValueError, TypeError, OSError) as exc:
            errors.append(f"{label}: {exc}")
            return None

    def unique_id(value, label, seen):
        validate_id(value, label, errors)
        if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
            return False
        if value in seen:
            errors.append(f"{label} must be unique")
            return False
        seen.add(value)
        return True

    def verdicts(parent, field, label, allowed):
        values = obj(parent, field, label)
        for key, value in values.items():
            if key not in allowed:
                errors.append(f"{label} has unknown check {key!r}")
            verdict = value.get("verdict") if isinstance(value, dict) else value
            require_enum(verdict, VALID_QA_VERDICT, f"{label}.{key}.verdict", errors)
            if isinstance(value, dict) and "notes" in value:
                text(value, "notes", f"{label}.{key}.notes")

    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    validate_id(manifest.get("project_id"), "project_id", errors)
    require_enum(manifest.get("run_mode"), VALID_RUN_MODES, "run_mode", errors)
    require_enum(manifest.get("generation_backend"), VALID_BACKENDS, "generation_backend", errors)
    from lc_scheduler import validate as validate_scheduler
    errors.extend(validate_scheduler(manifest))
    boolean(manifest, "critical_detail_census_completed", "critical_detail_census_completed")
    for key, default in (("max_transient_retries", 2), ("max_quality_repairs", 1)):
        number(manifest.get(key, default), key, 0, default, integer=True)
    text(manifest, "marketplace", "marketplace", required=True)
    language = text(manifest, "language", "language", required=True)
    if language and not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
        errors.append("language must be a BCP-47 language tag")
    strings(manifest, "shared_blockers", "shared_blockers")
    obj(manifest, "style_profile", "style_profile")
    if "style_reference_selection_path" in manifest:
        path_value(manifest["style_reference_selection_path"], "style_reference_selection_path", project=True)
    from lc_template_workflow import validate_template_inputs
    errors.extend(validate_template_inputs(manifest))

    truth = obj(manifest, "product_truth", "product_truth", required=True)
    text(truth, "product", "product_truth.product")
    # Legacy project-level flags remain readable, but V3 routes each task from
    # its actual product regions and evidence instead of a global master mode.
    if "source_quality" in truth:
        require_enum(truth["source_quality"], VALID_SOURCE_QUALITY, "product_truth.source_quality", errors)
    if "master_asset_mode" in truth:
        require_enum(truth["master_asset_mode"], VALID_MASTER_MODES, "product_truth.master_asset_mode", errors)
    boolean(truth, "master_confirmed", "product_truth.master_confirmed")
    for field in ("geometry_lock", "material_lock", "scene_scale_lock"):
        obj(truth, field, f"product_truth.{field}", required=True)
    safe = truth.get("safe_upscale_ratio", 1.25)
    marginal = truth.get("max_marginal_upscale_ratio", 1.75)
    safe_valid = number(safe, "product_truth.safe_upscale_ratio", 1.000001, 1.25)
    marginal_valid = number(marginal, "product_truth.max_marginal_upscale_ratio", 1.000001, 1.75)
    if safe_valid and marginal_valid and marginal <= safe:
        errors.append("max_marginal_upscale_ratio must exceed safe_upscale_ratio")

    references = array(manifest, "references", "references", required=True)
    if not references:
        errors.append("references must contain at least one product image")
    reference_ids: set[str] = set()
    reference_views: dict[str, str] = {}
    input_paths: set[Path] = set()
    for index, ref in enumerate(references):
        label = f"references[{index}]"
        if not isinstance(ref, dict):
            errors.append(f"{label} must be an object")
            continue
        if unique_id(ref.get("id"), f"{label}.id", reference_ids):
            reference_views[ref["id"]] = text(ref, "view", f"{label}.view", required=True)
        text(ref, "role", f"{label}.role", required=True)
        validate_bbox(ref.get("product_bbox_norm"), f"{label}.product_bbox_norm", errors)
        require_enum(ref.get("visual_quality", "unknown"), VALID_SOURCE_QUALITY, f"{label}.visual_quality", errors)
        source_path = path_value(ref.get("path"), f"{label}.path", existing=True)
        if source_path is not None:
            input_paths.add(source_path.resolve())
        obj(ref, "quality_review", f"{label}.quality_review")
        provenance = obj(ref, "provenance", f"{label}.provenance")
        strings(provenance, "source_reference_ids", f"{label}.provenance.source_reference_ids")
        obj(provenance, "reviewed_source_hashes", f"{label}.provenance.reviewed_source_hashes")

    facts = array(manifest, "facts", "facts")
    fact_ids: set[str] = set()
    for index, fact in enumerate(facts):
        label = f"facts[{index}]"
        if not isinstance(fact, dict):
            errors.append(f"{label} must be an object")
            continue
        unique_id(fact.get("id"), f"{label}.id", fact_ids)
        text(fact, "text", f"{label}.text")
        if "evidence" in fact and not isinstance(fact["evidence"], (str, list, dict)):
            errors.append(f"{label}.evidence must be text, an array, or an object")

    details = array(manifest, "critical_details", "critical_details")
    detail_ids: set[str] = set()
    for index, detail in enumerate(details):
        label = f"critical_details[{index}]"
        if not isinstance(detail, dict):
            errors.append(f"{label} must be an object")
            continue
        unique_id(detail.get("id"), f"{label}.id", detail_ids)
        text(detail, "name", f"{label}.name", required=True)
        for key, allowed, default in (("priority", VALID_PRIORITIES, None),
                                      ("evidence_level", VALID_EVIDENCE_LEVEL, "unknown"),
                                      ("visual_confirmation", VALID_DETAIL_STATUS, "unknown"),
                                      ("status", VALID_DETAIL_STATUS, "unknown")):
            require_enum(detail.get(key, default), allowed, f"{label}.{key}", errors)
        locations = array(detail, "locations", f"{label}.locations", required=True)
        if detail.get("status") == "confirmed" and not locations:
            errors.append(f"{label}.locations is required when status is confirmed")
        for loc_index, location in enumerate(locations):
            loc_label = f"{label}.locations[{loc_index}]"
            if not isinstance(location, dict):
                errors.append(f"{loc_label} must be an object")
                continue
            rid = text(location, "reference_id", f"{loc_label}.reference_id", required=True)
            if rid not in reference_ids:
                errors.append(f"{loc_label}.reference_id is unknown")
            elif location.get("view") != reference_views[rid]:
                errors.append(f"{loc_label}.view must match its reference view {reference_views[rid]!r}")
            validate_bbox(location.get("bbox_in_product_norm"), f"{loc_label}.bbox_in_product_norm", errors)
        visibility = obj(detail, "visibility", f"{label}.visibility")
        for job_id, value in visibility.items():
            require_enum(value, VALID_VISIBILITY, f"{label}.visibility.{job_id}", errors)

    jobs = array(manifest, "jobs", "jobs", required=True)
    if not jobs:
        errors.append("jobs must contain at least one image task")
    job_ids: set[str] = set()
    output_paths: dict[Path, str] = {}
    for index, job in enumerate(jobs):
        label = f"jobs[{index}]"
        if not isinstance(job, dict):
            errors.append(f"{label} must be an object")
            continue
        unique_id(job.get("id"), f"{label}.id", job_ids)
        require_enum(job.get("render_mode"), VALID_RENDER_MODES, f"{label}.render_mode", errors)
        require_enum(job.get("status", "pending"), VALID_JOB_STATUS, f"{label}.status", errors)
        require_enum(job.get("kind"), {"main", "listing", "a_plus"}, f"{label}.kind", errors)
        require_enum(job.get("placement_mode", "template"), {"template", "manual"}, f"{label}.placement_mode", errors)
        for field, default in (("required", True), ("requires_fine_detail", False), ("new_view", False)):
            boolean(job, field, f"{label}.{field}", default)
        for field in ("attempts", "quality_repairs"):
            number(job.get(field, 0), f"{label}.{field}", 0, 10000, integer=True)
        if "active_attempt_id" in job:
            validate_id(job["active_attempt_id"], f"{label}.active_attempt_id", errors)
        if "queued_at" in job:
            number(job["queued_at"], f"{label}.queued_at", 0, 253402300799)
        attempt_ids: set[str] = set()
        for i, attempt in enumerate(array(job, "generation_attempts", f"{label}.generation_attempts")):
            attempt_label = f"{label}.generation_attempts[{i}]"
            if not isinstance(attempt, dict):
                errors.append(f"{attempt_label} must be an object")
                continue
            unique_id(attempt.get("id"), f"{attempt_label}.id", attempt_ids)
            text(attempt, "prompt_hash", f"{attempt_label}.prompt_hash", required=True)
            if "kind" in attempt:
                require_enum(attempt["kind"], {"initial", "quality_repair", "transient_retry"}, f"{attempt_label}.kind", errors)
            require_enum(attempt.get("status"), {"dispatched", "ingested"}, f"{attempt_label}.status", errors)
            for key in ("dispatched_at", "queued_at", "tool_started_at", "tool_returned_at", "ingested_at"):
                if key in attempt or key == "dispatched_at":
                    number(attempt.get(key), f"{attempt_label}.{key}", 0, 253402300799)
        if "review_request" in job:
            obj(job, "review_request", f"{label}.review_request")
        if "visual_design_review_context" in job:
            text(job, "visual_design_review_context", f"{label}.visual_design_review_context", required=True)
        if "mobile_preview_binding" in job:
            binding = obj(job, "mobile_preview_binding", f"{label}.mobile_preview_binding")
            for field in ("sha256", "layout_sha256"):
                text(binding, field, f"{label}.mobile_preview_binding.{field}", required=True)
        for field in ("view", "target_view", "scene", "composition", "lighting", "selling_job"):
            if field in job:
                text(job, field, f"{label}.{field}")
        if "generation_dependency_version" in job and (type(job["generation_dependency_version"]) is not int
                or job["generation_dependency_version"] not in {1, 2}):
            errors.append(f"{label}.generation_dependency_version must be 1 or 2")
        if "padding_color" in job:
            color(job["padding_color"], f"{label}.padding_color")
        if "language" in job:
            lang = text(job, "language", f"{label}.language", required=True)
            if lang and not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", lang):
                errors.append(f"{label}.language must be a BCP-47 language tag")
        if "risk_priority" in job:
            number(job["risk_priority"], f"{label}.risk_priority", -10000, 10000)
        canvas = job.get("canvas")
        valid_canvas = isinstance(canvas, list) and len(canvas) == 2
        if not valid_canvas:
            errors.append(f"{label}.canvas must contain two integer dimensions")
        else:
            valid_canvas = all([number(v, f"{label}.canvas[{i}]", 1, 10000, integer=True) for i, v in enumerate(canvas)])
        if valid_canvas and isinstance(job.get("kind"), str) and job["kind"] in {"main", "listing"}:
            if min(canvas) < 1600 or not (canvas[0] == canvas[1] or canvas[1] * 10 == canvas[0] * 13):
                errors.append(f"{label}.canvas requires 1:1 or 1:1.3 (width:height), both sides >=1600")
        if job.get("kind") == "a_plus":
            text(job, "a_plus_module", f"{label}.a_plus_module", required=True)
        validate_bbox(job.get("target_product_bbox_norm"), f"{label}.target_product_bbox_norm", errors)
        if "generation_geometry_lock" in job:
            lock = obj(job, "generation_geometry_lock", f"{label}.generation_geometry_lock")
            for field in ("image_region_norm", "product_region_norm"):
                validate_bbox(lock.get(field), f"{label}.generation_geometry_lock.{field}", errors)
            for i, box in enumerate(array(lock, "text_regions_norm", f"{label}.generation_geometry_lock.text_regions_norm", required=True)):
                validate_bbox(box, f"{label}.generation_geometry_lock.text_regions_norm[{i}]", errors)
            if set(lock) - {"image_region_norm", "product_region_norm", "text_regions_norm"}:
                errors.append(f"{label}.generation_geometry_lock has unsupported fields")
        boolean(job, "hold", f"{label}.hold")
        if "publication_status" in job:
            require_enum(job["publication_status"], {"hold", "ready"}, f"{label}.publication_status", errors)
        for field in ("raw_product_bbox_norm", "output_product_bbox_norm"):
            validate_bbox(job.get(field), f"{label}.{field}", errors, nullable=True)
        overrides = obj(job, "detail_output_bbox_norms", f"{label}.detail_output_bbox_norms")
        for detail_id, bbox in overrides.items():
            if detail_id not in detail_ids:
                errors.append(f"{label}.detail_output_bbox_norms contains unknown detail {detail_id!r}")
            validate_bbox(bbox, f"{label}.detail_output_bbox_norms.{detail_id}", errors)
        for rid in strings(job, "source_reference_ids", f"{label}.source_reference_ids"):
            if rid not in reference_ids:
                errors.append(f"{label}.source_reference_ids contains unknown {rid!r}")
        for fid in strings(job, "claim_ids", f"{label}.claim_ids"):
            if fid not in fact_ids:
                errors.append(f"{label}.claim_ids contains unknown fact {fid!r}")
        for field in ("raw_output", "final_output"):
            path = path_value(job.get(field), f"{label}.{field}", project=True)
            if path is not None:
                if path in output_paths:
                    errors.append(f"{label}.{field} collides with {output_paths[path]}")
                output_paths[path] = f"{label}.{field}"
        output = job.get("final_output")
        if isinstance(output, str) and output and Path(output).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            errors.append(f"{label}.final_output must end in .png, .jpg or .jpeg")
        raw_output = job.get("raw_output")
        if isinstance(raw_output, str) and raw_output and Path(raw_output).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}:
            errors.append(f"{label}.raw_output must name a raster image file")
        if job.get("background_asset") is not None:
            input_path = path_value(job["background_asset"], f"{label}.background_asset", project=True, existing=True)
            if input_path is not None:
                input_paths.add(input_path.resolve())
        obj(job, "source_assessment", f"{label}.source_assessment")
        decision = obj(job, "render_decision", f"{label}.render_decision")
        strings(decision, "selected_reference_ids", f"{label}.render_decision.selected_reference_ids")
        for field in ("fingerprints", "detail_evidence_reference_ids"):
            mapping = obj(job, field, f"{label}.{field}")
            if any(not isinstance(v, str) for v in mapping.values()):
                errors.append(f"{label}.{field} must map keys to strings")
        verdicts(job, "semantic_qa_results", f"{label}.semantic_qa_results", {"geometry", "material", "scene_scale", "components", "clarity", "visual_integrity"})
        verdicts(job, "policy_qa_results", f"{label}.policy_qa_results", {"main_product_only", "claims", "competitor_copy", "text_readability", "mobile_readability", "visual_design"})
        verdicts(job, "detail_qa_results", f"{label}.detail_qa_results", detail_ids)

        disclosure = obj(job, "ai_disclosure", f"{label}.ai_disclosure")
        require_enum(disclosure.get("human_source", "unknown"), {"synthetic", "real", "none", "non_photorealistic", "unknown"}, f"{label}.ai_disclosure.human_source", errors)
        for field in ("notes", "reviewed_image_sha256", "reviewed_visual_fingerprint"):
            text(disclosure, field, f"{label}.ai_disclosure.{field}")
        if "disclosure_visual_fingerprint" in job:
            text(job, "disclosure_visual_fingerprint", f"{label}.disclosure_visual_fingerprint")
        for i, inset in enumerate(array(job, "disclosure_extra_images", f"{label}.disclosure_extra_images")):
            inset_label = f"{label}.disclosure_extra_images[{i}]"
            if not isinstance(inset, dict):
                errors.append(f"{inset_label} must be an object")
                continue
            path_value(inset.get("path"), f"{inset_label}.path", project=True, existing=True)
            text(inset, "sha256", f"{inset_label}.sha256", required=True)
        boolean(disclosure, "channel_reviewed", f"{label}.ai_disclosure.channel_reviewed")
        export = obj(job, "export", f"{label}.export")
        strings(export, "keywords", f"{label}.export.keywords")
        if "quality" in export:
            number(export["quality"], f"{label}.export.quality", 1, 100, integer=True)

        layout = obj(job, "layout", f"{label}.layout")
        version = layout.get("version", 1)
        errors.extend(f"{label}: {issue}" for issue in validate_design(job))
        if type(version) is not int or version not in {1, 2, 3}:
            errors.append(f"{label}.layout.version must be 1, 2 or 3")
        elif version == 2:
            from lc_layout import validate_layout_v2, LayoutError
            try:
                validate_layout_v2(layout)
            except LayoutError as exc:
                errors.append(f"{label}.layout: {exc}")
        elif version == 3:
            from lc_layout import validate_layout_v3, resolve_layout_defaults, LayoutError
            try:
                validate_layout_v3(resolve_layout_defaults(job))
            except LayoutError as exc:
                errors.append(f"{label}.layout: {exc}")
        for field, allowed, default in (("template", {"scene", "split", "benefits", "detail", "dimensions", "components"}, "scene"),
                                        ("theme", {"neutral", "warm", "technical", "playful"}, "neutral"),
                                        ("text_surface", {"transparent", "solid", "gradient"}, "transparent")):
            if version == 3 and field == "text_surface":
                continue  # V3 surface objects are validated with resolved V3 defaults above.
            require_enum(layout.get(field, default), allowed, f"{label}.layout.{field}", errors)
        if "direction" in layout:
            require_enum(layout["direction"], {"ltr", "rtl"}, f"{label}.layout.direction", errors)
        if "text_color" in layout and (not isinstance(layout["text_color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", layout["text_color"])):
            errors.append(f"{label}.layout.text_color must be #RRGGBB")
        for field, maximum in (("headline", 180), ("body", 500)):
            value = text(layout, field, f"{label}.layout.{field}")
            if len(value) > maximum:
                errors.append(f"{label}.layout.{field} is longer than {maximum} characters")
        sizes = obj(layout, "font_sizes", f"{label}.layout.font_sizes")
        for field, limits in (("headline", (120, 160)), ("body", (72, 88)), ("label", (64, 80))):
            if field in sizes and version == 1:
                number(sizes[field], f"{label}.layout.font_sizes.{field}", *limits)
        for i, region in enumerate(array(layout, "protected_regions", f"{label}.layout.protected_regions")):
            validate_bbox(region.get("bbox") if isinstance(region, dict) else region, f"{label}.layout.protected_regions[{i}]", errors)
        items = array(layout, "items", f"{label}.layout.items")
        if len(items) > (4 if version == 3 else 3):
            errors.append(f"{label}.layout.items exceeds its version's item limit")
        if layout.get("template") == "split" and items:
            errors.append(f"{label}.layout split uses headline/body only")
        for i, item in enumerate(items):
            item_label = f"{label}.layout.items[{i}]"
            if not isinstance(item, dict):
                errors.append(f"{item_label} must be an object")
                continue
            text(item, "text", f"{item_label}.text")
            strings(item, "evidence_refs", f"{item_label}.evidence_refs")
            if "icon" in item:
                require_enum(item["icon"], {"", "check", "leaf", "ruler", "tool", "layers", "care", "water", "light"}, f"{item_label}.icon", errors)
            if "image" in item:
                input_path = path_value(item["image"], f"{item_label}.image", project=True, existing=True)
                if input_path is not None:
                    input_paths.add(input_path.resolve())
            if "axis" in item:
                require_enum(item["axis"], {"horizontal", "vertical"}, f"{item_label}.axis", errors)
            if "target" in item:
                target = item["target"]
                if not isinstance(target, list) or len(target) != 2:
                    errors.append(f"{item_label}.target must be [x,y]")
                else:
                    for axis, value in enumerate(target):
                        number(value, f"{item_label}.target[{axis}]", 0, 1)
        if job.get("kind") == "main" and any(layout.get(k) for k in ("headline", "body", "items")):
            errors.append(f"{label}: main image cannot have marketing text or layout items")
        if job.get("kind") == "main" and layout.get("faq"):
            errors.append(f"{label}: main image cannot have marketing FAQ")
        if "text_overlays" in job:
            overlays = array(job, "text_overlays", f"{label}.text_overlays")
            if overlays:
                errors.append(f"{label}.text_overlays is legacy: migrate its copy to structured layout")

        for i, layer in enumerate(array(job, "product_layers", f"{label}.product_layers")):
            layer_label = f"{label}.product_layers[{i}]"
            if not isinstance(layer, dict):
                errors.append(f"{layer_label} must be an object")
                continue
            rid = text(layer, "reference_id", f"{layer_label}.reference_id", required=True)
            if rid not in reference_ids:
                errors.append(f"{layer_label}.reference_id is unknown")
            validate_bbox(layer.get("bbox_norm", job.get("target_product_bbox_norm")), f"{layer_label}.bbox_norm", errors)
            if layer.get("crop_bbox_norm") is not None:
                validate_bbox(layer["crop_bbox_norm"], f"{layer_label}.crop_bbox_norm", errors)
            for field in ("asset_path", "mask_path"):
                if layer.get(field) is not None:
                    input_path = path_value(layer[field], f"{layer_label}.{field}", project=True, existing=True)
                    if input_path is not None:
                        input_paths.add(input_path.resolve())
            strings(layer, "source_reference_ids", f"{layer_label}.source_reference_ids")
            obj(layer, "source_binding", f"{layer_label}.source_binding")
            boolean(layer, "opaque_rectangle", f"{layer_label}.opaque_rectangle")
            if "asset_origin" in layer:
                require_enum(layer["asset_origin"], {"original", "generated", "restored"}, f"{layer_label}.asset_origin", errors)
            shadow = obj(layer, "shadow", f"{layer_label}.shadow")
            boolean(shadow, "enabled", f"{layer_label}.shadow.enabled")
            for field, maximum in (("opacity", 1), ("blur", 1000)):
                if field in shadow:
                    number(shadow[field], f"{layer_label}.shadow.{field}", 0, maximum)
            if "offset" in shadow:
                offset = shadow["offset"]
                if not isinstance(offset, list) or len(offset) != 2:
                    errors.append(f"{layer_label}.shadow.offset must contain two numbers")
                else:
                    for axis, value in enumerate(offset):
                        number(value, f"{layer_label}.shadow.offset[{axis}]", -10000, 10000)
            if "color" in shadow and (not isinstance(shadow["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", shadow["color"])):
                errors.append(f"{layer_label}.shadow.color must be #RRGGBB")

    for detail in details:
        if not isinstance(detail, dict) or not isinstance(detail.get("visibility", {}), dict):
            continue
        visibility = detail.get("visibility", {})
        for job_id in visibility:
            if job_id not in job_ids:
                errors.append(f"critical_details[{detail.get('id')}].visibility references unknown job {job_id!r}")
        if isinstance(detail.get("priority"), str) and detail["priority"] in {"P0", "P1"}:
            missing = sorted(job_ids - set(visibility))
            if missing:
                errors.append(f"critical_details[{detail.get('id')}].visibility must explicitly cover every job; missing {missing}")
    for output_path, label in output_paths.items():
        if output_path.resolve() in input_paths:
            errors.append(f"{label} would overwrite an input asset")
    if not errors:
        from lc_quality import validate_quality
        errors.extend(validate_quality(manifest))
        errors.extend(validate_project_contracts(manifest))
        try:
            resolve_delivery_profile(manifest)
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def find_by_id(items: Iterable[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("id") == item_id), None)


def normalized_to_pixels(bbox: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, box_width, box_height = bbox
    left = max(0, min(width - 1, round(x * width)))
    top = max(0, min(height - 1, round(y * height)))
    right = max(left + 1, min(width, round((x + box_width) * width)))
    bottom = max(top + 1, min(height, round((y + box_height) * height)))
    return left, top, right, bottom


def detail_bbox_in_image(
    product_bbox: list[float], detail_bbox: list[float]
) -> list[float]:
    px, py, pw, ph = product_bbox
    dx, dy, dw, dh = detail_bbox
    return [px + dx * pw, py + dy * ph, dw * pw, dh * ph]


def preflight(manifest: dict[str, Any], base: Path, job_ids: Iterable[str] | None = None) -> None:
    from lc_quality import decide_job, validate_quality
    errors = validate_quality(manifest)
    if errors:
        raise PipelineError("Quality input validation failed:\n- " + "\n- ".join(errors))
    selected = job_selection(manifest, job_ids)
    assess_sources_scoped(manifest, base, selected)
    for job in manifest["jobs"]:
        if job["id"] not in selected:
            continue
        decision = decide_job(manifest, job)
        job["render_decision"] = decision
        job["effective_upscale_ratio"] = decision.get("effective_upscale_ratio")
        job["source_quality"] = decision.get("source_quality", "unknown")
        job["new_view"] = bool(decision.get("new_view"))
        if decision.get("blocked_reasons"):
            job["status"] = "blocked"
            job["blocked_reason"] = "QUALITY_" + ";".join(decision["blocked_reasons"])
        elif decision.get("recommended_mode"):
            job["render_mode"] = decision["recommended_mode"]


def extract_detail_references(manifest: dict[str, Any], base: Path, job_ids: Iterable[str] | None = None) -> None:
    output_dir = base / "detail_refs"
    output_dir.mkdir(parents=True, exist_ok=True)
    references = {ref["id"]: ref for ref in manifest["references"]}
    selected = job_selection(manifest, job_ids)
    grouped = {}
    chosen = []
    results = {}
    for detail in manifest.get("critical_details", []):
        if job_ids is not None and not any(detail.get("visibility", {}).get(j) == "required" for j in selected):
            continue
        chosen.append(detail)
        for index, location in enumerate(detail.get("locations", [])):
            grouped.setdefault(location["reference_id"], []).append((detail, index, location))
    for reference_id, locations in grouped.items():
        ref = references[reference_id]
        source_path = resolve_path(ref["path"], base)
        assert source_path is not None
        source_hash = sha256_file(source_path)
        # assess_sources has already bound the correctly oriented dimensions to
        # these source bytes. Standalone calls can obtain them while decoding.
        source_size = ref.get("image_size") if ref.get("sha256") == source_hash else None
        if (not isinstance(source_size, (list, tuple)) or len(source_size) != 2
                or any(type(n) is not int or n <= 0 for n in source_size)):
            source_size = None
        source = None
        def source_pixels():
            nonlocal source, source_size
            if source is None:
                with Image.open(source_path) as original:
                    source = ImageOps.exif_transpose(original).convert("RGB")
                if source_size is not None and tuple(source_size) != source.size:
                    raise PipelineError("Source dimensions changed; reassess product evidence")
                source_size = source.size
            return source
        try:
            if source_size is None:
                source_pixels()
            for detail, index, location in locations:
                image_bbox = detail_bbox_in_image(
                    ref["product_bbox_norm"], location["bbox_in_product_norm"]
                )
                left, top, right, bottom = normalized_to_pixels(
                    image_bbox, *source_size
                )
                detail_width, detail_height = right - left, bottom - top
                longest = max(detail_width, detail_height)
                shortest = min(detail_width, detail_height)
                pixel_verifiable = longest >= 32 and shortest >= 8
                visually_confirmed = location.get("visual_confirmation", detail.get("visual_confirmation")) == "confirmed"
                verifiable = pixel_verifiable and visually_confirmed
                padding = max(4, round(max(detail_width, detail_height) * 0.5))
                crop_box = (
                    max(0, left - padding),
                    max(0, top - padding),
                    min(source_size[0], right + padding),
                    min(source_size[1], bottom + padding),
                )
                output_path = output_dir / (
                    f"{detail['id']}__{location['view']}__{location['reference_id']}.png"
                )
                crop_inputs = {"source": source_hash, "box": crop_box}
                if DETAIL_CROP_ALGORITHM_VERSION != 1:
                    crop_inputs["algorithm_version"] = DETAIL_CROP_ALGORITHM_VERSION
                cache_key = digest(crop_inputs)
                previous = next((c for c in detail.get("reference_crops", [])
                                 if c.get("path") == relpath(output_path, base)), {})
                if (previous.get("cache_key") != cache_key or not output_path.is_file()
                        or previous.get("sha256") != sha256_file(output_path)):
                    with source_pixels().crop(crop_box) as crop:
                        crop.save(output_path, format="PNG")
                results[(detail["id"], index)] = {
                        "view": location["view"],
                        "reference_id": location["reference_id"],
                        "path": relpath(output_path, base),
                        "detail_pixel_size": [detail_width, detail_height],
                        "pixel_verifiable": pixel_verifiable,
                        "visually_confirmed": visually_confirmed,
                        "verifiable": verifiable,
                        "sha256": sha256_file(output_path),
                        "cache_key": cache_key,
                    }
        finally:
            if source is not None:
                source.close()
    for detail in chosen:
        crops = [results[(detail["id"], i)] for i in range(len(detail.get("locations", [])))]
        detail["reference_crops"] = crops
        detail["status"] = "confirmed" if any(c["verifiable"] for c in crops) else "unverifiable"


def lock_lines(lock: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in lock.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            rendered = "; ".join(str(item) for item in value)
        else:
            rendered = str(value)
        lines.append(f"- {key.replace('_', ' ').title()}: {rendered}")
    return lines or ["- Not confirmed; do not invent unsupported facts."]


def evidence_for_job(detail: dict, job: dict) -> tuple[dict | None, dict | None]:
    explicit = job.get("detail_evidence_reference_ids", {}).get(detail["id"], [])
    allowed = explicit or job.get("source_reference_ids", [])
    candidates = [c for c in detail.get("reference_crops", []) if c.get("verifiable")]
    if explicit:
        candidates = [c for c in candidates if c.get("reference_id") in explicit]
    # A detail close-up can support a new target angle without becoming that angle.
    candidates.sort(key=lambda c: (c.get("reference_id") not in allowed,
                                    c.get("view") != job.get("target_view", job.get("view"))))
    for crop in candidates:
        location = next((loc for loc in detail.get("locations", [])
                         if loc.get("reference_id") == crop.get("reference_id")
                         and loc.get("view") == crop.get("view")), None)
        if location:
            return location, crop
    return None, None


def generation_geometry(job: dict) -> dict:
    if "generation_geometry_lock" in job:
        lock = job["generation_geometry_lock"]
        errors = []
        if not isinstance(lock, dict) or set(lock) != {"image_region_norm", "product_region_norm", "text_regions_norm"}:
            raise PipelineError("generation_geometry_lock must contain exactly image/product/text regions")
        for field in ("image_region_norm", "product_region_norm"):
            validate_bbox(lock[field], f"generation_geometry_lock.{field}", errors)
        if not isinstance(lock["text_regions_norm"], list):
            errors.append("generation_geometry_lock.text_regions_norm must be an array")
        else:
            for box in lock["text_regions_norm"]:
                validate_bbox(box, "generation_geometry_lock.text_regions_norm", errors)
        if errors:
            raise PipelineError("; ".join(errors))
        return copy.deepcopy(lock)
    if not job.get("layout") or job.get("kind") == "main" or resolve_text_mode(job) == "model_native":
        return {"image_region_norm": [0, 0, 1, 1],
                "product_region_norm": job["target_product_bbox_norm"], "text_regions_norm": []}
    from lc_layout import layout_geometry
    geometry = layout_geometry(job)
    return {k: geometry[k] for k in ("image_region_norm", "product_region_norm", "text_regions_norm") if k in geometry}


def compile_job_prompt(manifest: dict[str, Any], job: dict[str, Any], base: Path
                       ) -> tuple[str, list[str], list[str], list[str]]:
    truth = manifest["product_truth"]
    required, hidden, reference_paths, detail_blocks = [], [], [], []
    source_ids = list(dict.fromkeys(job.get("source_reference_ids", []) +
                                   job.get("render_decision", {}).get("selected_reference_ids", [])))
    refs = {r["id"]: r for r in manifest["references"]}
    for ref_id in source_ids:
        if ref_id in refs:
            reference_paths.append(refs[ref_id]["path"])
    for detail in manifest.get("critical_details", []):
        visibility = detail.get("visibility", {}).get(job["id"], "optional")
        if visibility == "hidden":
            hidden.append(detail["id"])
            detail_blocks.append(f"- {detail['name']}: hidden in the target view. Do not reveal it, relocate it, or invent it on another surface.")
            continue
        if visibility != "required":
            continue
        required.append(detail["id"])
        location, crop = evidence_for_job(detail, job)
        if not crop or detail.get("status") != "confirmed":
            if detail["priority"] in {"P0", "P1"}:
                job["status"] = "blocked"
                job["blocked_reason"] = f"DETAIL_UNVERIFIABLE:{detail['id']}"
            continue
        reference_paths.append(crop["path"])
        if crop["reference_id"] in refs:
            reference_paths.append(refs[crop["reference_id"]]["path"])
        detail_blocks.append(
            f"- {detail['name']} ({detail['priority']}): {detail.get('description', '')}; "
            f"physical location: {location.get('position_description', '')}; "
            f"shape {detail.get('shape', '')}; orientation {detail.get('orientation', '')}; color {detail.get('color', '')}. "
            f"Evidence view: {crop['view']}. Do not delete, fill, move, redesign or invent the component; "
            "its projected location and apparent size must follow the target camera naturally.")
    paths = list(dict.fromkeys(reference_paths))
    roles = {r["path"]: r.get("role", "whole_product_reference") for r in manifest["references"]}
    geometry = generation_geometry(job)
    sections = ["Geometry Lock:", *lock_lines(truth.get("geometry_lock", {})),
                "- Preserve physical structure and dimensions. Natural perspective, silhouette projection and occlusion may change with the requested view.",
                "", "Material Lock:", *lock_lines(truth.get("material_lock", {})),
                "", "Scene Scale Lock:", *lock_lines(truth.get("scene_scale_lock", {})),
                "", "Critical Detail Lock:", *(detail_blocks or ["- No required identifying detail in this view."]),
                "", f"Asset: Amazon {job['kind']} image {job['id']}",
                f"Render mode: {job['render_mode']}; target view: {job.get('target_view', job.get('view'))}",
                f"Visual selling job: {job.get('selling_job', '')}", "Input image roles:",
                *[f"- {p}: {roles.get(p, 'critical_detail_reference')}" for p in paths],
                f"Product: {truth.get('product', '')}", f"Scene: {job.get('scene', '')}",
                f"Composition: {job.get('composition', '')}", f"Lighting: {job.get('lighting', '')}",
                f"Final canvas width x height: {job['canvas'][0]} x {job['canvas'][1]}; preserve its width:height ratio.",
                f"Normalized layout regions: {json.dumps(geometry, ensure_ascii=False)}",
                f"Target product box: {job['target_product_bbox_norm']}",
                ("Integrate the approved short text into the designed composition; keep faces, meaningful actions and identifying product details unobscured."
                 if resolve_text_mode(job) == "model_native" else "Leave the reserved text regions calm and free of product, faces and important actions."),
                ("Output the finished photographic poster with only the approved text and graphic treatment. Preserve genuine product labels from evidence; no watermarks."
                 if resolve_text_mode(job) == "model_native" else "Output a sharp photorealistic visual base without added marketing text, icons, arrows or watermarks. Preserve the product's genuine printed labels and branding from evidence."),
                "Do not mistake a high-resolution reference for a sharp product. Use clear supporting close-ups to recover supported appearance; never invent illegible text, ports or material detail."]
    sections.extend(design_prompt_lines(job))
    if job["render_mode"] == "pixel_composite":
        sections.append("The product will be composited locally from reviewed source pixels. If a background is needed, generate only the compatible background; do not repaint the product.")
    elif job["render_mode"] == "reference_edit":
        sections.append("Change only the specified defective region or environment; keep all already-correct product structure and regions unchanged.")
    else:
        sections.append("Reference-constrained redraw is permitted for sharpness, view, pose or scene fit. Rebuild the supported product appearance coherently in the target view; do not reproduce reference blur or invent hidden structure.")
    return "\n".join(sections) + "\n", required, hidden, paths


def asset_dependencies(value: Any, base: Path) -> dict[str, str]:
    result = {}
    def visit(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"asset_path", "mask_path", "image_path", "background_asset"} and isinstance(child, str) and child:
                    path = resolve_path(child, base)
                    result[child] = sha256_file(path) if path and path.is_file() else "MISSING"
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    return result


def generation_fingerprint(manifest: dict, job: dict, base: Path) -> str:
    """Verify model/local-composite inputs without loading layout/font/export dependencies."""
    copy_job = copy.deepcopy(job)
    bind_project_job(manifest, copy_job)
    prompt, required, hidden, paths = compile_job_prompt(manifest, copy_job, base)
    ref_hashes = {}
    for value in paths:
        path = resolve_path(value, base)
        ref_hashes[value] = sha256_file(path) if path and path.is_file() else "MISSING"
    details = critical_detail_dependencies(manifest, job, required + hidden)
    return digest({"version": PIPELINE_VERSION, "prompt": prompt, "references": ref_hashes,
                         "reference_boxes": [{"id": r["id"], "box": r.get("product_bbox_norm"), "view": r.get("view")}
                                             for r in manifest["references"] if r["path"] in paths],
                         "details": details, "product_layers": job.get("product_layers", []),
                         "background_asset": job.get("background_asset"),
                         "composite_color": job.get("padding_color", "#ffffff") if job["render_mode"] == "pixel_composite" else None,
                         "assets": asset_dependencies({"layers": job.get("product_layers", []),
                                                       "background_asset": job.get("background_asset")}, base)})


def bind_project_job(manifest: dict, job: dict) -> None:
    """Resolve project defaults without modifying any sibling job."""
    style = resolved_style_contract(manifest)
    if style is None:
        job.pop("_project_style", None)
    else:
        job["_project_style"] = style
        if job.get("kind") == "main":
            job["text_mode"] = "none"
        else:
            job.setdefault("text_mode", "local_overlay")
    apply_delivery_profile(manifest, job)


def typography_dispatch_fingerprint(manifest: dict, job: dict, base: Path) -> str:
    """Cheap dispatch binding; no browser or font initialization at handoff."""
    images = {}
    for collection in ("items", "panels"):
        for item in job.get("layout", {}).get(collection, []):
            if item.get("image"):
                path = resolve_path(item["image"], base)
                images[item["image"]] = sha256_file(path) if path and path.is_file() else "MISSING"
    return digest({"layout": job.get("layout"), "style": resolved_style_contract(manifest),
                   "design": design_layout_payload(job), "canvas": job.get("canvas"),
                   "geometry": generation_geometry(job), "language": job.get("language", manifest.get("language")),
                   "image_inputs": images,
                   "rules": {name: sha256_file(SCRIPT_DIR / name) for name in
                             ("lc_project_contracts.py", "lc_layout.py", "lc_layout_v3.py", "render_layout.mjs")}})


def current_fingerprints(manifest: dict, job: dict, base: Path) -> dict[str, str]:
    job = copy.deepcopy(job)
    bind_project_job(manifest, job)
    generation = generation_fingerprint(manifest, job, base)
    raw_path = resolve_path(job.get("raw_output"), base)
    raw_hash = sha256_file(raw_path) if raw_path and raw_path.is_file() else None
    if job.get("layout") and job.get("kind") != "main" and resolve_text_mode(job) != "model_native":
        from lc_layout import layout_fingerprint
        layout_runtime = layout_fingerprint(manifest, job, base)
    else:
        layout_runtime = "no-marketing-layout"
    layout_inputs = {"generation": generation, "raw": raw_hash, "raw_bbox": job.get("raw_product_bbox_norm"),
                          "layout": job.get("layout", {}), "runtime": layout_runtime,
                          "padding_color": job.get("padding_color", "#ffffff"),
                          "language": manifest.get("language"), "theme": manifest.get("style_profile", {}),
                          "assets": asset_dependencies(job.get("layout", {}), base)}
    if "text_mode" in job or job.get("design_brief"):
        layout_inputs.update(text_mode=resolve_text_mode(job), design=design_layout_payload(job))
    layout_hash = digest(layout_inputs)
    export_hash = digest({"layout": layout_hash, "export": job.get("export", {}),
                          "output": job.get("final_output"), "ai": job.get("ai_disclosure", {}),
                          "policy": POLICY_VERSION})
    return {"generation": generation, "layout": layout_hash, "export": export_hash}


def clear_reviews(job: dict, image_changed: bool) -> None:
    if image_changed:
        job["semantic_qa_results"] = {}
        job["detail_qa_results"] = {}
        job["detail_output_bbox_norms"] = {}
        job.pop("detail_review_context", None)
        job.pop("output_product_bbox_norm", None)
        job["ai_disclosure"] = {"human_source": "unknown", "notes": "Image changed: review human provenance again"}
        job.pop("model_text_review", None)
        job.pop("model_text_review_context", None)
        job.pop("panel_reviews", None)
        job.pop("panel_review_context", None)
    job["policy_qa_results"] = {}
    for key in ("qa_final_sha256", "qa_fingerprint", "qa_report_fingerprint"):
        job.pop(key, None)


def compile_prompts(manifest: dict[str, Any], base: Path, job_ids: Iterable[str] | None = None) -> None:
    prompt_dir = base / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    selected = job_selection(manifest, job_ids)
    for job in manifest["jobs"]:
        if job["id"] not in selected:
            continue
        previous = job.get("fingerprints", {})
        prompt, required, hidden, refs = compile_job_prompt(manifest, job, base)
        new = current_fingerprints(manifest, job, base)
        path = prompt_dir / f"{job['id']}.txt"
        if not path.is_file() or path.read_text(encoding="utf-8") != prompt:
            path.write_text(prompt, encoding="utf-8")
        job.update(prompt_file=relpath(path, base), prompt_hash=new["generation"],
                   required_details=required, hidden_details=hidden,
                   detail_reference_paths=[p for p in refs if "detail_refs/" in p],
                   generation_reference_paths=refs)
        if previous.get("generation") and previous["generation"] != new["generation"]:
            if job.get("status") in {"generation_repair_needed", "repair_needed"}:
                job["pending_attempt_kind"] = "quality_repair"
            if job.get("status") != "blocked":
                job["status"] = "pending"
            job["qa_invalidated_reason"] = "GENERATION_INPUT_CHANGED"
            # Recompiling a repair prompt is still the same logical image.
            # Never erase its attempt history or replenish its repair budget.
            if job.get("repair_in_progress") or job.get("pending_attempt_kind") == "quality_repair":
                job["pending_attempt_kind"] = "quality_repair"
            job["queued_at"] = time.time()
            clear_reviews(job, image_changed=True)
            for key in ("attempt_prompt_hash", "generated_prompt_hash", "final_prompt_hash", "final_sha256", "rendered_layout_hash", "exported_hash"):
                job.pop(key, None)
        elif previous.get("layout") and previous["layout"] != new["layout"]:
            if job.get("status") != "blocked":
                job["status"] = "generated" if job.get("generated_prompt_hash") == new["generation"] else "pending"
            job["qa_invalidated_reason"] = "LAYOUT_INPUT_CHANGED"
            clear_reviews(job, image_changed=False)
        elif previous.get("export") and previous["export"] != new["export"]:
            if job.get("status") != "blocked" and job.get("generated_prompt_hash") == new["generation"]:
                job["status"] = "generated"
            job["qa_invalidated_reason"] = "EXPORT_INPUT_CHANGED"
            job.pop("qa_fingerprint", None)
        job["fingerprints"] = current_fingerprints(manifest, job, base)
        job["prompt_hash"] = job["fingerprints"]["generation"]


def parse_color(value: Any, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    if isinstance(value, list) and len(value) == 3:
        return tuple(max(0, min(255, int(channel))) for channel in value)  # type: ignore[return-value]
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]
    return default


def find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        str(SCRIPT_DIR.parent / "assets" / "fonts" / "NotoSans-Regular.ttf"),
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def record_timing(job: dict, stage: str, started: float, cached: bool = False) -> None:
    record = {"stage": stage, "seconds": round(time.monotonic()-started, 4), "cached": cached}
    job.setdefault("timings", []).append(record)
    if cached:
        counters = job.setdefault("metrics", {}).setdefault("cache_hits", {})
        counters[stage] = counters.get(stage, 0) + 1


def has_text(job: dict) -> bool:
    """Compatibility name for policy checks, never use to choose the renderer."""
    layout = job.get("layout", {})
    if "text_mode" in job or layout.get("version", 1) >= 3:
        return has_marketing_text(job)
    return bool(layout.get("headline") or layout.get("body") or layout.get("items") or layout.get("faq") or job.get("text_overlays"))


def is_review_ready(job: dict) -> bool:
    if is_hold(job):
        return False
    if job.get("status") in {"generated", "review_pending", "qa_passed"}:
        return True
    if job.get("status") != "export_repair_needed" or not job.get("layout_result", {}).get("passed"):
        return False
    issues = {part.strip() for message in job.get("export_issues", []) for part in message.split(",")}
    source_review = {"AI_HUMAN_SOURCE_REVIEW_REQUIRED", "AI_DISCLOSURE_NOT_BOUND_TO_IMAGE", "AI_DISCLOSURE_INSET_REVIEW_REQUIRED"}
    return bool(issues) and issues.issubset(source_review) and issues == set(disclosure_issues(job))


def aspect_safe_postprocess(manifest: dict[str, Any], base: Path, force: bool = False,
                            job_ids: Iterable[str] | None = None, *, export: bool = True) -> None:
    selected = job_selection(manifest, job_ids)
    for job in manifest["jobs"]:
        if job["id"] in selected:
            bind_project_job(manifest, job)
    errors = validate_manifest(manifest, base)
    if errors:
        raise PipelineError("Manifest validation failed before composition:\n- " + "\n- ".join(errors))
    if not manifest.get("critical_detail_census_completed") or manifest.get("shared_blockers"):
        raise PipelineError("Shared product evidence and Critical Detail Census must be complete before composition")
    selected = job_selection(manifest, job_ids)
    preflight(manifest, base, selected)
    compile_prompts(manifest, base, selected)
    render_jobs = []
    retained_jobs = set()
    for job in manifest["jobs"]:
        if job["id"] not in selected:
            continue
        if job.get("status") in {"blocked", "failed", "generating"}:
            continue
        started = time.monotonic()
        raw_path = resolve_project_path(job.get("raw_output"), base, f"jobs[{job['id']}].raw_output")
        if raw_path is None:
            raise PipelineError(f"{job['id']}: raw_output is required")
        # Local compositing does not consume a model attempt.
        if job["render_mode"] == "pixel_composite" and job.get("generated_prompt_hash") != job["prompt_hash"]:
            if required_design_unresolved(job):
                job["status"], job["blocked_reason"] = "blocked", "DESIGN_REFERENCE_REQUIRED:resolve the explicit reference before composition"
                continue
            try:
                composite, layers = compose_product_layers(manifest, job, base)
            except (ValueError, OSError) as exc:
                job["status"], job["blocked_reason"] = "blocked", f"QUALITY_COMPOSITE:{exc}"
                continue
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            composite.save(raw_path, format="PNG")
            boxes = [item["bbox_norm"] for item in layers]
            x, y = min(b[0] for b in boxes), min(b[1] for b in boxes)
            r, b = max(b[0]+b[2] for b in boxes), max(b[1]+b[3] for b in boxes)
            job["raw_product_bbox_norm"] = [x, y, r-x, b-y]
            job["product_layer_provenance"] = layers
            job["generated_prompt_hash"] = job["prompt_hash"]
            job["bound_raw_sha256"] = sha256_file(raw_path)
            job["status"] = "generated"
            job.setdefault("metrics", {})["local_composites"] = job.get("metrics", {}).get("local_composites", 0)+1
        if not raw_path.is_file() or job.get("generated_prompt_hash") != job["prompt_hash"]:
            continue
        raw_sha = sha256_file(raw_path)
        if job.get("bound_raw_sha256") != raw_sha:
            job["status"], job["failed_reason"] = "failed", "RAW_CHANGED_WITHOUT_GENERATION_TRANSITION"
            continue
        new = current_fingerprints(manifest, job, base)
        job["fingerprints"] = new
        final_path = resolve_path(job.get("final_output"), base)
        if (not force and export and manifest.get("review_evidence") and job.get("status") == "qa_passed"
                and final_path and final_path.is_file() and job.get("final_sha256") == sha256_file(final_path)
                and job.get("rendered_layout_hash") == new["layout"] and job.get("exported_hash") == new["export"]
                and job.get("qa_fingerprint") == qa_fingerprint(manifest, job, base)):
            retained_jobs.add(job["id"])
            record_timing(job, "export", time.monotonic(), cached=True)
            continue
        layout_path = base / "review" / "layouts" / f"{job['id']}.png"
        image_path = base / "review" / "image_layers" / f"{job['id']}.png"
        image_input_hash = digest({"raw": raw_sha, "canvas": job["canvas"], "bbox": job.get("raw_product_bbox_norm"), "padding_color": job.get("padding_color", "#ffffff")})
        image_cached = not force and job.get("image_input_hash") == image_input_hash and image_path.is_file() and job.get("image_file_sha256") == sha256_file(image_path)
        if not image_cached:
            with Image.open(raw_path) as opened:
                source = ImageOps.exif_transpose(opened).convert("RGB")
                contained = ImageOps.contain(source, tuple(job["canvas"]), method=Image.Resampling.LANCZOS)
                image = Image.new("RGB", tuple(job["canvas"]), parse_color(job.get("padding_color", "#ffffff")))
                offset = ((image.width-contained.width)//2, (image.height-contained.height)//2)
                image.paste(contained, offset)
                job["aspect_padding"] = [offset[0], offset[1]]
                raw_bbox = job.get("raw_product_bbox_norm")
                if raw_bbox:
                    x, y, w, h = raw_bbox
                    job["output_product_bbox_norm"] = [(offset[0]+x*contained.width)/image.width,
                                                       (offset[1]+y*contained.height)/image.height,
                                                       w*contained.width/image.width, h*contained.height/image.height]
                image_sha = pixel_hash(image)
                if job.get("image_sha256") and job["image_sha256"] != image_sha:
                    clear_reviews(job, image_changed=True)
                    if raw_bbox:
                        job["output_product_bbox_norm"] = [(offset[0]+raw_bbox[0]*contained.width)/image.width,
                                                           (offset[1]+raw_bbox[1]*contained.height)/image.height,
                                                           raw_bbox[2]*contained.width/image.width, raw_bbox[3]*contained.height/image.height]
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image.save(image_path, format="PNG")
                job["image_file_sha256"] = sha256_file(image_path)
                job["image_sha256"] = image_sha
                job["image_input_hash"] = image_input_hash
        elif job.get("raw_product_bbox_norm") and not job.get("output_product_bbox_norm"):
            # Review invalidation can clear derived annotations while the pixel
            # cache remains valid. Recover geometry without rewriting pixels.
            with Image.open(raw_path) as opened:
                source = ImageOps.exif_transpose(opened)
                fitted = ImageOps.contain(source, tuple(job["canvas"]), method=Image.Resampling.LANCZOS)
                width, height = job["canvas"]
                offset = ((width-fitted.width)//2, (height-fitted.height)//2)
                x, y, w, h = job["raw_product_bbox_norm"]
                job["output_product_bbox_norm"] = [(offset[0]+x*fitted.width)/width,
                    (offset[1]+y*fitted.height)/height, w*fitted.width/width, h*fitted.height/height]
        job["image_output"] = relpath(image_path, base)
        job["layout_input"] = relpath(image_path, base)
        if apply_adaptive_typography(manifest, job, base):
            # The source pixels are unchanged, but typography must receive a
            # fresh visual/policy review and local render before export.
            clear_reviews(job, image_changed=False)
            job["qa_invalidated_reason"] = "ADAPTIVE_TYPOGRAPHY_UPDATED"
        job["disclosure_extra_images"] = [{"path": item["image"], "sha256": sha256_file(resolve_path(item["image"], base))}
                                           for item in (job.get("layout", {}).get("items", []) + job.get("layout", {}).get("panels", [])) if item.get("image")]
        visual_fingerprint = digest({"base_image": job["image_sha256"], "insets": job["disclosure_extra_images"]})
        if job.get("disclosure_visual_fingerprint") and job["disclosure_visual_fingerprint"] != visual_fingerprint:
            job["semantic_qa_results"] = {}
            job["policy_qa_results"] = {}
            job["ai_disclosure"] = {"human_source": "unknown", "notes": "Photographic content changed; review base and every inset"}
        job["disclosure_visual_fingerprint"] = visual_fingerprint
        job["fingerprints"] = current_fingerprints(manifest, job, base)
        layout_started = time.monotonic()
        from lc_typography import enabled as typography_enabled, proof_current
        proof_stale = typography_enabled(job) and not proof_current(job, base)
        if force or proof_stale or not job.get("layout_result", {}).get("passed") or job.get("rendered_layout_hash") != job["fingerprints"]["layout"] or not layout_path.is_file() or job.get("layout_output_sha256") != sha256_file(layout_path):
            if needs_local_layout(job) and job["kind"] != "main":
                render_jobs.append(copy.deepcopy(job))
            else:
                layout_path.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(image_path) as image:
                    image.save(layout_path, format="PNG")
                job["layout_result"] = {"passed": True, "checks": [], "output_path": relpath(layout_path, base)}
                if resolve_text_mode(job) == "model_native":
                    job["layout_result"].update(mode="model_native_passthrough", geometry_verified=False,
                                               requires_visual_review=True,
                                               checks=[{"check": "canvas_preparation", "passed": True}])
                job["rendered_layout_hash"] = job["fingerprints"]["layout"]
                job["layout_output_sha256"] = sha256_file(layout_path)
                if job.get("status") == "layout_repair_needed":
                    job["status"] = "generated"
        else:
            record_timing(job, "layout", layout_started, cached=True)
        record_timing(job, "image_prepare", started, cached=image_cached)
    if render_jobs:
        from lc_layout import render_batch
        results = render_batch(manifest, base, render_jobs)
        for rendering_job in render_jobs:
            job = find_by_id(manifest["jobs"], rendering_job["id"])
            for state_key in ("title_effect_state", "title_effect_attempts"):
                if state_key in rendering_job:
                    job[state_key] = copy.deepcopy(rendering_job[state_key])
            result = results.get(job["id"], {"passed": False, "checks": [{"code": "LAYOUT_RESULT_MISSING", "passed": False}]})
            job["layout_result"] = result
            expected_path = base / "review" / "layouts" / f"{job['id']}.png"
            if result.get("passed") and resolve_path(result.get("output_path"), base) != expected_path.resolve():
                result.update(passed=False, checks=[{"code": "LAYOUT_OUTPUT_PATH_MISMATCH", "passed": False}])
            if result.get("passed") and expected_path.is_file():
                job["rendered_layout_hash"] = job["fingerprints"]["layout"]
                job["layout_output_sha256"] = sha256_file(expected_path)
                if job.get("status") == "layout_repair_needed":
                    job["status"] = "generated"
            else:
                job["status"] = "layout_repair_needed"
            runtime = result.get("runtime", {})
            phases = [runtime.get(key) for key in ("python_prepare_seconds", "render_seconds", "preview_seconds")]
            if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in phases):
                job.setdefault("timings", []).append({"stage": "layout", "seconds": round(sum(phases), 4),
                    "cached": False, "measurement": "per_job_prepare_render_preview_excludes_shared_batch_costs",
                    "batch_id": runtime.get("batch_id")})
    for job in manifest["jobs"]:
        if job["id"] not in selected:
            continue
        if job["id"] in retained_jobs:
            continue
        if not export:
            if job.get("status") not in {"blocked", "failed", "pending", "generating", "generation_repair_needed", "layout_repair_needed"}:
                job["status"] = "review_pending"
            continue
        if job.get("status") in {"blocked", "failed", "pending", "generating", "generation_repair_needed"}:
            continue
        result = job.get("layout_result", {})
        if not result.get("passed"):
            continue
        layout_path = base / "review" / "layouts" / f"{job['id']}.png"
        if (resolve_path(result.get("output_path"), base) != layout_path.resolve()
                or not layout_path.is_file() or job.get("layout_output_sha256") != sha256_file(layout_path)):
            job["layout_result"] = {"passed": False, "checks": [{"code": "LAYOUT_OUTPUT_BINDING", "passed": False}]}
            job["status"] = "layout_repair_needed"
            continue
        final_path = resolve_project_path(job.get("final_output"), base, f"jobs[{job['id']}].final_output")
        if final_path is None:
            raise PipelineError(f"{job['id']}: final_output is required")
        fp = current_fingerprints(manifest, job, base)
        job["fingerprints"] = fp
        if job.get("exported_hash") == fp["export"] and final_path.is_file() and sha256_file(final_path) == job.get("final_sha256") and not force:
            record_timing(job, "export", time.monotonic(), cached=True)
            continue
        started = time.monotonic()
        try:
            with Image.open(layout_path) as image:
                from lc_typography import export_checked
                result = export_checked(image, job, base, final_path)
        except (OSError, ValueError) as exc:
            job["status"] = "export_repair_needed"
            job["export_issues"] = [str(exc)]
            continue
        job["export_result"] = result
        job["export_issues"] = []
        fp = current_fingerprints(manifest, job, base)
        job["fingerprints"] = fp
        job["exported_hash"] = fp["export"]
        job["final_sha256"] = result["file_sha256"]
        job["raw_sha256"] = sha256_file(resolve_path(job["raw_output"], base))
        job["final_prompt_hash"] = job["prompt_hash"]
        job["status"] = "generated"
        record_timing(job, "export", started)


def crop_output_detail(
    image: Image.Image,
    product_bbox: list[float],
    detail_bbox: list[float],
    absolute_detail_bbox: list[float] | None = None,
) -> Image.Image:
    image_bbox = absolute_detail_bbox or detail_bbox_in_image(product_bbox, detail_bbox)
    left, top, right, bottom = normalized_to_pixels(image_bbox, image.width, image.height)
    width, height = right - left, bottom - top
    padding = max(4, round(max(width, height) * 0.75))
    return image.crop(
        (
            max(0, left - padding),
            max(0, top - padding),
            min(image.width, right + padding),
            min(image.height, bottom + padding),
        )
    )


def make_comparison(reference: Image.Image, output: Image.Image, path: Path) -> None:
    tile_width, tile_height = 420, 420
    canvas = Image.new("RGB", (tile_width * 2, tile_height + 54), "white")
    draw = ImageDraw.Draw(canvas)
    font = find_font(24)
    for index, (label, image) in enumerate((("REFERENCE", reference), ("OUTPUT", output))):
        thumb = ImageOps.contain(image.convert("RGB"), (tile_width - 24, tile_height - 24))
        x = index * tile_width + (tile_width - thumb.width) // 2
        y = 48 + (tile_height - thumb.height) // 2
        canvas.paste(thumb, (x, y))
        draw.text((index * tile_width + 14, 12), label, fill="#17212b", font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG")


def corner_white_score(image: Image.Image) -> float:
    sample = max(8, min(image.width, image.height) // 40)
    corners = [
        (0, 0, sample, sample),
        (image.width - sample, 0, image.width, sample),
        (0, image.height - sample, sample, image.height),
        (image.width - sample, image.height - sample, image.width, image.height),
    ]
    values: list[float] = []
    for box in corners:
        stat = ImageStat.Stat(image.crop(box).convert("RGB"))
        values.append(sum(stat.mean) / 3)
    return round(sum(values) / len(values), 2)


def create_repair_prompt(
    manifest: dict[str, Any], job: dict[str, Any], detail: dict[str, Any], base: Path
) -> str:
    repair_dir = base / "repairs"
    repair_dir.mkdir(parents=True, exist_ok=True)
    path = repair_dir / f"{job['id']}__{detail['id']}.txt"
    prompt = (
        "Use case: precise-object-edit\n"
        f"Edit target: {job.get('raw_output', '')}\n"
        f"Critical detail reference: "
        f"{next((c.get('path') for c in detail.get('reference_crops', []) if c.get('view') == job.get('view')), '')}\n"
        f"Primary request: restore only {detail['name']} at its exact supported location.\n"
        f"Detail facts: {detail.get('description', '')}; shape {detail.get('shape', '')}; "
        f"orientation {detail.get('orientation', '')}; color {detail.get('color', '')}.\n"
        "Constraints: change only this missing or incorrect detail. Keep the entire remaining image, "
        "product geometry, materials, lighting, framing, scale, background, shadows, and every other "
        "visible detail pixel-for-pixel unchanged. Do not move, enlarge, shrink, rotate, simplify, "
        "or replace the detail. Preserve authentic product labels.\n"
        + ("Preserve all already-correct approved marketing text and graphic design exactly; do not add extra text or watermarks.\n"
           if resolve_text_mode(job) == "model_native" else "No added marketing text or watermark.\n")
    )
    path.write_text(prompt, encoding="utf-8")
    return relpath(path, base)


def create_semantic_repair_prompt(job: dict[str, Any], failed: list[str], base: Path) -> str:
    repair_dir = base / "repairs"
    repair_dir.mkdir(parents=True, exist_ok=True)
    path = repair_dir / f"{job['id']}__semantic.txt"
    prompt = (
        "Use case: precise-object-edit\n"
        f"Edit target: {job.get('raw_output', '')}\n"
        f"Primary request: correct only these failed checks: {', '.join(failed)}.\n"
        "Constraints: keep every already-correct product detail, composition, background, "
        + ("approved typography and graphic design, " if resolve_text_mode(job) == "model_native" else "text-free layout, ")
        + "and framing unchanged. Restore the product from the supplied whole-product and "
        "detail references. Do not add unsupported structure, material, component, prop, or claim.\n"
    )
    if resolve_text_mode(job) == "model_native":
        prompt += "Correct lettering only when a text check failed; otherwise preserve it. Approved exact copy: " + json.dumps(copy_blocks(job), ensure_ascii=False) + "\n"
    path.write_text(prompt, encoding="utf-8")
    return relpath(path, base)


def unpack_verdict(value: Any) -> str | None:
    return value.get("verdict") if isinstance(value, dict) else value


def style_selection_hash(manifest: dict, job: dict, base: Path) -> str | None:
    if (not requires_visual_design(job) and job.get("layout", {}).get("version", 1) != 2) or not manifest.get("style_reference_selection_path"):
        return None
    path = resolve_project_path(manifest["style_reference_selection_path"], base, "style_reference_selection_path")
    return sha256_file(path) if path.is_file() else "MISSING"


def visual_design_context(manifest: dict, job: dict, base: Path) -> str:
    payload = {"layout": current_fingerprints(manifest, job, base)["layout"],
               "selection": style_selection_hash(manifest, job, base)}
    if "design_resolution" in job:
        payload["resolution"] = job["design_resolution"]
        payload["reference_issue"] = design_reference_issue(job)
    return digest(payload)


def invalidate_visual_design_review(manifest: dict, job: dict, base: Path) -> None:
    if not requires_visual_design(job):
        return
    if job.get("visual_design_review_context") != visual_design_context(manifest, job, base):
        job.get("policy_qa_results", {}).pop("visual_design", None)
        job.pop("visual_design_review_context", None)
        job.pop("qa_fingerprint", None)
        job["visual_design_review_invalidated_reason"] = "LAYOUT_OR_STYLE_SELECTION_CHANGED"
        if job.get("status") == "qa_passed":
            job["status"] = "review_pending"


def mobile_preview_required(job: dict) -> bool:
    return "mobile_preview_binding" in job or requires_visual_design(job)


def native_text_context(manifest: dict, job: dict, base: Path) -> str:
    return digest({"layout": current_fingerprints(manifest, job, base)["layout"],
                   "copy": copy_blocks(job), "mobile": job.get("mobile_preview_binding"),
                   "layout_image": job.get("layout_output_sha256")})


def panel_review_context(manifest: dict, job: dict, base: Path) -> str:
    return digest({"layout": current_fingerprints(manifest, job, base)["layout"],
                   "panels": panel_contracts(manifest, job, base)})


def mobile_preview_is_current(job: dict, base: Path, manifest: dict | None = None) -> bool:
    binding = job.get("mobile_preview_binding") or {}
    layout = base / "review" / "layouts" / f"{job['id']}.png"
    preview = layout.with_name(f"{job['id']}-360.png")
    return (bool(binding.get("layout_sha256")) and bool(binding.get("sha256"))
            and artifact_sha256(manifest or {}, job, base, layout) == binding.get("layout_sha256")
            and artifact_sha256(manifest or {}, job, base, preview) == binding.get("sha256"))


def qa_fingerprint(manifest: dict, job: dict, base: Path) -> str:
    from lc_quality import assessment_context_fingerprint
    final_path = resolve_path(job.get("final_output"), base)
    layout_result = copy.deepcopy(job.get("layout_result", {}))
    # A staged transaction changes its directory, not its visual inputs.
    # Canonicalize only artifact path fields, never copy or external runtimes.
    for key in ("output_path", "preview_path"):
        if isinstance(layout_result.get(key), str):
            path = resolve_path(layout_result[key], base)
            if path is not None and path.is_relative_to(base.resolve()):
                layout_result[key] = relpath(path, base)
    payload = {"stages": current_fingerprints(manifest, job, base),
                   "final_sha256": sha256_file(final_path) if final_path and final_path.is_file() else None,
                   "semantic": job.get("semantic_qa_results", {}), "policy": job.get("policy_qa_results", {}),
                   "details": job.get("detail_qa_results", {}), "output_box": job.get("output_product_bbox_norm"),
                   "detail_boxes": job.get("detail_output_bbox_norms", {}),
                   "source_reviews": [{"id": r["id"], "quality_review": r.get("quality_review", {})} for r in manifest["references"]],
                   "source_assessment": job.get("source_assessment", {}),
                   "current_evidence_context": assessment_context_fingerprint(manifest, job),
                   "product_layer_provenance": job.get("product_layer_provenance", []),
                   "facts": manifest.get("facts", []),
                   "style_reference_selection": style_selection_hash(manifest, job, base),
                   "visual_design_review_context": job.get("visual_design_review_context"),
                   "mobile_preview_binding": job.get("mobile_preview_binding"),
                   "artifacts": {relpath(path, base): artifact_sha256(manifest, job, base, path) for path in
                                 (base / "review" / "layouts" / f"{job['id']}.png",
                                  base / "review" / "layouts" / f"{job['id']}-360.png",
                                  base / "review" / "image_layers" / f"{job['id']}.png")},
                   "rule_hashes": {name: sha256_file(SCRIPT_DIR / name) for name in
                                   ("lc_image_pipeline.py", "lc_quality.py", "lc_assets.py")},
                   "layout_result": layout_result, "policy_version": POLICY_VERSION,
                   "pipeline": PIPELINE_VERSION}
    from lc_dependencies import scoped_review_dependencies, evidence_dependencies
    if scoped_review_dependencies(manifest, job):
        dependencies = evidence_dependencies(manifest, job, base)
        payload["source_reviews"] = [{"id": r["id"], "quality_review": r.get("quality_review", {})}
                                     for r in dependencies["references"]]
        payload["facts"] = dependencies["facts"]
        payload["evidence_dependencies"] = dependencies
        payload["dependency_rule_hashes"] = {name: sha256_file(SCRIPT_DIR / name)
                                            for name in ("lc_dependencies.py", "lc_workflow.py")}
    if manifest.get("style_contract") or manifest.get("copy_budget"):
        payload["project_contracts"] = {key: manifest.get(key) for key in ("style_contract", "copy_budget")}
        payload["contract_rule_hashes"] = {name: sha256_file(SCRIPT_DIR / name)
            for name in ("lc_project_contracts.py", "lc_dependencies.py", "lc_workflow.py", "lc_delivery.py")}
    from lc_typography import enabled, proof_paths
    if enabled(job):
        from lc_dependencies import title_effect_dependencies
        payload["local_typography"] = {"export_result": job.get("export_result", {}).get("typography"),
            "proofs": {name: artifact_sha256(manifest, job, base, path) for name, path in proof_paths(base, job["id"]).items()},
            "effect": title_effect_dependencies(job, base, phase="review"), "effect_review": job.get("title_effect_review")}
    if resolve_text_mode(job) == "model_native":
        payload.update(model_text_review=job.get("model_text_review"),
                       model_text_review_context=job.get("model_text_review_context"))
    if has_panel_sources(job):
        payload.update(panel_reviews=job.get("panel_reviews"), panel_review_context=job.get("panel_review_context"),
                       panel_contracts=panel_contracts(manifest, job, base))
    if "design_resolution" in job:
        payload["design_resolution"] = job["design_resolution"]
        payload["reference_issue"] = design_reference_issue(job)
    return digest(payload)


def claim_issues(manifest: dict, job: dict) -> list[str]:
    layout = job.get("layout", {})
    blocks = copy_blocks(job)
    texts = [block["text"] for block in blocks]
    observed = job.get("model_text_review") or {}
    texts.extend(str(item.get("text", "")) for item in observed.get("blocks", []) if isinstance(item, dict))
    texts.extend(str(value) for value in observed.get("unexpected_text", []))
    text = " ".join(texts)
    issues = []
    if re.search(r"\b(buy now|shop now|order now|satisfaction guaranteed|money.back guarantee|best seller)\b", text, re.I):
        issues.append("PROMOTIONAL_COPY_NOT_ALLOWED_IN_DEFAULT_LISTING_LAYOUT")
    facts = {f["id"]: f for f in manifest.get("facts", []) if isinstance(f, dict) and f.get("id")}
    evidence_ids = set(facts) | {r["id"] for r in manifest["references"]} | {d["id"] for d in manifest.get("critical_details", [])}
    for item in blocks + layout.get("panels", []):
        for evidence_id in item.get("evidence_refs", []):
            if evidence_id not in evidence_ids:
                issues.append(f"LAYOUT_EVIDENCE_UNKNOWN:{evidence_id}")
    ids = job.get("claim_ids", [])
    if re.search(r"[0-9]", text) and not ids:
        issues.append("NUMERIC_COPY_REQUIRES_FACT_BINDING")
    for fact_id in ids:
        fact = facts.get(fact_id)
        if not fact or not fact.get("text") or not fact.get("evidence"):
            issues.append(f"CLAIM_EVIDENCE_MISSING:{fact_id}")
    return issues


def quality_assurance(manifest: dict[str, Any], base: Path,
                      job_ids: Iterable[str] | None = None, *, update_overviews: bool = True) -> dict[str, Any]:
    errors = validate_manifest(manifest, base, check_files=True)
    if errors:
        raise PipelineError("Manifest validation failed before QA:\n- " + "\n- ".join(errors))
    if not manifest.get("critical_detail_census_completed"):
        raise PipelineError("Critical Detail Census must be complete before QA")
    from lc_quality import decide_job
    selected = job_selection(manifest, job_ids)
    assess_sources_scoped(manifest, base, selected)
    report = {"schema_version": SCHEMA_VERSION, "project_id": manifest["project_id"],
              "jobs": [], "summary": {"passed": 0, "repair_needed": 0, "blocked": 0, "failed": 0, "review_pending": 0}}
    try:
        previous_results = {r["id"]: r for r in read_json(base / "qa_report.json").get("jobs", [])}
    except (PipelineError, KeyError, TypeError):
        previous_results = {}
    comparisons = []
    for job in manifest["jobs"]:
        started = time.monotonic()
        prior = previous_results.get(job["id"], {})
        previous_comparisons = [d for d in prior.get("details", []) if d.get("comparison_path")]
        if job["id"] not in selected:
            preserved = copy.deepcopy(prior) if prior else {"id": job["id"], "status": job.get("status", "pending"), "not_evaluated": True}
            report["jobs"].append(preserved)
            state = preserved.get("status")
            category = "passed" if state == "qa_passed" else state if state in report["summary"] else "repair_needed"
            report["summary"][category] += 1
            comparisons.extend((f"{job['id']} / {d['id']}", base / d["comparison_path"]) for d in previous_comparisons)
            continue
        invalidate_visual_design_review(manifest, job, base)
        comparisons_intact = all(artifact_sha256(manifest, job, base, base / d["comparison_path"]) == d.get("comparison_sha256")
                                 and bool(d.get("comparison_sha256"))
                                 for d in previous_comparisons)
        if (job.get("status") == "qa_passed" and prior.get("status") == "qa_passed"
                and job.get("qa_report_fingerprint") == digest(prior) and comparisons_intact
                and job.get("qa_fingerprint") == qa_fingerprint(manifest, job, base)):
            report["jobs"].append(prior)
            report["summary"]["passed"] += 1
            comparisons.extend((f"{job['id']} / {d['id']}", base / d["comparison_path"]) for d in previous_comparisons)
            record_timing(job, "qa", started, cached=True)
            continue
        result = {"id": job["id"], "checks": [], "details": []}
        blocked, image_failures, layout_failures, missing = [], [], [], []
        def check(code, passed, **data):
            result["checks"].append({"code": code, "passed": bool(passed), **data})
        if job.get("status") in {"blocked", "failed", "pending", "generating", "layout_repair_needed", "export_repair_needed"}:
            result.update(status=job["status"], reason=job.get("blocked_reason") or job.get("failed_reason") or job.get("export_issues"))
            category = job["status"] if job["status"] in report["summary"] else "repair_needed"
            report["summary"][category] += 1
            report["jobs"].append(result)
            continue
        final_path = resolve_project_path(job.get("final_output"), base, f"jobs[{job['id']}].final_output")
        current = current_fingerprints(manifest, job, base)
        raw_path = resolve_path(job.get("raw_output"), base)
        fresh = (final_path is not None and final_path.is_file()
                 and job.get("final_prompt_hash") == current["generation"]
                 and job.get("rendered_layout_hash") == current["layout"]
                 and job.get("exported_hash") == current["export"]
                 and sha256_file(final_path) == job.get("final_sha256")
                 and raw_path is not None and raw_path.is_file()
                 and sha256_file(raw_path) == job.get("bound_raw_sha256"))
        check("OUTPUT_BOUND_TO_CURRENT_INPUTS", fresh)
        if not fresh:
            job["status"], job["failed_reason"] = "failed", "STALE_OR_MODIFIED_OUTPUT"
            result["status"] = "failed"
            report["summary"]["failed"] += 1
            report["jobs"].append(result)
            continue
        if mobile_preview_required(job):
            preview_current = mobile_preview_is_current(job, base, manifest)
            check("MOBILE_PREVIEW_BINDING", preview_current)
            if not preview_current:
                missing.append("mobile_preview_review")
        from lc_workflow import annotation_fingerprint
        annotation_hash = annotation_fingerprint(job)
        if job.get("detail_review_context") and job["detail_review_context"] != annotation_hash:
            job["detail_qa_results"] = {}
        job["detail_review_context"] = annotation_hash
        decision = decide_job(manifest, job)
        job["new_view"] = bool(decision.get("new_view"))
        check("SOURCE_EVIDENCE_AND_FIT", not decision.get("blocked_reasons"), issues=decision.get("blocked_reasons", []))
        blocked.extend(decision.get("blocked_reasons", []))
        if decision.get("recommended_mode") != job["render_mode"]:
            blocked.append("RENDER_MODE_NO_LONGER_MATCHES_EVIDENCE")
        export_issues = check_export(job, final_path)
        check("FINAL_METADATA", not export_issues, issues=export_issues)
        blocked.extend(export_issues)
        from lc_typography import export_evidence_issues
        typography_issues = export_evidence_issues(manifest, job, base, final_path)
        if typography_issues:
            layout_failures.extend(typography_issues)
        if job.get("export_result", {}).get("typography") is not None:
            check("FINAL_ENCODED_TYPOGRAPHY", not typography_issues, issues=typography_issues)
        if job.get("title_effect_state", {}).get("applied"):
            from lc_title_effects import review_issues
            effect_issues = review_issues(job, job.get("title_effect_review"))
            check("LOCAL_TITLE_EFFECT_REVIEW", not effect_issues, issues=effect_issues)
            layout_failures.extend(effect_issues)
        copy_issues = claim_issues(manifest, job)
        contracts = project_contract_report(manifest)
        check("PROJECT_STYLE_AND_COPY", contracts["passed"], issues=contracts["issues"])
        if not contracts["passed"]:
            layout_failures.extend(contracts["issues"])
        check("COPY_FACT_BINDINGS", not copy_issues, issues=copy_issues)
        (image_failures if resolve_text_mode(job) == "model_native" else layout_failures).extend(copy_issues)
        check("CANVAS_PREPARATION" if resolve_text_mode(job) == "model_native" else "LAYOUT_GEOMETRY", job.get("layout_result", {}).get("passed", False))
        if not job.get("layout_result", {}).get("passed"):
            layout_failures.append("LAYOUT_GEOMETRY")
        with Image.open(final_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            check("CANVAS_SIZE", image.size == tuple(job["canvas"]), actual=list(image.size))
            if image.size != tuple(job["canvas"]):
                blocked.append("CANVAS_SIZE")
            product_box = job.get("output_product_bbox_norm")
            if product_box is None:
                missing.append("output_product_bbox_norm")
            if job["render_mode"] == "pixel_composite":
                provenance = job.get("product_layer_provenance", [])
                scale = max((p["scale"] for p in provenance), default=None)
                limit = manifest["product_truth"].get("safe_upscale_ratio", 1.25) if job.get("requires_fine_detail") else manifest["product_truth"].get("max_marginal_upscale_ratio", 1.75)
                valid_scale = scale is not None and scale <= limit
                check("ACTUAL_SAFE_UPSCALE", valid_scale, actual=scale, limit=limit)
                if not valid_scale:
                    blocked.append("ACTUAL_SAFE_UPSCALE")
            if job["kind"] == "main":
                white = corner_white_score(image)
                check("MAIN_WHITE_BACKGROUND", white >= 254.5 and not has_text(job), corner_white_score=white)
                if white < 254.5 or has_text(job):
                    image_failures.append("MAIN_WHITE_BACKGROUND")
            result["semantic_checks"] = []
            for key in ("geometry", "material", "components", "scene_scale", "clarity", "visual_integrity"):
                verdict = unpack_verdict(job.get("semantic_qa_results", {}).get(key))
                valid = verdict == "pass" or (key == "scene_scale" and job["kind"] == "main" and verdict == "not_applicable")
                result["semantic_checks"].append({"check": key, "verdict": verdict or "missing", "passed": valid})
                if not valid:
                    (missing if verdict is None else image_failures).append(f"semantic:{key}")
            result["policy_checks"] = []
            policy_keys = ["main_product_only", "claims", "competitor_copy", "text_readability", "mobile_readability"]
            if requires_visual_design(job):
                policy_keys.append("visual_design")
            for key in policy_keys:
                verdict = unpack_verdict(job.get("policy_qa_results", {}).get(key))
                if key == "visual_design" and design_reference_issue(job):
                    result["policy_checks"].append({"check": key, "verdict": verdict or "missing", "passed": False,
                                                    "reason": design_reference_issue(job)})
                    missing.append("design_reference_resolution")
                    continue
                allow_na = (key == "main_product_only" and job["kind"] != "main") or (key in {"text_readability", "mobile_readability"} and not has_text(job))
                valid = verdict == "pass" or (allow_na and verdict == "not_applicable")
                notes_missing = False
                if key == "visual_design":
                    design = job.get("policy_qa_results", {}).get(key)
                    if not isinstance(design, dict) or not isinstance(design.get("notes"), str) or not design["notes"].strip():
                        valid = False
                        notes_missing = True
                result["policy_checks"].append({"check": key, "verdict": verdict or "missing", "passed": valid})
                if not valid:
                    (missing if verdict is None or (notes_missing and verdict != "fail") else (layout_failures if needs_local_layout(job) and key != "main_product_only" else image_failures)).append(f"policy:{key}")
            if resolve_text_mode(job) == "model_native":
                text_issues = native_text_review_issues(job, job.get("model_text_review"))
                bound = job.get("model_text_review_context") == native_text_context(manifest, job, base)
                check("MODEL_TEXT_REVIEW", not text_issues and bound, issues=text_issues, bound=bound)
                if not bound or not job.get("model_text_review"):
                    missing.append("model_text_review")
                else:
                    image_failures.extend(text_issues)
            if has_panel_sources(job):
                contracts = panel_contracts(manifest, job, base)
                panel_issues = panel_review_issues(contracts, job.get("panel_reviews"))
                bound = job.get("panel_review_context") == panel_review_context(manifest, job, base)
                check("PANEL_REVIEWS", not panel_issues and bound, issues=panel_issues, bound=bound)
                source_errors = [f"{item['id']}:{error}" for item in contracts for error in item["errors"]]
                if source_errors:
                    blocked.extend(source_errors)
                elif not bound or not job.get("panel_reviews"):
                    missing.append("panel_reviews")
                else:
                    layout_failures.extend(panel_issues)
            for detail in manifest.get("critical_details", []):
                if detail.get("visibility", {}).get(job["id"]) != "required":
                    continue
                needed = detail["priority"] in {"P0", "P1"}
                location, crop = evidence_for_job(detail, job)
                dr = {"id": detail["id"], "priority": detail["priority"]}
                if not crop or detail.get("status") != "confirmed":
                    dr["verdict"] = "blocked_unverifiable"
                    if needed:
                        blocked.append(f"DETAIL_UNVERIFIABLE:{detail['id']}")
                    result["details"].append(dr)
                    continue
                override = job.get("detail_output_bbox_norms", {}).get(detail["id"])
                if (job.get("new_view") and override is None) or (not product_box and override is None):
                    dr["verdict"] = "manual_review_required"
                    if needed:
                        missing.append(f"detail_output_bbox:{detail['id']}")
                    result["details"].append(dr)
                    continue
                output_crop = crop_output_detail(image, product_box or [0,0,1,1], location["bbox_in_product_norm"], override)
                path = base / "review" / "details" / job["id"] / f"{detail['id']}.png"
                ref_path = resolve_project_path(crop["path"], base, "detail crop")
                with Image.open(ref_path) as ref:
                    make_comparison(ref.convert("RGB"), output_crop, path)
                comparisons.append((f"{job['id']} / {detail['id']}", path))
                dr["comparison_path"] = relpath(path, base)
                dr["comparison_sha256"] = sha256_file(path)
                verdict = unpack_verdict(job.get("detail_qa_results", {}).get(detail["id"]))
                dr["verdict"] = verdict or "manual_review_required"
                if needed and verdict != "pass":
                    if verdict == "fail":
                        image_failures.append(f"detail:{detail['id']}")
                        dr["repair_prompt"] = create_repair_prompt(manifest, job, detail, base)
                    else:
                        missing.append(f"detail:{detail['id']}")
                result["details"].append(dr)
        if blocked:
            job["status"], job["blocked_reason"] = "blocked", ";".join(blocked)
            report["summary"]["blocked"] += 1
        elif image_failures:
            if job.get("status") != "generation_repair_needed":
                job["queued_at"] = time.time()
            job["status"] = "generation_repair_needed"
            result["semantic_repair_prompt"] = create_semantic_repair_prompt(job, image_failures, base)
            report["summary"]["repair_needed"] += 1
        elif layout_failures:
            job["status"] = "layout_repair_needed"
            report["summary"]["repair_needed"] += 1
        elif missing:
            job["status"] = "review_pending"
            report["summary"]["review_pending"] += 1
        else:
            job["status"] = "qa_passed"
            job["qa_final_sha256"] = sha256_file(final_path)
            job["qa_fingerprint"] = qa_fingerprint(manifest, job, base)
            report["summary"]["passed"] += 1
        result.update(status=job["status"], blockers=blocked, image_failures=image_failures,
                      layout_failures=layout_failures, missing_reviews=missing)
        if job["status"] in {"qa_passed", "generation_repair_needed", "layout_repair_needed"}:
            job.setdefault("metrics", {}).setdefault("first_review_outcome", job["status"])
        record_timing(job, "qa", started)
        report["jobs"].append(result)
    micro_path = base / "review" / "micro_detail_contact_sheet.png"
    micro_binding = manifest.get("delivery_artifacts", {}).get("review/micro_detail_contact_sheet.png", {})
    micro_cached = (micro_binding.get("inputs") == digest(report) and bool(micro_binding.get("sha256"))
                    and artifact_sha256(manifest, None, base, micro_path) == micro_binding["sha256"])
    if update_overviews and not micro_cached:
        # A changed sibling invalidates the overview, not the unchanged image's
        # actual review. Rebuild only missing, previously reviewed comparisons.
        for result in report["jobs"]:
            job = find_by_id(manifest["jobs"], result["id"])
            for record in result.get("details", []):
                if not record.get("comparison_path"):
                    continue
                path = resolve_project_path(record["comparison_path"], base, "detail comparison")
                if path.is_file():
                    continue
                if artifact_sha256(manifest, job, base, path) != record.get("comparison_sha256"):
                    raise PipelineError(f"{job['id']}: missing comparison has no current retained review evidence")
                detail = find_by_id(manifest["critical_details"], record["id"])
                location, crop = evidence_for_job(detail, job)
                with Image.open(resolve_path(job["final_output"], base)) as image, Image.open(resolve_path(crop["path"], base)) as reference:
                    output_crop = crop_output_detail(image.convert("RGB"), job.get("output_product_bbox_norm") or [0, 0, 1, 1],
                        location["bbox_in_product_norm"], job.get("detail_output_bbox_norms", {}).get(detail["id"]))
                    make_comparison(reference.convert("RGB"), output_crop, path)
                if sha256_file(path) != record["comparison_sha256"]:
                    raise PipelineError(f"{job['id']}: rebuilt comparison differs from the reviewed pixels")
        create_micro_detail_sheet(comparisons, micro_path)
    for result in report["jobs"]:
        job = find_by_id(manifest["jobs"], result["id"])
        if job["id"] in selected:
            job["qa_report_fingerprint"] = digest(result)
    write_json(base / "qa_report.json", report)
    if update_overviews and not micro_cached:
        bind_artifact(manifest, base, "review/micro_detail_contact_sheet.png", digest(report))
    return report


def create_micro_detail_sheet(items: list[tuple[str, Path]], output: Path) -> None:
    cache_path = output.with_suffix(".cache.json")
    inputs = digest({"version": 1, "items": [(label, sha256_file(path)) for label, path in items]})
    try:
        cached = read_json(cache_path)
    except PipelineError:
        cached = {}
    if output.is_file() and cached.get("inputs") == inputs and cached.get("sha256") == sha256_file(output):
        return
    if not items:
        canvas = Image.new("RGB", (1200, 360), "#eef2f5")
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (48, 130),
            "Critical Detail Census complete: no required P0/P1 comparison crops for this run.",
            font=find_font(28),
            fill="#17212b",
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output, format="PNG", optimize=True)
        write_json(cache_path, {"inputs": inputs, "sha256": sha256_file(output)})
        return
    tile_width, tile_height = 840, 500
    columns = 2
    rows = math.ceil(len(items) / columns)
    canvas = Image.new("RGB", (tile_width * columns, tile_height * rows), "#eef2f5")
    draw = ImageDraw.Draw(canvas)
    font = find_font(22)
    for index, (label, path) in enumerate(items):
        with Image.open(path) as opened:
            thumb = ImageOps.contain(opened.convert("RGB"), (tile_width - 32, tile_height - 64))
        column, row = index % columns, index // columns
        x = column * tile_width + (tile_width - thumb.width) // 2
        y = row * tile_height + 48 + (tile_height - 64 - thumb.height) // 2
        canvas.paste(thumb, (x, y))
        draw.text((column * tile_width + 16, row * tile_height + 12), label, font=font, fill="#17212b")
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)
    write_json(cache_path, {"inputs": inputs, "sha256": sha256_file(output)})


def create_final_contact_sheet(manifest: dict[str, Any], base: Path) -> None:
    output = base / "final" / "contact_sheet.png"
    inputs = contact_inputs(manifest, base)
    binding = manifest.get("delivery_artifacts", {}).get("final/contact_sheet.png", {})
    if binding.get("inputs") == inputs and binding.get("sha256") and binding.get("sha256") == artifact_sha256(manifest, None, base, output):
        return
    items: list[tuple[str, Path]] = []
    for job in manifest["jobs"]:
        path = resolve_path(job.get("final_output"), base)
        if path and path.is_file():
            items.append((job["id"], path))
    if not items:
        return
    tile = 420
    label_height = 52
    columns = 4
    rows = math.ceil(len(items) / columns)
    canvas = Image.new("RGB", (tile * columns, (tile + label_height) * rows), "white")
    draw = ImageDraw.Draw(canvas)
    font = find_font(22)
    for index, (label, path) in enumerate(items):
        with Image.open(path) as opened:
            thumb = ImageOps.contain(opened.convert("RGB"), (tile - 24, tile - 24))
        column, row = index % columns, index // columns
        x = column * tile + (tile - thumb.width) // 2
        y = row * (tile + label_height) + (tile - thumb.height) // 2
        canvas.paste(thumb, (x, y))
        draw.text(
            (column * tile + 12, row * (tile + label_height) + tile + 10),
            label,
            font=font,
            fill="#17212b",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)
    bind_artifact(manifest, base, "final/contact_sheet.png", inputs)


def contact_inputs(manifest: dict, base: Path) -> str:
    return digest([{ "id": job["id"], "sha256": sha256_file(path) if path and path.is_file() else None}
                   for job in manifest["jobs"]
                   for path in [resolve_path(job.get("final_output"), base)]])


def bind_artifact(manifest: dict, base: Path, relative: str, inputs: str) -> None:
    manifest.setdefault("delivery_artifacts", {})[relative] = {"sha256": sha256_file(base / relative), "inputs": inputs}


def reported_timings(job: dict) -> list[dict]:
    records = copy.deepcopy(job.get("timings", []))
    for record in records:
        if record.get("stage") == "generation":
            record.setdefault("measurement", "legacy_dispatch_to_ingest_lifecycle")
    return records


@file_hash_context(fresh=True)
def delivery_check(manifest: dict[str, Any], base: Path) -> dict[str, Any]:
    issues = validate_manifest(manifest, base, check_files=True)
    if issues:
        raise PipelineError("Delivery input validation failed:\n- " + "\n- ".join(issues))
    from lc_quality import assess_sources, decide_job
    assess_sources(manifest, base, materialize=not (manifest.get("review_evidence")
        and resolve_delivery_profile(manifest)["name"] == "compact_jpg"))
    contract_report = project_contract_report(manifest)
    issues.extend(contract_report["issues"])
    if not manifest.get("critical_detail_census_completed"):
        issues.append("Critical Detail Census is incomplete")
    report_path = base / "qa_report.json"
    try:
        qa_report = read_json(report_path)
    except PipelineError:
        qa_report = {}
        issues.append("Current QA report is missing or invalid")
    results = {r.get("id"): r for r in qa_report.get("jobs", [])}
    for job in manifest.get("jobs", []):
        if not job.get("required", True):
            continue
        decision = decide_job(manifest, job)
        issues.extend(f"{job['id']}: current source gate: {issue}" for issue in decision["blocked_reasons"])
        if decision.get("recommended_mode") != job["render_mode"]:
            issues.append(f"{job['id']}: current processing mode changed")
        if job.get("status") != "qa_passed":
            issues.append(f"{job.get('id')}: status is {job.get('status')}, not qa_passed")
            continue
        path = resolve_project_path(job.get("final_output"), base, f"jobs[{job['id']}].final_output")
        if path is None or not path.is_file():
            issues.append(f"{job['id']}: final output is missing")
            continue
        if job.get("qa_final_sha256") != sha256_file(path):
            issues.append(f"{job['id']}: final output changed after QA")
        if job.get("qa_fingerprint") != qa_fingerprint(manifest, job, base):
            issues.append(f"{job['id']}: inputs, review verdicts or rules changed after QA")
        result = results.get(job["id"], {})
        if result.get("status") != "qa_passed" or digest(result) != job.get("qa_report_fingerprint"):
            issues.append(f"{job['id']}: QA report is stale or modified")
        for detail in result.get("details", []):
            if detail.get("comparison_path"):
                comparison = resolve_project_path(detail["comparison_path"], base, "detail comparison")
                if not detail.get("comparison_sha256") or artifact_sha256(manifest, job, base, comparison) != detail.get("comparison_sha256"):
                    issues.append(f"{job['id']}: detail comparison missing or changed: {detail.get('id')}")
        if (requires_visual_design(job)
                and job.get("visual_design_review_context") != visual_design_context(manifest, job, base)):
            issues.append(f"{job['id']}: visual design review is not bound to the current layout and style selection")
        if design_reference_issue(job):
            issues.append(f"{job['id']}: {design_reference_issue(job)}; design reference resolution still needs input")
        if resolve_text_mode(job) == "model_native":
            issues.extend(f"{job['id']}: {issue}" for issue in native_text_review_issues(job, job.get("model_text_review")))
            if job.get("model_text_review_context") != native_text_context(manifest, job, base):
                issues.append(f"{job['id']}: model text review is not bound to the current image and copy")
        if has_panel_sources(job):
            issues.extend(f"{job['id']}: {issue}" for issue in panel_review_issues(panel_contracts(manifest, job, base), job.get("panel_reviews")))
            if job.get("panel_review_context") != panel_review_context(manifest, job, base):
                issues.append(f"{job['id']}: panel review is not bound to current sources, crop and layout")
        if mobile_preview_required(job) and not mobile_preview_is_current(job, base, manifest):
            issues.append(f"{job['id']}: mobile preview is missing or changed since review")
        issues.extend(f"{job['id']}: {v}" for v in check_export(job, path))
    for relative in ("qa_report.json", "final/contact_sheet.png", "review/micro_detail_contact_sheet.png"):
        path = base / relative
        actual_sha = sha256_file(path) if relative == "qa_report.json" and path.is_file() else artifact_sha256(manifest, None, base, path)
        if not actual_sha:
            issues.append(f"required delivery artifact missing: {relative}")
        elif relative != "qa_report.json":
            binding = manifest.get("delivery_artifacts", {}).get(relative, {})
            expected = digest(qa_report) if relative.startswith("review/") else contact_inputs(manifest, base)
            if binding.get("sha256") != actual_sha or binding.get("inputs") != expected:
                issues.append(f"required delivery artifact stale or modified: {relative}")
    result = {"schema_version": SCHEMA_VERSION, "project_id": manifest.get("project_id"),
              "ready": not issues, "issues": issues, "policy_version": POLICY_VERSION,
              "project_contracts": contract_report,
              "metrics": {j["id"]: {"model_attempts": j.get("metrics", {}).get("model_dispatches", j.get("attempts", 0)), "quality_repairs": j.get("quality_repairs", 0),
                                      "timings": reported_timings(j), "local": j.get("metrics", {})} for j in manifest.get("jobs", [])},
              "timing_definitions": {"generation": "Dispatch-to-ingest lifecycle; includes orchestration, not model execution time",
                                     "queue": "Prepared/queued to dispatched", "tool": "Explicit tool_started to tool_returned events",
                                     "handoff": "Explicit tool_returned to ingested", "ingest": "Local artifact validation and binding",
                                     "review": "Review packet prepared to submitted"}}
    reviewed = [j for j in manifest["jobs"] if j.get("metrics", {}).get("first_review_outcome")]
    result["performance"] = {"reviewed_jobs": len(reviewed),
                             "first_pass_rate": sum(j["metrics"]["first_review_outcome"] == "qa_passed" for j in reviewed)/len(reviewed) if reviewed else None,
                             "model_repair_rate": sum(j.get("quality_repairs", 0) > 0 for j in reviewed)/len(reviewed) if reviewed else None}
    write_json(base / "delivery_report.json", result)
    if issues:
        raise PipelineError("Delivery gate failed:\n- " + "\n- ".join(issues))
    return result


def transition_job(manifest: dict[str, Any], job_id: str, next_status: str,
                   reason: str | None, base: Path | None = None, *, retry_after_seconds=None) -> None:
    from lc_scheduler import (adaptive, bind_attempt, record_failure, retry_after,
                              require_capacity, source_dispatch_decision)
    retry_after(retry_after_seconds)
    if retry_after_seconds is not None and (next_status != "pending" or not reason):
        raise PipelineError("retry_after_seconds requires a failed attempt returning to pending with a reason")
    job = find_by_id(manifest["jobs"], job_id)
    if job is None:
        raise PipelineError(f"Unknown job: {job_id}")
    current = job.get("status", "pending")
    if next_status not in VALID_JOB_STATUS or next_status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise PipelineError(f"Invalid transition: {current} -> {next_status}")
    if next_status == "generating":
        if required_design_unresolved(job):
            raise PipelineError("Required design reference is missing or changed; resolve it before generation")
        if is_hold(job):
            raise PipelineError(f"Job {job_id} is on HOLD and excluded from image-model dispatch")
        if job["render_mode"] == "pixel_composite":
            raise PipelineError("pixel_composite uses the local compose command, not an image-model call")
        if not job.get("prompt_hash"):
            raise PipelineError(f"Job {job_id} has not been prepared")
        if manifest.get("generation_gate", {}).get("status") != "open":
            raise PipelineError(f"Generation gate is closed: {manifest.get('generation_gate', {})}")
        contract_report = project_contract_report(manifest)
        if not contract_report["passed"]:
            raise PipelineError("Project design/copy preflight failed: " + "; ".join(contract_report["issues"]))
        if base is None:
            raise PipelineError("base is required to verify current source evidence before generation")
        errors = validate_manifest(manifest, base)
        if errors:
            raise PipelineError("Invalid generation inputs:\n- " + "\n- ".join(errors))
        if not manifest.get("critical_detail_census_completed") or manifest.get("shared_blockers"):
            raise PipelineError("Shared product evidence changed; run prepare before generation")
        decision = source_dispatch_decision(manifest, job, base)
        if decision["blocked_reasons"] or decision.get("recommended_mode") != job["render_mode"]:
            raise PipelineError("Current source evidence or processing mode requires review: " + ";".join(decision["blocked_reasons"]))
        if any(a.get("status") == "started" for a in job.get("title_effect_attempts", [])):
            raise PipelineError("An active local title edit must return before replacing its product base")
        try:
            require_capacity(manifest, job, exclude_product=job_id)
        except ValueError as exc:
            raise PipelineError(str(exc)) from exc
        if base is not None and generation_fingerprint(manifest, job, base) != job["prompt_hash"]:
            raise PipelineError("Generation inputs changed; run prepare before dispatch")
        if manifest.get("style_contract") and resolve_text_mode(job) == "local_overlay" and has_marketing_text(job):
            binding = job.get("typography_dispatch_binding", {})
            if binding.get("passed") is not True or binding.get("inputs") != typography_dispatch_fingerprint(manifest, job, base):
                raise PipelineError("Typography preflight is missing or stale; run prepare before dispatch")
        history = job.get("generation_attempts", [])
        repair_count = max(job.get("quality_repairs", 0),
                           sum(a.get("kind") == "quality_repair" for a in history))
        job["quality_repairs"] = repair_count
        repair_requested = current in {"generation_repair_needed", "repair_needed"} or job.get("pending_attempt_kind") == "quality_repair"
        attempt_kind = "initial"
        if repair_requested:
            repairs = repair_count+1
            if repairs > manifest.get("max_quality_repairs", 1):
                job["status"], job["blocked_reason"] = "blocked", "QUALITY_REPAIR_LIMIT_REACHED"
                return
            job["quality_repairs"] = repairs
            job["repair_transient_attempts"] = 0
            attempt_kind = "quality_repair"
        elif job.get("repair_in_progress"):
            retries = job.get("repair_transient_attempts", 0)+1
            if retries > manifest.get("max_transient_retries", 2):
                job["status"], job["failed_reason"] = "failed", "REPAIR_TRANSIENT_RETRY_LIMIT_REACHED"
                return
            job["repair_transient_attempts"] = retries
            attempt_kind = "transient_retry"
        else:
            # A completed image can start a new requested generation, while
            # consecutive failed dispatches retain their retry budget.
            trailing = 0
            for previous_attempt in reversed(history):
                if previous_attempt.get("status") == "ingested" or previous_attempt.get("kind") == "quality_repair":
                    break
                trailing += 1
            if not history:
                trailing = job.get("attempts", 0)
            if trailing >= 1+manifest.get("max_transient_retries", 2):
                job["status"], job["failed_reason"] = "failed", "TRANSIENT_RETRY_LIMIT_REACHED"
                return
            job["attempts"] = job.get("attempts", 0)+1
            attempt_kind = "transient_retry" if trailing else "initial"
        job.pop("pending_attempt_kind", None)
        job["repair_in_progress"] = repair_requested or job.get("repair_in_progress", False)
        job.setdefault("metrics", {})["model_dispatches"] = job.get("metrics", {}).get("model_dispatches", 0) + 1
        job["attempt_prompt_hash"] = job["prompt_hash"]
        job["generation_started_at"] = time.time()
        job["active_attempt_id"] = uuid.uuid4().hex
        attempt = {"id": job["active_attempt_id"], "prompt_hash": job["prompt_hash"], "kind": attempt_kind,
                   "dispatched_at": job["generation_started_at"], "status": "dispatched"}
        bind_attempt(manifest, attempt)
        if manifest.get("style_contract") or manifest.get("review_dependency_version") == 2:
            geometry = generation_geometry(job)
            job["generation_geometry_lock"] = copy.deepcopy(geometry)
            attempt["geometry"] = copy.deepcopy(geometry)
        if job.get("queued_at") is not None:
            attempt["queued_at"] = job["queued_at"]
            job.setdefault("timings", []).append({"stage": "queue", "seconds": round(max(0, job["generation_started_at"]-job["queued_at"]), 4),
                                                   "cached": False, "attempt_id": attempt["id"]})
        job.setdefault("generation_attempts", []).append(attempt)
        job.pop("queued_at", None)
        clear_reviews(job, image_changed=True)
        for key in ("generated_prompt_hash", "bound_raw_sha256", "final_prompt_hash", "final_sha256", "rendered_layout_hash", "exported_hash"):
            job.pop(key, None)
    if next_status == "generated":
        if current != "generating":
            # This only resumes deterministic stages; it cannot admit a new raw file.
            if not job.get("generated_prompt_hash"):
                raise PipelineError("No generated image exists; a review cannot fabricate one")
        else:
            if job.get("attempt_prompt_hash") != job.get("prompt_hash"):
                raise PipelineError("Output belongs to an old prompt; return to pending")
            if base is None:
                raise PipelineError("base is required to bind the generated file")
            if generation_fingerprint(manifest, job, base) != job["attempt_prompt_hash"]:
                raise PipelineError("Output belongs to changed generation inputs; return to pending")
            path = resolve_project_path(job.get("raw_output"), base, "raw_output")
            if path is None or not path.is_file():
                raise PipelineError("Save the model output at raw_output before marking generated")
            job["generated_prompt_hash"] = job["prompt_hash"]
            job["bound_raw_sha256"] = sha256_file(path)
            job["repair_in_progress"] = False
            if not adaptive(manifest):
                manifest.setdefault("network_health", {})["consecutive_timeouts"] = 0
            job.setdefault("timings", []).append({"stage": "generation", "seconds": round(time.time()-job.get("generation_started_at", time.time()), 4),
                                                   "cached": False, "measurement": "dispatch_to_ingest_lifecycle"})
    job["status"] = next_status
    if reason:
        job["status_reason"] = reason
        if next_status == "pending":
            job["queued_at"] = time.time()
            attempt = next((a for a in job.get("generation_attempts", [])
                            if a.get("id") == job.get("active_attempt_id")), None)
            if current == "generating" or not adaptive(manifest):
                record_failure(manifest, attempt, reason, retry_after_seconds=retry_after_seconds)


def prepare(manifest: dict[str, Any], base: Path, job_ids: Iterable[str] | None = None) -> None:
    from lc_stage_timing import record_batch_stage
    selected = job_selection(manifest, job_ids)
    started = time.perf_counter()
    _prepare_impl(manifest, base, selected)
    record_batch_stage(manifest, selected, "planning", started=started,
        measurement="local_prepare_validation_reference_preflight_and_prompt_planning",
        includes=["reference_compile"], external_agent_planning_seconds=None,
        external_agent_planning_measurement="unavailable_no_external_planning_events")


def _prepare_impl(manifest: dict[str, Any], base: Path, job_ids: Iterable[str] | None = None) -> None:
    selected = job_selection(manifest, job_ids)
    for job in manifest["jobs"]:
        if job["id"] in selected:
            if job.get("status") in {"generation_repair_needed", "repair_needed"}:
                job["pending_attempt_kind"] = "quality_repair"
            bind_project_job(manifest, job)
    errors = validate_manifest(manifest, base, check_files=True)
    if errors:
        raise PipelineError("Manifest validation failed:\n- " + "\n- ".join(errors))
    from lc_layout import layout_geometry
    selected = job_selection(manifest, job_ids)
    from lc_style_reference import prepare_design_briefs
    from lc_stage_timing import record_batch_stage
    reference_started = time.perf_counter()
    reference_result = prepare_design_briefs(manifest, base, selected)
    # Instrument the workflow boundary, preserving the standalone compiler's
    # byte-identical no-op behavior. No agent-side analysis time is observable.
    if isinstance(reference_result, dict):
        participants = set(reference_result["changed"] + reference_result["cached"] + reference_result["needs_input"])
        if participants:
            record_batch_stage(manifest, participants, "reference_compile", started=reference_started,
                cached=bool(reference_result["cached"]) and not reference_result["changed"] and not reference_result["needs_input"],
                measurement="local_reference_index_read_verify_select_and_brief_compile",
                external_visual_analysis_seconds=None,
                external_visual_analysis_measurement="unavailable_no_external_analysis_events")
    product = manifest.get("product_truth", {}).get("product", "").strip()
    if product and any(j["id"] in selected and j.get("layout", {}).get("version", 1) == 2 for j in manifest["jobs"]):
        relative = manifest.get("style_reference_selection_path", "style_reference_selection.json")
        selection_path = resolve_project_path(relative, base, "style_reference_selection_path")
        from lc_style_reference import prepare_selection
        # The selector reuses valid records, while checking that chosen external
        # samples still exist. Missing optional style inputs do not close the gate.
        prepare_selection({"product": product,
                           "category": manifest.get("category") or manifest.get("product_truth", {}).get("category", ""),
                           "intents": [j["selling_job"] for j in manifest["jobs"] if j.get("selling_job", "").strip()]}, selection_path)
        manifest["style_reference_selection_path"] = relpath(selection_path, base)
    for job in manifest["jobs"]:
        if job["id"] not in selected:
            continue
        reason = str(job.get("blocked_reason", ""))
        if job.get("status") == "blocked" and reason.startswith(DERIVED_BLOCK_PREFIXES):
            job["status"] = "pending"
            job.pop("blocked_reason", None)
        if job.get("layout") and job.get("placement_mode", "template") == "template" and not job.get("generation_geometry_lock") and resolve_text_mode(job) != "model_native":
            job["target_product_bbox_norm"] = layout_geometry(job)["product_region_norm"]
        if "text_mode" in job:
            planned_job = copy.deepcopy(job)
            planned_job.pop("model_text_review", None)
            copy_errors = claim_issues(manifest, planned_job)
            if copy_errors:
                job["status"], job["blocked_reason"] = "blocked", "DESIGN_COPY:" + ";".join(copy_errors)
        if job.get("status") == "pending" and not is_hold(job):
            job.setdefault("queued_at", time.time())
        for timing in job.get("timings", []):
            if timing.get("stage") == "generation":
                timing.setdefault("measurement", "legacy_dispatch_to_ingest_lifecycle")
    contract_report = preflight_project_contracts(manifest, base, [j for j in manifest["jobs"] if j["id"] in selected])
    preflight(manifest, base, selected)
    extract_detail_references(manifest, base, selected)
    compile_prompts(manifest, base, selected)
    for job in manifest["jobs"]:
        if job["id"] in selected:
            invalidate_visual_design_review(manifest, job, base)
            if required_design_unresolved(job) and job.get("status") in {"pending", "generation_repair_needed"}:
                job["status"], job["blocked_reason"] = "blocked", "DESIGN_REFERENCE_REQUIRED:resolve the explicit reference before dispatch"
    if contract_report["passed"]:
        typography_jobs = [j["id"] for j in manifest["jobs"] if j["id"] in selected
                           and j.get("status") in {"pending", "generation_repair_needed"}
                           and j.get("render_mode") != "pixel_composite" and not is_hold(j)]
        if typography_jobs:
            fit_report = preflight_layout_fit(manifest, base, typography_jobs)
            contract_report["issues"].extend(fit_report["issues"])
            for result in fit_report["jobs"]:
                job = find_by_id(manifest["jobs"], result["id"])
                job["typography_dispatch_binding"] = {"passed": result["passed"],
                    "inputs": typography_dispatch_fingerprint(manifest, job, base)}
    global_reasons = list(manifest.get("shared_blockers", []))
    global_reasons.extend(contract_report["issues"])
    if not manifest.get("critical_detail_census_completed"):
        global_reasons.append("CENSUS_INCOMPLETE: inspect all product sources and record P0/P1 visibility")
    manifest["generation_gate"] = {"status": "closed" if global_reasons else "open",
        "shared_reasons": global_reasons,
        "blocked_required_jobs": [j["id"] for j in manifest["jobs"] if j.get("required", True) and j["status"] == "blocked"]}
    write_json(base / "execution_plan.json", execution_plan(manifest))


def execution_plan(manifest: dict) -> dict:
    ready = [j for j in manifest["jobs"] if j.get("status") in {"pending", "generation_repair_needed"}
             and not is_hold(j) and not required_design_unresolved(j)]
    def risk(job):
        explicit = job.get("risk_priority")
        if isinstance(explicit, (int, float)):
            return explicit
        return (3 if job.get("new_view") else 0) + (2 if job["render_mode"] == "reference_generate" else 0) + (1 if has_text(job) else 0) + len(job.get("required_details", []))
    ready.sort(key=risk, reverse=True)
    # An anchor is tied to its generation fingerprint, not its fixed slot name.
    anchor = manifest.get("anchor_job_id")
    previous_anchor = find_by_id(manifest["jobs"], anchor) if anchor else None
    if (previous_anchor is None or is_hold(previous_anchor) or required_design_unresolved(previous_anchor)
            or previous_anchor.get("status") in {"blocked", "failed"}) and ready:
        anchor = ready[0]["id"]
        manifest["anchor_job_id"] = anchor
    anchor_job = find_by_id(manifest["jobs"], anchor) if anchor else None
    anchor_passed = bool(anchor_job and anchor_job.get("status") == "qa_passed")
    allowed = ready if anchor_passed else [j for j in ready if j["id"] == anchor]
    if manifest.get("generation_gate", {}).get("status") != "open":
        allowed = []
    from lc_scheduler import state as scheduler_state
    scheduling = scheduler_state(manifest)
    models = [j for j in allowed if j["render_mode"] != "pixel_composite"][:scheduling["model_capacity"]]
    local = [j for j in allowed if j["render_mode"] == "pixel_composite"]
    dispatched = {j["id"] for j in models + local}
    return {"anchor": anchor, "anchor_passed": anchor_passed, "concurrency": manifest.get("concurrency", 2),
            "scheduler": scheduling,
            "dispatch": [{"id": j["id"], "action": "compose" if j["render_mode"] == "pixel_composite" else "image_gen",
                          "prompt_hash": j.get("prompt_hash"), "prompt_file": j.get("prompt_file"),
                          "generation_reference_paths": list(j.get("generation_reference_paths") or []),
                          "risk": risk(j)} for j in allowed if j["id"] in dispatched],
            "deterministic_resume": [j["id"] for j in manifest["jobs"] if j.get("status") in {"generated", "layout_repair_needed", "export_repair_needed"}],
            "review_pending": [j["id"] for j in manifest["jobs"] if j.get("status") == "review_pending"],
            "blocked": [{"id": j["id"], "reason": j.get("blocked_reason")} for j in manifest["jobs"] if j.get("status") == "blocked"],
            "reused": [j["id"] for j in manifest["jobs"] if j.get("status") == "qa_passed"]}


def init_project(project_dir: Path, project_id: str, force: bool = False, *,
                 listing_aspect: str = "1:1", short_edge: int = 2000,
                 marketplace: str = "", language: str = "", include_a_plus: bool = False,
                 a_plus_canvas: list[int] | None = None, a_plus_module: str | None = None,
                 a_plus_count: int = 6) -> Path:
    if not isinstance(project_id, str) or not SAFE_ID.fullmatch(project_id):
        raise PipelineError("Invalid project_id")
    if not isinstance(marketplace, str) or not marketplace.strip() or not isinstance(language, str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
        raise PipelineError("A nonempty marketplace and BCP-47 language tag are required")
    if type(short_edge) is not int:
        raise PipelineError("short_edge must be an integer")
    if listing_aspect not in {"1:1", "1:1.3"} or short_edge < 1600:
        raise PipelineError("Choose 1:1 or 1:1.3 and short_edge >=1600")
    if listing_aspect == "1:1.3" and short_edge % 10:
        raise PipelineError("Portrait short edge must be a multiple of 10 for an exact 1:1.3 ratio")
    canvas = [short_edge, short_edge if listing_aspect == "1:1" else short_edge*13//10]
    if max(canvas) > 10000:
        raise PipelineError("Canvas sides may not exceed 10000 pixels")
    if include_a_plus and (not a_plus_canvas or not a_plus_module):
        raise PipelineError("A+ requires both --a-plus-module and --a-plus-canvas")
    if type(a_plus_count) is not int or not 1 <= a_plus_count <= 20:
        raise PipelineError("a_plus_count must be an integer from 1 to 20")
    if include_a_plus and (not isinstance(a_plus_canvas, list) or len(a_plus_canvas) != 2
            or any(type(v) is not int or not 1 <= v <= 10000 for v in a_plus_canvas)):
        raise PipelineError("A+ canvas requires two positive integers, each <=10000")
    template = read_json(SCRIPT_DIR.parent / "assets" / "project_manifest.template.json")
    path = project_dir / "project_manifest.json"
    if path.exists():
        if not force:
            raise PipelineError(f"Refusing to overwrite existing manifest: {path}")
        backup = path.with_name(f"project_manifest.backup-{time.time_ns()}.json")
        backup.write_bytes(path.read_bytes())
    project_dir.mkdir(parents=True, exist_ok=True)
    from lc_scheduler import default_policy as default_scheduler_policy
    template.update(project_id=project_id, marketplace=marketplace, language=language,
                    scheduler_policy=default_scheduler_policy(), concurrency=2,
                    listing_profile={"aspect": listing_aspect, "short_edge": short_edge},
                    design_template_policy={"version": 1, "mode": "auto"},
                    style_contract=default_style_contract(),
                    delivery_profile={"name": "compact_jpg", "jpeg_quality": 92},
                    review_dependency_version=2)
    for job in template["jobs"]:
        job["canvas"] = list(canvas)
        job["generation_dependency_version"] = 2
        if job.get("kind") == "main":
            job["text_mode"] = "none"
        else:
            job["text_mode"] = "local_overlay"
            layout = job.setdefault("layout", {})
            # An init scaffold is not an authored recipe override. Let the
            # selected template supply this default after product planning.
            layout.update(version=3, text_groups=[])
            layout.pop("recipe", None)
            layout.pop("headline", None)
            layout.pop("body", None)
    if include_a_plus:
        for index in range(a_plus_count):
            extra = copy.deepcopy(template["jobs"][2])
            identifier = f"{8+index:02d}_a_plus"
            extra.update(id=identifier, kind="a_plus", a_plus_module=a_plus_module, canvas=list(a_plus_canvas),
                         raw_output=f"raw/{identifier}.png", final_output=f"final/{identifier}.jpg")
            template["jobs"].append(extra)
    for job in template["jobs"]:
        bind_project_job(template, job)
    write_json(path, template)
    for directory in ("source", "raw", "final", "review", "prompts", "detail_refs", "repairs"):
        (project_dir / directory).mkdir(exist_ok=True)
    return path


def migrate_project(path: Path, marketplace: str | None = None, language: str | None = None) -> Path:
    manifest = read_json(path)
    if manifest.get("schema_version") == 3:
        return path
    if manifest.get("schema_version") != 2:
        raise PipelineError("Only v2 projects can be migrated")
    backup = path.with_name(f"project_manifest.v2-{time.time_ns()}.json")
    backup.write_bytes(path.read_bytes())
    manifest.update(schema_version=3, marketplace=marketplace or manifest.get("marketplace", ""),
                    language=language or manifest.get("language", ""), migration={"from": 2, "backup": backup.name, "requires_v3_review": True})
    for ref in manifest["references"]:
        ref["quality_review"] = {"clarity": "unknown", "evidence": "unknown", "defects": [], "notes": "Review source region for V3"}
    for job in manifest["jobs"]:
        job["status"] = "pending"
        job["source_assessment"] = {"scene_fit": "unknown", "evidence": "unknown", "degradation": "unknown", "reason": "V3 source/target review required"}
        job["ai_disclosure"] = {"human_source": "unknown", "notes": "Review the actual visual before export"}
        old = job.pop("text_overlays", [])
        job["legacy_text_overlays"] = old
        if old:
            job["layout"] = {"template": "scene", "theme": "neutral", "headline": old[0].get("text", ""),
                             "body": " ".join(o.get("text", "") for o in old[1:]), "items": []}
        job["semantic_qa_results"], job["policy_qa_results"], job["detail_qa_results"] = {}, {}, {}
        for key in ("fingerprints", "prompt_hash", "attempt_prompt_hash", "generated_prompt_hash", "final_prompt_hash", "final_sha256", "qa_final_sha256", "qa_fingerprint"):
            job.pop(key, None)
    write_json(path, manifest)
    return path


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--json", action="store_true", help="Emit exactly one JSON result on stdout")
    subs = command.add_subparsers(dest="command", required=True)
    init = subs.add_parser("init", help="Create a V3 project; seven Listing jobs, A+ only when requested")
    init.add_argument("--project-dir", type=Path, required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--force", action="store_true")
    init.add_argument("--listing-aspect", choices=["1:1", "1:1.3"], default="1:1")
    init.add_argument("--short-edge", type=int, default=2000)
    init.add_argument("--marketplace", required=True)
    init.add_argument("--language", required=True)
    init.add_argument("--include-a-plus", action="store_true")
    init.add_argument("--a-plus-module")
    init.add_argument("--a-plus-canvas", nargs=2, type=int)
    init.add_argument("--a-plus-count", type=int, default=6)
    subs.add_parser("doctor", help="Verify pinned local rendering runtime and fonts")
    for name in ("validate", "prepare", "plan", "compose", "postprocess", "qa", "finalize", "delivery-check", "deliver", "migrate"):
        sub = subs.add_parser(name)
        sub.add_argument("--manifest", type=Path, required=True)
        if name == "validate": sub.add_argument("--skip-file-check", action="store_true")
        if name in {"prepare", "plan", "compose", "postprocess", "qa", "finalize"}:
            sub.add_argument("--jobs", nargs="+", help="Only process these job ids; preserve unrelated job outputs and reviews")
        if name == "postprocess": sub.add_argument("--force", action="store_true")
        if name == "plan": sub.add_argument("--tool-capacity", type=int, choices=range(1, 5))
        if name == "migrate":
            sub.add_argument("--marketplace")
            sub.add_argument("--language")
    transition = subs.add_parser("transition")
    transition.add_argument("--manifest", type=Path, required=True)
    transition.add_argument("--job", required=True)
    transition.add_argument("--status", required=True)
    transition.add_argument("--reason")
    transition.add_argument("--retry-after-seconds", type=float)
    dependencies = subs.add_parser("migrate-dependencies", help="Verify a legacy bound artifact before adopting scoped per-image dependencies")
    dependencies.add_argument("--manifest", type=Path, required=True)
    dependencies.add_argument("--source-manifest", type=Path, required=True)
    dependencies.add_argument("--source-kind", choices=["historical_snapshot", "reconstructed_verified_dependency_view"], default="historical_snapshot")
    dependencies.add_argument("--allow-project-fork", action="store_true", help="Explicitly allow a retained-source project fork; all artifact and per-image input proofs still apply")
    dependencies.add_argument("--jobs", nargs="+", required=True)
    ingest = subs.add_parser("ingest", help="Immediately bind a completed model artifact and release its generation slot")
    ingest.add_argument("--manifest", type=Path, required=True)
    ingest.add_argument("--job", required=True)
    ingest.add_argument("--artifact", type=Path, required=True)
    ingest.add_argument("--attempt-id", required=True)
    ingest.add_argument("--tool-returned-at", type=float)
    event = subs.add_parser("attempt-event", help="Record an actual tool start/return timestamp, independent of ingestion")
    event.add_argument("--manifest", type=Path, required=True)
    event.add_argument("--job", required=True)
    event.add_argument("--attempt-id", required=True)
    event.add_argument("--event", choices=["tool_started", "tool_returned"], required=True)
    event.add_argument("--timestamp", type=float)
    review = subs.add_parser("review-prepare", help="Prepare pixels, annotations and an unsigned review packet without exporting")
    review.add_argument("--manifest", type=Path, required=True)
    review_jobs = review.add_mutually_exclusive_group()
    review_jobs.add_argument("--job")
    review_jobs.add_argument("--jobs", nargs="+", help="Prepare selected ready jobs; omit to prepare all ready jobs")
    review.add_argument("--annotations", type=Path)
    review.add_argument("--force", action="store_true", help="Replace the package even when its bound inputs are unchanged")
    submit = subs.add_parser("review-submit", help="Bind explicit judgments to one current review packet and finish that job")
    submit.add_argument("--manifest", type=Path, required=True)
    submit.add_argument("--packet", type=Path, required=True, help="Single packet, list, or map keyed by job id")
    for name in ("title-effect-prepare", "title-effect-event", "title-effect-ingest"):
        effect = subs.add_parser(name, help="Prepare or bind an optional local title edit; never invoke a model")
        effect.add_argument("--manifest", type=Path, required=True)
        effect.add_argument("--job", required=True)
        if name == "title-effect-event":
            effect.add_argument("--event", choices=["tool_started", "tool_returned", "failed"], required=True)
            effect.add_argument("--attempt-id", required=True)
            effect.add_argument("--kind", choices=["initial", "quality_repair", "transient_retry"], default="initial")
            effect.add_argument("--timestamp", type=float)
            effect.add_argument("--reason")
            effect.add_argument("--retry-after-seconds", type=float)
        elif name == "title-effect-ingest":
            effect.add_argument("--artifact", type=Path, required=True)
            effect.add_argument("--mask", type=Path, required=True)
            effect.add_argument("--attempt-id", required=True)
    for sub in subs.choices.values():
        sub.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return command


@file_hash_context(fresh=True)
def run_command(args) -> int:
    manifest = manifest_path = None
    result = None
    json_mode = getattr(args, "json", False)
    def emit(value, *, ok=True):
        if json_mode:
            payload = dict(value) if isinstance(value, dict) else {"result": str(value)}
            payload.update(ok=ok, command=args.command)
            if manifest_path is not None:
                payload["manifest"] = str(manifest_path)
            print(json.dumps(payload, ensure_ascii=False))
        elif isinstance(value, dict):
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            print(value)
    try:
        if args.command == "doctor":
            from lc_layout import doctor
            result = doctor()
            emit(result, ok=bool(result.get("passed")))
            return 0 if result.get("passed") else 2
        if args.command == "init":
            manifest_path = init_project(args.project_dir.resolve(), args.project_id, args.force,
                  listing_aspect=args.listing_aspect, short_edge=args.short_edge, marketplace=args.marketplace,
                  language=args.language, include_a_plus=args.include_a_plus,
                  a_plus_canvas=args.a_plus_canvas, a_plus_module=args.a_plus_module, a_plus_count=args.a_plus_count)
            emit(manifest_path)
            return 0
        manifest_path = args.manifest.expanduser().resolve()
        if args.command == "migrate":
            emit(migrate_project(manifest_path, args.marketplace, args.language))
            return 0
        base = manifest_path.parent
        manifest = read_json(manifest_path)
        if args.command == "validate":
            errors = validate_manifest(manifest, base, check_files=not args.skip_file_check)
            if errors:
                raise PipelineError("Manifest validation failed:\n- " + "\n- ".join(errors))
            emit({"valid": True} if json_mode else "manifest_valid")
            return 0
        errors = validate_manifest(manifest, base)
        if errors:
            manifest = None  # Invalid input is never rewritten by the error handler.
            raise PipelineError("Manifest validation failed:\n- " + "\n- ".join(errors))
        if args.command == "prepare":
            prepare(manifest, base, args.jobs)
        elif args.command == "plan":
            if getattr(args, "tool_capacity", None) is not None:
                from lc_scheduler import set_tool_capacity
                set_tool_capacity(manifest, args.tool_capacity)
            prepare(manifest, base, args.jobs)
            result = execution_plan(manifest)
        elif args.command in {"postprocess", "compose"}:
            aspect_safe_postprocess(manifest, base, force=getattr(args, "force", False), job_ids=args.jobs)
        elif args.command == "qa":
            quality_assurance(manifest, base, args.jobs, update_overviews=False)
        elif args.command == "finalize":
            aspect_safe_postprocess(manifest, base, job_ids=args.jobs)
            whole_project = job_selection(manifest, args.jobs) == {job["id"] for job in manifest["jobs"]}
            quality_assurance(manifest, base, args.jobs, update_overviews=whole_project)
            if whole_project:
                create_final_contact_sheet(manifest, base)
        elif args.command == "delivery-check":
            result = delivery_check(manifest, base)
        elif args.command == "deliver":
            from lc_delivery import compact_project, prepare_delivery_directory
            profile = resolve_delivery_profile(manifest)
            if profile["name"] == "compact_jpg":
                compaction = compact_project(manifest, base, manifest_path=manifest_path,
                    delivery_check_fn=delivery_check, qa_fingerprint_fn=qa_fingerprint,
                    stage_fingerprints_fn=current_fingerprints)
                result = compaction.pop("delivery_result")
                result["compaction"] = compaction
            else:
                result = delivery_check(manifest, base)
            result.update(prepare_delivery_directory(manifest, base, delivery_result=result))
            write_json(base / "delivery_report.json", result)
        elif args.command == "transition":
            transition_job(manifest, args.job, args.status, args.reason, base,
                           retry_after_seconds=getattr(args, "retry_after_seconds", None))
            job = find_by_id(manifest["jobs"], args.job)
            result = {"job": args.job, "status": job["status"], "attempt_id": job.get("active_attempt_id"),
                      "prompt_hash": job.get("prompt_hash")}
        elif args.command == "migrate-dependencies":
            from lc_dependencies import migrate_dependencies
            result = migrate_dependencies(manifest, base, read_json(args.source_manifest), args.jobs,
                                          source_kind=args.source_kind, allow_project_fork=args.allow_project_fork)
        elif args.command.startswith("title-effect-"):
            from lc_title_effects import prepare as prepare_effect, attempt_event as effect_event, ingest as ingest_effect
            job = find_by_id(manifest["jobs"], args.job)
            if job is None:
                raise PipelineError("Unknown title effect job")
            bind_project_job(manifest, job)
            if args.command == "title-effect-prepare":
                aspect_safe_postprocess(manifest, base, job_ids=[args.job], export=False)
                result = prepare_effect(manifest, base, job)
            elif args.command == "title-effect-event":
                result = effect_event(manifest, base, job, args.event, attempt_id=args.attempt_id,
                                      kind=args.kind, at=args.timestamp, reason=args.reason,
                                      retry_after_seconds=getattr(args, "retry_after_seconds", None))
            else:
                result = ingest_effect(manifest, base, job, args.artifact, args.mask, attempt_id=args.attempt_id)
                if not result.get("cached"):
                    clear_reviews(job, image_changed=False)
                    job.pop("title_effect_review", None)
                    job["status"] = "generated"
                    job["qa_invalidated_reason"] = "LOCAL_TITLE_EFFECT_CHANGED"
        elif args.command in {"ingest", "attempt-event", "review-prepare", "review-submit"}:
            from lc_workflow import ingest, attempt_event, review_prepare, review_prepare_many, review_submit, review_submit_many
            if args.command == "ingest":
                result = ingest(manifest, base, args.job, args.artifact, args.attempt_id,
                                tool_returned_at=getattr(args, "tool_returned_at", None))
            elif args.command == "attempt-event":
                result = attempt_event(manifest, args.job, args.attempt_id, args.event, args.timestamp)
            elif args.command == "review-prepare":
                annotations = read_json(args.annotations) if args.annotations else None
                result = (review_prepare(manifest, base, args.job, annotations, force=args.force) if args.job
                          else review_prepare_many(manifest, base, args.jobs, annotations, force=args.force))
            else:
                packet = read_json(args.packet)
                result = (review_submit(manifest, base, packet) if isinstance(packet, dict) and isinstance(packet.get("job"), str)
                          else review_submit_many(manifest, base, packet))
        if args.command in {"ingest", "transition"} and getattr(args, "_manifest_lock_timing", None):
            from lc_stage_timing import record_stage
            lock = args._manifest_lock_timing
            target = find_by_id(manifest["jobs"], args.job)
            record_stage(target, "lock_wait", seconds=lock["wait_seconds"], scope="command", command=args.command,
                         measurement="manifest_lock_acquire_wait_excludes_recovery_and_command_execution")
            record_stage(target, "lock_recovery", seconds=lock["recovery_seconds"], scope="command", command=args.command,
                         measurement="pending_transaction_recovery_after_lock_acquired")
        write_json(manifest_path, manifest)
        if json_mode:
            emit(result or {}, ok=not (isinstance(result, dict) and result.get("errors")))
        else:
            if result is not None:
                emit(result)
            print(manifest_path)
        return 2 if isinstance(result, dict) and result.get("errors") else 0
    except (PipelineError, ValueError, OSError) as exc:
        if manifest is not None and manifest_path is not None and args.command not in {"validate", "delivery-check"}:
            write_json(manifest_path, manifest)
        print(str(exc), file=sys.stderr)
        if json_mode:
            emit({"error": str(exc)}, ok=False)
        return 2


def main() -> int:
    args = parser().parse_args()
    from lc_workflow import manifest_lock
    path = getattr(args, "manifest", None)
    if args.command == "init":
        path = args.project_dir / "project_manifest.json"
    if path is None:
        return run_command(args)
    try:
        if args.command in {"prepare", "plan", "compose", "postprocess", "qa", "finalize", "review-prepare", "review-submit", "title-effect-prepare"}:
            from lc_transactions import run_staged_command
            selected = getattr(args, "jobs", None)
            if getattr(args, "job", None):
                selected = [args.job]
            if args.command == "review-prepare" and selected is None:
                # Do not CAS-bind pending/generating jobs merely because this
                # request means "all ready"; their ingestion must remain free.
                with manifest_lock(path.expanduser().resolve()):
                    current = read_json(path.expanduser().resolve())
                    from lc_workflow import review_candidate
                    selected = [job["id"] for job in current["jobs"] if review_candidate(job)]
                if not selected:
                    print(json.dumps({"ok": True, "manifest": str(path.resolve()), "packets": [], "skipped": "no_ready_jobs"}))
                    return 0
            if args.command == "review-submit":
                from lc_workflow import review_packet_map
                with manifest_lock(path.expanduser().resolve()):
                    current = read_json(path.expanduser().resolve())
                    selected = list(review_packet_map(current, read_json(args.packet)))
            def operation(stage_manifest_path):
                staged_args = copy.copy(args)
                staged_args.manifest = stage_manifest_path
                if args.command == "review-prepare" and not args.job:
                    staged_args.jobs = selected
                return run_command(staged_args)
            return run_staged_command(path.expanduser().resolve(), selected, operation, command_name=args.command)
        with manifest_lock(path.expanduser().resolve()) as lock_timing:
            args._manifest_lock_timing = lock_timing
            return run_command(args)
    except (TimeoutError, ValueError, OSError, PipelineError) as exc:
        print(str(exc), file=sys.stderr)
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "command": args.command, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
