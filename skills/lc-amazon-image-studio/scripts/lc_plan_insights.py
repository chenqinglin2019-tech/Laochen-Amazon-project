"""Plan insights: report every problem at once and say what to do next.

Called from the (orchestration-only) prepare step. It never approves anything and
never changes a blocked job's status; it only adds `plan_issues`,
`layout_alternatives` and a layout-fit attempt counter, and maps blockers to
concrete next actions. Measuring source-blocked jobs early avoids discovering
typography problems one gate at a time.
"""
from __future__ import annotations

import copy

LAYOUT_FIT_BUDGET = 3

# (blocked-reason prefix, action, command hint) in priority order.
ACTION_RULES = (
    ("QUALITY_REPAIR_LIMIT_REACHED", "ask_user", "Quality repair budget spent: get new evidence or approval, then "
     "`transition --job <id> --status pending --reason <why>`"),
    ("QUALITY_SOURCE_", "source_review", "source-review-prepare → view sheet → source-review-submit → plan"),
    ("QUALITY_", "source_review", "source-review-prepare → view sheet → source-review-submit → plan"),
    ("SOURCE_", "source_review", "source-review-prepare → view sheet → source-review-submit → plan"),
    ("CENSUS_", "source_review", "inspect every P0/P1 source in source-review, set critical_detail_census_completed"),
    ("DESIGN_REFERENCE_REQUIRED", "choose_design", "recommend → set design_template_set_id (or author an original design_brief)"),
    ("DESIGN_COPY:LAYOUT_FIT_BUDGET_EXHAUSTED", "ask_user", "three layouts failed: ask the user for shorter approved copy, "
     "another image position or module"),
    ("DESIGN_COPY:TYPOGRAPHY_PREFLIGHT", "fix_layout", "use layout_alternatives (recipes that fit) or enlarge the text box"),
    ("DESIGN_COPY:", "fix_copy", "fix the listed copy/design contract issue, then plan"),
    ("DETAIL_UNVERIFIABLE", "evidence", "supply a readable source for the required detail or hide it in this view"),
    ("DETAIL_VIEW_UNVERIFIABLE", "evidence", "supply a readable source for the required detail or hide it in this view"),
    ("LOCAL_BACKGROUND:", "fix_background", "fix the background normalization inputs, then plan"),
)


def action_for(reason: str):
    for prefix, action, hint in ACTION_RULES:
        if str(reason).startswith(prefix):
            return action, hint
    return "inspect", "read the blocked reason and fix its input, then plan"


def gate_actions(manifest):
    """Group blocked jobs by next action; shared gates first."""
    grouped = {}
    for reason in (manifest.get("generation_gate") or {}).get("shared_reasons", []):
        action, hint = action_for(reason if not str(reason).startswith("CENSUS") else "CENSUS_")
        grouped.setdefault((action, hint), set()).add("*")
    for job in manifest.get("jobs", []):
        if job.get("status") != "blocked":
            continue
        action, hint = action_for(job.get("blocked_reason", ""))
        grouped.setdefault((action, hint), set()).add(job["id"])
    return [{"action": action, "jobs": sorted(jobs), "how": hint} for (action, hint), jobs in grouped.items()]


def _typography_candidate(job, is_hold):
    from lc_design import resolve_text_mode
    return (job.get("render_mode") != "pixel_composite" and not is_hold(job) and job.get("_project_style")
            and resolve_text_mode(job) == "local_overlay")


def layout_alternatives(manifest, base, job_ids):
    """Recipes (with their default boxes) that fit each job's approved copy; one render batch."""
    from lc_layout_v3 import RECIPES
    from lc_project_contracts import preflight_layout_fit
    scratch = copy.deepcopy(manifest)
    variants, labels = [], {}
    for job in manifest.get("jobs", []):
        if job["id"] not in job_ids or (job.get("layout") or {}).get("version") != 3:
            continue
        current = (job.get("layout") or {}).get("recipe") or ((job.get("design_brief") or {}).get("layout") or {}).get("recipe")
        brief_layout = (job.get("design_brief") or {}).get("layout") or {}
        explicit_boxes = (any("box" in group for group in (job.get("layout") or {}).get("text_groups", []))
                          or "text_group_box" in (job.get("layout") or {}) or "text_group_box" in brief_layout)
        for recipe in RECIPES:
            if recipe == current and not explicit_boxes:
                continue  # identical to what was just measured
            label = f"{recipe}:default_boxes" if recipe == current else recipe
            variant = copy.deepcopy(job)
            # Renderer ids become file names/selectors: keep them plain.
            variant["id"] = f"{job['id']}-alt{len(labels)}"
            labels[variant["id"]] = (job["id"], label)
            variant["layout"]["recipe"] = recipe
            for group in variant["layout"].get("text_groups", []):
                group.pop("box", None)
            for key in ("text_group_box", "product_region_norm"):
                variant["layout"].pop(key, None)
            brief_layout = (variant.get("design_brief") or {}).get("layout")
            if isinstance(brief_layout, dict):
                for key in ("recipe", "text_group_box", "product_region_norm", "canvas_variants"):
                    brief_layout.pop(key, None)
            variant.pop("typography_preflight", None)
            try:
                # Each recipe brings its own product container; measure against it.
                from lc_layout import layout_geometry
                variant["target_product_bbox_norm"] = layout_geometry(variant)["product_region_norm"]
            except (ValueError, KeyError, TypeError):
                continue
            variants.append(variant)
    if not variants:
        return {}
    scratch["jobs"] = variants
    try:
        measured = preflight_layout_fit(scratch, base, [variant["id"] for variant in variants])
    except (ValueError, OSError, KeyError, TypeError):
        return {}
    fits = {}
    for row in measured.get("jobs", []):
        if row.get("passed") and row.get("id") in labels:
            job_id, label = labels[row["id"]]
            fits.setdefault(job_id, []).append(label)
    return fits


def collect_plan_issues(manifest, base, selected, contract_report, is_hold):
    from lc_project_contracts import preflight_layout_fit
    local = {row["id"]: row["issues"] for row in contract_report.get("jobs", []) if row.get("issues")}
    jobs = [job for job in manifest.get("jobs", []) if job["id"] in selected]
    # Measure text for jobs already blocked by an earlier gate (status untouched).
    early = [job["id"] for job in jobs if job.get("status") == "blocked"
             and not str(job.get("blocked_reason", "")).startswith("DESIGN_COPY") and _typography_candidate(job, is_hold)]
    early_fit = {}
    if early and not contract_report.get("shared_issues"):
        try:
            early_fit = {row["id"]: row for row in preflight_layout_fit(manifest, base, early)["jobs"]}
        except (ValueError, OSError, KeyError, TypeError):
            early_fit = {}
    failing = []
    for job in jobs:
        issues = []
        if job.get("status") == "blocked":
            issues.extend(part for part in str(job.get("blocked_reason", "")).split(";") if part)
        issues.extend(local.get(job["id"], []))
        record = early_fit.get(job["id"]) or job.get("typography_preflight") or {}
        if record and record.get("passed") is False:
            detail = "; ".join(str(check.get("detail") or check.get("check")) for check in record.get("checks", [])
                               if check.get("passed") is False)[:300]
            issues.append("TYPOGRAPHY_PREFLIGHT: " + (detail or "planned text does not fit"))
            failing.append(job["id"])
        deduped = list(dict.fromkeys(issues))
        if deduped:
            job["plan_issues"] = deduped
        else:
            job.pop("plan_issues", None)
    # Bound trial-and-error on layouts that do not fit.
    for job in jobs:
        record = job.get("typography_preflight") or {}
        if job["id"] in failing and record.get("fingerprint"):
            if job.get("layout_fit_last_failure") != record["fingerprint"]:
                job["layout_fit_failures"] = job.get("layout_fit_failures", 0) + 1
                job["layout_fit_last_failure"] = record["fingerprint"]
            other_block = job.get("status") == "blocked" and not str(job.get("blocked_reason", "")).startswith("DESIGN_COPY")
            if (job["layout_fit_failures"] >= LAYOUT_FIT_BUDGET and not other_block
                    and job.get("status") in {"pending", "blocked", "generation_repair_needed"}):
                job["status"] = "blocked"
                job["blocked_reason"] = ("DESIGN_COPY:LAYOUT_FIT_BUDGET_EXHAUSTED: three layout attempts did not fit the "
                                         "approved copy; ask the user for shorter copy, another image position or module")
        elif record.get("passed") is True:
            job.pop("layout_fit_failures", None)
            job.pop("layout_fit_last_failure", None)
    alternatives = layout_alternatives(manifest, base, set(failing)) if failing else {}
    for job in jobs:
        if job["id"] in alternatives:
            job["layout_alternatives"] = sorted(alternatives[job["id"]])
        elif job["id"] not in failing:
            job.pop("layout_alternatives", None)
    return {"issues": {job["id"]: job["plan_issues"] for job in jobs if job.get("plan_issues")},
            "layout_alternatives": alternatives}
