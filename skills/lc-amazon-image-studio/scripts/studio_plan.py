"""plan.json validation (V8): the only file the agent writes, checked before any generation.

Secondary images are delivered without review, so everything that can be checked in
text is checked here and all problems are returned at once (JSON path + code):
copy budgets per language and per canvas tier, numbers backed by product.facts,
prices / rankings / badges never, claim words only when the facts contain them,
script matches the marketplace language, the main image carries no copy.

V8.1 no-copy fields: `cast` (the new model, required when a slot shows a person),
`cast_anchor`, `hide` (areas of product photos to blur out), per-slot `tone_ref`
(opt-in colour/light board from a user template or a project reference) and an
original `scene` on user-template slots; wording that points at a reference or a
real person is rejected.
"""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from pathlib import Path

MAIN_ROUTES = {"auto", "photo", "generate"}
BACKDROP_CHOICES = {"auto", "white", "light_grey", "mid_grey"}
PEOPLE_VALUES = {False, True, "hands", "person"}
COPY_KEYS = ("eyebrow", "headline", "subline", "callouts")
MAX_REFERENCES = 4
MAX_HIDE_BOXES = 8
CJK_TEXT = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]")
# The image model never sees the original reference, so naming one can only mean "copy what you see".
REFERENCE_WORDS = re.compile(
    r"\b((the|this|that|these|those|user'?s?|their|its|sample|example|original|competitor'?s?) (references?|refs?)|"
    r"reference (images?|photos?|pictures?|sets?|designs?|scenes?|models?|people|person|style|look)|"
    r"templates?|style plates?|tone boards?|colou?r references?|competitors?|"
    r"(input|sample|example|original) (images?|photos?|pictures?))\b", re.I)
REAL_PERSON_WORDS = re.compile(r"\b(famous|celebrit\w*|look-?alikes?|resembl\w*)\b", re.I)
STOP_WORDS = {"with", "from", "that", "this", "into", "onto", "over", "under", "their", "there", "very", "soft", "light",
              "white", "warm", "clean", "simple", "natural", "small", "large", "behind", "front", "side", "left", "right"}

LATIN = {  # words, characters
    "standard": {"eyebrow": (3, 24), "headline": (6, 42), "subline": (12, 80), "callouts": (4, 4, 28), "total": 30},
    "wide": {"eyebrow": (3, 20), "headline": (5, 32), "subline": (8, 56), "callouts": (3, 3, 22), "total": 18},
    "narrow": {"eyebrow": None, "headline": (4, 26), "subline": None, "callouts": None, "total": 5},
}
CJK = {  # characters
    "standard": {"eyebrow": 6, "headline": 12, "subline": 24, "callouts": (4, 8)},
    "wide": {"eyebrow": 5, "headline": 10, "subline": 16, "callouts": (3, 6)},
    "narrow": {"eyebrow": None, "headline": 8, "subline": None, "callouts": None},
}
CJK_LANGUAGES = {"ja", "zh", "ko"}
SCRIPTS = {"latin": "LATIN", "ja": ("CJK", "HIRAGANA", "KATAKANA", "LATIN"), "zh": ("CJK", "LATIN"),
           "ko": ("HANGUL", "CJK", "LATIN"), "ar": ("ARABIC", "LATIN"), "he": ("HEBREW", "LATIN"),
           "ru": ("CYRILLIC", "LATIN"), "uk": ("CYRILLIC", "LATIN"), "bg": ("CYRILLIC", "LATIN"), "el": ("GREEK", "LATIN"),
           "hi": ("DEVANAGARI", "LATIN"), "th": ("THAI", "LATIN")}
FORBIDDEN = (r"[$€£¥₹]", r"\bsale\b", r"\bdiscount", r"%\s*off\b", r"\bdeals?\b", r"\bcoupons?\b", r"\bfree shipping\b",
             r"\bbuy now\b", r"\blimited time\b", r"\bbest[- ]?sell", r"#\s*1\b", r"\bno\.?\s*1\b", r"\bnumber one\b",
             r"\btop[- ]rated\b", r"\bamazon'?s? choice\b", r"\bmoney[- ]back\b", r"\bcheapest\b", r"\blowest price\b")
CLAIMS = ("guarantee", "warranty", "fda", "ce", "ul", "etl", "fcc", "rohs", "iso", "certified", "certification", "approved",
          "patented", "patent", "clinically", "dermatologist", "organic", "bpa-free", "bpa free", "non-toxic", "nontoxic",
          "hypoallergenic", "eco-friendly", "recyclable", "biodegradable", "waterproof", "water-resistant",
          "dishwasher-safe", "dishwasher safe", "100%", "medical", "antibacterial")
RULES_SUMMARY = {
    "standard": "eyebrow <=3 words; headline <=6 words/42 chars; subline <=12 words; <=4 callouts x <=4 words; <=30 words",
    "wide": "headline <=5 words; subline <=8 words; <=3 callouts x <=3 words (A+ 1464x600 and similar)",
    "narrow": "headline <=4 words only",
    "cjk": "headline <=12 chars, subline <=24, <=4 callouts x <=8 chars (tighter for wide/narrow)",
    "numbers": "every number in copy must appear in product.facts",
    "never": "prices, discounts, best seller/#1, Amazon's Choice; guarantees/certifications/waterproof/100% only if in facts",
    "language": "copy in the marketplace language; the main image has no copy",
}


def tier_for(canvas):
    from lc_frame_fit import plan
    band = plan(canvas)["band"]
    kept = min(band[2], band[3])
    return "standard" if kept >= 0.85 else "wide" if kept >= 0.6 else "narrow"


def _words(text):
    return [word for word in re.split(r"\s+", text.strip()) if word]


def _script_ok(text, language):
    base = language.split("-")[0].lower()
    allowed = SCRIPTS.get(base, SCRIPTS["latin"] if base not in SCRIPTS else None)
    if allowed is None:
        return True
    allowed = (allowed,) if isinstance(allowed, str) else allowed
    for char in text:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, "")
        if not any(name.startswith(script) or f" {script} " in f" {name} " for script in allowed):
            return False
    return True


def _numbers(text):
    values = set()
    for match in re.finditer(r"\d+(?:[.,]\d+)?", text):
        value = match.group(0).replace(",", ".")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        values.add(value)
    return values


def load_plan(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ValueError(f"PLAN_NOT_FOUND: {path}") from None
    except ValueError as exc:
        raise ValueError(f"PLAN_INVALID_JSON: {path}: {exc}") from None


def validate(plan, project, catalog):
    """Return (normalized_plan, errors, warnings); errors are dicts {path, code, message}."""
    import studio_catalog
    errors, warnings = [], []

    def error(path, code, message):
        errors.append({"path": path, "code": code, "message": message})

    def text(value, path, limit, required=False):
        if value is None or value == "":
            if required:
                error(path, "REQUIRED", "required")
            return ""
        if not isinstance(value, str):
            error(path, "TYPE", "must be text")
            return ""
        value = re.sub(r"\s+", " ", value).strip()
        if len(value) > limit:
            error(path, "TOO_LONG", f"at most {limit} characters")
        return value

    if not isinstance(plan, dict):
        return None, [{"path": "$", "code": "TYPE", "message": "plan.json must be an object"}], []
    if plan.get("version") != 1:
        error("$.version", "VERSION", "use \"version\": 1")
    normalized = {"version": 1}
    product = plan.get("product")
    if not isinstance(product, dict):
        error("$.product", "REQUIRED", "describe the product: name, look, scale, keep, facts")
        product = {}
    normalized["product"] = {
        "name": text(product.get("name"), "$.product.name", 80, True),
        "look": text(product.get("look"), "$.product.look", 500, True),
        "scale": text(product.get("scale"), "$.product.scale", 240),
        "keep": [text(item, f"$.product.keep[{i}]", 100) for i, item in enumerate(product.get("keep") or [])][:10],
        "facts": [text(item, f"$.product.facts[{i}]", 160) for i, item in enumerate(product.get("facts") or [])][:30],
        "transparent": bool(product.get("transparent", False)),
    }
    for key in set(product) - {"name", "look", "scale", "keep", "facts", "transparent"}:
        error(f"$.product.{key}", "UNKNOWN_KEY", "not a product field")
    facts_text = " ".join(normalized["product"]["facts"]).lower()
    fact_numbers = _numbers(facts_text)
    families = studio_catalog.family_ids(catalog)
    family = plan.get("family")
    if family is not None and family != "custom" and family not in families:
        error("$.family", "FAMILY_UNKNOWN", f"unknown family {family!r}; pick one from the catalog or use \"custom\"")
    normalized["family"] = family or "custom"
    normalized["style"] = text(plan.get("style"), "$.style", 300)
    _copy_wording(normalized["style"], "$.style", error)
    normalized["cast"] = text(plan.get("cast"), "$.cast", 300)
    if CJK_TEXT.search(normalized["cast"]):
        error("$.cast", "ENGLISH_REQUIRED", "describe the model in English (age range, hair, skin tone, build, styling)")
    _copy_wording(normalized["cast"], "$.cast", error, real_people=True)
    normalized["cast_anchor"] = plan.get("cast_anchor")
    people_default = plan.get("people", False)
    if people_default not in PEOPLE_VALUES:
        error("$.people", "PEOPLE", "use false, true, \"hands\" or \"person\"")
    for key in set(plan) - {"version", "product", "family", "style", "people", "slots", "cast", "cast_anchor", "hide"}:
        error(f"$.{key}", "UNKNOWN_KEY", "not a plan field")
    whole = [photo for photo in project["photos"] if photo.get("role") == "whole"]
    if not whole:
        error("$", "PHOTOS_REQUIRED", "register at least one whole-product photo (init --photos or add-photos)")
    photo_ids = {photo["id"] for photo in project["photos"]}
    normalized["hide"] = _hide(plan.get("hide"), photo_ids, error, warnings)
    slots_in = plan.get("slots")
    if not isinstance(slots_in, dict):
        error("$.slots", "REQUIRED", "an object keyed by slot id")
        slots_in = {}
    known_slots = {slot["id"]: slot for slot in project["slots"]}
    for key in set(slots_in) - set(known_slots):
        error(f"$.slots.{key}", "UNKNOWN_SLOT", f"the project has no slot {key!r}")
    normalized["slots"] = {}
    language = project["language"]
    cjk = language.split("-")[0].lower() in CJK_LANGUAGES
    for slot_id, slot in known_slots.items():
        path = f"$.slots.{slot_id}"
        entry = slots_in.get(slot_id)
        if entry is None:
            error(path, "SLOT_MISSING", "plan every slot, or mark it {\"skip\": true}")
            continue
        if not isinstance(entry, dict):
            error(path, "TYPE", "must be an object")
            continue
        if entry.get("skip") is True:
            normalized["slots"][slot_id] = {"skip": True}
            continue
        if slot["kind"] == "main":
            out = {"route": entry.get("route", "auto"), "photo": entry.get("photo"), "view": text(entry.get("view"), f"{path}.view", 60),
                   "backdrop": entry.get("backdrop", "auto")}
            if out["route"] not in MAIN_ROUTES:
                error(f"{path}.route", "ROUTE", "use auto, photo or generate")
            if out["backdrop"] not in BACKDROP_CHOICES:
                error(f"{path}.backdrop", "BACKDROP", "use auto, white, light_grey or mid_grey")
            if out["photo"] is not None and out["photo"] not in photo_ids:
                error(f"{path}.photo", "PHOTO_UNKNOWN", f"unknown photo {out['photo']!r}")
            if entry.get("copy"):
                error(f"{path}.copy", "MAIN_HAS_COPY", "the main image carries no text")
            for key in set(entry) - {"route", "photo", "view", "backdrop", "skip", "copy", "photos"}:
                error(f"{path}.{key}", "UNKNOWN_KEY", "not a main-slot field")
            out["photos"] = _photos(entry.get("photos"), photo_ids, whole, slot, path, error)
            normalized["slots"][slot_id] = out
            continue
        out = {"template": entry.get("template"), "message": text(entry.get("message"), f"{path}.message", 160, True),
               "scene": text(entry.get("scene"), f"{path}.scene", 300),
               "direction": text(entry.get("direction"), f"{path}.direction", 300)}
        template = out["template"]
        resolved = None
        if not template:
            error(f"{path}.template", "REQUIRED", "a template id from the catalog, or \"custom\"")
        elif template == "custom":
            design = entry.get("design") if isinstance(entry.get("design"), dict) else {}
            out["design"] = {key: text(design.get(key), f"{path}.design.{key}", 300) for key in ("style", "layout", "typography")}
            if not out["design"]["layout"]:
                error(f"{path}.design.layout", "REQUIRED", "custom designs describe at least the layout")
            for key, value in out["design"].items():
                _copy_wording(value, f"{path}.design.{key}", error)
        else:
            resolved = studio_catalog.resolve(catalog, template)
            if resolved is None:
                error(f"{path}.template", "TEMPLATE_UNKNOWN", f"unknown template {template!r}")
            elif family not in (None, "custom") and resolved[1] and resolved[1]["id"] != family:
                warnings.append({"path": f"{path}.template", "code": "FAMILY_MIX",
                                 "message": f"{template} belongs to {resolved[1]['id']}, not the set family {family}"})
        _copy_wording(out["scene"], f"{path}.scene", error, real_people=True)
        _copy_wording(out["direction"], f"{path}.direction", error, real_people=True)
        if resolved and resolved[0] == "user":
            if not out["scene"]:
                error(f"{path}.scene", "SCENE_REQUIRED", "write an original scene for this product; the user's templates "
                                                        "lend only colour tone and light, never their scene")
            elif _like_reference(out["scene"], resolved[2]):
                warnings.append({"path": f"{path}.scene", "code": "SCENE_LIKE_REFERENCE",
                                 "message": "this scene reuses most of the template's own setting words; invent a different "
                                            "setting for this product"})
        if "tone_ref" in entry:
            out["tone_ref"] = _tone_ref(entry.get("tone_ref"), resolved, project, catalog, f"{path}.tone_ref", error)
        people = entry.get("people", people_default)
        if people not in PEOPLE_VALUES:
            error(f"{path}.people", "PEOPLE", "use false, true, \"hands\" or \"person\"")
        out["people"] = people
        out["photos"] = _photos(entry.get("photos"), photo_ids, whole, slot, path, error)
        out["copy"] = _check_copy(entry.get("copy") or {}, f"{path}.copy", tier_for(slot["canvas"]), cjk, language,
                                  fact_numbers, facts_text, error, warnings)
        for key in set(entry) - {"template", "message", "scene", "direction", "design", "people", "photos", "copy", "skip",
                                 "tone_ref"}:
            error(f"{path}.{key}", "UNKNOWN_KEY", "not a slot field")
        normalized["slots"][slot_id] = out
    members = [slot_id for slot_id, out in normalized["slots"].items()
               if not out.get("skip") and out.get("people") in ("person", True)]
    normalized["cast_members"] = members
    if members and not normalized["cast"]:
        error("$.cast", "CAST_REQUIRED", "a slot shows a person: describe the new model in English (age range, hair, "
                                         "skin tone, build, styling), clearly unlike anyone in the user's references")
    if normalized["cast"] and not members:
        warnings.append({"path": "$.cast", "code": "CAST_UNUSED", "message": "no slot shows a person; cast is ignored"})
    if normalized["cast_anchor"] is not None and normalized["cast_anchor"] not in members:
        error("$.cast_anchor", "CAST_ANCHOR_INVALID", "must be a slot whose people is \"person\" or true")
    return normalized, errors, warnings


def _copy_wording(value, path, error, *, real_people=False):
    if not value:
        return
    found = REFERENCE_WORDS.search(value)
    if found:
        error(path, "COPY_WORDING", f"{found.group(0)!r}: the image model never sees the user's references; describe what "
                                    "you want in your own words instead of pointing at a reference")
    found = REAL_PERSON_WORDS.search(value) if real_people else None
    if found:
        error(path, "COPY_WORDING", f"{found.group(0)!r}: never ask for a real or famous person's likeness")


def _content_words(text):
    return {word for word in re.findall(r"[a-z]{4,}", str(text or "").lower()) if word not in STOP_WORDS}


def _like_reference(scene, template):
    generation = template.get("generation") or {}
    source = " ".join(" ".join(value) if isinstance(value, list) else str(value or "")
                      for value in (generation.get("background"), generation.get("props"), generation.get("surface")))
    reference = _content_words(source)
    return len(reference) >= 4 and len(reference & _content_words(scene)) / len(reference) >= 0.6


def _tone_ref(value, resolved, project, catalog, path, error):
    """Resolve tone_ref to {kind: plate|ref, sha256, ...} (the board itself is made at plan time)."""
    import studio_catalog
    if not isinstance(value, str) or not value.strip():
        error(path, "TYPE", "\"template\", one of the user's template ids, or a project reference id (ref1, ...)")
        return None

    def plate_of(record, label):
        sha = (record.get("assets") or {}).get("plate_sha256")
        if not sha or not catalog["library"].asset_path(sha).is_file():
            error(path, "TONE_REF_UNAVAILABLE", f"{label} has no colour/light image in the library")
            return None
        return {"value": value, "kind": "plate", "sha256": sha, "template": record["id"]}
    if value == "template":
        if not resolved or resolved[0] != "user":
            error(path, "TONE_REF_UNAVAILABLE", "\"template\" works only with one of the user's own templates")
            return None
        return plate_of(resolved[2], resolved[2]["id"])
    ref = next((item for item in project.get("refs", []) if item["id"] == value), None)
    if ref:
        return {"value": value, "kind": "ref", "id": ref["id"], "sha256": ref["sha256"], "path": ref["path"]}
    other = studio_catalog.resolve(catalog, value)
    if other and other[0] == "user":
        return plate_of(other[2], value)
    error(path, "TONE_REF_UNKNOWN", f"unknown reference {value!r}: use \"template\", a user template id or a project "
                                    "reference id")
    return None


def _hide(value, photo_ids, error, warnings):
    """{photo id: [[x, y, w, h], ...]} normalized boxes to blur out of product photos."""
    from lc_template_schema import _box
    if value is None:
        return {}
    if not isinstance(value, dict):
        error("$.hide", "TYPE", "an object {photo id: [[x, y, w, h], ...]}")
        return {}
    out = {}
    for photo_id, boxes in value.items():
        path = f"$.hide.{photo_id}"
        if photo_id not in photo_ids:
            error(path, "PHOTO_UNKNOWN", f"unknown photo {photo_id!r}")
            continue
        if not isinstance(boxes, list) or not boxes:
            error(path, "TYPE", "a non-empty list of [x, y, w, h] boxes")
            continue
        if len(boxes) > MAX_HIDE_BOXES:
            error(path, "TOO_MANY", f"at most {MAX_HIDE_BOXES} boxes per photo")
        good = []
        for index, box in enumerate(boxes[:MAX_HIDE_BOXES]):
            if not _box(box):
                error(f"{path}[{index}]", "BOX_INVALID", "a normalized box [x, y, w, h] within 0..1")
                continue
            good.append([round(float(item), 4) for item in box])
        if good:
            if min(1.0, sum(box[2] * box[3] for box in good)) > 0.6:
                warnings.append({"path": path, "code": "PHOTO_MOSTLY_HIDDEN",
                                 "message": "most of this photo is hidden; use another photo of the product if you have one"})
            out[photo_id] = good
    return out


def _photos(value, photo_ids, whole, slot, path, error):
    if value is None:
        chosen = [photo["id"] for photo in sorted(whole, key=lambda p: (p["view"] not in {"front", "three_quarter"}))][:3]
        return chosen
    if not isinstance(value, list) or not value:
        error(f"{path}.photos", "TYPE", "a non-empty list of photo ids")
        return []
    unknown = [item for item in value if item not in photo_ids]
    if unknown:
        error(f"{path}.photos", "PHOTO_UNKNOWN", f"unknown photos {unknown}")
    if len(value) > MAX_REFERENCES:
        error(f"{path}.photos", "TOO_MANY", f"at most {MAX_REFERENCES} reference photos per image")
    return [item for item in value if item in photo_ids][:MAX_REFERENCES]


def _check_copy(copy_in, path, tier, cjk, language, fact_numbers, facts_text, error, warnings):
    if not isinstance(copy_in, dict):
        error(path, "TYPE", "copy must be an object: eyebrow, headline, subline, callouts")
        return {}
    for key in set(copy_in) - set(COPY_KEYS):
        error(f"{path}.{key}", "UNKNOWN_KEY", "use eyebrow, headline, subline or callouts")
    out = {}
    for key in ("eyebrow", "headline", "subline"):
        value = copy_in.get(key)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            error(f"{path}.{key}", "TYPE", "must be text")
            continue
        out[key] = re.sub(r"\s+", " ", value).strip()
    callouts = copy_in.get("callouts") or []
    if not isinstance(callouts, list) or not all(isinstance(item, str) and item.strip() for item in callouts):
        error(f"{path}.callouts", "TYPE", "a list of short texts")
        callouts = []
    if callouts:
        out["callouts"] = [re.sub(r"\s+", " ", item).strip() for item in callouts]
    limits = (CJK if cjk else LATIN)[tier]
    for key, value in out.items():
        rule = limits.get(key)
        items = value if key == "callouts" else [value]
        if rule is None:
            error(f"{path}.{key}", "NOT_ALLOWED_HERE", f"this canvas ({tier}) has room for a headline only")
            continue
        if key == "callouts":
            count = rule[0]
            if len(items) > count:
                error(f"{path}.callouts", "TOO_MANY", f"at most {count} callouts here")
        for index, item in enumerate(items):
            where = f"{path}.{key}" + (f"[{index}]" if key == "callouts" else "")
            if cjk:
                limit = rule[1] if key == "callouts" else rule
                if len(item.replace(" ", "")) > limit:
                    error(where, "TOO_LONG", f"at most {limit} characters")
            else:
                words, chars = (rule[1], rule[2]) if key == "callouts" else rule
                if len(_words(item)) > words or len(item) > chars:
                    error(where, "TOO_LONG", f"at most {words} words / {chars} characters")
    if not cjk and out:
        total = sum(len(_words(item)) for value in out.values() for item in (value if isinstance(value, list) else [value]))
        if total > limits["total"]:
            error(path, "TOO_MUCH_TEXT", f"{total} words; at most {limits['total']} on this canvas")
    for key, value in out.items():
        for index, item in enumerate(value if isinstance(value, list) else [value]):
            where = f"{path}.{key}" + (f"[{index}]" if isinstance(value, list) else "")
            lowered = item.lower()
            for pattern in FORBIDDEN:
                if re.search(pattern, lowered):
                    error(where, "FORBIDDEN_WORDING", f"not allowed on Amazon images: {item!r}")
                    break
            missing = sorted(_numbers(item) - fact_numbers)
            if missing:
                error(where, "NUMBER_UNBACKED", f"numbers {missing} must appear in product.facts")
            for term in CLAIMS:
                pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
                if re.search(pattern, lowered) and not re.search(pattern, facts_text):
                    error(where, "CLAIM_UNBACKED", f"{term!r} must be stated in product.facts first")
            if not _script_ok(item, language):
                error(where, "WRONG_SCRIPT", f"write the copy in the marketplace language ({language})")
    return out
