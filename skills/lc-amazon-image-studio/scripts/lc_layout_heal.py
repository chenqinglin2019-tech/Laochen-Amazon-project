"""Remove the legacy V1 `layout.template` trap from V3 jobs.

Older `init` scaffolds kept `layout.template` (dimensions/components/detail/benefits)
on V3 secondary jobs. V3 geometry inherits it, and the renderer then demands
supporting `items` the job never has ("<template> requires supporting items"), so
typography preflight fails, every layout alternative fails the same way, and the
fit budget finally asks the user for shorter copy. Such a job can never have
rendered, and with no items its generation geometry is the same without the key,
so healing changes no prompt or generation fingerprint.

The slot's layout intent survives as job-level `default_recipe`, applied only when
neither the layout nor the adopted design brief chooses a recipe.
"""
from __future__ import annotations

ITEM_TEMPLATES = {"dimensions": "detail_callouts", "detail": "detail_callouts",
                  "components": "photo_sidebar", "benefits": "header_footer"}


def heal_legacy_templates(manifest, selected=None):
    """Before validation: drop item-requiring legacy templates from V3 jobs without items."""
    healed = []
    for job in manifest.get("jobs", []):
        if selected is not None and job.get("id") not in selected:
            continue
        layout = job.get("layout")
        if not isinstance(layout, dict) or layout.get("version") != 3 or layout.get("items"):
            continue
        template = layout.get("template")
        if template not in ITEM_TEMPLATES:
            continue
        layout.pop("template")
        job.setdefault("default_recipe", ITEM_TEMPLATES[template])
        job["layout_heal"] = {"removed_template": template, "default_recipe": job["default_recipe"]}
        healed.append(job.get("id"))
    return healed


def apply_default_recipes(manifest, selected=None):
    """After design briefs resolve: pin the slot default only when nothing else chose a recipe."""
    applied = []
    for job in manifest.get("jobs", []):
        if selected is not None and job.get("id") not in selected:
            continue
        layout = job.get("layout")
        default = job.get("default_recipe")
        if not isinstance(layout, dict) or layout.get("version") != 3 or not default:
            continue
        brief_recipe = ((job.get("design_brief") or {}).get("layout") or {}).get("recipe")
        if job.get("layout_recipe_source") == "slot_default" and brief_recipe:
            layout.pop("recipe", None)          # a design brief now decides
            job.pop("layout_recipe_source", None)
            continue
        if "recipe" in layout or brief_recipe or job.get("generation_geometry_lock"):
            continue
        layout["recipe"], job["layout_recipe_source"] = default, "slot_default"
        applied.append(job.get("id"))
    return applied
