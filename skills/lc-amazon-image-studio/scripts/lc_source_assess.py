"""Source-review pre-assessment (V7.1, user decision D3): measured proposals, agent confirms.

The agent still looks at the source sheet. Values it would otherwise type field by
field are proposed from measurements the pipeline already takes (edge signal over
the native product crop and its 3x3 tiles, product pixel size against the largest
planned use, detail-crop sizes, view match). Proposals are conservative:

- `clear` only with margin (strong edge signal, no weak tile, upscale within limit);
  `mild_softness` in between; otherwise no proposal (the agent decides);
- `blurred` is never proposed (a smooth material looks like blur to any metric);
- the census is proposed only when every P0/P1 detail is confirmed by the agent's own
  detail records and has a location.

Accepting proposals requires one observation sentence on submit
(`source-review-submit --observation ...`). Version: source-preassess-v1.
"""
from __future__ import annotations

from pathlib import Path

VERSION = "source-preassess-v1"
EDGE_CLEAR, EDGE_MILD, WEAK_TILE = 2.0, 1.0, 0.35
MIN_DETAIL_CROP = (32, 8)


def _product_pixels(base, ref):
    metrics = ref.get("quality_metrics") or {}
    crop = metrics.get("product_crop_path")
    if crop:
        try:
            from PIL import Image
            with Image.open(Path(base) / crop) as image:
                return image.size
        except OSError:
            pass
    return None


def _largest_use(manifest, ref_id):
    """Largest planned product size in pixels among jobs that use this reference."""
    best = 0
    for job in manifest.get("jobs", []):
        if ref_id not in (job.get("source_reference_ids") or []):
            continue
        box, canvas = job.get("target_product_bbox_norm"), job.get("canvas")
        if isinstance(box, list) and len(box) == 4 and isinstance(canvas, list) and len(canvas) == 2:
            best = max(best, box[2] * canvas[0], box[3] * canvas[1])
    return best


def propose_reference(manifest, base, ref):
    metrics = ref.get("quality_metrics") or {}
    edge = metrics.get("edge_signal")
    tiles = [t.get("edge_signal") for t in metrics.get("tiles", []) if isinstance(t.get("edge_signal"), (int, float))]
    size = _product_pixels(base, ref)
    use = _largest_use(manifest, ref.get("id"))
    upscale = round(use / max(size), 3) if size and use else None
    limit = float((manifest.get("product_truth") or {}).get("max_marginal_upscale_ratio", 1.75))
    clarity = None
    if isinstance(edge, (int, float)) and tiles:
        median = sorted(tiles)[len(tiles) // 2]
        weak = min(tiles) < WEAK_TILE * median if median else True
        if edge >= EDGE_CLEAR and not weak and (upscale is None or upscale <= limit):
            clarity = "clear"
        elif edge >= EDGE_MILD:
            clarity = "mild_softness"
    evidence = "sufficient" if clarity in {"clear", "mild_softness"} else None
    notes = (f"Auto pre-assessment ({VERSION}): edge signal {edge}, weakest tile {min(tiles) if tiles else None}, "
             f"product {size[0]}x{size[1]} px" if size else f"Auto pre-assessment ({VERSION}): edge signal {edge}")
    if upscale is not None:
        notes += f", largest planned use needs {upscale}x"
    return {"clarity": clarity, "evidence": evidence, "defects": [], "notes": notes + "."}


def _detail_ready(detail):
    if detail.get("visual_confirmation") != "confirmed" or not detail.get("locations"):
        return False
    crops = detail.get("reference_crops") or []
    if crops:
        return any((c.get("size") or [0, 0])[0] >= MIN_DETAIL_CROP[0] and (c.get("size") or [0, 0])[1] >= MIN_DETAIL_CROP[1]
                   or c.get("verifiable") for c in crops)
    return True


def propose_job(manifest, job, reference_proposals):
    refs = {ref.get("id"): ref for ref in manifest.get("references", [])}
    used = [rid for rid in (job.get("source_reference_ids") or []) if rid in refs]
    clarities = [reference_proposals.get(rid, {}).get("clarity") for rid in used]
    same_view = [rid for rid in used if refs[rid].get("view") == job.get("target_view", job.get("view"))
                 and "detail" not in str(refs[rid].get("role", ""))]
    if job.get("kind") == "main" and same_view:
        scene_fit, matched = "matched", same_view[:1]
    else:
        scene_fit, matched = "new_view", []
    required = [d for d in manifest.get("critical_details", [])
                if (d.get("visibility") or {}).get(job.get("id")) == "required" and d.get("priority") in {"P0", "P1"}]
    evidence = None
    if clarities and all(c in {"clear", "mild_softness"} for c in clarities) and all(_detail_ready(d) for d in required):
        evidence = "sufficient"
    degradation = {"clear": "none", "mild_softness": "mild"}.get(clarities[0]) if clarities and len(set(clarities)) == 1 else None
    reason = (f"Auto pre-assessment ({VERSION}): {scene_fit} from references {used}; "
              f"{len(required)} required P0/P1 detail(s) {'verifiable' if evidence else 'need a decision'}.")
    return {"scene_fit": scene_fit, "evidence": evidence, "degradation": degradation, "reason": reason,
            "matched_reference_ids": matched}


def propose_census(manifest):
    details = [d for d in manifest.get("critical_details", []) if d.get("priority") in {"P0", "P1"}]
    return all(_detail_ready(d) for d in details)  # vacuously complete without P0/P1 details
