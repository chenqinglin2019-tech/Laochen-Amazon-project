"""One-shot source review: one packet with current fingerprints, one binding submit.

Replaces the manual loop "prepare -> copy reviewed_sha256/region fingerprints ->
prepare -> copy assessment_context_fingerprint -> plan". The agent still looks at
every source crop and makes every judgment; code only carries the hashes. The
context fingerprint is computed after reference reviews and after template
geometry is resolved, so the following plan does not find it stale. No model calls.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

SCHEMA = "lc-source-review/1"
CONTEXT_KEYS = ("target_view", "view", "canvas", "target_product_bbox_norm", "scene", "composition", "lighting",
                "requires_fine_detail", "pixel_source_reference_id")


def _enums():
    import lc_quality as q
    return {"clarity": sorted(q.CLARITIES), "evidence": sorted(q.EVIDENCE),
            "scene_fit": sorted(q.FITS), "degradation": sorted(q.DEGRADATIONS)}


def _context_inputs(job):
    return {key: copy.deepcopy(job.get(key)) for key in CONTEXT_KEYS}


def _sheet(base, entries, out_path):
    """Numbered contact sheet of the actual product crops (one image to inspect)."""
    from PIL import Image, ImageDraw, ImageFont
    tiles = []
    for index, entry in enumerate(entries, 1):
        path = base / entry["crop"] if entry.get("crop") else None
        try:
            with Image.open(path) as image:
                tile = image.convert("RGB")
                tile.thumbnail((480, 480))
        except (OSError, TypeError, ValueError):
            tile = Image.new("RGB", (480, 480), "#dddddd")
        tiles.append((index, entry["id"], tile))
    if not tiles:
        return None
    columns = min(4, len(tiles))
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 500, rows * 540), "white")
    draw = ImageDraw.Draw(sheet)
    font_path = Path(__file__).resolve().parents[1] / "assets/fonts/NotoSans-Regular.ttf"
    try:
        font = ImageFont.truetype(str(font_path), 22)
    except OSError:
        font = ImageFont.load_default()
    for position, (index, identifier, tile) in enumerate(tiles):
        x, y = (position % columns) * 500 + 10, (position // columns) * 540 + 10
        sheet.paste(tile, (x + (480 - tile.width) // 2, y + (480 - tile.height) // 2))
        draw.text((x, y + 488), f"{index}. {identifier}", fill="#111111", font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, format="JPEG", quality=88)
    return out_path


def build_packet(manifest, base, job_ids=None):
    import lc_image_pipeline as p
    import lc_quality as q
    base = Path(base).resolve()
    selected = p.job_selection(manifest, job_ids)
    jobs = [job for job in manifest["jobs"] if job["id"] in selected]
    refs = {ref["id"]: ref for ref in manifest.get("references", [])}
    ordered = []
    for job in jobs:
        for rid in q._reference_ids(manifest, job):
            if rid in refs and rid not in ordered:
                ordered.append(rid)
    references = []
    for rid in ordered:
        ref = refs[rid]
        review = ref.get("quality_review") or {}
        bound = not q._review_problems(ref)
        references.append({
            "id": rid, "path": ref.get("path"), "role": ref.get("role"), "view": ref.get("view"),
            "product_bbox_norm": ref.get("product_bbox_norm"), "sha256": ref.get("sha256"),
            "region_fingerprint": q.source_region_fingerprint(ref),
            "crop": (ref.get("quality_metrics") or {}).get("product_crop_path"),
            "previously_bound": bound,
            "clarity": review.get("clarity") if bound else None,
            "evidence": review.get("evidence") if bound else None,
            "defects": list(review.get("defects", [])) if bound else [],
            "notes": review.get("notes", "") if bound else ""})
    job_entries, layers = [], []
    for job in jobs:
        assessment = job.get("source_assessment") or {}
        decision = q.decide_job(manifest, job)
        previous = assessment.get("reviewed_context_inputs")
        current = _context_inputs(job)
        changed = sorted(key for key in CONTEXT_KEYS if previous is not None and previous.get(key) != current.get(key))
        job_entries.append({
            "id": job["id"], **current, "source_reference_ids": q._reference_ids(manifest, job),
            "recommended_mode": decision.get("recommended_mode"), "recommendation": decision.get("reason"),
            "context_changed_since_last_review": changed,
            "scene_fit": assessment.get("scene_fit") if assessment.get("scene_fit") != "unknown" else None,
            "evidence": assessment.get("evidence") if assessment.get("evidence") != "unknown" else None,
            "degradation": assessment.get("degradation") if assessment.get("degradation") != "unknown" else None,
            "reason": assessment.get("reason", ""),
            "matched_reference_ids": list(assessment.get("matched_reference_ids", []))})
        for index, layer in enumerate(job.get("product_layers", [])):
            records = job.get("layer_asset_hashes", [])
            record = records[index] if index < len(records) else {}
            binding = layer.get("source_binding") or {}
            layers.append({"job": job["id"], "index": index, "reference_id": layer.get("reference_id"),
                           "asset_input": record.get("asset_input"), "mask_input": record.get("mask_input"),
                           "asset_sha256": record.get("asset_sha256"), "mask_sha256": record.get("mask_sha256"),
                           "reviewed": True if (binding.get("reviewed") and binding.get("reviewed_asset_sha256") == record.get("asset_sha256")
                                                and binding.get("reviewed_mask_sha256") == record.get("mask_sha256")) else None})
    sheet = _sheet(base, references, base / "review" / "source" / "sheet.jpg")
    packet = {"schema": SCHEMA, "created_at": time.time(), "enums": _enums(),
              "sheet": p.relpath(sheet, base) if sheet else None,
              "critical_detail_census_completed": bool(manifest.get("critical_detail_census_completed")),
              "references": references, "jobs": job_entries, "layers": layers,
              "instructions": ("View the sheet (and original crops where needed). Fill clarity/evidence/defects/notes per "
                               "reference and scene_fit/evidence/degradation/reason per job from what you actually see; "
                               "set layers[].reviewed=true only after checking each cutout/mask. Set "
                               "critical_detail_census_completed=true only after every P0/P1 source was inspected. "
                               "Hashes are bound by source-review-submit; never copy them by hand.")}
    out = base / "review" / "source" / "packet.json"
    p.write_json(out, packet)
    needs = [entry["id"] for entry in references if not entry["previously_bound"]] + \
            [entry["id"] for entry in job_entries if entry["scene_fit"] is None or entry["context_changed_since_last_review"]]
    return {"packet": p.relpath(out, base), "sheet": packet["sheet"], "references": len(references),
            "jobs": len(job_entries), "needs_review": needs}


def submit_packet(manifest, base, packet):
    import lc_image_pipeline as p
    import lc_quality as q
    base = Path(base).resolve()
    if not isinstance(packet, dict) or packet.get("schema") != SCHEMA:
        raise p.PipelineError("Not a source-review packet; run source-review-prepare")
    enums = _enums()
    refs = {ref["id"]: ref for ref in manifest.get("references", [])}
    errors = []
    for entry in packet.get("references", []):
        ref = refs.get(entry.get("id"))
        if ref is None:
            errors.append(f"unknown reference {entry.get('id')}")
            continue
        path = p.resolve_path(ref.get("path"), base)
        actual = p.sha256_file(path) if path and path.is_file() else "MISSING"
        if actual != entry.get("sha256") or ref.get("sha256") != entry.get("sha256") \
                or q.source_region_fingerprint(ref) != entry.get("region_fingerprint"):
            errors.append(f"{entry['id']}: source file or product box changed; run source-review-prepare again")
        for key in ("clarity", "evidence"):
            if entry.get(key) not in enums[key]:
                errors.append(f"{entry['id']}.{key} must be one of {enums[key]}")
        if not isinstance(entry.get("notes"), str) or not entry["notes"].strip():
            errors.append(f"{entry['id']}.notes must describe what was inspected")
        if not isinstance(entry.get("defects", []), list):
            errors.append(f"{entry['id']}.defects must be a list")
    jobs = {job["id"]: job for job in manifest["jobs"]}
    for entry in packet.get("jobs", []):
        if entry.get("id") not in jobs:
            errors.append(f"unknown job {entry.get('id')}")
            continue
        for key in ("scene_fit", "evidence", "degradation"):
            if entry.get(key) not in enums[key if key != "evidence" else "evidence"]:
                errors.append(f"{entry['id']}.{key} must be one of {enums[key]}")
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            errors.append(f"{entry['id']}.reason must explain the evidence decision")
    if errors:
        raise p.PipelineError("Source review rejected:\n- " + "\n- ".join(errors))
    for entry in packet.get("references", []):
        refs[entry["id"]]["quality_review"] = {
            "clarity": entry["clarity"], "evidence": entry["evidence"], "defects": list(entry.get("defects", [])),
            "notes": entry["notes"].strip(), "reviewed_sha256": entry["sha256"],
            "reviewed_region_fingerprint": entry["region_fingerprint"]}
    for entry in packet.get("layers", []):
        if entry.get("reviewed") is not True:
            continue
        job = jobs.get(entry.get("job"))
        index = entry.get("index")
        if job is None or not isinstance(index, int) or index >= len(job.get("product_layers", [])):
            raise p.PipelineError(f"Unknown product layer {entry.get('job')}[{index}]")
        layer = job["product_layers"][index]
        records = job.get("layer_asset_hashes", [])
        record = records[index] if index < len(records) else {}
        if record.get("asset_sha256") != entry.get("asset_sha256") or record.get("mask_sha256") != entry.get("mask_sha256"):
            raise p.PipelineError(f"{job['id']} layer {index} changed since the packet; run source-review-prepare again")
        provenance = refs.get(layer.get("reference_id"), {}).get("provenance", {})
        sources = set([layer.get("reference_id")] + layer.get("source_reference_ids", []) + provenance.get("source_reference_ids", []))
        layer["source_binding"] = {"reviewed": True, "reviewed_asset_sha256": record.get("asset_sha256"),
                                   "reviewed_mask_sha256": record.get("mask_sha256"),
                                   "source_reference_hashes": {rid: refs[rid]["sha256"] for rid in sources if rid in refs}}
    if packet.get("critical_detail_census_completed") is True:
        manifest["critical_detail_census_completed"] = True
    bound, blockers = [], {}
    for entry in packet.get("jobs", []):
        job = jobs[entry["id"]]
        assessment = job.setdefault("source_assessment", {})
        assessment.update({key: entry[key] for key in ("scene_fit", "evidence", "degradation")})
        assessment["reason"] = entry["reason"].strip()
        if entry.get("matched_reference_ids"):
            assessment["matched_reference_ids"] = list(entry["matched_reference_ids"])
        decision = q.decide_job(manifest, job)
        assessment["reviewed_reference_hashes"] = decision["required_reference_hashes"]
        assessment["reviewed_context_fingerprint"] = decision["assessment_context_fingerprint"]
        assessment["reviewed_context_inputs"] = _context_inputs(job)
        remaining = [reason for reason in q.decide_job(manifest, job)["blocked_reasons"]]
        if remaining:
            blockers[job["id"]] = remaining
        bound.append(job["id"])
    return {"bound_references": [entry["id"] for entry in packet.get("references", [])], "bound_jobs": bound,
            "remaining_source_blockers": blockers,
            "next_action": "plan" if not blockers else "resolve remaining_source_blockers (evidence), then plan"}
