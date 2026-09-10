"""Versioned, deterministic imagegen prompt formatting; no model or file I/O.

The official skill guides planning. Its installed bytes are deliberately not a
runtime dependency: only the resolved project inputs enter a generation hash.
"""
from __future__ import annotations

import copy
import json
import re

from lc_design import copy_blocks, design_generation_payload, resolve_text_mode

PROFILE = "images_2_5_v1"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _sentences(text):
    # Keep clauses intact; this is exact-fragment deduplication, not paraphrase.
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n+", text) if part.strip()]


def _leaves(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)


def _lines(label, value):
    if value in (None, "", [], {}):
        return []
    if isinstance(value, dict):
        return [line for key, item in value.items()
                for line in _lines(f"{label} / {key.replace('_', ' ')}", item)]
    if isinstance(value, list):
        return [f"{label}: " + "; ".join(str(item) for item in value)]
    return [f"{label}: {value}"]


def _canvas_background(text):
    # Resolve information-field placement, never camera/light/product directions.
    for old, new in (
        ("darker quiet vertical area to the right", "darker quiet area inside the planned information container"),
        ("quiet middle-right or upper-right field", "quiet field inside the planned information container"),
        ("deliberate low foreground gap or pale surface for information",
         "deliberate quiet gap or pale surface inside the planned information container"),
    ):
        text = text.replace(old, new)
    return text


def _canvas_reading_order(text):
    # Retain the adopted content sequence; its old absolute placement now comes
    # from the resolved canvas. Explicit project reading-order overrides survive.
    text = re.sub(r"\b(?:centered|upper|central|right-aligned|left-weighted|lower)\s+", "", text, flags=re.I)
    text = re.sub(r"\b(?:right-side|side)\s+(?=title\b)", "", text, flags=re.I)
    text = re.sub(r"\bheader band\b", "Heading group", text, flags=re.I)
    text = re.sub(r"\btitle band\b", "title group", text, flags=re.I)
    text = re.sub(r"\bfooter(?: (information|group))?\b",
                  lambda match: "supporting group" if match[1] == "group" else "supporting information", text)
    text = re.sub(r"\blow support\b", "supporting information", text)
    text = re.sub(r"\bbeside\b", "separate from", text)
    text = re.sub(r"\babove\b", "followed by", text)
    return text[:1].upper() + text[1:]


def _design(job):
    """Use resolved structured values; retain only unique free-form additions.

An active canvas or explicit composition replaces generic placement fields.
The adopted snapshot supplies the *old* field text as well, so an override does
not accidentally resurrect stale instructions embedded in resolved_prompt.
"""
    payload = copy.deepcopy(design_generation_payload(job))
    snapshot = (job.get("design_resolution") or {}).get("binding", {}).get("template", {}).get("snapshot", {})
    original = copy.deepcopy(snapshot.get("generation", {}))
    resolved = payload.pop("resolved_prompt", "")
    covered = set()
    for text in _leaves({"current": payload, "original": original}):
        covered.update(_sentences(text))
    active = payload.pop("canvas_composition", {})
    composition = job.get("composition") or active.get("notes") or payload.get("composition")
    if active or job.get("composition"):
        payload.pop("composition", None)
        payload.pop("reserved_space", None)
        payload.pop("canvas_adaptation", None)
        if isinstance(payload.get("background"), str):
            payload["background"] = _canvas_background(payload["background"])
    else:
        payload.pop("composition", None)
    # These are emitted once by the route, never inherited from a template.
    payload.pop("text_policy", None)
    if job.get("lighting"):
        payload.pop("lighting", None)
    family_style = payload.get("family_visual_style")
    if resolve_text_mode(job) != "model_native" and isinstance(family_style, dict):
        # Local graphics stay in the adopted brief; the model makes a clean base.
        family_style.pop("graphics", None)
    typography = payload.get("integrated_typography")
    if isinstance(typography, dict):
        reading = typography.get("reading_order")
        if ((active or job.get("composition")) and isinstance(reading, str)
                and reading == snapshot.get("layout", {}).get("reading_order")):
            typography["reading_order"] = _canvas_reading_order(reading)
        # Geometry is resolved once by the pipeline, including native posters.
        for key in ("product_region_norm", "text_group_box", "canvas_variants", "composition_note"):
            typography.pop(key, None)
        typography.pop("series_rhythm", None)  # Set planning, not this image's composition.
        guidance = typography.get("design_guidance")
        if isinstance(guidance, dict) and isinstance(guidance.get("avoid"), list):
            safeguards = set(_leaves(payload.get("product_safeguards", [])))
            guidance["avoid"] = [item for item in guidance["avoid"] if item not in safeguards]
    extra = []
    for part in _sentences(resolved):
        if part not in covered and part not in extra:
            extra.append(part)
    return composition, payload, extra


def ordered_references(manifest, job, paths):
    """Resolve an edit target without treating a detail/style image as a base."""
    request = job.get("prompt_edit")
    if request:
        return list(dict.fromkeys([request["target_path"], *paths]))
    if job["render_mode"] != "reference_edit":
        return paths
    from lc_quality import _is_whole
    refs = {r["id"]: r for r in manifest.get("references", [])
            if r["path"] in paths and _is_whole(r)
            and not any(kind in r.get("role", "") for kind in ("style", "design"))}
    explicit = job.get("pixel_source_reference_id")
    if explicit:
        if explicit not in refs:
            raise ValueError("The explicit edit target must be a current whole-product reference")
        target = refs[explicit]
    else:
        matched = [refs[rid] for rid in job.get("source_assessment", {}).get("matched_reference_ids", []) if rid in refs]
        candidates = matched or [ref for ref in refs.values()
            if ref.get("view") == job.get("target_view", job.get("view"))]
        if not candidates and len(refs) == 1:
            candidates = list(refs.values())
        if len(candidates) != 1:
            raise ValueError("Select one matched whole-product edit target with pixel_source_reference_id")
        target = candidates[0]
    return [target["path"], *[path for path in paths if path != target["path"]]]


def input_image_lines(manifest, paths, *, edit_target=None, background_only=False):
    from lc_quality import DETAIL_ROLES
    refs = {ref["path"]: ref for ref in manifest.get("references", [])}
    crops = {crop["path"] for detail in manifest.get("critical_details", [])
             for crop in detail.get("reference_crops", [])}
    lines = []
    for index, path in enumerate(paths, 1):
        ref = refs.get(path, {})
        role = ref.get("role", "whole_product_reference")
        if path == edit_target:
            purpose = "edit target; preserve its already-correct content"
        elif path in crops:
            purpose = "critical-detail evidence; use its supported shape and physical location, not its crop framing"
        elif "style" in role or "design" in role:
            purpose = "design reference only; no product identity, sample copy, claims or branding"
        elif role in DETAIL_ROLES:
            purpose = role.replace("_", " ") + "; evidence only for its visible detail, not a whole-product edit target"
        else:
            purpose = "product identity and visible-appearance reference"
            if (ref.get("provenance") or {}).get("kind") in {"generated", "restored"}:
                purpose += "; approved derived appearance, not evidence of new product facts"
        if background_only:
            purpose += "; context for an empty background, do not render the referenced product"
        lines.append(f"Image {index}: {path} — {purpose}.")
    return lines


def compile_image_prompt(manifest, job, paths, detail_blocks, geometry, locks):
    mode = resolve_text_mode(job)
    background_only = job["render_mode"] == "pixel_composite"
    request = job.get("prompt_edit") or {}
    editing = job["render_mode"] == "reference_edit" or bool(request)
    use_case = ("precise-object-edit" if editing else "photorealistic-natural" if background_only
                else "ads-marketing" if mode == "model_native" else "product-mockup")
    composition, design, extra = _design(job)
    if background_only:
        composition = "Prepare the empty backdrop and support around the planned local product container."
        design = {key: value for key, value in design.items() if key in {"background", "lighting", "family_visual_style"}}
        if isinstance(design.get("family_visual_style"), dict):
            design["family_visual_style"] = {key: value for key, value in design["family_visual_style"].items()
                                             if key in {"palette", "photography"}}
        extra = []
    truth = manifest["product_truth"]
    lines = [f"Use case: {use_case}", f"Asset type: Amazon {job['kind']} image {job['id']}",
             ("Primary request: create only the compatible empty photographic background for local product compositing."
              if background_only else
              "Primary request: edit the specified region or environment of the product photograph; preserve already-correct content."
              if editing else "Primary request: create an evidence-faithful commercial product photograph in the planned scene."),
             f"Visual objective: {job.get('selling_job', '')}", "Input images (in attachment order):",
             *input_image_lines(manifest, paths, edit_target=paths[0] if editing and paths else None,
                                background_only=background_only),
             *_lines("Scene/backdrop", job.get("scene")),
             *_lines("Product for scale/context only" if background_only else "Subject", truth.get("product")),
             "Style/medium: photorealistic commercial photography; depict only evidenced product appearance."]
    if request:
        lines.append("Observed failures to correct: " + ", ".join(request["failures"]) + ".")
        lines.append("The edit target is a previous model result to repair, not evidence for unsupported product facts. "
                     "Change only these failures; preserve the already-correct scene, geometry and approved typography.")
    if not background_only:
        lines.append(f"Target view: {job.get('target_view', job.get('view'))}.")
    lines.extend(_lines("Composition/framing", composition))
    lines.extend([f"Canvas intent: {job['canvas'][0]} x {job['canvas'][1]}; compose for this aspect ratio.",
                  "Placement containers (normalized x, y, width, height; not observed product masks): " + _json(geometry)])
    lines.extend(_lines("Lighting", job.get("lighting")))
    for key, value in design.items():
        lines.extend(_lines("Design / " + key.replace("_", " "), value))
    lines.extend("Additional design requirement: " + part for part in extra)
    if mode == "model_native":
        lines.append("Text (verbatim; render each block once, without its role label):")
        lines.extend(f"{block['role']}: {_json(block['text'])}" for block in copy_blocks(job))
        lines.extend(["Typography: integrate the approved wording into the composition with coherent hierarchy and spacing. "
                      "Keep spelling, case and punctuation; only line wrapping may change. Add no extra marketing text, badges or claims.",
                      "Keep all text clear at 360px image width: headline at least 18px, body/labels at least 12px; "
                      "target glyph-to-background contrast at least 4.5:1. These are design requirements, not a certification.",
                      "Protect faces, contact points and identifying product details from text. No local marketing text will be added afterward."])
        embedding = job.get("embedding_decision") or {}
        if embedding.get("kind") == "surface_embedded_3d":
            lines.extend(_lines("Decorative headline carrier", {key: embedding.get(key) for key in
                                                                ("surface", "material_lighting")}))
            lines.append("Apply credible perspective and contact lighting to the decorative headline only; do not imitate or replace a product label.")
    else:
        lines.append("Text policy: no added marketing text, icons, arrows, badges or watermarks. "
                     "Keep planned text regions calm and free of products, faces and important actions.")
    lines.append("Constraints:")
    if background_only:
        lines.extend(["- Leave the planned product container empty, with a compatible support surface and lighting. "
                      "Do not paint a substitute product, silhouette, accessories or identifying details.",
                      *["- Scene scale / " + text.lstrip("- ") for text in locks["scene_scale"]]])
    else:
        for title, key in (("Geometry", "geometry"), ("Material", "material"), ("Scene scale", "scene_scale")):
            lines.extend(f"- {title} / {text.lstrip('- ')}" for text in locks[key])
        lines.extend(["- Preserve physical structure, component relationships and confirmed dimensions. "
                      "Allow natural perspective, silhouette projection and occlusion in the supported target view.",
                      "- Preserve evidenced material identity, product color, finish and identifying texture; "
                      "allow natural highlights, reflection and environmental light without changing the product.",
                      "- Maintain credible support, relative scale, grip, contact shadows and occlusion. Do not invent measurements.",
                      *["- Critical detail / " + text.lstrip("- ") for text in detail_blocks],
                      "- Preserve authentic product labels and branding from evidence. Do not infer illegible text, hidden surfaces, "
                      "internal materials or included accessories from a style sample or generated image."])
        lines.append("Allowed changes: " + (
            "only the specified defective region or environment; preserve already-correct product details, framing and typography."
            if editing else "supported view, pose, lighting and scene integration; rebuild supported appearance without reproducing source blur."))
    lines.append("Avoid: invented claims, unapproved props, extra product units, watermarks and reference-board UI. "
                 "Reference styling never overrides verified product facts or the approved copy.")
    return "\n".join(lines) + "\n"


def detail_repair_prompt(manifest, job, detail, location, crop):
    paths = list(dict.fromkeys([job.get("raw_output", ""), crop["path"]] + [
        ref["path"] for ref in manifest.get("references", []) if ref["id"] == crop["reference_id"]]))
    lines = ["Use case: precise-object-edit", "Asset type: product-detail repair",
             f"Primary request: correct only {detail['name']} at its evidenced physical location.",
             "Input images (in attachment order):",
             *input_image_lines(manifest, paths, edit_target=job.get("raw_output")),
             *_lines("Detail", {key: detail.get(key) for key in ("description", "shape", "orientation", "color")}),
             *_lines("Supported physical location", location.get("position_description")),
             f"Evidence view: {crop['view']}; its crop framing is not the target-camera projection.",
             "Constraints: preserve all already-correct structure, materials, lighting, framing, scale, background and shadows. "
             "Keep the component on its evidenced surface; apparent size and position must follow the target perspective. "
             "Preserve authentic product labels and branding. Pixel-identical preservation requires local compositing, not a prompt promise.",
             ("Preserve already-correct approved typography; add no extra text, badges or claims."
              if resolve_text_mode(job) == "model_native" else "Add no marketing text, icons, arrows or watermark.")]
    return "\n".join(lines) + "\n"


def semantic_repair_prompt(job, failed):
    lines = ["Use case: precise-object-edit", "Asset type: targeted product-image repair",
             "Primary request: correct only these observed failures: " + ", ".join(dict.fromkeys(failed)) + ".",
             f"Input images: Image 1: {job.get('raw_output', '')} — edit target; "
             "subsequent images: the current bound whole-product and required detail evidence, in dispatch order.",
             "Constraints: preserve every already-correct product detail, composition, background, lighting and framing. "
             "Use the supplied evidence for corrections; do not add unsupported structure, materials, components, props or claims."]
    if resolve_text_mode(job) == "model_native":
        lines.append("Preserve approved typography and graphic design. Correct lettering only when a text check failed. "
                     "Text (verbatim; no extra text):")
        lines.extend(f"{block['role']}: {_json(block['text'])}" for block in copy_blocks(job))
    else:
        lines.append("Preserve the text-free layout and its reserved regions; add no marketing text, icons, arrows or watermark.")
    return "\n".join(lines) + "\n"
