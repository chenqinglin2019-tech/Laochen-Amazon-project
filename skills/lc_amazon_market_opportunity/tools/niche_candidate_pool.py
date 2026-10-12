"""Dual-source candidate pool and product-sample scoring (rule v10).

Pure functions: no I/O, network or project mutation.  User decisions
(2026-10-03): candidates come from both the POE niche table and the
multi-dimensional tag combinations; all four shortlist components use the same
product sample; "未体现X" conditions are stripped from combinations and vague
"泛X" values mean "has X of any kind"; combinations need keyword demand
evidence; the supply-demand index is made robust (top-3 ASINs removed, small
samples shrunk toward 1.0) and a formal market needs a robust index >= 1.0.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Callable, Iterable

COMBO_POOL_SIZE = 20          # combination cores taken by CLI opportunity score
DIRECTION_COUNT = 10          # the CLI "优先复核方向" are its top combinations; always kept
MAX_CONDITIONS = 3            # same limit as Agent-written tag expressions
ROBUST_DROP_HEAD = 3          # best sellers removed before the supply-demand index
ROBUST_SHRINK_K = 20.0        # pseudo-listings at the category average (index 1.0)
MIN_ROBUST_INDEX = 1.0        # formal recommendation gate (user decision C2)
CONTAINMENT_THRESHOLD = 0.5   # shared sales / smaller market sales => same demand
NEW_PRODUCT_DAYS = 360
SUCCESS_HEAD_FRACTION = 0.2
OPENNESS_BEST, OPENNESS_WORST = 20.0, 90.0

UNKNOWN_MARKERS = ("不可识别", "无法识别", "无法判断")
UNKNOWN_KEYS = {"unidentified", "unrecognized", "unknown", "不可识别", "other", "其他"}
ABSENCE_MARKERS = ("未体现", "未特别强调", "未披露", "未注明", "未说明", "未标明", "未提及", "通用未限定", "非候选", "未限定")
VAGUE_PREFIXES = ("泛",)


def value_class(normalized: str, displays: Iterable[str], legacy_non_candidate: set[str] = frozenset()) -> str:
    """Classify a tag value as unknown / absence / vague / positive (category-agnostic)."""
    key = str(normalized).strip().casefold()
    texts = [str(normalized), *[str(item) for item in displays]]
    if key in UNKNOWN_KEYS or any(marker in text for text in texts for marker in UNKNOWN_MARKERS):
        return "unknown"
    if key in legacy_non_candidate or any(marker in text for text in texts for marker in ABSENCE_MARKERS):
        return "absence"
    if any(str(item).startswith(VAGUE_PREFIXES) for item in displays):
        return "vague"
    return "positive"


def core_key(conditions: Iterable[tuple[str, Iterable[str]]]) -> tuple:
    return tuple(sorted((dimension, tuple(sorted(values))) for dimension, values in conditions))


def combo_id(key: tuple) -> str:
    return "combo-" + hashlib.sha256(json.dumps(key, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def combo_cores(formal_opportunities: list[dict[str, Any]], dimension_values: dict[str, dict[str, str]],
                display_lookup: Callable[[str, str], str | None], classes: dict[tuple[str, str], str],
                displays: dict[tuple[str, str], str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collapse CLI formal combinations into positive cores, best opportunity score first.

    ``dimension_values`` maps dimension -> {normalized key: original value};
    ``display_lookup(dimension, display)`` returns the normalized original value;
    ``classes``/``displays`` are keyed by (dimension, original value).
    """
    ordered = sorted(enumerate(formal_opportunities), key=lambda pair: (-(pair[1].get("opportunity_score") or 0), pair[0]))
    cores: dict[tuple, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for rank, (_, combo) in enumerate(ordered, 1):
        dimensions = [part.strip() for part in str(combo.get("dimensions") or "").split(" + ") if part.strip()]
        features = [part.strip() for part in str(combo.get("features") or "").split(" + ") if part.strip()]
        if not dimensions or len(dimensions) != len(features):
            skipped.append({"rank": rank, "features": combo.get("features"), "reason": "维度与特征数量不一致"})
            continue
        conditions, labels, stripped, unknown = [], [], [], False
        for dimension, display in zip(dimensions, features):
            value = display_lookup(dimension, display)
            if value is None:
                unknown = True
                break
            kind = classes.get((dimension, value), "positive")
            if kind == "unknown":
                unknown = True
                break
            if kind == "absence":
                stripped.append(display)
            elif kind == "vague":
                group = [original for original in dimension_values.get(dimension, {}).values()
                         if classes.get((dimension, original)) in {"positive", "vague"}]
                conditions.append((dimension, group))
                labels.append("带" + display.lstrip("".join(VAGUE_PREFIXES)) + "（任意）")
            else:
                conditions.append((dimension, [value]))
                labels.append(display)
        if unknown:
            skipped.append({"rank": rank, "features": combo.get("features"), "reason": "含不可识别或无法映射的标签值"})
            continue
        if not conditions:
            skipped.append({"rank": rank, "features": combo.get("features"), "reason": "去掉“未体现”类条件后没有可定义市场的条件"})
            continue
        if len(conditions) > MAX_CONDITIONS:
            skipped.append({"rank": rank, "features": combo.get("features"), "reason": f"有效条件超过 {MAX_CONDITIONS} 个"})
            continue
        key = core_key(conditions)
        entry = cores.get(key)
        variant = {"rank": rank, "features": combo.get("features"), "stripped": stripped,
                   "listing_count": combo.get("listing_count"), "supply_demand_index": combo.get("supply_demand_index"),
                   "opportunity_score": combo.get("opportunity_score")}
        if entry is None:
            cores[key] = {"key": key, "name": " + ".join(labels), "best_rank": rank, "opportunity_score": combo.get("opportunity_score"), "variants": [variant]}
        else:
            entry["variants"].append(variant)
    chosen = list(cores.values())[:COMBO_POOL_SIZE]
    chosen += [core for core in list(cores.values())[COMBO_POOL_SIZE:] if core["best_rank"] <= DIRECTION_COUNT]
    for core in chosen:
        core["id"] = combo_id(core["key"])
        hint = max((v for v in core["variants"] if v["stripped"]), key=lambda v: (v.get("supply_demand_index") or 0, -v["rank"]), default=None)
        core["entry_hint"] = None if hint is None else {
            "features": hint["features"], "stripped": hint["stripped"], "listing_count": hint["listing_count"],
            "supply_demand_index": hint["supply_demand_index"],
            "text": f"其中“{'、'.join(hint['stripped'])}”的商品（{hint['listing_count']} 个）多维供需指数 {hint['supply_demand_index']:.2f}，可作切入点参考"
            if isinstance(hint.get("supply_demand_index"), (int, float)) else None,
        }
    return chosen, skipped


def valid_members(members: list[dict[str, Any]], sales: Callable[[dict[str, Any]], float | None]) -> list[dict[str, Any]]:
    return [member for member in members if sales(member) is not None]


def robust_supply_demand(members: list[dict[str, Any]], category_count: int, category_sales: float,
                         sales: Callable[[dict[str, Any]], float | None]) -> dict[str, Any]:
    valid = sorted(valid_members(members, sales), key=lambda m: (-(sales(m) or 0.0), m["asin"]))
    n, q = len(valid), sum(sales(m) or 0.0 for m in valid)
    evidence: dict[str, Any] = {"status": "unavailable", "segment_valid_asin_count": n, "segment_monthly_sales_sum": q,
                                "category_valid_asin_count": category_count, "category_monthly_sales_sum": category_sales,
                                "drop_head": ROBUST_DROP_HEAD, "shrink_k": ROBUST_SHRINK_K,
                                "formula": "去掉本市场月销量前3个ASIN（本市场与品类母集同时扣除）后计算（销量占比/数量占比），再按 (n×指数+20×1.0)/(n+20) 向品类平均收缩。"}
    if category_count <= 0 or category_sales <= 0 or n <= 0:
        evidence["reason"] = "母集或本市场没有可用于供需指数的有效商品"
        return evidence
    raw = (q / category_sales) / (n / category_count) if q > 0 else 0.0
    head = valid[:ROBUST_DROP_HEAD]
    head_sales = sum(sales(m) or 0.0 for m in head)
    kept_n, kept_q = n - len(head), q - head_sales
    base_n, base_q = category_count - len(head), category_sales - head_sales
    if kept_n <= 0 or base_n <= 0 or base_q <= 0:
        evidence.update(raw_index=raw, reason="去掉头部商品后没有剩余有效商品")
        return evidence
    dropped_index = (kept_q / base_q) / (kept_n / base_n)
    robust = (kept_n * dropped_index + ROBUST_SHRINK_K) / (kept_n + ROBUST_SHRINK_K)
    evidence.update(status="available", raw_index=raw, listing_count_share=n / category_count, listing_sales_share=q / category_sales,
                    dropped_head_asins=[m["asin"] for m in head], dropped_head_sales_share=head_sales / q if q else None,
                    index_without_head=dropped_index, robust_index=robust)
    return evidence


def _openness(share_pct: float) -> float:
    if share_pct <= OPENNESS_BEST:
        return 100.0
    if share_pct >= OPENNESS_WORST:
        return 0.0
    return (OPENNESS_WORST - share_pct) / (OPENNESS_WORST - OPENNESS_BEST) * 100.0


def product_competition(members: list[dict[str, Any]], sales: Callable[[dict[str, Any]], float | None],
                        brand_key: Callable[[Any], str | None]) -> tuple[float | None, dict[str, Any]]:
    valid = valid_members(members, sales)
    total = sum(sales(m) or 0.0 for m in valid)
    if total <= 0:
        return None, {"status": "unavailable", "reason": "本市场没有正销量，无法计算集中度"}
    product_share = sum(sorted((sales(m) or 0.0 for m in valid), reverse=True)[:5]) / total * 100
    brands: dict[str, float] = defaultdict(float)
    for member in valid:
        key = brand_key(member.get("brand"))
        if key:
            brands[key] += sales(member) or 0.0
    brand_share = sum(sorted(brands.values(), reverse=True)[:5]) / total * 100
    product_score, brand_score = _openness(product_share), _openness(brand_share)
    return (product_score + brand_score) / 2, {
        "status": "available", "source": "product_sample", "product_top5_sales_share": product_share, "brand_top5_sales_share": brand_share,
        "unknown_brand_sales_share": (total - sum(brands.values())) / total, "product_openness_score": product_score, "brand_openness_score": brand_score,
        "formula": "本市场前5商品、前5品牌（已知品牌）月销量占比；≤20%得100分，≥90%得0分，两者取平均。",
    }


def product_new_entry(members: list[dict[str, Any]], sales: Callable[[dict[str, Any]], float | None]) -> tuple[float | None, dict[str, Any]]:
    valid = sorted(valid_members(members, sales), key=lambda m: (-(sales(m) or 0.0), m["asin"]))
    head = {m["asin"] for m in valid[:max(1, math.ceil(len(valid) * SUCCESS_HEAD_FRACTION))]} if valid else set()
    known = [m for m in valid if isinstance(m.get("launch_days"), (int, float)) and m["launch_days"] >= 0]
    new = [m for m in known if m["launch_days"] <= NEW_PRODUCT_DAYS]
    success = [m for m in new if m["asin"] in head]
    evidence = {"source": "product_sample", "new_product_count": len(new), "successful_new_product_count": len(success),
                "launch_days_missing_count": len(valid) - len(known), "success_head_count": len(head),
                "formula": "360天内上架为新品；进入本市场月销量前20%的新品为成功；50+(成功比例×100−50)×新品数/(新品数+5)。"}
    if not new:
        return None, {**evidence, "status": "unavailable", "reason": "本市场360天内没有可观察的新品，不能把无证据写作零成功率"}
    rate = len(success) / len(new)
    return 50 + (rate * 100 - 50) * len(new) / (len(new) + 5), {**evidence, "status": "available", "observed_success_rate": rate}


def percentiles(items: list[Any], value: Callable[[Any], float], ident: Callable[[Any], str]) -> dict[str, float]:
    ordered = sorted(items, key=lambda item: (value(item), ident(item)))
    if len(ordered) == 1:
        return {ident(ordered[0]): 50.0}
    out: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and value(ordered[end]) == value(ordered[index]):
            end += 1
        for item in ordered[index:end]:
            out[ident(item)] = ((index + 1 + end) / 2 - 1) / (len(ordered) - 1) * 100.0
        index = end
    return out


def containment_conflicts(markets: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    """Return pairs whose shared sales cover >= threshold of the smaller market.

    Each market: {"id", "sales_by_asin": {asin: monthly sales}}.
    """
    out: dict[tuple[str, str], float] = {}
    for i, left in enumerate(markets):
        left_total = sum(left["sales_by_asin"].values())
        for right in markets[i + 1:]:
            right_total = sum(right["sales_by_asin"].values())
            smaller = min(left_total, right_total)
            if smaller <= 0:
                continue
            small, large = (left, right) if len(left["sales_by_asin"]) <= len(right["sales_by_asin"]) else (right, left)
            shared = sum(value for asin, value in small["sales_by_asin"].items() if asin in large["sales_by_asin"])
            ratio = shared / smaller
            if ratio >= CONTAINMENT_THRESHOLD:
                out[(left["id"], right["id"])] = ratio
    return out
