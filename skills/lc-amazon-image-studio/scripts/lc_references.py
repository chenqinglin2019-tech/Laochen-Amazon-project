"""Register product photos in one command (V7.1): `add-references --photos ...`.

Replaces hand-written reference JSON: copies each photo into source/, names it from
the file, guesses the view from the file name (front/back/side/top/bottom/three_
quarter/detail; override with --views), measures the product box from a plain
background (otherwise a marked estimate the agent corrects on the source sheet),
replaces init's placeholder reference and points every job at the whole-product
photos. Detail close-ups get a detail role. Existing references are kept.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

VIEW_WORDS = (("three_quarter", ("three_quarter", "3-4", "34view", "angle", "oblique", "45")),
              ("back", ("back", "rear")), ("side", ("side", "left", "right", "profile")),
              ("top", ("top", "above")), ("bottom", ("bottom", "underside")),
              ("detail", ("detail", "closeup", "close-up", "macro", "zoom")), ("front", ("front", "main")))


def _guess_view(name):
    lowered = name.lower()
    for view, words in VIEW_WORDS:
        if any(word in lowered for word in words):
            return view
    return None


def _safe_id(stem, taken):
    base = re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_") or "photo"
    if not re.match(r"[a-z]", base):
        base = "photo_" + base
    candidate, index = base[:48], 2
    while candidate in taken:
        candidate, index = f"{base[:44]}_{index}", index + 1
    return candidate


def _product_box(path):
    from PIL import Image, ImageOps
    import numpy as np
    from lc_cutout import propose_mask
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    try:
        mask, _ = propose_mask(image)
    except ValueError:
        return [0.05, 0.05, 0.9, 0.9], False
    alpha = np.asarray(mask) > 127
    ys, xs = np.nonzero(alpha)
    if not len(xs):
        return [0.05, 0.05, 0.9, 0.9], False
    w, h = image.size
    return [round(xs.min() / w, 4), round(ys.min() / h, 4), round((xs.max() - xs.min() + 1) / w, 4),
            round((ys.max() - ys.min() + 1) / h, 4)], True


def add_references(manifest, base, photos, views=None):
    import lc_image_pipeline as p
    base = Path(base).resolve()
    views = list(views or [])
    references = [ref for ref in manifest.get("references", []) if isinstance(ref, dict)]
    placeholder = [ref for ref in references if ref.get("id") == "product_front" and not (base / str(ref.get("path", ""))).is_file()]
    references = [ref for ref in references if ref not in placeholder]
    taken = {ref.get("id") for ref in references}
    added = []
    for index, photo in enumerate(photos):
        source = Path(photo).expanduser().resolve()
        if not source.is_file():
            raise p.PipelineError(f"Photo not found: {photo}")
        rid = _safe_id(source.stem, taken)
        taken.add(rid)
        target = base / "source" / f"{rid}{source.suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if source != target:
            shutil.copy2(source, target)
        view = views[index] if index < len(views) else (_guess_view(source.stem) or ("front" if not added else f"angle_{index + 1}"))
        detail = view == "detail"
        box, measured = _product_box(target)
        reference = {"id": rid, "path": p.relpath(target, base),
                     "role": "critical_detail_reference" if detail else "whole_product_reference",
                     "view": view, "visual_quality": "unknown", "product_bbox_norm": box,
                     "provenance": {"kind": "real_photo", "notes": f"Registered from {source.name}"},
                     "quality_review": {"clarity": "unknown", "evidence": "unknown", "defects": [], "notes": "",
                                        "reviewed_sha256": "", "reviewed_region_fingerprint": ""}}
        if not measured:
            reference["product_bbox_estimated"] = True
        references.append(reference)
        added.append({"id": rid, "view": view, "role": reference["role"], "product_bbox_norm": box, "measured_box": measured})
    manifest["references"] = references
    whole = [ref["id"] for ref in references if ref.get("role") == "whole_product_reference"]
    for job in manifest.get("jobs", []):
        current = [rid for rid in (job.get("source_reference_ids") or []) if rid in taken]
        job["source_reference_ids"] = current or whole[:]
    return {"added": added, "placeholder_replaced": bool(placeholder), "whole_product_references": whole,
            "next": ("Check estimated boxes (measured_box=false) on the source sheet; then source-review-prepare.")}
