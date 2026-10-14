"""Product facts, evidence references and profile validation (gate G1)."""
from __future__ import annotations

import re

from .common import CORE_ATTRS, bad_text, digest, norm_text

PROFILE_SCHEMA = "compliance-profile-v1"
STATUSES = ("provided", "inferred", "unknown")
_REF = re.compile(r"^(title|description|notes|brand|category)$|^bullet:\d+$|^image:[A-Za-z0-9._-]+$|^catalog:[A-Za-z0-9._-]+$|^user:[A-Za-z0-9._-]+$")


def facts_digest(facts: dict) -> str:
    body = {k: v for k, v in facts.items() if k != "facts_digest"}
    return digest(body)


def texts(facts: dict) -> dict:
    """Text fields that keywords and evidence references can point to."""
    p = facts.get("product") or {}
    out = {"title": p.get("title") or "", "description": p.get("description") or "",
           "notes": p.get("notes") or "", "brand": p.get("brand") or "", "category": p.get("category") or ""}
    for i, b in enumerate(p.get("bullets") or [], 1):
        out[f"bullet:{i}"] = b or ""
    return out


def searchable(facts: dict) -> str:
    t = texts(facts)
    return norm_text("\n".join(v for k, v in t.items() if k != "brand"))


def valid_refs(facts: dict) -> set:
    refs = {k for k, v in texts(facts).items() if str(v).strip()}
    refs.update(f"image:{img.get('id')}" for img in facts.get("images") or [] if img.get("id"))
    refs.update(f"catalog:{k}" for k in (facts.get("catalog") or {}))
    refs.update(f"user:{k}" for k in (facts.get("user") or {}))
    return refs


def check_refs(refs, allowed: set, where: str, errors: list, required: bool = True):
    if not isinstance(refs, list) or (required and not refs):
        errors.append({"path": where, "message": "需要至少一个证据引用（如 title、bullet:2、image:<id>）"})
        return
    for r in refs:
        if not isinstance(r, str) or not _REF.match(r):
            errors.append({"path": where, "message": f"证据引用格式不对：{r!r}"})
        elif r not in allowed:
            errors.append({"path": where, "message": f"证据引用不存在：{r}"})


def template(pack, facts: dict) -> dict:
    """Profile skeleton the analyst fills in. Core attributes are listed with value null."""
    attrs = {}
    for a in CORE_ATTRS:
        spec = pack.attributes[a]
        attrs[a] = {"value": None, "status": "unknown", "evidence": [], "_type": spec["type"],
                    "_values": spec.get("values"), "_zh": spec.get("zh")}
    return {
        "schema": PROFILE_SCHEMA,
        "facts_digest": facts.get("facts_digest"),
        "product": {"name_zh": None, "name_en": None, "summary_zh": None},
        "families": [],
        "attributes": attrs,
        "claims": [],
        "notes_zh": None,
        "_examples": {
            "families": [{"id": "power_bank", "evidence": ["title", "image:img-1"]}],
            "attributes": {"battery.chemistry": {"value": ["li_ion"], "status": "provided", "evidence": ["bullet:2"]},
                           "battery.watt_hours": {"value": 37, "status": "inferred", "evidence": ["bullet:2"],
                                                  "note": "10000mAh×3.7V≈37Wh"},
                           "radio.technologies": {"value": [], "status": "provided", "evidence": ["image:img-2"]},
                           "user.primarily_children": {"value": False, "status": "inferred", "evidence": ["image:img-1"]}},
            "claims": [{"id": "fda_approved_cleared", "evidence": ["bullet:4"], "quote": "FDA approved material"}],
            "_rules": "families 至少一个；核心属性都要填写，不适用就写 false 或 []；看不出来写 status=unknown、value=null，"
                      "不能猜成 false。provided=资料或图片直接写明；inferred=有依据的推断。宣称只记录资料里真实出现的说法。",
        },
    }


def _coerce(value, spec):
    t = spec["type"]
    if t == "number" and isinstance(value, str):
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return value
    if t == "bool" and isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no"):
        return value.strip().lower() in ("true", "yes")
    if t == "multi" and isinstance(value, str):
        return [value]
    if t == "enum" and isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def _type_ok(value, spec) -> bool:
    t = spec["type"]
    values = [str(v) for v in spec.get("values") or []]
    if t == "bool":
        return isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "enum":
        return str(value) in values
    if t == "multi":
        return isinstance(value, list) and all(str(v) in values for v in value)
    return isinstance(value, str)


def validate(pack, facts: dict, profile) -> tuple:
    """Return (normalized_profile, errors). Format slips are fixed silently; anything else is an error."""
    errors = []
    if not isinstance(profile, dict):
        return None, [{"path": "", "message": "画像必须是 JSON 对象"}]
    if profile.get("schema") != PROFILE_SCHEMA:
        errors.append({"path": "schema", "message": f"schema 必须是 {PROFILE_SCHEMA}"})
    if profile.get("facts_digest") != facts.get("facts_digest"):
        errors.append({"path": "facts_digest", "message": "facts_digest 与本次事实包不一致，请重新 prepare"})
    allowed = valid_refs(facts)
    out = {"schema": PROFILE_SCHEMA, "facts_digest": facts.get("facts_digest"), "families": [], "attributes": {},
           "claims": [], "product": {}, "notes_zh": None}
    prod = profile.get("product") or {}
    for k in ("name_zh", "name_en", "summary_zh"):
        v = prod.get(k)
        if v is not None and (not isinstance(v, str) or len(v) > 400 or bad_text(v)):
            errors.append({"path": f"product.{k}", "message": "必须是 400 字以内的正常文本"})
        out["product"][k] = v
    fams = profile.get("families")
    if not isinstance(fams, list) or not fams:
        errors.append({"path": "families", "message": "至少填写一个产品族"})
        fams = []
    seen = set()
    for i, f in enumerate(fams):
        fid = f.get("id") if isinstance(f, dict) else f
        if fid not in pack.families:
            errors.append({"path": f"families[{i}]", "message": f"未知产品族 {fid!r}"})
            continue
        if fid in seen:
            continue
        seen.add(fid)
        refs = f.get("evidence") if isinstance(f, dict) else None
        check_refs(refs, allowed, f"families[{i}].evidence", errors)
        out["families"].append({"id": fid, "evidence": refs or []})
    attrs = profile.get("attributes") or {}
    if not isinstance(attrs, dict):
        errors.append({"path": "attributes", "message": "attributes 必须是对象"})
        attrs = {}
    for name, item in attrs.items():
        spec = pack.attributes.get(name)
        where = f"attributes.{name}"
        if spec is None:
            errors.append({"path": where, "message": "未知属性"})
            continue
        if not isinstance(item, dict):
            item = {"value": item, "status": "provided", "evidence": []}
        status = item.get("status")
        if status not in STATUSES:
            errors.append({"path": where + ".status", "message": "status 只能是 provided / inferred / unknown"})
            continue
        if status == "unknown":
            out["attributes"][name] = {"value": None, "status": "unknown", "evidence": []}
            continue
        value = _coerce(item.get("value"), spec)
        if value is None or not _type_ok(value, spec):
            errors.append({"path": where + ".value", "message": f"取值不符合类型 {spec['type']}"
                           + (f"，可选值 {spec.get('values')}" if spec.get("values") else "")})
            continue
        check_refs(item.get("evidence"), allowed, where + ".evidence", errors)
        out["attributes"][name] = {"value": value, "status": status, "evidence": item.get("evidence") or []}
        if name == "substance.primary_form" and item.get("note") is not None:
            note = item["note"]
            if not isinstance(note, str) or len(note) > 1500 or bad_text(note):
                errors.append({"path": where + ".note", "message": "形态说明须为 1500 字以内的正常文本"})
            else:
                out["attributes"][name]["note"] = note
    missing = [a for a in CORE_ATTRS if a not in out["attributes"] and a not in attrs]
    if missing:
        errors.append({"path": "attributes", "message": "缺少核心属性（不适用写 false/[]，不确定写 unknown）：" + "、".join(missing)})
    for a in CORE_ATTRS:
        out["attributes"].setdefault(a, {"value": None, "status": "unknown", "evidence": []})
    cl = profile.get("claims") or []
    if not isinstance(cl, list):
        errors.append({"path": "claims", "message": "claims 必须是列表"})
        cl = []
    for i, c in enumerate(cl):
        cid = c.get("id") if isinstance(c, dict) else c
        if cid not in pack.claims:
            errors.append({"path": f"claims[{i}]", "message": f"未知宣称 {cid!r}"})
            continue
        refs = c.get("evidence") if isinstance(c, dict) else None
        check_refs(refs, allowed, f"claims[{i}].evidence", errors)
        quote = (c.get("quote") if isinstance(c, dict) else None) or ""
        out["claims"].append({"id": cid, "evidence": refs or [], "quote": str(quote)[:200]})
    note = profile.get("notes_zh")
    if note is not None and (not isinstance(note, str) or len(note) > 1500 or bad_text(note)):
        errors.append({"path": "notes_zh", "message": "1500 字以内的正常文本"})
    out["notes_zh"] = note
    return out, errors


def quick_profile(pack, facts: dict) -> dict:
    """Provisional profile for the quick screen: families and claims from keywords, attributes unknown
    unless catalog data states them."""
    text = searchable(facts)
    fams = []
    for fid, m in pack.family_matchers.items():
        t = text
        for phrase in getattr(pack, "family_excludes", {}).get(fid, []):
            t = t.replace(phrase, " ")
        hits = m.find(t)
        if hits:
            fams.append({"id": fid, "evidence": ["title"], "keywords": hits})
    claims = [{"id": cid, "evidence": ["title"], "quote": ", ".join(hits)}
              for cid, m in pack.claim_matchers.items() if (hits := m.find(text))]
    attrs = {}
    for name, value in ((facts.get("catalog") or {}).get("profile_attributes") or {}).items():
        spec = pack.attributes.get(name)
        if spec and _type_ok(value, spec):
            attrs[name] = {"value": value, "status": "provided", "evidence": [f"catalog:{name}"]}
    return {"schema": PROFILE_SCHEMA, "facts_digest": facts.get("facts_digest"), "families": fams,
            "attributes": attrs, "claims": claims, "product": {}, "notes_zh": None, "quick": True}
