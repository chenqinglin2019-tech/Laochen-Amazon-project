"""Bounded, optional title edits on top of the existing local renderer.

The caller owns the manifest lock and persistence.  No function calls a model or
approves an image.  One group.decorative_effect may replace that group's exact
headline; all other copy stays in the locally rendered flat image.  Attempts
live outside the disposable prepared state and survive re-prepare/fallback.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import time
import uuid

from PIL import Image, ImageChops, ImageDraw


class TitleEffectError(ValueError):
    pass


_REVIEW_FLAGS = ("readable_original", "readable_360", "carrier_surface_visible",
                 "material_perspective_pass", "lighting_contact_pass",
                 "product_unchanged", "other_text_unchanged", "decorative_only")
_LIMITS = {"initial": 1, "quality_repair": 1, "transient_retry": 2}


def has_effect(job):
    return any(isinstance(g, dict) and g.get("decorative_effect") not in (None, {"kind": "none"})
               for g in (job.get("layout") or {}).get("text_groups", []))


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _path(base, value, *, external=False):
    if not isinstance(value, (str, Path)) or not str(value) or "://" in str(value):
        raise TitleEffectError("TITLE_EFFECT_LOCAL_PATH_REQUIRED")
    base, path = Path(base).resolve(), Path(value)
    path = path.resolve() if path.is_absolute() else (base / path).resolve()
    if not external and not path.is_relative_to(base):
        raise TitleEffectError("TITLE_EFFECT_OUT_OF_PROJECT_PATH")
    if not path.is_file():
        raise TitleEffectError("TITLE_EFFECT_SOURCE_MISSING")
    return path


def _box(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value)
            or min(value) < 0 or min(value[2:]) <= 0
            or value[0] + value[2] > 1.000001 or value[1] + value[3] > 1.000001):
        raise TitleEffectError("TITLE_EFFECT_REGION_INVALID")
    return list(value)


def _folder(base, job):
    identifier = job.get("id")
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", identifier):
        raise TitleEffectError("TITLE_EFFECT_JOB_ID_INVALID")
    folder = Path(base).resolve() / "title_effects" / identifier
    if not folder.resolve().is_relative_to(Path(base).resolve()):
        raise TitleEffectError("TITLE_EFFECT_OUT_OF_PROJECT_PATH")
    return folder


def _snapshot(base, job, value, label, *, external=False):
    path = _path(base, value, external=external)
    sha = _hash(path)
    folder = _folder(base, job)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{label}-{sha}{path.suffix.lower()}"
    if target.exists() and _hash(target) != sha:
        raise TitleEffectError("TITLE_EFFECT_ARCHIVE_TAMPERED")
    if not target.exists():
        shutil.copyfile(path, target)
    return {"path": str(target.relative_to(Path(base).resolve())), "sha256": sha}


def _image(base, record, *, mode=None, size=None):
    path = _path(base, record.get("path"))
    if _hash(path) != record.get("sha256"):
        raise TitleEffectError("TITLE_EFFECT_ARTIFACT_CHANGED")
    with Image.open(path) as source:
        source.load()
        if size and tuple(size) != source.size:
            raise TitleEffectError("TITLE_EFFECT_CANVAS_MISMATCH")
        if mode == "L" and source.mode not in {"1", "L"}:
            raise TitleEffectError("TITLE_EFFECT_GRAYSCALE_MASK_REQUIRED")
        if mode != "L" and source.convert("RGBA").getchannel("A").getextrema()[0] != 255:
            raise TitleEffectError("TITLE_EFFECT_OPAQUE_CANVAS_REQUIRED")
        return source.convert(mode or "RGB")


def _sources(manifest, base, identifiers):
    references = {r["id"]: r for r in manifest.get("references", []) if isinstance(r, dict) and "id" in r}
    if not isinstance(identifiers, list) or not identifiers or any(not isinstance(v, str) or not v for v in identifiers):
        raise TitleEffectError("TITLE_EFFECT_REAL_SOURCE_REQUIRED")
    found, visiting = {}, set()

    def visit(identifier):
        if identifier in visiting:
            raise TitleEffectError("TITLE_EFFECT_SOURCE_CYCLE")
        if identifier in found:
            return
        ref = references.get(identifier)
        if ref is None:
            raise TitleEffectError("TITLE_EFFECT_SOURCE_UNREGISTERED")
        path = _path(base, ref.get("path"))
        provenance = ref.get("provenance") or {"kind": "real_photo"}
        if not isinstance(provenance, dict):
            raise TitleEffectError("TITLE_EFFECT_SOURCE_PROVENANCE_INVALID")
        visiting.add(identifier)
        kind = provenance.get("kind", "real_photo")
        if kind in {"generated", "restored"}:
            parents = provenance.get("source_reference_ids")
            if provenance.get("qa_verdict") != "pass" or not isinstance(parents, list) or not parents:
                raise TitleEffectError("TITLE_EFFECT_REAL_SOURCE_REQUIRED")
            for parent in parents:
                visit(parent)
                if provenance.get("reviewed_source_hashes", {}).get(parent) != found[parent]["sha256"]:
                    raise TitleEffectError("TITLE_EFFECT_SOURCE_REVIEW_STALE")
        elif kind != "real_photo":
            raise TitleEffectError("TITLE_EFFECT_REAL_SOURCE_REQUIRED")
        visiting.remove(identifier)
        found[identifier] = {"id": identifier, "path": str(path.relative_to(Path(base).resolve())),
                             "sha256": _hash(path), "provenance": copy.deepcopy(provenance)}

    for identifier in identifiers:
        visit(identifier)
    return [found[key] for key in sorted(found)]


def _configured(job):
    """Validate only declared configuration; no paths, render or source reads."""
    raw_layout = job.get("layout") or {}
    raw_groups = raw_layout.get("text_groups", []) if isinstance(raw_layout, dict) else []
    if not isinstance(raw_groups, list):
        raise TitleEffectError("TITLE_EFFECT_GROUPS_INVALID")
    selected = [g for g in raw_groups if isinstance(g, dict) and g.get("decorative_effect") is not None
                and g.get("decorative_effect") != {"kind": "none"}]
    if not selected:
        return None
    if len(selected) != 1:
        raise TitleEffectError("TITLE_EFFECT_ONE_GROUP_PER_IMAGE")
    if job.get("text_mode") != "local_overlay" or job.get("kind") == "main" or raw_layout.get("version") != 3:
        raise TitleEffectError("TITLE_EFFECT_V3_LOCAL_OVERLAY_ONLY")
    canvas = job.get("canvas")
    if (not isinstance(canvas, (list, tuple)) or len(canvas) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in canvas)):
        raise TitleEffectError("TITLE_EFFECT_CANVAS_INVALID")
    from lc_project_contracts import word_count
    raw = selected[0]
    config = raw["decorative_effect"]
    if (not isinstance(config, dict) or isinstance(config.get("version"), bool) or config.get("version", 1) != 1
            or config.get("kind") != "surface_emboss" or config.get("purpose") != "decorative"):
        raise TitleEffectError("TITLE_EFFECT_DECORATIVE_CONFIG_REQUIRED")
    if any(not isinstance(config.get(key), str) or not config[key].strip()
           for key in ("reason", "surface", "material_lighting")):
        raise TitleEffectError("TITLE_EFFECT_SURFACE_EVIDENCE_REQUIRED")
    _box(config.get("allowed_bbox_norm"))
    treatment = raw.get("headline_treatment")
    if treatment is not None and treatment != {"kind": "plain"}:
        raise TitleEffectError("TITLE_EFFECT_PLAIN_GUIDE_REQUIRED")
    semantic = config.get("semantic_review")
    if not isinstance(semantic, dict) or semantic.get("decorative_only") is not True or any(
            semantic.get(key) is not False for key in ("contains_brand", "contains_facts")):
        raise TitleEffectError("TITLE_EFFECT_SEMANTIC_REVIEW_REQUIRED")
    title = raw.get("headline")
    if not isinstance(title, str) or not 1 <= word_count(title) <= 5 or re.search(r"\d", title):
        raise TitleEffectError("TITLE_EFFECT_SHORT_UNNUMBERED_TITLE_REQUIRED")
    if raw.get("evidence_refs") or raw.get("claim_ids") or raw.get("semantic_role") in {
            "brand", "fact", "specification", "steps", "faq", "restriction", "body"}:
        raise TitleEffectError("TITLE_EFFECT_DECORATIVE_TITLE_ONLY")
    # Explicit semantic attestation remains necessary: arbitrary factual prose
    # cannot be proved decorative by a keyword classifier.
    if re.search(r"\b(?:waterproof|certified|guaranteed|battery|volts?|watts?|hours?|inches?|cm|mm|kg|step|faq)\b|[一二三四五六七八九十百千万零〇两]\s*(?:个|只|件|小时|厘米)|防水|认证|保证|步骤|规格", title, re.I):
        raise TitleEffectError("TITLE_EFFECT_FACTUAL_TITLE_FORBIDDEN")
    brands = []
    for value in (job, job.get("product_truth", {}), job.get("product", {})):
        if isinstance(value, dict):
            brands.extend(value.get(key) for key in ("brand", "brand_name") if isinstance(value.get(key), str))
    if any(brand.strip() and brand.casefold() in title.casefold() for brand in brands):
        raise TitleEffectError("TITLE_EFFECT_BRAND_FORBIDDEN")
    group_id = raw.get("id")
    if not isinstance(group_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", group_id):
        raise TitleEffectError("TITLE_EFFECT_GROUP_ID_REQUIRED")
    if sum(isinstance(g, dict) and g.get("id") == group_id for g in raw_groups) != 1:
        raise TitleEffectError("TITLE_EFFECT_GROUP_ID_AMBIGUOUS")
    if "box" in raw:
        _box(raw["box"])
    identifiers = config.get("source_reference_ids", job.get("source_reference_ids"))
    if not isinstance(identifiers, list) or not identifiers or any(not isinstance(v, str) or not v for v in identifiers):
        raise TitleEffectError("TITLE_EFFECT_REAL_SOURCE_REQUIRED")
    return raw


def validate_config(job):
    """Return structural/title/semantic errors for validate_design, without I/O."""
    try:
        _configured(job)
    except (TitleEffectError, KeyError, TypeError, ValueError) as error:
        return [str(error)]
    return []


def _descriptor(manifest, base, job):
    raw = _configured(job)
    if raw is None:
        return None
    from lc_layout import resolve_layout_defaults, layout_geometry
    config, title, group_id = raw["decorative_effect"], raw["headline"], raw["id"]
    for value in (manifest, manifest.get("product_truth", {}), manifest.get("product", {})):
        if isinstance(value, dict) and any(isinstance(value.get(key), str) and value[key].strip()
                and value[key].casefold() in title.casefold() for key in ("brand", "brand_name")):
            raise TitleEffectError("TITLE_EFFECT_BRAND_FORBIDDEN")
    resolved = resolve_layout_defaults(job)
    matching = [g for g in resolved["text_groups"] if g.get("id") == group_id]
    if len(matching) != 1:
        raise TitleEffectError("TITLE_EFFECT_GROUP_ID_AMBIGUOUS")
    actual = matching[0]
    if actual.get("headline_treatment") not in (None, {"kind": "plain"}):
        raise TitleEffectError("TITLE_EFFECT_PLAIN_GUIDE_REQUIRED")
    # Body/label content, font and colors cannot spend a decorative-title call.
    # The exact headline glyph raster below detects any real typography shift.
    group = {"id": group_id, "headline": title,
             "headline_family": actual.get("headline_family", resolved.get("headline_family", "sans")),
             "headline_weight": actual.get("headline_weight", resolved.get("headline_weight", 600)),
             "text_color": actual.get("text_color", resolved.get("text_color", "#29251F")),
             "headline_size": actual.get("mobile_sizes", resolved.get("mobile_sizes", {})).get("headline", 24),
             "align": actual.get("align", "left"), "direction": resolved.get("direction"),
             "headline_treatment": {"kind": "plain"}}
    geom = layout_geometry(job)
    slot = next((g for g in geom["text_groups"] if g["id"] == group_id), None)
    if not slot:
        raise TitleEffectError("TITLE_EFFECT_GROUP_GEOMETRY_MISSING")
    group["box"] = slot["box"]
    protected = []
    if not (resolved.get("canvas_background") and resolved.get("panels")):
        product = job.get("output_product_bbox_norm") or job.get("target_product_bbox_norm") or job.get("raw_product_bbox_norm")
        if not product:
            raise TitleEffectError("TITLE_EFFECT_PRODUCT_PROTECTION_REQUIRED")
        protected.append(_box(product))
    protected.extend(_box(r.get("bbox") if isinstance(r, dict) else r) for r in resolved.get("protected_regions", []))
    if resolved.get("panels"):
        from lc_layout_v3 import panel_placement, mapped_product_box
        for panel, panel_slot in zip(resolved["panels"], geom["panels"]):
            if not panel.get("product_bbox_norm"):
                # An unlocalized product panel is protected in its entirety.
                protected.append(_box(panel_slot["box"])); continue
            with Image.open(_path(base, panel.get("image"))) as image:
                actual = {**panel, "box": panel_slot["box"], "source_size": list(image.size)}
                actual["placement"] = panel_placement(actual, job["canvas"])
                mapped = mapped_product_box(actual, job["canvas"])
                if mapped:
                    protected.append(_box(mapped))
    sources = _sources(manifest, base, config.get("source_reference_ids", job.get("source_reference_ids")))
    return {"version": 1, "group_id": group_id, "title": title, "config": copy.deepcopy(config),
            "group": group, "canvas": list(job["canvas"]), "protected": protected,
            "allowed_bbox_norm": _box(config.get("allowed_bbox_norm")), "sources": sources}


def _pixels(box, size, *, inner=False):
    x, y, w, h = _box(box)
    start, end = (math.ceil, math.floor) if inner else (math.floor, math.ceil)
    return (start(x * size[0]), start(y * size[1]), end((x + w) * size[0]), end((y + h) * size[1]))


def _bbox_pixels(value, size):
    if not isinstance(value, dict) or set(("x", "y", "width", "height")) - set(value):
        raise TitleEffectError("TITLE_EFFECT_TEXT_BBOX_INVALID")
    if any(isinstance(value[key], bool) or not isinstance(value[key], (int, float))
           or not math.isfinite(value[key]) for key in ("x", "y", "width", "height")):
        raise TitleEffectError("TITLE_EFFECT_TEXT_BBOX_INVALID")
    norm = [value["x"] / size[0], value["y"] / size[1], value["width"] / size[0], value["height"] / size[1]]
    return _pixels(norm, size)


def _region_mask(size, boxes):
    result = Image.new("L", size)
    draw = ImageDraw.Draw(result)
    for x0, y0, x1, y1 in boxes:
        if x1 > x0 and y1 > y0:
            draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=255)
    return result


def _capture(manifest, base, job, flat, background, glyph, bboxes):
    descriptor = _descriptor(manifest, base, job)
    if descriptor is None:
        return None
    if not isinstance(bboxes, list):
        raise TitleEffectError("TITLE_EFFECT_TEXT_BBOXES_REQUIRED")
    target_id = f"group-{descriptor['group_id']}-headline"
    targets = [b for b in bboxes if isinstance(b, dict) and b.get("id") == target_id and b.get("kind") == "text"]
    if len(targets) != 1:
        raise TitleEffectError("TITLE_EFFECT_HEADLINE_BBOX_REQUIRED")
    size = descriptor["canvas"]
    records = {key: _snapshot(base, job, value, key) for key, value in
               (("flat", flat), ("background", background), ("glyph", glyph))}
    for key, record in records.items():
        _image(base, record, mode="L" if key == "glyph" else "RGB", size=size)
    records["target_bbox"] = copy.deepcopy(targets[0]["bbox"])
    records["other_text_bboxes"] = [copy.deepcopy(b["bbox"]) for b in bboxes
                                   if isinstance(b, dict) and b.get("kind") == "text" and b.get("id") != target_id]
    records["descriptor_sha256"] = _digest(_effect_descriptor(descriptor))
    records["layout_configuration_sha256"] = _digest(_configuration(job))
    for value in [records["target_bbox"], *records["other_text_bboxes"]]:
        _bbox_pixels(value, size)
    # Prove that the original glyphs fit before spending an image-model call.
    all_glyphs = _image(base, records["glyph"], mode="L", size=size)
    title_area = _region_mask(size, [_bbox_pixels(records["target_bbox"], size)])
    minimum_mask = ImageChops.multiply(all_glyphs, title_area).point(lambda p: 255 if p else 0)
    _mask_issues(descriptor, records, base, minimum_mask)
    state = job.setdefault("title_effect_state", {})
    if state.get("guide") != records:
        state.pop("applied", None)
    state["guide"] = records
    return descriptor


def _effect_descriptor(descriptor):
    """Inputs that can change the title edit itself, excluding other content."""
    return {key: copy.deepcopy(descriptor[key]) for key in
            ("version", "group_id", "title", "config", "group", "canvas", "allowed_bbox_norm", "sources")}


def _current(manifest, base, job):
    descriptor = _descriptor(manifest, base, job)
    if descriptor is None:
        return None, None
    guide = job.get("title_effect_state", {}).get("guide")
    if not isinstance(guide, dict):
        return descriptor, None
    if (guide.get("descriptor_sha256") != _digest(_effect_descriptor(descriptor))
            or guide.get("layout_configuration_sha256") != _digest(_configuration(job))):
        # An old letterform raster is not a guide for newly edited copy, size,
        # placement, surface or source evidence. The renderer must refresh it.
        return descriptor, None
    images = {key: _image(base, guide[key], mode="L" if key == "glyph" else "RGB", size=descriptor["canvas"])
              for key in ("flat", "background", "glyph")}
    title_box = _bbox_pixels(guide["target_bbox"], descriptor["canvas"])
    allowed = _pixels(descriptor["allowed_bbox_norm"], descriptor["canvas"], inner=True)
    local_pixels = {"target_bbox": guide["target_bbox"],
                    "glyph_sha256": hashlib.sha256(images["glyph"].crop(title_box).tobytes()).hexdigest(),
                    "background_sha256": hashlib.sha256(images["background"].crop(allowed).tobytes()).hexdigest()}
    return descriptor, _digest({"descriptor": _effect_descriptor(descriptor), "local_pixels": local_pixels})


def _configuration(job):
    return {key: copy.deepcopy(job.get(key)) for key in
            ("layout", "canvas", "output_product_bbox_norm", "target_product_bbox_norm",
             "raw_product_bbox_norm", "text_mode", "kind", "_project_style", "typography_decision")}


def prepare(manifest, base, job, *, flat_path=None, background_path=None, glyph_path=None, bboxes=None):
    """Prepare immutable local guides/prompt; never consume or reset an attempt."""
    supplied = [flat_path, background_path, glyph_path, bboxes]
    if any(v is not None for v in supplied):
        if any(v is None for v in supplied):
            raise TitleEffectError("TITLE_EFFECT_COMPLETE_GUIDE_REQUIRED")
        _capture(manifest, base, job, *supplied)
    descriptor, fingerprint = _current(manifest, base, job)
    if descriptor is None:
        if isinstance(job.get("title_effect_state"), dict):
            job["title_effect_state"].update(status="disabled", fallback_reason="TITLE_EFFECT_DISABLED")
            job["title_effect_state"].pop("applied", None)
        return {"status": "disabled", "model_calls": 0}
    state = job.setdefault("title_effect_state", {})
    previous = state.get("fingerprint")
    state.update(descriptor=descriptor, fingerprint=fingerprint)
    if fingerprint is None:
        state["status"] = "needs_guide"
        state.pop("applied", None)
    elif previous != fingerprint:
        state.update(status="ready", fallback_reason="TITLE_EFFECT_INPUTS_CHANGED" if previous else None)
        state.pop("applied", None)
    elif state.get("status") in {None, "needs_guide"}:
        state["status"] = "ready"
    prompt = (f"Edit only the decorative headline {json.dumps(descriptor['title'], ensure_ascii=False)} once. "
              f"Keep the exact local letterforms, size, position and color role. Apply shallow surface embossing on "
              f"{descriptor['config']['surface']}; lighting/material: {descriptor['config']['material_lighting']}. "
              "Do not add, move, reword or alter any other text, brand, fact, number, product or scene. "
              f"Edits and contact shadow must stay within normalized region {descriptor['allowed_bbox_norm']}. "
              "Return a full-canvas raster; the separate, reviewed grayscale adoption mask determines the only accepted pixels.")
    state["prompt"] = prompt
    state["prompt_sha256"] = _digest({"fingerprint": fingerprint, "prompt": prompt})
    return {"status": state["status"], "fingerprint": fingerprint, "prompt": prompt,
            "prompt_sha256": state["prompt_sha256"], "guide": copy.deepcopy(state.get("guide")),
            "attempt_counts": {kind: sum(a.get("kind") == kind for a in job.get("title_effect_attempts", [])) for kind in _LIMITS},
            "model_calls": 0}


def attempt_event(manifest, base, job, event, *, attempt_id=None, kind="initial", at=None, reason=None):
    """Record explicit tool timestamps; append-only budgets span all input edits."""
    if event not in {"tool_started", "tool_returned", "failed"}:
        raise TitleEffectError("TITLE_EFFECT_EVENT_INVALID")
    stamp = time.time() if at is None else at
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp < 0:
        raise TitleEffectError("TITLE_EFFECT_TIMESTAMP_INVALID")
    history = job.get("title_effect_attempts", [])
    attempt = next((a for a in history if a["id"] == attempt_id), None)
    if event == "tool_started":
        if attempt is None:
            from lc_image_pipeline import active_model_count, is_hold
            if is_hold(job) or job.get("status") in {"blocked", "failed", "generating"}:
                raise TitleEffectError("TITLE_EFFECT_JOB_NOT_READY")
            if active_model_count(manifest) >= manifest.get("concurrency", 2):
                raise TitleEffectError("TITLE_EFFECT_CONCURRENCY_FULL")
            if "layout_result" in job and not job["layout_result"].get("passed"):
                raise TitleEffectError("TITLE_EFFECT_LAYOUT_PREFLIGHT_FAILED")
        prepared = prepare(manifest, base, job)
        if not prepared.get("fingerprint"):
            raise TitleEffectError("TITLE_EFFECT_PREPARED_GUIDE_REQUIRED")
        if attempt is not None:
            if attempt["fingerprint"] == prepared["fingerprint"] and attempt["tool_started_at"] == stamp:
                return copy.deepcopy(attempt)
            raise TitleEffectError("TITLE_EFFECT_ATTEMPT_CONFLICT")
        if any(a["status"] in {"started", "returned"} for a in history):
            raise TitleEffectError("TITLE_EFFECT_ATTEMPT_ACTIVE")
        if kind not in _LIMITS or sum(a["kind"] == kind for a in history) >= _LIMITS[kind]:
            raise TitleEffectError("TITLE_EFFECT_ATTEMPT_BUDGET_EXHAUSTED")
        if kind != "initial" and (not history or not isinstance(reason, str) or not reason.strip()):
            raise TitleEffectError("TITLE_EFFECT_RETRY_REASON_REQUIRED")
        if kind == "transient_retry" and history[-1].get("status") != "failed":
            raise TitleEffectError("TITLE_EFFECT_TRANSIENT_FAILURE_REQUIRED")
        attempt = {"id": attempt_id or str(uuid.uuid4()), "kind": kind, "status": "started",
                   "fingerprint": prepared["fingerprint"], "prompt_sha256": prepared["prompt_sha256"],
                   "prompt": prepared["prompt"], "guide": copy.deepcopy(prepared["guide"]),
                   "tool_started_at": stamp, "reason": reason}
        job.setdefault("title_effect_attempts", []).append(attempt)
        job["title_effect_state"]["status"] = "generating"
    else:
        if attempt is None:
            raise TitleEffectError("TITLE_EFFECT_ATTEMPT_UNKNOWN")
        field = "tool_returned_at" if event == "tool_returned" else "failed_at"
        if field in attempt:
            if attempt[field] == stamp and (event != "failed" or attempt.get("failure_reason") == reason):
                return copy.deepcopy(attempt)
            raise TitleEffectError("TITLE_EFFECT_EVENT_IMMUTABLE")
        allowed_statuses = {"started", "returned"} if event == "failed" else {"started"}
        if attempt["status"] not in allowed_statuses or stamp < attempt.get("tool_returned_at", attempt["tool_started_at"]):
            raise TitleEffectError("TITLE_EFFECT_EVENT_ORDER_INVALID")
        if event == "failed" and (not isinstance(reason, str) or not reason.strip()):
            raise TitleEffectError("TITLE_EFFECT_FAILURE_REASON_REQUIRED")
        attempt[field] = stamp
        attempt["status"] = "returned" if event == "tool_returned" else "failed"
        if event == "failed":
            attempt["failure_reason"] = reason
    return copy.deepcopy(attempt)


def _mask_issues(descriptor, guide, base, mask):
    size = tuple(descriptor["canvas"])
    glyph = _image(base, guide["glyph"], mode="L", size=size)
    target = _region_mask(size, [_bbox_pixels(guide["target_bbox"], size)])
    title_ink = ImageChops.multiply(glyph, target).point(lambda p: 255 if p > 0 else 0)
    if title_ink.getbbox() is None:
        raise TitleEffectError("TITLE_EFFECT_TITLE_GLYPHS_EMPTY")
    # All original ink, including antialias pixels, is replaced opaquely. A
    # partial mask could leave the flat title visible under the edited title.
    if ImageChops.multiply(title_ink, ImageChops.invert(mask)).getbbox():
        raise TitleEffectError("TITLE_EFFECT_MASK_MUST_REPLACE_ALL_TITLE_INK")
    allowed = _region_mask(size, [_pixels(descriptor["allowed_bbox_norm"], size, inner=True)])
    active = mask.point(lambda p: 255 if p else 0)
    if ImageChops.multiply(active, ImageChops.invert(allowed)).getbbox():
        raise TitleEffectError("TITLE_EFFECT_MASK_OUTSIDE_ALLOWED_REGION")
    protected = _region_mask(size, [_pixels(box, size) for box in descriptor["protected"]])
    if ImageChops.multiply(active, protected).getbbox():
        raise TitleEffectError("TITLE_EFFECT_MASK_TOUCHES_PRODUCT")
    other = _region_mask(size, [_bbox_pixels(box, size) for box in guide["other_text_bboxes"]])
    other = ImageChops.lighter(other, ImageChops.multiply(glyph, ImageChops.invert(target)).point(lambda p: 255 if p else 0))
    if ImageChops.multiply(active, other).getbbox():
        raise TitleEffectError("TITLE_EFFECT_MASK_TOUCHES_OTHER_TEXT")


def ingest(manifest, base, job, artifact_path, mask_path, *, attempt_id, review=None):
    """Bind returned pixels/mask, without signing their eventual composite."""
    prepared = prepare(manifest, base, job)
    history = job.get("title_effect_attempts", [])
    attempt = next((a for a in history if a["id"] == attempt_id), None)
    if attempt is None or attempt.get("status") not in {"returned", "ingested"}:
        raise TitleEffectError("TITLE_EFFECT_RETURN_EVENT_REQUIRED")
    if attempt["fingerprint"] != prepared.get("fingerprint") or attempt["prompt_sha256"] != prepared.get("prompt_sha256"):
        raise TitleEffectError("TITLE_EFFECT_STALE_ATTEMPT")
    artifact = _snapshot(base, job, artifact_path, "candidate", external=True)
    mask_record = _snapshot(base, job, mask_path, "mask", external=True)
    state = job["title_effect_state"]
    _image(base, artifact, size=state["descriptor"]["canvas"])
    mask = _image(base, mask_record, mode="L", size=state["descriptor"]["canvas"])
    _mask_issues(state["descriptor"], state["guide"], base, mask)
    binding = _digest({"fingerprint": prepared["fingerprint"], "attempt_id": attempt_id,
                       "prompt_sha256": attempt["prompt_sha256"], "artifact": artifact, "mask": mask_record})
    if attempt.get("binding"):
        if attempt["binding"] == binding:
            return {"binding": binding, "cached": True, "review_required": True}
        raise TitleEffectError("TITLE_EFFECT_INGEST_CONFLICT")
    candidate = {"binding": binding, "fingerprint": prepared["fingerprint"], "attempt_id": attempt_id,
                 "artifact": artifact, "mask": mask_record, "origin": str(Path(artifact_path).resolve()),
                 "prompt_sha256": attempt["prompt_sha256"], "sources": copy.deepcopy(state["descriptor"]["sources"])}
    if review is not None:
        candidate["intake_observation"] = copy.deepcopy(review)
    state.update(candidate=candidate, status="candidate_ready", fallback_reason=None)
    state.pop("applied", None)
    attempt.update(status="ingested", binding=binding, artifact=artifact, mask=mask_record)
    return {"binding": binding, "cached": False, "review_required": True,
            "artifact": copy.deepcopy(artifact), "mask": copy.deepcopy(mask_record)}


def composite(job, base, flat_path, background_path, glyph_path, bboxes, *, output_path=None, manifest=None):
    """Replace one headline once, or return the untouched, fully legible flat.

    A valid candidate may be applied before review to create review material.
    ``review_required`` is never a visual approval. Immutable guides survive a
    caller subsequently replacing its disposable renderer output with this PNG.
    """
    if not any(isinstance(g, dict) and g.get("decorative_effect") is not None
               for g in (job.get("layout") or {}).get("text_groups", [])):
        if isinstance(job.get("title_effect_state"), dict):
            job["title_effect_state"].update(status="disabled", fallback_reason="TITLE_EFFECT_DISABLED")
            job["title_effect_state"].pop("applied", None)
        return {"applied": False, "fallback_reason": None, "output_path": str(flat_path), "review_required": False}
    manifest = manifest or {"references": job.get("title_effect_state", {}).get("descriptor", {}).get("sources", [])}
    state = job.setdefault("title_effect_state", {})
    try:
        prepared = prepare(manifest, base, job, flat_path=flat_path, background_path=background_path,
                           glyph_path=glyph_path, bboxes=bboxes)
        if prepared["status"] == "disabled":
            return {"applied": False, "fallback_reason": None, "output_path": str(flat_path), "review_required": False}
        candidate = state.get("candidate")
        if not isinstance(candidate, dict):
            raise TitleEffectError("TITLE_EFFECT_CANDIDATE_MISSING")
        if candidate["fingerprint"] != prepared["fingerprint"]:
            raise TitleEffectError("TITLE_EFFECT_CANDIDATE_STALE")
        attempt = next((a for a in job.get("title_effect_attempts", []) if a.get("id") == candidate["attempt_id"]), None)
        if not attempt or attempt.get("status") != "ingested" or attempt.get("binding") != candidate["binding"]:
            raise TitleEffectError("TITLE_EFFECT_ATTEMPT_BINDING_MISSING")
        size = state["descriptor"]["canvas"]
        mask = _image(base, candidate["mask"], mode="L", size=size)
        _mask_issues(state["descriptor"], state["guide"], base, mask)
        flat = _image(base, state["guide"]["flat"], size=size)
        edited = _image(base, candidate["artifact"], size=size)
        output = Image.composite(edited, flat, mask)
        target = Path(output_path) if output_path else Path(flat_path).with_name(Path(flat_path).stem + ".title-effect.png")
        target = target.resolve() if target.is_absolute() else (Path(base) / target).resolve()
        if not target.is_relative_to(Path(base).resolve()) or target == _path(base, flat_path) or target.suffix.lower() != ".png":
            raise TitleEffectError("TITLE_EFFECT_DISTINCT_LOCAL_PNG_OUTPUT_REQUIRED")
        target.parent.mkdir(parents=True, exist_ok=True)
        output.save(target, format="PNG")
        output_sha = _hash(target)
        binding = _digest({"candidate": candidate["binding"], "output_sha256": output_sha,
                           "fingerprint": prepared["fingerprint"]})
        applied = {"binding": binding, "candidate_binding": candidate["binding"], "output_sha256": output_sha,
                   "group_id": state["descriptor"]["group_id"], "transcription_required": state["descriptor"]["title"],
                   "fingerprint": prepared["fingerprint"], "configuration_sha256": _digest(_configuration(job))}
        state.update(applied=applied, status="review_pending", fallback_reason=None)
        return {"applied": True, "fallback_reason": None, "output_path": str(target),
                "binding": binding, "output_sha256": output_sha, "group_id": applied["group_id"], "review_required": True}
    except (TitleEffectError, OSError, KeyError, TypeError, ValueError) as error:
        reason = str(error) or type(error).__name__
        state.update(status="fallback", fallback_reason=reason)
        state.pop("applied", None)
        return {"applied": False, "fallback_reason": reason, "output_path": str(flat_path), "review_required": False}


def review_issues(job, review):
    """Validate real observations bound to the current applied lossless pixels."""
    state = job.get("title_effect_state", {})
    applied = state.get("applied")
    if not applied:
        return []
    if not isinstance(review, dict):
        return ["TITLE_EFFECT_REVIEW_REQUIRED"]
    issues = []
    if review.get("binding") != applied.get("binding"):
        issues.append("TITLE_EFFECT_REVIEW_BINDING_STALE")
    if applied.get("configuration_sha256") != _digest(_configuration(job)):
        issues.append("TITLE_EFFECT_REVIEW_BINDING_STALE")
    title = state.get("descriptor", {}).get("title", "")
    from lc_design import normalized_copy
    if not isinstance(review.get("transcription"), str) or normalized_copy(review["transcription"]) != normalized_copy(title):
        issues.append("TITLE_EFFECT_TRANSCRIPTION_MISMATCH")
    if review.get("unexpected_text") != []:
        issues.append("TITLE_EFFECT_UNEXPECTED_TEXT_INVENTORY_REQUIRED")
    if review.get("verdict") != "pass" or any(review.get(key) is not True for key in _REVIEW_FLAGS):
        issues.append("TITLE_EFFECT_VISUAL_REVIEW_FAILED")
    if any(not isinstance(review.get(key), str) or not review[key].strip() for key in ("notes", "observed_surface")):
        issues.append("TITLE_EFFECT_ACTUAL_OBSERVATIONS_REQUIRED")
    try:
        observed = _box(review.get("bbox_norm"))
        allowed = state["descriptor"]["allowed_bbox_norm"]
        if (observed[0] < allowed[0] or observed[1] < allowed[1]
                or observed[0] + observed[2] > allowed[0] + allowed[2] + 1e-6
                or observed[1] + observed[3] > allowed[1] + allowed[3] + 1e-6):
            issues.append("TITLE_EFFECT_OBSERVED_REGION_OUTSIDE_ALLOWED")
    except TitleEffectError:
        issues.append("TITLE_EFFECT_OBSERVED_REGION_REQUIRED")
    return sorted(set(issues))


def submit_review(manifest, base, job, review):
    """Archive an effect observation; the normal image review still owns QA."""
    descriptor, fingerprint = _current(manifest, base, job)
    state = job.get("title_effect_state", {})
    if not descriptor or state.get("applied", {}).get("fingerprint") != fingerprint:
        raise TitleEffectError("TITLE_EFFECT_REVIEW_BINDING_STALE")
    candidate = state.get("candidate") or {}
    _image(base, candidate.get("artifact", {}), size=descriptor["canvas"])
    mask = _image(base, candidate.get("mask", {}), mode="L", size=descriptor["canvas"])
    _mask_issues(descriptor, state["guide"], base, mask)
    issues = review_issues(job, review)
    if issues:
        raise TitleEffectError(";".join(issues))
    record = {"review": copy.deepcopy(review), "applied": copy.deepcopy(state["applied"])}
    folder = _folder(base, job) / "reviews"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{_digest(record)}.json"
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2)
    if target.exists() and target.read_text(encoding="utf-8") != serialized:
        raise TitleEffectError("TITLE_EFFECT_REVIEW_ARCHIVE_TAMPERED")
    if not target.exists():
        target.write_text(serialized, encoding="utf-8")
    state["effect_observation"] = record
    return {"record": str(target.relative_to(Path(base).resolve())), "binding": review["binding"], "image_qa_approved": False}


def dependencies(job, base, *, phase="layout"):
    """Stable render inputs, or complete current review evidence.

    The layout branch deliberately ignores everything a render creates. Guide
    capture, adoption/fallback and review preparation must not invalidate their
    own cached layout. The surrounding pipeline already binds ordinary copy.
    """
    if phase not in {"layout", "review"}:
        raise TitleEffectError("TITLE_EFFECT_DEPENDENCY_PHASE_INVALID")
    groups = (job.get("layout") or {}).get("text_groups", [])
    configured = [copy.deepcopy(g) for g in groups if isinstance(g, dict) and g.get("decorative_effect") not in (None, {"kind": "none"})]
    if not configured:
        return {}
    state = job.get("title_effect_state", {})
    candidate = state.get("candidate") or {}
    files = {}
    descriptor = state.get("descriptor", {})
    records = [candidate.get("artifact"), candidate.get("mask"), *candidate.get("sources", [])]
    # layout_input is often a disposable image_layers cache. The main pipeline
    # binds raw pixels/placement; deleting that cache cannot revoke approval.
    # Source references below and our immutable guides are persistent evidence.
    if phase == "review":
        records += list(state.get("guide", {}).values()) + descriptor.get("sources", [])
    for record in records:
        if isinstance(record, dict) and "path" in record and "sha256" in record:
            try:
                files[record["path"]] = _hash(_path(base, record["path"]))
            except (TitleEffectError, OSError):
                files[record["path"]] = "MISSING"
    result = {"groups": configured, "candidate_binding": candidate.get("binding"), "files": files}
    if phase == "review":
        result.update(fingerprint=state.get("fingerprint"), guide=copy.deepcopy(state.get("guide")),
                      applied=copy.deepcopy(state.get("applied")), fallback_reason=state.get("fallback_reason"))
    return result
