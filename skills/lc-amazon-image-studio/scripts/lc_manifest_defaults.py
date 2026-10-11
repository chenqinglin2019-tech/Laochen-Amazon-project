"""Deterministic defaults applied before a command validates the manifest.

Each one removes a forced agent round trip on fresh projects without weakening a
gate:

- heal the legacy V1 `layout.template` trap (lc_layout_heal);
- refresh every job's derived `_project_style` binding from the manifest's
  style_contract. Validation reads that per-job copy, so a stale copy written by
  `init` made the documented style_contract edit ineffective
  ("DESIGN_COLOR_REQUIRED" forever);
- give missing per-job critical-detail visibility entries the value the prompt
  compiler already uses for them ("optional"), and inherit a detail location's
  `view` from its reference (the validator demands both to be equal anyway);
- prefill empty style roles from a user template family (V7 tokens) and, when a
  local-text job still has no colour source, compile the adopted template briefs
  first: their own text colours then satisfy validation. Explicit values always win.

Every change is recorded in `manifest["manifest_defaults"]`.
"""
from __future__ import annotations

import re
import time


def _ledger(manifest, key, value):
    record = manifest.setdefault("manifest_defaults", {})
    entries = record.setdefault(key, [])
    if value not in entries:
        entries.append(value)


def refresh_style_bindings(manifest):
    from lc_image_pipeline import bind_project_job
    for job in manifest.get("jobs", []):
        if isinstance(job, dict):
            bind_project_job(manifest, job)


def default_visibility(manifest):
    job_ids = [job.get("id") for job in manifest.get("jobs", []) if isinstance(job, dict) and job.get("id")]
    references = {ref.get("id"): ref for ref in manifest.get("references", []) if isinstance(ref, dict)}
    for detail in manifest.get("critical_details", []):
        if not isinstance(detail, dict):
            continue
        visibility = detail.setdefault("visibility", {})
        if not isinstance(visibility, dict):
            continue
        for job_id in job_ids:
            if job_id not in visibility:
                visibility[job_id] = "optional"
                _ledger(manifest, "visibility_optional", f"{detail.get('id')}:{job_id}")
        for location in detail.get("locations", []) or []:
            if isinstance(location, dict) and "view" not in location:
                reference = references.get(location.get("reference_id"))
                if reference and isinstance(reference.get("view"), str):
                    location["view"] = reference["view"]
                    _ledger(manifest, "location_view", f"{detail.get('id')}:{location.get('reference_id')}")


_NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)")


def _numbers(text):
    return {value.replace(",", ".") for value in _NUMBER.findall(str(text or ""))}


def auto_bind_claims(manifest):
    """Bind numeric copy to facts only when every number in the copy appears in a fact with evidence."""
    facts = [f for f in manifest.get("facts", []) if isinstance(f, dict) and f.get("id") and f.get("text") and f.get("evidence")]
    if not facts:
        return
    for job in manifest.get("jobs", []):
        if not isinstance(job, dict) or job.get("claim_ids"):
            continue
        groups = (job.get("layout") or {}).get("text_groups") or []
        text = " ".join(str(group.get(key) or "") for group in groups for key in ("headline", "body", "label"))
        text += " " + " ".join(str(v) for v in (job.get("copy") or {}).values())
        wanted = _numbers(text)
        if not wanted:
            continue
        matched = [f for f in facts if _numbers(f["text"]) & wanted]
        covered = set().union(*(_numbers(f["text"]) for f in matched)) if matched else set()
        if matched and wanted <= covered:
            job["claim_ids"] = [f["id"] for f in matched]
            _ledger(manifest, "claims_bound", f"{job.get('id')}:{','.join(job['claim_ids'])}")


def missing_text_colour(manifest):
    """Jobs whose local text has no colour source yet (would fail DESIGN_COLOR_REQUIRED)."""
    from lc_layout import resolve_layout_defaults
    from lc_typography import resolve_layout
    missing = []
    for job in manifest.get("jobs", []):
        if not isinstance(job, dict) or job.get("kind") == "main" or not job.get("_project_style"):
            continue
        layout = job.get("layout") or {}
        if job.get("text_mode", "local_overlay") != "local_overlay" or layout.get("version") != 3 or not layout.get("text_groups"):
            continue
        try:
            resolve_layout(job, resolve_layout_defaults(job))
        except ValueError as exc:
            if "DESIGN_COLOR_REQUIRED" in str(exc):
                missing.append(job["id"])
        except Exception:  # noqa: BLE001 - other layout problems are reported by validation
            continue
    return missing


def apply(manifest, base, *, resolve_briefs=True):
    """Return a short report; mutates `manifest` in memory (callers decide whether to save).

    Never raises: on malformed input it does nothing and validation reports the problem.
    """
    if not isinstance(manifest, dict) or not isinstance(manifest.get("jobs"), list) \
            or not all(isinstance(job, dict) for job in manifest["jobs"]):
        return {}
    try:
        return _apply(manifest, base, resolve_briefs=resolve_briefs)
    except Exception as exc:  # noqa: BLE001 - defaults are a convenience, validation is the gate
        return {"skipped": f"{type(exc).__name__}: {exc}"[:200]}


def _apply(manifest, base, *, resolve_briefs=True):
    from lc_layout_heal import heal_legacy_templates
    report = {}
    healed = heal_legacy_templates(manifest)
    if healed:
        report["healed_legacy_templates"] = healed
    default_visibility(manifest)
    auto_bind_claims(manifest)
    refresh_style_bindings(manifest)
    try:
        from lc_template_workflow_v2 import early_prefill
        early_prefill(manifest, base)
    except Exception:  # noqa: BLE001 - template selection problems surface later, with context
        pass
    if resolve_briefs:
        missing = missing_text_colour(manifest)
        if missing:
            try:
                from lc_style_reference import prepare_design_briefs
                prepare_design_briefs(manifest, base, set(missing))
                report["briefs_resolved_for_colour"] = missing
            except Exception:  # noqa: BLE001 - validation then reports the original problem
                pass
            refresh_style_bindings(manifest)
    if report:
        manifest.setdefault("manifest_defaults", {})["last_applied_at"] = time.time()
    return report
