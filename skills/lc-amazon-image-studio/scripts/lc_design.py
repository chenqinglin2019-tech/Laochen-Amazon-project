"""Small, side-effect-free design/text routing helpers shared by both pipelines.

An absent text_mode deliberately preserves legacy behaviour and fingerprints.
Model lettering and local lettering are mutually exclusive sources of copy.
"""
from __future__ import annotations

import json
import hashlib
import math
import re
from pathlib import Path
from typing import Any

TEXT_MODES = {"none", "local_overlay", "model_native"}


def _layout(job: dict) -> dict:
    value = job.get("layout")
    return value if isinstance(value, dict) else {}


def _layout_blocks(layout: dict) -> list[dict]:
    if not isinstance(layout, dict):
        return []
    result = []
    def add(identifier, role, text, evidence=()):
        if isinstance(text, str) and text.strip():
            result.append({"id": identifier, "role": role, "text": text, "evidence_refs": list(evidence or ())})
    for key in ("headline", "body", "label"):
        add(key, key, layout.get(key))
    for index, group in enumerate(layout.get("text_groups", []) or []):
        if not isinstance(group, dict):
            continue
        for key in ("headline", "body", "label"):
            add(f"group:{group.get('id', index)}:{key}", key, group.get(key), group.get("evidence_refs"))
    for index, item in enumerate(layout.get("items", []) or []):
        if not isinstance(item, dict):
            continue
        add(f"item:{item.get('id', index)}", "label", item.get("text"), item.get("evidence_refs"))
    for index, item in enumerate(layout.get("faq", []) or []):
        if not isinstance(item, dict):
            continue
        for key in ("question", "answer"):
            add(f"faq:{index}:{key}", key, item.get(key), item.get("evidence_refs"))
    return result


def resolve_text_mode(job: dict) -> str:
    if "text_mode" in job:
        return job["text_mode"]
    # Legacy items (including icon-only items) still need their renderer.
    layout = _layout(job)
    return "local_overlay" if (_layout_blocks(layout) or layout.get("items") or job.get("text_overlays")) else "none"


def copy_blocks(job: dict) -> list[dict]:
    if resolve_text_mode(job) == "model_native":
        value = job.get("copy") or {}
        if not isinstance(value, dict):
            return []
        return [{"id": key, "role": key, "text": value[key], "evidence_refs": list(job.get("claim_ids", []))}
                for key in ("headline", "body") if isinstance(value.get(key), str) and value[key].strip()]
    return _layout_blocks(_layout(job))


def has_marketing_text(job: dict) -> bool:
    return bool(copy_blocks(job) or job.get("text_overlays"))


def needs_local_layout(job: dict) -> bool:
    if resolve_text_mode(job) == "model_native":
        return False
    layout = _layout(job)
    # A text-free grid still needs its local image panels composed.
    return bool(copy_blocks(job) or layout.get("items") or layout.get("panels") or job.get("text_overlays"))


def requires_visual_design(job: dict) -> bool:
    return ("text_mode" in job or bool(job.get("design_brief"))
            or (_layout(job).get("version") in {2, 3} and has_marketing_text(job)))


def required_design_unresolved(job: dict) -> bool:
    value = job.get("design_resolution") or {}
    return bool((value.get("required") is True or value.get("source") == "user_reference")
                and design_reference_issue(job))


def design_reference_issue(job: dict) -> str | None:
    """Recheck only explicitly chosen external design evidence, not model inputs.

    A file change blocks new dispatch/starts and invalidates design review; it
    deliberately does not change the compiled generation hash or delay ingest.
    """
    resolution = job.get("design_resolution") or {}
    if resolution.get("status") == "needs_input":
        return "design_reference_needs_input"
    if resolution.get("source") in {"template_library", "original_design"}:
        from lc_template_workflow import template_resolution_issue
        return template_resolution_issue(job)
    if resolution.get("status") != "selected" or resolution.get("source") != "user_reference":
        return None
    reference = resolution.get("reference") or {}
    path, expected = reference.get("external_path"), reference.get("sha256")
    if not isinstance(path, str) or not path or not isinstance(expected, str) or not expected:
        return "design_reference_binding_missing"
    try:
        source = Path(path)
        if not source.is_absolute() or not source.is_file():
            return "design_reference_missing"
        actual = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                actual.update(chunk)
        return None if actual.hexdigest() == expected else "design_reference_changed"
    except OSError:
        return "design_reference_unreadable"


def scene_layer_panels(job: dict) -> list[dict]:
    """Describe visible, already-composited scene tiles without drawing them twice."""
    layout = _layout(job)
    recipe = layout.get("recipe") or (job.get("design_brief") or {}).get("layout", {}).get("recipe")
    layers = job.get("product_layers") or []
    if (job.get("render_mode") != "pixel_composite" or recipe != "scene_grid" or layout.get("panels")
            or not layers or any(not layer.get("opaque_rectangle") or layer.get("mask_path") for layer in layers)):
        return []
    return [{"id": f"layer-{index}", "image": layer.get("asset_path"), "reference_id": layer.get("reference_id"),
             "evidence_refs": [layer.get("reference_id")], "box": layer.get("bbox_norm", job.get("target_product_bbox_norm")),
             "source_crop": layer.get("crop_bbox_norm") or [0, 0, 1, 1], "fit": "contain"}
            for index, layer in enumerate(layers)]


def has_panel_sources(job: dict) -> bool:
    return bool(_layout(job).get("panels") or scene_layer_panels(job))


def design_generation_payload(job: dict) -> dict:
    brief = job.get("design_brief") or {}
    result = dict(brief.get("generation") or {})
    if resolve_text_mode(job) == "model_native" and brief.get("layout"):
        result["integrated_typography"] = brief["layout"]
    if resolve_text_mode(job) == "model_native" and job.get("_project_style"):
        style = job["_project_style"]
        result["project_typography"] = style
        if result.get("integrated_typography"):
            if style.get("version") == 1:
                result["integrated_typography"] = {**result["integrated_typography"],
                    "text_color": style["text_color"], "headline_family": style["font_family"],
                    "headline_weight": style["headline_weight"], "body_weight": style["body_weight"],
                    "label_weight": style["label_weight"], "mobile_sizes": style["mobile_sizes"]}
            else:
                result["integrated_typography"] = {**result["integrated_typography"],
                    "selection": style["selection"], "min_contrast_ratio": style["min_contrast_ratio"],
                    "body_weight": style["body_weight"], "label_weight": style["label_weight"],
                    "mobile_sizes": style["mobile_sizes"]}
    if resolve_text_mode(job) == "model_native" and isinstance(job.get("typography_decision"), dict):
        result["typography_decision"] = job["typography_decision"]
    return result


def design_layout_payload(job: dict) -> dict:
    brief = job.get("design_brief") or {}
    return brief.get("layout") or {}


def design_prompt_lines(job: dict) -> list[str]:
    lines = []
    if "text_mode" in job:
        lines.append(f"Marketing text mode: {resolve_text_mode(job)}.")
    payload = design_generation_payload(job)
    if payload:
        lines.extend(["Visual design brief (design guidance only; product facts remain authoritative):",
                      json.dumps(payload, ensure_ascii=False, sort_keys=True)])
    if resolve_text_mode(job) == "model_native":
        lines.extend(["Compose the complete photographic poster with integrated typography and purposeful graphic design.",
                      "Render exactly these approved short copy blocks, once each; do not invent extra copy, badges, claims or logos:",
                      json.dumps(copy_blocks(job), ensure_ascii=False, sort_keys=True),
                      "Render only the text values. Block IDs, roles and evidence references are metadata, not visible copy.",
                      "Choose coherent type hierarchy, line breaks and placement from the design brief. Keep product-critical details unobscured.",
                      "Readability must hold at 360px image width. No local marketing text will be overlaid afterward."])
        embedding = job.get("embedding_decision") or {}
        if embedding.get("kind") == "surface_embedded_3d":
            lines.extend(["Embed the exact headline as a physically credible 3D treatment on this visible carrier surface only:",
                          json.dumps(embedding, ensure_ascii=False, sort_keys=True),
                          "Match the documented material, perspective, contact, and lighting. Do not make the text resemble or replace a product label."])
        if job.get("_project_style", {}).get("version") == 1:
            lines.append("The project typography contract is mandatory for all visible marketing text, labels and diagrams; do not introduce alternate text colors or fonts.")
    return lines


def validate_design(job: dict) -> list[str]:
    errors = []
    from lc_title_effects import validate_config
    errors.extend(validate_config(job))
    mode = resolve_text_mode(job)
    if not isinstance(mode, str) or mode not in TEXT_MODES:
        errors.append("text_mode must be none, local_overlay or model_native")
    value = job.get("copy")
    if value is not None and mode != "model_native":
        errors.append("job.copy is model_native-only; local copy belongs to layout")
    if mode == "model_native":
        if job.get("kind") == "main" or job.get("render_mode") == "pixel_composite":
            errors.append("model_native is unavailable for main images or pixel_composite")
        if not isinstance(value, dict) or set(value) - {"headline", "body"}:
            errors.append("model_native copy must contain only headline/body strings")
        elif (not isinstance(value.get("headline"), str) or not value["headline"].strip()
              or any(not isinstance(v, str) for v in value.values())):
            errors.append("model_native requires a nonempty headline and string copy")
        elif len(value["headline"]) > 180 or len(value.get("body", "")) > 200:
            errors.append("model_native is short-copy only (headline <=180, body <=200 characters)")
        layout = _layout(job)
        if _layout_blocks(layout) or layout.get("items") or layout.get("panels") or job.get("text_overlays"):
            errors.append("model_native cannot also contain local text, icons or panels")
    if mode == "none" and (_layout_blocks(_layout(job)) or value or job.get("text_overlays")):
        errors.append("text_mode none cannot contain marketing copy")
    if job.get("kind") == "main" and has_marketing_text(job):
        errors.append("main images cannot contain marketing copy")
    embedding = job.get("embedding_decision")
    if embedding is not None:
        allowed = {"kind", "reason", "surface", "material_lighting"}
        if not isinstance(embedding, dict) or set(embedding) - allowed or embedding.get("kind") not in {"none", "surface_embedded_3d"}:
            errors.append("embedding_decision must use kind none/surface_embedded_3d and documented fields")
        elif embedding["kind"] == "surface_embedded_3d":
            required = ("reason", "surface", "material_lighting")
            if any(not isinstance(embedding.get(key), str) or not embedding[key].strip() for key in required):
                errors.append("surface_embedded_3d requires reason, surface and material_lighting")
            if mode != "model_native":
                errors.append("surface_embedded_3d requires model_native; do not add local duplicate text")
            headline = value.get("headline", "") if isinstance(value, dict) else ""
            body = value.get("body", "") if isinstance(value, dict) else ""
            from lc_project_contracts import word_count
            if not isinstance(headline, str) or not 1 <= word_count(headline) <= 5 or re.search(r"\d", headline):
                errors.append("surface_embedded_3d requires a 1-5 word decorative headline without numbers")
            if body.strip() or job.get("claim_ids"):
                errors.append("surface_embedded_3d cannot carry body copy or fact-bound claims")
    brief = job.get("design_brief")
    if brief is not None:
        if not isinstance(brief, dict):
            errors.append("design_brief must be an object")
        else:
            for key in ("generation", "layout"):
                if key in brief and not isinstance(brief[key], dict):
                    errors.append(f"design_brief.{key} must be an object")
    from lc_project_contracts import style_job_issues
    return errors + style_job_issues(job)


def normalized_copy(text: str) -> str:
    # Line breaks and inter-word spacing may change, not spelling/punctuation.
    return re.sub(r"\s+", " ", text).strip()


def native_text_review_issues(job: dict, review: Any) -> list[str]:
    """Validate a real transcription, never manufacture observations from copy."""
    if resolve_text_mode(job) != "model_native":
        return []
    if not isinstance(review, dict):
        return ["MODEL_TEXT_REVIEW_MISSING"]
    if review.get("verdict") not in {"pass", "fail"} or not isinstance(review.get("notes"), str) or not review["notes"].strip():
        return ["MODEL_TEXT_REVIEW_EXPLICIT_VERDICT_REQUIRED"]
    if not isinstance(review.get("unexpected_text"), list) or any(not isinstance(value, str) for value in review["unexpected_text"]):
        return ["MODEL_TEXT_UNEXPECTED_INVENTORY_REQUIRED"]
    expected = {b["id"]: b for b in copy_blocks(job)}
    blocks = review.get("blocks")
    if not isinstance(blocks, list) or len(blocks) != len(expected):
        return ["MODEL_TEXT_TRANSCRIPTION_INCOMPLETE"]
    issues, seen = [], set()
    for block in blocks:
        if not isinstance(block, dict):
            issues.append("MODEL_TEXT_BLOCK_INVALID"); continue
        identifier = block.get("id")
        if identifier not in expected or identifier in seen:
            issues.append("MODEL_TEXT_BLOCK_ID_INVALID"); continue
        seen.add(identifier)
        if not isinstance(block.get("text"), str):
            issues.append("MODEL_TEXT_TRANSCRIPTION_REQUIRED")
        elif normalized_copy(block["text"]) != normalized_copy(expected[identifier]["text"]):
            issues.append("MODEL_TEXT_COPY_MISMATCH")
        box = block.get("bbox_norm")
        if (not isinstance(box, list) or len(box) != 4
            or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in box)
            or any(n < 0 or n > 1 for n in box) or box[2] <= 0 or box[3] <= 0
            or box[0] + box[2] > 1.000001 or box[1] + box[3] > 1.000001):
            issues.append("MODEL_TEXT_REGION_INVALID")
    if review["unexpected_text"]:
        issues.append("MODEL_TEXT_UNEXPECTED_TEXT")
    if review["verdict"] != "pass":
        issues.append("MODEL_TEXT_REVIEW_FAILED")
    embedding = job.get("embedding_decision") or {}
    if embedding.get("kind") == "surface_embedded_3d":
        embedded = review.get("embedding")
        required = ("carrier_surface_visible", "material_perspective_pass", "lighting_contact_pass",
                    "readable_original", "readable_360", "product_label_unchanged")
        if (not isinstance(embedded, dict)
                or any(not isinstance(embedded.get(key), bool) for key in required)
                or not isinstance(embedded.get("observed_surface"), str)
                or not embedded["observed_surface"].strip()
                or not isinstance(embedded.get("notes"), str)
                or not embedded["notes"].strip()):
            issues.append("SURFACE_EMBEDDING_REVIEW_REQUIRED")
        elif any(embedded[key] is not True for key in required):
            issues.append("SURFACE_EMBEDDING_REVIEW_FAILED")
    return sorted(set(issues))


def panel_contracts(manifest: dict, job: dict, base) -> list[dict]:
    """Read-only pixel/source/crop contracts, shared by package and stale checks.

    A fact ID is not pixel provenance. Every image panel must point to a
    registered source image, whose generated/restored provenance reaches photos.
    """
    panels = _layout(job).get("panels") or scene_layer_panels(job)
    if not panels:
        return []
    from PIL import Image
    import lc_image_pipeline as p
    from lc_layout import layout_geometry
    from lc_layout_v3 import mapped_product_box, panel_placement
    references = {ref["id"]: ref for ref in manifest.get("references", [])}
    slots = (layout_geometry(job)["panels"] if _layout(job).get("panels")
             else [{"id": panel["id"], "box": panel["box"]} for panel in panels])
    records = []
    for index, (panel, slot) in enumerate(zip(panels, slots)):
        if not panel.get("image"):
            panel = {**panel, "image": references.get(panel.get("reference_id"), {}).get("path")}
        path = p.resolve_project_path(panel["image"], base, "panel image")
        file_hash = p.sha256_file(path) if path and path.is_file() else "MISSING"
        evidence = panel.get("evidence_refs", [])
        matched = [ref for rid, ref in references.items() if path and rid in evidence
                   and p.resolve_path(ref.get("path"), base) == path]
        errors, sources = [], []
        if not matched:
            errors.append("PANEL_REGISTERED_IMAGE_REFERENCE_REQUIRED")
        for ref in matched:
            provenance = ref.get("provenance") or {"kind": "real_photo"}
            kind = provenance.get("kind", "real_photo")
            bindings = {}
            if kind in {"generated", "restored"}:
                ids = provenance.get("source_reference_ids", [])
                if not ids or provenance.get("qa_verdict") != "pass":
                    errors.append("PANEL_GENERATED_PROVENANCE_UNREVIEWED")
                for source_id in ids:
                    source = references.get(source_id)
                    if not source or source.get("provenance", {}).get("kind", "real_photo") != "real_photo":
                        errors.append("PANEL_REAL_PHOTO_SOURCE_REQUIRED")
                        continue
                    source_path = p.resolve_path(source.get("path"), base)
                    actual = p.sha256_file(source_path) if source_path and source_path.is_file() else "MISSING"
                    bindings[source_id] = actual
                    if actual == "MISSING" or provenance.get("reviewed_source_hashes", {}).get(source_id) != actual:
                        errors.append("PANEL_SOURCE_BINDING_STALE")
            elif kind != "real_photo":
                errors.append("PANEL_PROVENANCE_KIND_INVALID")
            sources.append({"id": ref["id"], "path": ref["path"], "provenance": provenance,
                            "source_hashes": bindings})
        if file_hash == "MISSING":
            errors.append("PANEL_IMAGE_MISSING")
            size = [1, 1]
        else:
            with Image.open(path) as image:
                size = list(image.size)
        product_bbox = panel.get("product_bbox_norm")
        if product_bbox is None and scene_layer_panels(job) and matched:
            product_bbox = matched[0].get("product_bbox_norm")
        normalized = {**panel, "product_bbox_norm": product_bbox, "box": slot["box"], "source_size": size, "fit": panel.get("fit", "cover")}
        normalized["source_crop"] = panel.get("source_crop") or [0, 0, 1, 1]
        normalized["placement"] = panel_placement(normalized, job["canvas"])
        records.append({"id": slot["id"], "image": panel["image"], "image_sha256": file_hash,
                        "evidence_refs": evidence, "sources": sources, "box": slot["box"],
                        "source_crop": panel.get("source_crop", [0, 0, 1, 1]), "fit": normalized["fit"],
                        "product_bbox_norm": product_bbox,
                        "mapped_product_bbox_norm": mapped_product_box(normalized, job["canvas"]),
                        "errors": sorted(set(errors))})
    return records


def panel_review_issues(contracts: list[dict], reviews: Any) -> list[str]:
    if not contracts:
        return []
    issues = [f"{contract['id']}:{error}" for contract in contracts for error in contract.get("errors", [])]
    if not isinstance(reviews, dict) or set(reviews) != {contract["id"] for contract in contracts}:
        return issues + ["PANEL_REVIEWS_INCOMPLETE"]
    for contract in contracts:
        review = reviews[contract["id"]]
        if not isinstance(review, dict) or set(review) != {"provenance", "product_identity", "crop"}:
            issues.append(f"{contract['id']}:PANEL_REVIEW_FIELDS_REQUIRED")
            continue
        for key, result in review.items():
            if (not isinstance(result, dict) or result.get("verdict") not in {"pass", "fail"}
                    or not isinstance(result.get("notes"), str) or not result["notes"].strip()):
                issues.append(f"{contract['id']}:{key}:PANEL_EXPLICIT_REVIEW_REQUIRED")
            elif result["verdict"] == "fail":
                issues.append(f"{contract['id']}:{key}:PANEL_REVIEW_FAILED")
    return issues
