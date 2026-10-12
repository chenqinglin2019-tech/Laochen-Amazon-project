"""Offline evidence contracts, review cache and adequacy checks.

No network or model calls are made here. Rule suggestions never stand in for an
Agent's semantic review. Imported decisions are bound to the original text,
saved context and taxonomy; changes require a fresh review.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_THRESHOLDS = {
    "pilot": 300, "checkpoint": 3000, "target": 10000, "segment": 1000,
    "known_authors": 20, "contexts": 5, "channels": 2,
    "saturation_batches": 3, "saturation_batch_size": 200,
    "new_topic_ratio": 0.05, "stable_top_topics": 8,
}
SOURCE_KINDS = {"social", "review", "after_sales", "research_signal", "alexa", "rufus"}
ACCEPTED_CODING_METHODS = {"agent_reviewed", "model_reviewed", "rule_classified"}
UNKNOWN_AUTHORS = {"unknown", "anonymous", "[deleted]", "deleted", "[removed]", "removed", "none", "null", "n/a"}
KANO_TYPES = {"必备型", "期望型", "魅力型", "无差异型", "反向型"}
KANO_REVIEW_VERSION = "1.0.0"
KANO_NON_ATTRIBUTE_CODES = {"general_purchase_selection", "general_satisfaction"}
KANO_REVIEW_STATES = {"unreviewed", "classified", "insufficient", "conflict"}


class EvidenceError(ValueError):
    pass


def validate_kano_review(need: Mapping[str, Any], *, require_current: bool = True) -> None:
    """Validate review state without inventing a category for missing evidence.

    Legacy needs without review metadata remain readable. Older explicit review
    versions can be read by reconciliation, but do not vote in current results.
    """
    status, version, kind = (need.get(key) for key in
                             ("kano_review_status", "kano_review_version", "kano_type"))
    reason = str(need.get("kano_reason") or "").strip()
    if status is None:
        if version is not None:
            raise EvidenceError("KANO规则版本不能缺少复核状态")
    else:
        if status not in KANO_REVIEW_STATES or not isinstance(version, str) or not version.strip():
            raise EvidenceError("KANO复核状态或规则版本无效")
        if require_current and version != KANO_REVIEW_VERSION:
            raise EvidenceError("KANO复核规则已更新，需重新复核")
        if status != "unreviewed" and not reason:
            raise EvidenceError("已完成KANO复核必须记录判断或无法分类的原因")
        if status == "classified":
            if version == KANO_REVIEW_VERSION and need.get("code") in KANO_NON_ATTRIBUTE_CODES:
                raise EvidenceError("购买/满意汇总不是具体产品属性，需细化需求或标注KANO信息不足")
            if kind not in KANO_TYPES:
                raise EvidenceError("classified状态必须提供有效KANO类型")
        elif kind is not None:
            raise EvidenceError("只有classified状态允许提供KANO类型")
    if kind is not None and (kind not in KANO_TYPES or not reason):
        raise EvidenceError("KANO必须是五类中文且给出对应引文解释")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def source_kind(row: Mapping[str, Any]) -> str:
    raw = row.get("raw_json") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    if not isinstance(raw, Mapping):
        raw = {}
    if str(row.get("evidence_kind") or raw.get("evidence_kind") or "").casefold() in {"research_signal", "model_summary"}:
        return "research_signal"
    marker_candidates = [raw]
    for _ in range(5):
        if any(str(item.get("evidence_kind") or "").casefold() in {"research_signal", "model_summary"} for item in marker_candidates):
            return "research_signal"
        marker_candidates = [child for item in marker_candidates for child in item.values() if isinstance(child, Mapping)]
    kind = str(row.get("source_kind") or raw.get("source_kind") or "").casefold()
    if kind in SOURCE_KINDS:
        return kind
    candidates = [raw]
    for _ in range(4):
        children = []
        for candidate in candidates:
            if str(candidate.get("evidence_kind") or "").casefold() in {"research_signal", "model_summary"}:
                return "research_signal"
            for key in ("provenance", "payload", "original"):
                nested = candidate.get(key)
                if isinstance(nested, Mapping):
                    kind = str(nested.get("source_kind") or "").casefold()
                    if kind in SOURCE_KINDS:
                        return kind
                    children.append(nested)
        candidates = children
    source = str(row.get("source") or row.get("platform") or "").casefold()
    if source in {"after_sales", "support", "returns", "customer_service"}:
        return "after_sales"
    if source in {"amazon", "amazon_review", "amazon_reviews", "amazon.com", "review", "reviews", "walmart", "target", "bestbuy"}:
        return "review"
    return "social"


def known_author(value: Any) -> bool:
    text = str(value or "").strip().casefold()
    # Platform prefixes do not turn deleted accounts into identifiable authors.
    last = text.rsplit(":", 1)[-1]
    return bool(text and last not in UNKNOWN_AUTHORS and not text.startswith(("unknown:", "anonymous:", "record:")))


def context_key(value: Any) -> bool:
    return bool(value and not str(value).startswith(("record:", "unknown:")))


def load_entries(paths: Sequence[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix.casefold() == ".jsonl":
                rows = [json.loads(line) for line in text.splitlines() if line.strip()]
            else:
                value = json.loads(text)
                rows = value.get("entries", []) if isinstance(value, Mapping) else value
        except (OSError, ValueError) as exc:
            raise EvidenceError("无法读取编码导入文件：%s" % path) from exc
        if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
            raise EvidenceError("编码文件必须是 JSONL 对象或 {entries:[...]}：%s" % path)
        entries.extend(rows)
    return entries


def review_input(row: Mapping[str, Any], text: str, context: Sequence[Mapping[str, Any]], taxonomy_hash: str) -> dict[str, Any]:
    identity = str(row.get("hard_key") or row.get("record_id") or "")
    payload = {
        "hard_identity": identity,
        "platform": str(row.get("source") or "unknown"),
        "source_kind": source_kind(row),
        "text_sha256": text_digest(text),
        "context_sha256": digest(list(context)),
        "taxonomy_sha256": taxonomy_hash,
    }
    return {**payload, "record_id": str(row["record_id"]), "cache_key": digest(payload), "text": text, "saved_context": list(context)}


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise EvidenceError("%s 必须是非空字符串组成的数组" % label)
    if len(value) != len(set(value)):
        raise EvidenceError("%s 不允许重复项" % label)
    return value


def validate_entry(entry: Mapping[str, Any], record: Mapping[str, Any], semantics: Sequence[str], segment_ids: set[str]) -> dict[str, Any]:
    if entry.get("record_id") != record.get("record_id"):
        raise EvidenceError("编码record_id与当前输入不匹配")
    for key in ("cache_key", "hard_identity", "text_sha256", "context_sha256", "taxonomy_sha256"):
        if entry.get(key) != record.get(key):
            raise EvidenceError("编码与当前原文/上下文/词典不匹配：%s.%s" % (record["record_id"], key))
    if any(not isinstance(entry.get(key), str) or not entry[key].strip() for key in ("reviewed_by", "reason")):
        raise EvidenceError("每条编码必须标明 reviewed_by 和 reason")
    decision = entry.get("decision")
    if decision not in {"include", "exclude", "undetermined"}:
        raise EvidenceError("编码 decision 只能是 include/exclude/undetermined")
    clean: dict[str, Any] = {key: entry[key] for key in ("cache_key", "hard_identity", "text_sha256", "context_sha256", "taxonomy_sha256", "reviewed_by", "reason", "decision")}
    clean["record_id"] = record["record_id"]
    clean["reviewed_at"] = str(entry.get("reviewed_at") or "")
    method = entry.get("coding_method", "agent_reviewed")
    if method not in ACCEPTED_CODING_METHODS:
        raise EvidenceError("编码来源无效")
    if method == "rule_classified" and not entry.get("rule_version"):
        raise EvidenceError("规则编码必须绑定规则版本")
    clean.update(coding_method=method, rule_version=entry.get("rule_version"), processing_status="completed")
    if entry.get("review_payload_sha256"):
        clean.update(review_payload_sha256=entry["review_payload_sha256"],
                     reviewed_segment_indices=entry.get("reviewed_segment_indices", []))
    if decision != "include":
        return clean
    if record.get("identity_verified") is False:
        raise EvidenceError("缺少可验证来源身份；需先完成身份核验")
    if record.get("source_kind") in {"research_signal", "alexa", "rufus"}:
        raise EvidenceError("研究资料与Alexa问答不能计入消费者VOC")
    codes = _strings(entry.get("semantic_codes"), "semantic_codes")
    if not codes or not set(codes).issubset(set(semantics)):
        raise EvidenceError("纳入编码必须归入至少一类固定语义")
    memberships = _strings(entry.get("segment_memberships", []), "segment_memberships")
    if not set(memberships).issubset(segment_ids):
        raise EvidenceError("编码引用了未选定的细分方向")
    context = entry.get("product_context")
    if not isinstance(context, Mapping) or context.get("basis") not in {"self", "saved_context"}:
        raise EvidenceError("纳入编码必须提供 product_context.basis 和原文 quote")
    quote = str(context.get("quote") or "").strip()
    if context["basis"] == "self":
        context_text = str(record["text"])
    else:
        context_text = next((str(item.get("text") or "") for item in record["saved_context"] if str(item.get("record_id")) == str(context.get("record_id"))), "")
    if not quote or quote not in context_text:
        raise EvidenceError("产品上下文引文必须能在本条或保存的上下文中找到")
    raw_needs = entry.get("needs")
    if not isinstance(raw_needs, list):
        raise EvidenceError("needs 必须为数组；一般相关表达可为空")
    needs = []
    seen = set()
    for item in raw_needs:
        if not isinstance(item, Mapping):
            raise EvidenceError("needs 每项必须是对象")
        code = str(item.get("need_id") or item.get("code") or "")
        label = str(item.get("label") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", code) or code in seen or not label:
            raise EvidenceError("开放需求必须有唯一有效 code 和 label")
        if not quote or quote not in str(record["text"]):
            raise EvidenceError("需求引文必须是完整原文中的真实片段")
        if item.get("stance") not in {"support", "counter", "mixed", "context"}:
            raise EvidenceError("needs.stance 必须是 support/counter/mixed/context")
        applicability = item.get("applicability", "unknown")
        if applicability not in {"current", "historical", "unknown"}:
            raise EvidenceError("applicability 必须是 current/historical/unknown")
        applicability_reason = str(item.get("applicability_reason") or "").strip()
        if applicability != "unknown" and not applicability_reason:
            raise EvidenceError("型号适用性判断必须说明结构/型号/场景依据")
        need = {"code": code, "need_id": code, "label": label, "quote": quote, "stance": item["stance"], "applicability": applicability, "applicability_reason": applicability_reason,
                "alternative_explanations": _strings(item.get("alternative_explanations", []), "alternative_explanations"),
                "serious": item.get("serious") is True, "novel": item.get("novel") is True}
        if item.get("opportunity_specific") is True:
            need["opportunity_specific"] = True
        kano = item.get("kano_type")
        review_status = item.get("kano_review_status")
        validate_kano_review(item)
        if review_status is not None:
            need.update(kano_review_status=review_status, kano_review_version=KANO_REVIEW_VERSION)
            if item.get("kano_reason"):
                need["kano_reason"] = str(item["kano_reason"])
        if kano is not None:
            need.update(kano_type=kano, kano_reason=str(item["kano_reason"]))
        needs.append(need)
        seen.add(code)
    scenarios = entry.get("scenarios", [])
    if not isinstance(scenarios, list):
        raise EvidenceError("scenarios 必须是数组")
    clean_scenarios = []
    for item in scenarios:
        if not isinstance(item, Mapping) or not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", str(item.get("code") or "")) or not str(item.get("label") or "").strip():
            raise EvidenceError("场景必须有 code/label")
        quote = str(item.get("quote") or "").strip()
        if not quote or quote not in str(record["text"]):
            raise EvidenceError("场景引文必须来自原文")
        clean_scenarios.append({"code": item["code"], "label": item["label"], "quote": quote})
    clean.update(semantic_codes=codes, segment_memberships=memberships, product_context=dict(context), needs=needs, scenarios=clean_scenarios)
    return clean


def _representative(voice: Mapping[str, Any]) -> dict[str, Any]:
    return {key: voice.get(key) for key in ("voice_id", "platform", "excerpt", "source_url", "published_at", "semantic_codes", "topic_codes")}


def need_metrics(voices: Sequence[Mapping[str, Any]], thresholds: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = defaultdict(list)
    for voice in voices:
        for need in voice.get("needs", []):
            groups[str(need.get("need_id") or need["code"])].append((voice, need))
    results = []
    for code, pairs in groups.items():
        mentioned_voices = {str(v["voice_id"]): v for v, _ in pairs}
        support = [(v, n) for v, n in pairs if n.get("stance") in {"support", "mixed"} and v.get("coding_method") in ACCEPTED_CODING_METHODS]
        counter = [(v, n) for v, n in pairs if n.get("stance") in {"counter", "mixed"} and v.get("coding_method") in ACCEPTED_CODING_METHODS]
        authors = {str(v["author_key"]) for v in mentioned_voices.values() if known_author(v.get("author_key"))}
        anonymous_voice_records = sum(
            1 for v in mentioned_voices.values()
            if not known_author(v.get("author_key"))
        )
        contexts = {str(v["thread_key"]) for v, _ in support if context_key(v.get("thread_key"))}
        channels = {str(v["platform"]) for v, _ in support if v.get("platform") not in {None, "", "unknown"}}
        applicability = {kind: sorted({str(v["voice_id"]) for v, n in support if n.get("applicability", "unknown") == kind}) for kind in ("current", "historical", "unknown")}
        refs = sorted({str(v["voice_id"]) for v, _ in support})
        eligible = bool(refs) and bool(applicability["current"])
        source_denominators = Counter(str(v.get("source_kind")) for v in voices)
        source_counts = Counter(str(v.get("source_kind")) for v in mentioned_voices.values())
        results.append({"code": code, "need_id": code, "label": str(pairs[0][1]["label"]), "count": len(mentioned_voices),
                        "share": len(mentioned_voices) / len(voices) if voices else 0.0,
                        "source_counts": dict(source_counts), "source_denominators": dict(source_denominators),
                        "source_shares": {k: n/source_denominators[k] for k,n in source_counts.items()},
                        "all_refs": sorted(mentioned_voices),
                        "eligible": eligible, "known_authors": len(authors), "contexts": len(contexts), "channels": len(channels), "platforms": sorted(channels),
                        "anonymous_author_voice_records": anonymous_voice_records,
                        "support_refs": refs, "counter_refs": sorted({str(v["voice_id"]) for v, _ in counter}),
                        "segment_ids": sorted({str(s) for v, _ in pairs for s in v.get("segment_memberships", [])}),
                        "applicability": applicability,
                        "alternative_explanations": sorted({str(x) for _, n in pairs for x in n.get("alternative_explanations", [])}),
                        "serious": any(n.get("serious") is True for _, n in pairs), "novel": any(n.get("novel") is True for _, n in pairs),
                        "representative_support": [_representative(v) for v, _ in support[:3]], "representative_counter": [_representative(v) for v, _ in counter[:3]],
                        "gaps": (["缺少当前产品适用依据"] if not applicability["current"] else [])})
    return sorted(results, key=lambda item: (-item["count"], item["code"]))


def saturation(voices: Sequence[Mapping[str, Any]], batch_order: Sequence[str], thresholds: Mapping[str, Any], batch_statuses: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Group consecutive completed collection batches into >=200 new voices.

    Grouping is deterministic from first discovery and saved batch execution
    order. An empty/failed batch interrupts the sequence. A short trailing
    group is retained as pending and can never certify saturation.
    """
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for voice in voices:
        identity = str(voice.get("hard_identity") or voice.get("voice_id") or "")
        if voice.get("coding_method") in ACCEPTED_CODING_METHODS and identity not in seen:
            groups[str(voice.get("first_batch_id") or "")].append(voice)
            seen.add(identity)
    cumulative: Counter[str] = Counter()
    rows = []
    pending: list[Mapping[str, Any]] = []
    source_ids: list[str] = []
    unstarted: list[str] = []

    def emit(children: Sequence[Mapping[str, Any]], ids: Sequence[str], completed: bool, reason: str) -> None:
        before = set(cumulative)
        previous_top = {code for code, _ in sorted(cumulative.items(), key=lambda item: (-item[1], item[0]))[:10]}
        added = {str(n["code"]) for v in children for n in v.get("needs", [])}
        for voice in children:
            cumulative.update({str(n["code"]) for n in voice.get("needs", [])})
        after_top = {code for code, _ in sorted(cumulative.items(), key=lambda item: (-item[1], item[0]))[:10]}
        ratio = len(added - before) / len(before) if before else None
        overlap = len(previous_top & after_top)
        passed = completed and len(children) >= thresholds["saturation_batch_size"] and ratio is not None and ratio <= thresholds["new_topic_ratio"] and overlap >= thresholds["stable_top_topics"]
        rows.append({"batch_id": "analysis_%04d" % (len(rows) + 1), "source_batch_ids": list(ids), "collection_completed": completed,
                     "new_valid_voices": len(children), "previous_topics": len(before), "new_topics": len(added - before),
                     "new_topic_ratio": round(ratio, 6) if ratio is not None else None, "stable_top_topics": overlap,
                     "passed": passed, "reason": reason})

    for batch_id in batch_order:
        children = groups.get(batch_id, [])
        # A queued query that has not run is not an empty/failed observation.
        # Otherwise adding optional future searches could revoke already
        # observed saturation and force spending until every queue is drained.
        if batch_statuses is not None and batch_statuses.get(batch_id) == "planned" and not children:
            unstarted.append(batch_id)
            continue
        completed = batch_statuses is None or batch_statuses.get(batch_id) == "completed"
        if not completed or not children:
            if pending:
                emit(pending, source_ids, False, "interrupted_before_minimum")
                pending, source_ids = [], []
            emit(children, [batch_id], False, "collection_incomplete" if not completed else "no_new_valid_voices")
            continue
        pending.extend(children)
        source_ids.append(batch_id)
        if len(pending) >= thresholds["saturation_batch_size"]:
            emit(pending, source_ids, True, "complete_increment")
            pending, source_ids = [], []
    if pending:
        emit(pending, source_ids, False, "pending_minimum_batch_size")
    size = thresholds["saturation_batches"]
    passed = len(rows) >= size and all(row["passed"] for row in rows[-size:])
    return {"status": "saturated" if passed else "not_saturated", "batches": rows, "unstarted_batch_ids": unstarted,
            "method": "按首次发现合并连续非空成功采集批次形成分析增量；不足200条的尾部、空批次或失败均不能证明饱和"}


def evaluate(voices: Sequence[Mapping[str, Any]], segments: Sequence[Mapping[str, Any]], batch_order: Sequence[str], review: Mapping[str, Any], *, thresholds: Mapping[str, Any] | None = None, required_scenarios: Sequence[str] = (), batch_statuses: Mapping[str, str] | None = None) -> dict[str, Any]:
    if thresholds is not None and not isinstance(thresholds, Mapping):
        raise EvidenceError("证据门槛必须是对象")
    if thresholds and set(thresholds) - set(DEFAULT_THRESHOLDS):
        raise EvidenceError("未知证据门槛字段")
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    if any(isinstance(limits[key], bool) or not isinstance(limits[key], int) or limits[key] < 1 for key in limits if key != "new_topic_ratio"):
        raise EvidenceError("数量门槛必须是正整数")
    if isinstance(limits["new_topic_ratio"], bool) or not isinstance(limits["new_topic_ratio"], (int, float)) or not 0 <= limits["new_topic_ratio"] <= 1:
        raise EvidenceError("new_topic_ratio 必须位于 0–1")
    if not limits["pilot"] <= limits["checkpoint"] <= limits["target"]:
        raise EvidenceError("必须满足 pilot <= checkpoint <= target")
    needs = need_metrics(voices, limits)
    sat = saturation(voices, batch_order, limits, batch_statuses)
    checks = []
    def check(code: str, label: str, passed: bool, observed: Any, required: Any) -> None:
        checks.append({"code": code, "label": label, "passed": bool(passed), "observed": observed, "required": required})
    check("quantity", "全品类数量底线", len(voices) >= limits["checkpoint"], len(voices), limits["checkpoint"])
    check("coding", "逐条语义复核完成", review.get("unreviewed_records") == 0, review.get("unreviewed_records"), 0)
    check("core_needs", "存在多来源独立支持的核心需求", any(n["eligible"] for n in needs), sum(n["eligible"] for n in needs), 1)
    segment_coverage = []
    for segment in segments:
        sid = str(segment["segment_id"])
        count = sum(sid in v.get("segment_memberships", []) for v in voices)
        segment_coverage.append({"segment_id": sid, "label": str(segment.get("feature") or sid), "count": count, "required": limits["segment"], "meets_quantity": count >= limits["segment"]})
    check("segment_candidates", "至少一个拟推荐细分达到样本底线", any(item["meets_quantity"] for item in segment_coverage), sum(item["meets_quantity"] for item in segment_coverage), 1)
    observed_scenarios = {str(s["code"]) for v in voices if v.get("coding_method") in ACCEPTED_CODING_METHODS for s in v.get("scenarios", [])}
    missing = sorted(set(required_scenarios) - observed_scenarios)
    check("scenarios", "预先定义的关键使用场景覆盖", bool(required_scenarios) and not missing, {"covered": sorted(observed_scenarios), "missing": missing}, list(required_scenarios) or "需在项目词典定义关键场景")
    checks[-1]["description"] = "已覆盖 %d 个场景，尚缺 %d 个预设关键场景" % (len(set(required_scenarios) & observed_scenarios), len(missing)) if required_scenarios else "尚未预先定义关键使用场景"
    check("saturation", "连续新增批次的需求饱和", sat["status"] == "saturated", sat["status"], "saturated")
    return {"status": "sufficient" if all(item["passed"] for item in checks) else "partial", "checks": checks,
            "gaps": [item["label"] for item in checks if not item["passed"]], "thresholds": limits,
            "saturation": sat, "needs": needs, "segment_coverage": segment_coverage,
            "next_step": "核对证据缺口", "representativeness": "历史兼容口径"}


def evaluate_single_segment(
    voices, segment, batch_order, review, *, social_policy, data_exhaustion=None,
    thresholds=None, required_scenarios=(), batch_statuses=None,
):
    """PRD v2: advisory source targets; processing/quality/gap checks remain gates."""
    accepted = [v for v in voices if v.get("coding_method") in ACCEPTED_CODING_METHODS]
    social = [v for v in accepted if v.get("source_kind") == "social"]
    reviews = [v for v in accepted if v.get("source_kind") == "review"
               and str(v.get("platform") or "").casefold() in {"amazon", "amazon_review", "amazon_reviews", "amazon.com", "reviews", "review"}]
    limits = {**DEFAULT_THRESHOLDS, "pilot": 200, "checkpoint": 6000, "target": 6000,
              "segment": 6000}
    needs = need_metrics(accepted, limits)
    observed = {s["code"] for v in accepted for s in v.get("scenarios", [])}
    gap = data_exhaustion if isinstance(data_exhaustion, Mapping) else {}
    gap_done = gap.get("status") in {"completed", "source_exhausted_after_two_gap_fill_rounds"} and bool(gap.get("rounds"))
    checks = []
    def check(code, label, passed, actual, required):
        checks.append(dict(code=code, label=label, passed=bool(passed), observed=actual, required=required,
                           blocking=code not in {"quantity", "amazon_quantity", "selected_segment_social_quantity"}))
    check("quantity", "有效VOC总数", len(reviews)+len(social) >= 6000, len(reviews)+len(social), 6000)
    check("amazon_quantity", "Amazon有效评论", len(reviews) >= 4000, len(reviews), 4000)
    check("selected_segment_social_quantity", "有效社媒声音", len(social) >= 2000, len(social), 2000)
    check("coding", "全量处理完成", review.get("unreviewed_records") == 0, review.get("unreviewed_records"), 0)
    check("quality", "质量抽检与问题闭环", review.get("quality_review_complete") is True,
          review.get("quality_review_complete"), True)
    check("scenarios", "关键场景查漏已记录", gap_done, gap.get("status"), "completed")
    platform_counts = Counter(v.get("platform") for v in social)
    authors = Counter(v.get("author_key") for v in social if known_author(v.get("author_key")))
    roots = Counter(v.get("thread_key") for v in social if context_key(v.get("thread_key")))
    n = len(social)
    concentration = dict(social_valid_voices=n, platform_count=len(platform_counts),
        largest_platform_share=max(platform_counts.values(), default=0)/n if n else 0,
        largest_author_share=max(authors.values(), default=0)/n if n else 0,
        largest_root_discussion_share=max(roots.values(), default=0)/n if n else 0,
        root_discussion_count=len(roots))
    return dict(status="sufficient" if all(c["passed"] for c in checks if c["blocking"]) else "partial",
        checks=checks, gaps=[c["label"] for c in checks if c["blocking"] and not c["passed"]], thresholds={**limits, "targets_are_advisory": True},
        needs=needs, segment_coverage=[dict(segment_id=segment["segment_id"], count=len(accepted),
            required=6000, meets_quantity=len(reviews)+len(social)>=6000)],
        saturation=dict(status="informational_only", batches=[], method="主题稳定性不作为硬门槛"),
        single_segment_social=dict(policy=dict(social_policy), data_exhaustion=dict(gap),
            downgrade_applied=False, concentration=concentration, concentration_alerts=[]),
        scenario_coverage=dict(observed=sorted(observed), missing=sorted(set(required_scenarios)-observed)),
        next_step="完成列明的处理、质量或采集缺口；数量达标不替代业务产物验收",
        representativeness="非概率样本；作者、讨论与平台集中度只用于披露")


def source_breakdown(voices: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    labels = {str(code): str(label) for voice in voices for code, label in zip(voice.get("topic_codes", []), voice.get("topic_labels", []))}
    for kind in ("social", "review", "after_sales"):
        children = [v for v in voices if v.get("source_kind") == kind]
        # Internal taxonomy aliases may share one consumer-facing label.  The
        # source overview must show one viewpoint row while retaining every
        # independently identified voice; a voice carrying two aliases counts
        # once in that row, and different authors/messages are never removed.
        topics: dict[str, dict[str, Any]] = {}
        for voice in children:
            voice_id = str(voice.get("voice_id") or voice.get("record_id") or "")
            raw_labels = {
                str(code): str(label)
                for code, label in zip(voice.get("topic_codes", []), voice.get("topic_labels", []))
                if str(label).strip()
            }
            for raw_code in voice.get("topic_codes", []):
                code = str(raw_code)
                label = labels.get(code) or raw_labels.get(code) or "待复核主题"
                bucket_key = code
                bucket = topics.setdefault(bucket_key, {"codes": set(), "voices": {}, "label": label})
                bucket["codes"].add(code)
                bucket["voices"][voice_id] = voice
        top_topics = []
        for _key, bucket in topics.items():
            count = len(bucket["voices"])
            top_topics.append({
                "code": sorted(bucket["codes"])[0],
                "label": bucket["label"],
                "count": count,
                "share": round(count / len(children), 6) if children else 0.0,
            })
        top_topics.sort(key=lambda item: (-int(item["count"]), str(item["label"])))
        result.append({"source_kind": kind, "count": len(children), "share": round(len(children) / len(voices), 6) if voices else 0.0,
                       "known_authors": len({str(v["author_key"]) for v in children if known_author(v.get("author_key"))}),
                       "contexts": len({str(v["thread_key"]) for v in children if context_key(v.get("thread_key"))}),
                       "platforms": sorted({str(v["platform"]) for v in children}),
                       "top_topics": top_topics[:10]})
    return result


def repetition_audit(voices: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Flag repeated text without deleting independently identified messages."""
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for voice in voices:
        groups[text_digest(re.sub(r"\s+", " ", str(voice.get("full_text") or voice["excerpt"]).strip().casefold()))].append(voice)
    repeated = [items for items in groups.values() if len(items) > 1]
    return {"duplicate_text_groups": len(repeated), "records_in_groups": sum(len(items) for items in repeated),
            "hard_identity_records_retained": True,
            "groups": [{"voice_refs": [v["voice_id"] for v in items], "known_authors": len({v["author_key"] for v in items if known_author(v.get("author_key"))}), "contexts": len({v["thread_key"] for v in items if context_key(v.get("thread_key"))})} for items in repeated]}
