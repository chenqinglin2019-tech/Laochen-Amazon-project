"""Pure, source-scoped metrics for the second niche recommendation round.

No I/O, network, authentication, or upstream mutation. Shares ending in ``_pct``
and pressure estimates are percentage points; other rates/coverage are ratios.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

LAUNCH_EDGES = (90, 120, 150, 180, 210, 240, 270, 300, 360, 720)
RATING_EDGES = (4.0, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8)
REVIEW_EDGES = (30, 60, 100, 200, 300, 400, 500, 600, 700, 1000, 2000, 3000)
PRICE_MULTIPLIER_EDGES = (0.4, 0.6, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4, 1.6, 2.0, 2.5, 3.0)
UNKNOWN_BRANDS = {"", "unknown", "未知", "na", "n/a", "none", "null", "not provided", "未披露", "不详", "-", "—"}
# Display-only thresholds (user decisions 2026-10-01): never gate or re-rank.
LOW_COVERAGE_CLICK_SHARE = 0.60
HIGH_LEVELS = {"极高", "很高", "较高"}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _nonnegative(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and result >= 0 else None


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _head_count(count: int, fraction: float = 0.1) -> int:
    return max(1, math.ceil(count * fraction)) if count else 0


def _status(reasons: list[str]) -> str:
    return "ready" if not reasons else "pending_validation"


def product_evidence(members: list[dict]) -> dict:
    """Calculate only from the supplied segment member rows.

    An effective sample requires ASIN, price > 0 and monthly sales > 0. Exact
    duplicates are counted once; conflicting duplicate ASIN rows are isolated.
    Missing launch/brand/review/rating information never borrows category data.
    """
    by_asin: dict[str, list[dict]] = defaultdict(list)
    excluded: list[dict] = []
    for raw in members:
        row = dict(raw)
        asin = str(row.get("asin") or "").strip().upper()
        price, sales = _number(row.get("price")), _number(row.get("monthly_sales"))
        reasons = []
        if not asin:
            reasons.append("missing_asin")
        if price is None or price <= 0:
            reasons.append("invalid_price")
        if sales is None or sales <= 0:
            reasons.append("invalid_monthly_sales")
        if reasons:
            excluded.append({"asin": asin, "reasons": reasons})
            continue
        row.update(asin=asin, price=price, monthly_sales=sales)
        for key in ("launch_days", "review_count", "rating"):
            row[key] = _nonnegative(row.get(key))
        brand_display = " ".join(str(row.get("brand") or "").split())
        row.setdefault("brand_original", row.get("brand"))
        row["brand"] = "" if brand_display.casefold() in UNKNOWN_BRANDS else brand_display
        row["brand_key"] = row["brand"].casefold()
        by_asin[asin].append(row)
    effective = []
    fields = ("price", "monthly_sales", "launch_days", "review_count", "rating", "brand_key")
    duplicates_removed = 0
    for asin, rows in by_asin.items():
        if any(any(row.get(key) != rows[0].get(key) for key in fields) for row in rows[1:]):
            excluded.append({"asin": asin, "reasons": ["conflicting_duplicate_asin"]})
        else:
            effective.append(rows[0])
            duplicates_removed += len(rows) - 1
    effective.sort(key=lambda row: (-row["monthly_sales"], row["asin"]))
    count = len(effective)
    total_sales = sum(row["monthly_sales"] for row in effective)
    mean_price = sum(row["price"] for row in effective) / count if count else None
    product_head = effective[:_head_count(count)]
    success_asins = {row["asin"] for row in effective[:_head_count(count, .2)]}
    brands: dict[str, float] = defaultdict(float)
    brand_displays: dict[str, set[str]] = defaultdict(set)
    for row in effective:
        if row["brand_key"]:
            brands[row["brand_key"]] += row["monthly_sales"]
            brand_displays[row["brand_key"]].add(row["brand"])
    brand_order = sorted(brands, key=lambda brand: (-brands[brand], brand))
    brand_head = brand_order[:_head_count(len(brands))]
    brand_missing = sum(not row["brand"] for row in effective)
    launch_missing = sum(row["launch_days"] is None for row in effective)
    new_products = [row for row in effective if row["launch_days"] is not None and row["launch_days"] <= 360]
    successful_new = [row for row in new_products if row["asin"] in success_asins]
    reasons = []
    if count == 0:
        reasons.append("no_effective_products")
    if brand_missing:
        reasons.append("missing_brand")
    if launch_missing:
        reasons.append("missing_launch_days")
    if not new_products:
        reasons.append("no_observable_new_products")
    return {
        "status": _status(reasons), "reasons": reasons,
        "input_count": len(members), "effective_count": count,
        "excluded_products": excluded, "duplicates_removed": duplicates_removed,
        "members": effective, "total_monthly_sales": total_sales, "mean_price": mean_price,
        "product_head_share_pct": 100 * sum(row["monthly_sales"] for row in product_head) / total_sales if total_sales else None,
        "product_head_count": len(product_head), "product_head_asins": [row["asin"] for row in product_head],
        "product_status": "ready" if count else "pending_validation",
        "brand_head_share_pct": 100 * sum(brands[brand] for brand in brand_head) / total_sales if total_sales and not brand_missing else None,
        "brand_head_count": len(brand_head),
        "brand_head_names": [min(brand_displays[key]) for key in brand_head],
        "brand_head_keys": brand_head,
        "brand_count": len(brands), "brand_missing_count": brand_missing,
        "brand_status": "ready" if count and not brand_missing else "pending_validation",
        "new_product_count": len(new_products), "successful_new_product_count": len(successful_new),
        "new_product_asins": [row["asin"] for row in new_products],
        "successful_new_product_asins": [row["asin"] for row in successful_new],
        "success_head_count": len(success_asins), "success_head_asins": sorted(success_asins),
        "new_product_success_rate": len(successful_new) / len(new_products) if new_products and not launch_missing else None,
        "new_product_status": "ready" if new_products and not launch_missing else "pending_validation",
        "launch_days_missing_count": launch_missing,
        "review_count_missing_count": sum(row["review_count"] is None for row in effective),
        "rating_missing_count": sum(row["rating"] is None for row in effective),
        "top20_asins": [row["asin"] for row in effective[:20]],
        "confidence": "low" if count < 50 else "standard",
    }


def advertising_evidence(keyword_rows: list[dict], mean_price: float | None) -> dict:
    """Round-two advertising metrics on one paired keyword set (user decision 2026-10-03).

    A keyword takes part only when it has conversion data in the uploaded
    conversion sheet (clicks > 0 and 0 <= purchases <= clicks) AND one
    unambiguous, positive SellerSprite ``PPC竞价`` (suggested bid).  Missing
    either one drops the whole keyword from BOTH the conversion rate and the
    weighted CPC; nothing is borrowed from other sources.  The frozen
    ``direct`` keyword boundary is not used here.
    """
    details: list[dict] = []
    for raw in keyword_rows:
        row = dict(raw)
        key = " ".join(str(row.get("key") or row.get("keyword") or "").casefold().split())
        clicks = _number(row.get("clicks"))
        purchases = _number(row.get("purchases"))
        bid = _number(row.get("ppc_bid"))
        source_reason = row.get("exclusion_reason")
        conversion_valid = (
            bool(key)
            and row.get("conversion_available", True) is not False
            and clicks is not None
            and clicks > 0
            and purchases is not None
            and 0 <= purchases <= clicks
        )
        bid_valid = bid is not None and bid > 0
        included = conversion_valid and bid_valid
        problems = []
        if not key:
            problems.append("missing_keyword")
        else:
            if not conversion_valid:
                problems.append("missing_or_invalid_conversion_data")
            if not bid_valid:
                problems.append(source_reason or "missing_or_nonpositive_sellersprite_bid")
        row.update(
            key=key,
            clicks=clicks,
            purchases=purchases,
            ppc_bid=bid,
            conversion_valid=conversion_valid,
            bid_valid=bid_valid,
            included=included,
            exclusion_reason="+".join(problems) or None,
            click_weight=None,
            purchase_weight=None,
            weighted_bid=None,
        )
        details.append(row)

    conversion_rows = [row for row in details if row["conversion_valid"]]
    participating = [row for row in details if row["included"]]
    all_clicks = sum(row["clicks"] for row in conversion_rows)
    all_purchases = sum(row["purchases"] for row in conversion_rows)
    participating_clicks = sum(row["clicks"] for row in participating)
    participating_purchases = sum(row["purchases"] for row in participating)
    conversion = _ratio(participating_purchases, participating_clicks)
    bid = (
        sum((row["clicks"] / participating_clicks) * row["ppc_bid"] for row in participating)
        if participating_clicks > 0 and participating
        else None
    )
    for row in participating:
        row["click_weight"] = _ratio(row["clicks"], participating_clicks)
        # Historical alias kept for detail consumers; both use click share.
        row["purchase_weight"] = row["click_weight"]
        row["weighted_bid"] = row["click_weight"] * row["ppc_bid"] if row["click_weight"] is not None else None
    price = _number(mean_price)
    pressure = bid / (price * conversion) * 100 if bid is not None and price is not None and price > 0 and conversion is not None and conversion > 0 else None
    purchase_coverage = _ratio(participating_purchases, all_purchases)
    click_coverage = _ratio(participating_clicks, all_clicks)
    low_coverage = click_coverage is not None and click_coverage < LOW_COVERAGE_CLICK_SHARE
    reasons = []
    if not participating:
        reasons.append("no_keywords_with_both_conversion_and_bid")
    elif participating_purchases <= 0:
        reasons.append("no_purchases_in_paired_keywords")
    if price is None or price <= 0:
        reasons.append("invalid_segment_mean_price")
    return {
        "status": _status(reasons), "reasons": reasons,
        "representative_bid": bid, "click_conversion_rate": conversion,
        "pressure_estimate": pressure, "half_conversion_pressure_estimate": pressure * 2 if pressure is not None else None,
        # total_* are the paired keyword set used for BOTH the conversion rate and the CPC.
        "mean_price": price, "total_clicks": participating_clicks, "total_purchases": participating_purchases,
        "all_conversion_clicks": all_clicks, "all_conversion_purchases": all_purchases,
        "participating_clicks": participating_clicks, "participating_purchases": participating_purchases,
        "core_keyword_count": len(details), "conversion_keyword_count": len(conversion_rows),
        "participating_keyword_count": len(participating),
        "conversion_match_rate": len(conversion_rows) / len(details) if details else None,
        "purchase_coverage": purchase_coverage, "click_coverage": click_coverage,
        "low_coverage": low_coverage, "low_coverage_threshold": LOW_COVERAGE_CLICK_SHARE,
        "coverage_note": f"低覆盖（只有 {click_coverage * 100:.1f}% 的点击同时有转化与竞价数据）" if low_coverage else None,
        "missing_bid_count": sum(row["conversion_valid"] and not row["bid_valid"] for row in details),
        "missing_conversion_count": sum(not row["conversion_valid"] for row in details),
        "keyword_details": details,
        "bid_source": "SellerSprite.PPC竞价", "weighting": "clicks",
        "keyword_set": "keywords_with_both_conversion_and_sellersprite_bid",
        "coverage_basis": "paired_keyword_clicks / all_conversion_clicks",
        "pressure_unit": "percentage_points", "conversion_rate_unit": "ratio",
    }


def _grade(value: float, advertising: bool = False) -> str:
    edges = (100, 80, 60, 40, 25, 15) if advertising else (80, 60, 50, 40, 30, 20)
    for edge, label in zip(edges, ("极高", "很高", "较高", "中等", "较低", "很低")):
        if value >= edge:
            return label
    return "极低"


def _format(value: float) -> str:
    return f"{value:g}"


def _band_label(low: float | None, high: float | None, suffix: str = "") -> str:
    if low is None and high is None:
        return "全部区间" + suffix
    if low is None:
        return f"<{_format(high)}{suffix}"
    if high is None:
        return f">={_format(low)}{suffix}"
    return f"{_format(low)}-{_format(high)}{suffix}"


def _pivot(members: list[dict], field: str, edges: tuple, multiplier: float = 1, suffix: str = "") -> dict:
    missing = [row["asin"] for row in members if row.get(field) is None]
    if missing or not members:
        return {"status": "pending_validation", "reason": "missing_" + field if missing else "no_effective_products", "missing_asins": missing, "bands": []}
    buckets = [{"low": None if index == 0 else edges[index-1], "high": edge, "rows": []} for index, edge in enumerate((*edges, None))]
    for row in members:
        value = row[field] / multiplier
        index = next((i for i, edge in enumerate(edges) if value < edge), len(edges))
        buckets[index]["rows"].append(row)
    merged = []
    pending = None
    for bucket in buckets:
        if pending is None:
            pending = {"low": bucket["low"], "high": bucket["high"], "rows": list(bucket["rows"])}
        else:
            pending["high"] = bucket["high"]
            pending["rows"].extend(bucket["rows"])
        if len(pending["rows"]) >= 10:
            merged.append(pending)
            pending = None
    if pending:
        if merged:
            merged[-1]["high"] = pending["high"]
            merged[-1]["rows"].extend(pending["rows"])
        elif pending["rows"]:
            merged.append(pending)
    total_sales = sum(row["monthly_sales"] for row in members)
    bands = []
    for index, bucket in enumerate(merged, 1):
        count = len(bucket["rows"])
        sales = sum(row["monthly_sales"] for row in bucket["rows"])
        listing_share, sales_share = count / len(members), sales / total_sales
        band = {
            "label": _band_label(bucket["low"], bucket["high"], suffix), "order": index,
            "low": bucket["low"], "high": bucket["high"],
            "listing_count": count, "listing_count_share": listing_share * 100,
            "sales": sales, "sales_share": sales_share * 100, "avg_sales": sales / count,
            "sales_to_listing_share_ratio": sales_share / listing_share,
            "asins": [row["asin"] for row in bucket["rows"]],
        }
        if field == "price":
            band.update(actual_price_low=bucket["low"] * multiplier if bucket["low"] is not None else None,
                        actual_price_high=bucket["high"] * multiplier if bucket["high"] is not None else None)
        bands.append(band)
    return {"status": "ready", "missing_asins": [], "bands": bands,
            "minimum_band_target": 10, "low_sample": len(members) < 10}


def _rule(label: str, value: Any, basis: str, *, summary: str | None = None,
          reason: str | None = None, advertising: bool = False) -> dict:
    ready = value is not None and reason is None
    level = _grade(value, advertising) if ready and isinstance(value, (float, int)) else None
    return {"status": "ready" if ready else "pending_validation", "label": label,
            "value": value, "level": level, "basis": basis,
            "summary": summary or (f"{value:.2f}%，{level}" if ready and level else str(value) if ready else "无法判断"),
            "reason": reason}


def eight_conclusions(members: list[dict], ad_evidence: dict) -> dict:
    """Recompute the original eight rules within this segment only.

    Missing review/rating values remain unknown (the user-approved refinement
    contract), rather than inheriting the old market cleaner's zero imputation.
    """
    evidence = product_evidence(members)
    rows = evidence["members"]
    total_sales = evidence["total_monthly_sales"]
    head_n = _head_count(len(rows))
    pivots = {
        "review_count": _pivot(rows, "review_count", REVIEW_EDGES),
        "rating": _pivot(rows, "rating", RATING_EDGES),
        "launch_days": _pivot(rows, "launch_days", LAUNCH_EDGES, suffix="天"),
        "price": _pivot(rows, "price", PRICE_MULTIPLIER_EDGES, evidence["mean_price"] or 1, "x均价"),
    }
    if rows and not evidence["review_count_missing_count"]:
        review_head = sorted(rows, key=lambda row: (-row["review_count"], row["asin"]))[:head_n]
        review_share = sum(row["monthly_sales"] for row in review_head) / total_sales * 100
    else:
        review_share = None
    cheap_head = sorted(rows, key=lambda row: (row["price"], row["asin"]))[:head_n]
    cheap_share = sum(row["monthly_sales"] for row in cheap_head) / total_sales * 100 if total_sales else None
    selected_bands = {}
    for field in ("rating", "launch_days", "price"):
        qualifying = [band for band in pivots[field]["bands"] if band["sales_share"] > band["listing_count_share"] + 1e-12]
        if field == "price":
            qualifying.sort(key=lambda band: (-band["sales_to_listing_share_ratio"], band["order"]))
        selected_bands[field] = qualifying[:2 if field == "price" else 1]
    rating_band = selected_bands["rating"]
    age_band = selected_bands["launch_days"]
    price_bands = selected_bands["price"]
    pressure = _number(ad_evidence.get("pressure_estimate"))
    rules = {
        "review_dependency": _rule("评论依赖性", review_share, "本市场评论数最高的前10%商品销量／本市场总销量", reason="missing_review_count" if evidence["review_count_missing_count"] else None),
        "rating_requirement": _rule("评分值依赖性", rating_band[0]["label"] if rating_band else None, "评分区间从低到高，首个销量占比大于商品数量占比的区间", reason=None if rating_band else pivots["rating"].get("reason", "no_qualifying_band")),
        "price_sensitivity": _rule("价格敏感度", cheap_share, "本市场价格最低的前10%商品销量／本市场总销量"),
        "best_price_bands": _rule("最值得进入的价格带", [band["label"] for band in price_bands] if price_bands else None, "销量占比大于数量占比的价格带，按两者比值降序取前两个；分箱使用本市场均价", reason=None if price_bands else pivots["price"].get("reason", "no_qualifying_band")),
        "new_product_cycle": _rule("新品打造周期", age_band[0]["label"] if age_band else None, "上架天数从低到高，首个销量占比大于商品数量占比的区间", reason=None if age_band else pivots["launch_days"].get("reason", "no_qualifying_band")),
        "product_monopoly": _rule("商品垄断度", evidence["product_head_share_pct"], "本市场月销量前10%商品销量／本市场总销量"),
        "brand_monopoly": _rule("品牌垄断度", evidence["brand_head_share_pct"], "本市场月销量前10%品牌销量／本市场总销量", reason="missing_brand" if evidence["brand_missing_count"] else None),
        "ad_pressure": _rule("广告压力指数", pressure, "只用同时有转化数据和卖家精灵建议竞价的关键词：点击量加权 CPC／（本市场商品算术均价×这些关键词的购买量／点击量）", advertising=True, reason=None if ad_evidence.get("status") == "ready" else "advertising_evidence_incomplete"),
    }
    for field, rule_key in (("rating", "rating_requirement"), ("launch_days", "new_product_cycle"), ("price", "best_price_bands")):
        rules[rule_key]["selected_bands"] = selected_bands[field]
    return {"status": "ready" if all(rule["status"] == "ready" for rule in rules.values()) else "partial",
            "confidence": evidence["confidence"], "sample_count": len(rows), "mean_price": evidence["mean_price"],
            "rules": rules, "pivots": pivots, "source_scope": "this_segment_only",
            "head_count_rule": "ceil, at least one; ASIN/brand stable tie-break"}


def entry_advice(conclusions: dict, ad_evidence: dict, search_growth: dict | None, is_backup: bool) -> dict:
    """One display line per analysed market; it never changes rank or membership."""
    rules = conclusions.get("rules") or {}
    flags = []
    for key, label in (("product_monopoly", "商品垄断度"), ("brand_monopoly", "品牌垄断度"), ("ad_pressure", "广告压力")):
        level = (rules.get(key) or {}).get("level")
        if level in HIGH_LEVELS:
            flags.append(f"{label}{level}")
    if ad_evidence.get("low_coverage"):
        flags.append(ad_evidence.get("coverage_note") or "广告低覆盖")
    if conclusions.get("confidence") == "low":
        flags.append("有效商品少于 50 个")
    if (search_growth or {}).get("status") == "watch":
        flags.append("近90/180天搜索量均下降≥20%")
    if is_backup:
        flags.append("候补（未达正式推荐条件）")
    level = "低" if not flags else "中" if len(flags) <= 2 else "高"
    unknown = [key for key, rule in rules.items() if rule.get("status") != "ready"]
    if len(unknown) >= 2 or (rules.get("ad_pressure") or {}).get("status") != "ready":
        advice = "证据不足，先补数据"
    elif level == "高" or is_backup:
        advice = "谨慎进入，需差异化验证"
    elif level == "中":
        advice = "可进入，关注所列风险"
    else:
        advice = "建议优先进入"
    return {"advice": advice, "risk_level": level, "flags": flags, "undetermined_rules": unknown,
            "rule": "风险旗标：商品/品牌垄断或广告压力达较高及以上、广告低覆盖、有效商品<50、搜索量近期下滑、候补；0个=低，1-2个=中，≥3个=高。仅作提示，不改变排名。"}
