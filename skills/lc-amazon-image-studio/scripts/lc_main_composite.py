"""Main image from a qualifying real photo instead of a model call (V7.1, user decision D4).

For projects with `main_image_policy={"version":1,"mode":"auto_composite"}`, source-review
preparation looks for a real whole-product photo of the main view on a plain light
background. When the cutout is clean and the product is large enough, the main job
gets a proposed product layer (mask + overlay on the source sheet). The agent confirms
it in the source review (`layers[].reviewed = true`, or `rejected = true`); the main
image is then composed locally on pure white by the existing pixel_composite path, so
its product pixels are 100% real and no model time is spent. All main-image QA
(white background, safe upscale) still applies. Anything doubtful falls back to the
normal model route.
"""
from __future__ import annotations

from pathlib import Path

MAX_UPSCALE, FINE_DETAIL_UPSCALE = 1.75, 1.25
MAIN_FILL = 0.85


def enabled(manifest):
    policy = manifest.get("main_image_policy")
    return isinstance(policy, dict) and policy.get("mode") == "auto_composite"


def _eligible(image, ref, job, manifest):
    import numpy as np
    from lc_cutout import propose_mask
    reasons = []
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    border = np.concatenate([rgb[:3].reshape(-1, 3), rgb[-3:].reshape(-1, 3), rgb[:, :3].reshape(-1, 3), rgb[:, -3:].reshape(-1, 3)])
    median = np.median(border, axis=0)
    luminance = float(0.2126 * median[0] + 0.7152 * median[1] + 0.0722 * median[2])
    chroma = float(median.max() - median.min())
    if luminance < 200 or chroma > 18:
        return None, [f"background not light/neutral (luminance {luminance:.0f}, chroma {chroma:.0f})"]
    try:
        mask, stats = propose_mask(image)
    except ValueError as exc:
        return None, [str(exc)]
    alpha = np.asarray(mask) > 127
    ys, xs = np.nonzero(alpha)
    if not len(xs):
        return None, ["empty mask"]
    height, width = alpha.shape
    if xs.min() <= 1 or ys.min() <= 1 or xs.max() >= width - 2 or ys.max() >= height - 2:
        reasons.append("product touches the photo edge (may be cropped)")
    box_w, box_h = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    canvas = job.get("canvas") or [2000, 2000]
    target = MAIN_FILL * min(canvas)
    upscale = round(max(target / box_w, target / box_h) if box_w and box_h else 99, 3)
    limit = FINE_DETAIL_UPSCALE if job.get("requires_fine_detail") else MAX_UPSCALE
    limit = min(limit, float((manifest.get("product_truth") or {}).get("max_marginal_upscale_ratio", limit)))
    if upscale > limit:
        reasons.append(f"product too small for the main canvas (needs {upscale}x > {limit}x)")
    pad = 0.01
    crop = [max(0.0, xs.min() / width - pad), max(0.0, ys.min() / height - pad)]
    crop += [min(1.0 - crop[0], box_w / width + 2 * pad), min(1.0 - crop[1], box_h / height + 2 * pad)]
    return ({"mask": mask, "stats": stats, "upscale": upscale, "crop": [round(v, 5) for v in crop]} if not reasons else None), reasons


def propose(manifest, base):
    """Add a proposed main-image layer when a reference qualifies; returns a report."""
    from PIL import Image, ImageOps
    import lc_image_pipeline as p
    from lc_cutout import overlay
    if not enabled(manifest):
        return None
    base = Path(base).resolve()
    main = next((job for job in manifest.get("jobs", []) if job.get("kind") == "main"), None)
    if main is None or main.get("status") not in {"pending", None} or main.get("text_mode", "none") != "none":
        return None
    record = main.get("main_composite") or {}
    if main.get("product_layers") and record.get("status") != "proposed":
        return None  # the agent's own layers always win
    refs = [ref for ref in manifest.get("references", []) if "detail" not in str(ref.get("role", ""))
            and (ref.get("provenance") or {}).get("kind", "real_photo") == "real_photo"
            and ref.get("view") == main.get("target_view", main.get("view", "front"))]
    tried = []
    for ref in refs:
        path = p.resolve_path(ref.get("path"), base)
        if path is None or not path.is_file():
            continue
        sha = p.sha256_file(path)
        if record.get("reference_id") == ref["id"] and record.get("ref_sha256") == sha and record.get("status") in {"proposed", "rejected"}:
            return {"status": record["status"], "reference": ref["id"], "cached": True}
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        result, reasons = _eligible(image, ref, main, manifest)
        if result is None:
            tried.append({"reference": ref["id"], "reasons": reasons})
            continue
        mask_path = base / "source" / "masks" / f"{ref['id']}-main-mask.png"
        mask_path.parent.mkdir(parents=True, exist_ok=True)
        result["mask"].save(mask_path)
        preview = base / "review" / "cutouts" / f"{ref['id']}-main-overlay.jpg"
        preview.parent.mkdir(parents=True, exist_ok=True)
        overlay(image, result["mask"]).save(preview, format="JPEG", quality=85)
        main["product_layers"] = [{"reference_id": ref["id"], "asset_path": ref["path"], "mask_path": p.relpath(mask_path, base),
                                   "asset_origin": "original", "source_reference_ids": [ref["id"]], "crop_bbox_norm": result["crop"]}]
        main["pixel_source_reference_id"] = ref["id"]
        main["main_composite"] = {"status": "proposed", "reference_id": ref["id"], "ref_sha256": sha,
                                  "upscale": result["upscale"], "overlay": p.relpath(preview, base),
                                  "border_spread": result["stats"].get("border_spread"),
                                  "coverage": result["stats"].get("product_coverage")}
        return {"status": "proposed", "reference": ref["id"], "overlay": main["main_composite"]["overlay"],
                "upscale": result["upscale"]}
    main["main_composite"] = {"status": "ineligible", "tried": tried}
    return {"status": "ineligible", "tried": tried}


def reject(manifest, job):
    """The agent rejected the proposed cutout: back to the model route, remembered per reference."""
    record = job.get("main_composite") or {}
    job.pop("product_layers", None)
    job.pop("pixel_source_reference_id", None)
    job["product_layers"] = []
    record["status"] = "rejected"
    job["main_composite"] = record
