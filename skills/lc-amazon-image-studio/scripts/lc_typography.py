"""Opt-in design-first typography and raster checks; no model or approval calls."""
from __future__ import annotations

import copy
import math
import re
from pathlib import Path
import numpy as np
from PIL import Image

ROLES = {"headline", "body", "label", "accent", "graphic"}


def default_contract():
    return {"version": 3, "selection": "design_first", "color_roles": {}, "font_roles": {},
            "body_weight": 400, "label_weight": 400, "min_contrast_ratio": 4.5,
            "mobile_sizes": {"headline": 24, "body": 12, "label": 12},
            "allowed_adjustments": ["lightness", "position", "local_surface"]}


def validate_contract(style):
    errors = []
    for key in ("color_roles", "font_roles"):
        values = style.get(key, {})
        if not isinstance(values, dict) or set(values) - ROLES:
            errors.append(f"style_contract.{key} must map supported typography roles")
            continue
        for role, value in values.items():
            if key == "color_roles":
                if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                    errors.append(f"style_contract.color_roles.{role} must be #RRGGBB")
            elif (not isinstance(value, dict) or set(value) != {"family", "weight"}
                  or not isinstance(value.get("family"), str) or value.get("family") not in {"sans", "serif"}
                  or type(value.get("weight")) is not int
                  or value["weight"] not in ({400, 600} if value["family"] == "serif" else {400, 600, 700})):
                errors.append(f"style_contract.font_roles.{role} needs supported family and weight")
    allowed = style.get("allowed_adjustments", [])
    if not isinstance(allowed, list) or any(not isinstance(x, str) or x not in {"lightness", "position", "local_surface"} for x in allowed):
        errors.append("style_contract.allowed_adjustments supports lightness/position/local_surface")
    return errors


def resolve_layout(job, layout):
    """Resolve a copy only: explicit design values never become overwritten output."""
    style = job["_project_style"]
    colors, fonts = style["color_roles"], style["font_roles"]
    layout = copy.deepcopy(layout)
    layout.setdefault("mobile_sizes", copy.deepcopy(style["mobile_sizes"]))
    layout.setdefault("body_weight", style["body_weight"])
    layout.setdefault("label_weight", style["label_weight"])
    raw_layout = job.get("layout") or {}
    raw_groups = raw_layout.get("text_groups", [])
    for index, group in enumerate(layout.get("text_groups", [])):
        raw = next((g for g in raw_groups if g.get("id") == group.get("id")), {}) if group.get("id") else (raw_groups[index] if index < len(raw_groups) else {})
        role = group.get("color_role", "headline" if group.get("headline") else "body")
        font_role = group.get("font_role", role)
        if not isinstance(role, str) or not isinstance(font_role, str) or role not in ROLES or font_role not in ROLES:
            raise ValueError("Text color_role/font_role must name a supported typography role")
        role_color = colors.get(role, colors.get("body") if role == "label" else None)
        color = raw.get("text_color", raw_layout.get("text_color", role_color if role_color is not None else group.get("text_color", layout.get("text_color"))))
        if color is None:
            raise ValueError(f"DESIGN_COLOR_REQUIRED:{group.get('id', role)}: choose a product-specific role or explicit text_color")
        group["text_color"] = color
        face = fonts.get(font_role, fonts.get("headline", {}) if group.get("headline") else {})
        for key, source in (("headline_family", "family"), ("headline_weight", "weight")):
            if key not in raw and key not in raw_layout and source in face:
                group[key] = face[source]
        group.setdefault("body_weight", style["body_weight"])
        group.setdefault("label_weight", style["label_weight"])
        group.setdefault("mobile_sizes", copy.deepcopy(layout["mobile_sizes"]))
    layout.setdefault("graphic_color", colors.get("graphic", colors.get("accent", colors.get("body", layout.get("text_color", "#29251F")))))
    layout.setdefault("graphic_text_color", colors.get("label", colors.get("body", layout.get("text_color", "#29251F"))))
    return layout


def enabled(job):
    from lc_title_effects import has_effect
    from lc_design import has_marketing_text
    return (job.get("kind") != "main" and job.get("text_mode", "local_overlay") == "local_overlay"
            and ((job.get("layout") or {}).get("version") == 3)
            and has_marketing_text(job)
            and (job.get("_project_style", {}).get("version") == 3 or has_effect(job)))


def decision(job, resolved):
    """Audit requested roles separately from final resolved values; no silent repair."""
    previous = {g.get("id"): g for g in job.get("layout_result", {}).get("typography_decision", {}).get("resolved_groups", [])}
    groups = [{key: copy.deepcopy(g[key]) for key in
               ("id", "color_role", "font_role", "text_color", "headline_family", "headline_weight", "mobile_sizes", "surface", "box")
               if key in g} for g in resolved.get("text_groups", [])]
    adjustments = copy.deepcopy(job.get("layout_result", {}).get("typography_decision", {}).get("adjustments", []))
    adjustments += [{"group_id": g.get("id"), "before": previous[g.get("id")], "after": g,
                    "automatic": False, "reason": "Explicit project/layout configuration changed"}
                   for g in groups if g.get("id") in previous and previous[g.get("id")] != g]
    return {"version": 3, "selection": "design_first", "requested": copy.deepcopy(job.get("_project_style", {})),
            "explicit_layout": copy.deepcopy(job.get("layout", {})),
            "resolved_groups": groups,
            "adjustments": adjustments, "on_failure": "layout_repair_needed",
            "allowed_adjustments": job.get("_project_style", {}).get("allowed_adjustments", [])}


def luminance(image):
    a = np.asarray(image, dtype=np.float32) / 255
    a = np.where(a <= .04045, a / 12.92, ((a + .055) / 1.055) ** 2.4)
    return a @ np.array([.2126, .7152, .0722], dtype=np.float32)


def include_glyph_overhang(mask, bboxes):
    """Include ink outside DOM advance boxes (e.g. Serif italic/side bearings).

    Accepted layouts have nonoverlapping text boxes. Assign fringe pixels to
    their nearest box, retaining the original conservative line bounds. This
    uses the existing shared mask rather than launching a renderer per title.
    """
    result = copy.deepcopy(bboxes)
    texts = [b for b in result if b.get("kind") == "text"]
    ys, xs = np.nonzero(np.asarray(mask.convert("L")) > 0)
    if not texts or not xs.size:
        return result
    best = np.full(xs.size, np.inf, dtype=np.float64)
    owners = np.zeros(xs.size, dtype=np.int32)
    for i, item in enumerate(texts):
        box = item["bbox"]
        dx = np.maximum(np.maximum(box["x"] - (xs + .5), xs + .5 - box["x"] - box["width"]), 0)
        dy = np.maximum(np.maximum(box["y"] - (ys + .5), ys + .5 - box["y"] - box["height"]), 0)
        distance = dx * dx + dy * dy
        selected = distance < best
        owners[selected], best[selected] = i, distance[selected]
    for i, item in enumerate(texts):
        selected = owners == i
        if not selected.any():
            continue
        box = item["bbox"]
        left, top = min(box["x"], float(xs[selected].min())), min(box["y"], float(ys[selected].min()))
        right = max(box["x"] + box["width"], float(xs[selected].max() + 1))
        bottom = max(box["y"] + box["height"], float(ys[selected].max() + 1))
        item["advance_bbox"] = copy.deepcopy(box)
        item["bbox"] = {"x": left, "y": top, "width": right-left, "height": bottom-top}
    return result


def raster_contrast(image, background, mask, bboxes):
    """Glyph-core checks deliberately exclude anti-alias fringe and exterior shadows."""
    fg, bg = luminance(image), luminance(background)
    core = np.asarray(mask.convert("L")) >= 245
    checks = []
    for item in bboxes:
        if item.get("kind") != "text":
            continue
        box = item["bbox"]
        x, y = max(0, math.floor(box["x"])), max(0, math.floor(box["y"]))
        r, b = min(image.width, math.ceil(box["x"] + box["width"])), min(image.height, math.ceil(box["y"] + box["height"]))
        selected = core[y:b, x:r]
        a, z = fg[y:b, x:r][selected], bg[y:b, x:r][selected]
        ratios = (np.maximum(a, z) + .05) / (np.minimum(a, z) + .05)
        minimum = float(ratios.min()) if ratios.size else 0
        checks.append({"check": "glyph_contrast", "element": item["id"], "passed": minimum >= 4.5,
                       "ratio_min": round(minimum, 4), "ratio_p05": round(float(np.quantile(ratios, .05)), 4) if ratios.size else 0,
                       "minimum": 4.5, "core_pixels": int(ratios.size),
                       "method": "actual raster glyph core alpha >=245 against rendered text-free background"})
    return checks


def proof_paths(base, job_id):
    root = Path(base) / "review/layouts"
    return {"background": root / f"{job_id}-background.png", "glyph_mask": root / f"{job_id}-glyphs.png"}


def check_export(job, base, final):
    paths = proof_paths(base, job["id"])
    with Image.open(final) as image, Image.open(paths["background"]) as background, Image.open(paths["glyph_mask"]) as mask:
        if image.size != background.size or image.size != mask.size:
            raise ValueError("Typography proof dimensions changed")
        checks = raster_contrast(image.convert("RGB"), background.convert("RGB"), mask, job["layout_result"]["bboxes"])
    from lc_assets import file_hash
    return {"passed": bool(checks) and all(x["passed"] for x in checks), "checks": checks,
            "final_sha256": file_hash(Path(final)),
            "proof_hashes": {name: file_hash(path) for name, path in paths.items()},
            "stage": "final_encoded_image", "quality": job.get("export", {}).get("quality")}


def proof_current(job, base):
    from lc_assets import file_hash
    expected = job.get("layout_result", {}).get("typography_proof_hashes", {})
    return all(path.is_file() and expected.get(name) == file_hash(path)
               for name, path in proof_paths(base, job["id"]).items())


def export_checked(image, job, base, final):
    """Use the existing encoder, then inspect its actual delivered glyph pixels."""
    from lc_assets import export_image
    result = export_image(image, job, final)
    if not enabled(job):
        return result
    if not proof_current(job, base):
        raise ValueError("TYPOGRAPHY_PROOF_STALE: rebuild the affected layout")
    review = check_export(job, base, final)
    attempts = [{"quality": review["quality"], "passed": review["passed"]}]
    if not review["passed"] and Path(final).suffix.lower() in {".jpg", ".jpeg"} and job.get("export", {}).get("quality") == 92:
        job["export"]["quality"] = 95
        result = export_image(image, job, final)
        review = check_export(job, base, final)
        attempts.append({"quality": 95, "passed": review["passed"]})
    review["encoding_attempts"] = attempts
    result["typography"] = review
    if not review["passed"]:
        # Keep the failed encoded proof for a focused local repair, never approve it.
        job["export_result"] = result
        raise ValueError("FINAL_GLYPH_CONTRAST: adjust the affected design within allowed_adjustments; preserve copy and mobile size")
    return result


def export_evidence_issues(manifest, job, base, final):
    """Missing disposable proofs are allowed only with bound, real QA evidence."""
    if not enabled(job):
        return []
    from lc_assets import file_hash
    from lc_delivery import artifact_sha256
    result = job.get("export_result", {}).get("typography", {})
    if not result.get("passed") or result.get("final_sha256") != file_hash(Path(final)):
        return ["FINAL_GLYPH_CONTRAST_EVIDENCE_MISSING_OR_STALE"]
    for key, path in proof_paths(base, job["id"]).items():
        actual = artifact_sha256(manifest, job, base, path)
        if actual is None or actual != result.get("proof_hashes", {}).get(key):
            return ["TYPOGRAPHY_PROOF_STALE"]
    return []
