"""Apply a measured layout alternative automatically when approved copy does not fit (V7.1).

Plan already measures every recipe for a job whose text fails typography preflight
(`layout_alternatives`). Instead of returning that list to the agent (and, after
three tries, asking the user for shorter copy), the first fitting alternative is
written into the job's own layout: the recipe plus its default text/product boxes,
exactly the geometry that was measured. Copy and font sizes never change; the
design brief is untouched (explicit layout keys take precedence over it). The job is
then re-prepared once, so prompts, source binding and typography are current.

Opt out per job with `layout_recipe_locked: true`. Recorded in `job.layout_autofit`.
"""
from __future__ import annotations

import copy
import time

_RUNNING = {"active": False}
PANEL_RECIPES = {"scene_grid", "steps"}


def _overlap(a, b):
    width = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    height = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0.0, width) * max(0.0, height)


def _choose(job, labels):
    """Current recipe (default boxes) first, then the composition closest to the current one."""
    from lc_layout import layout_geometry
    from lc_layout_v3 import RECIPES, recipe_geometry
    layout = job.get("layout") or {}
    current = layout.get("recipe") or ((job.get("design_brief") or {}).get("layout") or {}).get("recipe")
    try:
        product = layout_geometry(job)["product_region_norm"]
    except Exception:  # noqa: BLE001
        product = [0.0, 0.0, 1.0, 1.0]
    width, height = job["canvas"]
    order = list(RECIPES)
    options = []
    for label in labels:
        recipe = label.split(":", 1)[0]
        if recipe in PANEL_RECIPES and not layout.get("panels") and current not in PANEL_RECIPES:
            continue
        overlap = _overlap(product, recipe_geometry(recipe, width, height)["product"])
        options.append((0 if recipe == current else 1, -overlap, order.index(recipe) if recipe in order else 99, recipe))
    return min(options)[-1] if options else None


def _apply(job, recipe):
    from lc_layout_v3 import recipe_geometry
    width, height = job["canvas"]
    geometry = recipe_geometry(recipe, width, height)
    layout = job["layout"]
    before = {"recipe": layout.get("recipe"), "boxes": [g.get("box") for g in layout.get("text_groups", [])]}
    layout["recipe"] = recipe
    for index, group in enumerate(layout.get("text_groups", [])):
        if index < len(geometry["groups"]):
            group["box"] = copy.deepcopy(geometry["groups"][index])
    layout.pop("text_group_box", None)
    layout["product_region_norm"] = copy.deepcopy(geometry["product"])
    job["layout_autofit"] = {"from": before, "to": recipe, "at": time.time()}
    job.pop("layout_fit_failures", None)
    job.pop("layout_fit_last_failure", None)


def autofit(manifest, base, selected, prepare_again):
    """Return the job ids whose layout was changed (and re-prepared)."""
    from lc_composition import enabled
    if enabled(manifest):
        # Measured alternatives remain available for visual selection; capacity
        # alone cannot authorize a different composition.
        return []
    if _RUNNING["active"]:
        return []
    changed = []
    for job in manifest.get("jobs", []):
        if job.get("id") not in selected or job.get("status") != "blocked":
            continue
        if not str(job.get("blocked_reason", "")).startswith(("DESIGN_COPY:TYPOGRAPHY_PREFLIGHT", "DESIGN_COPY:LAYOUT_FIT_BUDGET")):
            continue
        if job.get("layout_recipe_locked") or job.get("generation_geometry_lock") or (job.get("layout") or {}).get("version") != 3:
            continue
        recipe = _choose(job, job.get("layout_alternatives") or [])
        if not recipe:
            continue
        _apply(job, recipe)
        job["status"] = "pending"
        job.pop("blocked_reason", None)
        changed.append(job["id"])
    if changed:
        _RUNNING["active"] = True
        try:
            prepare_again(set(changed))
        finally:
            _RUNNING["active"] = False
    return changed
