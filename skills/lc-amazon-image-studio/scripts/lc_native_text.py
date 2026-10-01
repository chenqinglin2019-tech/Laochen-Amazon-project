"""Measure model-drawn (native) text contrast on the final JPEG encoding.

Native text has no text-free background or glyph mask, so the local renderer's
glyph-core check cannot run. This tool gives the reviewer one repeatable method
instead of ad-hoc code: encode the bound review image exactly like export
(JPEG, same quality, 4:4:4) in memory, then per transcribed block estimate the
background from the box border, split text by Otsu on luminance distance, erode
one pixel to drop the antialiased fringe and compute WCAG ratios per core pixel.
It reports evidence; the reviewer still makes the verdict. No model calls.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

METHOD = ("in-memory JPEG encode identical to export (quality q, 4:4:4) of the bound review image; per block: "
          "background = median luminance of the box border ring; text = Otsu split of |L - background|; glyph core = "
          "text mask eroded by 1 px (antialiased fringe excluded); WCAG ratio per core pixel against the background; "
          "pass = 5th percentile >= 4.5 with >= 20 core pixels")


def _otsu(values):
    import numpy as np
    hist, edges = np.histogram(values, bins=256, range=(0.0, float(values.max()) or 1.0))
    weight = hist.cumsum()
    total = weight[-1]
    if total == 0:
        return 0.0
    centers = (edges[:-1] + edges[1:]) / 2
    mean = (hist * centers).cumsum()
    between = (mean[-1] * weight / total - mean) ** 2 / np.maximum(weight * (total - weight), 1e-12) * total
    return float(centers[int(np.argmax(between))])


def _erode(mask):
    import numpy as np
    core = mask.copy()
    core[1:, :] &= mask[:-1, :]
    core[:-1, :] &= mask[1:, :]
    core[:, 1:] &= mask[:, :-1]
    core[:, :-1] &= mask[:, 1:]
    return core


def _quality(manifest, job):
    quality = (job.get("export") or {}).get("quality")
    if type(quality) is int and 1 <= quality <= 100:
        return quality
    profile = manifest.get("delivery_profile") or {}
    return profile.get("jpeg_quality", 92) if type(profile.get("jpeg_quality", 92)) is int else 92


def measure(manifest, base, job_id, blocks):
    import numpy as np
    from PIL import Image
    import lc_image_pipeline as p
    from lc_assets import pixel_hash
    from lc_typography import luminance
    base = Path(base).resolve()
    job = p.find_by_id(manifest["jobs"], job_id)
    if job is None:
        raise p.PipelineError(f"Unknown job: {job_id}")
    if p.resolve_text_mode(job) != "model_native":
        raise p.PipelineError("native-text-measure only applies to model_native jobs; local text is checked automatically")
    layer = base / "review" / "image_layers" / f"{job_id}.png"
    source = layer if layer.is_file() else p.resolve_path(job.get("raw_output"), base)
    if source is None or not source.is_file():
        raise p.PipelineError("No bound image to measure; run review-prepare first")
    with Image.open(source) as image:
        rgb = image.convert("RGB")
    if list(rgb.size) != list(job.get("canvas", [])):
        raise p.PipelineError("The image is not at the final canvas size yet; run review-prepare first")
    quality = _quality(manifest, job)
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=quality, subsampling=0)
    with Image.open(io.BytesIO(buffer.getvalue())) as decoded:
        encoded = decoded.convert("RGB")
    if not isinstance(blocks, list) or not blocks:
        raise p.PipelineError("Provide the transcribed blocks as [{id, bbox_norm:[x,y,w,h]}]")
    width, height = encoded.size
    results = []
    for block in blocks:
        box = block.get("bbox_norm") if isinstance(block, dict) else None
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            raise p.PipelineError(f"Block {block!r} needs bbox_norm [x,y,w,h]")
        left, top = max(0, int(box[0] * width)), max(0, int(box[1] * height))
        right, bottom = min(width, int((box[0] + box[2]) * width + 0.999)), min(height, int((box[1] + box[3]) * height + 0.999))
        if right - left < 6 or bottom - top < 6:
            raise p.PipelineError(f"Block {block.get('id')} box is too small to measure")
        lum = luminance(encoded.crop((left, top, right, bottom)))
        ring = np.concatenate([lum[:2, :].ravel(), lum[-2:, :].ravel(), lum[:, :2].ravel(), lum[:, -2:].ravel()])
        background = float(np.median(ring))
        distance = np.abs(lum - background)
        text = distance > max(_otsu(distance), 0.02)
        core = _erode(text)
        values = lum[core]
        if values.size:
            ratios = (np.maximum(values, background) + .05) / (np.minimum(values, background) + .05)
            minimum, p05 = float(ratios.min()), float(np.quantile(ratios, .05))
        else:
            minimum = p05 = 0.0
        rows = np.where(text.any(axis=1))[0]
        text_height_360 = ((rows[-1] - rows[0] + 1) * 360 / width) if rows.size else 0.0
        results.append({"id": block.get("id"), "bbox_norm": box, "ratio_min": round(minimum, 3), "ratio_p05": round(p05, 3),
                        "core_pixels": int(values.size), "background_luminance": round(background, 4),
                        "text_span_height_px_at_360": round(float(text_height_360), 1),
                        "passed": bool(values.size >= 20 and p05 >= 4.5)})
    record = {"schema": "lc-native-text-measure/1", "job": job_id, "measured_at": time.time(),
              "source": p.relpath(source, base), "source_sha256": p.sha256_file(source),
              "encoding": {"format": "JPEG", "quality": quality, "chroma_subsampling": "4:4:4"},
              "expected_final_pixel_sha256": pixel_hash(encoded), "method": METHOD, "blocks": results,
              "passed": all(item["passed"] for item in results),
              "note": ("Copy method, ratios and the 360px text heights into reviews.model_text_review.notes. "
                       "If the exported final's pixel_sha256 differs from expected_final_pixel_sha256, measure again.")}
    out = base / "review" / "native_text" / f"{job_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**{key: record[key] for key in ("job", "passed", "encoding", "expected_final_pixel_sha256", "blocks")},
            "record": p.relpath(out, base)}
