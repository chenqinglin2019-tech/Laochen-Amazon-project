#!/usr/bin/env python3
"""Select external design references without importing their visual assets.

The index records user-supplied comparison boards by absolute external path and
SHA-256 only.  It intentionally never copies a sample product, its on-image
copy, CTA, brand, or source pixels into this skill.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # Windows uses msvcrt in _selection_lock.
    fcntl = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "assets" / "layouts" / "style_reference_index.json"
DEFAULT_PROFILES = ROOT / "assets" / "layouts" / "style_reference_profiles.json"
SIGNAL_FIELDS = ("product_category", "image_intent", "composition", "lighting")
DEFAULT_WEIGHTS = {
    # Category has the highest weight so a design board showing a look-alike
    # product cannot win over a better-fitting use case just by resemblance.
    "product_category": 6.0,
    "image_intent": 5.0,
    "composition": 4.0,
    "lighting": 3.0,
}
MISSING_SIGNAL = "__not_provided__"
TAG_ALIASES = {
    "home_decor": "home_decor",
    "home_decorator": "home_decor",
    "home_decoration": "home_decor",
    "家居装饰": "home_decor",
    "家居摆件": "home_decor",
    "动物摆件": "animal_decor",
    "beauty": "beauty_cosmetic",
    "美妆": "beauty_cosmetic",
    "travel": "travel_gear",
    "旅行": "travel_gear",
    "travel_gear": "travel_gear",
    "tool": "power_tool",
    "工具": "power_tool",
    "editorial": "editorial_hero",
    "编辑风格": "editorial_hero",
    "场景留白": "scene_whitespace",
    "细节展示": "visual_detail",
    "细节标注": "detail_callout",
    "暖色室内": "warm_interior",
    "暗色影棚": "low_key",
}
CATEGORY_KEYWORDS = (
    ("home_decor", ("home decor", "home-decor", "decoration", "decor", "figurine", "ornament", "摆件", "装饰", "家居")),
    ("power_tool", ("chainsaw", "drill", "saw", "power tool", "工具", "电钻", "电锯")),
    ("beauty_cosmetic", ("skincare", "cosmetic", "concealer", "makeup", "beauty", "护肤", "美妆", "遮瑕")),
    ("travel_gear", ("suitcase", "luggage", "carry-on", "travel bag", "行李箱", "旅行箱")),
    ("audio_electronics", ("headphone", "earphone", "speaker", "耳机", "音箱")),
    ("cookware", ("wok", "pan", "cookware", "锅", "炊具")),
    ("bedding", ("bedding", "duvet", "bed sheet", "床品", "被套")),
    ("drinkware", ("water bottle", "tumbler", "drinkware", "水瓶", "保温杯")),
    ("footwear", ("running shoe", "sneaker", "shoe", "跑鞋", "鞋")),
    ("apparel", ("jacket", "dress", "apparel", "服装", "外套", "裙")),
    ("pet_accessory", ("litter mat", "cat litter", "pet accessory", "猫砂", "宠物")),
    ("animal_decor", ("rabbit", "bunny", "animal figure", "兔子", "兔")),
)
INTENT_KEYWORDS = (
    ("scene_whitespace", ("whitespace", "left blank", "negative space", "留白", "左侧空", "左侧留")),
    ("detail_callout", ("callout", "annotation", "标注", "细节框")),
    ("feature_detail", ("feature detail", "feature", "产品细节", "功能细节")),
    ("visual_detail", ("visible detail", "visual detail", "detail", "细节", "可见")),
    ("editorial_hero", ("editorial", "编辑", "质感")),
    ("lifestyle_hero", ("lifestyle", "scene", "hero", "场景", "主图")),
)
CANONICAL_INTENT_TAGS = frozenset({
    "action_hero", "benefit_communication", "celebration_story", "condition_story",
    "detail_callout", "editorial_hero", "feature_detail", "gift_lifestyle",
    "how_to", "kit_overview", "lifestyle_hero", "scene_whitespace", "visual_detail",
})


class ReferenceIndexError(ValueError):
    """Raised when a reference index or profile is unsafe to use."""


def prepare_design_briefs(manifest, base, selected):
    """V5 executable design adapter; older selection APIs remain unchanged."""
    from lc_reference_design import prepare_design_briefs as compile_briefs
    return compile_briefs(manifest, base, selected)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReferenceIndexError(f"Cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReferenceIndexError(f"JSON root must be an object: {path}")
    return value


def _tag_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _normalise_tag(value: str) -> str:
    normalized = "_".join(value.strip().lower().replace("-", " ").split())
    return TAG_ALIASES.get(normalized, normalized)


def _context_tags(value: Any, label: str, *, required: bool = False) -> list[str]:
    """Accept a single tag or a tag list and return stable, normalized tags."""
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    elif value is None and not required:
        return [MISSING_SIGNAL]
    else:
        raise ReferenceIndexError(f"product_context.{label} must be a nonempty string or string list")
    if not values or all(isinstance(item, str) and not item.strip() for item in values):
        if not required:
            return [MISSING_SIGNAL]
        raise ReferenceIndexError(f"product_context.{label} must be a nonempty string or string list")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ReferenceIndexError(f"product_context.{label} must be a nonempty string or string list")
    return sorted(set(_normalise_tag(item) for item in values))


def _infer_tags(
    text: str, vocabulary: tuple[tuple[str, tuple[str, ...]], ...], *, multiple: bool = False,
) -> list[str]:
    normalized = text.casefold()
    matches: list[str] = []
    for tag, keywords in vocabulary:
        if any(keyword in normalized for keyword in keywords):
            matches.append(tag)
    return matches if multiple else matches[:1]


def _intent_context_tags(value: Any, product_context: dict[str, Any]) -> tuple[list[str], str]:
    """Keep canonical intent tags, but normalize a natural-language selling job."""
    direct = _context_tags(value, "intents")
    if direct != [MISSING_SIGNAL] and all(tag in CANONICAL_INTENT_TAGS for tag in direct):
        return direct, "provided"
    parts: list[str] = []
    if isinstance(value, str):
        parts.append(value)
    elif isinstance(value, list):
        parts.extend(item for item in value if isinstance(item, str))
    if direct == [MISSING_SIGNAL] or not parts:
        parts.extend(
            item for item in (
                product_context.get("selling_job"), product_context.get("job_id"),
                product_context.get("image_intent"),
            ) if isinstance(item, str)
        )
        source = "selling_job_keyword"
    else:
        source = "intents_keyword"
    inferred = _infer_tags(" ".join(parts), INTENT_KEYWORDS, multiple=True)
    if inferred:
        return inferred, source
    return ([MISSING_SIGNAL] if direct == [MISSING_SIGNAL] else direct), "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_index(index: dict[str, Any]) -> list[str]:
    """Return deterministic validation errors without reading external files."""
    errors: list[str] = []
    if index.get("schema_version") != 1:
        errors.append("INDEX_SCHEMA_VERSION_INVALID")
    if index.get("asset_policy") != "external_path_and_hash_only":
        errors.append("INDEX_ASSET_POLICY_INVALID")
    refs = index.get("references")
    if not isinstance(refs, list) or not refs:
        return errors + ["INDEX_REFERENCES_REQUIRED"]

    seen: set[str] = set()
    for position, reference in enumerate(refs):
        prefix = f"REFERENCE_{position}"
        if not isinstance(reference, dict):
            errors.append(f"{prefix}_MUST_BE_OBJECT")
            continue
        identifier = reference.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{prefix}_ID_REQUIRED")
        elif identifier in seen:
            errors.append(f"REFERENCE_ID_DUPLICATE:{identifier}")
        else:
            seen.add(identifier)
        external_path = reference.get("external_path")
        if not isinstance(external_path, str) or not Path(external_path).is_absolute():
            errors.append(f"REFERENCE_EXTERNAL_PATH_MUST_BE_ABSOLUTE:{identifier}")
        digest = reference.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            errors.append(f"REFERENCE_SHA256_INVALID:{identifier}")
        if reference.get("source_mode") != "external_reference_only":
            errors.append(f"REFERENCE_SOURCE_MODE_INVALID:{identifier}")
        if reference.get("sample_asset_copied") is not False:
            errors.append(f"REFERENCE_ASSET_COPY_FORBIDDEN:{identifier}")
        if not isinstance(reference.get("visual_observation"), str) or not reference["visual_observation"].strip():
            errors.append(f"REFERENCE_VISUAL_OBSERVATION_REQUIRED:{identifier}")
        for field in SIGNAL_FIELDS:
            if not _tag_list(reference.get(field)):
                errors.append(f"REFERENCE_{field.upper()}_REQUIRED:{identifier}")
    return errors


def verify_external_sources(index: dict[str, Any]) -> list[str]:
    """Verify path + hash provenance; this never copies external inputs."""
    errors: list[str] = []
    for reference in index.get("references", []):
        if not isinstance(reference, dict):
            continue
        identifier = str(reference.get("id", "unknown"))
        path_value = reference.get("external_path")
        if not isinstance(path_value, str):
            continue
        path = Path(path_value)
        if not path.is_file():
            errors.append(f"REFERENCE_SOURCE_MISSING:{identifier}")
        elif _sha256(path) != reference.get("sha256"):
            errors.append(f"REFERENCE_SOURCE_HASH_MISMATCH:{identifier}")
    return errors


def validate_profiles(profiles: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if profiles.get("schema_version") != 1:
        errors.append("PROFILE_SCHEMA_VERSION_INVALID")
    values = profiles.get("profiles")
    if not isinstance(values, list) or not values:
        return errors + ["PROFILES_REQUIRED"]
    seen: set[str] = set()
    for position, profile in enumerate(values):
        prefix = f"PROFILE_{position}"
        if not isinstance(profile, dict):
            errors.append(f"{prefix}_MUST_BE_OBJECT")
            continue
        identifier = profile.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{prefix}_ID_REQUIRED")
        elif identifier in seen:
            errors.append(f"PROFILE_ID_DUPLICATE:{identifier}")
        else:
            seen.add(identifier)
        signals = profile.get("signals")
        if not isinstance(signals, dict):
            errors.append(f"PROFILE_SIGNALS_REQUIRED:{identifier}")
            continue
        for field in SIGNAL_FIELDS:
            if not _tag_list(signals.get(field)):
                errors.append(f"PROFILE_{field.upper()}_REQUIRED:{identifier}")
        maximum = profile.get("max_auxiliary", 2)
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0 or maximum > 2:
            errors.append(f"PROFILE_MAX_AUXILIARY_INVALID:{identifier}")
        threshold = profile.get("minimum_score", 1)
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or threshold < 0:
            errors.append(f"PROFILE_MINIMUM_SCORE_INVALID:{identifier}")
    return errors


def _profile_by_id(profiles: dict[str, Any], profile_id: str) -> dict[str, Any]:
    for profile in profiles.get("profiles", []):
        if profile.get("id") == profile_id:
            return profile
    raise ReferenceIndexError(f"Unknown reference profile: {profile_id}")


def _automatic_profile(product_context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    """Build a neutral scoring profile from project context, never a named preset.

    Product words supply only a small, auditable category fallback when a legacy
    project has no taxonomy. They are never matched to the sample product.
    """
    if not isinstance(product_context, dict):
        raise ReferenceIndexError("product_context must be an object")
    product = product_context.get("product")
    if not isinstance(product, str) or not product.strip():
        raise ReferenceIndexError("product_context.product must be nonempty text")
    category = _context_tags(product_context.get("category"), "category")
    category_source = "provided"
    if category == [MISSING_SIGNAL]:
        category = _infer_tags(product, CATEGORY_KEYWORDS) or [MISSING_SIGNAL]
        category_source = "product_keyword" if category != [MISSING_SIGNAL] else "unknown"
    intents, intent_source = _intent_context_tags(product_context.get("intents"), product_context)
    composition = _context_tags(product_context.get("composition"), "composition")
    lighting = _context_tags(
        product_context.get("lighting", product_context.get("color_lighting")), "lighting"
    )
    related = _context_tags(product_context.get("related_categories"), "related_categories")
    if related == [MISSING_SIGNAL]:
        related = []
    maximum = product_context.get("max_auxiliary", 2)
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0 or maximum > 2:
        raise ReferenceIndexError("product_context.max_auxiliary must be an integer from 0 to 2")
    signals = {
        "product_category": category,
        "image_intent": intents,
        "composition": composition,
        "lighting": lighting,
    }
    basis = [field for field, values in signals.items() if values != [MISSING_SIGNAL]]
    minimum_dimensions = 2 if len(basis) >= 2 else 1
    profile = {
        "id": "automatic_context",
        "signals": signals,
        "related_product_categories": related,
        "max_auxiliary": maximum,
        "minimum_score": 1,
        "minimum_matched_dimensions": minimum_dimensions,
    }
    public_context = {
        "product": product.strip(),
        "category": [] if category == [MISSING_SIGNAL] else category,
        "intents": [] if intents == [MISSING_SIGNAL] else intents,
        "composition": [] if composition == [MISSING_SIGNAL] else composition,
        "lighting": [] if lighting == [MISSING_SIGNAL] else lighting,
    }
    if related:
        public_context["related_categories"] = related
    return profile, public_context, {"category": category_source, "intents": intent_source}


def _validate_saved_selection(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if value.get("schema_version") != 1:
        errors.append("SELECTION_SCHEMA_VERSION_INVALID")
    if value.get("selection_status") == "needs_input":
        if value.get("primary") is not None or value.get("auxiliaries") not in ([], None):
            errors.append("SELECTION_NEEDS_INPUT_MUST_NOT_HAVE_CANDIDATES")
        if not isinstance(value.get("needs_input"), list) or not value["needs_input"]:
            errors.append("SELECTION_NEEDS_INPUT_REASON_REQUIRED")
        return errors
    primary = value.get("primary")
    if not isinstance(primary, dict):
        errors.append("SELECTION_PRIMARY_REQUIRED")
    auxiliaries = value.get("auxiliaries")
    if not isinstance(auxiliaries, list) or len(auxiliaries) > 2:
        errors.append("SELECTION_AUXILIARIES_INVALID")
    candidates = ([primary] if isinstance(primary, dict) else []) + (
        auxiliaries if isinstance(auxiliaries, list) else []
    )
    for candidate in candidates:
        identifier = candidate.get("id") if isinstance(candidate, dict) else None
        if not isinstance(candidate, dict):
            errors.append("SELECTION_CANDIDATE_INVALID")
            continue
        if not isinstance(identifier, str) or not identifier:
            errors.append("SELECTION_CANDIDATE_ID_REQUIRED")
        if not isinstance(candidate.get("external_path"), str) or not Path(candidate["external_path"]).is_absolute():
            errors.append(f"SELECTION_CANDIDATE_PATH_INVALID:{identifier}")
        digest = candidate.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            errors.append(f"SELECTION_CANDIDATE_SHA256_INVALID:{identifier}")
    return errors


@contextlib.contextmanager
def _selection_lock(selection_path: Path) -> Iterator[None]:
    """Serialize the complete selection read/select/commit transaction."""
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = selection_path.with_name(f".{selection_path.name}.lock")
    # Keep this lock file rather than unlinking it after release: a late opener
    # must lock the same inode as any process already waiting on it.
    with lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:  # pragma: no cover - exercised on Windows hosts.
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            while True:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - exercised on Windows hosts.
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _fsync_directory(path: Path) -> None:
    """Best-effort directory sync after an already-synced atomic replacement."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Some filesystems cannot fsync directories; the file itself was synced.
        pass
    finally:
        os.close(descriptor)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    """Durably replace JSON without sharing a temporary name between writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _candidate_source_errors(selection: dict[str, Any]) -> list[str]:
    """Check only chosen sources so optional style selection remains fast."""
    errors: list[str] = []
    candidates = [selection.get("primary")] + list(selection.get("auxiliaries", []))
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        identifier = str(candidate.get("id", "unknown"))
        path_value = candidate.get("external_path")
        if not isinstance(path_value, str) or not Path(path_value).is_file():
            errors.append(f"REFERENCE_SOURCE_MISSING:{identifier}")
        elif _sha256(Path(path_value)) != candidate.get("sha256"):
            errors.append(f"REFERENCE_SOURCE_HASH_MISMATCH:{identifier}")
    return errors


def _needs_input_selection(
    public_context: dict[str, Any], inference: dict[str, str], index_path: Path, reasons: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "selection_status": "needs_input",
        "selection_mode": "automatic_context",
        "selection_context": public_context,
        "inference": inference,
        "selection_basis": [
            key for key in ("product_category", "image_intent", "composition", "lighting")
            if public_context.get({
                "product_category": "category", "image_intent": "intents",
                "composition": "composition", "lighting": "lighting",
            }[key])
        ],
        "primary": None,
        "auxiliaries": [],
        "needs_input": sorted(set(reasons)),
        "index_provenance": {
            "index_path": str(index_path.resolve()),
            "index_sha256": _sha256(index_path),
            "asset_policy": "external_path_and_hash_only",
        },
        "source_policy": {
            "external_path_and_hash_only": True,
            "copy_sample_product_pixels": False,
            "copy_sample_copy_or_cta": False,
            "copy_sample_brand_or_logo": False,
        },
    }


def _score_reference(reference: dict[str, Any], profile: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    signals = profile["signals"]
    related = profile.get("related_product_categories", [])
    breakdown: dict[str, Any] = {}
    score = 0.0
    matched_dimensions = 0
    reasons: list[str] = []
    for field in SIGNAL_FIELDS:
        requested = set(signals[field])
        observed = set(reference[field])
        matches = sorted(requested.intersection(observed))
        if matches:
            value = float(weights[field])
            score += value
            matched_dimensions += 1
            breakdown[field] = {"score": value, "matches": matches, "match_type": "exact"}
            reasons.append(f"{field} exact: {', '.join(matches)}")
        elif field == "product_category":
            related_matches = sorted(set(related).intersection(observed))
            if related_matches:
                value = float(weights[field]) * 0.5
                score += value
                matched_dimensions += 1
                breakdown[field] = {"score": value, "matches": related_matches, "match_type": "related"}
                reasons.append(f"product_category related: {', '.join(related_matches)}")
            else:
                breakdown[field] = {"score": 0.0, "matches": [], "match_type": "none"}
        else:
            breakdown[field] = {"score": 0.0, "matches": [], "match_type": "none"}
    return {
        "id": reference["id"],
        "score": round(score, 3),
        "matched_dimensions": matched_dimensions,
        "reason": reasons,
        "score_breakdown": breakdown,
        "reference": reference,
    }


def _style_profile_hint(reference: dict[str, Any]) -> dict[str, Any]:
    """Expose design direction without coupling it to product facts or font files."""
    intent = set(reference["image_intent"])
    composition = set(reference["composition"])
    if "editorial_hero" in intent:
        headline_tone = "editorial_serif"
    elif "detail_callout" in intent or "detail_insets" in composition:
        headline_tone = "technical_sans"
    else:
        headline_tone = "clean_sans"
    return {
        "design_reference_id": reference["id"],
        "headline_tone": headline_tone,
        "composition": reference["composition"],
        "lighting": reference["lighting"],
        "text_surface_preference": "transparent",
        "font_resolution": "layout_local_only",
    }


def select_references(index: dict[str, Any], profile: dict[str, Any], *, max_auxiliary: int | None = None) -> dict[str, Any]:
    """Rank by category + intent + composition + lighting, then select 1 + <=2."""
    index_errors = validate_index(index)
    profile_errors = validate_profiles({"schema_version": 1, "profiles": [profile]})
    if index_errors or profile_errors:
        raise ReferenceIndexError("; ".join(index_errors + profile_errors))
    maximum = profile.get("max_auxiliary", 2) if max_auxiliary is None else max_auxiliary
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0 or maximum > 2:
        raise ReferenceIndexError("max_auxiliary must be an integer from 0 to 2")
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(index.get("selection_weights", {}))
    ranked = [_score_reference(reference, profile, weights) for reference in index["references"]]
    minimum_score = float(profile.get("minimum_score", 1))
    minimum_dimensions = int(profile.get("minimum_matched_dimensions", 2))
    qualified = [candidate for candidate in ranked if candidate["score"] >= minimum_score
                 and candidate["matched_dimensions"] >= minimum_dimensions]
    tie_break = {value: position for position, value in enumerate(profile.get("tie_break_case_ids", []))}
    qualified.sort(key=lambda candidate: (-candidate["score"], -candidate["matched_dimensions"],
                                           tie_break.get(candidate["id"], len(tie_break)), candidate["id"]))
    if not qualified:
        raise ReferenceIndexError(f"No reference meets profile: {profile['id']}")

    def public(candidate: dict[str, Any]) -> dict[str, Any]:
        reference = candidate["reference"]
        return {
            "id": candidate["id"],
            "external_path": reference["external_path"],
            "sha256": reference["sha256"],
            "score": candidate["score"],
            "reason": candidate["reason"],
            "visual_observation": reference["visual_observation"],
            "source_mode": "external_reference_only",
        }

    result = {
        "schema_version": 1,
        "profile_id": profile["id"],
        "selection_basis": ["product_category", "image_intent", "composition", "lighting"],
        "primary": public(qualified[0]),
        "auxiliaries": [public(candidate) for candidate in qualified[1:1 + maximum]],
        "style_profile_hint": _style_profile_hint(qualified[0]["reference"]),
        "source_policy": {
            "external_path_and_hash_only": True,
            "copy_sample_product_pixels": False,
            "copy_sample_copy_or_cta": False,
            "copy_sample_brand_or_logo": False,
        },
    }
    if profile.get("selection_note"):
        result["selection_note"] = profile["selection_note"]
    return result


def prepare_selection(
    product_context: dict[str, Any], selection_path: Path, *, force: bool = False,
    index_path: Path = DEFAULT_INDEX, verify_files: bool = False,
) -> dict[str, Any]:
    """Select and persist references once for a new V2 layout project.

    Existing valid selections are returned unchanged unless `force` is explicit.
    The saved record carries only external sample paths and hashes; it never
    imports reference pixels or sample copy into a project.
    """
    selection_path = Path(selection_path)
    with _selection_lock(selection_path):
        return _prepare_selection_locked(
            product_context, selection_path, force=force,
            index_path=index_path, verify_files=verify_files,
        )


def _prepare_selection_locked(
    product_context: dict[str, Any], selection_path: Path, *, force: bool,
    index_path: Path, verify_files: bool,
) -> dict[str, Any]:
    """Read, select, and commit while the selection-specific lock is held."""
    if selection_path.exists() and not force:
        saved = _read_json(selection_path)
        saved_errors = _validate_saved_selection(saved)
        if saved_errors:
            raise ReferenceIndexError(
                f"Saved selection is invalid; refuse to overwrite without --force: {'; '.join(saved_errors)}"
            )
        if saved.get("selection_status") != "needs_input":
            source_errors = _candidate_source_errors(saved)
            if source_errors:
                saved["selection_status"] = "needs_input"
                saved["needs_input"] = sorted(set(source_errors))
                saved["primary"] = None
                saved["auxiliaries"] = []
                _write_json(selection_path, saved)
        return saved
    index = _read_json(Path(index_path))
    errors = validate_index(index)
    if errors:
        raise ReferenceIndexError("; ".join(errors))
    profile, public_context, inference = _automatic_profile(product_context)
    if verify_files:
        source_errors = verify_external_sources(index)
        if source_errors:
            selection = _needs_input_selection(public_context, inference, Path(index_path), source_errors)
            _write_json(selection_path, selection)
            return selection
    if not any(values != [MISSING_SIGNAL] for values in profile["signals"].values()):
        selection = _needs_input_selection(
            public_context, inference, Path(index_path), ["STYLE_CONTEXT_INSUFFICIENT"]
        )
        _write_json(selection_path, selection)
        return selection
    try:
        selection = select_references(index, profile)
    except ReferenceIndexError as exc:
        if str(exc).startswith("No reference meets profile:"):
            selection = _needs_input_selection(public_context, inference, Path(index_path), ["NO_REFERENCE_MATCH"])
            _write_json(selection_path, selection)
            return selection
        raise
    selection.update({
        "selection_status": "selected",
        "selection_mode": "automatic_context",
        "selection_context": public_context,
        "inference": inference,
        "index_provenance": {
            "index_path": str(Path(index_path).resolve()),
            "index_sha256": _sha256(Path(index_path)),
            "asset_policy": "external_path_and_hash_only",
        },
    })
    selection["selection_basis"] = [
        field for field, values in profile["signals"].items() if values != [MISSING_SIGNAL]
    ]
    source_errors = _candidate_source_errors(selection)
    if source_errors:
        selection = _needs_input_selection(public_context, inference, Path(index_path), source_errors)
    _write_json(selection_path, selection)
    return selection


def _json_output(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate index/profile schema and optional external hashes")
    validate.add_argument("--verify-files", action="store_true", help="check external paths and SHA-256 values")
    select = subparsers.add_parser("select", help="select one primary plus up to two auxiliary references")
    select.add_argument("--profile", required=True, help="profile ID from style_reference_profiles.json")
    select.add_argument("--max-auxiliary", type=int, choices=range(0, 3), default=None)
    select.add_argument("--verify-files", action="store_true", help="check selected source paths and hashes before output")
    prepare = subparsers.add_parser("prepare", help="select from product context and save/reuse a selection record")
    prepare.add_argument("--product-context", type=Path, required=True,
                         help="JSON with product, category, intents, and optional composition/lighting")
    prepare.add_argument("--selection-output", type=Path, required=True)
    prepare.add_argument("--force", action="store_true", help="replace an existing saved selection")
    prepare.add_argument("--verify-files", action="store_true", help="check all external paths and hashes before selection")
    args = parser.parse_args(argv)

    try:
        index = _read_json(args.index)
        profiles = _read_json(args.profiles)
        errors = validate_index(index) + validate_profiles(profiles)
        if args.command == "validate":
            if args.verify_files and not errors:
                errors.extend(verify_external_sources(index))
            _json_output({"valid": not errors, "errors": errors, "reference_count": len(index.get("references", []))})
            return 0 if not errors else 2
        if errors:
            raise ReferenceIndexError("; ".join(errors))
        if args.command == "prepare":
            context = _read_json(args.product_context)
            _json_output(prepare_selection(
                context, args.selection_output, force=args.force,
                index_path=args.index, verify_files=args.verify_files,
            ))
            return 0
        profile = _profile_by_id(profiles, args.profile)
        if args.verify_files:
            verification = verify_external_sources(index)
            if verification:
                raise ReferenceIndexError("; ".join(verification))
        _json_output(select_references(index, profile, max_auxiliary=args.max_auxiliary))
        return 0
    except ReferenceIndexError as exc:
        print(f"style-reference error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
