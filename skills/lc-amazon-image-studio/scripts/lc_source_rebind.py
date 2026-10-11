"""Auto-rebind a source assessment when only a layout-driven product box moved (V7.1, D3).

The reviewed source context includes the planned product box. Switching a layout
recipe or text box (by hand or by auto-fit) moves that box, which used to send the
job back through a whole new source review although nothing the reviewer judged had
changed. Rebinding happens only when all of these hold:

- the job is blocked by SOURCE_ASSESSMENT_CONTEXT_STALE;
- of the reviewed context inputs, only `target_product_bbox_norm` differs;
- that box is the one the layout derives (template placement, no geometry lock);
- with the old box, today's fingerprint reproduces the stored one exactly (so no
  reference, detail, review or layer changed).

Then the decision is recomputed on the new box: computed checks such as the upscale
limit still block, and the processing route still follows the recommendation.
"""
from __future__ import annotations

import copy
import time


def rebind_layout_only(manifest, base, selected):
    import lc_quality as q
    from lc_layout import layout_geometry
    from lc_source_review import CONTEXT_KEYS, _context_inputs
    rebound = []
    for job in manifest.get("jobs", []):
        if job.get("id") not in selected or job.get("status") != "blocked":
            continue
        if "SOURCE_ASSESSMENT_CONTEXT_STALE" not in str(job.get("blocked_reason", "")):
            continue
        assessment = job.get("source_assessment") or {}
        previous = assessment.get("reviewed_context_inputs")
        if not isinstance(previous, dict):
            continue
        current = _context_inputs(job)
        if [key for key in CONTEXT_KEYS if previous.get(key) != current.get(key)] != ["target_product_bbox_norm"]:
            continue
        if job.get("generation_geometry_lock") or job.get("placement_mode", "template") != "template" or not job.get("layout"):
            continue
        try:
            if layout_geometry(job)["product_region_norm"] != current["target_product_bbox_norm"]:
                continue
        except Exception:  # noqa: BLE001 - not a layout-driven box
            continue
        probe = copy.deepcopy(job)
        probe["target_product_bbox_norm"] = copy.deepcopy(previous["target_product_bbox_norm"])
        if q.decide_job(manifest, probe).get("assessment_context_fingerprint") != assessment.get("reviewed_context_fingerprint"):
            continue
        assessment["reviewed_context_fingerprint"] = q.decide_job(manifest, job)["assessment_context_fingerprint"]
        assessment["reviewed_context_inputs"] = current
        assessment.setdefault("rebinds", []).append({"at": time.time(), "reason": "layout_box_only",
                                                     "from": previous["target_product_bbox_norm"],
                                                     "to": current["target_product_bbox_norm"]})
        decision = q.decide_job(manifest, job)
        job["render_decision"] = decision
        job["effective_upscale_ratio"] = decision.get("effective_upscale_ratio")
        if decision.get("blocked_reasons"):
            job["blocked_reason"] = "QUALITY_" + ";".join(decision["blocked_reasons"])
        else:
            job["status"] = "pending"
            job.pop("blocked_reason", None)
            if decision.get("recommended_mode"):
                job["render_mode"] = decision["recommended_mode"]
        rebound.append(job["id"])
    return rebound
