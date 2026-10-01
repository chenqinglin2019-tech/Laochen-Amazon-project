#!/usr/bin/env python3
"""Offline keyword classification ledger and downstream integrity checks.

This tool never classifies product intent. Semantic decisions are supplied by a
reviewer; deterministic checks enforce coverage, provenance and quarantine.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone

VERSION = "1.1"
PROFILE = "01_product_profile.json"
RAW = "02_kw_raw.json"
DECISIONS = "03_keyword_decisions.json"
VALIDATION = "03_keyword_validation.json"
POOLS = {"eligible": "03_kw_filtered.json", "deferred": "03_kw_pending.json", "excluded": "03_kw_removed.json"}
DECISION_CODES = {
    "eligible": {"identity", "attribute", "intent", "synonym"},
    "deferred": {"ambiguous_intent", "unknown_fact", "seasonal_unconfirmed", "identity_conflict"},
    "excluded": {"product_mismatch", "fact_conflict", "user_restriction", "unusable_query"},
}
DOWNSTREAM = ("05_title_keywords.json", "06_qa.json", "07_listing.json")


def norm(value):
    """Keep word order, numbers, units, accents and negation; no stemming/sorting."""
    text = unicodedata.normalize("NFKC", value).casefold()
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-"}))
    return re.sub(r"\s+", " ", text).strip()


def phrase_spans(text, phrase):
    # CJK has no inter-word spaces. This is a lexical signal, never a classifier.
    text, phrase = norm(text), norm(phrase)
    if not phrase:
        return []
    cjk = re.search(r"[\u3040-\u30ff\u3400-\u9fff]", phrase)
    pattern = re.escape(phrase) if cjk else r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
    return [match.span() for match in re.finditer(pattern, text)]


def contains_phrase(text, phrase):
    return bool(phrase_spans(text, phrase))


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_json(path, required=True):
    if not path.exists() and not required:
        return None
    def invalid(value):
        raise ValueError("Nonfinite JSON number")
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid)


def atomic_write(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", prefix=".keyword-", delete=False) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def fingerprints(run, names):
    return {name: hashlib.sha256((run / name).read_bytes()).hexdigest() if (run / name).exists() else None for name in names}


def source_words(raw):
    if not isinstance(raw, dict):
        raise ValueError("Raw keyword response must be an object")
    words = raw.get("keywords")
    if words is None:
        words = raw.get("raw", {}).get("keyword_data")
    if not isinstance(words, list):
        raise ValueError("Raw response requires a keyword array")
    result = []
    for item in words:
        word = item.get("keyword") if isinstance(item, dict) else item
        if not isinstance(word, str):
            raise ValueError("Every source keyword must be a string; do not silently skip malformed records")
        result.append(word)
    return result


def source_records(raw):
    records = {}
    for index, word in enumerate(source_words(raw)):
        key = norm(word)
        record = records.setdefault(key, {"keyword_id": "raw-" + digest(key)[:20], "keyword": word,
                                        "normalized": key, "source_positions": [], "original_forms": []})
        record["source_positions"].append(index)
        record["original_forms"].append(word)
    return list(records.values())


def draft(record, origin):
    return dict(record, origin=origin, initial_decision=None, decision=None, reason_code=None,
                reason="", query_intent="", intent_group="", role=None, label=None,
                fact_ids=[], measurement_ids=[], identity_basis=False, evidence="", applies_to=[],
                reviewer="", resolution="", group_difference="", promotion_condition="", restrictions="")


def prepare(run):
    if (run / DECISIONS).exists():
        raise ValueError("Decision ledger exists; update it in place instead of overwriting review history")
    bound = fingerprints(run, (PROFILE, RAW))
    profile, raw = read_json(run / PROFILE), read_json(run / RAW)
    records = [draft(record, "raw") for record in source_records(raw)]
    existing = {item["normalized"] for item in records}
    identity = profile.get("product_identity", {})
    supplemental = []
    for word in [identity.get("canonical_name")] + identity.get("protected_terms", []):
        if not nonempty(word) or norm(word) in existing:
            continue
        key = norm(word)
        supplemental.append(draft({"keyword_id": "product-" + digest(key)[:20], "keyword": word,
                                   "normalized": key, "source_ref": "profile.product_identity"}, "product"))
        existing.add(key)
    result = {"keyword_schema_version": VERSION, "source_fingerprints": bound,
              "bound_facts": fact_snapshot(profile),
              "records": records, "supplemental_terms": supplemental}
    if bound != fingerprints(run, (PROFILE, RAW)):
        raise ValueError("Source files changed while preparing")
    atomic_write(run / DECISIONS, result)
    return result


def fact_snapshot(profile):
    """Per-fact digests so a later profile edit can name the exact keywords it affects."""
    snapshot = {"__identity__": digest(profile.get("product_identity")), "__forbidden__": digest(profile.get("forbidden_terms", [])),
                "__variants__": digest([v.get("variant_id") for v in profile.get("variants", []) if isinstance(v, dict)])}
    for owner in [profile] + [v for v in profile.get("variants", []) if isinstance(v, dict)]:
        for key, identity in (("facts", "fact_id"), ("measurements", "measurement_id")):
            for value in owner.get(key, []):
                if isinstance(value, dict) and isinstance(value.get(identity), str):
                    snapshot[value[identity]] = digest(value)
    return snapshot


def rebind(run, reviewed=False):
    """Re-bind the ledger to an edited profile after only the affected keywords were rechecked."""
    decisions, profile = read_json(run / DECISIONS), read_json(run / PROFILE)
    current = fingerprints(run, (PROFILE, RAW))
    old = decisions.get("source_fingerprints", {})
    if old.get(RAW) != current[RAW]:
        raise ValueError("02_kw_raw.json changed; raw keywords cannot be re-bound, prepare a new ledger in a new run")
    if old == current:
        return {"rebound": False, "affected": [], "message": "ledger already bound to current files"}
    before, after = decisions.get("bound_facts"), fact_snapshot(profile)
    records = all_records(decisions)
    if not isinstance(before, dict):
        changed, affected = None, [r["keyword"] for r in records if r.get("fact_ids") or r.get("measurement_ids")]
    else:
        changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        affected = []
        for record in records:
            refs = set(record.get("fact_ids") or []) | set(record.get("measurement_ids") or [])
            if (refs & changed or "__identity__" in changed and record.get("identity_basis")
                    or "__forbidden__" in changed and record.get("reason_code") == "user_restriction"
                    or "__variants__" in changed and record.get("applies_to") != ["all"]):
                affected.append(record["keyword"])
    if affected and not reviewed:
        return {"rebound": False, "affected": affected, "changed": sorted(changed) if changed is not None else None,
                "message": "recheck only these keywords against the edited profile, update them if needed, then run rebind --reviewed"}
    decisions["source_fingerprints"], decisions["bound_facts"] = current, after
    atomic_write(run / DECISIONS, decisions)
    return {"rebound": True, "affected": affected, "changed": sorted(changed) if changed is not None else None}


GROUP_FIELDS = ("decision", "reason_code", "reason", "query_intent", "evidence", "role", "label", "fact_ids",
                "measurement_ids", "identity_basis", "applies_to", "promotion_condition", "restrictions",
                "group_difference", "resolution")


def apply_groups(run, groups_file):
    """Fill per-keyword ledger fields from intent-group judgements.

    The per-keyword ledger and every check stay unchanged; a group judgement is copied
    to each member so one decision is written once instead of once per keyword.
    """
    decisions, spec = read_json(run / DECISIONS), read_json(groups_file)
    if not isinstance(spec, dict) or not isinstance(spec.get("groups"), dict):
        raise ValueError("Groups file needs a 'groups' object")
    records = all_records(decisions)
    by_key = {}
    for record in records:
        by_key[record["keyword_id"]] = record
        by_key[norm(record["keyword"])] = record
    reviewer = spec.get("reviewer")
    unknown, assigned = [], {}
    for group_id, group in spec["groups"].items():
        if not nonempty(group_id) or not isinstance(group, dict) or not isinstance(group.get("keywords"), list):
            raise ValueError("Each group needs an id and a keywords array")
        for word in group["keywords"]:
            record = by_key.get(word) or by_key.get(norm(word)) if isinstance(word, str) else None
            if record is None:
                unknown.append(word); continue
            if record["keyword_id"] in assigned and assigned[record["keyword_id"]] != group_id:
                raise ValueError("Keyword assigned to two groups: " + record["keyword"])
            assigned[record["keyword_id"]] = group_id
    overrides = spec.get("overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be an object keyed by keyword or keyword_id")
    for word in overrides:
        if (by_key.get(word) or by_key.get(norm(word))) is None:
            unknown.append(word)
    if unknown:
        raise ValueError("Unknown keywords in groups file (use the exact keyword or keyword_id): " + ", ".join(map(str, unknown[:20])))
    stored = decisions.setdefault("intent_groups", {})
    for group_id, group in spec["groups"].items():
        stored[group_id] = {key: group[key] for key in GROUP_FIELDS + ("reviewer",) if key in group}
        stored[group_id]["keywords"] = [by_key.get(w, by_key.get(norm(w)))["keyword_id"] for w in group["keywords"]]
    for record in records:
        group_id = assigned.get(record["keyword_id"])
        if group_id is None:
            continue
        group = spec["groups"][group_id]
        for key in GROUP_FIELDS:
            if key in group:
                record[key] = list(group[key]) if isinstance(group[key], list) else group[key]
        record["intent_group"] = group_id
        record["reviewer"] = group.get("reviewer") or reviewer or record.get("reviewer", "")
        if record.get("initial_decision") is None:
            record["initial_decision"] = record.get("decision")
    for word, fields in overrides.items():
        record = by_key.get(word) or by_key.get(norm(word))
        if not isinstance(fields, dict):
            raise ValueError("Override for %s must be an object" % word)
        for key, value in fields.items():
            if key in GROUP_FIELDS + ("intent_group", "reviewer", "initial_decision", "matched_terms", "initial_reason"):
                record[key] = value
        if record.get("initial_decision") is None:
            record["initial_decision"] = record.get("decision")
    atomic_write(run / DECISIONS, decisions)
    remaining = sum(r.get("decision") is None for r in records)
    return {"applied": len(assigned), "overrides": len(overrides), "unreviewed": remaining}


def keyword_metrics(raw):
    metrics = {}
    for value in raw.get("raw", {}).get("keyword_data", []) if isinstance(raw.get("raw"), dict) else []:
        if isinstance(value, dict) and isinstance(value.get("keyword"), str):
            metrics.setdefault(norm(value["keyword"]), value)
    return metrics


def _searches(metric):
    value = metric.get("searches", metric.get("monthly_searches")) if isinstance(metric, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def write_view(run):
    """Compact traffic-sorted table for reading the ledger instead of the verbose JSON."""
    decisions, raw = read_json(run / DECISIONS), read_json(run / RAW)
    metrics = keyword_metrics(raw)
    rows = []
    for record in all_records(decisions):
        metric = metrics.get(record["normalized"], {})
        traffic = metric.get("trafficPercentage", metric.get("traffic_percentage"))
        rows.append((_searches(metric), record["keyword"], "" if traffic is None else traffic,
                     record.get("decision") or "-", record.get("intent_group") or "-", record["origin"]))
    rows.sort(key=lambda row: (row[0] is None, -(row[0] or 0)))
    lines = ["keyword\tsearches\ttraffic_pct\tdecision\tgroup\torigin"]
    lines += ["\t".join(["" if v is None else str(v) for v in (row[1], row[0], row[2], row[3], row[4], row[5])]) for row in rows]
    (run / "03_keyword_view.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"rows": len(rows), "unreviewed": sum(row[3] == "-" for row in rows), "file": "03_keyword_view.tsv"}


def all_records(decisions):
    if not isinstance(decisions, dict):
        raise ValueError("Decision ledger must be an object")
    result = []
    for key in ("records", "supplemental_terms"):
        if not isinstance(decisions.get(key), list) or any(not isinstance(item, dict) for item in decisions[key]):
            raise ValueError(key + " must contain objects")
        result.extend(decisions[key])
    return result


def status_result(issues, **extra):
    status = "failed" if any(i["severity"] == "error" for i in issues) else "incomplete" if any(i["severity"] == "incomplete" for i in issues) else "passed"
    return dict(status=status, issues=issues, **extra)


def check_decisions(profile, raw, decisions, source_fingerprints):
    issues = []
    def add(code, path, message, severity="error"):
        issues.append(dict(code=code, path=path, message=message, severity=severity))
    expected = source_records(raw)
    if decisions is None:
        add("keyword_audit_missing", DECISIONS, "缺少逐词审查；历史词表可读，但筛词尚未验收", "incomplete")
        return status_result(issues)
    records = all_records(decisions)
    if decisions.get("keyword_schema_version") not in ("1.0", VERSION):
        add("keyword_schema", DECISIONS, "关键词分类版本不受支持")
    if decisions.get("source_fingerprints") != source_fingerprints:
        add("keyword_source_stale", DECISIONS, "画像或原始词已变化，需重新核对分类与事实", "incomplete")
    actual_raw = decisions["records"]
    expected_projection = [{key: item[key] for key in ("keyword_id", "keyword", "normalized", "source_positions", "original_forms")} for item in expected]
    actual_projection = [{key: item.get(key) for key in ("keyword_id", "keyword", "normalized", "source_positions", "original_forms")} for item in actual_raw]
    if actual_projection != expected_projection:
        add("keyword_coverage", DECISIONS, "原始词必须按首次出现顺序全部且仅出现一次，完整保留重复位置与原词")
    variant_ids = [v.get("variant_id") for v in profile.get("variants", [])] if profile.get("listing_mode") == "family" else []
    facts, measures = {}, {}
    for owner_id, owner in [("all", profile)] + [(v.get("variant_id"), v) for v in profile.get("variants", [])]:
        for key, catalog, identity in (("facts", facts, "fact_id"), ("measurements", measures, "measurement_id")):
            for value in owner.get(key, []):
                identifier = value.get(identity)
                if identifier in catalog:
                    add("keyword_duplicate_fact", str(identifier), "事实或规格编号重复")
                catalog[identifier] = (owner_id, value)
    ids, normalized, groups = set(), set(), {}
    protected = profile.get("product_identity", {}).get("protected_terms", [])
    if not nonempty(profile.get("product_identity", {}).get("canonical_name")) or not isinstance(protected, list) or not protected or any(not nonempty(term) for term in protected):
        add("keyword_product_identity", PROFILE, "筛词前必须确认完整品名及非空必保短语")
        protected = []
    for index, item in enumerate(records):
        path = "keywords[%d]" % index
        word, identifier = item.get("keyword"), item.get("keyword_id")
        if not isinstance(word, str) or not nonempty(identifier):
            add("keyword_record", path, "关键词与稳定编号必须有效"); continue
        key = norm(word)
        if identifier in ids or key in normalized:
            add("keyword_duplicate", path, "同一个原词或补充词不能重复分类或跨来源绕过暂缓状态")
        ids.add(identifier); normalized.add(key)
        if item.get("normalized") != key:
            add("keyword_normalization", path, "规范化映射与原词不一致")
        origin = "raw" if index < len(actual_raw) else "product"
        if item.get("origin") != origin:
            add("keyword_origin", path, "原始词与本品补充词必须分开记录")
        if origin == "product" and (identifier != "product-" + digest(key)[:20] or not nonempty(item.get("source_ref"))):
            add("keyword_supplement", path, "补充词需要稳定编号和真实来源")
        initial, final = item.get("initial_decision"), item.get("decision")
        final_code = item.get("reason_code")
        if initial not in DECISION_CODES or final not in DECISION_CODES:
            add("keyword_unreviewed", path, "每个词必须完成可用、暂缓或剔除分类", "incomplete"); continue
        if final_code not in DECISION_CODES[final]:
            add("keyword_reason_code", path, "reason_code 必须对应当前 decision；修正分类时同步更新理由，不能使用片段命中或白名单外作为依据")
        for name in ("reason", "query_intent", "intent_group", "evidence", "reviewer"):
            if not nonempty(item.get(name)):
                add("keyword_basis_missing", path + "." + name, "需要完整搜索意图、逐词依据和审查者", "incomplete")
        if item.get("role") not in {"identity", "attribute", "intent", "synonym"} or item.get("label") not in {"high", "relevant"}:
            add("keyword_role", path, "角色和兼容相关性标签必须明确")
        scope = item.get("applies_to")
        valid_scope = isinstance(scope, list) and bool(scope) and all(isinstance(s, str) for s in scope) and len(set(scope)) == len(scope) and (scope == ["all"] or bool(variant_ids) and set(scope) <= set(variant_ids))
        if not valid_scope:
            add("keyword_scope", path, "适用范围必须是全系列或已提供的具体子体"); scope = []
        supported = item.get("identity_basis") is True
        confirmed_refs = 0
        uncertain_refs = 0
        if type(item.get("identity_basis")) is not bool:
            add("keyword_identity_basis", path, "identity_basis 必须是布尔值")
        for field, catalog in (("fact_ids", facts), ("measurement_ids", measures)):
            refs = item.get(field)
            if not isinstance(refs, list) or any(not nonempty(ref) for ref in refs) or len(set(refs)) != len(refs):
                add("keyword_references", path + "." + field, "引用必须是无重复编号数组"); continue
            for ref in refs:
                if ref not in catalog:
                    add("keyword_reference_missing", path, "引用不存在：" + ref); continue
                owner, fact = catalog[ref]
                if owner != "all" and (scope == ["all"] or any(target != owner for target in scope)):
                    add("keyword_fact_scope", path, "不能将子体事实提升到系列或串用给其他子体")
                confirmed = nonempty(fact.get("source_ref")) and (field == "measurement_ids" or fact.get("status") == "confirmed")
                supported |= confirmed
                confirmed_refs += int(confirmed)
                uncertain_refs += int(not confirmed)
                if final == "eligible" and not confirmed:
                    add("keyword_unknown_fact", path, "未知或冲突事实不能支持可用词")
        if final == "eligible" and not supported:
            add("keyword_evidence", path, "可用词需要已确认事实、规格或本品身份依据")
        if final == "eligible" and item.get("role") == "attribute" and not confirmed_refs:
            add("keyword_attribute_evidence", path, "属性词不能仅凭产品名称确认，必须引用已确认事实或规格")
        if final == "excluded":
            if final_code == "fact_conflict" and (not confirmed_refs or uncertain_refs):
                add("keyword_unknown_is_not_conflict", path, "事实未知不能当成事实冲突剔除，应暂缓核实")
            if final_code == "user_restriction" and not any(contains_phrase(word, term) for term in profile.get("forbidden_terms", []) if nonempty(term)):
                add("keyword_restriction_basis", path, "用户禁词剔除必须对应实际提供的完整禁用词或短语")
            if final_code == "unusable_query" and any(char.isalnum() for char in key):
                add("keyword_unusable_query", path, "含有效文字或数字的查询不能仅按乱码剔除；先修复或暂缓语义评估")
        if final == "deferred" and not nonempty(item.get("promotion_condition")):
            add("keyword_promotion", path, "暂缓词需要说明疑点及晋级条件", "incomplete")
        if initial != final and not nonempty(item.get("resolution")):
            add("keyword_resolution", path, "改变分类必须解释修正依据", "incomplete")
        if key in {norm(term) for term in protected} and final != "eligible":
            if final != "deferred" or final_code != "identity_conflict":
                add("keyword_identity_dropped", path, "核心品名不能因流量、缺席词表或词片段被删除")
            else:
                add("keyword_identity_conflict", path, "必保词与事实冲突尚未解决", "incomplete")
        if nonempty(item.get("intent_group")):
            groups.setdefault(item["intent_group"], []).append(item)
        for phrase in item.get("matched_terms", []):
            if not nonempty(phrase) or not contains_phrase(word, phrase):
                add("keyword_substring_match", path, "命中证据必须是完整词或短语，不能是单词内部片段")
    for term in protected:
        if norm(term) not in normalized:
            add("keyword_protected_missing", DECISIONS, "完整核心品名必须在原词或本品补充词中登记：" + term)
    for group, members in groups.items():
        if len({item.get("decision") for item in members}) > 1 and any(not nonempty(item.get("group_difference")) for item in members):
            add("keyword_intent_conflict", group, "同意图组分类不一致，必须逐项解释实际差异")
    counts = {decision: sum(item.get("decision") == decision for item in actual_raw) for decision in DECISION_CODES}
    counts.update(raw_records=len(source_words(raw)), unique=len(expected), duplicates=len(source_words(raw)) - len(expected),
                  supplemental=len(decisions["supplemental_terms"]))
    if sum(counts[k] for k in DECISION_CODES) != len(expected):
        add("keyword_count_conservation", DECISIONS, "可用＋暂缓＋剔除必须等于唯一原始词数", "incomplete")
    return status_result(issues, counts=counts)


def project_pools(decisions, raw):
    pools = {name: [] for name in POOLS.values()}
    tagged = []
    metrics = keyword_metrics(raw)
    for item in all_records(decisions):
        reason = item["reason"]
        if item["origin"] == "raw":
            entry = item["keyword"] if item["decision"] == "eligible" else {"keyword": item["keyword"], "reason": reason,
                    "reason_code": item["reason_code"],
                    "keyword_id": item["keyword_id"], "applies_to": item["applies_to"]}
            if item["decision"] == "deferred":
                entry["promotion_condition"] = item["promotion_condition"]
            pools[POOLS[item["decision"]]].append(entry)
        if item["decision"] == "eligible":
            metric = metrics.get(item["normalized"], {}) if item["origin"] == "raw" else {}
            tagged.append({key: item[key] for key in ("keyword_id", "keyword", "label", "role", "intent_group", "applies_to")} | {
                "reason": reason, "source": RAW if item["origin"] == "raw" else item["source_ref"],
                "origin": item["origin"], "searches": metric.get("searches", metric.get("monthly_searches")),
                "traffic_percentage": metric.get("trafficPercentage", metric.get("traffic_percentage")),
                "restrictions": item.get("restrictions", "")})
    pools["04_kw_tagged.json"] = tagged
    return pools


def scope_allows(record, targets):
    return record.get("applies_to") == ["all"] or set(targets) <= set(record.get("applies_to", []))


def check_usage(profile, decisions, title_keywords=None, qa=None, listing=None):
    issues = []
    def add(code, path, message):
        issues.append(dict(code=code, path=path, message=message, severity="error"))
    records = all_records(decisions)
    by_word = {r["normalized"]: r for r in records}
    variant_ids = {v.get("variant_id") for v in profile.get("variants", [])}
    def eligible(word, path, targets=None):
        item = by_word.get(norm(word)) if isinstance(word, str) else None
        if not item or item.get("decision") != "eligible":
            add("keyword_usage_quarantine", path, "只能使用可用词或有依据的本品补充词：" + str(word)); return
        if targets is not None and (not isinstance(targets, list) or not targets or any(not isinstance(t, str) for t in targets) or len(set(targets)) != len(targets) or (targets != ["all"] and not set(targets) <= variant_ids) or not scope_allows(item, targets)):
            add("keyword_usage_scope", path, "使用范围超出该词的真实适用子体")
    if title_keywords is not None:
        if not isinstance(title_keywords, dict):
            raise ValueError("Title keywords must be an object")
        candidates = title_keywords.get("title_keywords", {})
        if not isinstance(candidates, dict) or any(not isinstance(candidates.get(field), list) for field in ("high", "relevant")):
            add("keyword_candidates_shape", "title_keywords", "候选词需要 high/relevant 两个数组")
            candidates = candidates if isinstance(candidates, dict) else {}
        for field in ("high", "relevant"):
            words = candidates.get(field, [])
            if not isinstance(words, list):
                raise ValueError("Title candidate arrays are required")
            for word in words:
                eligible(word, "title_keywords." + field)
        placements = title_keywords.get("placement_plan", [])
        if not isinstance(placements, list):
            raise ValueError("Placement plan must be an array")
        if not placements:
            add("keyword_placement_missing", "placement_plan", "必须记录实际关键词投放计划，不能仅提供空对象")
        for index, entry in enumerate(placements):
            if not isinstance(entry, dict) or not nonempty(entry.get("target_field")) or not nonempty(entry.get("reason")):
                add("keyword_placement_shape", "placement_plan", "投放记录需要关键词、字段、范围和理由"); continue
            targets = entry.get("applies_to")
            if targets is None:
                add("keyword_usage_scope", "placement_plan[%d]" % index, "投放计划必须明确适用子体")
            eligible(entry.get("keyword"), "placement_plan[%d]" % index, targets)
            if any(marker in entry["target_field"] for marker in ("parent.", "shared_content")) and targets != ["all"]:
                add("keyword_usage_scope", "placement_plan[%d]" % index, "父体及共用正文不能使用子体专属词")
        declared_protected = title_keywords.get("protected_terms", [])
        if not isinstance(declared_protected, list) or any(not nonempty(word) for word in declared_protected):
            add("keyword_protected_shape", "protected_terms", "必保词必须是完整短语数组")
            declared_protected = []
        if not {norm(word) for word in profile.get("product_identity", {}).get("protected_terms", [])} <= {norm(word) for word in declared_protected}:
            add("keyword_protected_missing", "protected_terms", "投放计划不得遗漏产品画像中的必保核心短语")
        for word in declared_protected:
            eligible(word, "protected_terms", ["all"])
    if qa is not None:
        if not isinstance(qa, dict):
            raise ValueError("Enhanced QA must be an object")
        for word in qa.get("requested_keywords", []):
            eligible(word, "qa.requested_keywords")
    if listing is not None:
        if not isinstance(listing, dict):
            raise ValueError("Listing must be an object")
        if profile.get("listing_mode") == "family":
            shared = listing.get("shared_content", {})
            contents = [("all", shared)] + [(v.get("variant_id"), dict(shared, **v.get("content_overrides", {}))) for v in listing.get("variants", [])]
        else:
            contents = [("all", listing)]
        for target, content in contents:
            text = content.get("search_terms", "")
            if not isinstance(text, str):
                continue  # Existing listing validator owns field-shape errors.
            allowed_spans = [span for r in records if r.get("decision") == "eligible" and scope_allows(r, [target]) for span in phrase_spans(text, r["keyword"])]
            for item in records:
                if item.get("decision") == "eligible" and scope_allows(item, [target]):
                    continue
                spans = phrase_spans(text, item["keyword"])
                # A shorter ambiguous phrase inside a supported complete phrase is
                # not a new search-intent claim (cat door vs cat door corner).
                if any(not any(a <= start and end <= b and (a < start or end < b) for a, b in allowed_spans) for start, end in spans):
                    add("keyword_search_terms_quarantine", str(target) + ".search_terms", "后台词出现暂缓、剔除或其他子体的完整词组：" + item["keyword"])
    return issues


POLICY = Path(__file__).resolve().parents[1] / "knowledge" / "quality_policy.json"
FIELD_ORDER = ("title", "item_highlight", "bullets[0]", "bullets[1]", "bullets[2]", "bullets[3]", "bullets[4]",
               "description", "search_terms")
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def _tokens(text):
    """Word set used for A9-style matching: case-folded, simple English plural folding."""
    words = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", norm(text))
    return {w[:-2] if len(w) > 4 and w.endswith("es") and w[-3] in "sxz" else w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
            for w in words}


def _fields(content):
    result = {}
    for field in FIELD_ORDER:
        if field.startswith("bullets["):
            bullets = content.get("bullets") if isinstance(content.get("bullets"), list) else []
            index = int(field[8])
            value = bullets[index] if index < len(bullets) else None
        else:
            value = content.get(field)
        if isinstance(value, str):
            result[field] = value
    return result


def _targets(profile, listing):
    """[(target, field-prefix map, content)] with family content resolved per child."""
    if profile.get("listing_mode") != "family":
        return [("single", {f: f for f in FIELD_ORDER}, listing)]
    shared = listing.get("shared_content", {}) if isinstance(listing.get("shared_content"), dict) else {}
    result = []
    for variant in listing.get("variants", []):
        if not isinstance(variant, dict):
            continue
        vid, overrides = variant.get("variant_id"), variant.get("content_overrides") or {}
        content = dict(shared, **{k: v for k, v in overrides.items() if k in ("bullets", "description", "search_terms")})
        content.update(title=variant.get("title"), item_highlight=variant.get("item_highlight"))
        prefixes = {}
        for field in FIELD_ORDER:
            base = field.split("[")[0]
            if base in ("title", "item_highlight") or base in overrides:
                prefixes[field] = "variants.%s.%s" % (vid, field)
            else:
                prefixes[field] = "shared_content." + field
        result.append((vid, prefixes, content))
    return result


def coverage(run, write_placement=False):
    """Deterministic SEO feedback: where eligible keywords are indexed and what is still missing.

    It is advisory (never a completion gate) so it cannot start a repair loop.
    """
    profile, raw, decisions, listing = [read_json(run / name) for name in (PROFILE, RAW, DECISIONS, "07_listing.json")]
    qa = read_json(run / "06_qa.json", required=False)
    policy = read_json(POLICY)
    site = profile.get("site")
    byte_limit = policy["sites"].get(site, {}).get("search_terms_max_bytes", policy["default_limits"]["search_terms_max_bytes"])
    metrics = keyword_metrics(raw)
    records = all_records(decisions)
    eligible = [r for r in records if r.get("decision") == "eligible"]
    quarantined = [r for r in records if r.get("decision") in ("deferred", "excluded")]
    report = {"site": site, "targets": {}, "intent_map": [], "fact_unlocks": [], "unsupported_questions": []}
    placements = []
    for target, prefixes, content in _targets(profile, listing):
        fields = _fields(content)
        joined = " ".join(fields.values())
        index_tokens = _tokens(joined)
        title_tokens = _tokens(fields.get("title", ""))
        rows, known, covered_searches = [], 0, 0
        for record in eligible:
            if not (record.get("applies_to") == ["all"] or target in record.get("applies_to", [])):
                continue
            word = record["keyword"]
            searches = _searches(metrics.get(record["normalized"], {})) if record["origin"] == "raw" else None
            phrase_fields = [f for f, text in fields.items() if contains_phrase(text, word)]
            words = _tokens(word)
            token_covered = norm(word) in norm(joined) if CJK.search(word) else bool(words) and words <= index_tokens
            in_title = norm(word) in norm(fields.get("title", "")) if CJK.search(word) else bool(words) and words <= title_tokens
            rows.append({"keyword": word, "searches": searches, "phrase_fields": phrase_fields,
                         "token_covered": token_covered, "title_tokens_covered": in_title})
            if searches is not None:
                known += searches
                covered_searches += searches if token_covered else 0
            for field in phrase_fields:
                placements.append((prefixes[field], word, target, record))
        rows.sort(key=lambda row: (row["searches"] is None, -(row["searches"] or 0)))
        search_terms = fields.get("search_terms", "")
        repeated = sorted(_tokens(search_terms) & title_tokens) if not CJK.search(search_terms) else []
        hits = []
        for record in quarantined:
            spans = [f for f, text in fields.items() if contains_phrase(text, record["keyword"])
                     and not any(contains_phrase(text, e["keyword"]) and contains_phrase(e["keyword"], record["keyword"]) and e is not record for e in eligible)]
            if spans:
                hits.append({"keyword": record["keyword"], "decision": record["decision"], "fields": spans})
        report["targets"][str(target)] = {
            "eligible": len(rows),
            "phrase_covered": sum(bool(r["phrase_fields"]) for r in rows),
            "token_covered": sum(r["token_covered"] for r in rows),
            "searches_weighted_token_coverage": round(covered_searches / known, 4) if known else None,
            "top_uncovered": [r for r in rows if not r["token_covered"]][:30],
            "top10_in_title": [r["keyword"] for r in rows[:10] if r["title_tokens_covered"]],
            "search_terms": {"bytes": len(search_terms.encode("utf-8")), "limit": byte_limit,
                             "words_repeated_from_title": repeated},
            "quarantined_phrase_hits": hits,
        }
    # COSMO-style intent relations: each confirmed relation should be stated somewhere indexable.
    targets = _targets(profile, listing)
    for entry in profile.get("intent_map", []) if isinstance(profile.get("intent_map"), list) else []:
        if not isinstance(entry, dict) or not nonempty(entry.get("expression")):
            continue
        scope = entry.get("applies_to") or ["all"]
        found = {str(t): [f for f, text in _fields(c).items() if contains_phrase(text, entry["expression"])]
                 for t, _, c in targets if scope == ["all"] or t in scope}
        report["intent_map"].append({"relation": entry.get("relation"), "expression": entry["expression"],
                                     "expressed_in": found, "missing_for": sorted(t for t, f in found.items() if not f)})
    # Facts that would unlock deferred traffic, ranked by searches.
    unlocks = {}
    for record in records:
        if record.get("decision") != "deferred":
            continue
        key = record.get("promotion_condition") or record.get("intent_group") or record["keyword"]
        item = unlocks.setdefault(key, {"fact_needed": key, "keywords": [], "searches": 0})
        item["keywords"].append(record["keyword"])
        item["searches"] += _searches(metrics.get(record["normalized"], {})) or 0
    report["fact_unlocks"] = sorted(unlocks.values(), key=lambda item: -item["searches"])
    if isinstance(qa, dict):
        report["unsupported_questions"] = [r.get("question") for r in qa.get("question_reviews", [])
                                           if isinstance(r, dict) and r.get("disposition") == "unsupported"]
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write(run / "07_keyword_coverage.json", report)
    if write_placement:
        title_keywords = read_json(run / "05_title_keywords.json")
        plan, seen = [], set()
        for field, word, target, record in placements:
            shared = not field.startswith("variants.")
            applies = ["all"] if shared or profile.get("listing_mode") != "family" else [target]
            if shared and record.get("applies_to") != ["all"]:
                continue  # Scope problems stay visible in check/usage review, never silently planned.
            key = (field, norm(word))
            if key not in seen:
                seen.add(key)
                plan.append({"keyword": word, "target_field": field, "applies_to": applies,
                             "reason": "coverage 工具按最终文案中的完整短语位置生成"})
        title_keywords["placement_plan"] = plan
        atomic_write(run / "05_title_keywords.json", title_keywords)
        report["placement_entries"] = len(plan)
    return report


def check_run(run, require_exports=True, downstream=True):
    """Recompute evidence from source files; never trust a cached 'passed' flag."""
    names = (PROFILE, RAW, DECISIONS) + tuple(POOLS.values()) + ("04_kw_tagged.json",) + DOWNSTREAM
    before = fingerprints(run, names)
    if before[RAW] is None or before[DECISIONS] is None:
        return status_result([dict(code="keyword_audit_missing", path=DECISIONS, message="缺少新版筛词审查，历史结果仅兼容展示", severity="incomplete")], fingerprints=before)
    try:
        profile, raw, decisions = [read_json(run / name) for name in (PROFILE, RAW, DECISIONS)]
        result = check_decisions(profile, raw, decisions, {name: before[name] for name in (PROFILE, RAW)})
        if result["status"] == "passed":
            if require_exports:
                for name, expected in project_pools(decisions, raw).items():
                    actual = read_json(run / name, required=False)
                    if actual != expected:
                        result["issues"].append(dict(code="keyword_export_mismatch", path=name, message="词池或标注与审查记录不一致；必须通过统一工具导出", severity="error"))
            if downstream:
                if before["07_listing.json"] is not None and before["05_title_keywords.json"] is None:
                    result["issues"].append(dict(code="keyword_placement_missing", path="05_title_keywords.json", message="已有 Listing 但缺少候选及实际投放计划", severity="incomplete"))
                result["issues"].extend(check_usage(profile, decisions, *[read_json(run / name, required=False) for name in DOWNSTREAM]))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return status_result([dict(code="keyword_data_invalid", path=str(run), message="筛词数据格式无效：" + type(error).__name__, severity="error")], fingerprints=before)
    if before != fingerprints(run, names):
        result["issues"].append(dict(code="keyword_changed_during_check", path=str(run), message="检查期间文件发生变化", severity="incomplete"))
    return status_result(result["issues"], counts=result.get("counts"), fingerprints=before, review_policy="final_usage_only",
                         limitations="机器校验覆盖结构、词边界、来源和隔离；完整语义及自然文案中的关键词使用仍须人工或模型复审。")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "view", "apply", "check", "export", "rebind", "coverage"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--groups", type=Path, help="apply: intent-group judgement file")
    parser.add_argument("--reviewed", action="store_true", help="rebind: affected keywords were rechecked")
    parser.add_argument("--write-placement", action="store_true", help="coverage: rewrite 05 placement_plan from the final copy")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            value = prepare(args.run_dir)
            view = write_view(args.run_dir)
            print(json.dumps({"prepared": True, "records": len(value["records"]), "view": view["file"]}, ensure_ascii=False)); return 0
        if args.command == "view":
            print(json.dumps(write_view(args.run_dir), ensure_ascii=False)); return 0
        if args.command == "apply":
            if args.groups is None:
                raise ValueError("apply requires --groups FILE")
            summary = apply_groups(args.run_dir, args.groups)
            write_view(args.run_dir)
            print(json.dumps(summary, ensure_ascii=False)); return 0
        if args.command == "rebind":
            result = rebind(args.run_dir, args.reviewed)
            print(json.dumps(result, ensure_ascii=False)); return 0 if result["rebound"] or not result["affected"] else 1
        if args.command == "coverage":
            report = coverage(args.run_dir, args.write_placement)
            summary = {target: {k: v for k, v in item.items() if k in ("eligible", "token_covered", "searches_weighted_token_coverage")}
                       | {"uncovered_top5": [r["keyword"] for r in item["top_uncovered"][:5]],
                          "search_terms_bytes": "%d/%d" % (item["search_terms"]["bytes"], item["search_terms"]["limit"])}
                       for target, item in report["targets"].items()}
            summary["intent_missing"] = [e["expression"] for e in report["intent_map"] if e["missing_for"]]
            summary["fact_unlocks_top3"] = [u["fact_needed"] for u in report["fact_unlocks"][:3]]
            print(json.dumps(summary, ensure_ascii=False)); return 0
        has_exports = any((args.run_dir / name).exists() for name in POOLS.values())
        result = check_run(args.run_dir, require_exports=has_exports if args.command == "check" else False, downstream=args.command == "check")
        if args.command == "export" and result["status"] == "passed":
            decisions, raw = [read_json(args.run_dir / name) for name in (DECISIONS, RAW)]
            expected = project_pools(decisions, raw)
            if result["fingerprints"] != fingerprints(args.run_dir, result["fingerprints"]):
                raise ValueError("Inputs changed after validation")
            for name, value in expected.items():
                atomic_write(args.run_dir / name, value)
            result = check_run(args.run_dir, require_exports=True, downstream=False)
        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        result["stage"] = "classification_and_exports" if args.command == "export" else "keyword_check"
        atomic_write(args.run_dir / VALIDATION, result)
        print(json.dumps({"status": result["status"], "counts": result.get("counts"), "issues": result["issues"]}, ensure_ascii=False))
        return 0 if result["status"] == "passed" else 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        print("Keyword operation failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
