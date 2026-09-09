#!/usr/bin/env python3
"""Deterministic Listing v2 checks; semantic truth still needs an independent review.

Python 3.9+, standard library only. No command rewrites generated marketing text.
Fingerprints bind review files to source bytes; backend fingerprints bind canonical
single-product payloads. All backend calls use the shared credential-safe launcher.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import string
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path

_BACKEND_SPEC = importlib.util.spec_from_file_location("listing_backend_cli", Path(__file__).with_name("backend_cli.py"))
backend_cli = importlib.util.module_from_spec(_BACKEND_SPEC)
_BACKEND_SPEC.loader.exec_module(backend_cli)

POLICY_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "quality_policy.json"
TEXT_FIELDS = ("title", "item_highlight", "description", "search_terms")
CONTENT_FIELDS = ("bullets", "description", "search_terms")
FRONT_FIELDS = ("title", "item_highlight") + tuple("bullets[%d]" % i for i in range(5)) + ("description",)
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
LENGTH_UNITS = {"mm", "cm", "m", "in", "ft"}
UNIT_ALIASES = {"inch": "in", "inches": "in", '"': "in", "centimeter": "cm",
                "centimeters": "cm", "millimeter": "mm", "millimeters": "mm",
                "meter": "m", "meters": "m", "feet": "ft", "foot": "ft",
                "fluid ounces": "fl oz", "fluid ounce": "fl oz", "floz": "fl oz"}


def _reject_json_constant(value):
    raise ValueError("Non-finite JSON number is not permitted")


def load_json(path):
    with open(path, encoding="utf-8-sig") as handle:
        return json.load(handle, parse_constant=_reject_json_constant)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent),
                                         prefix="." + path.name + ".", delete=False) as handle:
            temporary = handle.name
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def canonical_sha256(data):
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_fingerprints(profile_path, listing_path, qa_path=None):
    return {key + "_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None
            for key, path in (("profile", profile_path), ("listing", listing_path), ("qa", qa_path))}


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _norm(value):
    return re.sub(r"[\s\-‐‑‒–—]+", " ", str(value).casefold()).strip()


def _contains(text, phrase):
    phrase = _norm(phrase)
    # Japanese/Chinese do not require spaces around an intact product phrase.
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", phrase):
        return bool(phrase) and phrase in _norm(text)
    if phrase and phrase[0].isdigit():
        return re.search(r"(?<![A-Za-z0-9_])" + re.escape(phrase) + r"(?![A-Za-z0-9_])", _norm(text)) is not None
    return bool(phrase) and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", _norm(text)) is not None


def _decimal_text(value):
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _measurement_display(record, site):
    kind = record.get("kind")
    value, unit = record.get("value"), record.get("unit")
    if not isinstance(value, str) or not value.strip() or not isinstance(unit, str) or not unit.strip():
        raise ValueError("measurement requires a nonempty original string value and unit")
    unit = UNIT_ALIASES.get(unit.strip().lower(), unit.strip().lower())
    if kind in ("nominal", "size"):
        unit = record["unit"].strip()
        return {"display_value": value.strip(), "display_unit": unit,
                "display_text": value.strip() + " " + unit, "approximate": False}
    if kind not in ("length", "weight", "volume"):
        raise ValueError("unknown measurement kind")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("measurement value is not a decimal") from None
    if not number.is_finite() or number <= 0 or number.adjusted() > 12 or number.adjusted() < -12:
        raise ValueError("measurement must be a finite positive practical value")
    if kind == "weight" and unit not in ("mg", "g", "kg", "oz", "lb", "lbs"):
        raise ValueError("weight unit is unsupported (oz is mass; fl oz is volume)")
    if kind == "volume" and unit not in ("ml", "l", "cl", "fl oz", "gal", "qt", "pt", "cup", "cups"):
        raise ValueError("volume unit is unsupported (fl oz is volume; oz is mass)")
    approximate = False
    with localcontext() as context:
        context.prec = 50
        if kind == "length":
            if unit not in LENGTH_UNITS:
                raise ValueError("unsupported length unit")
            if site == "US":
                # Divide by the exact conversion constant instead of a rounded reciprocal.
                exact = {"mm": lambda: number / Decimal("25.4"),
                         "cm": lambda: number / Decimal("2.54"),
                         "m": lambda: number * 100 / Decimal("2.54"),
                         "ft": lambda: number * 12, "in": lambda: number}[unit]()
                number = exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if number == 0:
                    raise ValueError("length rounds to zero inches; needs an explicit precision exception")
                approximate = number != exact
                unit = "in"
    shown = _decimal_text(number)
    return {"display_value": shown, "display_unit": unit,
            "display_text": shown + " " + unit, "approximate": approximate}


def normalize_profile(profile):
    """Return a copy with stable missing IDs and deterministic measurement displays.

    Invalid/missing units raise ValueError, leaving the source untouched. Original
    values and units are retained; no product facts or variant combinations added.
    """
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    result = copy.deepcopy(profile)
    result.setdefault("listing_mode", "single")
    if result["listing_mode"] not in ("single", "family"):
        raise ValueError("profile.listing_mode must be single or family")
    site = result.get("site")
    if site not in load_json(POLICY_PATH)["sites"]:
        raise ValueError("profile.site must name a supported site")
    variants = _list(result.get("variants")) if result["listing_mode"] == "family" else []
    used_ids = {v.get("variant_id") for v in variants if isinstance(v, dict) and isinstance(v.get("variant_id"), str)}
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict):
            raise ValueError("variant must be an object")
        if not variant.get("variant_id"):
            number = index + 1
            candidate = "child-%02d" % number
            while candidate in used_ids:
                number += 1
                candidate = "child-%02d" % number
            variant["variant_id"] = candidate
            used_ids.add(candidate)
        variant.setdefault("sku", None)
        variant.setdefault("asin", None)
    global_measurements = {}
    for owner in [result] + variants:
        for measurement in _list(owner.get("measurements")):
            if not isinstance(measurement, dict):
                raise ValueError("measurement must be an object")
            mid = measurement.get("measurement_id")
            if not isinstance(mid, str) or not mid or mid in global_measurements:
                raise ValueError("measurement_id must be present and globally unique")
            measurement.update(_measurement_display(measurement, site))
            global_measurements[mid] = measurement
    root_ids = {m.get("measurement_id") for m in _list(result.get("measurements"))}
    for variant in variants:
        allowed = root_ids | {m.get("measurement_id") for m in _list(variant.get("measurements"))}
        for attribute in _dict(variant.get("attributes")).values():
            if not isinstance(attribute, dict):
                raise ValueError("profile attributes must be objects")
            if attribute.get("measurement_id"):
                mid = attribute["measurement_id"]
                if mid not in allowed:
                    raise ValueError("attribute references a missing or another child's measurement")
                attribute["display"] = global_measurements[mid]["display_text"]
                attribute["title_value"] = global_measurements[mid]["display_text"]
    return result


def resolved_listings(profile, listing):
    """Return [(target, complete_single_content)] in input order (never Cartesian)."""
    if profile.get("listing_mode", "single") != "family":
        return [("single", copy.deepcopy(listing))]
    result = []
    for variant in _list(listing.get("variants")):
        if not isinstance(variant, dict):
            continue
        content = {key: listing.get(key, profile.get(key)) for key in ("site", "listing_language", "listing_language_code")}
        content.update(copy.deepcopy(_dict(listing.get("shared_content"))))
        content.update({key: copy.deepcopy(value) for key, value in _dict(variant.get("content_overrides")).items() if key in CONTENT_FIELDS})
        content.update({key: copy.deepcopy(variant.get(key)) for key in ("title", "item_highlight", "claims")})
        result.append((variant.get("variant_id"), content))
    return result


def build_payloads(profile, listing):
    """Return records {target, filename, payload, payload_sha256}; no backend calls."""
    records = []
    for target, content in resolved_listings(profile, listing):
        if not isinstance(target, str) or not SAFE_ID.fullmatch(target):
            raise ValueError("unsafe payload target")
        payload = {key: content.get(key, profile.get(key)) for key in
                   ("site", "listing_language", "listing_language_code", "title", "item_highlight", "bullets", "description", "search_terms")}
        records.append({"target": target, "filename": target + ".json", "payload": payload,
                        "payload_sha256": canonical_sha256(payload)})
    return records


def _field(content, field):
    if field in TEXT_FIELDS:
        return content.get(field)
    match = re.fullmatch(r"bullets\[([0-4])\]", str(field))
    if match:
        bullets = _list(content.get("bullets"))
        index = int(match[1])
        return bullets[index] if index < len(bullets) else None
    return None


def check_media_sets(profile, listing, plans, add):
    """Check creative ownership/counts separately from each resolved image's facts."""
    mode = profile.get("listing_mode", "single")
    ids = [v.get("variant_id") for v in _list(profile.get("variants")) if isinstance(v, dict)] if mode == "family" else []
    strategy = listing.get("media_strategy")
    allowed = ("single",) if mode == "single" else ("per_variant_full", "shared_secondary")
    if strategy not in allowed:
        add("media_strategy", "listing.media_strategy", "Select single, per_variant_full, or confirmed shared_secondary for this product mode")
    if strategy == "shared_secondary":
        assessment = _dict(profile.get("appearance_assessment"))
        if (assessment.get("status") != "same" or assessment.get("differences_only_size_or_quantity") is not True
                or not isinstance(assessment.get("source_ref"), str) or not assessment["source_ref"].strip()):
            add("media_reuse_evidence", "profile.appearance_assessment", "Sharing secondary creatives requires sourced confirmation of identical appearance with only size/quantity differences")
    sets = listing.get("image_sets")
    if not isinstance(sets, dict):
        add("image_sets", "listing.image_sets", "Explicit shared and per-child image sets are required for new acceptance")
        return
    if set(sets) != {"shared", "variants"}:
        add("image_sets", "listing.image_sets", "Image sets contain shared and variants only")
    used = set()
    image_counts = load_json(POLICY_PATH)["media_limits"]

    def use(pid, role, target, path, number=None):
        plan = plans.get(pid) if isinstance(pid, str) else None
        if plan is None or plan.get("role") != role:
            add("image_set_reference", path, "Plan reference is missing or has the wrong image role")
            return
        used.add(pid)
        if plan.get("applies_to") != [target]:
            add("image_set_scope", path, "Shared plans use ['all']; a child's independent creative uses only that child ID")
        label = plan.get("image") if role != "aplus" else plan.get("module")
        if role != "aplus" and (not isinstance(label, str) or not re.match(r"^图%d（[^）]+）$" % number, label)):
            add("image_number", path, "Number each main/secondary set as 图1（主图） through 图7（主题）")
        if role == "main" and label != "图1（主图）":
            add("image_number", path, "The first image is 图1（主图）")
        if role == "aplus" and (not isinstance(label, str) or not re.match(r"^模块%d[：:]\S" % number, label)):
            add("aplus_number", path, "Number A+ modules consecutively as 模块N：主题 in their shared order")

    def refs(value, path, count=None):
        if not isinstance(value, list) or any(not isinstance(pid, str) or not pid for pid in value):
            add("image_set_reference", path, "Image references must be an array of nonempty plan IDs")
            return []
        if len(set(value)) != len(value):
            add("image_set_duplicate", path, "A plan cannot occupy two slots in the same set")
        if count is not None and len(value) != count:
            add("image_set_count", path, "Exactly %d references are required" % count)
        return value

    shared = _dict(sets.get("shared"))
    if set(shared) != {"main", "secondary", "a_plus"}:
        add("image_set_shape", "listing.image_sets.shared", "Shared set needs exactly main, secondary, and a_plus")
    use(shared.get("main"), "main", "all", "listing.image_sets.shared.main", 1)
    secondary = refs(shared.get("secondary"), "listing.image_sets.shared.secondary", image_counts["secondary_count"])
    for number, pid in enumerate(secondary, 2):
        use(pid, "secondary", "all", "listing.image_sets.shared.secondary[%d]" % (number - 2), number)
    a_plus = refs(shared.get("a_plus"), "listing.image_sets.shared.a_plus")
    for index, pid in enumerate(a_plus):
        use(pid, "aplus", "all", "listing.image_sets.shared.a_plus[%d]" % index, index + 1)
    unique_aplus_images = {pid for pid in a_plus if _dict(plans.get(pid)).get("role") == "aplus"
                           and _dict(plans.get(pid)).get("asset_type") == "image"}
    if len(unique_aplus_images) < image_counts["a_plus_min_images"]:
        add("aplus_image_count", "listing.image_sets.shared.a_plus", "At least %d distinct A+ image creatives are required; text-only modules do not count" % image_counts["a_plus_min_images"])
    children = sets.get("variants")
    if not isinstance(children, list):
        add("image_sets_variants", "listing.image_sets.variants", "Per-child sets must be an array (empty for a single product)")
        children = []
    if [c.get("variant_id") if isinstance(c, dict) else None for c in children] != ids:
        add("image_sets_variants", "listing.image_sets.variants", "Image sets must exactly match supplied children and input order")
    for index, child in enumerate(children):
        path = "listing.image_sets.variants[%d]" % index
        if not isinstance(child, dict):
            add("image_set_shape", path, "Child set must be an object")
            continue
        if set(child) != {"variant_id", "main", "secondary"}:
            add("image_set_shape", path, "Child set contains variant_id, main, secondary; A+ is shared only")
        vid = child.get("variant_id")
        if not isinstance(vid, str) or vid not in ids:
            continue
        use(child.get("main"), "main", vid, path + ".main", 1)
        child_secondary = refs(child.get("secondary"), path + ".secondary", image_counts["secondary_count"])
        if strategy == "shared_secondary" and child_secondary != secondary:
            add("image_reuse_mismatch", path + ".secondary", "This mode must reuse the shared six secondary plans in order")
        for number, pid in enumerate(child_secondary, 2):
            use(pid, "secondary", "all" if strategy == "shared_secondary" else vid,
                path + ".secondary[%d]" % (number - 2), number)
    if used != set(plans):
        add("image_set_orphan", "listing.image_sets", "Every creative must belong to the shared or corresponding child set; no extra or unassigned images")


def check_local(profile, listing, qa=None):
    """Return deterministic issues; not a language detector or claim-truth oracle."""
    try:
        # Public dict API follows the same strict JSON constraints as the CLI.
        json.dumps([profile, listing, qa], allow_nan=False)
        return _check_local(profile, listing, qa)
    except (TypeError, ValueError, KeyError, AttributeError):
        return [{"severity": "error", "code": "malformed_structure", "path": "$",
                 "message": "Invalid JSON value or nested field type; use the v2 data contract"}]


def _check_local(profile, listing, qa=None):
    issues = []

    def add(code, path, message, severity="error"):
        issues.append({"severity": severity, "code": code, "path": path, "message": message})

    def array(owner, key, path):
        value = owner.get(key)
        if not isinstance(value, list):
            add("array_required", path + "." + key, "Expected an array")
            return []
        return value

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    if not isinstance(profile, dict) or not isinstance(listing, dict):
        add("object_required", "$", "Profile and listing must be JSON objects")
        return issues
    policy = load_json(POLICY_PATH)
    limits = policy["default_limits"]
    mode = profile.get("listing_mode", "single")
    if mode not in ("single", "family"):
        add("listing_mode", "profile.listing_mode", "Use single or family")
    if listing.get("listing_mode", "single") != mode:
        add("mode_mismatch", "listing.listing_mode", "Profile and listing modes differ")
    if profile.get("schema_version") != "2.1" or listing.get("schema_version") != "2.1":
        add("legacy_schema", "$", "Legacy content remains readable; regenerate and review under the current delivery contract before acceptance", "incomplete")
    if "a_plus_plan" in listing and "aplus_plan" in listing and listing["a_plus_plan"] != listing["aplus_plan"]:
        add("aplus_alias_conflict", "listing.a_plus_plan", "a_plus_plan and legacy aplus_plan contain conflicting content")
    a_plus_key = "a_plus_plan" if "a_plus_plan" in listing else "aplus_plan"
    if listing.get("schema_version") == "2.1":
        if "brand_name" not in listing or listing.get("brand_name") != profile.get("brand"):
            add("brand_metadata", "listing.brand_name", "brand_name must preserve the supplied brand or null")
        for key in ("buyer_question_coverage", "excluded_claims"):
            array(listing, key, "listing")
        if any(not nonempty(item) for item in _list(listing.get("excluded_claims"))):
            add("excluded_claims", "listing.excluded_claims", "Excluded claims must be nonempty strings")
        for index, item in enumerate(_list(listing.get("buyer_question_coverage"))):
            if not isinstance(item, dict) or any(not nonempty(item.get(key)) for key in ("question", "status", "location")):
                add("buyer_question_coverage", "listing.buyer_question_coverage[%d]" % index, "Coverage requires a question, status, and readable location or reason")
            elif item["status"] not in ("covered", "partially_covered", "not_claimed", "not_applicable"):
                add("buyer_question_coverage", "listing.buyer_question_coverage[%d].status" % index, "Use covered, partially_covered, not_claimed, or not_applicable")
    site = profile.get("site")
    if site not in policy["sites"]:
        add("site", "profile.site", "A supported site is required; no implicit US default")
    if listing.get("site") != site:
        add("site_mismatch", "listing.site", "Listing site must match profile")
    for key in ("listing_language", "listing_language_code"):
        if not nonempty(profile.get(key)) or listing.get(key) != profile.get(key):
            add("language_metadata", "listing." + key, "Language metadata must be present and match profile")
    if site in policy["sites"]:
        expected = policy["sites"][site]["language_code"]
        if profile.get("listing_language_code") != expected and not (site == "CA" and profile.get("listing_language_code") == "fr"):
            add("site_language", "profile.listing_language_code", "Language code does not match the target site")
    identity = _dict(profile.get("product_identity"))
    for key in ("original_name", "canonical_name"):
        if not nonempty(identity.get(key)):
            add("identity_missing", "profile.product_identity." + key, "Product identity is required")
    protected = _list(identity.get("protected_terms"))
    if not protected or any(not nonempty(term) for term in protected):
        add("protected_terms", "profile.product_identity.protected_terms", "At least one nonempty complete product phrase is required")
    forbidden = _list(profile.get("forbidden_terms"))
    variants = array(profile, "variants", "profile") if mode == "family" else []
    ids, sku_set, combos = [], set(), set()
    dimensions = _list(profile.get("variation_dimensions")) if mode == "family" else []
    if mode == "family":
        if not variants:
            add("variants_empty", "profile.variants", "A family requires supplied variants")
        if not dimensions or any(not nonempty(d) for d in dimensions) or len({str(d) for d in dimensions}) != len(dimensions):
            add("variation_dimensions", "profile.variation_dimensions", "Unique ordered variation dimensions are required")
        theme = _dict(profile.get("variation_theme"))
        if theme.get("status") != "confirmed" or not nonempty(theme.get("source_ref")) or not nonempty(theme.get("name")):
            add("variation_theme", "profile.variation_theme", "Verify the actual site's category variation theme before completion")
        parent_sku = profile.get("parent_sku")
        if parent_sku is not None:
            if not nonempty(parent_sku):
                add("sku", "profile.parent_sku", "SKU must be a nonempty string or null")
            else:
                sku_set.add(parent_sku)
    owners = [("all", profile)]
    for index, variant in enumerate(variants):
        path = "profile.variants[%d]" % index
        if not isinstance(variant, dict):
            add("variant_object", path, "Variant must be an object")
            continue
        vid = variant.get("variant_id")
        if not isinstance(vid, str) or not SAFE_ID.fullmatch(vid) or vid in ("all", "single", "parent", "media") or vid in ids:
            add("variant_id", path + ".variant_id", "IDs must be unique, filename safe, and not reserved")
        ids.append(vid if isinstance(vid, str) else "__invalid_%d" % index)
        owners.append((ids[-1], variant))
        sku = variant.get("sku")
        if sku is not None:
            if not nonempty(sku) or sku in sku_set:
                add("sku", path + ".sku", "SKU must be null or a unique nonempty string, including parent")
            else:
                sku_set.add(sku)
        attributes = _dict(variant.get("attributes"))
        if set(attributes) != set(str(d) for d in dimensions):
            add("attribute_dimensions", path + ".attributes", "Attributes must match exactly the supplied variation dimensions")
        combo = []
        for dim in dimensions:
            if not isinstance(dim, str):
                continue
            attr = _dict(attributes.get(dim))
            for key in ("value", "display", "title_value"):
                if not nonempty(attr.get(key)):
                    add("attribute_value", path + ".attributes." + dim + "." + key, "A real, nonempty attribute value is required")
            value = attr.get("value", "")
            combo.append(str(value))
            if "color" in dim.casefold() and any(re.fullmatch(r"[A-Za-z ]+\s+\d+", str(attr.get(k, ""))) for k in ("display", "title_value")):
                add("ambiguous_color", path + ".attributes." + dim, "Numbered placeholder colors need the actual color name")
        combo = tuple(combo)
        if combo in combos:
            add("duplicate_combination", path + ".attributes", "Duplicate supplied variant combination")
        combos.add(combo)

    facts, measurements, images = {}, {}, {}
    for owner_id, owner in owners:
        for key, id_key, dest in (("facts", "fact_id", facts), ("measurements", "measurement_id", measurements)):
            for index, record in enumerate(array(owner, key, "profile." + owner_id)):
                path = "profile.%s.%s[%d]" % (owner_id, key, index)
                if not isinstance(record, dict):
                    add("record_object", path, "Record must be an object")
                    continue
                rid = record.get(id_key)
                if not nonempty(rid) or rid in dest:
                    add("global_id", path + "." + id_key, "Record ID must be globally unique and nonempty")
                    continue
                dest[rid] = (owner_id, record)
                if key == "facts":
                    if not nonempty(record.get("field")) or record.get("status") not in ("confirmed", "unknown", "conflict"):
                        add("fact_shape", path, "Fact requires a field and confirmed/unknown/conflict status")
                    if record.get("status") == "confirmed" and (not nonempty(record.get("source_ref")) or record.get("value") is None or record.get("value") == ""):
                        add("fact_source", path, "Confirmed facts require an explicit value and source")
                else:
                    if record.get("subject") not in ("product", "package", "fit") or not nonempty(record.get("label")) or not nonempty(record.get("source_ref")):
                        add("measurement_metadata", path, "Measurement requires subject, dimension label, and source")
                    try:
                        display = _measurement_display(record, site)
                        if any(record.get(k) != value for k, value in display.items()):
                            add("measurement_display", path, "Display differs from deterministic conversion; run normalize")
                    except (ValueError, InvalidOperation) as error:
                        add("measurement_invalid", path, str(error))
    for owner_id, owner in owners[1:]:
        for dim, attribute in _dict(owner.get("attributes")).items():
            attr = _dict(attribute)
            mid = attr.get("measurement_id")
            if mid:
                source = measurements.get(mid) if isinstance(mid, str) else None
                if not source or source[0] not in ("all", owner_id):
                    add("attribute_measurement_scope", "profile." + owner_id + "." + dim, "Attribute cannot reference another child's measurement")
                elif any(attr.get(k) != source[1].get("display_text") for k in ("display", "title_value")):
                    add("attribute_measurement_display", "profile." + owner_id + "." + dim, "Attribute must reuse its own localized display_text")

    length_token = re.compile(r'(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)\s*[-‐‑]?\s*(centimeters?|millimeters?|meters?|inches|inch|in|cm|mm|m|feet|foot|ft|")(?![A-Za-z])', re.I)

    def scan_measurements(text, allowed_owners, path):
        matching_groups = []
        if not isinstance(text, str):
            return matching_groups
        for match in length_token.finditer(text):
            number, unit = Decimal(match[1]), UNIT_ALIASES.get(match[2].lower(), match[2].lower())
            matches, own, nominal = [], [], []
            for mid, (owner_id, measurement) in measurements.items():
                shown_unit = measurement.get("display_unit")
                if isinstance(shown_unit, str):
                    shown_unit = UNIT_ALIASES.get(shown_unit.casefold(), shown_unit.casefold())
                try:
                    same_value = Decimal(str(measurement.get("display_value"))) == number
                except InvalidOperation:
                    same_value = False
                if shown_unit == unit and same_value:
                    matches.append(mid)
                    if owner_id in allowed_owners:
                        own.append(mid)
                        if measurement.get("kind") in ("nominal", "size"):
                            nominal.append(mid)
            if site == "US" and unit != "in" and not nominal:
                add("source_unit_leak", path, "Ordinary US lengths must use normalized inches, including compact or reformatted numeric units")
            elif not own:
                if matches:
                    add("measurement_wrong_variant", path, "Registered size belongs to another child: " + match[0])
                else:
                    add("measurement_unregistered", path, "Numeric length has no matching registered measurement for this product: " + match[0])
            if own:
                matching_groups.append(set(own))
        return matching_groups

    # Package counts are facts, not lengths or arbitrary digits in materials/models.
    quantity_fields = {"quantity", "package_quantity", "unit_count", "pack_count", "number_of_items"}
    quantities = {}
    for fid, (owner_id, fact) in facts.items():
        if fact.get("field") in quantity_fields and re.fullmatch(r"[1-9]\d*", str(fact.get("value", ""))):
            quantities[fid] = (owner_id, int(fact["value"]))
    quantity_token = re.compile(r"\b(\d+)\s*[- ]?\s*(?:packs?|count|pieces?|pcs)\b|\b(?:pack|set)\s+of\s+(\d+)\b|\bquantity\s*:\s*(\d+)\b", re.I)

    def scan_quantities(text, allowed_owners, path):
        matching_groups = []
        if not isinstance(text, str):
            return matching_groups
        for match in quantity_token.finditer(text):
            number = int(next(value for value in match.groups() if value is not None))
            own = {fid for fid, (owner_id, value) in quantities.items() if owner_id in allowed_owners and value == number}
            if not own:
                code = "quantity_wrong_variant" if any(value == number for _, value in quantities.values()) else "quantity_unregistered"
                add(code, path, "Package count must match a registered quantity fact for this child: " + match[0])
            if own:
                matching_groups.append(own)
        return matching_groups

    def scope(value, path):
        if not isinstance(value, list) or not value or any(not isinstance(v, str) for v in value):
            add("scope", path, "applies_to must be ['all'] or explicit variant IDs")
            return set()
        if len(set(value)) != len(value) or ("all" in value and value != ["all"]) or (value != ["all"] and any(v not in ids for v in value)):
            add("scope", path, "Invalid, mixed, duplicate or unknown applies_to IDs")
            return set()
        return {"single"} if mode == "single" else (set(ids) if value == ["all"] else set(value))

    for index, record in enumerate(array(profile, "images", "profile")):
        path = "profile.images[%d]" % index
        if not isinstance(record, dict):
            add("image_object", path, "Image must be an object")
            continue
        image_id = record.get("image_id")
        if not nonempty(image_id) or image_id in images:
            add("image_id", path, "Image ID must be globally unique and nonempty")
            continue
        image_scope = scope(record.get("applies_to"), path + ".applies_to")
        if not nonempty(record.get("source")):
            add("image_source", path, "Image needs its actual source")
        images[image_id] = (image_scope, record)
    for owner_id, owner in owners[1:]:
        for image_id in array(owner, "image_ids", "profile." + owner_id):
            source = images.get(image_id) if isinstance(image_id, str) else None
            if not source or owner_id not in source[0]:
                add("variant_image_scope", "profile." + owner_id + ".image_ids", "Image does not belong to this child")

    def check_text(target, content, parent=False):
        path = "listing." + target
        fields = ("title", "item_highlight") if parent else TEXT_FIELDS
        for field in fields:
            value = content.get(field)
            # Empty search terms are legitimate after deduplication.
            if not isinstance(value, str) or (field != "search_terms" and not value.strip()):
                add("text_field", path + "." + field, "Expected a nonempty string (search_terms may be empty)")
                continue
            limit = limits.get(field + "_max_chars")
            if limit is not None and len(value) > limit:
                add("field_length", path + "." + field, "Length %d exceeds %d characters" % (len(value), limit))
            if field == "search_terms" and len(value.encode("utf-8")) > limits["search_terms_max_bytes"]:
                add("search_bytes", path + ".search_terms", "UTF-8 search terms exceed the configured byte budget")
        for term in protected:
            if isinstance(term, str) and term and not _contains(content.get("title", ""), term):
                add("identity_dropped", path + ".title", "Missing intact protected product phrase: " + term)
        if not parent:
            bullets = content.get("bullets")
            if not isinstance(bullets, list) or len(bullets) != limits["bullets_count"] or any(not nonempty(b) for b in _list(bullets)):
                add("bullets_shape", path + ".bullets", "Exactly five nonempty bullet strings are required")
            valid_bullets = [b for b in _list(bullets) if isinstance(b, str)]
            for index, bullet in enumerate(valid_bullets):
                label = re.fullmatch(r"【([^】]+)】\s*\S[\s\S]*", bullet)
                if not label or label[1] != label[1].upper() or not label[1].strip():
                    add("bullet_format", path + ".bullets[%d]" % index, "Use 【UPPERCASE BENEFIT LABEL】 followed by natural target-language copy; uncased scripts are allowed")
            if any(len(b) > limits["bullet_max_chars"] for b in valid_bullets) or sum(map(len, valid_bullets)) > limits["bullets_total_max_chars"]:
                add("bullets_length", path + ".bullets", "Bullet or combined editorial budget exceeded")
        for field in (("title", "item_highlight") if parent else FRONT_FIELDS + ("search_terms",)):
            value = _field(content, field)
            if isinstance(value, str):
                for term in forbidden:
                    if isinstance(term, str) and _contains(value, term):
                        add("forbidden_term", path + "." + field, "Contains a user-forbidden phrase: " + term)

    resolved = dict(resolved_listings(profile, listing))
    profile_variants = {owner_id: owner for owner_id, owner in owners[1:]}
    if mode == "family":
        listing_variants = array(listing, "variants", "listing")
        listing_ids = [v.get("variant_id") if isinstance(v, dict) else None for v in listing_variants]
        if listing_ids != ids:
            add("variant_set_order", "listing.variants", "Output must exactly match supplied IDs and order, with no omission, duplication or extra combination")
        shared = _dict(listing.get("shared_content"))
        if not isinstance(listing.get("shared_content"), dict) or any(key not in CONTENT_FIELDS for key in shared):
            add("shared_content", "listing.shared_content", "Shared content only contains bullets, description and search_terms")
        for field in CONTENT_FIELDS:
            value = shared.get(field)
            if field == "bullets":
                if not isinstance(value, list) or len(value) != limits["bullets_count"] or any(not nonempty(b) for b in _list(value)):
                    add("shared_content", "listing.shared_content.bullets", "Shared bullets must contain five complete strings")
                for index, bullet in enumerate(_list(value)):
                    scan_measurements(bullet, {"all"}, "listing.shared_content.bullets[%d]" % index)
                    scan_quantities(bullet, {"all"}, "listing.shared_content.bullets[%d]" % index)
            else:
                if not isinstance(value, str) or (field == "description" and not value.strip()):
                    add("shared_content", "listing.shared_content." + field, "Shared content requires complete string fields")
                if field == "description":
                    scan_measurements(value, {"all"}, "listing.shared_content.description")
                scan_quantities(value, {"all"}, "listing.shared_content." + field)
        parent = _dict(listing.get("parent"))
        if not isinstance(listing.get("parent"), dict):
            add("parent_missing", "listing.parent", "Family parent title and highlight are required")
        if parent.get("sku") != profile.get("parent_sku"):
            add("parent_sku", "listing.parent.sku", "Parent SKU must match input, including null")
        check_text("parent", parent, parent=True)
        for field in ("title", "item_highlight"):
            value = parent.get(field, "")
            for _, variant in owners[1:]:
                for attr in _dict(variant.get("attributes")).values():
                    for phrase in (_dict(attr).get("display"), _dict(attr).get("title_value")):
                        if isinstance(phrase, str) and _contains(value, phrase):
                            add("parent_variant_leak", "listing.parent." + field, "Contains a specific variant value: " + phrase)
            if field == "title" and isinstance(value, str) and re.search(r"(?:[$€£¥]\s*\d|\b\d+(?:\.\d+)?\s*(?:USD|EUR|GBP|dollars|pack|packs|pcs|pieces|count)\b|\b(?:pack\s+of|stock|inventory)\s*\d)", value, re.I):
                add("parent_price_quantity", "listing.parent.title", "Parent title cannot contain price, inventory or concrete pack quantity")
        template = listing.get("title_template")
        slots = []
        try:
            if not isinstance(template, str):
                raise ValueError("A title template is required")
            parsed = list(string.Formatter().parse(template))
            slots = [name for _, name, _, _ in parsed if name is not None]
            if slots != dimensions or any(spec or conv or any(c in name for c in ".[]") for _, name, spec, conv in parsed if name is not None):
                raise ValueError("Template must contain every dimension once, in order, without formatting expressions")
        except ValueError as error:
            add("title_template", "listing.title_template", str(error))
            template = None
        for index, variant in enumerate(listing_variants):
            if not isinstance(variant, dict):
                continue
            target = variant.get("variant_id")
            source = profile_variants.get(target) if isinstance(target, str) else None
            if source is None:
                continue
            path = "listing.variants[%d]" % index
            attrs = {dim: _dict(_dict(source.get("attributes")).get(dim)).get("title_value") for dim in dimensions if isinstance(dim, str)}
            if variant.get("attributes") != attrs:
                add("listing_attribute_mapping", path + ".attributes", "Listing attributes must exactly match this child's normalized title values")
            if variant.get("sku") != source.get("sku"):
                add("listing_sku", path + ".sku", "Child SKU must match input, including null")
            overrides = variant.get("content_overrides")
            if not isinstance(overrides, dict) or set(overrides) - set(CONTENT_FIELDS):
                add("content_overrides", path + ".content_overrides", "Only bullets/description/search_terms can be overridden")
            if template is not None:
                try:
                    expected = template.format_map(attrs)
                    if variant.get("title") != expected:
                        add("title_template_mismatch", path + ".title", "Title differs from the common template filled with this child's values")
                except (KeyError, ValueError, IndexError, AttributeError):
                    add("title_template", path + ".title", "Template cannot be resolved safely")
    for target, content in resolved.items():
        check_text(str(target), content)

    def check_refs(record, allowed_owners, path):
        result = {"fact_ids": [], "measurement_ids": []}
        for key, collection in (("fact_ids", facts), ("measurement_ids", measurements)):
            for rid in array(record, key, path):
                source = collection.get(rid) if isinstance(rid, str) else None
                if source is None or source[0] not in allowed_owners:
                    add("reference_scope", path + "." + key, "Reference is missing or belongs to another child: " + str(rid))
                elif key == "fact_ids" and (source[1].get("status") != "confirmed" or not nonempty(source[1].get("source_ref"))):
                    add("unconfirmed_fact", path + "." + key, "Only confirmed, sourced facts can support claims")
                else:
                    result[key].append(rid)
        return result

    claim_refs, claim_fact_refs = {}, {}
    content_targets = dict(resolved)
    if mode == "family":
        content_targets["parent"] = _dict(listing.get("parent"))
    for target, content in content_targets.items():
        allowed = {"all"} if target in ("single", "parent") else {"all", target}
        found_fields = set()
        for index, claim in enumerate(array(content, "claims", "listing." + str(target))):
            path = "listing.%s.claims[%d]" % (target, index)
            if not isinstance(claim, dict):
                add("claim_object", path, "Claim must be an object")
                continue
            field = claim.get("field")
            valid_fields = ("title", "item_highlight") if target == "parent" else FRONT_FIELDS + ("search_terms",)
            if field not in valid_fields:
                add("claim_field", path, "Claim field does not locate an applicable text field")
                continue
            found_fields.add(field)
            refs = check_refs(claim, allowed, path)
            claim_refs.setdefault((target, field), set()).update(refs["measurement_ids"])
            claim_fact_refs.setdefault((target, field), set()).update(refs["fact_ids"])
            value = _field(content, field)
            for mid in refs["measurement_ids"]:
                shown = measurements[mid][1].get("display_text")
                if not isinstance(value, str) or not isinstance(shown, str) or not _contains(value, shown):
                    add("measurement_text", path, "Text must reuse registered localized display_text for " + mid)
        required = ("title", "item_highlight") if target == "parent" else FRONT_FIELDS
        for field in required:
            if field not in found_fields:
                add("claim_missing", "listing." + str(target) + "." + field, "Front-end field requires an explicit evidence/semantic-review claim record")
        # Scan only registered specifications. This cannot detect all invented numbers.
        for field in required:
            value = _field(content, field)
            if not isinstance(value, str):
                continue
            scan_measurements(value, allowed, "listing." + str(target) + "." + field)
            quantity_groups = scan_quantities(value, allowed, "listing." + str(target) + "." + field)
            if any(not group & claim_fact_refs.get((target, field), set()) for group in quantity_groups):
                add("quantity_unreferenced", "listing." + str(target) + "." + field, "Package count needs a corresponding quantity fact reference")
            for mid, (owner_id, measurement) in measurements.items():
                shown = measurement.get("display_text")
                if owner_id in allowed and isinstance(shown, str) and _contains(value, shown) and mid not in claim_refs.get((target, field), set()):
                    # Identical numeric dimensions may need only the specifically used label's ID.
                    same_value_ids = {rid for rid, (oid, rec) in measurements.items() if oid in allowed and rec.get("display_text") == shown}
                    if not same_value_ids & claim_refs.get((target, field), set()):
                        add("measurement_unreferenced", "listing." + str(target) + "." + field, "Registered specification is present without its measurement reference")

    plan_ids, main_coverage = {}, set()

    def check_media_record(plan, path, template=False):
        applicable = scope(plan.get("applies_to"), path + ".applies_to")
        common = plan.get("applies_to") == ["all"]
        allowed = {"all"} if common or mode == "single" else ({"all"} | applicable if len(applicable) == 1 else {"all"})
        refs = check_refs(plan, allowed, path)
        for key in ("buyer_question", "selling_point", "direction", "visual_evidence", "scene_intent", "mobile_check", "production_notes"):
            if not nonempty(plan.get(key)):
                add("plan_text", path + "." + key, "Planning rationale must be a nonempty string")
        status = plan.get("status", "ready")
        if status not in ("ready", "pending"):
            add("plan_status", path + ".status", "Plan status is ready or pending")
        elif status == "pending":
            add("plan_pending", path, "This creative still lacks facts or material; retain the production note and complete before acceptance", "incomplete")
        overlay = plan.get("overlay_text")
        if not isinstance(overlay, str):
            add("overlay_text", path + ".overlay_text", "overlay_text must be a string")
            overlay = ""
        native_text = plan.get("native_text", "")
        if not isinstance(native_text, str):
            add("native_text", path + ".native_text", "native_text must be a string")
            native_text = ""
        if plan.get("role") == "main" and (overlay or native_text):
            add("main_image_text", path + ".overlay_text", "Main image must not have overlaid marketing text")
        for key, value in (("overlay_text", overlay), ("native_text", native_text)):
            length_groups = scan_measurements(value, allowed, path + "." + key)
            if any(not group & set(refs["measurement_ids"]) for group in length_groups):
                add("measurement_unreferenced", path + "." + key, "Image length needs its corresponding measurement reference")
            quantity_groups = scan_quantities(value, allowed, path + "." + key)
            if any(not group & set(refs["fact_ids"]) for group in quantity_groups):
                add("quantity_unreferenced", path + "." + key, "Image count needs a corresponding quantity fact reference")
            if not template and re.search(r"\{[^{}]+\}", value):
                add("unresolved_media_text", path + "." + key, "Resolved copy must contain actual child parameters, not template placeholders")
            for term in forbidden:
                if isinstance(term, str) and _contains(value, term):
                    add("forbidden_term", path + "." + key, "Contains a user-forbidden phrase: " + term)
        source_ids = array(plan, "source_image_ids", path)
        if not source_ids and not template and plan.get("asset_type", "image") == "image":
            add("plan_material_pending", path + ".source_image_ids", "Image source is missing; identify required material in production_notes", "incomplete")
        for image_id in source_ids:
            source = images.get(image_id) if isinstance(image_id, str) else None
            if source is None or not applicable <= source[0] or (common and source[1].get("applies_to") != ["all"]):
                add("plan_image_scope", path + ".source_image_ids", "Cannot reuse another child's or non-common material")
        body_refs = array(plan, "body_refs", path)
        if not body_refs:
            add("body_refs_empty", path + ".body_refs", "Plan must map to corresponding Listing text")
        for target in applicable:
            content = resolved.get(target, {})
            for field in body_refs:
                if field not in FRONT_FIELDS or not isinstance(_field(content, field), str):
                    add("body_ref", path + ".body_refs", "Body reference must locate existing front-end text for every applicable child")
            for mid in refs["measurement_ids"]:
                shown = measurements[mid][1].get("display_text")
                if not any(mid in claim_refs.get((target, field), set()) and isinstance(_field(content, field), str)
                           and _contains(_field(content, field), shown or "") for field in body_refs if isinstance(field, str)):
                    add("plan_body_measurement", path, "Image specification must also appear and be referenced in the applicable Listing body")
            for fid in set(refs["fact_ids"]) & set(quantities):
                number = quantities[fid][1]
                if not any(fid in claim_fact_refs.get((target, field), set()) and any(
                        int(next(v for v in match.groups() if v is not None)) == number
                        for match in quantity_token.finditer(_field(content, field) or ""))
                        for field in body_refs if field in FRONT_FIELDS):
                    add("plan_body_quantity", path, "Image package quantity must also appear with its fact reference in the applicable body")
        if plan.get("role") != "main":
            for mid in refs["measurement_ids"]:
                shown = measurements[mid][1].get("display_text")
                if not isinstance(shown, str) or not (_contains(overlay, shown) or _contains(native_text, shown)):
                    add("plan_measurement_text", path, "Specification must reuse localized display_text in overlay_text or native_text")

    for plan_key in ("image_plan", a_plus_key):
        plans = array(listing, plan_key, "listing")
        if not plans:
            add("plan_empty", "listing." + plan_key, "A complete image/A+ plan is required")
        if plan_key == "image_plan" and not any(isinstance(p, dict) and p.get("role") == "main" for p in plans):
            add("main_image_missing", "listing.image_plan", "A main-image plan is required")
        for index, plan in enumerate(plans):
            path = "listing.%s[%d]" % (plan_key, index)
            if not isinstance(plan, dict):
                add("plan_object", path, "Plan must be an object")
                continue
            pid = plan.get("plan_id")
            if not nonempty(pid) or pid in plan_ids:
                add("plan_id", path, "Plan IDs must be nonempty and globally unique")
            else:
                plan_ids[pid] = plan
            applicable = scope(plan.get("applies_to"), path + ".applies_to")
            if plan_key == "image_plan" and plan.get("role") == "main":
                main_coverage.update(applicable)
            if plan.get("role") not in (("main", "secondary") if plan_key == "image_plan" else ("aplus",)):
                add("plan_role", path + ".role", "Role does not match its plan collection")
            if plan_key == a_plus_key:
                if plan.get("asset_type") not in ("image", "text") or not nonempty(plan.get("module")):
                    add("aplus_asset", path, "A+ needs its module label and explicit image/text asset_type")
            elif plan.get("asset_type", "image") != "image":
                add("plan_asset", path, "Main/secondary slots must be image creatives")
            bindings = plan.get("variant_bindings", [])
            if not isinstance(bindings, list):
                add("media_bindings", path + ".variant_bindings", "Bindings must be an array")
                bindings = []
            check_media_record(plan, path, template=bool(bindings))
            if bindings:
                if mode != "family" or plan.get("applies_to") != ["all"]:
                    add("media_binding_scope", path, "Only a shared family template can have child bindings")
                binding_ids = [b.get("variant_id") if isinstance(b, dict) else None for b in bindings]
                if binding_ids != ids:
                    add("media_binding_coverage", path + ".variant_bindings", "Bindings must cover exactly all input children in order")
                fields = {"source_image_ids", "fact_ids", "measurement_ids", "body_refs", "overlay_text",
                          "native_text", "direction", "visual_evidence", "production_notes", "status"}
                required = {"source_image_ids", "fact_ids", "measurement_ids", "body_refs", "overlay_text"}
                for binding_index, binding in enumerate(bindings):
                    binding_path = path + ".variant_bindings[%d]" % binding_index
                    if not isinstance(binding, dict):
                        add("media_binding", binding_path, "Binding must be an object")
                        continue
                    if set(binding) - fields - {"variant_id"} or not required <= set(binding):
                        add("media_binding", binding_path, "Provide source/fact/measurement/body references and final overlay text; do not change identity, role or scope")
                    vid = binding.get("variant_id")
                    if not isinstance(vid, str) or vid not in ids:
                        continue
                    bound = {key: value for key, value in plan.items() if key != "variant_bindings"}
                    bound.update({key: value for key, value in binding.items() if key in fields})
                    bound["applies_to"] = [vid]
                    check_media_record(bound, binding_path)

    if main_coverage != (set(ids) if mode == "family" else {"single"}):
        add("main_image_coverage", "listing.image_plan", "Every supplied child needs an applicable main-image plan")
    check_media_sets(profile, listing, plan_ids, add)

    if qa is not None:
        if not isinstance(qa, dict):
            add("qa_object", "qa", "QA must be an object")
        elif qa.get("site") != site:
            add("qa_site", "qa.site", "QA site must match profile")
        elif site != "US":
            if qa.get("status") != "skipped" or qa.get("reason_code") != "rufus_us_only" or qa.get("qa_pairs") != []:
                add("qa_non_us", "qa", "Non-US must retain the explicit skipped record with an empty qa_pairs array")
        else:
            if qa.get("status") == "unavailable":
                if not nonempty(qa.get("reason")) or any(qa.get(key) != [] for key in ("requested_keywords", "qa_pairs", "question_reviews")):
                    add("qa_unavailable_shape", "qa", "Unavailable QA requires the real reason and empty requested_keywords/qa_pairs/question_reviews arrays")
                else:
                    add("qa_unavailable", "qa", "US QA collection is unavailable; retain the reason and complete collection before final acceptance", "incomplete")
                return issues
            if qa.get("status") != "completed":
                add("qa_status", "qa.status", "US QA must be completed or the deliverable remains incomplete")
            requested = array(qa, "requested_keywords", "qa")
            if not requested or any(not nonempty(keyword) for keyword in requested):
                add("qa_requested_keywords", "qa.requested_keywords", "Retain the actual nonempty keyword strings used for collection")
            questions = set()
            for pair in array(qa, "qa_pairs", "qa"):
                if isinstance(pair, dict):
                    for question in _list(pair.get("questions")):
                        if isinstance(question, str):
                            questions.add((pair.get("keyword"), question))
            reviewed_questions = set()
            for index, review in enumerate(array(qa, "question_reviews", "qa")):
                path = "qa.question_reviews[%d]" % index
                if not isinstance(review, dict):
                    add("qa_review_object", path, "Question review must be an object")
                    continue
                pair = (review.get("keyword"), review.get("question"))
                if any(not isinstance(v, str) for v in pair):
                    add("qa_question", path, "Review requires original keyword and question strings")
                    continue
                if pair not in questions:
                    add("qa_provenance", path, "Reviewed question must come from the captured original response")
                if pair[0] not in requested:
                    quarantined = review.get("relevance") in ("irrelevant", "uncertain") and review.get("disposition") == "excluded"
                    add("qa_seed_mismatch", path, "Response seed differs from requested keywords; preserve and quarantine it",
                        "warning" if quarantined else "error")
                reviewed_questions.add(pair)
                relevance, disposition = review.get("relevance"), review.get("disposition")
                if relevance not in ("relevant", "irrelevant", "uncertain") or disposition not in ("answered", "unsupported", "excluded"):
                    add("qa_disposition", path, "Invalid relevance or disposition")
                if disposition == "answered" and (relevance != "relevant" or not _list(review.get("fact_ids"))):
                    add("qa_unsupported_answer", path, "Only relevant questions with product evidence may be answered")
                applicable = scope(review.get("applies_to"), path + ".applies_to")
                allowed = {"all"} if review.get("applies_to") == ["all"] or len(applicable) != 1 else {"all"} | applicable
                check_refs({"fact_ids": review.get("fact_ids"), "measurement_ids": []}, allowed, path)
            if reviewed_questions != questions:
                add("qa_review_coverage", "qa.question_reviews", "Every captured question needs a relevance/disposition review")
    return issues


def make_review_template(profile_path, listing_path, qa_path=None):
    profile, listing = load_json(profile_path), load_json(listing_path)
    policy = load_json(POLICY_PATH)
    targets = ["single"] if profile.get("listing_mode", "single") != "family" else ["parent"] + [v["variant_id"] for v in profile["variants"]]
    records = [{"target": target, "check": check, "status": "pending", "evidence": ""}
               for target in targets for check in policy["semantic_checks"]]
    records += [{"target": "media", "check": check, "status": "pending", "evidence": ""} for check in policy["media_checks"]]
    return {"schema_version": "2.1", "fingerprints": file_fingerprints(profile_path, listing_path, qa_path),
            "keyword_fingerprints": keyword_review_fingerprints(Path(listing_path).parent),
            "records": records,
            "limitations": "Review actual copy, facts, variants, images and keyword_usage against 03_keyword_decisions/05_title_keywords; do not mechanically mark pass. Review actual used keywords and related intents, not every unused or excluded term. Check full-intent use, paraphrases, backend word order and truthful negative mentions; references verify scope, not semantic truth."}


def keyword_review_fingerprints(run_dir):
    return {name: hashlib.sha256((Path(run_dir) / name).read_bytes()).hexdigest() if (Path(run_dir) / name).exists() else None
            for name in ("02_kw_raw.json", "03_keyword_decisions.json", "05_title_keywords.json")}


def current_keyword_stage(run_dir):
    spec = importlib.util.spec_from_file_location("listing_keyword_quality", Path(__file__).with_name("keyword_quality.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_run(Path(run_dir))


def validate_bundle(profile, listing, qa=None, review=None, backend=None, fingerprints=None, keywords=None):
    issues = check_local(profile, listing, qa)

    def add(code, path, message, severity="error"):
        issues.append({"severity": severity, "code": code, "path": path, "message": message})

    local_errors = sum(i["severity"] == "error" for i in issues)
    local_status = "failed" if local_errors else "incomplete" if any(i["severity"] == "incomplete" for i in issues) else "passed"
    if qa is None:
        add("qa_missing", "qa", "QA evidence or explicit non-US skipped file is missing", "incomplete")
    expected = load_json(POLICY_PATH)
    targets = ["single"] if _dict(profile).get("listing_mode", "single") != "family" else ["parent"] + [v.get("variant_id") for v in _list(profile.get("variants")) if isinstance(v, dict)]
    required = {(str(target), check) for target in targets for check in expected["semantic_checks"]}
    required |= {("media", check) for check in expected["media_checks"]}
    semantic_start = len(issues)
    if review is None:
        add("review_missing", "semantic", "Independent semantic review is missing", "incomplete")
    elif not isinstance(review, dict):
        add("review_invalid", "semantic", "Semantic review must be an object")
    else:
        if fingerprints is None or review.get("fingerprints") != fingerprints:
            add("review_stale", "semantic.fingerprints", "Review is missing current source-file fingerprints", "incomplete")
        if keywords is not None and keywords.get("status") == "passed":
            keyword_bound = {name: keywords.get("fingerprints", {}).get(name) for name in ("02_kw_raw.json", "03_keyword_decisions.json", "05_title_keywords.json")}
            recorded_keywords = review.get("keyword_fingerprints")
            if not isinstance(recorded_keywords, dict) or any(name not in recorded_keywords or recorded_keywords[name] != value for name, value in keyword_bound.items()):
                add("review_keywords_stale", "semantic.keyword_fingerprints", "Keyword-usage review is not bound to current keyword decisions and placements", "incomplete")
        seen = set()
        for index, record in enumerate(_list(review.get("records"))):
            path = "semantic.records[%d]" % index
            if not isinstance(record, dict):
                add("review_record", path, "Review record must be an object")
                continue
            key = (str(record.get("target")), str(record.get("check")))
            if key in seen or key not in required:
                add("review_target", path, "Duplicate or unexpected semantic target/check")
            seen.add(key)
            status = record.get("status")
            if status == "pending":
                add("review_pending", path, "Review still pending", "incomplete")
            elif status == "fail":
                add("review_failed", path, "Semantic review found a failure")
            elif status not in ("pass", "not_applicable"):
                add("review_status", path, "Invalid semantic review status")
            if not isinstance(record.get("evidence"), str) or not record["evidence"].strip():
                add("review_evidence", path, "Pass needs evidence and not_applicable needs a reason", "incomplete")
        if seen != required:
            add("review_coverage", "semantic.records", "Semantic review is missing one or more targets/checks", "incomplete")
    semantic_issues = issues[semantic_start:]
    semantic_status = "failed" if any(i["severity"] == "error" for i in semantic_issues) else "incomplete" if semantic_issues else "passed"
    backend_start = len(issues)
    try:
        payloads = {p["target"]: p for p in build_payloads(profile, listing)}
    except (ValueError, TypeError, AttributeError):
        payloads = {}
        add("payload_invalid", "backend", "Cannot project malformed content to backend payloads")
    if backend is None:
        add("backend_missing", "backend", "Backend validation is missing", "incomplete")
    elif not isinstance(backend, dict):
        add("backend_invalid", "backend", "Backend validation must be an object")
    else:
        seen = set()
        for index, record in enumerate(_list(backend.get("records"))):
            path = "backend.records[%d]" % index
            if not isinstance(record, dict):
                add("backend_record", path, "Backend record must be an object")
                continue
            target = record.get("target")
            if not isinstance(target, str) or target not in payloads or target in seen:
                add("backend_target", path, "Unexpected or duplicate backend target; parent is never submitted")
                continue
            seen.add(target)
            if record.get("payload_sha256") != payloads[target]["payload_sha256"]:
                add("backend_stale", path, "Backend payload fingerprint is missing or stale", "incomplete")
            response = record.get("response")
            if record.get("exit_code") != 0 or type(record.get("exit_code")) is not int or not isinstance(response, dict) or response.get("ok") is not True or response.get("errors") != []:
                add("backend_failed", path, "Backend needs exit_code=0, JSON ok=true and errors=[]")
        if seen != set(payloads) or not payloads:
            add("backend_coverage", "backend.records", "Every sellable output requires its own current backend record", "incomplete")
    backend_issues = issues[backend_start:]
    backend_status = "failed" if any(i["severity"] == "error" for i in backend_issues) else "incomplete" if backend_issues else "passed"
    if keywords is None:
        keywords = {"status": "incomplete", "issues": [{"severity": "incomplete", "code": "keyword_audit_missing", "path": "keywords", "message": "Missing current keyword audit; legacy keyword files are not evidence of a completed review"}]}
    else:
        keywords = copy.deepcopy(keywords)
    if keywords.get("status") == "passed":
        bound = keywords.get("fingerprints", {})
        for source, key in (("01_product_profile.json", "profile_sha256"), ("07_listing.json", "listing_sha256"), ("06_qa.json", "qa_sha256")):
            if fingerprints is None or bound.get(source) != fingerprints.get(key):
                keywords["status"] = "incomplete"
                keywords.setdefault("issues", []).append({"severity": "incomplete", "code": "keyword_bundle_mismatch", "path": source, "message": "Keyword audit is not bound to the product, Listing or QA used by this validation"})
    issues.extend(keywords.get("issues", []))
    if keywords.get("status") != "passed" and not keywords.get("issues"):
        add("keyword_audit_incomplete", "keywords", "Keyword audit has not passed", "incomplete")
    status = "failed" if any(i["severity"] == "error" for i in issues) else "incomplete" if any(i["severity"] == "incomplete" for i in issues) else "passed"
    return {"schema_version": "2.1", "status": status, "fingerprints": fingerprints,
            "evidence_fingerprints": {"review_sha256": canonical_sha256(review) if review is not None else None,
                                      "backend_sha256": canonical_sha256(backend) if backend is not None else None,
                                      "keywords_sha256": canonical_sha256(keywords)},
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "local": {"status": local_status, "error_count": local_errors},
            "semantic": {"status": semantic_status}, "backend": {"status": backend_status},
            "keywords": keywords,
            "issues": issues, "limitations": "Automated checks cover structure, registered values and reference scope; semantic review covers language, labels, factual truth, category eligibility and visual claims."}


def run_backend(profile, listing, cli=None, timeout=120, config=None):
    """Call only CLI validate for each sellable payload; never print raw process IO."""
    issues = check_local(profile, listing)
    if any(issue["severity"] == "error" for issue in issues):
        return {"schema_version": "2.1", "status": "failed", "issues": issues, "records": []}
    records = []
    for payload in build_payloads(profile, listing):
        with tempfile.TemporaryDirectory(prefix="listing-validate-") as directory:
            path = Path(directory) / payload["filename"]
            atomic_write_json(path, payload["payload"])
            record = {"target": payload["target"], "payload_sha256": payload["payload_sha256"]}
            record.update(backend_cli.run_cli("validate", site=profile["site"], listing_file=path,
                                              cli=cli, config=config, timeout=timeout))
            records.append(record)
    return {"schema_version": "2.1", "records": records}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("normalize", "check", "prepare", "review-template", "backend"):
        command = commands.add_parser(name)
        command.add_argument("--profile", required=True)
        if name != "normalize":
            command.add_argument("--listing", required=True)
        if name in ("check", "review-template"):
            command.add_argument("--qa")
        if name == "check":
            command.add_argument("--review")
            command.add_argument("--backend")
        if name == "backend":
            command.add_argument("--cli", help="Optional CLI path; defaults to the bundled platform executable")
            command.add_argument("--config", help="Optional config path; defaults to this Skill's config.json")
            command.add_argument("--timeout", type=float, default=120)
        if name == "prepare":
            command.add_argument("--output-dir", required=True)
        else:
            command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        profile = load_json(args.profile)
        listing = load_json(args.listing) if args.command != "normalize" else None
        if args.command == "normalize":
            atomic_write_json(args.output, normalize_profile(profile))
            print("normalized")
            return 0
        if args.command == "review-template":
            atomic_write_json(args.output, make_review_template(args.profile, args.listing, args.qa))
            print("pending semantic review template written")
            return 0
        if args.command == "check":
            result = validate_bundle(profile, listing, load_json(args.qa) if args.qa else None,
                                     load_json(args.review) if args.review else None,
                                     load_json(args.backend) if args.backend else None,
                                     file_fingerprints(args.profile, args.listing, args.qa),
                                     keywords=current_keyword_stage(Path(args.listing).parent))
            atomic_write_json(args.output, result)
            print(result["status"])
            return 0 if result["status"] == "passed" else 1
        issues = check_local(profile, listing)
        if any(i["severity"] == "error" for i in issues):
            result = {"status": "failed", "issues": issues, "records": []}
            path = Path(args.output_dir) / "manifest.json" if args.command == "prepare" else args.output
            atomic_write_json(path, result)
            print("failed: correct local issues before payload preparation/backend validation")
            return 1
        if args.command == "prepare":
            payloads = build_payloads(profile, listing)
            for payload in payloads:
                atomic_write_json(Path(args.output_dir) / payload["filename"], payload["payload"])
            atomic_write_json(Path(args.output_dir) / "manifest.json", {"schema_version": "2.1", "status": "prepared",
                              "fingerprints": file_fingerprints(args.profile, args.listing),
                              "records": [{k: v for k, v in p.items() if k != "payload"} for p in payloads]})
            print("prepared %d sellable payloads" % len(payloads))
            return 0
        result = run_backend(profile, listing, args.cli, timeout=args.timeout, config=args.config)
        atomic_write_json(args.output, result)
        valid = bool(result["records"]) and all(r["exit_code"] == 0 and isinstance(r["response"], dict) and r["response"].get("ok") is True and r["response"].get("errors") == [] for r in result["records"])
        print("backend passed" if valid else "backend failed")
        return 0 if valid else 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        # Do not print user file contents, environment values, or raw CLI exception IO.
        print("error: %s; inspect input JSON, units, required fields, and paths" % type(error).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
