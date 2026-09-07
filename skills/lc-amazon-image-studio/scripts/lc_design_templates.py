#!/usr/bin/env python3
"""Validated, versioned text-only design templates; no image or model I/O.

Visual interpretation and semantic review belong to the agent. This module
validates reviewed records, offers conservative candidates, imports immutable
versions, and compiles portable snapshots into the existing design brief.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import string
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

from lc_style_reference import CATEGORY_KEYWORDS, _selection_lock, _write_json

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILTIN = ROOT / "assets/layouts/design_templates.json"
DEFAULT_USER = ROOT / "assets/layouts/design_templates.user.json"
RECIPES = {"photo_overlay", "header_footer", "photo_sidebar", "scene_grid", "detail_callouts", "steps"}
KINDS = {"secondary", "a_plus"}
SHAPES = {"square", "portrait", "wide"}
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SOURCE_ID = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*\Z")
CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
UNSAFE_TEXT = re.compile(r"(?:data:|base64|https?://|file://|<\s*/?\s*[a-z][^>]*>|(?:^|\s)(?:/[A-Za-z]|[A-Za-z]:[\\/]|~/))", re.I)
ASSET_FILE = re.compile(r"(?:^|\s|[\"'])(?:[^\s\"']+[\\/])?[^\s\"']+\.(?:png|jpe?g|webp|gif|tiff?|psd|svg)(?:$|\s|[\"'])", re.I)
ENCODED_ASSET = re.compile(r"(?:^|\s)[A-Za-z0-9+/]{256,}={0,2}(?:$|\s)")
FORBIDDEN_KEYS = {"copy", "headline", "body", "label", "image", "images", "image_url", "image_path", "asset", "asset_path", "external_path", "path", "url", "base64", "blob", "html", "product_facts", "brand", "claims", "evidence_refs", "panels", "text_groups"}
COMMON_FIELDS = {"id", "revision", "name", "description", "source_ids", "review"}
FAMILY_FIELDS = COMMON_FIELDS | {"categories", "keywords", "style", "avoid"}
TEMPLATE_FIELDS = COMMON_FIELDS | {"family_id", "intents", "kinds", "canvas_shapes", "recipe", "generation", "layout", "prompt_template", "scene_default", "fixed_style", "adaptation_rules", "avoid"}
SOURCE_FIELDS = {"id", "filename", "sha256", "region_norm", "observation"}


class TemplateError(ValueError):
    """Invalid, conflicting, or unusable reviewed template data."""


TemplateLibraryError = TemplateError


def empty_library() -> dict:
    return {"schema_version": 1, "asset_policy": "text_only", "language": "en", "sources": [], "families": [], "templates": []}


def content_hash(value: Any) -> str:
    try:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        encoded = payload.encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise TemplateError(f"Non-JSON template content: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def _semantic_hash(record: dict) -> str:
    value = {k: v for k, v in record.items() if k not in {"id", "revision", "source_ids", "review"}}
    for key in ("categories", "keywords", "intents", "kinds", "canvas_shapes", "avoid"):
        if key in value:
            value[key] = sorted(set(value[key]))
    return content_hash(value)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TemplateError(f"Cannot read template JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TemplateError("Template JSON root must be an object")
    return value


def _strings(value: Any, *, nonempty: bool = True) -> bool:
    return isinstance(value, list) and (bool(value) or not nonempty) and all(isinstance(v, str) and v.strip() for v in value)


def _box(value: Any) -> bool:
    return (isinstance(value, list) and len(value) == 4 and
            all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in value) and
            value[2] > 0 and value[3] > 0 and value[0] + value[2] <= 1.000001 and value[1] + value[3] <= 1.000001)


def _boxes_overlap(first: list, second: list) -> bool:
    return (min(first[0] + first[2], second[0] + second[2]) - max(first[0], second[0]) > .000001 and
            min(first[1] + first[3], second[1] + second[3]) - max(first[1], second[1]) > .000001)


def _canvas_errors(layout: dict, canvas_shapes: Any, prefix: str, errors: list[str]) -> None:
    if "composition_note" in layout and (not isinstance(layout["composition_note"], str) or not layout["composition_note"].strip()):
        errors.append(f"{prefix}: English composition_note required")
    if "product_region_norm" in layout:
        if not _box(layout["product_region_norm"]):
            errors.append(f"{prefix}: invalid product_region_norm")
        elif _box(layout.get("text_group_box")) and _boxes_overlap(layout["product_region_norm"], layout["text_group_box"]):
            errors.append(f"{prefix}: product and text regions must not overlap")
    if "canvas_variants" not in layout:
        return
    variants = layout["canvas_variants"]
    if not isinstance(variants, dict) or not variants or set(variants) - SHAPES:
        errors.append(f"{prefix}: canvas_variants accepts square/portrait/wide only")
        return
    if _strings(canvas_shapes) and set(variants) != set(canvas_shapes):
        errors.append(f"{prefix}: canvas_variants must cover exactly the supported canvas_shapes")
    for shape, variant in variants.items():
        location = f"{prefix}.canvas_variants.{shape}"
        if not isinstance(variant, dict) or set(variant) != {"text_group_box", "product_region_norm", "composition_note"}:
            errors.append(f"{location}: text_group_box/product_region_norm/composition_note required")
            continue
        valid_boxes = True
        for key in ("text_group_box", "product_region_norm"):
            if not _box(variant[key]):
                errors.append(f"{location}: invalid {key}")
                valid_boxes = False
        if valid_boxes and _boxes_overlap(variant["text_group_box"], variant["product_region_norm"]):
            errors.append(f"{location}: product and text regions must not overlap")
        if not isinstance(variant["composition_note"], str) or not variant["composition_note"].strip():
            errors.append(f"{location}: English composition_note required")


def _text_errors(value: Any, location: str, errors: list[str]) -> None:
    """Reject executable/asset payloads; this cannot certify semantic truth."""
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                errors.append(f"{location}: object keys must be strings")
                continue
            if key.casefold() in FORBIDDEN_KEYS:
                errors.append(f"{location}.{key}: assets or product copy are forbidden")
            if CJK.search(key):
                errors.append(f"{location}.{key}: template keys must be English")
            _text_errors(child, f"{location}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _text_errors(child, f"{location}[{index}]", errors)
    elif isinstance(value, str):
        if CJK.search(value):
            errors.append(f"{location}: template text must be English")
        if UNSAFE_TEXT.search(value) or ASSET_FILE.search(value) or ENCODED_ASSET.search(value):
            errors.append(f"{location}: image paths, URLs, encoded assets, and HTML are forbidden")
    elif isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{location}: finite JSON numbers required")
    elif value is not None and not isinstance(value, (int, float, bool)):
        errors.append(f"{location}: JSON values required")


def _prompt_errors(prompt: Any, location: str, errors: list[str]) -> None:
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append(f"{location}: prompt_template required")
        return
    fields = []
    try:
        for _, field, spec, conversion in string.Formatter().parse(prompt):
            if field is not None:
                fields.append(field)
                if field not in {"product", "scene", "selling_job"} or spec or conversion:
                    errors.append(f"{location}: only plain product/scene/selling_job placeholders are allowed")
    except ValueError:
        errors.append(f"{location}: malformed prompt placeholder")
    if "product" not in fields:
        errors.append(f"{location}: prompt must use the product placeholder")


def validate_library(document: Any, *, check_references: bool = True) -> list[str]:
    """Validate without reading historical images. Partial imports skip refs."""
    if not isinstance(document, dict):
        return ["Template library must be an object"]
    try:
        content_hash(document)
    except TemplateError as exc:
        return [str(exc)]
    errors: list[str] = []
    if set(document) != set(empty_library()):
        errors.append("Template library accepts schema_version/asset_policy/language/sources/families/templates only")
    if type(document.get("schema_version")) is not int or document.get("schema_version") != 1:
        errors.append("Template schema_version must be 1")
    if document.get("asset_policy") != "text_only" or document.get("language") != "en":
        errors.append("Template library requires text_only assets and English text")
    collections = {}
    for key in ("sources", "families", "templates"):
        records = document.get(key)
        if not isinstance(records, list):
            errors.append(f"{key} must be a list")
            records = []
        collections[key] = records
    seen_sources: set[str] = set()
    for index, source in enumerate(collections["sources"]):
        prefix = f"sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{prefix}: source must be an object")
            continue
        if set(source) - SOURCE_FIELDS or SOURCE_FIELDS - {"region_norm"} - set(source):
            errors.append(f"{prefix}: invalid source fields")
        identifier = source.get("id")
        if not isinstance(identifier, str) or not SOURCE_ID.fullmatch(identifier):
            errors.append(f"{prefix}: source ID must use lowercase letters, digits, hyphens, or underscores")
        elif identifier in seen_sources:
            errors.append(f"{prefix}: duplicate source ID {identifier}")
        else:
            seen_sources.add(identifier)
        filename = source.get("filename")
        if (not isinstance(filename, str) or not filename.strip() or len(filename.encode("utf-8")) > 255 or filename in {".", ".."} or
                "/" in filename or "\\" in filename or ":" in filename or PureWindowsPath(filename).drive or "\0" in filename):
            errors.append(f"{prefix}: filename must be a basename, never a path")
        digest = source.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"{prefix}: invalid SHA256")
        if "region_norm" in source and not _box(source["region_norm"]):
            errors.append(f"{prefix}: invalid source region")
        observation = source.get("observation")
        if not isinstance(observation, str) or not observation.strip():
            errors.append(f"{prefix}: English visual observation required")
        else:
            _text_errors(observation, f"{prefix}.observation", errors)
    family_ids: set[str] = set()
    for collection, fields in (("families", FAMILY_FIELDS), ("templates", TEMPLATE_FIELDS)):
        seen: set[tuple[str, int]] = set()
        for index, record in enumerate(collections[collection]):
            prefix = f"{collection}[{index}]"
            if not isinstance(record, dict):
                errors.append(f"{prefix}: record must be an object")
                continue
            if set(record) != fields:
                errors.append(f"{prefix}: missing or unsupported record fields")
            identifier, revision = record.get("id"), record.get("revision")
            valid_id = isinstance(identifier, str) and bool(ID.fullmatch(identifier))
            valid_revision = type(revision) is int and revision > 0
            if not valid_id:
                errors.append(f"{prefix}: ID must be kebab-case")
            if not valid_revision:
                errors.append(f"{prefix}: revision must be a positive integer")
            if valid_id and valid_revision:
                key = (identifier, revision)
                if key in seen:
                    errors.append(f"{prefix}: duplicate ID/revision {identifier}@{revision}")
                seen.add(key)
                if collection == "families":
                    family_ids.add(identifier)
            for field in ("name", "description"):
                if not isinstance(record.get(field), str) or not record[field].strip():
                    errors.append(f"{prefix}: {field} required")
            for field in ("source_ids", "avoid"):
                if not _strings(record.get(field)):
                    errors.append(f"{prefix}: nonempty {field} required")
            refs = record.get("source_ids")
            if check_references and _strings(refs) and any(ref not in seen_sources for ref in refs):
                errors.append(f"{prefix}: unknown source ID")
            review = record.get("review")
            if (not isinstance(review, dict) or set(review) != {"visual_reviewed", "notes"} or
                    review.get("visual_reviewed") is not True or not isinstance(review.get("notes"), str) or not review["notes"].strip()):
                errors.append(f"{prefix}: completed visual review and notes required")
            if collection == "families":
                for field in ("categories", "keywords"):
                    if not _strings(record.get(field)):
                        errors.append(f"{prefix}: nonempty {field} required")
                style = record.get("style")
                if (not isinstance(style, dict) or set(style) != {"palette", "typography", "photography", "graphics", "rhythm"} or
                        any(not isinstance(v, str) or not v.strip() for v in style.values())):
                    errors.append(f"{prefix}: complete style roles required")
            else:
                if not isinstance(record.get("family_id"), str) or not ID.fullmatch(record["family_id"]):
                    errors.append(f"{prefix}: family_id required")
                for field, allowed in (("intents", None), ("kinds", KINDS), ("canvas_shapes", SHAPES), ("fixed_style", None), ("adaptation_rules", None)):
                    values = record.get(field)
                    if not _strings(values) or (allowed and any(v not in allowed for v in values)):
                        errors.append(f"{prefix}: invalid {field}")
                if not isinstance(record.get("recipe"), str) or record["recipe"] not in RECIPES:
                    errors.append(f"{prefix}: unsupported recipe")
                for field in ("generation", "layout"):
                    if not isinstance(record.get(field), dict) or not record[field]:
                        errors.append(f"{prefix}: nonempty {field} required")
                layout = record.get("layout")
                if isinstance(layout, dict):
                    _canvas_errors(layout, record.get("canvas_shapes"), prefix, errors)
                    if layout.get("recipe") != record.get("recipe"):
                        errors.append(f"{prefix}: layout recipe must match template recipe")
                    if "text_group_box" in layout and not _box(layout["text_group_box"]):
                        errors.append(f"{prefix}: invalid text_group_box")
                    if "headline_family" in layout and layout["headline_family"] not in ("sans", "serif"):
                        errors.append(f"{prefix}: headline_family must be sans or serif")
                    if "headline_weight" in layout and (type(layout["headline_weight"]) is not int or layout["headline_weight"] not in (400, 600, 700) or (layout.get("headline_family") == "serif" and layout["headline_weight"] == 700)):
                        errors.append(f"{prefix}: unsupported headline_weight")
                    if "align" in layout and layout["align"] not in ("left", "center", "right"):
                        errors.append(f"{prefix}: invalid text alignment")
                    if "text_color" in layout and (not isinstance(layout["text_color"], str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", layout["text_color"])):
                        errors.append(f"{prefix}: text_color must be #RRGGBB")
                    if "text_surface" in layout:
                        surface = layout["text_surface"]
                        if not isinstance(surface, dict) or set(surface) - {"kind", "color", "opacity", "padding_em", "direction"} or surface.get("kind") not in ("transparent", "solid", "gradient"):
                            errors.append(f"{prefix}: invalid text_surface")
                        elif (any(key in surface and (isinstance(surface[key], bool) or not isinstance(surface[key], (int, float)) or not math.isfinite(surface[key]) or not 0 <= surface[key] <= maximum) for key, maximum in (("opacity", 1), ("padding_em", 2))) or
                              ("direction" in surface and surface["direction"] not in ("horizontal", "vertical")) or
                              ("color" in surface and (not isinstance(surface["color"], str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", surface["color"])) )):
                            errors.append(f"{prefix}: invalid text_surface values")
                if not isinstance(record.get("scene_default"), str) or not record["scene_default"].strip():
                    errors.append(f"{prefix}: scene_default required")
                _prompt_errors(record.get("prompt_template"), prefix, errors)
            _text_errors(record, prefix, errors)
        if check_references:
            for identifier in {identifier for identifier, _ in seen}:
                revisions = sorted(revision for key, revision in seen if key == identifier)
                if revisions != list(range(1, len(revisions) + 1)):
                    errors.append(f"{collection}: versions must retain consecutive history starting at 1: {identifier}")
    if check_references:
        for record in collections["templates"]:
            if isinstance(record, dict) and (not isinstance(record.get("family_id"), str) or record["family_id"] not in family_ids):
                errors.append(f"{record.get('id', 'template')}: unknown family ID")
    return errors


def _validated(document: dict, *, check_references: bool = True) -> dict:
    errors = validate_library(document, check_references=check_references)
    if errors:
        raise TemplateError("; ".join(errors))
    return document


def _merge(builtin: dict, user: dict) -> dict:
    merged = empty_library()
    for key in ("sources", "families", "templates"):
        merged[key] = copy.deepcopy(builtin[key] + user[key])
    return _validated(merged)


def load_library(builtin_path: Path | str | None = None, user_path: Path | str | None = None) -> dict:
    builtin_path, user_path = Path(builtin_path or DEFAULT_BUILTIN), Path(user_path or DEFAULT_USER)
    if builtin_path.resolve() == user_path.resolve():
        raise TemplateError("Built-in and user libraries must be separate files")
    builtin = _validated(_read_json(builtin_path))
    user = _validated(_read_json(user_path), check_references=False) if user_path.exists() else empty_library()
    return _merge(builtin, user)


def _latest(records: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for record in records:
        if record["id"] not in latest or record["revision"] > latest[record["id"]]["revision"]:
            latest[record["id"]] = record
    return sorted(latest.values(), key=lambda r: r["id"])


def _get(library: dict, collection: str, identifier: str, revision: int | None) -> dict | None:
    records = [r for r in library[collection] if r["id"] == identifier and (revision is None or r["revision"] == revision)]
    return copy.deepcopy(max(records, key=lambda r: r["revision"])) if records else None


def get_family(library: dict, identifier: str, revision: int | None = None) -> dict | None:
    return _get(library, "families", identifier, revision)


def get_template(library: dict, identifier: str, revision: int | None = None) -> dict | None:
    return _get(library, "templates", identifier, revision)


def import_library(payload: dict, user_path: Path | str | None = None, builtin_path: Path | str | None = None) -> dict:
    """Atomically append reviewed versions; conflicting revisions never write.

    Semantically equal records reuse the canonical ID/revision. Provenance and
    review-note differences do not manufacture a new design version. Close but
    nonidentical designs are reported for agent review, not silently merged.
    """
    payload = copy.deepcopy(_validated(payload, check_references=False))
    user_path, builtin_path = Path(user_path or DEFAULT_USER), Path(builtin_path or DEFAULT_BUILTIN)
    if user_path.resolve() == builtin_path.resolve():
        raise TemplateError("Import may not overwrite the built-in library")
    with _selection_lock(user_path):
        builtin = _validated(_read_json(builtin_path))
        user = _validated(_read_json(user_path), check_references=False) if user_path.exists() else empty_library()
        merged = _merge(builtin, user)
        result = {"added": {"sources": [], "families": [], "templates": []}, "reused": {"sources": [], "families": [], "templates": []}, "source_map": {}, "family_map": [], "template_map": [], "similar_candidates": []}
        for source in payload["sources"]:
            same_id = next((s for s in merged["sources"] if s["id"] == source["id"]), None)
            if same_id and same_id != source:
                raise TemplateError(f"Immutable source ID conflict: {source['id']}")
            existing = same_id or next((s for s in merged["sources"] if (s["sha256"], s.get("region_norm")) == (source["sha256"], source.get("region_norm"))), None)
            if existing:
                result["source_map"][source["id"]] = existing["id"]
                result["reused"]["sources"].append(existing["id"])
            else:
                result["source_map"][source["id"]] = source["id"]
                result["added"]["sources"].append(source["id"])
                user["sources"].append(source)
                merged["sources"].append(source)
        family_alias: dict[str, str] = {}
        for collection, map_key in (("families", "family_map"), ("templates", "template_map")):
            for incoming in sorted(payload[collection], key=lambda r: (r["id"], r["revision"])):
                record = copy.deepcopy(incoming)
                record["source_ids"] = sorted(set(result["source_map"].get(v, v) for v in record["source_ids"]))
                if collection == "templates":
                    record["family_id"] = family_alias.get(record["family_id"], record["family_id"])
                versions = [r for r in merged[collection] if r["id"] == record["id"]]
                same_version = next((r for r in versions if r["revision"] == record["revision"]), None)
                semantic = _semantic_hash(record)
                if same_version and _semantic_hash(same_version) != semantic:
                    raise TemplateError(f"Immutable {collection} revision conflict: {record['id']}@{record['revision']}")
                existing = same_version or next((r for r in merged[collection] if _semantic_hash(r) == semantic), None)
                if existing:
                    chosen = existing
                    result["reused"][collection].append({"id": chosen["id"], "revision": chosen["revision"]})
                else:
                    expected = max((r["revision"] for r in versions), default=0) + 1
                    if record["revision"] != expected:
                        raise TemplateError(f"New {collection} revision must be {expected}: {record['id']}")
                    chosen = record
                    for candidate in _latest(merged[collection]):
                        if collection == "families":
                            similar = set(candidate["categories"]) & set(record["categories"])
                        else:
                            similar = candidate["family_id"] == record["family_id"] and candidate["recipe"] == record["recipe"] and set(candidate["intents"]) & set(record["intents"])
                        if similar:
                            result["similar_candidates"].append({"kind": collection, "incoming_id": record["id"], "candidate_id": candidate["id"], "reason": "Related category or composition; retained as a distinct reviewed variant."})
                    user[collection].append(record)
                    merged[collection].append(record)
                    result["added"][collection].append({"id": record["id"], "revision": record["revision"]})
                result[map_key].append({"incoming_id": incoming["id"], "incoming_revision": incoming["revision"], "id": chosen["id"], "revision": chosen["revision"]})
                if collection == "families":
                    family_alias[incoming["id"]] = chosen["id"]
        _validated(merged)
        if any(result["added"].values()):
            _write_json(user_path, user)
        result["changed"] = any(result["added"].values())
        return result


def _normalise(value: str) -> str:
    return "_".join(re.findall(r"\w+", value.casefold()))


def _words(value: Any) -> str:
    if isinstance(value, str):
        return value.casefold().replace("_", " ").replace("-", " ")
    if isinstance(value, list):
        return " ".join(_words(v) for v in value)
    return ""


CATEGORY_ALIASES = {
    "tools": "power_tool", "tool": "power_tool", "power_tools": "power_tool",
    "beauty": "beauty_cosmetic", "cosmetics": "beauty_cosmetic", "cosmetic": "beauty_cosmetic",
    "travel": "travel_gear", "luggage": "travel_gear", "audio": "audio_electronics",
    "electronics": "audio_electronics", "pet_supplies": "pet_accessory", "pet_accessories": "pet_accessory",
    "shoes": "footwear", "clothing": "apparel", "home_decoration": "home_decor",
}


def _category_tag(value: str) -> str:
    tag = _normalise(value)
    return CATEGORY_ALIASES.get(tag, tag)


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized = _words(phrase)
    plural = r"(?:s|es)?" if re.search(r"[a-z]{3,}$", normalized) else ""
    return bool(re.search(r"(?<!\w)" + re.escape(normalized) + plural + r"(?!\w)", text))


def rank_families(library: dict, context: dict) -> list[dict]:
    """Conservative category gate; stylistic overlap alone is not a match."""
    _validated(library)
    if not isinstance(context, dict):
        raise TemplateError("Template context must be an object")
    category_text = _words(context.get("category", context.get("product_category")))
    product_text = _words(context.get("product"))
    categories = {_category_tag(v) for v in (context.get("category") if isinstance(context.get("category"), list) else [category_text]) if isinstance(v, str) and v}
    for tag, keywords in CATEGORY_KEYWORDS:
        if any(_contains_phrase(category_text + " " + product_text, word) for word in keywords):
            categories.add(_category_tag(tag))
    preferences = _words(context.get("style_preferences"))
    result = []
    for family in _latest(library["families"]):
        matches = sorted({_category_tag(c) for c in family["categories"]} & categories)
        if not matches:
            continue
        keyword_matches = [kw for kw in family["keywords"] if _contains_phrase(preferences, kw) or _contains_phrase(product_text, kw)]
        score = 10 * len(matches) + 2 * len(keyword_matches)
        reasons = ["Category match: " + ", ".join(matches)]
        if keyword_matches:
            reasons.append("Product/style cues: " + ", ".join(keyword_matches))
        result.append({"id": family["id"], "revision": family["revision"], "score": score, "reasons": reasons})
    return sorted(result, key=lambda r: (-r["score"], r["id"]))


INTENT_GROUPS = {
    "dimensions": ("dimension", "dimensions", "size", "sizing", "measurement", "measurements", "尺寸"),
    "faq": ("faq", "question", "questions", "问答"),
    "how_to": ("how to", "how_to", "step", "steps", "installation", "install", "assembly", "步骤", "安装"),
    "kit_overview": ("kit overview", "kit_overview", "included", "what is included", "contents", "包含"),
    "detail_callout": ("detail callout", "detail_callout", "callout", "annotation", "标注"),
    "visual_detail": ("visual detail", "visual_detail", "macro", "detail", "texture", "细节"),
    "feature_detail": ("feature detail", "feature_detail", "feature", "function", "功能"),
    "lifestyle_hero": ("lifestyle hero", "lifestyle_hero", "lifestyle", "scene", "hero", "场景"),
    "editorial_hero": ("editorial hero", "editorial_hero", "editorial", "premium", "质感"),
    "gift_lifestyle": ("gift lifestyle", "gift_lifestyle", "gift", "礼物"),
    "benefit_communication": ("benefit communication", "benefit_communication", "benefit", "用途"),
    "action_hero": ("action hero", "action_hero", "action", "performance", "动作"),
    "scene_grid": ("scene grid", "scene_grid", "multiple scenes", "four scenes", "场景四格"),
}
INTENT_ALIASES = {
    "scene_context": {"lifestyle_hero"}, "gift_context": {"gift_lifestyle"},
    "multi_scene": {"scene_grid"}, "versatility": {"scene_grid"},
    "material_detail": {"visual_detail"}, "craftsmanship": {"visual_detail"},
    "function_demo": {"action_hero", "feature_detail"},
    "setup": {"how_to"}, "assembly": {"how_to"}, "installation": {"how_to"},
}


def _intents(value: Any) -> set[str]:
    text = _words(value)
    signals = set()
    for intent, keywords in INTENT_GROUPS.items():
        if any(re.search(r"(?<!\w)" + re.escape(_words(word)) + r"(?!\w)", text) for word in keywords):
            signals.add(intent)
    if isinstance(value, list):
        signals.update(_normalise(v) for v in value if isinstance(v, str))
    elif isinstance(value, str) and " " not in value:
        signals.add(_normalise(value))
    for tag in tuple(signals):
        signals.update(INTENT_ALIASES.get(tag, set()))
    return signals


def _job_kind(job: dict) -> str:
    kind = job.get("kind", "secondary")
    if not isinstance(kind, str):
        raise TemplateError("Template job kind must be a string")
    return "secondary" if kind == "listing" else kind


def _job_shape(job: dict) -> str:
    canvas = job.get("canvas")
    if isinstance(canvas, dict):
        canvas = [canvas.get("width"), canvas.get("height")]
    if (not isinstance(canvas, (list, tuple)) or len(canvas) != 2 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in canvas)):
        raise TemplateError("Template job requires a positive width/height canvas")
    ratio = canvas[0] / canvas[1]
    return "square" if .95 <= ratio <= 1.05 else ("wide" if ratio > 1 else "portrait")


def rank_templates(library: dict, family_id: str, job: dict) -> list[dict]:
    _validated(library)
    if not isinstance(job, dict):
        raise TemplateError("Template job must be an object")
    kind = _job_kind(job)
    if kind == "main":
        return []
    shape = _job_shape(job)
    wanted = _intents(job.get("intents") or job.get("image_intent") or job.get("selling_job", ""))
    special = wanted & {"dimensions", "faq", "how_to", "kit_overview"}
    if not isinstance(job.get("layout", {}), dict):
        raise TemplateError("Template job layout must be an object")
    requested_recipe = job.get("layout", {}).get("recipe")
    result = []
    for template in _latest(library["templates"]):
        if template["family_id"] != family_id or kind not in template["kinds"] or shape not in template["canvas_shapes"]:
            continue
        available = _intents(template["intents"])
        overlap = wanted & available
        if not overlap or (special and not special <= available):
            continue
        score = len(overlap) * 10 + (3 if requested_recipe == template["recipe"] else 0)
        reasons = [f"Compatible {kind} / {shape}", "Intent match: " + ", ".join(sorted(overlap))]
        if requested_recipe == template["recipe"]:
            reasons.append("Compatible preferred layout recipe")
        result.append({"id": template["id"], "revision": template["revision"], "score": score, "reasons": reasons, "recipe": template["recipe"]})
    return sorted(result, key=lambda r: (-r["score"], r["id"]))


def template_compatible(template: dict, job: dict) -> bool:
    """Kind/shape/text-route gate; semantic selection stays with the caller."""
    if not isinstance(template, dict) or not isinstance(job, dict):
        return False
    return (_job_kind(job) in template.get("kinds", []) and _job_shape(job) in template.get("canvas_shapes", []) and
            job.get("text_mode", "local_overlay") in ("local_overlay", "model_native"))


def compile_template(family: dict, template: dict, context: dict, job: dict) -> dict:
    """Compile only text snapshots. Local typography never enters generation."""
    snapshot_doc = empty_library()
    snapshot_doc.update(families=[family], templates=[template])
    _validated(snapshot_doc, check_references=False)
    if template["family_id"] != family["id"]:
        raise TemplateError("Template does not belong to the selected family")
    if not isinstance(context, dict) or not isinstance(job, dict):
        raise TemplateError("Template context and job must be objects")
    if not template_compatible(template, job):
        raise TemplateError("Template is incompatible with job kind, canvas, or text mode")
    variables = {"product": context.get("product"), "scene": job.get("scene") or context.get("scene") or template["scene_default"], "selling_job": job.get("selling_job") or context.get("selling_job")}
    if any(not isinstance(v, str) or not v.strip() for v in variables.values()):
        raise TemplateError("Template compilation requires product, scene, and selling_job text")
    generation = copy.deepcopy(template["generation"])
    generation["resolved_prompt"] = template["prompt_template"].format_map(variables)
    generation["family_visual_style"] = {key: family["style"][key] for key in ("palette", "photography", "graphics")}
    generation["text_policy"] = ("Render only approved copy supplied separately by the project; never copy sample text, claims, labels, brands, or badges." if job.get("text_mode") == "model_native" else
                                 "Generate no marketing text, invented labels, brand marks, claims, badges, or sample-product facts. Approved copy is composed locally.")
    layout = copy.deepcopy(template["layout"])
    variants = layout.pop("canvas_variants", None)
    if variants:
        layout.update(copy.deepcopy(variants[_job_shape(job)]))
    composition_note = layout.pop("composition_note", "")
    if layout.get("product_region_norm") is not None:
        generation["canvas_composition"] = {"product_region_norm": copy.deepcopy(layout["product_region_norm"]),
                                            "text_region_norm": copy.deepcopy(layout.get("text_group_box")),
                                            "notes": composition_note}
    layout["family_typography"] = family["style"]["typography"]
    layout["series_rhythm"] = family["style"]["rhythm"]
    layout["design_guidance"] = {"fixed_style": copy.deepcopy(template["fixed_style"]), "adaptation_rules": copy.deepcopy(template["adaptation_rules"]), "avoid": list(dict.fromkeys(family["avoid"] + template["avoid"]))}
    brief = {"version": 1, "reference_ids": [template["id"]], "generation": generation, "layout": layout}
    binding = {"schema_version": 1}
    for key, record in (("family", family), ("template", template)):
        binding[key] = {"id": record["id"], "revision": record["revision"], "content_hash": content_hash(record), "snapshot": copy.deepcopy(record)}
    return {"brief": brief, "binding": binding}


def binding_issue(binding: Any) -> str | None:
    """Validate immutable snapshots only; never consult current libraries/images."""
    if not isinstance(binding, dict) or set(binding) != {"schema_version", "family", "template"} or type(binding.get("schema_version")) is not int or binding.get("schema_version") != 1:
        return "Invalid template binding structure"
    records = {}
    for key in ("family", "template"):
        value = binding.get(key)
        if not isinstance(value, dict) or set(value) != {"id", "revision", "content_hash", "snapshot"}:
            return f"Invalid {key} binding"
        snapshot = value.get("snapshot")
        if not isinstance(snapshot, dict) or value.get("id") != snapshot.get("id") or value.get("revision") != snapshot.get("revision"):
            return f"Invalid {key} snapshot identity"
        try:
            if content_hash(snapshot) != value.get("content_hash"):
                return f"Changed {key} template snapshot"
        except TemplateError as exc:
            return str(exc)
        records[key] = snapshot
    document = empty_library()
    document.update(families=[records["family"]], templates=[records["template"]])
    errors = validate_library(document, check_references=False)
    if errors:
        return "; ".join(errors)
    if records["template"]["family_id"] != records["family"]["id"]:
        return "Template snapshot has a different family"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builtin", type=Path, default=DEFAULT_BUILTIN)
    parser.add_argument("--user", type=Path, default=DEFAULT_USER)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Return the merged, text-only library")
    validate = commands.add_parser("validate", help="Validate the merged library or a complete JSON library")
    validate.add_argument("--input", type=Path)
    importer = commands.add_parser("import", help="Atomically add agent-reviewed JSON records")
    importer.add_argument("--input", type=Path, required=True)
    candidates = commands.add_parser("candidates", help="Rank families, optionally templates for a job")
    candidates.add_argument("--context", type=Path, required=True)
    candidates.add_argument("--job", type=Path)
    candidates.add_argument("--family-id")
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            result = import_library(_read_json(args.input), args.user, args.builtin)
        elif args.command == "validate" and args.input:
            errors = validate_library(_read_json(args.input))
            result = {"valid": not errors, "errors": errors}
        else:
            library = load_library(args.builtin, args.user)
            if args.command == "list":
                result = library
            elif args.command == "validate":
                result = {"valid": True, "errors": [], "counts": {key: len(library[key]) for key in ("sources", "families", "templates")}}
            else:
                context = _read_json(args.context)
                families = rank_families(library, context)
                family_id = args.family_id or (families[0]["id"] if families else None)
                result = {"families": families, "templates": rank_templates(library, family_id, _read_json(args.job)) if args.job and family_id else [], "selected_family_id": family_id}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2 if isinstance(result, dict) and result.get("valid") is False else 0
    except (TemplateError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
