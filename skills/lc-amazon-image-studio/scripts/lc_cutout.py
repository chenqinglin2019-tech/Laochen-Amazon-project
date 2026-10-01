"""Candidate product mask for plain-background source photos (reviewed before use).

Pixel compositing keeps real product pixels but needs a cutout/mask layer; the
skill never guesses one silently. This helper proposes a mask only when the
photo background is plain (border colour nearly uniform): background = pixels
close to the border colour AND connected to the image border (so enclosed light
parts of the product stay opaque). It writes the mask plus an overlay preview;
the agent must inspect the overlay and confirm the layer in source-review before
compose can use it. Complex/lifestyle backgrounds are refused (use reference_edit).
"""
from __future__ import annotations

from pathlib import Path


def _connected_to_border(candidate):
    import numpy as np
    region = np.zeros_like(candidate)
    region[0, :] = candidate[0, :]
    region[-1, :] = candidate[-1, :]
    region[:, 0] = candidate[:, 0]
    region[:, -1] = candidate[:, -1]
    while True:
        grown = region.copy()
        grown[1:, :] |= region[:-1, :]
        grown[:-1, :] |= region[1:, :]
        grown[:, 1:] |= region[:, :-1]
        grown[:, :-1] |= region[:, 1:]
        grown &= candidate
        if (grown == region).all():
            return region
        region = grown


def propose_mask(image, tolerance=24.0, uniformity=12.0, work_size=600):
    """Return (mask L-image, stats) or raise ValueError when the background is not plain."""
    import numpy as np
    from PIL import Image, ImageFilter
    rgb = image.convert("RGB")
    full = np.asarray(rgb, dtype=np.float32)
    border = np.concatenate([full[:3].reshape(-1, 3), full[-3:].reshape(-1, 3),
                             full[:, :3].reshape(-1, 3), full[:, -3:].reshape(-1, 3)])
    background = np.median(border, axis=0)
    spread = float(np.percentile(np.linalg.norm(border - background, axis=1), 90))
    if spread > uniformity:
        raise ValueError(f"Background is not plain (border colour spread {spread:.1f} > {uniformity}); "
                         "use reference_edit or supply a reviewed cutout")
    scale = min(1.0, work_size / max(rgb.size))
    small = rgb.resize((max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))), Image.Resampling.BILINEAR)
    small_candidate = np.linalg.norm(np.asarray(small, dtype=np.float32) - background, axis=2) < tolerance
    region = _connected_to_border(small_candidate)
    region_full = Image.fromarray((region * 255).astype("uint8")).resize(rgb.size, Image.Resampling.NEAREST)
    region_full = np.asarray(region_full.filter(ImageFilter.MaxFilter(7))) > 0  # tolerate the scale step at edges
    candidate_full = np.linalg.norm(full - background, axis=2) < tolerance
    product = ~(candidate_full & region_full)
    mask = Image.fromarray((product * 255).astype("uint8"), "L")
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))  # drop isolated specks
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))  # 1 px natural edge
    coverage = float(np.asarray(mask, dtype=np.float32).mean() / 255)
    if not 0.01 <= coverage <= 0.97:
        raise ValueError(f"Implausible product coverage {coverage:.2%}; supply a reviewed cutout instead")
    return mask, {"background_rgb": [round(float(v), 1) for v in background], "border_spread": round(spread, 2),
                  "product_coverage": round(coverage, 4), "tolerance": tolerance}


def overlay(image, mask):
    import numpy as np
    from PIL import Image
    rgb = image.convert("RGB")
    tint = Image.new("RGB", rgb.size, (255, 0, 160))
    step = max(8, rgb.width // 60)
    ys, xs = np.indices((rgb.height, rgb.width))
    shade = np.where(((xs // step + ys // step) % 2).astype(bool), 220, 255).astype("uint8")
    checker = Image.fromarray(np.dstack([shade, shade, shade]), "RGB")
    shown = Image.composite(rgb, Image.blend(checker, tint, 0.25), mask)
    shown.thumbnail((1200, 1200))
    return shown


def make_cutout(manifest, base, reference_id, *, tolerance=24.0):
    from PIL import Image, ImageOps
    import lc_image_pipeline as p
    base = Path(base).resolve()
    ref = next((item for item in manifest.get("references", []) if item.get("id") == reference_id), None)
    if ref is None:
        raise p.PipelineError(f"Unknown reference: {reference_id}")
    path = p.resolve_path(ref.get("path"), base)
    if path is None or not path.is_file():
        raise p.PipelineError(f"Reference file missing: {ref.get('path')}")
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    try:
        mask, stats = propose_mask(image, tolerance=tolerance)
    except ValueError as exc:
        raise p.PipelineError(f"CUTOUT_NOT_AVAILABLE: {exc}") from exc
    mask_path = base / "source" / "masks" / f"{reference_id}-mask.png"
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(mask_path)
    preview = base / "review" / "cutouts" / f"{reference_id}-overlay.jpg"
    preview.parent.mkdir(parents=True, exist_ok=True)
    overlay(image, mask).save(preview, format="JPEG", quality=85)
    layer = {"reference_id": reference_id, "asset_path": ref["path"], "mask_path": p.relpath(mask_path, base),
             "asset_origin": "original", "source_reference_ids": [reference_id]}
    if ref.get("product_bbox_norm"):
        layer["crop_bbox_norm"] = list(ref["product_bbox_norm"])
    return {"reference": reference_id, "mask": p.relpath(mask_path, base), "overlay": p.relpath(preview, base),
            "stats": stats, "suggested_layer": layer,
            "next_action": ("View the overlay (magenta = removed background). If the product edge is right, add "
                            "suggested_layer to the job's product_layers, then source-review-prepare/submit "
                            "(set that layer reviewed=true) and plan. Otherwise keep reference_edit.")}
