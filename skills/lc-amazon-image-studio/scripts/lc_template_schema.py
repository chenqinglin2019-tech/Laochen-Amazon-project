"""Schema v2 for user template libraries built from the user's own reference sets.

A family is one reference set: a product profile (controlled taxonomy) plus
executable style tokens (hex palette, font faces). A template is one observed
image position with concrete generation parameters, a full text-group skeleton
(roles and geometry, never sample copy) and content-addressed assets (original,
neutralized style plate, thumbnail). Built-in v1 records are untouched; the
compiler is versioned so future compiler edits never recompile bound jobs.
Standard library only.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = ROOT / "assets/layouts/template_taxonomy.json"
COMPILER_VERSION = 1
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
HEX = re.compile(r"#[0-9A-Fa-f]{6}\Z")
CJK = re.compile(r"[㐀-鿿豈-﫿぀-ヿ가-힯]")
UNSAFE = re.compile(r"(?:data:|base64|https?://|file://|<\s*/?\s*[a-z][^>]*>)", re.I)
FORBIDDEN_KEYS = {"copy", "headline_text", "body_text", "sample_text", "brand", "claims", "product_facts",
                  "url", "path", "image", "images", "html", "base64", "evidence_refs", "panels"}
FAMILY_FIELDS = {"id", "revision", "schema", "name", "description", "origin", "product_profile", "tokens", "avoid",
                 "source_ids", "review"}
TEMPLATE_FIELDS = {"id", "revision", "schema", "family_id", "name", "slot_role", "observed_shape", "recipe", "layout",
                   "generation", "assets", "observation", "avoid", "source_ids", "review"}
SOURCE_FIELDS = {"id", "filename", "sha256", "set_id", "observation"}
GENERATION_KEYS = ("background", "props", "surface", "lighting", "color_grade", "camera", "depth_of_field",
                   "product_placement", "product_scale", "shadow", "negative_space", "mood")
GLOBAL_SAFEGUARDS = [
    "Follow the project's text_mode and approved copy; add no extra marketing lettering, icons, measurements, claims, badges or sales controls.",
    "Never borrow product identity, sample copy, logos, packaging, accessories, quantities or claims from any style reference.",
    "Do not invent hidden geometry, material identity, human scale or safe-use behavior; follow current product evidence and protection regions.",
]
PLATE_FIDELITY = ("Match the attached style plate as closely as the current product and evidence allow: background and "
                  "surfaces, props style, light direction and quality, colour grade, camera angle and depth of field, "
                  "composition and negative space. Its blurred or flattened areas are empty placeholders; never "
                  "reproduce any product, text, logo, badge or packaging from it.")


class SchemaError(ValueError):
    pass


@lru_cache(maxsize=1)
def taxonomy() -> dict:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def empty_document() -> dict:
    return {"schema_version": 2, "asset_policy": "content_addressed", "language": "en",
            "sources": [], "families": [], "templates": []}


def content_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def semantic_hash(record: dict) -> str:
    return content_hash({key: value for key, value in record.items()
                         if key not in {"id", "revision", "source_ids", "review", "origin", "name"}})


def _box(value) -> bool:
    return (isinstance(value, list) and len(value) == 4
            and all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in value)
            and value[2] > 0 and value[3] > 0 and value[0] + value[2] <= 1.000001 and value[1] + value[3] <= 1.000001)


def _overlap(first, second) -> bool:
    return (min(first[0] + first[2], second[0] + second[2]) - max(first[0], second[0]) > .005
            and min(first[1] + first[3], second[1] + second[3]) - max(first[1], second[1]) > .005)


def _text_errors(value, location, errors, *, allow_cjk=False):
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or CJK.search(key):
                errors.append(f"{location}: keys must be English strings")
                continue
            if key.casefold() in FORBIDDEN_KEYS:
                errors.append(f"{location}.{key}: sample copy, claims, paths and images are forbidden")
            _text_errors(child, f"{location}.{key}", errors, allow_cjk=allow_cjk)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _text_errors(child, f"{location}[{index}]", errors, allow_cjk=allow_cjk)
    elif isinstance(value, str):
        if CJK.search(value) and not allow_cjk:
            errors.append(f"{location}: template text must be English")
        if UNSAFE.search(value):
            errors.append(f"{location}: URLs, encoded data and HTML are forbidden")
    elif isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{location}: finite numbers required")
    elif value is not None and not isinstance(value, (int, float, bool)):
        errors.append(f"{location}: JSON values required")


def _enum_list(values, allowed, location, errors):
    if not isinstance(values, list) or any(v not in allowed for v in values):
        errors.append(f"{location} must be a list from {sorted(allowed)}")


def validate_profile(profile, location="product_profile", *, family=True) -> list:
    tax, errors = taxonomy(), []
    if not isinstance(profile, dict):
        return [f"{location} must be an object"]
    categories = profile.get("categories") if family else [profile.get("category")] + list(profile.get("secondary_categories", []))
    _enum_list([c for c in categories if c is not None], set(tax["categories"]), f"{location}.categories", errors)
    if family and not categories:
        errors.append(f"{location}.categories needs at least one category")
    if not family and profile.get("category") not in tax["categories"]:
        errors.append(f"{location}.category must be one of the taxonomy categories")
    attributes = profile.get("attributes", {})
    if not isinstance(attributes, dict):
        errors.append(f"{location}.attributes must be an object")
        return errors
    for name, value in attributes.items():
        allowed = set(tax["attributes"].get(name, []))
        if not allowed:
            errors.append(f"{location}.attributes.{name} is not a known attribute")
            continue
        values = value if isinstance(value, list) else [value]
        _enum_list(values, allowed, f"{location}.attributes.{name}", errors)
    return errors


def validate_document(document, *, check_references=True) -> list:
    tax = taxonomy()
    if not isinstance(document, dict):
        return ["Template library v2 must be an object"]
    errors = []
    if document.get("schema_version") != 2 or document.get("asset_policy") != "content_addressed" or document.get("language") != "en":
        errors.append("v2 root requires schema_version 2, asset_policy content_addressed, language en")
    for key in ("sources", "families", "templates"):
        if not isinstance(document.get(key), list):
            errors.append(f"{key} must be a list")
    if errors:
        return errors
    seen = set()
    for source in document["sources"]:
        location = f"sources[{source.get('id') if isinstance(source, dict) else '?'}]"
        if not isinstance(source, dict) or set(source) - SOURCE_FIELDS or not {"id", "filename", "sha256"} <= set(source):
            errors.append(f"{location}: id/filename/sha256 required (optional set_id/observation)")
            continue
        if not isinstance(source["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,80}", source["id"]):
            errors.append(f"{location}: invalid id")
        if not isinstance(source["sha256"], str) or not SHA.fullmatch(source["sha256"]):
            errors.append(f"{location}: sha256 must be 64 hex")
        if not isinstance(source["filename"], str) or "/" in source["filename"] or "\\" in source["filename"]:
            errors.append(f"{location}: filename must be a bare name")
        _text_errors(source.get("observation", ""), f"{location}.observation", errors)
    families = {}
    for family in document["families"]:
        location = f"families[{family.get('id') if isinstance(family, dict) else '?'}]"
        if not isinstance(family, dict) or set(family) - FAMILY_FIELDS or not {"id", "revision", "name", "product_profile", "tokens", "review"} <= set(family):
            errors.append(f"{location}: id/revision/name/product_profile/tokens/review required")
            continue
        if not isinstance(family["id"], str) or not ID.fullmatch(family["id"]) or type(family["revision"]) is not int or family["revision"] < 1:
            errors.append(f"{location}: kebab-case id and positive integer revision required")
        if (family.get("id"), family.get("revision")) in seen:
            errors.append(f"{location}: duplicate id/revision")
        seen.add((family.get("id"), family.get("revision")))
        errors.extend(validate_profile(family["product_profile"], f"{location}.product_profile"))
        tokens = family["tokens"]
        palette = tokens.get("palette", {}) if isinstance(tokens, dict) else {}
        if not isinstance(palette, dict) or not palette or any(role not in tax["palette_roles"] or not isinstance(v, str) or not HEX.fullmatch(v)
                                                                 for role, v in palette.items()):
            errors.append(f"{location}.tokens.palette must map palette roles to #RRGGBB")
        fonts = tokens.get("fonts", {}) if isinstance(tokens, dict) else {}
        for role, face in (fonts.items() if isinstance(fonts, dict) else []):
            if role not in tax["font_roles"] or not isinstance(face, dict) or face.get("face") not in tax["font_faces"]:
                errors.append(f"{location}.tokens.fonts.{role} needs a bundled face {tax['font_faces']}")
        if not isinstance(family["review"], dict) or family["review"].get("visual_reviewed") is not True:
            errors.append(f"{location}.review.visual_reviewed must be true after an actual visual review")
        _text_errors({k: v for k, v in family.items() if k not in {"review"}}, location, errors)
        families.setdefault(family["id"], []).append(family)
    for template in document["templates"]:
        location = f"templates[{template.get('id') if isinstance(template, dict) else '?'}]"
        if not isinstance(template, dict) or set(template) - TEMPLATE_FIELDS or not {"id", "revision", "family_id", "slot_role", "observed_shape", "recipe", "layout", "generation", "review"} <= set(template):
            errors.append(f"{location}: id/revision/family_id/slot_role/observed_shape/recipe/layout/generation/review required")
            continue
        if not isinstance(template["id"], str) or not ID.fullmatch(template["id"]) or type(template["revision"]) is not int or template["revision"] < 1:
            errors.append(f"{location}: kebab-case id and positive integer revision required")
        if (template.get("id"), template.get("revision")) in seen:
            errors.append(f"{location}: duplicate id/revision")
        seen.add((template.get("id"), template.get("revision")))
        if template["slot_role"] not in tax["slot_roles"]:
            errors.append(f"{location}.slot_role must be one of {tax['slot_roles']}")
        if template["observed_shape"] not in {"square", "portrait", "wide"}:
            errors.append(f"{location}.observed_shape must be square/portrait/wide")
        if template["recipe"] not in tax["recipes"]:
            errors.append(f"{location}.recipe must be one of {tax['recipes']}")
        if (template["slot_role"] == "main") != (template["recipe"] == "none"):
            errors.append(f"{location}: main images use recipe none (no marketing text); other slots need a V3 recipe")
        layout = template["layout"]
        if not isinstance(layout, dict):
            errors.append(f"{location}.layout must be an object")
            layout = {}
        product = layout.get("product_region_norm")
        if product is not None and not _box(product):
            errors.append(f"{location}.layout.product_region_norm must be a normalized box")
        groups = layout.get("text_groups", [])
        if not isinstance(groups, list) or len(groups) > 6:
            errors.append(f"{location}.layout.text_groups must hold at most six groups")
            groups = []
        if template["slot_role"] == "main" and groups:
            errors.append(f"{location}: main images carry no text groups")
        ids = set()
        for index, group in enumerate(groups):
            where = f"{location}.layout.text_groups[{index}]"
            if not isinstance(group, dict) or group.get("role") not in tax["text_roles"] or not _box(group.get("box")):
                errors.append(f"{where}: role from {tax['text_roles']} and a normalized box are required")
                continue
            if group.get("id") in ids or not isinstance(group.get("id"), str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", group["id"]):
                errors.append(f"{where}: unique lowercase id required")
            ids.add(group.get("id"))
            box = group["box"]
            if box[0] < .02 or box[1] < .02 or box[0] + box[2] > .98 or box[1] + box[3] > .98:
                errors.append(f"{where}: keep text inside the safe margin (2%)")
            if product is not None and _box(product) and _overlap(box, product):
                errors.append(f"{where}: text box overlaps the product region")
            if group.get("color_role") is not None and group["color_role"] not in tax["palette_roles"]:
                errors.append(f"{where}.color_role must be a palette role")
            if group.get("font_role") is not None and group["font_role"] not in tax["font_roles"]:
                errors.append(f"{where}.font_role must be a font role")
            size = group.get("size")
            if size is not None and (type(size) not in {int, float} or not 12 <= size <= 64):
                errors.append(f"{where}.size is the 360px-preview size token (12..64)")
            errors.extend(_group_style_errors(group, where, tax))
        generation = template["generation"]
        if not isinstance(generation, dict) or set(generation) - set(GENERATION_KEYS) or not generation:
            errors.append(f"{location}.generation accepts {GENERATION_KEYS}")
        assets = template.get("assets", {})
        if not isinstance(assets, dict) or any(not isinstance(v, str) or not SHA.fullmatch(v) for v in assets.values()) \
                or set(assets) - {"reference_sha256", "plate_sha256", "thumb_sha256"}:
            errors.append(f"{location}.assets accepts reference/plate/thumb sha256 only")
        if not isinstance(template["review"], dict) or template["review"].get("visual_reviewed") is not True:
            errors.append(f"{location}.review.visual_reviewed must be true after an actual visual review")
        _text_errors({k: v for k, v in template.items() if k not in {"review", "assets"}}, location, errors)
        if check_references and template.get("family_id") not in families:
            errors.append(f"{location}: unknown family {template.get('family_id')}")
    return errors


def _group_style_errors(group, where, tax):
    """Optional observed typography/graphics (rendered by the style_v1 renderer)."""
    errors = []
    roles = tax["palette_roles"]

    def number(key, value, low, high):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            errors.append(f"{where}.{key} must be {low}..{high}")
    if group.get("case", "none") not in {"none", "uppercase"}:
        errors.append(f"{where}.case must be none/uppercase")
    if "letter_spacing_em" in group:
        number("letter_spacing_em", group["letter_spacing_em"], -.05, .3)
    if "line_height" in group:
        number("line_height", group["line_height"], .9, 2)
    surface = group.get("surface")
    if surface is not None:
        if not isinstance(surface, dict) or surface.get("kind") not in {"transparent", "solid", "gradient"} \
                or set(surface) - {"kind", "color_role", "opacity", "radius_em", "border_color_role", "border_width_px", "shadow"}:
            errors.append(f"{where}.surface needs kind transparent/solid/gradient (+color_role, opacity, radius_em, border_color_role, border_width_px, shadow)")
        else:
            for key in ("color_role", "border_color_role"):
                if key in surface and surface[key] not in roles:
                    errors.append(f"{where}.surface.{key} must be a palette role")
            if "opacity" in surface:
                number("surface.opacity", surface["opacity"], .2, 1)
            if "radius_em" in surface:
                number("surface.radius_em", surface["radius_em"], 0, 3)
            if "border_width_px" in surface:
                number("surface.border_width_px", surface["border_width_px"], 0, 4)
            if not isinstance(surface.get("shadow", False), bool):
                errors.append(f"{where}.surface.shadow must be true/false")
    pill = group.get("pill")
    if pill is not None and (not isinstance(pill, dict) or pill.get("color_role") not in roles
                             or pill.get("text_color_role", "accent_text") not in roles or set(pill) - {"color_role", "text_color_role"}):
        errors.append(f"{where}.pill needs color_role (+text_color_role) from the palette")
    divider = group.get("divider")
    if divider is not None:
        if not isinstance(divider, dict) or divider.get("color_role") not in roles or set(divider) - {"color_role", "width_px", "length_em"}:
            errors.append(f"{where}.divider needs color_role (+width_px 1..6, length_em 0..20)")
        else:
            number("divider.width_px", divider.get("width_px", 2), 1, 6)
            number("divider.length_em", divider.get("length_em", 0), 0, 20)
    return errors


def latest(records: list) -> list:
    newest = {}
    for record in records:
        if record["id"] not in newest or record["revision"] > newest[record["id"]]["revision"]:
            newest[record["id"]] = record
    return sorted(newest.values(), key=lambda item: item["id"])


def binding_entry(record) -> dict:
    return {"id": record["id"], "revision": record["revision"], "content_hash": content_hash(record),
            "snapshot": copy.deepcopy(record)}


def binding_issue(binding) -> str | None:
    if not isinstance(binding, dict) or binding.get("schema_version") != 2 or binding.get("compiler") != COMPILER_VERSION:
        return "design_template_v2_binding_invalid"
    for key in ("family", "template", "tokens_family"):
        entry = binding.get(key)
        if entry is None and key != "family":
            continue
        if (not isinstance(entry, dict) or not isinstance(entry.get("snapshot"), dict)
                or content_hash(entry["snapshot"]) != entry.get("content_hash")
                or entry["snapshot"].get("id") != entry.get("id") or entry["snapshot"].get("revision") != entry.get("revision")):
            return f"design_template_v2_{key}_snapshot_changed"
    return None


def face_family(face: str) -> str:
    fallback = taxonomy()["font_face_fallback"].get(face, face)
    return "serif" if fallback == "noto_serif" or face in {"noto_serif", "libre_baskerville"} else "sans"


def v3_weight(face: str, weight) -> int:
    family = face_family(face)
    weight = int(weight) if isinstance(weight, (int, float)) else 600
    choices = (400, 600) if family == "serif" else (400, 600, 700)
    return min(choices, key=lambda value: abs(value - weight))


def style_contract_roles(tokens) -> dict:
    """Family tokens as style_contract color/font roles (explicit agent values always win)."""
    palette, fonts = tokens.get("palette", {}), tokens.get("fonts", {})
    colors = {}
    for role, source in (("headline", "ink"), ("body", "muted"), ("label", "accent"), ("accent", "accent"), ("graphic", "accent")):
        value = palette.get(source) or palette.get("ink")
        if value:
            colors[role] = value.upper()
    faces = {}
    for role, source in (("headline", "display"), ("body", "text"), ("label", "label")):
        face = fonts.get(source)
        if isinstance(face, dict) and face.get("face"):
            faces[role] = {"family": face_family(face["face"]), "weight": v3_weight(face["face"], face.get("weight", 600))}
    return {"color_roles": colors, "font_roles": faces}


def _sentence(value):
    return ", ".join(value) if isinstance(value, list) else str(value)


def compile_v2(family, template, job, *, match, shape, plate=False, tokens_family=None):
    """Compile an adopted family/template snapshot into the existing design_brief shape."""
    style_source = tokens_family or family
    tokens = style_source["tokens"]
    generation = {}
    source_generation = (template or {}).get("generation", {})
    for key in GENERATION_KEYS:
        if source_generation.get(key):
            generation[key] = _sentence(source_generation[key])
    is_main = job.get("kind") == "main"
    if is_main:
        generation = {key: value for key, value in generation.items() if key in {"camera", "product_placement", "product_scale", "shadow"}}
    else:
        palette = tokens.get("palette", {})
        names = tokens.get("palette_names", {})
        generation["family_visual_style"] = {
            "palette": "; ".join(f"{role} {value}" + (f" ({names[role]})" if names.get(role) else "") for role, value in palette.items()),
            "photography": "; ".join(_sentence(v) for v in (tokens.get("photography") or {}).values())}
        if plate:
            generation["reference_fidelity"] = PLATE_FIDELITY
    avoid = list(dict.fromkeys(GLOBAL_SAFEGUARDS + list(family.get("avoid", [])) + list((template or {}).get("avoid", []))))
    generation["product_safeguards"] = avoid
    layout = {}
    if template and not is_main and template.get("recipe") != "none":
        groups = copy.deepcopy(template["layout"].get("text_groups", []))
        observed = template.get("observed_shape") == shape
        layout["recipe"] = template["recipe"]
        palette = tokens.get("palette", {})
        fonts = tokens.get("fonts", {})
        headline = next((group for group in groups if group["role"] == "headline"), groups[0] if groups else None)
        if headline:
            face = (fonts.get(headline.get("font_role", "display")) or {}).get("face", "noto_sans")
            layout["headline_family"] = face_family(face)
            layout["headline_weight"] = v3_weight(face, (fonts.get(headline.get("font_role", "display")) or {}).get("weight", 600))
            if headline.get("align") in {"left", "center", "right"}:
                layout["align"] = headline["align"]
            if headline.get("color_role") and palette.get(headline["color_role"]):
                layout["text_color"] = palette[headline["color_role"]].upper()
        if observed:
            if template["layout"].get("product_region_norm"):
                layout["product_region_norm"] = copy.deepcopy(template["layout"]["product_region_norm"])
            if headline:
                layout["text_group_box"] = copy.deepcopy(headline["box"])
        for group in groups:
            if not observed:
                group.pop("box", None)  # adapted canvas: recipe geometry decides placement
            if group.get("color_role") and palette.get(group["color_role"]):
                group["text_color"] = palette[group["color_role"]].upper()
            face = (fonts.get(group.get("font_role", "text")) or {})
            if face.get("face"):
                group["face"] = face["face"]
                for key in ("case", "letter_spacing_em"):
                    if key in face and key not in group:
                        group[key] = face[key]
        layout["skeleton"] = groups
        if template["layout"].get("graphics"):
            layout["graphics"] = copy.deepcopy(template["layout"]["graphics"])
    binding = {"schema_version": 2, "compiler": COMPILER_VERSION, "family": binding_entry(family),
               "template": binding_entry(template) if template else None,
               "tokens_family": binding_entry(tokens_family) if tokens_family else None}
    return {"brief": {"version": 2, "reference_ids": [], "generation": generation, "layout": layout},
            "binding": binding, "match": match}
