"""Source-region inspection and evidence-gated render decisions for Studio v3.

Metrics are inspection aids, never substitutes for visual review.  No model or
external service is called here.  Source review images are NOT deliverables.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps, ImageStat
from lc_assets import file_hash, file_hash_context

VERSION = "source-quality-v3.1"
CLARITIES = {"clear", "mild_softness", "blurred", "unknown"}
EVIDENCE = {"sufficient", "insufficient", "unknown"}
FITS = {"matched", "local_change", "new_view", "unknown"}
DEGRADATIONS = {"none", "mild", "localized", "global", "unknown"}
DETAIL_ROLES = {"critical_detail_reference", "material_reference", "component_reference", "package_reference"}


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _sha(path: Path) -> str:
    return file_hash(path)


def _bbox_valid(value: Any) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 4
            and all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in value)
            and value[0] >= 0 and value[1] >= 0 and value[2] > 0 and value[3] > 0
            and value[0] + value[2] <= 1.00000001 and value[1] + value[3] <= 1.00000001)


def _pixels(box: list[float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    if not _bbox_valid(box):
        raise ValueError(f"Invalid normalized product/detail box: {box!r}")
    w, h = size
    x, y, bw, bh = box
    left, top = min(w - 1, round(x * w)), min(h - 1, round(y * h))
    return left, top, min(w, max(left + 1, round((x + bw) * w))), min(h, max(top + 1, round((y + bh) * h)))


def source_region_fingerprint(ref: dict[str, Any]) -> str:
    """Fingerprint the actual inspected source and region, not review results."""
    return _fingerprint({"version": VERSION, "sha256": ref.get("sha256"), "bbox": ref.get("product_bbox_norm")})


def _required_details(manifest: dict, job: dict) -> list[dict]:
    return [d for d in manifest.get("critical_details", []) if d.get("priority") in {"P0", "P1"}
            and d.get("visibility", {}).get(job.get("id")) == "required"]


def _reference_ids(manifest: dict, job: dict) -> list[str]:
    ids = list(job.get("source_reference_ids", []))
    for layer in job.get("product_layers", []):
        if layer.get("reference_id"):
            ids.append(layer["reference_id"])
        ids.extend(layer.get("source_reference_ids", []))
        binding = layer.get("source_binding", {})
        if isinstance(binding, dict):
            ids.extend(binding.get("source_reference_hashes", {}))
    for detail in _required_details(manifest, job):
        ids.extend(location.get("reference_id") for location in detail.get("locations", []) if location.get("reference_id"))
    # Generated views retain their actual photographic evidence dependencies.
    # Include them in prompt inputs and review fingerprints, not only a sidecar.
    refs = {ref["id"]: ref for ref in manifest.get("references", [])}
    selected = list(dict.fromkeys(ids))
    seen = set(selected)
    for rid in selected:
        provenance = refs.get(rid, {}).get("provenance", {})
        if not isinstance(provenance, dict):
            continue
        dependencies = provenance.get("source_reference_ids", [])
        if not isinstance(dependencies, list) or not all(isinstance(dependency, str) for dependency in dependencies):
            continue
        for dependency in dependencies:
            if dependency not in seen:
                seen.add(dependency)
                selected.append(dependency)
    return selected


def assessment_context_fingerprint(manifest: dict, job: dict) -> str:
    """Bind human assessment to target, evidence and source review; omit states."""
    refs = {ref["id"]: ref for ref in manifest.get("references", [])}
    required = _required_details(manifest, job)
    return _fingerprint({
        "version": VERSION,
        "target": {key: job.get(key) for key in ("target_view", "view", "canvas", "target_product_bbox_norm", "scene", "composition", "lighting", "requires_fine_detail", "pixel_source_reference_id")},
        "references": [{"id": rid, "region": source_region_fingerprint(refs[rid]), "role": refs[rid].get("role"),
                        "view": refs[rid].get("view"), "review": refs[rid].get("quality_review"),
                        "provenance": refs[rid].get("provenance")} if rid in refs else {"missing": rid}
                       for rid in _reference_ids(manifest, job)],
        "required_details": [{key: d.get(key) for key in ("id", "priority", "evidence_level", "visual_confirmation", "locations")} for d in required],
        "product_layers": job.get("product_layers", []),
        "layer_asset_hashes": job.get("layer_asset_hashes", []),
    })


def _metrics(product: Image.Image) -> dict[str, Any]:
    gray = ImageOps.grayscale(product)

    def signal(region: Image.Image) -> float:
        if region.width < 3 or region.height < 3:
            return 0.0
        edges = region.filter(ImageFilter.FIND_EDGES).crop((1, 1, region.width - 1, region.height - 1))
        return round(ImageStat.Stat(edges).mean[0], 4)

    tiles = []
    for row in range(3):
        for col in range(3):
            box = (col * gray.width // 3, row * gray.height // 3,
                   (col + 1) * gray.width // 3, (row + 1) * gray.height // 3)
            tiles.append({"grid": [col, row], "edge_signal": signal(gray.crop(box))})
    edge = signal(gray)
    return {
        "screening_only": True, "measurement_scale": "native_product_pixels", "edge_signal": edge,
        "luminance_stddev": round(ImageStat.Stat(gray).stddev[0], 4), "tiles": tiles,
        "inspection_flags": ["inspect_smooth_surface_or_soft_focus"] if edge < 1 else [],
        "limitations": "Edge/noise/texture signals cannot distinguish a smooth material from blur or prove genuine detail. Visually inspect original pixels and target-size preview for defocus, motion blur, compression, noise, oversmoothing, fake sharpening and localized defects.",
    }


def _artifact_ok(record: dict, root: Path) -> bool:
    paths = record.get("artifacts", {})
    if not paths:
        return False
    for relative, digest in paths.items():
        path = root / relative
        if not path.is_file() or _sha(path) != digest:
            return False
    return True


def _write_json_if_changed(path: Path, value: Any) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        temp = path.with_suffix(".tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(path)


def _assess_layer_assets(manifest: dict, job: dict, base: Path, cache: dict, hashes: dict) -> list[dict]:
    refs = {ref["id"]: ref for ref in manifest.get("references", [])}
    records = []

    def local_path(value):
        if not isinstance(value, str) or not value or "://" in value:
            raise ValueError("Layer assets must use a local path")
        path = Path(value).expanduser()
        return (path if path.is_absolute() else base / path).resolve()

    def file_hash(path):
        if str(path) not in hashes:
            hashes[str(path)] = _sha(path)
        return hashes[str(path)]

    for index, layer in enumerate(job.get("product_layers", [])):
        ref = refs.get(layer.get("reference_id"), {})
        record = {"index": index, "reference_id": layer.get("reference_id"),
                  "asset_input": layer.get("asset_path") or ref.get("path"), "mask_input": layer.get("mask_path"),
                  "crop_bbox_norm": layer.get("crop_bbox_norm"),
                  "bbox_norm": layer.get("bbox_norm", job.get("target_product_bbox_norm")),
                  "canvas": job.get("canvas"), "errors": []}
        try:
            source_path = local_path(ref.get("path"))
            asset_path = local_path(layer.get("asset_path") or ref.get("path"))
            mask_path = local_path(layer["mask_path"]) if layer.get("mask_path") else None
            record.update(asset_sha256=file_hash(asset_path), reference_sha256=ref.get("sha256"),
                          mask_sha256=file_hash(mask_path) if mask_path else None,
                          asset_matches_reference=asset_path == source_path)
            metrics_key = "layer_" + _fingerprint({key: record.get(key) for key in ("asset_sha256", "mask_sha256", "crop_bbox_norm", "bbox_norm", "canvas")})
            if metrics_key not in cache:
                with Image.open(asset_path) as source:
                    product = ImageOps.exif_transpose(source).convert("RGBA")
                if mask_path:
                    with Image.open(mask_path) as source:
                        mask = ImageOps.exif_transpose(source).convert("L")
                    if mask.size != product.size:
                        raise ValueError("Layer mask dimensions do not match asset")
                    product.putalpha(mask)
                if layer.get("crop_bbox_norm"):
                    product = product.crop(_pixels(layer["crop_bbox_norm"], product.size))
                alpha_box = product.getchannel("A").getbbox()
                if alpha_box is None:
                    raise ValueError("Layer product is fully transparent")
                target = _pixels(record["bbox_norm"], tuple(record["canvas"]))
                scale = min((target[2] - target[0]) / product.width, (target[3] - target[1]) / product.height)
                cache[metrics_key] = {"asset_crop_pixel_size": list(product.size),
                                      "visible_pixel_size": [alpha_box[2] - alpha_box[0], alpha_box[3] - alpha_box[1]],
                                      "effective_upscale_ratio": round(scale, 6)}
            record.update(cache[metrics_key])
        except (ValueError, OSError, TypeError, KeyError) as exc:
            record["errors"].append(str(exc))
        records.append(record)
    return records


@file_hash_context()
def assess_sources(manifest: dict[str, Any], base: Path, *, materialize: bool = True,
                   job_ids: set[str] | None = None) -> None:
    """Inspect every source crop and cache originals, detail crops, target previews.

    This runs before the detail census is complete. It never marks a human review
    as passed. Expected review fingerprints are exposed even when review is due.
    """
    base = Path(base).resolve()
    from lc_delivery import source_cache_metadata_is_current
    trusted_metadata = not materialize and source_cache_metadata_is_current(manifest, base)
    root = base / "review" / "source_quality"
    root.mkdir(parents=True, exist_ok=True)
    index_path = root / "index.json"
    try:
        cache = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if cache.get("version") != VERSION:
        cache = {"version": VERSION, "entries": {}}
    entries = cache.setdefault("entries", {})
    def usable(record, fields):
        if not all(field in record for field in fields):
            return False
        if _artifact_ok(record, root):
            return True
        if not trusted_metadata:
            return False
        # Missing reviewed rasters are disposable; changed surviving files are
        # never accepted using a historical digest.
        return all(not (root / name).exists() or _sha(root / name) == expected
                   for name, expected in record.get("artifacts", {}).items())
    summary: list[dict] = []
    references = manifest.get("references", [])
    file_hashes = {}
    for ref in references:
        path = Path(ref["path"]).expanduser()
        if not path.is_absolute():
            path = base / path
        ref["sha256"] = _sha(path)
        file_hashes[str(path.resolve())] = ref["sha256"]
        region_hash = source_region_fingerprint(ref)
        old_metrics = ref.get("quality_metrics", {})
        retained_previews = [item for item in old_metrics.get("target_previews", [])
                             if job_ids is not None and item.get("job_id") not in job_ids]
        if old_metrics.get("region_fingerprint") != region_hash:
            retained_previews = []
        product = None
        source_size = None
        def product_pixels():
            nonlocal product, source_size
            if product is None:
                with Image.open(path) as original:
                    source = ImageOps.exif_transpose(original).convert("RGB")
                try:
                    source_size = list(source.size)
                    product = source.crop(_pixels(ref["product_bbox_norm"], source.size))
                finally:
                    source.close()
            return product
        source_key = "source_" + region_hash
        entry = entries.get(source_key, {})
        if not usable(entry, ("image_size", "product_pixel_size", "metrics", "product_crop")):
            crop = product_pixels()
            filename = f"{region_hash}_product.png"
            if materialize:
                crop.save(root / filename)
            entry = {"image_size": source_size, "product_pixel_size": list(crop.size),
                     "metrics": _metrics(crop), "product_crop": filename,
                     "artifacts": {filename: _sha(root / filename)} if materialize else {}}
            entries[source_key] = entry
        ref["image_size"] = entry["image_size"]
        ref["product_pixel_size"] = entry["product_pixel_size"]
        ref["quality_metrics"] = {**entry["metrics"], "version": VERSION,
                                  "region_fingerprint": region_hash,
                                  "product_crop_path": str((root / entry["product_crop"]).relative_to(base)),
                                  "target_previews": retained_previews, "detail_regions": []}
        # Keep v2 diagnostic consumers working; never use this for pass/fail.
        ref["edge_signal"] = entry["metrics"]["edge_signal"]
        for job in manifest.get("jobs", []):
            if job_ids is not None and job["id"] not in job_ids:
                continue
            if ref["id"] not in _reference_ids(manifest, job):
                continue
            canvas = job.get("canvas", [2000, 2000])
            target = job.get("target_product_bbox_norm", [0.1, 0.1, 0.8, 0.8])
            if len(canvas) != 2 or not all(isinstance(n, int) and n > 0 for n in canvas):
                raise ValueError("Job canvas must contain two positive integers")
            rect = _pixels(target, tuple(canvas))
            preview_hash = _fingerprint([region_hash, canvas, target])
            preview_key = "preview_" + preview_hash
            preview = entries.get(preview_key, {})
            if not usable(preview, ("path", "thumbnail", "canvas", "target_bbox")):
                filename = f"{preview_hash}_target.png"
                smallname = f"{preview_hash}_360.png"
                if materialize:
                    crop = product_pixels()
                    result = Image.new("RGB", tuple(canvas), "#eeeeee")
                    fitted = ImageOps.contain(crop, (rect[2] - rect[0], rect[3] - rect[1]), Image.Resampling.LANCZOS)
                    result.paste(fitted, (rect[0] + (rect[2] - rect[0] - fitted.width) // 2,
                                          rect[1] + (rect[3] - rect[1] - fitted.height) // 2))
                    result.save(root / filename)
                    result.resize((360, round(360 * result.height / result.width)), Image.Resampling.LANCZOS).save(root / smallname)
                preview = {"path": filename, "thumbnail": smallname, "canvas": canvas, "target_bbox": target,
                           "artifacts": {f: _sha(root / f) for f in (filename, smallname)} if materialize else {}}
                entries[preview_key] = preview
            ref["quality_metrics"]["target_previews"].append({"job_id": job["id"],
                "path": str((root / preview["path"]).relative_to(base)),
                "thumbnail_path": str((root / preview["thumbnail"]).relative_to(base)),
                "canvas": canvas, "target_product_bbox_norm": target, "review_only": True})
        for detail in manifest.get("critical_details", []):
            for loc in detail.get("locations", []):
                if loc.get("reference_id") != ref["id"]:
                    continue
                box = loc.get("bbox_in_product_norm")
                detail_hash = _fingerprint([region_hash, box])
                detail_key = "detail_" + detail_hash
                detail_entry = entries.get(detail_key, {})
                if not usable(detail_entry, ("path", "pixel_size", "metrics")):
                    product_crop = product_pixels()
                    crop = product_crop.crop(_pixels(box, product_crop.size))
                    filename = f"{detail_hash}_detail.png"
                    if materialize:
                        crop.save(root / filename)
                    detail_entry = {"path": filename, "pixel_size": list(crop.size), "metrics": _metrics(crop),
                                    "artifacts": {filename: _sha(root / filename)} if materialize else {}}
                    entries[detail_key] = detail_entry
                ref["quality_metrics"]["detail_regions"].append({"detail_id": detail.get("id"),
                    "path": str((root / detail_entry["path"]).relative_to(base)),
                    "bbox_in_product_norm": box, "pixel_size": detail_entry["pixel_size"], "metrics": detail_entry["metrics"]})
        order = {job["id"]: index for index, job in enumerate(manifest.get("jobs", []))}
        ref["quality_metrics"]["target_previews"].sort(key=lambda item: order.get(item["job_id"], len(order)))
        summary.append({"reference_id": ref["id"], "sha256": ref["sha256"], "image_size": ref["image_size"],
                        "product_pixel_size": ref["product_pixel_size"], "quality_metrics": ref["quality_metrics"]})
        if product is not None:
            product.close()
    for job in manifest.get("jobs", []):
        if job_ids is not None and job["id"] not in job_ids:
            continue
        job["layer_asset_hashes"] = _assess_layer_assets(manifest, job, base, entries, file_hashes)
        job["assessment_context_fingerprint"] = assessment_context_fingerprint(manifest, job)
    _write_json_if_changed(index_path, cache)
    _write_json_if_changed(root / "review.json", {"version": VERSION, "screening_only": True, "references": summary})


def _review_problems(ref: dict) -> list[str]:
    review = ref.get("quality_review", {})
    rid = ref["id"]
    problems = []
    if review.get("clarity", "unknown") == "unknown" or review.get("evidence", "unknown") == "unknown":
        problems.append(f"SOURCE_REVIEW_REQUIRED:{rid}")
    if not ref.get("sha256") or review.get("reviewed_sha256") != ref.get("sha256"):
        problems.append(f"SOURCE_REVIEW_STALE:{rid}")
    if review.get("reviewed_region_fingerprint") != source_region_fingerprint(ref):
        problems.append(f"SOURCE_REGION_REVIEW_STALE:{rid}")
    return problems


def _is_whole(ref: dict) -> bool:
    return ref.get("role", "whole_product_reference") not in DETAIL_ROLES


def _real_evidence(ref: dict, refs: dict[str, dict]) -> bool:
    provenance = ref.get("provenance", {})
    if provenance.get("kind", "real_photo") == "real_photo":
        return True
    # A generated master can be reused, but its real evidence is still required.
    ids = provenance.get("source_reference_ids", [])
    hashes = provenance.get("reviewed_source_hashes", {})
    return (provenance.get("qa_verdict") == "pass" and bool(ids)
            and all(rid in refs and refs[rid].get("provenance", {}).get("kind", "real_photo") == "real_photo"
                    and not _review_problems(refs[rid]) and hashes.get(rid) == refs[rid].get("sha256") for rid in ids))


def _layer_blockers(manifest: dict, job: dict, refs: dict, pixel_reference_id: str | None) -> list[str]:
    """Validate the actual compositing inputs rather than the best unused photo."""
    blockers = []
    layers = job.get("product_layers", [])
    records = job.get("layer_asset_hashes", [])
    target_view = job.get("target_view") or job.get("view")
    matched = job.get("source_assessment", {}).get("matched_reference_ids", [])
    limit = manifest.get("product_truth", {}).get("safe_upscale_ratio", 1.25) if job.get("requires_fine_detail") else manifest.get("product_truth", {}).get("max_marginal_upscale_ratio", 1.75)
    for index, layer in enumerate(layers):
        tag = f"SOURCE_LAYER:{index}"
        rid = layer.get("reference_id")
        ref = refs.get(rid)
        if ref is None:
            blockers.append(f"{tag}:REFERENCE_MISSING")
            continue
        review = ref.get("quality_review", {})
        if _review_problems(ref) or review.get("clarity") != "clear" or review.get("evidence") != "sufficient":
            blockers.append(f"{tag}:CLEAR_REVIEWED_SOURCE_REQUIRED")
        if ref.get("view") != target_view and rid not in matched:
            blockers.append(f"{tag}:TARGET_VIEW_NOT_MATCHED")
        if ref.get("role") in DETAIL_ROLES and rid not in matched:
            blockers.append(f"{tag}:COMPONENT_VIEW_REVIEW_REQUIRED")
        if len(layers) == 1 and rid != pixel_reference_id:
            blockers.append(f"{tag}:SELECTED_PIXEL_REFERENCE_MISMATCH")
        record = records[index] if index < len(records) else {}
        expected = {"index": index, "reference_id": rid, "asset_input": layer.get("asset_path") or ref.get("path"),
                    "mask_input": layer.get("mask_path"), "crop_bbox_norm": layer.get("crop_bbox_norm"),
                    "bbox_norm": layer.get("bbox_norm", job.get("target_product_bbox_norm")), "canvas": job.get("canvas")}
        if not record or any(record.get(key) != value for key, value in expected.items()) or record.get("reference_sha256") != ref.get("sha256"):
            blockers.append(f"{tag}:ASSET_ASSESSMENT_STALE")
            continue
        if record.get("errors"):
            blockers.append(f"{tag}:ASSET_UNREADABLE")
            continue
        scale = record.get("effective_upscale_ratio")
        if not isinstance(scale, (int, float)) or scale > limit:
            blockers.append(f"{tag}:ACTUAL_UPSCALE_EXCEEDS_LIMIT")
        provenance = ref.get("provenance", {})
        reference_origin = provenance.get("kind", "real_photo")
        expected_origin = "original" if reference_origin == "real_photo" else reference_origin
        origin = layer.get("asset_origin", expected_origin)
        if origin != expected_origin:
            blockers.append(f"{tag}:ASSET_ORIGIN_CONTRADICTS_REFERENCE")
        if reference_origin != "real_photo" and not _real_evidence(ref, refs):
            blockers.append(f"{tag}:GENERATED_ASSET_EVIDENCE_UNVERIFIED")
        if not record.get("asset_matches_reference") or layer.get("mask_path"):
            binding = layer.get("source_binding", {})
            if (binding.get("reviewed") is not True or binding.get("reviewed_asset_sha256") != record.get("asset_sha256")
                    or binding.get("reviewed_mask_sha256") != record.get("mask_sha256")):
                blockers.append(f"{tag}:CUTOUT_SOURCE_BINDING_REQUIRED")
            evidence_ids = set([rid] + layer.get("source_reference_ids", []) + provenance.get("source_reference_ids", []))
            supplied = binding.get("source_reference_hashes", {})
            if (not evidence_ids.issubset(supplied) or any(eid not in refs or supplied.get(eid) != refs[eid].get("sha256") for eid in supplied)):
                blockers.append(f"{tag}:CUTOUT_SOURCE_HASHES_STALE")
    return blockers


def decide_job(manifest: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """Return a recommendation with explicit blockers, without mutating job state."""
    refs = {ref["id"]: ref for ref in manifest.get("references", [])}
    selected = _reference_ids(manifest, job)
    assessment = job.get("source_assessment", {})
    context_hash = assessment_context_fingerprint(manifest, job)
    blocked: list[str] = []
    available = [refs[rid] for rid in selected if rid in refs]
    for rid in selected:
        if rid not in refs:
            blocked.append(f"SOURCE_REFERENCE_MISSING:{rid}")
    if not available:
        blocked.append("SOURCE_NO_REFERENCES")
    for ref in available:
        blocked.extend(_review_problems(ref))
        if not _real_evidence(ref, refs):
            blocked.append(f"SOURCE_MASTER_EVIDENCE_UNVERIFIED:{ref['id']}")
    expected_hashes = {ref["id"]: ref.get("sha256") for ref in available}
    if assessment.get("reviewed_reference_hashes") != expected_hashes:
        blocked.append("SOURCE_ASSESSMENT_REFERENCES_STALE")
    if assessment.get("reviewed_context_fingerprint") != context_hash:
        blocked.append("SOURCE_ASSESSMENT_CONTEXT_STALE")
    fit, degradation = assessment.get("scene_fit", "unknown"), assessment.get("degradation", "unknown")
    evidence = assessment.get("evidence", "unknown")
    if fit == "unknown" or degradation == "unknown" or evidence == "unknown":
        blocked.append("SOURCE_JOB_REVIEW_REQUIRED")
    if evidence == "insufficient":
        blocked.append("SOURCE_JOB_EVIDENCE_INSUFFICIENT")
    target_view = job.get("target_view") or job.get("view")
    matched_ids = assessment.get("matched_reference_ids", [])
    layers = job.get("product_layers", [])
    explicit_components = {layer.get("reference_id") for layer in layers if layer.get("reference_id") in matched_ids} if len(layers) > 1 else set()
    whole = [ref for ref in available if _is_whole(ref) or ref["id"] in explicit_components]
    # Explicit reviewed matching can cover differently named but compatible views.
    # It must identify a reference; a vague matched label cannot bless all angles.
    same_view = [ref for ref in whole if ref.get("view") == target_view or ref["id"] in matched_ids]
    new_view = fit == "new_view"
    if fit in {"matched", "local_change"} and not same_view:
        blocked.append("SOURCE_MATCHED_REFERENCE_REVIEW_REQUIRED")
    canvas = job.get("canvas", [2000, 2000])
    target = job.get("target_product_bbox_norm", [0.1, 0.1, 0.8, 0.8])
    ratios = {}
    for ref in whole:
        size = ref.get("product_pixel_size", [])
        if len(size) == 2 and min(size) > 0:
            # Product occupies a contained, aspect-preserving rectangle. The
            # target is an available region, not permission to stretch the image.
            ratios[ref["id"]] = min(canvas[0] * target[2] / size[0], canvas[1] * target[3] / size[1])
            if len(layers) > 1:
                # Components occupy their individually reviewed slots, rather
                # than each being enlarged to the entire kit's product region.
                actual_scales = [record["effective_upscale_ratio"] for record in job.get("layer_asset_hashes", [])
                                 if record.get("reference_id") == ref["id"] and isinstance(record.get("effective_upscale_ratio"), (int, float))]
                if actual_scales:
                    ratios[ref["id"]] = max(actual_scales)
    candidates = [ref for ref in same_view if ref["id"] in ratios and ref.get("quality_review", {}).get("clarity") == "clear" and not _review_problems(ref)]
    pixel_id = job.get("pixel_source_reference_id")
    if pixel_id:
        candidates = [ref for ref in candidates if ref["id"] == pixel_id]
    candidate = min(candidates, key=lambda ref: ratios[ref["id"]], default=None)
    safe = float(manifest.get("product_truth", {}).get("safe_upscale_ratio", 1.25))
    marginal = float(manifest.get("product_truth", {}).get("max_marginal_upscale_ratio", 1.75))
    ratio = ratios.get(candidate["id"]) if candidate else None
    clarities = [ref.get("quality_review", {}).get("clarity", "unknown") for ref in whole]
    quality = "unknown" if blocked else "sufficient"
    mode: str | None = None
    action = "review_sources"
    if new_view:
        mode, action, reason = "reference_generate", "generate_target_view", "目标视角、姿态或互动关系改变；由足够实拍证据支持参考重绘。"
    elif degradation == "localized":
        mode, action, reason = "reference_edit", "repair_local_region", "商品局部质量不足；用可确认的局部参考定向编辑，并重查细节与清晰度。"
    elif degradation == "global" or (whole and all(c == "blurred" for c in clarities)):
        mode, action, reason = "reference_generate", "redraw_same_view", "商品区域整体模糊；文件像素和正确角度不能保证商品清晰，按已确认结构进行同视角重绘。"
        quality = "insufficient" if not blocked else "unknown"
    elif degradation == "mild" or (not candidate and "mild_softness" in clarities):
        mode, action, reason = "reference_edit", "conservative_cleanup_then_review", "轻微软化或噪点需要保守处理及复查；不得把锐化光晕或虚构纹理视为真实改善。"
        quality = "marginal" if not blocked else "unknown"
    elif candidate and ratio is not None and ratio <= (safe if job.get("requires_fine_detail") else marginal):
        if fit == "local_change":
            mode, action, reason = "reference_edit", "edit_environment", "商品清晰且视角匹配，但局部环境或光照需要调整。"
        else:
            mode, action, reason = "pixel_composite", "reuse_verified_pixels", "选中的商品区域清晰且适配目标画面，按其实际像素与目标占比复用。"
        if ratio > safe:
            quality = "marginal" if not blocked else "unknown"
    elif whole and evidence == "sufficient":
        mode, action, reason = "reference_generate", "redraw_from_confirmed_evidence", "没有满足目标尺寸与区域清晰度要求的可复用商品像素；由多参考实拍证据支持重绘。"
    else:
        reason = "先审阅每张商品区域及目标画面；不能用文件大小或边缘分数代替视觉判断。"
    if not whole:
        blocked.append("SOURCE_WHOLE_PRODUCT_REFERENCE_REQUIRED")
    for detail in _required_details(manifest, job):
        confirmed = detail.get("visual_confirmation") == "confirmed" and detail.get("evidence_level") == "visual_confirmed"
        readable = False
        for location in detail.get("locations", []):
            ref = refs.get(location.get("reference_id"))
            if not ref or _review_problems(ref) or not _real_evidence(ref, refs):
                continue
            size = ref.get("product_pixel_size", [])
            box = location.get("bbox_in_product_norm")
            if len(size) != 2 or not _bbox_valid(box):
                continue
            dims = (size[0] * box[2], size[1] * box[3])
            if max(dims) >= 32 and min(dims) >= 8:
                # Global source clarity may differ from this explicitly reviewed detail.
                loc_confirmation = location.get("visual_confirmation", detail.get("visual_confirmation"))
                readable = readable or loc_confirmation == "confirmed"
        if not confirmed or not readable:
            blocked.append(f"SOURCE_REQUIRED_DETAIL_UNVERIFIABLE:{detail.get('id')}")
    if pixel_id and pixel_id not in {ref["id"] for ref in same_view}:
        blocked.append("SOURCE_PIXEL_REFERENCE_NOT_MATCHED")
    if not assessment.get("reason", "").strip():
        blocked.append("SOURCE_ASSESSMENT_REASON_REQUIRED")
    layer_blockers = _layer_blockers(manifest, job, refs, candidate["id"] if candidate else None) if mode == "pixel_composite" else []
    blocked.extend(layer_blockers)
    return {
        "recommended_mode": mode, "reason": reason, "suggested_action": action,
        "blocked_reasons": list(dict.fromkeys(blocked)), "selected_reference_ids": selected,
        "layer_blockers": layer_blockers,
        "pixel_source_reference_id": candidate["id"] if candidate else None,
        "source_quality": quality, "effective_upscale_ratio": round(ratio, 4) if ratio is not None else None,
        "reference_upscale_ratios": {rid: round(value, 4) for rid, value in ratios.items()},
        "source_quality_by_reference": {ref["id"]: {"clarity": ref.get("quality_review", {}).get("clarity", "unknown"),
                                                       "evidence": ref.get("quality_review", {}).get("evidence", "unknown")} for ref in available},
        "new_view": new_view, "assessment_context_fingerprint": context_hash,
        "required_reference_hashes": expected_hashes,
        "required_output_checks": ["geometry", "material", "components", "scene_scale", "clarity"],
        "require_output_detail_relocation": new_view,
    }


def validate_quality(manifest: dict[str, Any]) -> list[str]:
    """Validate input types/enums; pending reviews are runtime blockers, not schema errors."""
    errors = []
    for ref in manifest.get("references", []):
        prefix = f"references[{ref.get('id', '?')}].quality_review"
        review = ref.get("quality_review", {})
        if not isinstance(review, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key, allowed in (("clarity", CLARITIES), ("evidence", EVIDENCE)):
            if not isinstance(review.get(key, "unknown"), str) or review.get(key, "unknown") not in allowed:
                errors.append(f"{prefix}.{key} must be one of {sorted(allowed)}")
        if not isinstance(review.get("defects", []), list) or not all(isinstance(d, str) for d in review.get("defects", [])):
            errors.append(f"{prefix}.defects must be a list of strings")
        for key in ("notes", "reviewed_sha256", "reviewed_region_fingerprint"):
            if not isinstance(review.get(key, ""), str):
                errors.append(f"{prefix}.{key} must be a string")
        provenance = ref.get("provenance", {})
        provenance_prefix = f"references[{ref.get('id', '?')}].provenance"
        if not isinstance(provenance, dict):
            errors.append(f"{provenance_prefix} must be an object")
        else:
            kind = provenance.get("kind", "real_photo")
            if not isinstance(kind, str) or kind not in {"real_photo", "generated", "restored"}:
                errors.append(f"{provenance_prefix}.kind must be real_photo, generated, or restored")
            ids = provenance.get("source_reference_ids", [])
            if not isinstance(ids, list) or not all(isinstance(rid, str) for rid in ids):
                errors.append(f"{provenance_prefix}.source_reference_ids must be a list of reference IDs")
            hashes = provenance.get("reviewed_source_hashes", {})
            if not isinstance(hashes, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in hashes.items()):
                errors.append(f"{provenance_prefix}.reviewed_source_hashes must map reference IDs to hashes")
    for job in manifest.get("jobs", []):
        prefix = f"jobs[{job.get('id', '?')}].source_assessment"
        review = job.get("source_assessment", {})
        if not isinstance(review, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key, allowed in (("scene_fit", FITS), ("evidence", EVIDENCE), ("degradation", DEGRADATIONS)):
            if not isinstance(review.get(key, "unknown"), str) or review.get(key, "unknown") not in allowed:
                errors.append(f"{prefix}.{key} must be one of {sorted(allowed)}")
        for key in ("reason", "reviewed_context_fingerprint"):
            if not isinstance(review.get(key, ""), str):
                errors.append(f"{prefix}.{key} must be a string")
        hashes = review.get("reviewed_reference_hashes", {})
        if not isinstance(hashes, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in hashes.items()):
            errors.append(f"{prefix}.reviewed_reference_hashes must map reference IDs to hashes")
        valid_layers = True
        layers = job.get("product_layers", [])
        if not isinstance(layers, list):
            errors.append(f"jobs[{job.get('id', '?')}].product_layers must be a list")
            layers = []
            valid_layers = False
        for index, layer in enumerate(layers):
            layer_prefix = f"jobs[{job.get('id', '?')}].product_layers[{index}]"
            if not isinstance(layer, dict):
                errors.append(f"{layer_prefix} must be an object")
                valid_layers = False
                continue
            source_ids = layer.get("source_reference_ids", [])
            if not isinstance(source_ids, list) or not all(isinstance(rid, str) for rid in source_ids):
                errors.append(f"{layer_prefix}.source_reference_ids must be a list of reference IDs")
                valid_layers = False
            binding = layer.get("source_binding", {})
            if not isinstance(binding, dict):
                errors.append(f"{layer_prefix}.source_binding must be an object")
                valid_layers = False
                continue
            if not isinstance(binding.get("reviewed", False), bool):
                errors.append(f"{layer_prefix}.source_binding.reviewed must be boolean")
            binding_hashes = binding.get("source_reference_hashes", {})
            if not isinstance(binding_hashes, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in binding_hashes.items()):
                errors.append(f"{layer_prefix}.source_binding.source_reference_hashes must map reference IDs to hashes")
                valid_layers = False
            for key in ("reviewed_asset_sha256", "reviewed_mask_sha256"):
                if binding.get(key) is not None and not isinstance(binding[key], str):
                    errors.append(f"{layer_prefix}.source_binding.{key} must be a hash string or null")
        records = job.get("layer_asset_hashes", [])
        if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
            errors.append(f"jobs[{job.get('id', '?')}].layer_asset_hashes must be a list of objects from assess_sources")
        matched = review.get("matched_reference_ids", [])
        if not isinstance(matched, list) or not all(isinstance(rid, str) for rid in matched):
            errors.append(f"{prefix}.matched_reference_ids must be a list of reference IDs")
        elif valid_layers and any(rid not in _reference_ids(manifest, job) for rid in matched):
            errors.append(f"{prefix}.matched_reference_ids must identify a job source or product layer")
    return errors
