#!/usr/bin/env python3
"""Deterministic local pipeline for Lc Amazon Image Studio v2.

The script never calls an image model. It prepares manifests and prompts, extracts
critical-detail references, performs aspect-safe post-processing, and enforces QA
gates around source resolution and micro-detail preservation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, Iterable

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat
except ImportError as exc:  # pragma: no cover - environment-specific failure
    raise SystemExit(
        "Pillow is required. Use the Codex bundled Python runtime or install pillow."
    ) from exc


SCHEMA_VERSION = 2
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
}
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DERIVED_BLOCK_PREFIXES = (
    "SOURCE_",
    "FINE_DETAIL_",
    "RESTORED_MASTER_",
    "DETAIL_UNVERIFIABLE:",
    "DETAIL_VIEW_UNVERIFIABLE:",
)
ALLOWED_TRANSITIONS = {
    "pending": {"pending", "generating", "blocked", "failed"},
    "generating": {"generating", "generated", "pending", "failed", "blocked"},
    "generated": {"generated", "qa_passed", "repair_needed", "blocked", "failed"},
    "qa_passed": {"qa_passed", "pending"},
    "repair_needed": {"repair_needed", "generating", "blocked", "failed"},
    "blocked": {"blocked", "pending"},
    "failed": {"failed", "pending", "blocked"},
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
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def resolve_path(value: str | None, base: Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_enum(value: Any, allowed: set[str], label: str, errors: list[str]) -> None:
    if value not in allowed:
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
    if not all(isinstance(number, (int, float)) and math.isfinite(number) for number in value):
        errors.append(f"{label} must contain finite numbers")
        return
    x, y, width, height = value
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        errors.append(f"{label} must stay inside normalized range 0..1")


def validate_manifest(manifest: dict[str, Any], base: Path, check_files: bool = True) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not manifest.get("project_id"):
        errors.append("project_id is required")
    else:
        validate_id(manifest.get("project_id"), "project_id", errors)
    require_enum(manifest.get("run_mode"), VALID_RUN_MODES, "run_mode", errors)
    require_enum(
        manifest.get("generation_backend"), VALID_BACKENDS, "generation_backend", errors
    )
    concurrency = manifest.get("concurrency")
    if not isinstance(concurrency, int) or not 1 <= concurrency <= 2:
        errors.append("concurrency must be 1 or 2")
    if not isinstance(manifest.get("critical_detail_census_completed", False), bool):
        errors.append("critical_detail_census_completed must be boolean")

    truth = manifest.get("product_truth")
    if not isinstance(truth, dict):
        errors.append("product_truth must be an object")
        truth = {}
    require_enum(
        truth.get("source_quality"), VALID_SOURCE_QUALITY, "product_truth.source_quality", errors
    )
    require_enum(
        truth.get("master_asset_mode"),
        VALID_MASTER_MODES,
        "product_truth.master_asset_mode",
        errors,
    )
    if not isinstance(truth.get("master_confirmed", False), bool):
        errors.append("product_truth.master_confirmed must be boolean")
    for field in ("geometry_lock", "material_lock", "scene_scale_lock"):
        if not isinstance(truth.get(field), dict):
            errors.append(f"product_truth.{field} must be an object")
    safe = truth.get("safe_upscale_ratio", 1.25)
    marginal = truth.get("max_marginal_upscale_ratio", 1.75)
    if not isinstance(safe, (int, float)) or safe <= 1:
        errors.append("product_truth.safe_upscale_ratio must be greater than 1")
    if not isinstance(marginal, (int, float)) or marginal <= safe:
        errors.append("max_marginal_upscale_ratio must be greater than safe_upscale_ratio")

    references = manifest.get("references")
    if not isinstance(references, list) or not references:
        errors.append("references must contain at least one product image")
        references = []
    reference_ids: set[str] = set()
    reference_views: dict[str, str] = {}
    for index, ref in enumerate(references):
        label = f"references[{index}]"
        if not isinstance(ref, dict):
            errors.append(f"{label} must be an object")
            continue
        ref_id = ref.get("id")
        validate_id(ref_id, f"{label}.id", errors)
        if not ref_id or ref_id in reference_ids:
            errors.append(f"{label}.id must be unique and non-empty")
        else:
            reference_ids.add(ref_id)
            reference_views[ref_id] = str(ref.get("view", ""))
        validate_bbox(ref.get("product_bbox_norm"), f"{label}.product_bbox_norm", errors)
        require_enum(
            ref.get("visual_quality", "unknown"),
            VALID_SOURCE_QUALITY,
            f"{label}.visual_quality",
            errors,
        )
        path = resolve_path(ref.get("path"), base)
        if check_files and (path is None or not path.is_file()):
            errors.append(f"{label}.path does not exist: {ref.get('path')!r}")

    detail_ids: set[str] = set()
    details = manifest.get("critical_details", [])
    if not isinstance(details, list):
        errors.append("critical_details must be an array")
        details = []
    for index, detail in enumerate(details):
        label = f"critical_details[{index}]"
        if not isinstance(detail, dict):
            errors.append(f"{label} must be an object")
            continue
        detail_id = detail.get("id")
        validate_id(detail_id, f"{label}.id", errors)
        if not detail_id or detail_id in detail_ids:
            errors.append(f"{label}.id must be unique and non-empty")
        else:
            detail_ids.add(detail_id)
        require_enum(detail.get("priority"), VALID_PRIORITIES, f"{label}.priority", errors)
        require_enum(
            detail.get("evidence_level", "unknown"),
            VALID_EVIDENCE_LEVEL,
            f"{label}.evidence_level",
            errors,
        )
        require_enum(
            detail.get("visual_confirmation", "unknown"),
            VALID_DETAIL_STATUS,
            f"{label}.visual_confirmation",
            errors,
        )
        require_enum(
            detail.get("status", "unknown"), VALID_DETAIL_STATUS, f"{label}.status", errors
        )
        locations = detail.get("locations")
        if not isinstance(locations, list):
            errors.append(f"{label}.locations must be an array")
        else:
            if detail.get("status") == "confirmed" and not locations:
                errors.append(f"{label}.locations is required when status is confirmed")
            for loc_index, location in enumerate(locations):
                loc_label = f"{label}.locations[{loc_index}]"
                reference_id = location.get("reference_id")
                if reference_id not in reference_ids:
                    errors.append(f"{loc_label}.reference_id is unknown")
                elif location.get("view") != reference_views.get(reference_id):
                    errors.append(
                        f"{loc_label}.view must match its reference view "
                        f"{reference_views.get(reference_id)!r}"
                    )
                validate_bbox(
                    location.get("bbox_in_product_norm"),
                    f"{loc_label}.bbox_in_product_norm",
                    errors,
                )
        visibility = detail.get("visibility", {})
        if not isinstance(visibility, dict):
            errors.append(f"{label}.visibility must be an object")
        else:
            for job_id, value in visibility.items():
                require_enum(value, VALID_VISIBILITY, f"{label}.visibility.{job_id}", errors)

    jobs = manifest.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        errors.append("jobs must contain at least one image task")
        jobs = []
    job_ids: set[str] = set()
    for index, job in enumerate(jobs):
        label = f"jobs[{index}]"
        if not isinstance(job, dict):
            errors.append(f"{label} must be an object")
            continue
        job_id = job.get("id")
        validate_id(job_id, f"{label}.id", errors)
        if not job_id or job_id in job_ids:
            errors.append(f"{label}.id must be unique and non-empty")
        else:
            job_ids.add(job_id)
        require_enum(job.get("render_mode"), VALID_RENDER_MODES, f"{label}.render_mode", errors)
        require_enum(job.get("status", "pending"), VALID_JOB_STATUS, f"{label}.status", errors)
        if job.get("kind") not in {"main", "listing", "a_plus"}:
            errors.append(f"{label}.kind must be main, listing, or a_plus")
        if not isinstance(job.get("required", True), bool):
            errors.append(f"{label}.required must be boolean")
        if not isinstance(job.get("requires_fine_detail", False), bool):
            errors.append(f"{label}.requires_fine_detail must be boolean")
        semantic = job.get("semantic_qa_results", {})
        if not isinstance(semantic, dict):
            errors.append(f"{label}.semantic_qa_results must be an object")
        else:
            for key, value in semantic.items():
                if key not in {"geometry", "material", "scene_scale", "components"}:
                    errors.append(f"{label}.semantic_qa_results has unknown check {key!r}")
                verdict = value.get("verdict") if isinstance(value, dict) else value
                if verdict not in VALID_QA_VERDICT:
                    errors.append(
                        f"{label}.semantic_qa_results.{key} verdict must be pass, fail, or not_applicable"
                    )
        policy = job.get("policy_qa_results", {})
        if not isinstance(policy, dict):
            errors.append(f"{label}.policy_qa_results must be an object")
        else:
            for key, value in policy.items():
                if key not in {"main_product_only", "claims", "competitor_copy", "text_readability"}:
                    errors.append(f"{label}.policy_qa_results has unknown check {key!r}")
                verdict = value.get("verdict") if isinstance(value, dict) else value
                if verdict not in VALID_QA_VERDICT:
                    errors.append(
                        f"{label}.policy_qa_results.{key} verdict must be pass, fail, or not_applicable"
                    )
        canvas = job.get("canvas")
        if (
            not isinstance(canvas, list)
            or len(canvas) != 2
            or not all(isinstance(value, int) and value > 0 for value in canvas)
        ):
            errors.append(f"{label}.canvas must be [positive width, positive height]")
        validate_bbox(
            job.get("target_product_bbox_norm"),
            f"{label}.target_product_bbox_norm",
            errors,
        )
        validate_bbox(
            job.get("output_product_bbox_norm"),
            f"{label}.output_product_bbox_norm",
            errors,
            nullable=True,
        )
        validate_bbox(
            job.get("raw_product_bbox_norm"),
            f"{label}.raw_product_bbox_norm",
            errors,
            nullable=True,
        )
        overrides = job.get("detail_output_bbox_norms", {})
        if not isinstance(overrides, dict):
            errors.append(f"{label}.detail_output_bbox_norms must be an object")
        else:
            for detail_id, bbox in overrides.items():
                if detail_id not in detail_ids:
                    errors.append(
                        f"{label}.detail_output_bbox_norms contains unknown detail {detail_id!r}"
                    )
                validate_bbox(bbox, f"{label}.detail_output_bbox_norms.{detail_id}", errors)
        for ref_id in job.get("source_reference_ids", []):
            if ref_id not in reference_ids:
                errors.append(f"{label}.source_reference_ids contains unknown {ref_id!r}")
        for output_field in ("raw_output", "final_output"):
            value = job.get(output_field)
            try:
                resolve_project_path(value, base, f"{label}.{output_field}")
            except PipelineError as exc:
                errors.append(str(exc))
        if job.get("kind") in {"main", "listing"} and canvas != [1600, 1600]:
            errors.append(f"{label}.canvas must be [1600, 1600] for Amazon listing images")

    for detail in details:
        for job_id in detail.get("visibility", {}):
            if job_id not in job_ids:
                errors.append(
                    f"critical_details[{detail.get('id')}].visibility references unknown job {job_id!r}"
                )
        if detail.get("priority") in {"P0", "P1"}:
            missing = sorted(job_ids - set(detail.get("visibility", {})))
            if missing:
                errors.append(
                    f"critical_details[{detail.get('id')}].visibility must explicitly cover every job; "
                    f"missing {missing}"
                )
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


def detail_location_for_view(detail: dict[str, Any], view: str) -> dict[str, Any] | None:
    exact = [location for location in detail.get("locations", []) if location.get("view") == view]
    return exact[0] if exact else None


def image_edge_signal(image: Image.Image) -> float:
    gray = ImageOps.grayscale(image)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return round(float(ImageStat.Stat(edges).mean[0]), 3)


def preflight(manifest: dict[str, Any], base: Path) -> None:
    truth = manifest["product_truth"]
    safe = float(truth.get("safe_upscale_ratio", 1.25))
    marginal = float(truth.get("max_marginal_upscale_ratio", 1.75))
    reference_sizes: dict[str, tuple[int, int]] = {}
    reference_visual_quality: dict[str, str] = {}

    for ref in manifest["references"]:
        path = resolve_path(ref["path"], base)
        assert path is not None
        with Image.open(path) as source:
            source.load()
            width, height = source.size
            left, top, right, bottom = normalized_to_pixels(
                ref["product_bbox_norm"], width, height
            )
            product_width, product_height = right - left, bottom - top
            ref["image_size"] = [width, height]
            ref["product_pixel_size"] = [product_width, product_height]
            ref["edge_signal"] = image_edge_signal(source.crop((left, top, right, bottom)))
            ref["sha256"] = sha256_file(path)
            reference_sizes[ref["id"]] = (product_width, product_height)
            reference_visual_quality[ref["id"]] = ref.get("visual_quality", "unknown")

    best_quality = "insufficient"
    quality_rank = {"insufficient": 0, "marginal": 1, "sufficient": 2}
    for job in manifest["jobs"]:
        source_ids = job.get("source_reference_ids", [])
        source_id = source_ids[0] if source_ids else None
        if source_id not in reference_sizes:
            job["effective_upscale_ratio"] = None
            job.setdefault("preflight_warnings", []).append("NO_SOURCE_REFERENCE")
            continue
        source_width, source_height = reference_sizes[source_id]
        canvas_width, canvas_height = job["canvas"]
        _, _, target_width_norm, target_height_norm = job["target_product_bbox_norm"]
        target_width = target_width_norm * canvas_width
        target_height = target_height_norm * canvas_height
        ratio = max(target_width / source_width, target_height / source_height)
        job["effective_upscale_ratio"] = round(ratio, 4)
        if ratio <= safe:
            quality = "sufficient"
        elif ratio <= marginal:
            quality = "marginal"
        else:
            quality = "insufficient"
            if job["render_mode"] == "pixel_composite":
                job["status"] = "blocked"
                job["blocked_reason"] = "SOURCE_UPSCALE_EXCEEDS_LIMIT"
        visual_quality = reference_visual_quality.get(source_id, "unknown")
        job["visual_source_quality"] = visual_quality
        if visual_quality == "unknown":
            job["status"] = "blocked"
            job["blocked_reason"] = "SOURCE_VISUAL_QUALITY_NOT_REVIEWED"
        elif visual_quality == "insufficient" and job["render_mode"] == "pixel_composite":
            job["status"] = "blocked"
            job["blocked_reason"] = "SOURCE_VISUAL_QUALITY_INSUFFICIENT"
            quality = "insufficient"
        elif visual_quality == "marginal" and quality == "sufficient":
            quality = "marginal"
        if job.get("requires_fine_detail") and quality != "sufficient":
            job["status"] = "blocked"
            job["blocked_reason"] = "FINE_DETAIL_REQUIRES_SUFFICIENT_SOURCE"
        job["source_quality"] = quality
        if quality_rank[quality] > quality_rank[best_quality]:
            best_quality = quality
    truth["source_quality"] = best_quality
    if best_quality == "insufficient" and truth.get("master_asset_mode") == "original_pixels":
        truth["master_asset_mode"] = "blocked"
    if truth.get("master_asset_mode") == "restored_master" and not truth.get("master_confirmed"):
        for job in manifest["jobs"]:
            job["status"] = "blocked"
            job["blocked_reason"] = "RESTORED_MASTER_NOT_CONFIRMED"


def extract_detail_references(manifest: dict[str, Any], base: Path) -> None:
    output_dir = base / "detail_refs"
    output_dir.mkdir(parents=True, exist_ok=True)
    references = {ref["id"]: ref for ref in manifest["references"]}

    for detail in manifest.get("critical_details", []):
        crops: list[dict[str, Any]] = []
        has_confirmed = False
        for location in detail.get("locations", []):
            ref = references[location["reference_id"]]
            source_path = resolve_path(ref["path"], base)
            assert source_path is not None
            with Image.open(source_path) as source:
                source = ImageOps.exif_transpose(source).convert("RGB")
                image_bbox = detail_bbox_in_image(
                    ref["product_bbox_norm"], location["bbox_in_product_norm"]
                )
                left, top, right, bottom = normalized_to_pixels(
                    image_bbox, source.width, source.height
                )
                detail_width, detail_height = right - left, bottom - top
                longest = max(detail_width, detail_height)
                shortest = min(detail_width, detail_height)
                pixel_verifiable = longest >= 32 and shortest >= 8
                visually_confirmed = detail.get("visual_confirmation") == "confirmed"
                verifiable = pixel_verifiable and visually_confirmed
                has_confirmed = has_confirmed or verifiable
                padding = max(4, round(max(detail_width, detail_height) * 0.5))
                crop_box = (
                    max(0, left - padding),
                    max(0, top - padding),
                    min(source.width, right + padding),
                    min(source.height, bottom + padding),
                )
                crop = source.crop(crop_box)
                output_path = output_dir / (
                    f"{detail['id']}__{location['view']}__{location['reference_id']}.png"
                )
                crop.save(output_path, format="PNG")
                crops.append(
                    {
                        "view": location["view"],
                        "reference_id": location["reference_id"],
                        "path": relpath(output_path, base),
                        "detail_pixel_size": [detail_width, detail_height],
                        "pixel_verifiable": pixel_verifiable,
                        "visually_confirmed": visually_confirmed,
                        "verifiable": verifiable,
                        "sha256": sha256_file(output_path),
                    }
                )
        detail["reference_crops"] = crops
        detail["status"] = "confirmed" if has_confirmed else "unverifiable"


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


def compile_job_prompt(
    manifest: dict[str, Any], job: dict[str, Any], base: Path
) -> tuple[str, list[str], list[str], list[str]]:
    truth = manifest["product_truth"]
    required: list[str] = []
    hidden: list[str] = []
    reference_paths: list[str] = []
    source_ids = job.get("source_reference_ids", [])
    for ref_id in source_ids:
        ref = find_by_id(manifest["references"], ref_id)
        if ref:
            reference_paths.append(ref["path"])

    detail_blocks: list[str] = []
    for detail in manifest.get("critical_details", []):
        visibility = detail.get("visibility", {}).get(job["id"], "optional")
        location = detail_location_for_view(detail, job.get("view", ""))
        if visibility == "hidden":
            hidden.append(detail["id"])
            detail_blocks.append(
                f"- {detail['name']} ({detail['priority']}): not visible from this view. "
                "Do not reveal it, relocate it, or invent it on another surface."
            )
            continue
        if visibility != "required":
            continue
        required.append(detail["id"])
        if detail.get("status") == "unverifiable" or location is None:
            job["status"] = "blocked"
            job["blocked_reason"] = f"DETAIL_UNVERIFIABLE:{detail['id']}"
        crop = next(
            (
                crop
                for crop in detail.get("reference_crops", [])
                if crop.get("view") == job.get("view") and crop.get("verifiable")
            ),
            None,
        )
        if crop:
            reference_paths.append(crop["path"])
        else:
            job["status"] = "blocked"
            job["blocked_reason"] = f"DETAIL_VIEW_UNVERIFIABLE:{detail['id']}:{job.get('view', '')}"
        position = location.get("position_description") if location else "unsupported view"
        detail_blocks.append(
            f"- {detail['name']} ({detail['priority']}): {detail.get('description', '')} "
            f"Location: {position}. Shape/orientation/color: "
            f"{detail.get('shape', 'preserve reference')}; "
            f"{detail.get('orientation', 'preserve reference')}; "
            f"{detail.get('color', 'preserve reference')}. "
            "It must remain present at the exact supported location. Do not delete, fill, "
            "move, enlarge, shrink, rotate, simplify, or replace it."
        )

    roles: list[str] = []
    reference_role_by_path = {
        ref["path"]: ref.get("role", "whole_product_reference")
        for ref in manifest["references"]
    }
    for path in dict.fromkeys(reference_paths):
        role = (
            "critical_detail_reference"
            if "detail_refs/" in path
            else reference_role_by_path.get(path, "whole_product_reference")
        )
        roles.append(f"- {path}: {role}")

    sections = [
        "Geometry Lock:",
        *lock_lines(truth.get("geometry_lock", {})),
        "",
        "Material Lock:",
        *lock_lines(truth.get("material_lock", {})),
        "",
        "Scene Scale Lock:",
        *lock_lines(truth.get("scene_scale_lock", {})),
        "",
        "Critical Detail Lock:",
        *(detail_blocks or ["- No critical detail is required from this supported view."]),
        "",
        "Use case: product-mockup",
        f"Asset type: Amazon image {job['id']}",
        f"Render mode: {job['render_mode']}",
        f"Primary request: {job.get('selling_job', '')}",
        "Input images:",
        *(roles or ["- No supported reference; block rather than invent product geometry."]),
        f"Scene/backdrop: {job.get('scene', '')}",
        f"Subject: {truth.get('product', '')}",
        "Style/medium: photorealistic product photography with believable real-world texture",
        f"Composition/framing: {job.get('composition', '')}",
        f"Lighting/mood: {job.get('lighting', '')}",
        "Text: none; generate a clean text-free base image",
        "Constraints: preserve exact product geometry, materials, supported view details, and scale; "
        "change only the requested surroundings when using edit/composite mode",
        "Avoid: non-uniform scaling, product redesign, hallucinated ports or accessories, "
        "missing required details, fake certifications, logos, watermarks, and in-image text",
    ]
    prompt = "\n".join(str(line).rstrip() for line in sections).strip() + "\n"
    return prompt, required, hidden, list(dict.fromkeys(reference_paths))


def compile_prompts(manifest: dict[str, Any], base: Path) -> None:
    prompt_dir = base / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    for job in manifest["jobs"]:
        previous_hash = job.get("prompt_hash")
        prompt, required, hidden, references = compile_job_prompt(manifest, job, base)
        digest = hashlib.sha256(prompt.encode("utf-8"))
        execution_contract = {
            "kind": job.get("kind"),
            "view": job.get("view"),
            "canvas": job.get("canvas"),
            "target_product_bbox_norm": job.get("target_product_bbox_norm"),
            "render_mode": job.get("render_mode"),
            "required_details": required,
            "hidden_details": hidden,
            "text_overlays": job.get("text_overlays", []),
        }
        digest.update(
            json.dumps(execution_contract, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        for value in references:
            path = resolve_path(value, base)
            if path and path.is_file():
                digest.update(sha256_file(path).encode("ascii"))
        prompt_hash = digest.hexdigest()
        prompt_path = prompt_dir / f"{job['id']}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        job["prompt_file"] = relpath(prompt_path, base)
        job["prompt_hash"] = prompt_hash
        job["required_details"] = required
        job["hidden_details"] = hidden
        job["detail_reference_paths"] = [
            value for value in references if "detail_refs/" in value
        ]
        job["generation_reference_paths"] = references
        if previous_hash and previous_hash != prompt_hash:
            if job.get("status") != "blocked":
                job["status"] = "pending"
            job["qa_invalidated_reason"] = "PROMPT_OR_REFERENCE_CHANGED"
            job["attempts"] = 0
            job["quality_repairs"] = 0
            job["semantic_qa_results"] = {}
            job["policy_qa_results"] = {}
            job["detail_qa_results"] = {}
            for key in (
                "attempt_prompt_hash",
                "generated_prompt_hash",
                "final_prompt_hash",
                "final_sha256",
                "qa_final_sha256",
            ):
                job.pop(key, None)


def parse_color(value: Any, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    if isinstance(value, list) and len(value) == 3:
        return tuple(max(0, min(255, int(channel))) for channel in value)  # type: ignore[return-value]
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]
    return default


def find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def apply_overlays(image: Image.Image, overlays: list[dict[str, Any]]) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    for overlay in overlays:
        text = str(overlay.get("text", "")).strip()
        if not text:
            continue
        x_norm, y_norm = overlay.get("xy_norm", [0.06, 0.06])
        max_width = int(float(overlay.get("max_width_norm", 0.42)) * image.width)
        font_size = int(overlay.get("font_size", max(24, image.width // 28)))
        font = find_font(font_size)
        approximate_chars = max(8, int(max_width / max(font_size * 0.58, 1)))
        wrapped = "\n".join(textwrap.wrap(text, width=approximate_chars))
        x, y = int(x_norm * image.width), int(y_norm * image.height)
        bbox = draw.multiline_textbbox((x, y), wrapped, font=font, spacing=6)
        padding = int(overlay.get("padding", 18))
        shift_x = 0
        shift_y = 0
        if bbox[0] - padding < 0:
            shift_x = padding - bbox[0]
        elif bbox[2] + padding > image.width:
            shift_x = image.width - padding - bbox[2]
        if bbox[1] - padding < 0:
            shift_y = padding - bbox[1]
        elif bbox[3] + padding > image.height:
            shift_y = image.height - padding - bbox[3]
        x += shift_x
        y += shift_y
        bbox = draw.multiline_textbbox((x, y), wrapped, font=font, spacing=6)
        background = parse_color(overlay.get("background", "#ffffff")) + (
            int(overlay.get("background_alpha", 220)),
        )
        draw.rounded_rectangle(
            (
                bbox[0] - padding,
                bbox[1] - padding,
                bbox[2] + padding,
                bbox[3] + padding,
            ),
            radius=12,
            fill=background,
        )
        draw.multiline_text(
            (x, y),
            wrapped,
            font=font,
            fill=parse_color(overlay.get("color", "#17212b")) + (255,),
            spacing=6,
        )


def aspect_safe_postprocess(manifest: dict[str, Any], base: Path, force: bool = False) -> None:
    for job in manifest["jobs"]:
        if job.get("status") == "qa_passed" and not force:
            continue
        raw_path = resolve_project_path(job.get("raw_output"), base, f"jobs[{job['id']}].raw_output")
        if raw_path is None or not raw_path.is_file():
            continue
        if job.get("status") != "generated":
            raise PipelineError(
                f"Job {job['id']} has a raw output but status is {job.get('status')!r}; "
                "transition it to generated before postprocessing"
            )
        if job.get("generated_prompt_hash") != job.get("prompt_hash"):
            raise PipelineError(f"Job {job['id']} raw output is not bound to the current prompt hash")
        final_path = resolve_project_path(
            job.get("final_output"), base, f"jobs[{job['id']}].final_output"
        )
        if final_path is None:
            final_path = base / "final" / f"{job['id']}.png"
            job["final_output"] = relpath(final_path, base)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        target_width, target_height = job["canvas"]
        with Image.open(raw_path) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            source_width, source_height = source.size
            contained = ImageOps.contain(
                source, (target_width, target_height), method=Image.Resampling.LANCZOS
            )
            background = Image.new(
                "RGB",
                (target_width, target_height),
                parse_color(job.get("padding_color", "#ffffff")),
            )
            offset = (
                (target_width - contained.width) // 2,
                (target_height - contained.height) // 2,
            )
            background.paste(contained, offset)
            apply_overlays(background, job.get("text_overlays", []))
            background.save(final_path, format="PNG", optimize=True)
            raw_bbox = job.get("raw_product_bbox_norm")
            if raw_bbox is not None:
                scale_x = contained.width / source_width
                scale_y = contained.height / source_height
                x, y, width, height = raw_bbox
                job["output_product_bbox_norm"] = [
                    round((offset[0] + x * source_width * scale_x) / target_width, 8),
                    round((offset[1] + y * source_height * scale_y) / target_height, 8),
                    round(width * source_width * scale_x / target_width, 8),
                    round(height * source_height * scale_y / target_height, 8),
                ]
        job["final_sha256"] = sha256_file(final_path)
        job["raw_sha256"] = sha256_file(raw_path)
        job["final_prompt_hash"] = job["prompt_hash"]
        if job.get("status") not in {"blocked", "failed"}:
            job["status"] = "generated"


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
        f"Edit target: {job.get('final_output', job.get('raw_output', ''))}\n"
        f"Critical detail reference: "
        f"{next((c.get('path') for c in detail.get('reference_crops', []) if c.get('view') == job.get('view')), '')}\n"
        f"Primary request: restore only {detail['name']} at its exact supported location.\n"
        f"Detail facts: {detail.get('description', '')}; shape {detail.get('shape', '')}; "
        f"orientation {detail.get('orientation', '')}; color {detail.get('color', '')}.\n"
        "Constraints: change only this missing or incorrect detail. Keep the entire remaining image, "
        "product geometry, materials, lighting, framing, scale, background, shadows, and every other "
        "visible detail pixel-for-pixel unchanged. Do not move, enlarge, shrink, rotate, simplify, "
        "or replace the detail. No text or watermark.\n"
    )
    path.write_text(prompt, encoding="utf-8")
    return relpath(path, base)


def create_semantic_repair_prompt(job: dict[str, Any], failed: list[str], base: Path) -> str:
    repair_dir = base / "repairs"
    repair_dir.mkdir(parents=True, exist_ok=True)
    path = repair_dir / f"{job['id']}__semantic.txt"
    prompt = (
        "Use case: precise-object-edit\n"
        f"Edit target: {job.get('final_output', job.get('raw_output', ''))}\n"
        f"Primary request: correct only these failed checks: {', '.join(failed)}.\n"
        "Constraints: keep every already-correct product detail, composition, background, text-free "
        "layout, and framing unchanged. Restore the product from the supplied whole-product and "
        "detail references. Do not add unsupported structure, material, component, prop, or claim.\n"
    )
    path.write_text(prompt, encoding="utf-8")
    return relpath(path, base)


def unpack_verdict(value: Any) -> str | None:
    return value.get("verdict") if isinstance(value, dict) else value


def quality_assurance(manifest: dict[str, Any], base: Path) -> dict[str, Any]:
    errors = validate_manifest(manifest, base, check_files=True)
    if errors:
        raise PipelineError("Manifest validation failed before QA:\n- " + "\n- ".join(errors))
    if not manifest.get("critical_detail_census_completed"):
        raise PipelineError("Critical Detail Census must be complete before QA")

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": manifest["project_id"],
        "jobs": [],
        "summary": {"passed": 0, "repair_needed": 0, "blocked": 0, "failed": 0},
    }
    comparison_paths: list[tuple[str, Path]] = []
    details_by_id = {detail["id"]: detail for detail in manifest.get("critical_details", [])}
    references_by_id = {ref["id"]: ref for ref in manifest["references"]}

    for job in manifest["jobs"]:
        result: dict[str, Any] = {"id": job["id"], "checks": [], "details": []}
        current_status = job.get("status")
        if current_status == "blocked":
            result["status"] = "blocked"
            result["blocked_reason"] = job.get("blocked_reason")
            report["summary"]["blocked"] += 1
            report["jobs"].append(result)
            continue
        if current_status == "failed":
            result["status"] = "failed"
            result["failed_reason"] = job.get("failed_reason")
            report["summary"]["failed"] += 1
            report["jobs"].append(result)
            continue
        if current_status not in {"generated", "repair_needed", "qa_passed"}:
            result["status"] = current_status
            result["checks"].append({"code": "JOB_NOT_READY_FOR_QA", "passed": False})
            report["summary"]["failed"] += 1
            report["jobs"].append(result)
            continue

        final_path = resolve_project_path(
            job.get("final_output"), base, f"jobs[{job['id']}].final_output"
        )
        if final_path is None or not final_path.is_file():
            job["status"] = "failed"
            job["failed_reason"] = "FINAL_OUTPUT_MISSING"
            result["status"] = "failed"
            result["checks"].append({"code": "FINAL_OUTPUT_MISSING", "passed": False})
            report["summary"]["failed"] += 1
            report["jobs"].append(result)
            continue
        current_sha = sha256_file(final_path)
        if (
            job.get("final_prompt_hash") != job.get("prompt_hash")
            or job.get("final_sha256") != current_sha
        ):
            job["status"] = "failed"
            job["failed_reason"] = "STALE_OR_MODIFIED_OUTPUT"
            result["status"] = "failed"
            result["checks"].append(
                {"code": "OUTPUT_BOUND_TO_CURRENT_PROMPT", "passed": False}
            )
            report["summary"]["failed"] += 1
            report["jobs"].append(result)
            continue

        hard_block = False
        needs_repair = False
        with Image.open(final_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            expected_size = tuple(job["canvas"])
            size_pass = image.size == expected_size
            result["checks"].append(
                {
                    "code": "CANVAS_SIZE",
                    "passed": size_pass,
                    "actual": list(image.size),
                    "expected": list(expected_size),
                }
            )
            if not size_pass:
                needs_repair = True

            output_product_bbox = job.get("output_product_bbox_norm")
            actual_ratio: float | None = None
            source_ids = job.get("source_reference_ids", [])
            source_ref = references_by_id.get(source_ids[0]) if source_ids else None
            if output_product_bbox is not None and source_ref and source_ref.get("product_pixel_size"):
                source_width, source_height = source_ref["product_pixel_size"]
                _, _, out_width, out_height = output_product_bbox
                actual_ratio = max(
                    out_width * image.width / source_width,
                    out_height * image.height / source_height,
                )
                actual_ratio = round(actual_ratio, 4)
            else:
                needs_repair = True
            safe = float(manifest["product_truth"].get("safe_upscale_ratio", 1.25))
            marginal = float(
                manifest["product_truth"].get("max_marginal_upscale_ratio", 1.75)
            )
            ratio_pass = not (
                job.get("render_mode") == "pixel_composite"
                and (actual_ratio is None or actual_ratio > marginal)
            )
            fine_detail_pass = not (
                job.get("requires_fine_detail")
                and (actual_ratio is None or actual_ratio > safe)
            )
            result["checks"].extend(
                [
                    {"code": "ACTUAL_SAFE_UPSCALE", "passed": ratio_pass, "actual": actual_ratio},
                    {"code": "FINE_DETAIL_SOURCE", "passed": fine_detail_pass, "actual": actual_ratio},
                ]
            )
            if not ratio_pass or not fine_detail_pass:
                hard_block = True

            if job.get("kind") == "main":
                white_score = corner_white_score(image)
                white_pass = white_score >= 245 and not job.get("text_overlays")
                result["checks"].append(
                    {
                        "code": "MAIN_WHITE_BACKGROUND",
                        "passed": white_pass,
                        "corner_white_score": white_score,
                    }
                )
                if not white_pass:
                    needs_repair = True

            failed_review_checks: list[str] = []
            semantic_checks: list[dict[str, Any]] = []
            for key in ("geometry", "material", "components", "scene_scale"):
                verdict = unpack_verdict(job.get("semantic_qa_results", {}).get(key))
                allow_na = key == "scene_scale" and job.get("kind") == "main"
                passed = verdict == "pass" or (allow_na and verdict == "not_applicable")
                semantic_checks.append(
                    {"check": key, "verdict": verdict or "missing", "passed": passed}
                )
                if not passed:
                    failed_review_checks.append(f"semantic:{key}")
            result["semantic_checks"] = semantic_checks

            policy_checks: list[dict[str, Any]] = []
            for key in ("main_product_only", "claims", "competitor_copy", "text_readability"):
                verdict = unpack_verdict(job.get("policy_qa_results", {}).get(key))
                allow_na = (key == "main_product_only" and job.get("kind") != "main") or (
                    key == "text_readability" and not job.get("text_overlays")
                )
                passed = verdict == "pass" or (allow_na and verdict == "not_applicable")
                policy_checks.append(
                    {"check": key, "verdict": verdict or "missing", "passed": passed}
                )
                if not passed:
                    failed_review_checks.append(f"policy:{key}")
            result["policy_checks"] = policy_checks
            if failed_review_checks:
                needs_repair = True
                result["semantic_repair_prompt"] = create_semantic_repair_prompt(
                    job, failed_review_checks, base
                )

            required_detail_ids = [
                detail["id"]
                for detail in manifest.get("critical_details", [])
                if detail.get("visibility", {}).get(job["id"]) == "required"
            ]
            job["required_details"] = required_detail_ids
            job["hidden_details"] = [
                detail["id"]
                for detail in manifest.get("critical_details", [])
                if detail.get("visibility", {}).get(job["id"]) == "hidden"
            ]
            verdicts = job.setdefault("detail_qa_results", {})
            for detail_id in required_detail_ids:
                detail = details_by_id[detail_id]
                priority = detail["priority"]
                detail_result: dict[str, Any] = {
                    "id": detail_id,
                    "priority": priority,
                    "status": detail.get("status"),
                }
                location = detail_location_for_view(detail, job.get("view", ""))
                crop_meta = next(
                    (
                        crop
                        for crop in detail.get("reference_crops", [])
                        if crop.get("view") == job.get("view") and crop.get("verifiable")
                    ),
                    None,
                )
                if detail.get("status") != "confirmed" or location is None or crop_meta is None:
                    detail_result["verdict"] = "blocked_unverifiable"
                    hard_block = True
                    result["details"].append(detail_result)
                    continue
                detail_override = job.get("detail_output_bbox_norms", {}).get(detail_id)
                if output_product_bbox is None and detail_override is None:
                    detail_result["verdict"] = "manual_review_required"
                    needs_repair = priority in {"P0", "P1"}
                    result["details"].append(detail_result)
                    continue
                output_crop = crop_output_detail(
                    image,
                    output_product_bbox or [0.0, 0.0, 1.0, 1.0],
                    location["bbox_in_product_norm"],
                    absolute_detail_bbox=detail_override,
                )
                reference_path = resolve_project_path(
                    crop_meta["path"], base, f"detail_refs[{detail_id}]"
                )
                assert reference_path is not None
                with Image.open(reference_path) as reference_opened:
                    comparison_path = (
                        base / "review" / "details" / job["id"] / f"{detail_id}.png"
                    )
                    make_comparison(reference_opened.convert("RGB"), output_crop, comparison_path)
                comparison_paths.append((f"{job['id']} / {detail_id}", comparison_path))
                detail_result["comparison_path"] = relpath(comparison_path, base)
                verdict = unpack_verdict(verdicts.get(detail_id))
                if verdict == "pass":
                    detail_result["verdict"] = "pass"
                elif verdict == "fail":
                    detail_result["verdict"] = "fail"
                    needs_repair = priority in {"P0", "P1"}
                    detail_result["repair_prompt"] = create_repair_prompt(
                        manifest, job, detail, base
                    )
                else:
                    detail_result["verdict"] = "manual_review_required"
                    needs_repair = priority in {"P0", "P1"}
                result["details"].append(detail_result)

        if hard_block:
            job["status"] = "blocked"
            report["summary"]["blocked"] += 1
        elif needs_repair:
            job["status"] = "repair_needed"
            report["summary"]["repair_needed"] += 1
        else:
            job["status"] = "qa_passed"
            job["qa_final_sha256"] = current_sha
            report["summary"]["passed"] += 1
        result["status"] = job["status"]
        report["jobs"].append(result)

    report_path = base / "qa_report.json"
    write_json(report_path, report)
    create_micro_detail_sheet(
        comparison_paths, base / "review" / "micro_detail_contact_sheet.png"
    )
    return report


def create_micro_detail_sheet(items: list[tuple[str, Path]], output: Path) -> None:
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


def create_final_contact_sheet(manifest: dict[str, Any], base: Path) -> None:
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
    output = base / "final" / "contact_sheet.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)


def delivery_check(manifest: dict[str, Any], base: Path) -> dict[str, Any]:
    errors = validate_manifest(manifest, base, check_files=True)
    issues = list(errors)
    for job in manifest.get("jobs", []):
        if not job.get("required", True):
            continue
        if job.get("status") != "qa_passed":
            issues.append(f"{job.get('id')}: status is {job.get('status')}, not qa_passed")
            continue
        final_path = resolve_project_path(
            job.get("final_output"), base, f"jobs[{job.get('id')}].final_output"
        )
        if final_path is None or not final_path.is_file():
            issues.append(f"{job.get('id')}: final output is missing")
            continue
        current_sha = sha256_file(final_path)
        if job.get("qa_final_sha256") != current_sha:
            issues.append(f"{job.get('id')}: final output changed after QA")
        if job.get("final_prompt_hash") != job.get("prompt_hash"):
            issues.append(f"{job.get('id')}: final output is bound to a stale prompt")
    for required_path in (
        base / "qa_report.json",
        base / "final" / "contact_sheet.png",
        base / "review" / "micro_detail_contact_sheet.png",
    ):
        if not required_path.is_file():
            issues.append(f"required delivery artifact missing: {relpath(required_path, base)}")
    report = {
        "schema_version": SCHEMA_VERSION,
        "project_id": manifest.get("project_id"),
        "ready": not issues,
        "issues": issues,
    }
    write_json(base / "delivery_report.json", report)
    if issues:
        raise PipelineError("Delivery gate failed:\n- " + "\n- ".join(issues))
    return report


def transition_job(
    manifest: dict[str, Any], job_id: str, next_status: str, reason: str | None
) -> None:
    job = find_by_id(manifest["jobs"], job_id)
    if job is None:
        raise PipelineError(f"Unknown job: {job_id}")
    require_enum(next_status, VALID_JOB_STATUS, "next_status", errors := [])
    if errors:
        raise PipelineError(errors[0])
    current = job.get("status", "pending")
    if next_status not in ALLOWED_TRANSITIONS[current]:
        raise PipelineError(f"Invalid transition: {current} -> {next_status}")
    if next_status == "generating":
        if not job.get("prompt_hash"):
            raise PipelineError(f"Job {job_id} has not been prepared; prompt_hash is missing")
        if current == "pending" and manifest.get("generation_gate", {}).get("status") != "open":
            blocked = manifest.get("generation_gate", {}).get("blocked_required_jobs", [])
            raise PipelineError(f"Generation gate is closed by required jobs: {blocked}")
        if current == "repair_needed":
            repairs = int(job.get("quality_repairs", 0)) + 1
            if repairs > int(manifest.get("max_quality_repairs", 1)):
                job["status"] = "blocked"
                job["blocked_reason"] = "QUALITY_REPAIR_LIMIT_REACHED"
                return
            job["quality_repairs"] = repairs
        else:
            attempts = int(job.get("attempts", 0)) + 1
            max_attempts = 1 + int(manifest.get("max_transient_retries", 2))
            if attempts > max_attempts:
                job["status"] = "failed"
                job["failed_reason"] = "TRANSIENT_RETRY_LIMIT_REACHED"
                return
            job["attempts"] = attempts
        job["attempt_prompt_hash"] = job["prompt_hash"]
        job["semantic_qa_results"] = {}
        job["policy_qa_results"] = {}
        job["detail_qa_results"] = {}
        for key in ("generated_prompt_hash", "final_prompt_hash", "final_sha256", "qa_final_sha256"):
            job.pop(key, None)
    if next_status == "generated":
        if job.get("attempt_prompt_hash") != job.get("prompt_hash"):
            raise PipelineError(
                f"Job {job_id} was generated from a stale prompt hash; return it to pending"
            )
        job["generated_prompt_hash"] = job["prompt_hash"]
    job["status"] = next_status
    if reason:
        job["status_reason"] = reason


def prepare(manifest: dict[str, Any], base: Path) -> None:
    errors = validate_manifest(manifest, base, check_files=True)
    if errors:
        raise PipelineError("Manifest validation failed:\n- " + "\n- ".join(errors))
    if not manifest.get("critical_detail_census_completed"):
        raise PipelineError(
            "Critical Detail Census is not complete. Set critical_detail_census_completed=true "
            "only after inspecting every source image at original detail."
        )
    for job in manifest["jobs"]:
        reason = str(job.get("blocked_reason", ""))
        if job.get("status") == "blocked" and reason.startswith(DERIVED_BLOCK_PREFIXES):
            job["status"] = "pending"
            job.pop("blocked_reason", None)
    preflight(manifest, base)
    extract_detail_references(manifest, base)
    compile_prompts(manifest, base)
    blocked_required = [
        job["id"]
        for job in manifest["jobs"]
        if job.get("required", True) and job.get("status") == "blocked"
    ]
    manifest["generation_gate"] = {
        "status": "closed" if blocked_required else "open",
        "blocked_required_jobs": blocked_required,
    }


def init_project(project_dir: Path, project_id: str, force: bool) -> Path:
    template_path = Path(__file__).resolve().parent.parent / "assets" / "project_manifest.template.json"
    manifest_path = project_dir / "project_manifest.json"
    if manifest_path.exists() and not force:
        raise PipelineError(f"Refusing to overwrite existing manifest: {manifest_path}")
    project_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_json(template_path)
    manifest["project_id"] = project_id
    write_json(manifest_path, manifest)
    for directory in ("source", "raw", "final", "review", "prompts", "detail_refs", "repairs"):
        (project_dir / directory).mkdir(exist_ok=True)
    return manifest_path


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    subcommands = command.add_subparsers(dest="command", required=True)

    init = subcommands.add_parser("init", help="Create a versioned project skeleton")
    init.add_argument("--project-dir", required=True, type=Path)
    init.add_argument("--project-id", required=True)
    init.add_argument("--force", action="store_true")

    for name in ("validate", "prepare", "postprocess", "qa", "finalize", "delivery-check"):
        sub = subcommands.add_parser(name)
        sub.add_argument("--manifest", required=True, type=Path)
        if name == "validate":
            sub.add_argument("--skip-file-check", action="store_true")
        if name == "postprocess":
            sub.add_argument("--force", action="store_true")

    transition = subcommands.add_parser("transition")
    transition.add_argument("--manifest", required=True, type=Path)
    transition.add_argument("--job", required=True)
    transition.add_argument("--status", required=True)
    transition.add_argument("--reason")
    return command


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "init":
            path = init_project(args.project_dir.resolve(), args.project_id, args.force)
            print(path)
            return 0

        manifest_path = args.manifest.expanduser().resolve()
        base = manifest_path.parent
        manifest = read_json(manifest_path)
        if args.command == "validate":
            errors = validate_manifest(manifest, base, check_files=not args.skip_file_check)
            if errors:
                raise PipelineError("Manifest validation failed:\n- " + "\n- ".join(errors))
            print("manifest_valid")
            return 0
        if args.command == "prepare":
            prepare(manifest, base)
        elif args.command == "postprocess":
            aspect_safe_postprocess(manifest, base, force=args.force)
            create_final_contact_sheet(manifest, base)
        elif args.command == "qa":
            quality_assurance(manifest, base)
        elif args.command == "finalize":
            aspect_safe_postprocess(manifest, base)
            quality_assurance(manifest, base)
            create_final_contact_sheet(manifest, base)
        elif args.command == "delivery-check":
            delivery_check(manifest, base)
        elif args.command == "transition":
            transition_job(manifest, args.job, args.status, args.reason)
        write_json(manifest_path, manifest)
        print(manifest_path)
        return 0
    except PipelineError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
