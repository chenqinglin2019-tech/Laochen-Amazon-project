"""Project adapter for portable design templates; no model or image I/O.

Selected text snapshots are project inputs. Library changes never silently
replace them, and an unresolved design never becomes a product fact.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def validate_template_inputs(manifest):
    if not isinstance(manifest, dict):
        return ["Template project must be an object"]
    errors = []
    jobs = manifest.get("jobs", [])
    if not isinstance(jobs, list):
        errors.append("Template project jobs must be a list")
        jobs = []
    if "design_template_policy" in manifest:
        policy = manifest["design_template_policy"]
        if (not isinstance(policy, dict) or set(policy) != {"version", "mode"}
                or type(policy.get("version")) is not int or policy["version"] != 1
                or policy.get("mode") != "auto"):
            errors.append("design_template_policy requires {version:1,mode:auto}")
    objects = [("project", manifest, "design_template_set_id", "design_template_set_revision")]
    objects += [(str(j.get("id", "job")), j, "design_template_id", "design_template_revision")
                for j in jobs if isinstance(j, dict)]
    for label, obj, id_key, rev_key in objects:
        if id_key in obj and (not isinstance(obj[id_key], str) or not ID.fullmatch(obj[id_key])):
            errors.append(f"{label}.{id_key} must be a stable ID")
        if rev_key in obj and (id_key not in obj or type(obj[rev_key]) is not int or obj[rev_key] < 1):
            errors.append(f"{label}.{rev_key} requires an ID and a positive integer")
        if id_key == "design_template_id" and obj.get(id_key) and obj.get("design_reference_id"):
            errors.append(f"{label}: choose a template or external reference, not both")
    for key in ("design_template_library_path", "design_template_user_library_path"):
        if key in manifest and (not isinstance(manifest[key], str) or not manifest[key].strip()
                                or "\x00" in manifest[key] or "://" in manifest[key]):
            errors.append(f"{key} must be a local file path")
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if "design_template_original_reason" in job and (
                not isinstance(job["design_template_original_reason"], str)
                or not job["design_template_original_reason"].strip()):
            errors.append(f"{job.get('id')}: original design needs a nonempty reason")
        if job.get("design_template_original_reason") and (job.get("design_template_id") or job.get("design_reference_id")):
            errors.append(f"{job.get('id')}: original design and explicit template/reference are mutually exclusive")
        if "design_resolution" in job and not isinstance(job["design_resolution"], dict):
            errors.append(f"{job.get('id')}: design_resolution must be an object")
        if "design_overrides" in job:
            value = job["design_overrides"]
            if (not isinstance(value, dict) or set(value) - {"generation", "layout"}
                    or any(not isinstance(v, dict) for v in value.values())):
                errors.append(f"{job.get('id')}: design_overrides accepts generation/layout objects only")
    return errors


def uses_templates(manifest, job):
    # An explicit external reference preserves the legacy path even in a new
    # project. A per-image template is more specific than project references.
    if job.get("design_reference_id"):
        return False
    if job.get("design_template_id"):
        return True
    if job.get("design_template_original_reason"):
        return True
    if manifest.get("design_reference_ids"):
        return False
    return ("design_template_policy" in manifest or "design_template_set_id" in manifest
            or (job.get("design_resolution") or {}).get("source") in
            {"template_library", "original_design"})


def template_resolution_issue(job):
    """Recheck adopted text, never the source screenshot or current library."""
    from lc_design_templates import binding_issue
    resolution = job.get("design_resolution") or {}
    if resolution.get("source") not in {"template_library", "original_design"}:
        return None
    if resolution.get("status") != "selected":
        return "design_template_needs_input"
    if resolution.get("source") == "template_library":
        issue = binding_issue(resolution.get("binding"))
        if issue:
            return issue
    if resolution.get("brief_hash") != digest(job.get("design_brief")):
        return "design_template_brief_changed_run_prepare"
    return None


def prepare_template_briefs(manifest, base, selected):
    import lc_design_templates as library_api
    from lc_style_reference import ReferenceIndexError
    errors = validate_template_inputs(manifest)
    if errors:
        raise ReferenceIndexError("; ".join(errors))
    result = {"changed": [], "cached": [], "needs_input": []}
    jobs = [j for j in manifest.get("jobs", []) if j["id"] in selected
            and j.get("kind") != "main" and j.get("text_mode") != "none"]
    if not jobs:
        return result
    context = {"product": (manifest.get("product_truth") or {}).get("product", ""),
               "category": manifest.get("category") or (manifest.get("product_truth") or {}).get("category", ""),
               "style_preferences": manifest.get("design_style_preferences", "")}
    project_request = {"id": manifest.get("design_template_set_id"),
                       "revision": manifest.get("design_template_set_revision")}
    catalog = None

    def load():
        nonlocal catalog
        if catalog is None:
            kwargs = {}
            for field, arg in (("design_template_library_path", "builtin_path"),
                               ("design_template_user_library_path", "user_path")):
                if field in manifest:
                    path = Path(manifest[field])
                    kwargs[arg] = path if path.is_absolute() else Path(base) / path
            catalog = library_api.load_library(**kwargs)
        return catalog

    def assign(job, brief, resolution):
        if job.get("design_brief") == brief and job.get("design_resolution") == resolution:
            result["cached"].append(job["id"])
        else:
            job["design_brief"], job["design_resolution"] = brief, resolution
            result["changed"].append(job["id"])

    def unresolved(job, reason):
        # Keep old assets and snapshots for recovery, but close new dispatch.
        resolution = copy.deepcopy(job.get("design_resolution") or {})
        resolution.update(status="needs_input", source="template_library", required=True,
                          matched=False, reason=reason)
        job["design_resolution"] = resolution
        result["needs_input"].append(job["id"])

    def family_entry(family):
        return {"id": family["id"], "revision": family["revision"],
                "content_hash": library_api.content_hash(family), "snapshot": copy.deepcopy(family)}

    saved_set = manifest.get("design_template_selection") or {}
    if not isinstance(saved_set, dict):
        raise ReferenceIndexError("design_template_selection must be an object")

    for job in jobs:
        previous = job.get("design_resolution") or {}
        explicit = job.get("design_template_id")
        request = {"template_id": explicit, "template_revision": job.get("design_template_revision"),
                   "project": project_request}
        # A deliberate authored brief is not silently replaced by ranking.
        original_reason = job.get("design_template_original_reason")
        if (not explicit and job.get("design_brief") and (original_reason or (
                not project_request["id"] and (not previous or previous.get("source") == "original_design")))):
            brief = copy.deepcopy(job["design_brief"])
            if not brief.get("generation"):
                unresolved(job, "An original design needs a nonempty generation brief.")
                continue
            assign(job, brief, {"status": "selected", "source": "original_design", "matched": False,
                               "required": True, "brief_hash": digest(brief),
                               "reason": original_reason or "Preserved authored project design; no library match claimed."})
            continue
        try:
            binding = previous.get("binding")
            same_request = previous.get("request") == request
            if binding and same_request:
                issue = library_api.binding_issue(binding)
                if issue:
                    unresolved(job, issue)
                    continue
                family, template = binding["family"]["snapshot"], binding["template"]["snapshot"]
                reasons = previous.get("selection_reasons", [])
            else:
                family = None
                template = None
                reasons = []
                if explicit:
                    template = library_api.get_template(load(), explicit, job.get("design_template_revision"))
                    if template is None:
                        unresolved(job, f"Requested template is unavailable: {explicit}")
                        continue
                saved_family = saved_set.get("family")
                if saved_family and saved_set.get("request") == project_request:
                    snapshot = saved_family.get("snapshot") if isinstance(saved_family, dict) else None
                    if (not isinstance(snapshot, dict) or saved_family.get("content_hash") != library_api.content_hash(snapshot)
                            or saved_family.get("id") != snapshot.get("id")
                            or saved_family.get("revision") != snapshot.get("revision")):
                        unresolved(job, "Project family snapshot changed; explicitly choose the family again.")
                        continue
                    family = snapshot
                elif project_request["id"]:
                    family = library_api.get_family(load(), project_request["id"], project_request["revision"])
                    if family is None:
                        unresolved(job, f"Requested style family is unavailable: {project_request['id']}")
                        continue
                    reasons = ["User-selected project style family."]
                if template and (family is None or family["id"] != template["family_id"]):
                    family = library_api.get_family(load(), template["family_id"])
                    reasons = ["Per-image template override; other images keep their project family."]
                if family is None:
                    ranked = library_api.rank_families(load(), context)
                    if not ranked:
                        unresolved(job, "No suitable style family. Author an original design or explicitly choose a suitable template.")
                        continue
                    winner = ranked[0]
                    family = library_api.get_family(load(), winner["id"], winner["revision"])
                    reasons = winner.get("reasons", [])
                if template is None:
                    candidates = library_api.rank_templates(load(), family["id"], job)
                    if not candidates:
                        unresolved(job, "No compatible image template in the selected family. Author an original design or choose another template.")
                        continue
                    # Stable diversification only among equally suitable options;
                    # do not reduce intent/format suitability just to vary a grid.
                    top_score = candidates[0]["score"]
                    equal = [c for c in candidates if c["score"] == top_score]
                    def used(candidate):
                        return sum((j.get("design_resolution") or {}).get("binding", {}).get("template", {}).get("id") == candidate["id"]
                                   for j in manifest.get("jobs", []) if j["id"] != job["id"])
                    winner = min(equal, key=lambda c: (used(c), c["id"]))
                    template = library_api.get_template(load(), winner["id"], winner["revision"])
                    reasons = reasons + winner.get("reasons", [])
                if (not saved_set or saved_set.get("request") != project_request) and (
                        not explicit or family["id"] == project_request["id"]):
                    saved_set = {"schema_version": 1, "request": copy.deepcopy(project_request),
                                 "family": family_entry(family), "selection_reasons": reasons}
                    manifest["design_template_selection"] = saved_set
            compiled = library_api.compile_template(family, template, context, job)
            brief = compiled["brief"]
            for section, override in job.get("design_overrides", {}).items():
                brief[section].update(copy.deepcopy(override))
            if job.get("text_mode") == "local_overlay" and job.get("layout", {}).get("version") == 3:
                # Resolve after both project layout and brief overrides. Use
                # the existing dispatch lock after generation: later local
                # typesetting must not move the model's historical geometry.
                from lc_image_pipeline import generation_geometry
                planned = {**job, "design_brief": brief}
                geometry = generation_geometry(planned)
                brief["generation"]["canvas_composition"] = {
                    "product_region_norm": geometry["product_region_norm"],
                    "text_region_norm": next(iter(geometry["text_regions_norm"]), None),
                    "text_regions_norm": geometry["text_regions_norm"],
                    "notes": "These final project reservations override provisional template positions. Preserve the product inside its container and leave the text regions clear."}
            resolution = {"status": "selected", "source": "template_library", "matched": True,
                          "required": True, "request": request, "binding": compiled["binding"],
                          "brief_hash": digest(brief), "selection_reasons": reasons,
                          "adjustments": copy.deepcopy(job.get("design_overrides", {}))}
            assign(job, brief, resolution)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            unresolved(job, str(exc))
    return result
