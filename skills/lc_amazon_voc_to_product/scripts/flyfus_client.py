#!/usr/bin/env python3
"""Isolated Flyfus V5 adapter.

This module deliberately does not import the existing collector or its auth
helpers.  It reads only the user-owned Flyfus config when a Flyfus command is
actually run, records point usage without requiring a points cap, and records
every requested review page with its original page number and response.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request


API_BASE = "https://open-api.flyfus.com"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "lc_amazon_market_opportunity" / "flyfus_api.env"
CONFIG_KEY = "FLYFUS_API_KEY"
PLACEHOLDER_VALUES = frozenset({"", "changeme", "your_api_key", "your-api-key", "<api-key>", "<flyfus_api_key>"})


class FlyfusError(Exception):
    """Safe user-facing failure for the isolated Flyfus route."""


class FlyfusConfigurationError(FlyfusError):
    pass


class FlyfusRequestError(FlyfusError):
    pass


def _safe_error(message: str) -> FlyfusConfigurationError:
    return FlyfusConfigurationError(message)


def initialize_config(path: Path = DEFAULT_CONFIG_PATH) -> Mapping[str, Any]:
    """Create an empty private config only when absent; never overwrite it."""
    target = path.expanduser()
    if target.exists() or target.is_symlink():
        return {"status": "exists", "path": str(target), "created": False}
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(str(target.parent), 0o700)
    try:
        descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return {"status": "exists", "path": str(target), "created": False}
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(CONFIG_KEY + "=\n")
        handle.flush()
        os.fsync(handle.fileno())
    if os.name != "nt":
        os.chmod(str(target), 0o600)
    return {"status": "created", "path": str(target), "created": True}


def load_api_key(path: Path = DEFAULT_CONFIG_PATH) -> str:
    """Read exactly one non-executable Flyfus key without returning it in errors."""
    target = path.expanduser()
    if not target.exists():
        raise _safe_error("Flyfus 配置缺失：请在 %s 填写 %s" % (target, CONFIG_KEY))
    if target.is_symlink() or not target.is_file():
        raise _safe_error("Flyfus 配置必须是当前用户的普通私密文件：%s" % target)
    if os.name != "nt":
        mode = stat.S_IMODE(target.stat().st_mode)
        if mode != 0o600:
            raise _safe_error("Flyfus 配置权限必须为 0600：%s" % target)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise _safe_error("无法读取 Flyfus 配置：%s" % type(exc).__name__) from None
    values: Dict[str, str] = {}
    assignment = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        matched = assignment.fullmatch(line)
        if not matched:
            raise _safe_error("Flyfus 配置格式无效；只允许 KEY=VALUE 文本，不能执行命令")
        key, value = matched.group(1), matched.group(2).strip()
        if key != CONFIG_KEY or key in values:
            raise _safe_error("Flyfus 配置只允许一个 %s 字段" % CONFIG_KEY)
        values[key] = value
    api_key = values.get(CONFIG_KEY, "")
    if api_key.casefold() in PLACEHOLDER_VALUES or api_key.casefold().startswith("your_"):
        raise _safe_error("Flyfus 配置为空或仍是占位值：%s" % target)
    return api_key


def _redact(value: Any, api_key: str = "") -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): ("<redacted>" if str(key).casefold() in {"authorization", "api_key", "token", "secret", "x-api-key"} else _redact(child, api_key))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact(child, api_key) for child in value]
    if isinstance(value, str) and api_key:
        return value.replace(api_key, "<redacted>")
    return value


def _json_request(endpoint: str, payload: Mapping[str, Any], api_key: str, timeout: float = 30.0, opener: Any = None) -> Mapping[str, Any]:
    body = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib_request.Request(
        API_BASE + endpoint,
        data=body,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": "Bearer " + api_key},
    )
    open_request = opener or urllib_request.urlopen
    try:
        with open_request(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        raise FlyfusRequestError("Flyfus 请求被拒绝或失败（HTTP %s）" % exc.code) from None
    except (urllib_error.URLError, OSError, TimeoutError) as exc:
        raise FlyfusRequestError("Flyfus 请求失败：%s" % type(exc).__name__) from None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        raise FlyfusRequestError("Flyfus 返回不是 JSON") from None
    if not isinstance(decoded, Mapping):
        raise FlyfusRequestError("Flyfus 返回结构无效")
    code = decoded.get("code")
    if code not in (None, 0, 200, "0", "200"):
        raise FlyfusRequestError("Flyfus 返回业务错误（code=%s）" % str(code))
    return decoded


def response_items(response: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    data = response.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in ("list", "items", "records", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    for key in ("list", "items", "records"):
        value = response.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def response_total(response: Mapping[str, Any]) -> Optional[int]:
    candidates: List[Any] = []
    data = response.get("data")
    if isinstance(data, Mapping):
        candidates.extend(data.get(key) for key in ("total", "totalCount", "count"))
    candidates.extend(response.get(key) for key in ("total", "totalCount", "count"))
    for candidate in candidates:
        try:
            return int(candidate)
        except (TypeError, ValueError):
            pass
    return None


def review_records(response: Mapping[str, Any], asin: str, market: str) -> List[Mapping[str, Any]]:
    """Normalize a single Flyfus review page without inventing an identity."""
    items = response_items(response)
    records: List[Mapping[str, Any]] = []
    for item in items:
        review_id = str(item.get("reviewId") or item.get("review_id") or item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or item.get("reviewContent") or item.get("text") or "").strip()
        text = "\n\n".join(part for part in (title, content) if part)
        if not review_id or not text:
            continue
        url = str(item.get("url") or item.get("reviewUrl") or "").strip()
        if not url:
            url = "https://www.amazon.com/gp/customer-reviews/" + review_id
        records.append({
            "content_id": review_id,
            "text": text,
            "published_at": item.get("date") or item.get("reviewDate"),
            "url": url,
            "source": "amazon",
            "source_kind": "review",
            "author": item.get("author") or item.get("authorName") or item.get("reviewerName"),
            "author_id": item.get("authorId") or item.get("reviewerId"),
            "metadata": {"provider": "flyfus", "request_asin": asin, "market": market, "rating": item.get("rating"), "verified_purchase": item.get("verifiedPurchase"), "vine": item.get("vine"), "purchase_variant": "unknown"},
        })
    return records


def review_page_receipt(response: Mapping[str, Any], asin: str, market: str, page: int, points_cap: Optional[int], api_key: str) -> Mapping[str, Any]:
    """Persist a single explicitly requested page, including zero-result pages."""
    items = response_items(response)
    return _redact({
        "provider": "flyfus",
        "operation": "review_page",
        "status": "complete" if items else "empty_page",
        "request": {"asin": asin, "market": market, "page": page},
        "points_reserved": 10,
        "points_cap": points_cap,
        "spend_boundary": "points_cap" if points_cap is not None else "task_completion",
        "returned_record_count": len(items),
        "reported_total": response_total(response),
        "records": review_records(response, asin, market),
        "response": response,
    }, api_key)


def collect_review_pages(
    fetch_page: Any,
    asin: str,
    market: str,
    start_page: int,
    max_pages: int,
    max_records: int,
    points_cap: Optional[int],
    api_key: str,
    save_page: Any = None,
) -> Mapping[str, Any]:
    """Fetch sequential pages until the frozen per-ASIN cap or a safe stop.

    Flyfus reports a total but exposes each review page separately.  We retain
    each request/response and stop immediately if a later page returns no new
    native review ID, preventing an API page parameter regression from being
    mistaken for new consumer reviews.
    """
    pages: List[Mapping[str, Any]] = []
    unique_records: List[Mapping[str, Any]] = []
    seen_ids = set()
    sampled_ids = set()
    max_records = min(max_records, 1000)
    reported_total: Optional[int] = None
    halt_reason = "max_pages_reached"
    for page in range(start_page, start_page + max_pages):
        response = fetch_page(page)
        receipt = review_page_receipt(response, asin, market, page, points_cap, api_key)
        # Save each successful response before advancing; errors still propagate
        # unchanged, and this function never retries a charge-uncertain request.
        if save_page is not None:
            save_page(receipt)
        pages.append(receipt)
        page_total = receipt.get("reported_total")
        if isinstance(page_total, int) and page_total >= 0:
            reported_total = page_total
        raw_ids = [str(item.get("reviewId") or item.get("review_id") or item.get("id") or "").strip()
                   for item in response_items(response)]
        newly_sampled = set()
        for raw_id in raw_ids:
            if raw_id and raw_id not in sampled_ids and len(sampled_ids) < max_records:
                sampled_ids.add(raw_id)
                newly_sampled.add(raw_id)
        page_records = [record for record in receipt["records"] if record["content_id"] in newly_sampled]
        if not page_records:
            halt_reason = ("empty_page" if not receipt["returned_record_count"] else
                           "nonincremental_page" if not newly_sampled and any(raw_ids) else "normalization_empty")
            break
        new_records = [record for record in page_records if record["content_id"] not in seen_ids]
        if not new_records:
            halt_reason = "nonincremental_page"
            break
        for record in new_records:
            if record["content_id"] in seen_ids:
                continue
            seen_ids.add(record["content_id"])
            unique_records.append(record)
            if len(unique_records) >= max_records:
                break
        target = min(reported_total, max_records) if reported_total is not None else max_records
        if len(sampled_ids) >= target:
            halt_reason = "reported_total_reached" if reported_total is not None and reported_total <= max_records else "per_asin_cap_reached"
            break
    return _redact({
        "provider": "flyfus",
        "operation": "review_pages",
        "status": "complete",
        "halt_reason": halt_reason,
        "request": {"asin": asin, "market": market, "start_page": start_page, "max_pages": max_pages, "max_records": max_records},
        "points_reserved": 10 * len(pages),
        "points_cap": points_cap,
        "spend_boundary": "points_cap" if points_cap is not None else "task_completion",
        "pages_fetched": len(pages),
        "returned_record_count": sum(int(page["returned_record_count"]) for page in pages),
        "unique_record_count": len(unique_records),
        "sampled_native_id_count": len(sampled_ids),
        "reported_total": reported_total,
        "records": unique_records,
        "pages": pages,
    }, api_key)


def review_probe_receipt(response: Mapping[str, Any], asin: str, market: str, points_cap: Optional[int], api_key: str) -> Mapping[str, Any]:
    items = response_items(response)
    total = response_total(response)
    mismatch = total is not None and total > len(items) and len(items) < 1000
    status = "batch_contract_mismatch" if mismatch else "probe_complete"
    reason = "响应显示仍有更多评论，但首批少于用户确认的 1000 条；停止自动分页，需核验接口分页与计费。" if mismatch else None
    return _redact({"provider": "flyfus", "operation": "review_probe", "status": status, "halt_reason": reason, "request": {"asin": asin, "market": market, "page": 1}, "points_reserved": 10, "points_cap": points_cap, "spend_boundary": "points_cap" if points_cap is not None else "task_completion", "returned_record_count": len(items), "reported_total": total, "records": review_records(response, asin, market), "response": response}, api_key)


def recommendation_receipt(response: Mapping[str, Any], request_payload: Mapping[str, Any], points_cap: Optional[int], reserve_points: int, api_key: str) -> Mapping[str, Any]:
    items = response_items(response)
    return _redact({"provider": "flyfus", "operation": "recommended_qa", "status": "complete", "request": dict(request_payload), "points_cap": points_cap, "points_reserved": reserve_points, "spend_boundary": "points_cap" if points_cap is not None else "task_completion", "returned_question_count": len(items), "response": response}, api_key)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(target))
    if os.name != "nt":
        os.chmod(str(target), 0o600)


def _positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="隔离的 Flyfus V5 适配器；按冻结范围完成并记录积分")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-config", help="只在配置不存在时创建私密空模板")
    init.add_argument("--config", type=Path, default=argparse.SUPPRESS)
    probe = commands.add_parser("probe-review", help="请求一次评论首批并验证批量合同；不会自动翻页")
    probe.add_argument("--asin", required=True)
    probe.add_argument("--market", required=True)
    probe.add_argument("--points-cap", type=_positive, help="可选的兼容性上限；默认按冻结范围完成")
    probe.add_argument("--output", type=Path, required=True)
    review_pages = commands.add_parser("fetch-review-pages", help="按页顺序抓取商品评论，保留每页回执并在重复页安全停止")
    review_pages.add_argument("--asin", required=True)
    review_pages.add_argument("--market", required=True)
    review_pages.add_argument("--start-page", type=_positive, default=1)
    review_pages.add_argument("--max-pages", type=_positive, required=True)
    review_pages.add_argument("--max-records", type=_positive, default=1000)
    review_pages.add_argument("--points-cap", type=_positive, help="可选的兼容性上限；默认按冻结范围完成")
    review_pages.add_argument("--output", type=Path, required=True)
    qa = commands.add_parser("recommendations", help="获取关键词或商品推荐问答")
    qa.add_argument("--kind", choices=("product", "keyword"), required=True)
    qa.add_argument("--asin")
    qa.add_argument("--keyword")
    qa.add_argument("--market", required=True)
    qa.add_argument("--with-answer", action="store_true")
    qa.add_argument("--page", type=_positive, default=1)
    qa.add_argument("--points-cap", type=_positive, help="可选的兼容性上限；默认按冻结范围完成")
    qa.add_argument("--reserve-points", type=_positive, required=True)
    qa.add_argument("--output", type=Path, required=True)
    return parser


def execute(args: argparse.Namespace) -> Mapping[str, Any]:
    config = getattr(args, "config", DEFAULT_CONFIG_PATH)
    if args.command == "init-config":
        return initialize_config(config)
    if args.command == "recommendations" and args.points_cap is not None and args.reserve_points > args.points_cap:
        raise FlyfusConfigurationError("推荐问答预留积分超过本次积分上限；未发送请求")
    api_key = load_api_key(config)
    if args.command == "probe-review":
        if args.points_cap is not None and args.points_cap < 10:
            raise FlyfusConfigurationError("评论首批需至少预留 10 积分；未发送请求")
        response = _json_request("/api/v2/product/review", {"asin": args.asin, "market": args.market, "page": 1}, api_key, args.timeout_seconds)
        result = review_probe_receipt(response, args.asin, args.market, args.points_cap, api_key)
        _write_json(args.output, result)
        return {key: value for key, value in result.items() if key not in {"response", "records"}}
    if args.command == "fetch-review-pages":
        def fetch_page(page: int) -> Mapping[str, Any]:
            return _json_request(
                "/api/v2/product/review",
                {"asin": args.asin, "market": args.market, "page": page},
                api_key,
                args.timeout_seconds,
            )
        result = collect_review_pages(
            fetch_page,
            args.asin,
            args.market,
            args.start_page,
            args.max_pages,
            args.max_records,
            args.points_cap,
            api_key,
            save_page=lambda receipt: _write_json(
                args.output.parent / (args.output.name + ".pages") / ("page-%06d.json" % receipt["request"]["page"]),
                receipt,
            ),
        )
        _write_json(args.output, result)
        return {key: value for key, value in result.items() if key not in {"records", "pages"}}
    if args.kind == "product":
        if not args.asin or args.keyword:
            raise FlyfusConfigurationError("商品问答需要 --asin，且不能同时提供 --keyword")
        endpoint = "/api/v2/product/question"
        payload: Dict[str, Any] = {"asin": args.asin, "market": args.market, "withAnswer": bool(args.with_answer), "page": args.page}
    else:
        if not args.keyword or args.asin:
            raise FlyfusConfigurationError("关键词问答需要 --keyword，且不能同时提供 --asin")
        endpoint = "/api/v2/keyword/question"
        payload = {"keyword": args.keyword, "market": args.market, "withAnswer": bool(args.with_answer)}
    response = _json_request(endpoint, payload, api_key, args.timeout_seconds)
    result = recommendation_receipt(response, payload, args.points_cap, args.reserve_points, api_key)
    _write_json(args.output, result)
    return {key: value for key, value in result.items() if key != "response"}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = execute(args)
    except FlyfusError as exc:
        sys.stderr.write(json.dumps({"status": "flyfus_error", "error": str(exc)}, ensure_ascii=False) + "\n")
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
