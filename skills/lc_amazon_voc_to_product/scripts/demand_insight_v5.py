#!/usr/bin/env python3
"""Local, reproducible V5 demand-insight sidecar builder.

No network, browser, credential, or existing collector authentication is used
here. Inputs are already selected market data, imported review/social records,
or an agent-authored question plan. The script validates the V5 contracts and
writes sidecars that can be audited without changing the legacy schemas.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

import single_segment_contract as single_segment


class ContractError(Exception):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_object(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("无法读取 JSON 输入：%s" % type(exc).__name__) from None
    if not isinstance(value, Mapping):
        raise ContractError("输入顶层必须是 JSON 对象")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(path))
    if os.name != "nt":
        os.chmod(str(path), 0o600)


def append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if os.name != "nt":
        os.chmod(str(path), 0o600)


def nonempty(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ContractError("缺少 %s" % label)
    return result


def list_of_mappings(value: Any, label: str) -> List[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ContractError("%s 必须是对象数组" % label)
    return list(value)


def plan_reviews(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    period = nonempty(payload.get("sales_stat_period"), "sales_stat_period")
    segments = list_of_mappings(payload.get("segments"), "segments")
    if not 1 <= len(segments) <= 3:
        raise ContractError("V5 只接受既有规则选出的 1–3 个细分，不补凑")
    seen_segment_ids: Set[str] = set()
    products: Dict[str, Dict[str, Any]] = {}
    result_segments: List[Dict[str, Any]] = []
    for raw in segments:
        segment_id = nonempty(raw.get("segment_id"), "segment_id")
        if segment_id in seen_segment_ids:
            raise ContractError("segment_id 重复：%s" % segment_id)
        seen_segment_ids.add(segment_id)
        if raw.get("valid") is not True:
            raise ContractError("细分必须已由既有 Top3 规则判定有效：%s" % segment_id)
        try:
            share = float(raw.get("listing_share"))
        except (TypeError, ValueError):
            raise ContractError("细分缺少 listing_share：%s" % segment_id) from None
        if not 0.03 <= share <= 0.20:
            raise ContractError("细分 Listing 占比不在既有 3%%–20%% 门槛内：%s" % segment_id)
        candidates = list_of_mappings(raw.get("candidates"), "candidates")
        if not candidates:
            raise ContractError("细分缺少头部商品候选：%s" % segment_id)
        parent_ids: Set[str] = set()
        selected: List[Dict[str, Any]] = []
        previous_sales: Optional[float] = None
        for raw_product in candidates[:3]:
            asin = nonempty(raw_product.get("asin"), "candidate.asin")
            parent_id = nonempty(raw_product.get("parent_id"), "candidate.parent_id")
            candidate_period = nonempty(raw_product.get("sales_stat_period") or period, "candidate.sales_stat_period")
            if candidate_period != period:
                raise ContractError("候选商品销量统计期与细分不一致：%s" % asin)
            if parent_id in parent_ids:
                raise ContractError("同一细分不能选择同父体变体：%s" % parent_id)
            parent_ids.add(parent_id)
            try:
                sales = float(raw_product.get("sales"))
            except (TypeError, ValueError):
                raise ContractError("候选商品缺少单 Listing 销量：%s" % asin) from None
            if previous_sales is not None and sales > previous_sales:
                raise ContractError("候选商品必须按同统计期单 Listing 销量降序提供：%s" % segment_id)
            previous_sales = sales
            item = {"asin": asin, "parent_id": parent_id, "sales": sales, "sales_stat_period": period}
            selected.append(item)
            product = products.setdefault(asin, {"asin": asin, "parent_id": parent_id, "sales_stat_period": period, "segment_ids": []})
            if product["parent_id"] != parent_id:
                raise ContractError("同一 ASIN 的父体信息冲突：%s" % asin)
            product["segment_ids"].append(segment_id)
        result_segments.append({
            "segment_id": segment_id,
            "listing_share": share,
            "sales_stat_period": period,
            "candidate_products": selected,
            "effective_text_review_target": 2000,
            "effective_text_review_ceiling": 3000,
            "top_up_allowed_only_if": ["predefined_review_answerable_scenario_gap", "documented_positive_negative_conflict_without_condition"],
            "top_up_gaps": list_of_mappings(raw.get("top_up_gaps", []), "top_up_gaps"),
            "collection_state": "pending",
            "stop_rule": "stop_after_first_candidate_that_reaches_target_without_documented_review_answerable_gap",
        })
    return {"schema_version": "v5-demand-insight-plan-1.0", "created_at": now_utc(), "sales_stat_period": period, "segments": result_segments, "unique_products": sorted(products.values(), key=lambda item: item["asin"]), "deduplication": "shared ASIN is requested once; different reviewId values are retained; repeated reviewId is deduplicated only within a segment statistic"}


def plan_single_segment(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Build the new selected-segment review/Alexa/social plan without I/O.

    ``plan-reviews`` remains the legacy Top3 entry.  This entry intentionally
    delegates ranking and scope validation to the dedicated contract instead
    of weakening the old parent-deduplication rules.
    """
    try:
        plan = single_segment.build_plan(payload)
    except single_segment.SingleSegmentContractError as exc:
        raise ContractError(str(exc)) from None
    return {
        key: value
        for key, value in plan.items()
        if key != "input_snapshot"
    } | {"created_at": now_utc()}


def single_segment_progress(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Local orchestration decision from validated processing counts, not hits."""
    try:
        gate = single_segment.collection_gate(payload.get("amazon_valid"), payload.get("social_valid"),
            processing_complete=payload.get("processing_complete") is True,
            quality_passed=payload.get("quality_passed") is True,
            gap_check_recorded=payload.get("gap_check_recorded") is True,
            approved_directions=payload.get("approved_directions", 0))
        plan = payload.get("sampling_plan")
        if not isinstance(plan, Mapping) or plan.get("workflow_mode") != "single_segment":
            raise ContractError("sampling_plan 必须是冻结单细分计划")
        completed = payload.get("completed_asins", [])
        if not isinstance(completed, list) or any(not isinstance(asin, str) for asin in completed):
            raise ContractError("completed_asins 必须是ASIN数组")
        next_asins = single_segment.next_review_asins(plan, completed, payload["amazon_valid"],
            current_batch_processed=payload.get("current_batch_processed") is True,
            evidence_gap=payload.get("evidence_gap") is True)
    except single_segment.SingleSegmentContractError as exc:
        raise ContractError(str(exc)) from None
    return {"schema_version": "single-segment-progress-2.0", "business_rules_version": "voc-prd-v2.1", "created_at": now_utc(),
            **gate, "next_review_asins": next_asins,
            "next_action": "stop_collection" if gate["can_stop"] else
                ("collect_next_review_batch" if next_asins else "complete_processing_or_fill_documented_gaps"),
            "network_executed": False}


def _record_id(record: Mapping[str, Any]) -> str:
    return nonempty(record.get("content_id") or record.get("reviewId") or record.get("id"), "record.content_id/reviewId/id")


def _record_text(record: Mapping[str, Any]) -> str:
    return str(record.get("text") or record.get("content") or record.get("title") or "").strip()


def _record_segments(record: Mapping[str, Any]) -> List[str]:
    values = record.get("segment_ids")
    if not isinstance(values, list) or not values:
        raise ContractError("每条记录必须有非空 segment_ids")
    return [nonempty(value, "record.segment_id") for value in values]


def summarize_voices(payload: Mapping[str, Any], source_kind: str) -> Mapping[str, Any]:
    records = list_of_mappings(payload.get("records"), "records")
    by_segment: Dict[str, Dict[str, Any]] = {}
    for record in records:
        actual_kind = str(record.get("source_kind") or source_kind).strip()
        if actual_kind != source_kind:
            continue
        record_id = _record_id(record)
        text = _record_text(record)
        status = str(record.get("coding_status") or "pending").strip()
        needs = record.get("needs") if isinstance(record.get("needs"), list) else []
        metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
        for segment_id in _record_segments(record):
            bucket = by_segment.setdefault(segment_id, {"interface_records": 0, "ids": set(), "text_ids": set(), "coded_text_ids": set(), "pending_text_ids": set(), "need_ids": defaultdict(set), "product_ids": defaultdict(set), "variant_unknown": set()})
            bucket["interface_records"] += 1
            bucket["ids"].add(record_id)
            if not text:
                continue
            bucket["text_ids"].add(record_id)
            if status == "coded":
                bucket["coded_text_ids"].add(record_id)
                seen_need_codes: Set[str] = set()
                for need in needs:
                    if not isinstance(need, Mapping):
                        continue
                    code = str(need.get("code") or need.get("need_code") or "").strip()
                    if code and code not in seen_need_codes:
                        bucket["need_ids"][code].add(record_id)
                        seen_need_codes.add(code)
            else:
                bucket["pending_text_ids"].add(record_id)
            product = str(metadata.get("request_asin") or record.get("asin") or "").strip()
            if product:
                bucket["product_ids"][product].add(record_id)
            if str(metadata.get("purchase_variant") or record.get("purchase_variant") or "unknown") == "unknown":
                bucket["variant_unknown"].add(record_id)
    summaries: List[Dict[str, Any]] = []
    for segment_id, bucket in sorted(by_segment.items()):
        denominator = len(bucket["coded_text_ids"])
        needs = []
        for code, ids in sorted(bucket["need_ids"].items()):
            count = len(ids)
            needs.append({"need_code": code, "mention_count": count, "share": (count / denominator if denominator else None), "denominator": denominator})
        summaries.append({
            "segment_id": segment_id,
            "interface_record_count": bucket["interface_records"],
            "unique_record_id_count": len(bucket["ids"]),
            "effective_text_record_count": len(bucket["text_ids"]),
            "coded_effective_text_record_count": denominator,
            "pending_review_count": len(bucket["pending_text_ids"]),
            "purchase_variant_unknown_count": len(bucket["variant_unknown"]) if source_kind == "review" else None,
            "product_distribution": [{"asin": asin, "unique_record_count": len(ids)} for asin, ids in sorted(bucket["product_ids"].items())],
            "needs": needs,
        })
    return {"schema_version": "v5-demand-insight-summary-1.0", "created_at": now_utc(), "source_kind": source_kind, "counting_contract": "same id is counted once per segment and per need; similar but different ids are retained; source summaries retain separate denominators", "segments": summaries}


def keyword_summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    keywords = list_of_mappings(payload.get("keywords"), "keywords")
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in keywords:
        segment_id = nonempty(item.get("segment_id"), "keyword.segment_id")
        grouped[segment_id].append({"keyword": nonempty(item.get("keyword"), "keyword.keyword"), "intent": nonempty(item.get("intent"), "keyword.intent"), "search_volume": item.get("search_volume"), "purchase_signal": item.get("purchase_signal"), "evidence_ref": nonempty(item.get("evidence_ref"), "keyword.evidence_ref")})
    return {"schema_version": "v5-demand-insight-keywords-1.0", "created_at": now_utc(), "segments": [{"segment_id": key, "keywords": value} for key, value in sorted(grouped.items())]}


def active_question_plan(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    questions = list_of_mappings(payload.get("questions"), "questions")
    initial: Counter[str] = Counter()
    followups: Counter[str] = Counter()
    seen_ids: Set[str] = set()
    normalized: List[Dict[str, Any]] = []
    for item in questions:
        question_id = nonempty(item.get("question_id"), "question.question_id")
        if question_id in seen_ids:
            raise ContractError("question_id 重复：%s" % question_id)
        seen_ids.add(question_id)
        segment_id = nonempty(item.get("segment_id"), "question.segment_id")
        phase = nonempty(item.get("phase"), "question.phase")
        if phase not in {"initial", "followup"}:
            raise ContractError("question.phase 只能是 initial 或 followup")
        (initial if phase == "initial" else followups)[segment_id] += 1
        source_refs = item.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            raise ContractError("问题必须有至少一个 source_refs")
        target = item.get("target")
        if not isinstance(target, Mapping) or not (str(target.get("asin") or "").strip() or str(target.get("keyword") or "").strip()):
            raise ContractError("问题 target 必须绑定 ASIN 或关键词")
        normalized.append({"question_id": question_id, "segment_id": segment_id, "phase": phase, "question": nonempty(item.get("question"), "question.question"), "source_refs": list(source_refs), "target": dict(target), "development_decision": nonempty(item.get("development_decision"), "question.development_decision"), "expected_verification": nonempty(item.get("expected_verification"), "question.expected_verification"), "followup_condition": nonempty(item.get("followup_condition"), "question.followup_condition")})
    if any(count > 6 for count in initial.values()) or any(count > 3 for count in followups.values()):
        raise ContractError("每细分最多 6 个首轮问题和 3 个追问/跨商品核对；不应用配额填满无价值问题")
    return {"schema_version": "v5-active-question-plan-1.0", "created_at": now_utc(), "questions": normalized, "limits": {"initial_per_segment": 6, "followup_per_segment": 3}}


TRANSITIONS = {"pending": {"submitting", "blocked_login", "selector_changed"}, "submitting": {"submitted", "submission_uncertain", "blocked_login", "selector_changed"}, "submitted": {"completed", "partial", "submission_uncertain", "blocked_login", "selector_changed"}, "partial": set(), "completed": set(), "submission_uncertain": set(), "blocked_login": set(), "selector_changed": set()}


def _last_ledger_state(path: Path, question_id: str) -> Optional[str]:
    if not path.exists():
        return None
    last: Optional[str] = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            raise ContractError("现有主动问答账本不是有效 JSONL") from None
        if isinstance(item, Mapping) and item.get("question_id") == question_id:
            last = str(item.get("state") or "")
    return last


def append_qa_event(ledger: Path, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    question_id = nonempty(payload.get("question_id"), "ledger.question_id")
    state = nonempty(payload.get("state"), "ledger.state")
    if state not in TRANSITIONS:
        raise ContractError("未知主动问答状态：%s" % state)
    previous = _last_ledger_state(ledger, question_id) or "pending"
    if state not in TRANSITIONS[previous]:
        raise ContractError("主动问答状态不能从 %s 转为 %s" % (previous, state))
    event = {"recorded_at": now_utc(), "question_id": question_id, "state": state, "page_binding": nonempty(payload.get("page_binding"), "ledger.page_binding"), "conversation_id": payload.get("conversation_id"), "answer": payload.get("answer") if state in {"completed", "partial"} else None, "completion_verified": bool(payload.get("completion_verified")) if state == "completed" else False, "reason": payload.get("reason")}
    if state == "completed" and not event["completion_verified"]:
        raise ContractError("completed 必须确认问题、对应回答和生成完成状态")
    append_jsonl(ledger, event)
    return event


def evidence_links(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    needs = list_of_mappings(payload.get("needs"), "needs")
    result: List[Dict[str, Any]] = []
    for need in needs:
        need_id = nonempty(need.get("need_id"), "need.need_id")
        evidence = list_of_mappings(need.get("evidence"), "need.evidence")
        counts = {"review": set(), "social": set(), "alexa": set(), "keyword": set(), "product": set()}
        normalized = []
        for item in evidence:
            source_type = nonempty(item.get("source_type"), "evidence.source_type")
            source_id = nonempty(item.get("source_id"), "evidence.source_id")
            if source_type not in counts:
                raise ContractError("未知 evidence.source_type：%s" % source_type)
            counts[source_type].add(source_id)
            normalized.append({"source_type": source_type, "source_id": source_id, "role": nonempty(item.get("role"), "evidence.role")})
        result.append({"need_id": need_id, "evidence": normalized, "consumer_voice_counts": {"review_unique_records": len(counts["review"]), "social_unique_records": len(counts["social"])}, "research_signal_counts": {"alexa_refs": len(counts["alexa"]), "keyword_refs": len(counts["keyword"]), "product_refs": len(counts["product"])}, "guardrail": "Alexa references are research signals and never enter consumer voice, KANO, people, or channel counts"})
    return {"schema_version": "v5-need-evidence-links-1.0", "created_at": now_utc(), "needs": result}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V5 需求洞察 sidecar 生成器；纯本地、无鉴权、无网络")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("plan-reviews", "生成旧 Top3/头部商品和评论采样计划"), ("plan-single-segment", "生成用户选定单细分的评论、Alexa 与社媒采样计划"), ("single-segment-progress", "核对独立来源门槛并生成下一评论批次"), ("summarize-reviews", "生成评论统计摘要"), ("summarize-social", "生成社媒统计摘要"), ("summarize-keywords", "生成关键词摘要"), ("plan-questions", "校验主动问题计划和配额"), ("link-evidence", "生成需求证据关联")):
        child = commands.add_parser(name, help=help_text)
        child.add_argument("--input", type=Path, required=True)
        child.add_argument("--output", type=Path, required=True)
    ledger = commands.add_parser("append-qa-ledger", help="追加并校验主动问答恢复账本状态")
    ledger.add_argument("--input", type=Path, required=True)
    ledger.add_argument("--ledger", type=Path, required=True)
    return parser


def execute(args: argparse.Namespace) -> Mapping[str, Any]:
    payload = load_object(args.input)
    if args.command == "plan-reviews":
        value = plan_reviews(payload)
    elif args.command == "plan-single-segment":
        value = plan_single_segment(payload)
    elif args.command == "single-segment-progress":
        value = single_segment_progress(payload)
    elif args.command == "summarize-reviews":
        value = summarize_voices(payload, "review")
    elif args.command == "summarize-social":
        value = summarize_voices(payload, "social")
    elif args.command == "summarize-keywords":
        value = keyword_summary(payload)
    elif args.command == "plan-questions":
        value = active_question_plan(payload)
    elif args.command == "link-evidence":
        value = evidence_links(payload)
    elif args.command == "append-qa-ledger":
        return append_qa_event(args.ledger, payload)
    else:
        raise ContractError("未知命令")
    write_json(args.output, value)
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        result = execute(build_parser().parse_args(argv))
    except ContractError as exc:
        sys.stderr.write(json.dumps({"status": "contract_error", "error": str(exc)}, ensure_ascii=False) + "\n")
        return 2
    sys.stdout.write(json.dumps({"status": "ok", "command": "local_sidecar", "output_keys": sorted(result.keys())}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
