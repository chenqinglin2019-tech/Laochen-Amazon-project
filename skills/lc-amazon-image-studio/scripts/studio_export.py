"""Finished secondary / A+ images (V8): fit the model frame to the canvas and export.

The image model returns 1:1, 3:2 or 2:3 frames. When the canvas has another aspect,
the prompt already told the model which band is kept; here the band is placed where
the least strong detail (text, product edges) is lost, and `cut_risk` reports what
was cut anyway (one automatic redo above the threshold). Export: JPEG 4:4:4 with the
Amazon AI-disclosure keyword in XMP when synthetic people appear, read back to check.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

SYNTHETIC_KEYWORD = "contains-synthetic-performer"
DC = "http://purl.org/dc/elements/1.1/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XMP = "adobe:ns:meta/"
CUT_RISK_LIMIT = 0.06        # share of strong detail allowed outside the kept band
EDGE_BUSY_FACTOR = 3.0       # detail density right inside a cut line vs the image median
ASPECT_TOLERANCE = 0.005


def make_xmp(keywords):
    ET.register_namespace("x", XMP)
    ET.register_namespace("rdf", RDF)
    ET.register_namespace("dc", DC)
    root = ET.Element(f"{{{XMP}}}xmpmeta")
    rdf = ET.SubElement(root, f"{{{RDF}}}RDF")
    desc = ET.SubElement(rdf, f"{{{RDF}}}Description", {f"{{{RDF}}}about": ""})
    bag = ET.SubElement(ET.SubElement(desc, f"{{{DC}}}subject"), f"{{{RDF}}}Bag")
    for value in sorted(set(keywords)):
        ET.SubElement(bag, f"{{{RDF}}}li").text = value
    return ET.tostring(root, encoding="utf-8")


def xmp_keywords(image):
    payload = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
    if not payload:
        return []
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("External declarations are forbidden in XMP")
    root = ET.fromstring(payload)
    return [item.text or "" for subject in root.iter(f"{{{DC}}}subject") for item in subject.iter(f"{{{RDF}}}li")]


def _detail_profile(image, axis):
    """Strong-detail energy per row (axis=0) or column (axis=1) at half size."""
    import numpy as np
    small = image.convert("L")
    small = small.resize((max(8, small.width // 2), max(8, small.height // 2)))
    luminance = np.asarray(small, dtype=np.float32)
    dx = np.abs(np.diff(luminance, axis=1, prepend=luminance[:, :1]))
    dy = np.abs(np.diff(luminance, axis=0, prepend=luminance[:1, :]))
    strong = (np.maximum(dx, dy) > 60).astype(np.float32)
    return strong.sum(axis=1 if axis == 0 else 0), small.size


def fit_to_canvas(image, canvas):
    """Crop to the canvas aspect where the least detail is lost, then resize. Returns (image, info)."""
    import numpy as np
    from PIL import Image, ImageFilter
    width, height = image.size
    target_w, target_h = canvas
    source_ratio, target_ratio = width / height, target_w / target_h
    info = {"source_size": [width, height], "canvas": [target_w, target_h], "cut_risk": 0.0, "edge_busy": False}
    if abs(source_ratio / target_ratio - 1) > ASPECT_TOLERANCE:
        crop_rows = source_ratio < target_ratio          # canvas is wider: keep a horizontal band
        profile, (small_w, small_h) = _detail_profile(image, 0 if crop_rows else 1)
        length = small_h if crop_rows else small_w
        keep = (small_w / target_ratio) if crop_rows else (small_h * target_ratio)
        keep = int(round(min(length, keep)))
        total = float(profile.sum()) or 1.0
        prefix = np.concatenate([[0.0], np.cumsum(profile)])
        offsets = np.arange(0, length - keep + 1)
        kept = prefix[offsets + keep] - prefix[offsets]
        centre = (length - keep) / 2
        strip = max(1, int(0.02 * length))
        top_strip = prefix[np.minimum(offsets + strip, length)] - prefix[offsets]
        bottom_strip = prefix[offsets + keep] - prefix[np.maximum(offsets + keep - strip, 0)]
        # Keep a margin: detail right at a cut line is penalised unless nothing is cut there.
        edge = (np.where(offsets > 0, top_strip, 0) + np.where(offsets + keep < length, bottom_strip, 0)) / total
        score = (total - kept) / total + 2.0 * edge + 0.02 * np.abs(offsets - centre) / max(1.0, centre)
        best = int(offsets[int(np.argmin(score))])
        lost = float((total - kept[best - offsets[0]]) / total)
        median = float(np.median(profile)) + 1e-6
        inside = [float(profile[best:best + strip].mean()), float(profile[best + keep - strip:best + keep].mean())]
        trimmed = [best > 0, best + keep < length]
        busy = any(trim and density > EDGE_BUSY_FACTOR * median and density > 2.0
                   for trim, density in zip(trimmed, inside))
        factor = (height if crop_rows else width) / length
        start, size = round(best * factor), round(keep * factor)
        box = (0, start, width, min(height, start + size)) if crop_rows else (start, 0, min(width, start + size), height)
        image = image.crop(box)
        info.update(crop_px=list(box), cut_risk=round(lost, 4), edge_busy=bool(busy),
                    band=[round(box[1] / height, 4), round(box[3] / height, 4)] if crop_rows else
                    [round(box[0] / width, 4), round(box[2] / width, 4)])
    scale = target_w / image.width
    result = image.resize((target_w, target_h), Image.Resampling.LANCZOS)
    if scale > 1.3:
        result = result.filter(ImageFilter.UnsharpMask(radius=1.2, percent=40, threshold=3))
    info["upscale"] = round(scale, 3)
    info["cut"] = bool(info["cut_risk"] > CUT_RISK_LIMIT or info["edge_busy"])
    return result.convert("RGB"), info


def export_jpeg(image, path, *, quality=92, people=False, keep_png=None):
    """JPEG 4:4:4 (+ XMP AI disclosure when synthetic people appear); read back to verify."""
    from PIL import Image
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    keywords = [SYNTHETIC_KEYWORD] if people else []
    temporary = path.with_name(f".{path.stem}.tmp.jpg")
    options = {"format": "JPEG", "quality": quality, "subsampling": 0, "optimize": True}
    if keywords:
        options["xmp"] = make_xmp(keywords)
    image.convert("RGB").save(temporary, **options)
    with Image.open(temporary) as check:
        check.load()
        if check.size != image.size or set(xmp_keywords(check)) != set(keywords):
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"EXPORT_VERIFY_FAILED: {path.name}")
    import lc_fsretry
    lc_fsretry.replace(temporary, path)
    if keep_png:
        image.convert("RGB").save(keep_png, format="PNG")
    return {"path": str(path), "quality": quality, "keywords": keywords, "subsampling": "4:4:4"}


def finish_secondary(raw_path, out_path, canvas, *, people=False, quality=92, work_png=None):
    """Raw model image -> finished canvas JPEG. Returns info incl. `cut` for the automatic check."""
    from PIL import Image, ImageOps
    with Image.open(raw_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    fitted, info = fit_to_canvas(image, canvas)
    exported = export_jpeg(fitted, out_path, quality=quality, people=people, keep_png=work_png)
    return {**info, **exported}


def rewrite_keywords(work_png, out_path, *, people, quality=92):
    """People flag corrected after export: re-encode the same pixels with the right keywords."""
    from PIL import Image
    with Image.open(work_png) as image:
        image.load()
        return export_jpeg(image, out_path, quality=quality, people=people)
