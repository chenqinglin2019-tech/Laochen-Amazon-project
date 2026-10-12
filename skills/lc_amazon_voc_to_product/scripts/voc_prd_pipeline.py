"""Deterministic PRD rule execution and bounded review manifests; no API calls."""
from __future__ import annotations
import hashlib
import json
import math
import re
from collections import defaultdict

KANO_MIN_SHARE = 0.03
OPPORTUNITY_MIN_SHARE = 0.005


def _canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def unified_need_registry(voices, opportunity_records, denominator):
    """Build one versioned need registry from base coding and opportunity review.

    A voice/need pair is counted once.  The source judgments are retained in
    ``links`` so a later disagreement can be reviewed instead of allowing a
    last writer to overwrite an earlier coding decision.
    """
    if not isinstance(denominator, int) or denominator < 0:
        raise ValueError("denominator must be a non-negative integer")
    by_voice = {str(row.get("voice_id")): row for row in voices if isinstance(row, dict) and row.get("voice_id")}
    if len(by_voice) != len(voices):
        raise ValueError("voices require unique voice_id")
    reviewed = {str(row.get("voice_id")): row for row in opportunity_records if isinstance(row, dict) and row.get("voice_id")}
    if set(reviewed) != set(by_voice):
        raise ValueError("opportunity review must cover every accepted voice")

    needs = {}
    def add(voice_id, raw, origin):
        if not isinstance(raw, dict):
            return
        need_id = str(raw.get("need_id") or raw.get("code") or "").strip()
        label = str(raw.get("label") or "").strip()
        if not need_id or not label:
            raise ValueError("need requires stable need_id and label")
        stance = str(raw.get("stance") or "support")
        applicability = str(raw.get("applicability") or "unknown")
        if stance not in {"support", "counter", "mixed"}:
            raise ValueError("need stance is invalid")
        if applicability not in {"current", "future", "unknown"}:
            raise ValueError("need applicability is invalid")
        row = needs.setdefault(need_id, {"need_id": need_id, "code": need_id, "label": label,
            "links": {}, "origin": set(), "specific_opportunity": False, "design_hypothesis": False})
        if row["label"] != label:
            raise ValueError("one need_id must have one canonical label")
        link = row["links"].setdefault(voice_id, {"voice_id": voice_id, "judgments": []})
        link["judgments"].append({"origin": origin, "stance": stance, "applicability": applicability,
            "quote": str(raw.get("quote") or ""), "rationale": str(raw.get("rationale") or "")})
        row["origin"].add(origin)
        row["specific_opportunity"] = row["specific_opportunity"] or bool(raw.get("opportunity_specific", origin == "opportunity_review"))
        row["design_hypothesis"] = row["design_hypothesis"] or bool(raw.get("design_hypothesis", False))

    for voice_id, voice in by_voice.items():
        for need in voice.get("needs", []) if isinstance(voice.get("needs"), list) else []:
            add(voice_id, need, "base_coding")
    for voice_id, record in reviewed.items():
        if record.get("decision") != "specific_need":
            continue
        for need in record.get("needs", []) if isinstance(record.get("needs"), list) else []:
            add(voice_id, need, "opportunity_review")

    result = []
    for need_id, row in needs.items():
        links = []
        support, counter, mixed, current = set(), set(), set(), set()
        for voice_id, link in row["links"].items():
            judgments = link["judgments"]
            stances = {item["stance"] for item in judgments}
            applicable = {item["applicability"] for item in judgments}
            resolved_stance = "mixed" if "mixed" in stances or {"support", "counter"} <= stances else next(iter(stances))
            resolved_applicability = "current" if "current" in applicable else ("future" if "future" in applicable else "unknown")
            if resolved_stance in {"support", "mixed"}: support.add(voice_id)
            if resolved_stance in {"counter", "mixed"}: counter.add(voice_id)
            if resolved_stance == "mixed": mixed.add(voice_id)
            if resolved_applicability == "current": current.add(voice_id)
            links.append({"voice_id": voice_id, "stance": resolved_stance,
                "applicability": resolved_applicability, "judgments": judgments})
        all_refs = sorted(row["links"])
        count = len(all_refs)
        semantic_source_sha256 = _canonical_sha256({"need_id": need_id, "label": row["label"],
            "links": sorted(links, key=lambda item: item["voice_id"]), "denominator": denominator})
        result.append({"need_id": need_id, "code": need_id, "label": row["label"],
            "origin": sorted(row["origin"]), "all_refs": all_refs, "support_refs": sorted(support),
            "counter_refs": sorted(counter), "mixed_refs": sorted(mixed), "current_refs": sorted(current),
            "count": count, "denominator": denominator, "share": count / denominator if denominator else 0.0,
            "eligible": bool(support and current), "eligible_reason": "有支持原声且至少一条当前适用" if support and current else "缺少支持原声或当前适用证据",
            "specific_opportunity": row["specific_opportunity"], "design_hypothesis": row["design_hypothesis"],
            "links": sorted(links, key=lambda item: item["voice_id"]), "semantic_source_sha256": semantic_source_sha256})
    return sorted(result, key=lambda item: (-item["count"], item["need_id"]))


def need_evidence_sha256(need, voices, denominator, taxonomy_sha256):
    """Bind a holistic judgment to exact evidence, mapping and denominator."""
    ids = set(need.get("all_refs", []))
    payload = {"need_id": need["need_id"], "denominator": denominator,
               "taxonomy_sha256": taxonomy_sha256, "need": need,
               "voices": sorted((v for v in voices if v["voice_id"] in ids), key=lambda v: v["voice_id"])}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def holistic_kano(needs, voices, taxonomy_sha256, prior_rows=()):
    denominator = len(voices)
    previous = {r.get("need_id") or r.get("code"): r for r in prior_rows}
    rows, queue = [], []
    for need in needs:
        source_hash = need_evidence_sha256(need, voices, denominator, taxonomy_sha256)
        below = not denominator or need["count"] * 100 < denominator * 3
        row = {"need_id": need["need_id"], "code": need["need_id"], "label": need["label"],
               "count": need["count"], "share": need["count"] / denominator if denominator else 0,
               "denominator": denominator, "source_sha256": source_hash,
               "status": "below_threshold" if below else "pending", "classification": None,
               "rationale": "需求提及率低于3%，不进入KANO分析" if below else "",
               "evidence_ids": need["support_refs"], "counter_evidence_ids": need["counter_refs"],
               "applicable_scenarios": [], "validation_questions": []}
        prior = previous.get(need["need_id"], {})
        if not below and prior.get("source_sha256") == source_hash and prior.get("status") in {"classified", "insufficient", "conflict", "not_applicable"}:
            if prior.get("rationale") and (prior.get("classification") in {"M", "O", "A", "I", "R"} if prior["status"] == "classified" else prior.get("classification") is None):
                row.update({k: prior[k] for k in ("status", "classification", "rationale", "applicable_scenarios", "validation_questions") if k in prior})
        rows.append(row)
        if row["status"] == "pending":
            queue.append({"need_id": row["need_id"], "status": "pending", "evidence": need,
                          "source_sha256": source_hash, "denominator": denominator,
                          "taxonomy_sha256": taxonomy_sha256,
                          "instruction": "按具体need_id综合判断；完整读取证据与反证，不按逐评论投票"})
    return rows, queue


def results_sha256(entries):
    return hashlib.sha256(json.dumps(sorted(entries, key=lambda r: (r["record_id"], r["cache_key"])),
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def canonicalize_decision(decision, config):
    """Explicit versioned aliases unify need IDs, not consumers or records."""
    if not decision:
        return decision
    result = dict(decision)
    aliases = config.get("need_aliases", {})
    labels = config.get("need_labels", {})
    needs = {}
    for original in decision.get("needs", []):
        need = dict(original)
        code = need.get("need_id") or need.get("code")
        seen = set()
        while code in aliases:
            if code in seen:
                raise ValueError("need alias cycle")
            seen.add(code); code = aliases[code]
        need.update(code=code, need_id=code)
        if code in labels:
            need["label"] = labels[code]
        if code in needs:
            existing = needs[code]
            if existing["label"] != need["label"]:
                raise ValueError("alias needs require a single canonical label")
            if existing.get("stance") != need.get("stance"):
                existing["stance"] = "mixed"
        else:
            needs[code] = need
    if "needs" in decision:
        result["needs"] = list(needs.values())
    return result


def classify(record, config, segment_ids):
    """Only explicit versioned rules may produce final decisions; misses stay pending.

    Rules use literal phrases, not executable code. Each rule supplies required
    product phrases, phrases, reject_phrases, semantics and optional need metadata.
    Negated/ambiguous expressions must be separated into explicit rules.
    """
    text = record["text"]
    technical_reason = None
    if not any(c.isalnum() for c in text):
        technical_reason = "空内容或仅符号，不存在可分析文字"
    if record.get("source_kind") in {"research_signal", "alexa", "rufus"}:
        technical_reason = "研究资料或问答，非消费者VOC"
    if technical_reason:
        return {**{k: record[k] for k in ("record_id", "cache_key", "hard_identity", "text_sha256", "context_sha256", "taxonomy_sha256")},
            "decision": "exclude", "coding_method": "rule_classified", "rule_version": "technical-v1",
            "reviewed_by": "python:technical-v1", "reason": technical_reason}
    if not config or not config.get("version") or record.get("identity_verified") is False:
        return None
    folded = text.casefold()
    if re.search(r"\b(?:sponsored|affiliate|promo code|shop now|order now|paid promotion)\b", folded):
        return None
    matched = []
    for rule in config.get("rules", []):
        if not isinstance(rule, dict) or not rule.get("id"):
            raise ValueError("rule must have an id")
        phrases = rule.get("phrases", [])
        anchors = rule.get("product_phrases", [])
        if not phrases or not anchors:
            raise ValueError("rules require literal phrases and product_phrases")
        if any(not isinstance(s, str) or not s.strip() for s in phrases + anchors + rule.get("reject_phrases", [])):
            raise ValueError("rule phrases must be nonempty strings")
        if any(re.search(re.escape(s), text, re.IGNORECASE) for s in rule.get("reject_phrases", [])):
            continue
        if not any(re.search(re.escape(s), text, re.IGNORECASE) for s in phrases) or not any(re.search(re.escape(s), text, re.IGNORECASE) for s in anchors):
            continue
        if not rule.get("handles_negation") and re.search(r"\b(?:not|never|no|without|don't|doesn't|isn't)\b|不|没有|并非", folded):
            return None
        matched.append(rule)
    if not matched:
        return None
    decisions = {r.get("decision", "include") for r in matched}
    if len(decisions) != 1 or any(r.get("requires_review") for r in matched):
        return None
    decision = next(iter(decisions))
    base = {k: record[k] for k in ("record_id", "cache_key", "hard_identity", "text_sha256", "context_sha256", "taxonomy_sha256")}
    base.update(decision=decision, coding_method="rule_classified", rule_version=config["version"],
                reviewed_by="python:" + config["version"], reason="命中规则: " + ",".join(r["id"] for r in matched))
    if decision != "include":
        return base
    needs = {}
    for rule in matched:
        need = rule.get("need")
        if need:
            need = dict(need)
            code = need.get("need_id") or need.get("code")
            aliases = config.get("need_aliases", {})
            code = aliases.get(code, code)
            if code in needs and needs[code].get("stance") != need.get("stance"):
                return None
            match = next(m for p in rule["phrases"] if (m := re.search(re.escape(p), text, re.IGNORECASE)))
            need.update(code=code, need_id=code, quote=text[match.start():match.end()])
            needs[code] = need
    anchor = next(m for p in matched[0]["product_phrases"] if (m := re.search(re.escape(p), text, re.IGNORECASE)))
    base.update(semantic_codes=sorted({s for r in matched for s in r.get("semantic_codes", [])}),
                segment_memberships=sorted(segment_ids), product_context={"basis": "self", "quote": text[anchor.start():anchor.end()]},
                needs=list(needs.values()), scenarios=[])
    return base


def quality_sample(entries, source_by_id, seed="voc-prd-v1"):
    """Stable 5%, minimum50 per source plus one per decision/rule family."""
    groups = defaultdict(list)
    for entry in entries:
        if entry.get("coding_method") == "rule_classified":
            groups[source_by_id.get(entry["record_id"], "social")].append(entry)
    selected = {}
    for source, rows in groups.items():
        rows.sort(key=lambda r: hashlib.sha256((seed+r["cache_key"]).encode()).hexdigest())
        for row in rows[:max(50, math.ceil(len(rows)*.05))]:
            selected[row["cache_key"]] = row
        families = {}
        for row in rows:
            families.setdefault((row["decision"], row["reason"]), row)
        for row in families.values():
            selected[row["cache_key"]] = row
    return [selected[k] for k in sorted(selected)]


def review_batches(records, max_records=20, token_budget=8000):
    """Conservative byte-based token upper bound; never truncate. Oversize splits
    are manifests only: complete review needs all segment IDs before acceptance.
    """
    if not 1 <= max_records <= 20 or token_budget < 256:
        raise ValueError("invalid batch bounds")
    batches, pending, size = [], [], 0
    for row in records:
        payload = {k: v for k, v in row.items() if k not in {"rule_suggestions", "audit_sample", "decision"}}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        cost = len(encoded.encode())
        if cost > token_budget:
            if pending:
                batches.append({"records": pending, "estimated_token_upper_bound": size})
                pending, size = [], 0
            chunks, current = [], ""
            for char in encoded:
                if len((current+char).encode()) > token_budget//2:
                    chunks.append(current); current = ""
                current += char
            if current:
                chunks.append(current)
            for i, chunk in enumerate(chunks):
                batches.append({"record_id": row["record_id"], "cache_key": row["cache_key"],
                    "segment_index": i, "segment_count": len(chunks), "json_fragment": chunk,
                    "review_payload_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                    "requires_complete_parent_merge": True})
            continue
        if pending and (size+cost > token_budget or len(pending)>=max_records):
            batches.append({"records": pending, "estimated_token_upper_bound": size})
            pending, size = [], 0
        pending.append(row); size += cost
    if pending:
        batches.append({"records": pending, "estimated_token_upper_bound": size})
    return batches


def validate_batch_ids(inputs, outputs):
    expected = [r["record_id"] for r in inputs]
    actual = [r["record_id"] for r in outputs]
    if len(actual) != len(set(actual)) or len(expected) != len(set(expected)) or set(expected) != set(actual):
        raise ValueError("review batch missing, duplicate or unexpected record IDs")


def validate_segments(expected_count, reviewed_indices):
    if expected_count < 1 or sorted(reviewed_indices) != list(range(expected_count)):
        raise ValueError("long record is not completely reviewed")


def validate_long_review(record, entry):
    plan = review_batches([record])
    if not plan or not plan[0].get("requires_complete_parent_merge"):
        return
    if entry.get("review_payload_sha256") != plan[0]["review_payload_sha256"]:
        raise ValueError("long review is not bound to the complete payload")
    validate_segments(plan[0]["segment_count"], entry.get("reviewed_segment_indices", []))
