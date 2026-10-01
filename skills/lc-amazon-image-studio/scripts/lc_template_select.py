#!/usr/bin/env python3
"""Pick the template family and per-image templates from the product's traits.

Deterministic and explainable: every score comes with its breakdown. User v2
families come from the per-user library; v1 built-ins (when enabled) are lifted
onto the same taxonomy so a fresh install still auto-selects. Families imported
for the current request are preferred (manifest design_template_policy.prefer_family_ids).
Never needs_input: a missing slot falls back to a near slot, another family
restyled with the chosen tokens, or an original brief built from the tokens.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

WEIGHTS = {"category_exact": 40, "category_group": 20, "material": 8, "style_mood": 8, "color_tone": 6,
           "use_environment": 6, "audience": 4, "size_class": 4, "price_tier": 4}
PREFERRED_BONUS = 100


def _tax():
    from lc_template_schema import taxonomy
    return taxonomy()


def category_from_text(text: str) -> list:
    """Categories implied by free text via taxonomy aliases (longest alias wins first)."""
    text = f" {str(text or '').casefold()} "
    counts, longest = {}, {}
    for slug, spec in _tax()["categories"].items():
        for alias in spec["aliases"] + [slug.replace("_", " ")]:
            if re.search(r"(?<![a-z])" + re.escape(alias.casefold()) + r"s?(?![a-z])", text):
                counts[slug] = counts.get(slug, 0) + 1
                longest[slug] = max(longest.get(slug, 0), len(alias))
    # More distinct alias hits first (plush + toy beats toddler), then the longest alias.
    return sorted(counts, key=lambda slug: (-counts[slug], -longest[slug], slug))


def resolve_profile(manifest) -> tuple:
    """(profile, source): explicit manifest.product_profile, else inferred from category/product text."""
    profile = manifest.get("product_profile")
    if isinstance(profile, dict) and profile.get("category") in _tax()["categories"]:
        return copy.deepcopy(profile), "manifest"
    truth = manifest.get("product_truth") or {}
    text = " ".join(str(v) for v in (manifest.get("category"), truth.get("category"), truth.get("product")) if v)
    categories = category_from_text(text)
    return ({"category": categories[0] if categories else None, "secondary_categories": categories[1:3],
             "attributes": {}}, "inferred" if categories else "unknown")


def _v1_family_profile(family) -> dict:
    categories = []
    for text in family.get("categories", []) + family.get("keywords", []):
        for slug in category_from_text(text):
            if slug not in categories:
                categories.append(slug)
    return {"categories": categories, "attributes": {}}


def candidate_families(manifest, base=None, library=None):
    """[(family, templates, source, schema)] from the user v2 library and enabled v1 built-ins."""
    from lc_template_library import Library
    import lc_design_templates as v1
    from lc_template_schema import latest
    library = library or Library(_library_dir(manifest, base))
    rows = []
    document = library.load_v2()
    templates = latest(document["templates"])
    for family in latest(document["families"]):
        rows.append((family, [t for t in templates if t["family_id"] == family["id"]], "user", 2))
    try:
        builtin = v1.load_library(user_path=library.root / "__no_v1_user__.json")
    except v1.TemplateError:
        builtin = {"families": [], "templates": []}
    v1_templates = v1._latest(builtin.get("templates", []))
    for family in v1._latest(builtin.get("families", [])):
        rows.append((family, [t for t in v1_templates if t.get("family_id") == family["id"]], "builtin", 1))
    return rows


def _library_dir(manifest, base):
    value = manifest.get("design_template_library_dir")
    if value and base is not None and not Path(value).is_absolute():
        return str(Path(base) / value)
    return value


def score_family(profile, family, schema, *, preferred=()) -> dict:
    tax = _tax()
    family_profile = family["product_profile"] if schema == 2 else _v1_family_profile(family)
    breakdown, score = {}, 0
    wanted = [profile.get("category")] + list(profile.get("secondary_categories", []))
    wanted = [c for c in wanted if c]
    have = family_profile.get("categories", [])
    if wanted and wanted[0] in have:
        breakdown["category"] = WEIGHTS["category_exact"]
    elif wanted and any(c in have for c in wanted[1:]):
        breakdown["category"] = WEIGHTS["category_group"]
    elif wanted and any(tax["categories"].get(c, {}).get("group") == tax["categories"].get(wanted[0], {}).get("group") for c in have):
        breakdown["category"] = WEIGHTS["category_group"]
    attributes, family_attributes = profile.get("attributes", {}), family_profile.get("attributes", {})
    ordered = tax.get("ordered_attributes", {})
    for name in ("material", "style_mood", "color_tone", "use_environment", "audience", "size_class", "price_tier"):
        mine = attributes.get(name)
        theirs = family_attributes.get(name)
        if not mine or not theirs:
            continue
        mine = mine if isinstance(mine, list) else [mine]
        theirs = theirs if isinstance(theirs, list) else [theirs]
        if set(mine) & set(theirs):
            breakdown[name] = WEIGHTS[name]
        elif name in ordered and any(abs(ordered[name].index(a) - ordered[name].index(b)) == 1
                                     for a in mine for b in theirs if a in ordered[name] and b in ordered[name]):
            breakdown[name] = WEIGHTS[name] // 2
    score = sum(breakdown.values())
    attribute_max = sum(WEIGHTS[key] for key in ("material", "style_mood", "color_tone", "use_environment", "audience", "size_class", "price_tier"))
    attribute_score = score - breakdown.get("category", 0)
    mismatch = "category" not in breakdown
    eligible = not mismatch or family["id"] in preferred or (attribute_max and attribute_score >= attribute_max / 2)
    if family["id"] in preferred:
        breakdown["preferred"] = PREFERRED_BONUS
        score += PREFERRED_BONUS
    return {"score": score, "breakdown": breakdown, "category_mismatch": mismatch, "eligible": bool(eligible)}


def slot_role(job) -> str | None:
    tax = _tax()
    explicit = job.get("template_slot_role")
    if explicit in tax["slot_roles"]:
        return explicit
    if job.get("kind") == "main":
        return "main"
    match = re.match(r"^\d{2}_(.+)$", str(job.get("id", "")))
    if match and match.group(1) in tax["slot_roles"]:
        return match.group(1)
    if job.get("kind") == "a_plus":
        module = str(job.get("a_plus_module", "")).casefold()
        for role, words in tax["a_plus_module_keywords"].items():
            if any(word in module for word in words):
                return role
        return "a_plus_lifestyle"
    text = str(job.get("selling_job", "")).casefold()
    for role, words in (("size_or_components", ("size", "dimension", "component", "included", "kit")),
                        ("compatibility_or_installation", ("install", "compatib", "fit", "mount", "connect")),
                        ("material_or_detail", ("material", "detail", "texture", "craft")),
                        ("storage_or_package", ("storage", "package", "carry", "travel")),
                        ("problem_solution", ("problem", "solution", "before", "concern")),
                        ("primary_use_case", ("use", "scene", "lifestyle"))):
        if any(word in text for word in words):
            return role
    return "primary_use_case"


def _shape(job) -> str:
    width, height = job.get("canvas", [2000, 2000])
    ratio = width / height if height else 1
    return "square" if 0.95 <= ratio <= 1.05 else "wide" if ratio > 1 else "portrait"


def slot_match(family_row, all_rows, job, *, used=None) -> dict:
    """Best template for this job: observed/adapted in family → near slot → other family → original."""
    tax = _tax()
    family, templates, source, schema = family_row
    role = slot_role(job)
    shape = _shape(job)
    used = used or {}
    if schema != 2:
        return {"match": "builtin_v1", "slot_role": role, "template": None, "family": family["id"], "source": source}

    def pick(candidates):
        if not candidates:
            return None
        return min(candidates, key=lambda t: (t.get("observed_shape") != shape, used.get(t["id"], 0), t["id"]))
    same = [t for t in templates if t["slot_role"] == role]
    chosen = pick(same)
    if chosen:
        return {"match": "observed" if chosen.get("observed_shape") == shape else "adapted", "slot_role": role,
                "template": chosen, "family": family["id"], "source": source}
    for near in tax["slot_similarity"].get(role, []):
        chosen = pick([t for t in templates if t["slot_role"] == near])
        if chosen:
            return {"match": "adapted", "slot_role": role, "template": chosen, "family": family["id"], "source": source,
                    "note": f"nearest slot {near}"}
    if role != "main":
        for other in all_rows:
            if other[3] != 2 or other[0]["id"] == family["id"]:
                continue
            chosen = pick([t for t in other[1] if t["slot_role"] == role])
            if chosen:
                return {"match": "cross_family", "slot_role": role, "template": chosen, "family": family["id"],
                        "template_family": other[0], "source": source,
                        "note": f"{other[0]['id']} layout restyled with {family['id']} tokens"}
    return {"match": "original", "slot_role": role, "template": None, "family": family["id"], "source": source}


def recommend(manifest, base=None, *, top=3, library=None) -> dict:
    profile, profile_source = resolve_profile(manifest)
    policy = manifest.get("design_template_policy") or {}
    preferred = set(policy.get("prefer_family_ids", []))
    rows = candidate_families(manifest, base, library)
    ranked = []
    for row in rows:
        family, templates, source, schema = row
        result = score_family(profile, family, schema, preferred=preferred)
        if not result["eligible"]:
            continue
        coverage = []
        if schema == 2:
            used = {}
            for job in manifest.get("jobs", []):
                match = slot_match(row, rows, job, used=used)
                template = match.get("template")
                if template:
                    used[template["id"]] = used.get(template["id"], 0) + 1
                coverage.append({"job": job["id"], "slot_role": match["slot_role"], "match": match["match"],
                                 "template": template["id"] if template else None,
                                 "text_roles": [g["role"] for g in (template or {}).get("layout", {}).get("text_groups", [])]})
            result["score"] += sum(2 if item["match"] == "observed" else 1 if item["match"] in {"adapted", "cross_family"} else 0
                                   for item in coverage)
        ranked.append({"id": family["id"], "revision": family["revision"], "source": source, "schema": schema,
                       "name": family.get("name"), **result, "coverage": coverage})
    ranked.sort(key=lambda item: (-item["score"], item["source"] != "user", item["id"]))
    selected = ranked[0] if ranked else None
    return {"product_profile": profile, "profile_source": profile_source, "families": ranked[:top],
            "selected": {"id": selected["id"], "revision": selected["revision"], "source": selected["source"]} if selected else None,
            "note": ("Fill manifest.product_profile (taxonomy) for better matches." if profile_source != "manifest" else "")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir")
    subs = parser.add_subparsers(dest="command", required=True)
    rec = subs.add_parser("recommend")
    rec.add_argument("--manifest", type=Path, required=True)
    rec.add_argument("--top", type=int, default=3)
    rec.add_argument("--apply", action="store_true", help="Write the best family into design_template_set_id")
    subs.add_parser("taxonomy")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        if args.command == "taxonomy":
            tax = _tax()
            result = {"categories": sorted(tax["categories"]), "attributes": tax["attributes"], "slot_roles": tax["slot_roles"]}
        else:
            from lc_template_library import Library
            path = args.manifest.expanduser().resolve()
            manifest = json.loads(path.read_text(encoding="utf-8"))
            result = recommend(manifest, path.parent, top=args.top,
                               library=Library(args.library_dir) if args.library_dir else None)
            if args.apply and result["selected"]:
                from lc_workflow import manifest_lock
                import lc_image_pipeline as p
                with manifest_lock(path):
                    current = p.read_json(path)
                    current["design_template_set_id"] = result["selected"]["id"]
                    current["design_template_set_revision"] = result["selected"]["revision"]
                    p.write_json(path, current)
                result["applied"] = True
        print(json.dumps({"ok": True, "command": args.command, **result}, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "command": args.command, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
