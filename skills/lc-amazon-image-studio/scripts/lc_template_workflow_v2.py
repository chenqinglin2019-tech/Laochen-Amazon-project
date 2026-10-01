"""Template policy v2 at plan time: pick, adopt and compile user/builtin templates.

- family: explicit design_template_set_id > preferred (imported for this request) > recommend()
- per image: observed/adapted template in the family > near slot > other family restyled
  with the chosen tokens > original brief from the tokens (never needs_input)
- adoption copies the style plate + reference thumbnail into the project
  (design/plates, design/references), bound by sha256: projects never read the
  library again, so clearing or editing the library cannot change them
- the init scaffold's generic scene/composition/lighting are removed only while
  they still equal the scaffold text, so template parameters actually reach the prompt
- empty style_contract roles and missing text-group styling are prefilled from
  the family tokens with a ledger; explicit agent values always win
Replays compile from the stored snapshots (deterministic compiler version).
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

SCAFFOLD_KEYS = ("scene", "composition", "lighting")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _scaffold():
    path = Path(__file__).resolve().parents[1] / "assets/project_manifest.template.json"
    jobs = json.loads(path.read_text(encoding="utf-8")).get("jobs", [])
    return {job["id"]: job for job in jobs}, (jobs[2] if len(jobs) > 2 else {})


def neutralize_scaffold(job):
    """Drop generic init text so the adopted template drives scene/composition/lighting."""
    if job.get("kind") == "main":
        return []
    by_id, a_plus = _scaffold()
    source = by_id.get(job["id"]) or (a_plus if job.get("kind") == "a_plus" else None)
    removed = []
    for key in SCAFFOLD_KEYS:
        if source and job.get(key) and job.get(key) == source.get(key):
            job.pop(key)
            removed.append(key)
    return removed


def _copy_asset(library, sha, folder, base):
    import lc_image_pipeline as p
    source = library.asset_path(sha)
    target = Path(base) / "design" / folder / f"{sha}.jpg"
    if not target.is_file() or p.sha256_file(target) != sha:
        if not source.is_file():
            raise ValueError(f"Template asset {sha} is missing from the library")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return {"path": p.relpath(target, Path(base)), "sha256": sha}


PART_OF = {"headline": "headline", "body": "body", "eyebrow": "label", "label": "label", "feature": "label", "badge": "label"}


def _style_from_skeleton(group, primary, skeleton, palette):
    """Observed typography -> a style_v1 group style (only what the template actually specifies)."""
    from lc_layout_style import faces
    registry, style = faces(), {}
    color = lambda role: palette.get(role, "").upper() or None
    for part in ("headline", "body", "label"):
        if not group.get(part):
            continue
        spec = primary if primary and PART_OF.get(primary.get("role")) == part else \
            next((item for item in skeleton if PART_OF.get(item.get("role")) == part), None)
        if not spec:
            continue
        if spec.get("face") in registry:
            style.setdefault("faces", {})[part] = spec["face"]
        if spec.get("text_color") and part != "headline":
            style.setdefault("colors", {})[part] = spec["text_color"]
        if spec.get("case") == "uppercase":
            style.setdefault("case", {})[part] = "uppercase"
        for key in ("letter_spacing_em", "line_height"):
            if key in spec:
                style.setdefault(key, {})[part] = spec[key]
        if part == "label" and spec.get("pill") and color(spec["pill"]["color_role"]):
            style["pill"] = {"color": color(spec["pill"]["color_role"])}
            if color(spec["pill"].get("text_color_role", "accent_text")):
                style["pill"]["text_color"] = color(spec["pill"].get("text_color_role", "accent_text"))
    source = primary or {}
    divider = source.get("divider")
    after = "headline" if group.get("headline") else "body" if group.get("body") else None
    if divider and after and color(divider["color_role"]):
        style["divider"] = {"after": after, "color": color(divider["color_role"]),
                            "width_px": divider.get("width_px", 2), "length_em": divider.get("length_em", 0)}
    surface = source.get("surface") or {}
    if (group.get("surface") or {}).get("kind") in {"solid", "gradient"} and \
            any(key in surface for key in ("radius_em", "border_width_px", "shadow")):
        extra = {key: surface[key] for key in ("radius_em", "shadow") if key in surface}
        if surface.get("border_width_px") and color(surface.get("border_color_role", "muted")):
            extra.update(border_width_px=surface["border_width_px"], border_color=color(surface.get("border_color_role", "muted")))
        style["surface"] = extra
    return style


def _prefill_layout(job, brief, shape_observed, palette=None):
    """Missing styling only, by group id or role; approved copy is never written."""
    skeleton = (brief.get("layout") or {}).get("skeleton") or []
    layout = job.get("layout") or {}
    groups = layout.get("text_groups") or []
    ledger = []
    if layout.get("version") != 3 or not groups:
        return ledger
    size_key = {"headline": "headline", "body": "body"}
    for index, group in enumerate(groups):
        spec = next((item for item in skeleton if item.get("id") == group.get("id")), None) or \
            next((item for item in skeleton if item.get("role") == group.get("role")), None) or \
            (skeleton[index] if index < len(skeleton) else None)
        if not spec:
            continue
        if shape_observed and spec.get("box") and "box" not in group and index > 0:
            group["box"] = copy.deepcopy(spec["box"]); ledger.append(f"{group.get('id', index)}.box")
        for key in ("align",):
            if spec.get(key) and key not in group:
                group[key] = spec[key]; ledger.append(f"{group.get('id', index)}.{key}")
        if spec.get("text_color") and "text_color" not in group and "color_role" not in group:
            group["text_color"] = spec["text_color"]; ledger.append(f"{group.get('id', index)}.text_color")
        if spec.get("size") and "mobile_sizes" not in group:
            role = size_key.get(spec.get("role"), "label")
            group["mobile_sizes"] = {role: max(18 if role == "headline" else 12, int(spec["size"]))}
            ledger.append(f"{group.get('id', index)}.mobile_sizes")
        surface = spec.get("surface") or {}
        if surface.get("kind") in {"solid", "gradient"} and "surface" not in group and surface.get("color"):
            group["surface"] = {"kind": surface["kind"], "color": surface["color"], "opacity": surface.get("opacity", 1)}
            ledger.append(f"{group.get('id', index)}.surface")
        if "style" not in group:
            style = _style_from_skeleton(group, spec, skeleton, palette or {})
            if style:
                group["style"] = style
                ledger.append(f"{group.get('id', index)}.style")
    if any("style" in group for group in groups) and "renderer" not in layout:
        layout["renderer"] = "style_v1"
        ledger.append("renderer")
    return ledger


def _resolve_surface_colors(brief, tokens):
    palette = (tokens or {}).get("palette", {})
    for group in (brief.get("layout") or {}).get("skeleton", []) or []:
        surface = group.get("surface") or {}
        if surface.get("color_role") and palette.get(surface["color_role"]):
            surface["color"] = palette[surface["color_role"]].upper()


def prefill_style_contract(manifest, tokens):
    from lc_template_schema import style_contract_roles
    contract = manifest.get("style_contract")
    if not isinstance(contract, dict) or contract.get("version") != 3:
        return {}
    roles = style_contract_roles(tokens)
    selection = manifest.setdefault("design_template_selection", {})
    ledger = selection.setdefault("token_prefill", {})
    changed = {}
    for key in ("color_roles", "font_roles"):
        current = contract.setdefault(key, {})
        for role, value in roles[key].items():
            previous = ledger.get(key, {}).get(role)
            if role not in current or (previous is not None and current[role] == previous):
                current[role] = value
                changed.setdefault(key, {})[role] = value
                ledger.setdefault(key, {})[role] = value
    return changed


def resolution_issue_v2(job):
    """Snapshots and compiled brief only; plate bytes are bound by the generation fingerprint."""
    from lc_template_schema import binding_issue
    resolution = job.get("design_resolution") or {}
    if resolution.get("status") != "selected":
        return "design_template_needs_input"
    if resolution.get("binding"):
        issue = binding_issue(resolution["binding"])
        if issue:
            return issue
    if resolution.get("brief_hash") != _digest(job.get("design_brief")):
        return "design_template_brief_changed_run_prepare"
    return None


def prepare_template_briefs_v2(manifest, base, selected):
    import lc_image_pipeline as p
    from lc_template_library import Library
    from lc_template_schema import compile_v2
    from lc_template_select import candidate_families, recommend, slot_match, _shape
    base = Path(base).resolve()
    result = {"changed": [], "cached": [], "needs_input": []}
    library = Library(manifest.get("design_template_library_dir") and str(base / manifest["design_template_library_dir"]))
    rows = candidate_families(manifest, base, library)
    by_id = {row[0]["id"]: row for row in rows}
    explicit = manifest.get("design_template_set_id")
    reasons = []
    if explicit and explicit in by_id:
        row, reasons = by_id[explicit], ["User-selected project family."]
    elif explicit:
        # Pinned family is gone from the library: replay adopted snapshots, never reselect.
        row, reasons = None, ["Pinned family not in the library; adopted snapshots replay unchanged."]
    else:
        advice = recommend(manifest, base, top=1, library=library)
        pick = advice["selected"]
        row = by_id.get(pick["id"]) if pick else None
        if row:
            reasons = [f"Auto-selected by product profile ({advice['profile_source']}): "
                       + json.dumps(advice["families"][0]["breakdown"], sort_keys=True)]
    if row is not None and row[3] == 1:
        # Built-in text-only family: pin it and reuse the frozen v1 route.
        from lc_template_workflow import _prepare_template_briefs_v1
        manifest["design_template_set_id"] = row[0]["id"]
        manifest["design_template_set_revision"] = row[0]["revision"]
        for job in manifest["jobs"]:
            if job["id"] in selected:
                neutralize_scaffold(job)
        return _prepare_template_briefs_v1(manifest, base, selected)
    family = row[0] if row else None
    if family and not explicit:
        # Pin the adoption so later plans replay snapshots instead of re-selecting.
        manifest["design_template_set_id"] = family["id"]
        manifest["design_template_set_revision"] = family["revision"]
    pinned = manifest.get("design_template_set_id")
    if family:
        manifest["design_template_selection"] = {**(manifest.get("design_template_selection") or {}),
                                                 "schema_version": 2, "family": {"id": family["id"], "revision": family["revision"]},
                                                 "selection_reasons": reasons}
        prefill_style_contract(manifest, family["tokens"])
    used = {}
    for job in manifest["jobs"]:
        if job["id"] not in selected or (job.get("kind") != "main" and job.get("text_mode") == "none"):
            continue
        previous = job.get("design_resolution") or {}
        removed = neutralize_scaffold(job)
        request = {"set_id": pinned, "template_id": job.get("design_template_id"),
                   "slot": job.get("template_slot_role"), "compiler": 1}
        if previous.get("schema_version") == 2 and previous.get("request") == request and previous.get("binding"):
            snapshot = previous["binding"]
            family_snapshot = snapshot["family"]["snapshot"]
            template_snapshot = (snapshot.get("template") or {}).get("snapshot")
            tokens_snapshot = (snapshot.get("tokens_family") or {}).get("snapshot")
            match = {"match": previous.get("match"), "slot_role": previous.get("slot_role")}
        else:
            if family is None:
                if job.get("kind") == "main":
                    continue
                job["design_resolution"] = {"status": "needs_input", "source": "template_library", "schema_version": 2,
                                            "required": True, "matched": False,
                                            "reason": "No template family available; import a reference set or author a design_brief"}
                result["needs_input"].append(job["id"])
                continue
            match = slot_match(row, rows, job, used=used)
            if job.get("kind") == "main" and match["match"] not in {"observed", "adapted"}:
                continue  # main images keep their white-background rules without a template
            template_snapshot = match.get("template")
            if match["match"] == "cross_family":
                family_snapshot, tokens_snapshot = match["template_family"], family
            else:
                family_snapshot, tokens_snapshot = family, None
        if template_snapshot:
            used[template_snapshot["id"]] = used.get(template_snapshot["id"], 0) + 1
        shape = _shape(job)
        assets = {}
        plate_ok = bool(template_snapshot and match["match"] in {"observed", "adapted"} and job.get("kind") != "main")
        try:
            if template_snapshot and (template_snapshot.get("assets") or {}).get("plate_sha256") and plate_ok:
                assets["plate"] = {**_copy_asset(library, template_snapshot["assets"]["plate_sha256"], "plates", base), "use": "full"}
            if template_snapshot and (template_snapshot.get("assets") or {}).get("thumb_sha256"):
                assets["reference_thumbnail"] = _copy_asset(library, template_snapshot["assets"]["thumb_sha256"], "references", base)
        except (ValueError, OSError) as exc:
            if previous.get("assets"):
                assets = previous["assets"]  # adopted project copies remain authoritative
            else:
                job["design_resolution"] = {"status": "needs_input", "source": "template_library", "schema_version": 2,
                                            "required": True, "matched": False, "reason": str(exc)}
                result["needs_input"].append(job["id"])
                continue
        compiled = compile_v2(family_snapshot, template_snapshot, job, match=match["match"], shape=shape,
                              plate="plate" in assets, tokens_family=tokens_snapshot)
        brief = compiled["brief"]
        _resolve_surface_colors(brief, (tokens_snapshot or family_snapshot)["tokens"])
        for section, override in (job.get("design_overrides") or {}).items():
            brief.setdefault(section, {}).update(copy.deepcopy(override))
        ledger = _prefill_layout(job, brief, template_snapshot is not None and template_snapshot.get("observed_shape") == shape,
                                 palette=(tokens_snapshot or family_snapshot)["tokens"].get("palette", {}))
        if job.get("text_mode") == "local_overlay" and (job.get("layout") or {}).get("version") == 3:
            geometry = p.generation_geometry({**job, "design_brief": brief})
            notes = (template_snapshot or {}).get("generation", {}).get("negative_space") or ""
            brief["generation"]["canvas_composition"] = {
                "product_region_norm": geometry["product_region_norm"],
                "text_region_norm": next(iter(geometry["text_regions_norm"]), None),
                "text_regions_norm": geometry["text_regions_norm"],
                "notes": (notes + ". " if notes else "") + "Keep the product inside its container and leave the text regions clear."}
        resolution = {"status": "selected", "source": "template_library", "schema_version": 2,
                      "matched": match["match"] != "original", "match": match["match"], "slot_role": match.get("slot_role"),
                      "required": True, "request": request, "binding": compiled["binding"], "brief_hash": _digest(brief),
                      "selection_reasons": reasons, "assets": assets, "adjustments": copy.deepcopy(job.get("design_overrides", {})),
                      "layout_prefill": ledger, "scaffold_removed": removed or previous.get("scaffold_removed", [])}
        if job.get("design_brief") == brief and {k: v for k, v in previous.items() if k != "layout_prefill"} == \
                {k: v for k, v in resolution.items() if k != "layout_prefill"}:
            result["cached"].append(job["id"])
        else:
            job["design_brief"], job["design_resolution"] = brief, resolution
            result["changed"].append(job["id"])
    return result


def early_prefill(manifest, base):
    """Before validation: give empty style_contract roles the chosen family's tokens.

    Avoids the guaranteed DESIGN_COLOR_REQUIRED round trip on new projects. Only user
    v2 families carry executable tokens; explicit agent values are never replaced.
    """
    if (manifest.get("design_template_policy") or {}).get("version") != 2:
        return {}
    try:
        from lc_template_library import Library
        from lc_template_select import candidate_families, recommend
        base = Path(base).resolve()
        library = Library(manifest.get("design_template_library_dir") and str(base / manifest["design_template_library_dir"]))
        rows = {row[0]["id"]: row for row in candidate_families(manifest, base, library)}
        family_id = manifest.get("design_template_set_id")
        if family_id and family_id not in rows:
            return {}  # pinned family no longer in the library: adopted snapshots stay as they are
        if family_id not in rows:
            pick = recommend(manifest, base, top=1, library=library)["selected"]
            family_id = pick["id"] if pick else None
        row = rows.get(family_id)
        if row is None or row[3] != 2:
            return {}
        return prefill_style_contract(manifest, row[0]["tokens"])
    except (OSError, ValueError, RuntimeError):
        return {}
