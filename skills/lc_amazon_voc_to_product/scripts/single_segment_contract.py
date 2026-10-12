#!/usr/bin/env python3
"""Freeze a user-selected segment and build its local sampling contract.

This module deliberately has no HTTP, credential, quota or vendor-client
dependency.  It is the business boundary between an upstream opportunity
selection and this Skill's single-segment VOC workflow.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


INPUT_SCHEMA = "single-segment-input-1.0"
PLAN_SCHEMA = "single-segment-sampling-plan-1.0"
SCOPE_ID = "selected_segment_all_history"
INITIAL_REVIEW_ASIN_COUNT = 5
MAX_REVIEW_ASIN_COUNT = 50
SOCIAL_POLICY = {
    "trial_valid_target": 200,
    "normal_valid_target": 2000,
    "normal_valid_max": None,
    "data_exhaustion_downgrade_floor": None,
    "review_batch_valid_target": 200,
    "earliest_normal_stop_check": 2000,
    "saturation_batches": None,
    "saturation_is_hard_gate": False,
    "stop_rule": "source_targets_and_processing_quality_and_documented_scenario_gap_check",
    "saturation_new_topic_ratio_max": 0.05,
    "saturation_stable_top10_min": 8,
    "coverage_alerts": {
        "single_root_discussion_share_max": 0.10,
        "single_author_share_max": 0.20,
        "single_platform_share_max": 0.70,
        "minimum_root_discussions": 20,
        "minimum_relevant_platforms": 2,
    },
}


class SingleSegmentContractError(ValueError):
    """A supplied business input cannot safely determine the research scope."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SingleSegmentContractError("%s 必须是非空文本" % field)
    return text


def _number(value: Any, field: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SingleSegmentContractError("%s 必须是数值" % field)
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise SingleSegmentContractError("%s 不得小于 %s" % (field, minimum))
    return number


def _list(value: Any, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not value:
        raise SingleSegmentContractError("%s 必须是非空数组" % field)
    if any(not isinstance(item, Mapping) for item in value):
        raise SingleSegmentContractError("%s 每项必须是对象" % field)
    return list(value)


def _stable_segment_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return (slug[:40] or "selected-segment") + "-" + digest(name)[:10]


def _sales_value(product: Mapping[str, Any], index: int) -> float:
    for key in ("sales", "units_sold", "monthly_sales"):
        if key in product:
            return _number(product[key], "products[%d].%s" % (index, key))
    raise SingleSegmentContractError("products[%d] 缺少销量字段（sales、units_sold 或 monthly_sales）" % index)


def _traffic_value(keyword: Mapping[str, Any], index: int) -> float:
    for key in ("traffic_share", "traffic_ratio", "traffic_percent"):
        if key in keyword:
            return _number(keyword[key], "keywords[%d].%s" % (index, key))
    raise SingleSegmentContractError("keywords[%d] 缺少流量占比字段（traffic_share、traffic_ratio 或 traffic_percent）" % index)


def _selected_segment(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = payload.get("selected_segment")
    if not isinstance(raw, Mapping):
        raw = {"name": payload.get("segment_name"), "id": payload.get("segment_id")}
    name = _text(raw.get("name") or raw.get("feature") or raw.get("label"), "selected_segment.name")
    segment_id = str(raw.get("id") or raw.get("segment_id") or "").strip() or _stable_segment_id(name)
    result = {
        "segment_id": segment_id,
        "name": name,
        "definition": str(raw.get("definition") or raw.get("description") or "").strip(),
        "core_features": [str(item).strip() for item in raw.get("core_features", []) if str(item).strip()]
        if isinstance(raw.get("core_features", []), list)
        else [],
    }
    result["source_ref"] = str(raw.get("source_ref") or "").strip() or None
    return result


def normalise_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise SingleSegmentContractError("输入顶层必须是对象")
    declared = payload.get("schema_version")
    if declared not in (None, INPUT_SCHEMA):
        raise SingleSegmentContractError("schema_version 必须为 %s" % INPUT_SCHEMA)
    project = payload.get("project") if isinstance(payload.get("project"), Mapping) else {}
    marketplace = _text(project.get("marketplace") or payload.get("marketplace"), "project.marketplace")
    language = _text(project.get("language") or payload.get("language"), "project.language")
    segment = _selected_segment(payload)
    product_rows = _list(payload.get("products"), "products")
    keyword_rows = _list(payload.get("keywords"), "keywords")
    products: list[dict[str, Any]] = []
    seen_asins: set[str] = set()
    periods: set[str] = set()
    for index, product in enumerate(product_rows):
        asin = _text(product.get("asin") or product.get("ASIN"), "products[%d].asin" % index).upper()
        if asin in seen_asins:
            raise SingleSegmentContractError("products 不允许重复 ASIN：%s" % asin)
        seen_asins.add(asin)
        sales = _sales_value(product, index)
        period = str(product.get("sales_stat_period") or payload.get("sales_stat_period") or "").strip()
        if not period:
            raise SingleSegmentContractError("products[%d] 缺少可比销量统计口径 sales_stat_period" % index)
        periods.add(period)
        products.append({"asin": asin, "sales": sales, "sales_stat_period": period, "detail": copy.deepcopy(dict(product))})
    if len(periods) != 1:
        raise SingleSegmentContractError("全部商品必须使用同一 sales_stat_period 后才能按销量排序")
    keywords: list[dict[str, Any]] = []
    seen_keywords: set[str] = set()
    for index, keyword in enumerate(keyword_rows):
        text = _text(keyword.get("keyword") or keyword.get("text"), "keywords[%d].keyword" % index)
        marker = text.casefold()
        if marker in seen_keywords:
            raise SingleSegmentContractError("keywords 不允许重复关键词：%s" % text)
        seen_keywords.add(marker)
        keywords.append({"keyword": text, "traffic_share": _traffic_value(keyword, index), "detail": copy.deepcopy(dict(keyword))})
    units = {str(row.get("traffic_unit") or payload.get("traffic_unit") or
                 ("percent" if "traffic_percent" in row else "ratio")) for row in keyword_rows}
    if len(units) != 1 or not units <= {"ratio", "percent"}:
        raise SingleSegmentContractError("关键词流量单位必须一致且明确为 ratio 或 percent")
    traffic_unit = next(iter(units))
    if any(row["traffic_share"] > (1 if traffic_unit == "ratio" else 100) for row in keywords):
        raise SingleSegmentContractError("关键词流量超出声明单位范围")
    return {
        "schema_version": INPUT_SCHEMA,
        "workflow_mode": "single_segment",
        "project": {
            "project_id": str(project.get("project_id") or payload.get("project_id") or "").strip() or None,
            "marketplace": marketplace,
            "language": language,
        },
        "selected_segment": segment,
        "sales_stat_period": next(iter(periods)),
        "products": products,
        "keywords": keywords,
        "traffic_unit": traffic_unit,
        "search_plan": copy.deepcopy(payload.get("search_plan")),
        "source_ref": str(payload.get("source_ref") or "").strip() or None,
    }


def build_search_plan(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a bounded semantic planning output against the full keyword set.

    Unknown markets remain explicitly pending instead of mechanically using
    the first three rows.  Search expressions are project input: a generic
    workflow must not silently inherit an example category's terminology.
    """
    keywords = [row["keyword"] for row in snapshot["keywords"]]
    index = {word.casefold(): word for word in keywords}
    supplied = snapshot.get("search_plan")
    if supplied is None:
        return {"status": "planning_required", "keyword_count": len(keywords),
                "keyword_sha256": digest(keywords), "expressions": [],
                "instruction": "分析完整关键词列表，提交三个互补自然表达及真实支撑词、意图、理由、误召回范围；不得机械取前三名"}
    if not isinstance(supplied, Mapping):
        raise SingleSegmentContractError("search_plan 必须是对象")
    expressions = _list(supplied.get("expressions"), "search_plan.expressions")
    if len(expressions) != 3:
        raise SingleSegmentContractError("search_plan 必须恰好提供三个基础表达")
    normalized, seen = [], set()
    for row in expressions:
        expression = _text(row.get("expression"), "expression")
        marker = " ".join(expression.casefold().split())
        if marker in seen:
            raise SingleSegmentContractError("三个基础表达不得重复")
        if snapshot["project"]["language"].lower().startswith("en") and re.search(r"[\u4e00-\u9fff]", expression):
            raise SingleSegmentContractError("英文检索基础不得占用中文细分名")
        seen.add(marker)
        support = row.get("supporting_keywords")
        if not isinstance(support, list) or not support or any(str(word).casefold() not in index for word in support):
            raise SingleSegmentContractError("每个表达必须引用完整关键词列表内的真实支撑词")
        normalized.append({"expression": expression,
                           "supporting_keywords": [index[str(word).casefold()] for word in support],
                           **{key: _text(row.get(key), key) for key in ("intent", "reason", "false_positive_scope")}})
    return {"status": "ready", "planner_version": _text(supplied.get("planner_version"), "planner_version"),
            "keyword_count": len(keywords), "keyword_sha256": digest(keywords), "expressions": normalized,
            "reserve_terms": [word for word in keywords if word.casefold() not in seen]}


def collection_gate(amazon_valid: int, social_valid: int, *, processing_complete: bool,
                    quality_passed: bool, gap_check_recorded: bool,
                    approved_directions: int = 0) -> dict[str, Any]:
    for value in (amazon_valid, social_valid):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SingleSegmentContractError("有效数量必须是非负整数")
    gaps = {"amazon": max(0, 4000 - amazon_valid), "social": max(0, 2000 - social_valid),
            "total": max(0, 6000 - amazon_valid - social_valid)}
    return {"targets": {"amazon": 4000, "social": 2000, "total": 6000}, "gaps": gaps,
            "targets_are_advisory": True,
            "quantity_met": not any(gaps.values()),
            "can_stop_expansion": amazon_valid + social_valid >= 6000,
            "can_stop": processing_complete and quality_passed and gap_check_recorded and approved_directions == 3}


def next_review_asins(plan: Mapping[str, Any], completed_asins: Sequence[str], amazon_valid: int,
                      *, current_batch_processed: bool, evidence_gap: bool = False) -> list[str]:
    """Pure scheduling decision; never initiates requests or retries."""
    collection_gate(amazon_valid, 0, processing_complete=False, quality_passed=False, gap_check_recorded=False)
    candidates = [row["asin"] for row in plan["sampling"]["reviews"]["asins"]]
    completed = set(completed_asins)
    if completed - set(candidates):
        raise SingleSegmentContractError("已完成ASIN不在冻结前50候选内")
    if not current_batch_processed:
        return []
    initial = [asin for asin in candidates[:5] if asin not in completed]
    return initial or ([asin for asin in candidates[5:] if asin not in completed][:1] if evidence_gap else [])


def build_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = normalise_input(payload)
    snapshot_sha256 = digest(snapshot)
    products = sorted(snapshot["products"], key=lambda item: (-item["sales"], item["asin"]))
    keywords = sorted(snapshot["keywords"], key=lambda item: (-item["traffic_share"], item["keyword"].casefold(), item["keyword"]))
    initial_review_products = products[:INITIAL_REVIEW_ASIN_COUNT]
    review_candidates = products[:MAX_REVIEW_ASIN_COUNT]
    selected_keywords = keywords[:10]
    all_terms = [snapshot["selected_segment"]["name"]] + [item["keyword"] for item in keywords]
    term_bank = list(dict.fromkeys(term for term in all_terms if term))
    selection = {
        "schema_version": "single-segment-selection-1.0",
        "workflow_mode": "single_segment",
        "selection_mode": "user_selected_single_segment",
        "input_snapshot_sha256": snapshot_sha256,
        "source": {
            "marketplace": snapshot["project"]["marketplace"],
            "language": snapshot["project"]["language"],
            "source_ref": snapshot["source_ref"],
        },
        "selected_segment": copy.deepcopy(snapshot["selected_segment"]),
        "selected_segments": [{
            "segment_id": snapshot["selected_segment"]["segment_id"],
            "rank": 1,
            "dimension": "用户选定细分市场",
            "feature": snapshot["selected_segment"]["name"],
            "definition": snapshot["selected_segment"]["definition"],
            "synonyms": term_bank,
        }],
        "full_product_pool": {
            "product_count": len(products),
            "input_snapshot_sha256": snapshot_sha256,
            "asins": [item["asin"] for item in products],
            "sales_stat_period": snapshot["sales_stat_period"],
            "products": [{"asin": item["asin"], "sales": item["sales"],
                          "sales_stat_period": item["sales_stat_period"],
                          "detail": copy.deepcopy(item["detail"])} for item in products],
        },
    }
    return {
        "schema_version": PLAN_SCHEMA,
        "workflow_mode": "single_segment",
        "collection_scope": SCOPE_ID,
        "input_snapshot_sha256": snapshot_sha256,
        "selection": selection,
        "sampling": {
            "reviews": {
                "ordering": "sales_desc_then_asin",
                "sales_stat_period": snapshot["sales_stat_period"],
                "initial_asin_count": INITIAL_REVIEW_ASIN_COUNT,
                "max_asin_count": MAX_REVIEW_ASIN_COUNT,
                "actual_candidate_asin_count": len(review_candidates),
                "effective_review_target": 4000,
                "total_effective_voc_target": 6000,
                "progression_rule": "start_with_top_5_then_expand_for_documented_evidence_gap_after_processing",
                "expansion_stop_condition": "amazon_4000_and_total_6000_are_advisory_stop_targets; completion_requires_processing_quality_gap_review_and_three_directions",
                "per_asin_raw_review_limit": 1000,
                "completion_rules": ["reached_1000_unique_review_ids", "confirmed_end_of_pagination", "budget_paused", "request_failed_or_unknown", "pagination_stalled"],
                "asins": [{"rank": index, "asin": item["asin"], "sales": item["sales"]} for index, item in enumerate(review_candidates, 1)],
            },
            "alexa": {
                "keywords": [{"rank": index, "keyword": item["keyword"], "traffic_share": item["traffic_share"]} for index, item in enumerate(selected_keywords, 1)],
                "product_asins": [{"rank": index, "asin": item["asin"]} for index, item in enumerate(initial_review_products, 1)],
                "answers_required": True,
                "keyword_pagination_assumption": "unsupported_until_existing_adapter_contract_confirms",
                "product_pagination": "existing_adapter_only",
            },
            "social": {
                **copy.deepcopy(SOCIAL_POLICY),
                "term_bank": term_bank,
                "search_plan": build_search_plan(snapshot),
                "scope_rule": "only_selected_segment_related_records_count_as_social_voc",
                "insufficiency_rule": "report_actual_gap_as_partial; no_1200_downgrade; failure_is_not_saturation",
            },
            "competitive_pool": {
                "product_count": len(products),
                "source": "full_selected_segment_product_snapshot",
                "rule": "use_all_products_for_direct-competitor-audit; review_sampling_top50_does_not_limit_this_pool",
            },
        },
        "input_snapshot": snapshot,
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def materialise(input_path: Path, output_dir: Path) -> dict[str, Any]:
    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SingleSegmentContractError("无法读取输入 JSON：%s" % input_path) from exc
    plan = build_plan(raw)
    snapshot = plan.pop("input_snapshot")
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    snapshot = {**snapshot, "captured_at": generated_at, "input_file_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest()}
    plan = {**plan, "generated_at": generated_at, "input_snapshot_sha256": digest({key: value for key, value in snapshot.items() if key not in {"captured_at", "input_file_sha256"}})}
    snapshot_path = output_dir / "single_segment_input_snapshot.json"
    plan_path = output_dir / "single_segment_sampling_plan.json"
    selection_path = output_dir / "selected_segments.json"
    if any(path.exists() for path in (snapshot_path, plan_path, selection_path)):
        raise SingleSegmentContractError("冻结产物已存在，请使用新版本运行目录，禁止覆盖旧快照")
    _write_json(snapshot_path, snapshot)
    _write_json(plan_path, plan)
    _write_json(selection_path, plan["selection"])
    return {
        "status": "planned",
        "workflow_mode": "single_segment",
        "input_snapshot": str(snapshot_path.resolve()),
        "sampling_plan": str(plan_path.resolve()),
        "selection": str(selection_path.resolve()),
        "selected_segment": plan["selection"]["selected_segment"],
        "review_asins": [item["asin"] for item in plan["sampling"]["reviews"]["asins"]],
        "alexa_keywords": [item["keyword"] for item in plan["sampling"]["alexa"]["keywords"]],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="上游明确交接的单细分 JSON")
    parser.add_argument("--output-dir", type=Path, required=True, help="本次下游新运行目录")
    args = parser.parse_args(argv)
    try:
        result = materialise(args.input.expanduser().resolve(), args.output_dir.expanduser().resolve())
    except SingleSegmentContractError as exc:
        parser.exit(2, "单细分输入无效：%s\n" % exc)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
