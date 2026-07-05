#!/usr/bin/env python3
"""
Unified Amazon front crawler for:
1. BSR category ranking pages
2. keyword search result pages
3. competitor storefront pages

The crawler reads SellerSprite extension data from a visible Chrome session.
It does not solve CAPTCHA or bypass verification; when verification appears,
it saves state and waits for manual handling.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse, urlunparse

from selenium.common.exceptions import JavascriptException, TimeoutException, WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    Workbook = None
    load_workbook = None

from amazon_category_rank_crawler import (
    BatchPauseScheduler,
    REQUESTED_DATA_FIELDS,
    UserFacingError,
    append_jsonl,
    build_runtime_config as build_category_runtime_config,
    clean_url,
    config_bool,
    config_float,
    config_int,
    config_text,
    country_from_flag_code_or_text,
    detect_block,
    discover_child_categories,
    dump_json,
    ensure_dir,
    extract_by_selectors,
    extract_current_category_path,
    extract_node_id,
    extract_table_rows,
    find_next_page_url,
    load_json,
    normalize_header,
    normalize_space,
    now_iso,
    now_ts,
    parse_field_from_text,
    parse_table_row_fields,
    read_jsonl,
    resolve_path,
    run_crawl as run_category_crawl,
    save_debug_snapshot,
    sleep_between_pages,
    slugify,
    start_driver,
    validate_amazon_url,
    wait_for_amazon_products,
    wait_for_manual_clear,
    wait_for_sellersprite_data,
    wait_for_sellersprite_data_or_prompt,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT_DIR / "config" / "amazon_front_crawler.json"
SUPPORTED_MODES = {"bsr_category", "keyword_search", "storefront"}
SEARCH_SORT_OPTIONS = {
    "Featured": "featured-rank",
    "Price: Low to High": "price-asc-rank",
    "Price: High to Low": "price-desc-rank",
    "Avg. Customer Review": "review-rank",
    "Newest Arrivals": "date-desc-rank",
    "Best Sellers": "exact-aware-popularity-rank",
}


FRONT_DEDUP_HEADERS = [
    "来源类型",
    "来源关键词列表",
    "来源搜索排序规则列表",
    "来源店铺URL列表",
    "来源店铺名称列表",
    "来源店铺排序规则列表",
    "来源类目路径列表",
    "来源页面URL列表",
    "出现次数",
    "最佳页码",
    "最佳排名",
    "ASIN",
    "商品标题",
    "商品URL",
    "评论数量",
    "评分值",
    "卖家名称",
    "品牌名称",
    "卖家所处国家",
    "近30天销量（子体）",
    "近30天销量（父体）",
    "FBA费用",
    "毛利率",
    "配送方式",
    "配送时长",
    "上架时间",
    "自然搜索词数量",
    "广告搜索词数量",
    "抓取时间",
    "加载状态",
    "备注",
]

FRONT_FIELD_TO_HEADER = {
    "source_types": "来源类型",
    "source_keywords": "来源关键词列表",
    "source_search_sort_orders": "来源搜索排序规则列表",
    "source_store_urls": "来源店铺URL列表",
    "source_store_names": "来源店铺名称列表",
    "source_store_sort_orders": "来源店铺排序规则列表",
    "source_category_paths": "来源类目路径列表",
    "source_page_urls": "来源页面URL列表",
    "appearance_count": "出现次数",
    "best_page_number": "最佳页码",
    "best_rank": "最佳排名",
    "asin": "ASIN",
    "title": "商品标题",
    "product_url": "商品URL",
    "review_count": "评论数量",
    "rating_value": "评分值",
    "seller_name": "卖家名称",
    "brand_name": "品牌名称",
    "seller_country": "卖家所处国家",
    "sales_30_days_child": "近30天销量（子体）",
    "sales_30_days_parent": "近30天销量（父体）",
    "fba_fee": "FBA费用",
    "gross_margin": "毛利率",
    "fulfillment_method": "配送方式",
    "delivery_duration": "配送时长",
    "launch_date": "上架时间",
    "organic_keywords_count": "自然搜索词数量",
    "ad_keywords_count": "广告搜索词数量",
    "scraped_at": "抓取时间",
    "load_status": "加载状态",
    "note": "备注",
}


@dataclass
class FrontRuntimeConfig:
    mode: str
    job_id: str
    outputs_root: Path
    keywords_file: Path
    store_urls_file: Path
    start_url: str
    max_pages_per_keyword: int
    include_sponsored: bool
    keyword_sort_orders: List[str]
    store_page_limit: Optional[int]
    store_sort_orders: List[str]
    resume: bool
    browser_mode: str
    chrome_binary: str
    chrome_user_data_dir: Path
    chrome_profile_directory: str
    debugger_address: str
    extension_path: Path
    activate_plugin: bool
    page_timeout: int
    plugin_timeout: int
    plugin_retry_attempts: int
    plugin_retry_wait_seconds: float
    plugin_retry_wait_seconds_max: float
    plugin_relaunch_retry_attempts: int
    plugin_relaunch_wait_seconds: float
    plugin_second_relaunch_retry_attempts: int
    plugin_second_relaunch_wait_seconds: float
    manual_pause_timeout: int
    delay_seconds_min: float
    delay_seconds_max: float
    batch_pause_pages_min: int
    batch_pause_pages_max: int
    batch_pause_seconds_min: float
    batch_pause_seconds_max: float
    page_scroll_before_extract: bool
    page_scroll_max_rounds: int
    page_scroll_step_ratio: float
    page_scroll_wait_seconds: float
    page_scroll_stable_rounds: int
    save_debug_snapshots: bool
    field_selectors: Dict[str, List[str]] = field(default_factory=dict)


class FrontStateStore:
    def __init__(self, path: Path, runtime: FrontRuntimeConfig, initial_queue: Sequence[Dict[str, Any]]) -> None:
        self.path = path
        self.runtime = runtime
        self.initial_queue = list(initial_queue)
        self.data: Dict[str, Any] = {}

    def load_or_create(self) -> None:
        if self.runtime.resume and self.path.exists():
            self.data = load_json(self.path)
            return
        self.data = {
            "job_id": self.runtime.job_id,
            "mode": self.runtime.mode,
            "created_at": now_iso(),
            "queue": self.initial_queue,
            "current": None,
            "completed_pages": [],
            "completed_sources": [],
            "records_count": 0,
            "failures_count": 0,
        }
        self.flush()

    def flush(self) -> None:
        self.data["updated_at"] = now_iso()
        dump_json(self.path, self.data)

    def next_work(self) -> Optional[Dict[str, Any]]:
        current = self.data.get("current")
        if current:
            return current
        queue = self.data.get("queue") or []
        if not queue:
            return None
        current = queue.pop(0)
        self.data["queue"] = queue
        self.data["current"] = current
        self.flush()
        return current

    def set_current(self, current: Optional[Dict[str, Any]]) -> None:
        self.data["current"] = current
        self.flush()

    def mark_page_completed(self, key: str, count: int) -> None:
        completed = set(self.data.setdefault("completed_pages", []))
        completed.add(key)
        self.data["completed_pages"] = sorted(completed)
        self.data["records_count"] = int(self.data.get("records_count") or 0) + count
        self.flush()

    def is_page_completed(self, key: str) -> bool:
        return key in set(self.data.get("completed_pages") or [])

    def finish_current_source(self, reason: str = "") -> None:
        current = self.data.get("current")
        if current:
            source_id = str(current.get("source_id") or current.get("keyword") or current.get("store_url") or "")
            done = set(self.data.setdefault("completed_sources", []))
            done.add(source_id)
            self.data["completed_sources"] = sorted(done)
            self.data.setdefault("completed_source_reasons", {})[source_id] = reason
        self.data["current"] = None
        self.flush()

    def log_failure(self) -> None:
        self.data["failures_count"] = int(self.data.get("failures_count") or 0) + 1
        self.flush()

    def mark_manual_pause(self, reason: str, page_url: str) -> None:
        self.data["manual_pause"] = {
            "paused_at": now_iso(),
            "reason": reason,
            "page_url": page_url,
            "current": self.data.get("current"),
        }
        self.flush()

    def clear_manual_pause(self) -> None:
        if self.data.pop("manual_pause", None) is not None:
            self.flush()


def parse_sort_orders(raw_value: Any, field_name: str, subject_name: str) -> List[str]:
    if raw_value in ("", None):
        return []
    if isinstance(raw_value, str):
        candidates = [part.strip() for part in re.split(r"[,;，；]+", raw_value) if part.strip()]
    elif isinstance(raw_value, list):
        candidates = [str(item).strip() for item in raw_value if str(item).strip()]
    else:
        raise UserFacingError(f"配置项 `{field_name}` 必须是数组、逗号分隔文本或空值。")
    normalized: List[str] = []
    alias_map = {normalize_header(key): key for key in SEARCH_SORT_OPTIONS}
    for candidate in candidates:
        key = alias_map.get(normalize_header(candidate))
        if not key:
            raise UserFacingError(f"不支持的{subject_name}排序规则：{candidate}")
        if key not in normalized:
            normalized.append(key)
    return normalized


def parse_store_sort_orders(raw_value: Any) -> List[str]:
    return parse_sort_orders(raw_value, "store_sort_orders", "店铺")


def parse_keyword_sort_orders(raw_value: Any) -> List[str]:
    return parse_sort_orders(raw_value, "keyword_sort_orders", "关键词")


def prompt_sort_orders(subject_name: str) -> List[str]:
    labels = list(SEARCH_SORT_OPTIONS.keys())
    print(f"请选择{subject_name}排序规则，可多选。输入序号，用逗号分隔；直接回车默认 Featured。")
    for index, label in enumerate(labels, start=1):
        print(f"  {index}. {label}")
    try:
        raw = input("排序规则：").strip()
    except EOFError:
        raw = ""
    if not raw:
        return ["Featured"]
    selected: List[str] = []
    for part in re.split(r"[,;，；\\s]+", raw):
        if not part:
            continue
        if not part.isdigit():
            raise UserFacingError("排序规则请输入序号，例如：1,6")
        index = int(part)
        if index < 1 or index > len(labels):
            raise UserFacingError(f"排序规则序号超出范围：{index}")
        label = labels[index - 1]
        if label not in selected:
            selected.append(label)
    return selected or ["Featured"]


def prompt_store_sort_orders() -> List[str]:
    return prompt_sort_orders("店铺商品")


def prompt_keyword_sort_orders() -> List[str]:
    return prompt_sort_orders("关键词搜索结果")


def prompt_store_page_limit() -> int:
    print("请输入每个店铺、每个排序规则要抓取前多少页商品，最多 20 页；直接回车默认 20。")
    try:
        raw = input("抓取页数：").strip()
    except EOFError:
        raw = ""
    if not raw:
        return 20
    if not raw.isdigit():
        raise UserFacingError("店铺抓取页数请输入 1-20 的整数。")
    value = int(raw)
    if value < 1 or value > 20:
        raise UserFacingError("店铺抓取页数必须在 1-20 之间。")
    return value


def build_front_runtime_config(config: Dict[str, Any], no_resume: bool) -> FrontRuntimeConfig:
    mode = config_text(config, "mode", "keyword_search").lower()
    if mode not in SUPPORTED_MODES:
        raise UserFacingError("配置项 `mode` 只支持 bsr_category、keyword_search 或 storefront。")

    job_id = config_text(config, "job_id") or f"amazon-front-{mode}-{now_ts()}"
    outputs_root = resolve_path(config_text(config, "outputs_root", "outputs"))
    keywords_file = resolve_path(config_text(config, "keywords_file", "inputs/keywords.csv"))
    store_urls_file = resolve_path(config_text(config, "store_urls_file", "inputs/storefronts.csv"))
    start_url = config_text(config, "start_url")

    if mode == "bsr_category":
        if not start_url:
            raise UserFacingError("bsr_category 模式下 `start_url` 不能为空。")
        validate_amazon_url(start_url)
    if mode == "keyword_search" and not keywords_file.exists():
        raise UserFacingError(f"没有找到关键词表格：{keywords_file}")
    if mode == "storefront" and not store_urls_file.exists():
        raise UserFacingError(f"没有找到店铺 URL 表格：{store_urls_file}")

    browser_mode = config_text(config, "browser_mode", "launch").lower()
    if browser_mode not in {"launch", "attach", "reuse", "applescript"}:
        raise UserFacingError("配置项 `browser_mode` 只支持 launch、attach、reuse 或 applescript。")

    extension_path_text = config_text(config, "extension_path")
    extension_path = resolve_path(extension_path_text) if extension_path_text else Path("")
    if browser_mode == "launch" and extension_path_text and not extension_path.exists():
        raise UserFacingError(f"没有找到卖家精灵扩展目录：{extension_path}")

    min_delay = config_float(config, "delay_seconds_min", 4)
    max_delay = config_float(config, "delay_seconds_max", 9)
    if max_delay < min_delay:
        max_delay = min_delay
    batch_pages_min = config_int(config, "batch_pause_pages_min", 20) or 0
    batch_pages_max = config_int(config, "batch_pause_pages_max", 30) or 0
    if batch_pages_min < 0 or batch_pages_max < 0:
        raise UserFacingError("配置项 batch_pause_pages_min / batch_pause_pages_max 不能小于 0。")
    if batch_pages_max and batch_pages_max < batch_pages_min:
        batch_pages_max = batch_pages_min
    batch_seconds_min = config_float(config, "batch_pause_seconds_min", 60)
    batch_seconds_max = config_float(config, "batch_pause_seconds_max", 180)
    if batch_seconds_min < 0 or batch_seconds_max < 0:
        raise UserFacingError("配置项 batch_pause_seconds_min / batch_pause_seconds_max 不能小于 0。")
    if batch_seconds_max < batch_seconds_min:
        batch_seconds_max = batch_seconds_min
    plugin_retry_wait_min = config_float(
        config,
        "plugin_retry_wait_seconds_min",
        config_float(config, "plugin_retry_wait_seconds", 10),
    )
    plugin_retry_wait_max = config_float(config, "plugin_retry_wait_seconds_max", 20)
    if plugin_retry_wait_min < 0 or plugin_retry_wait_max < 0:
        raise UserFacingError("配置项 plugin_retry_wait_seconds_min / plugin_retry_wait_seconds_max 不能小于 0。")
    if plugin_retry_wait_max < plugin_retry_wait_min:
        plugin_retry_wait_max = plugin_retry_wait_min
    page_scroll_max_rounds = max(config_int(config, "page_scroll_max_rounds", 18) or 0, 0)
    page_scroll_step_ratio = config_float(config, "page_scroll_step_ratio", 0.85) or 0.85
    if page_scroll_step_ratio <= 0:
        raise UserFacingError("配置项 page_scroll_step_ratio 必须大于 0。")
    page_scroll_wait_seconds = max(config_float(config, "page_scroll_wait_seconds", 1.0) or 0, 0)
    page_scroll_stable_rounds = max(config_int(config, "page_scroll_stable_rounds", 2) or 1, 1)

    raw_selectors = config.get("field_selectors") or {}
    field_selectors: Dict[str, List[str]] = {}
    if isinstance(raw_selectors, dict):
        for key, value in raw_selectors.items():
            if isinstance(value, list):
                field_selectors[key] = [str(item).strip() for item in value if str(item).strip()]

    max_pages_per_keyword = config_int(config, "max_pages_per_keyword", 7) or 7
    if max_pages_per_keyword < 1:
        raise UserFacingError("配置项 `max_pages_per_keyword` 必须大于 0。")
    keyword_sort_orders = parse_keyword_sort_orders(config.get("keyword_sort_orders"))
    store_sort_orders = parse_store_sort_orders(config.get("store_sort_orders"))
    store_page_limit = config_int(config, "store_page_limit")
    if mode == "keyword_search" and not keyword_sort_orders:
        keyword_sort_orders = ["Featured"]
    if mode == "storefront":
        if not store_sort_orders:
            store_sort_orders = prompt_store_sort_orders()
        if store_page_limit is None:
            store_page_limit = prompt_store_page_limit()
        if store_page_limit < 1:
            raise UserFacingError("店铺抓取页数必须大于 0。")
        if store_page_limit > 20:
            raise UserFacingError("店铺抓取最多支持 20 页，请把 store_page_limit 调整到 20 以内。")

    return FrontRuntimeConfig(
        mode=mode,
        job_id=slugify(job_id),
        outputs_root=outputs_root,
        keywords_file=keywords_file,
        store_urls_file=store_urls_file,
        start_url=start_url,
        max_pages_per_keyword=max_pages_per_keyword,
        include_sponsored=config_bool(config, "include_sponsored", False),
        keyword_sort_orders=keyword_sort_orders,
        store_page_limit=store_page_limit,
        store_sort_orders=store_sort_orders,
        resume=False if no_resume else config_bool(config, "resume", True),
        browser_mode=browser_mode,
        chrome_binary=config_text(config, "chrome_binary"),
        chrome_user_data_dir=resolve_path(config_text(config, "chrome_user_data_dir", "chrome_profiles/category-rank-sellersprite")),
        chrome_profile_directory=config_text(config, "chrome_profile_directory", "Default") or "Default",
        debugger_address=config_text(config, "debugger_address", "127.0.0.1:9222"),
        extension_path=extension_path,
        activate_plugin=config_bool(config, "activate_plugin", True),
        page_timeout=config_int(config, "page_timeout", 90) or 90,
        plugin_timeout=config_int(config, "plugin_timeout", 120) or 120,
        plugin_retry_attempts=max(config_int(config, "plugin_retry_attempts", 5) or 0, 0),
        plugin_retry_wait_seconds=plugin_retry_wait_min,
        plugin_retry_wait_seconds_max=plugin_retry_wait_max,
        plugin_relaunch_retry_attempts=max(config_int(config, "plugin_relaunch_retry_attempts", 3) or 0, 0),
        plugin_relaunch_wait_seconds=max(config_float(config, "plugin_relaunch_wait_seconds", 300) or 0, 0),
        plugin_second_relaunch_retry_attempts=max(config_int(config, "plugin_second_relaunch_retry_attempts", 3) or 0, 0),
        plugin_second_relaunch_wait_seconds=max(config_float(config, "plugin_second_relaunch_wait_seconds", 600) or 0, 0),
        manual_pause_timeout=config_int(config, "manual_pause_timeout", 900) or 900,
        delay_seconds_min=min_delay,
        delay_seconds_max=max_delay,
        batch_pause_pages_min=batch_pages_min,
        batch_pause_pages_max=batch_pages_max,
        batch_pause_seconds_min=batch_seconds_min,
        batch_pause_seconds_max=batch_seconds_max,
        page_scroll_before_extract=config_bool(config, "page_scroll_before_extract", True),
        page_scroll_max_rounds=page_scroll_max_rounds,
        page_scroll_step_ratio=page_scroll_step_ratio,
        page_scroll_wait_seconds=page_scroll_wait_seconds,
        page_scroll_stable_rounds=page_scroll_stable_rounds,
        save_debug_snapshots=config_bool(config, "save_debug_snapshots", True),
        field_selectors=field_selectors,
    )


def read_input_rows(path: Path) -> List[Dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            return [{str(k or "").strip(): normalize_space(str(v or "")) for k, v in row.items()} for row in reader]
    if suffix in {".xlsx", ".xlsm"}:
        if load_workbook is None:
            raise UserFacingError("缺少 openpyxl，无法读取 Excel 输入表。")
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [normalize_space(str(value or "")) for value in rows[0]]
        output: List[Dict[str, str]] = []
        for raw_row in rows[1:]:
            row: Dict[str, str] = {}
            for index, header in enumerate(headers):
                if not header:
                    continue
                value = raw_row[index] if index < len(raw_row) else ""
                row[header] = normalize_space(str(value or ""))
            output.append(row)
        return output
    raise UserFacingError(f"暂不支持的输入表格式：{path.suffix}")


def pick_column(row: Dict[str, str], aliases: Sequence[str]) -> str:
    normalized_to_key = {normalize_header(key): key for key in row.keys()}
    for alias in aliases:
        key = normalized_to_key.get(normalize_header(alias))
        if key:
            return normalize_space(row.get(key) or "")
    return ""


def load_keywords(path: Path) -> List[str]:
    keywords: List[str] = []
    seen = set()
    for row in read_input_rows(path):
        keyword = pick_column(row, ["keyword", "关键词"])
        if keyword and keyword not in seen:
            keywords.append(keyword)
            seen.add(keyword)
    if not keywords:
        raise UserFacingError("关键词表必须包含 `keyword` 或 `关键词` 列，且至少有一个关键词。")
    return keywords


def load_storefronts(path: Path) -> List[Dict[str, str]]:
    stores: List[Dict[str, str]] = []
    seen = set()
    for row in read_input_rows(path):
        store_url = pick_column(row, ["store_url", "店铺URL", "店铺url"])
        store_name = pick_column(row, ["store_name", "店铺名称", "店铺名"])
        if not store_url or store_url in seen:
            continue
        validate_amazon_url(store_url)
        stores.append({"store_url": store_url, "store_name": store_name})
        seen.add(store_url)
    if not stores:
        raise UserFacingError("店铺 URL 表必须包含 `store_url` 或 `店铺URL` 列，且至少有一个 Amazon 店铺链接。")
    return stores


def build_initial_queue(runtime: FrontRuntimeConfig) -> List[Dict[str, Any]]:
    if runtime.mode == "keyword_search":
        queue: List[Dict[str, Any]] = []
        for keyword in load_keywords(runtime.keywords_file):
            for sort_order in runtime.keyword_sort_orders:
                queue.append(
                    {
                        "source_type": "keyword_search",
                        "source_id": f"{keyword}|sort:{sort_order}",
                        "keyword": keyword,
                        "search_sort_order": sort_order,
                        "page_number": 1,
                        "page_url": build_keyword_search_url(keyword, sort_order),
                        "seen_page_urls": [],
                        "previous_page_asins": [],
                    }
                )
        return queue
    if runtime.mode == "storefront":
        queue: List[Dict[str, Any]] = []
        for store in load_storefronts(runtime.store_urls_file):
            for sort_order in runtime.store_sort_orders:
                queue.append(
                    {
                        "source_type": "storefront",
                        "source_id": f"{store['store_url']}|sort:{sort_order}",
                        "store_url": store["store_url"],
                        "store_name": store.get("store_name", ""),
                        "store_sort_order": sort_order,
                        "page_number": 1,
                        "page_url": store["store_url"],
                        "seen_page_urls": [],
                        "previous_page_asins": [],
                        "prepared_storefront": False,
                    }
                )
        return queue
    return []


def build_keyword_search_url(keyword: str, sort_order: str = "Featured") -> str:
    base_url = f"https://www.amazon.com/s?k={quote_plus(keyword)}"
    return apply_sort_to_url(base_url, sort_order)


def apply_sort_to_url(url: str, sort_order: str) -> str:
    sort_code = SEARCH_SORT_OPTIONS.get(sort_order)
    if not sort_code:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["s"] = [sort_code]
    flat_query = urlencode([(key, value) for key, values in query.items() for value in values])
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, flat_query, parsed.fragment))


def wait_for_product_cards(driver: WebDriver, runtime: FrontRuntimeConfig, timeout: Optional[int] = None) -> bool:
    original_timeout = runtime.page_timeout
    if timeout is not None:
        runtime.page_timeout = timeout
    try:
        wait_for_amazon_products(driver, runtime)
        return True
    except TimeoutException:
        return False
    finally:
        runtime.page_timeout = original_timeout


def wait_for_page_or_manual_front(
    driver: WebDriver,
    runtime: FrontRuntimeConfig,
    state: FrontStateStore,
    failures_path: Path,
    debug_dir: Path,
    current: Dict[str, Any],
) -> bool:
    block_reason = detect_block(driver)
    if block_reason:
        state.mark_manual_pause(block_reason, driver.current_url)
        cleared = wait_for_manual_clear(driver, block_reason, runtime.manual_pause_timeout)
        if cleared:
            state.clear_manual_pause()
        if not cleared:
            log_front_failure(failures_path, state, current, block_reason, "人工处理超时", driver.current_url)
            if runtime.save_debug_snapshots:
                save_debug_snapshot(driver, debug_dir, block_reason)
            return False
    if wait_for_product_cards(driver, runtime):
        return True
    return False


def find_store_products_url(driver: WebDriver) -> str:
    script = r"""
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const absUrl = (href) => {
  try { return new URL(href, location.href).href; } catch (err) { return href || ''; }
};
const phrases = [
  'products', 'shop all', 'all products', 'see all products', 'visit the store',
  '商品', '全部商品', '所有商品', '店铺商品'
];
const links = [...document.querySelectorAll('a[href]')];
for (const link of links) {
  const text = norm(link.innerText || link.textContent || link.getAttribute('aria-label') || '').toLowerCase();
  const href = absUrl(link.getAttribute('href') || link.href || '');
  if (!href || !/amazon\./i.test(href)) continue;
  if (phrases.some(phrase => text.includes(phrase))) return href;
}
for (const link of links) {
  const href = absUrl(link.getAttribute('href') || link.href || '');
  if (/\/s\?/.test(href) && /(?:me=|rh=|i=merchant-items)/.test(href)) return href;
}
return '';
"""
    try:
        return str(driver.execute_script(script) or "")
    except (JavascriptException, WebDriverException):
        return ""


def prepare_storefront_page(driver: WebDriver, runtime: FrontRuntimeConfig, current: Dict[str, Any]) -> None:
    if current.get("prepared_storefront"):
        return
    sort_order = str(current.get("store_sort_order") or "Featured")
    if wait_for_product_cards(driver, runtime, timeout=12):
        sorted_url = apply_sort_to_url(driver.current_url, sort_order)
        if clean_url(sorted_url) != clean_url(driver.current_url):
            driver.get(sorted_url)
        current["prepared_storefront"] = True
        current["page_url"] = driver.current_url
        return
    products_url = find_store_products_url(driver)
    if products_url and clean_url(products_url) != clean_url(driver.current_url):
        sorted_url = apply_sort_to_url(products_url, sort_order)
        driver.get(sorted_url)
        current["page_url"] = sorted_url
    current["prepared_storefront"] = True


def extract_front_product_cards(driver: WebDriver, include_sponsored: bool) -> List[Dict[str, Any]]:
    script = r"""
const includeSponsored = arguments[0];
const asinRe = /\b([A-Z0-9]{10})\b/;
const asinUrlRe = /\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?#]|$)/i;
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const absUrl = (href) => {
  try { return new URL(href, location.href).href; } catch (err) { return href || ''; }
};
const isSponsored = (el) => {
  if (el.matches('[data-component-type*="sp-sponsored" i], [class*="AdHolder" i]')) return true;
  const explicit = el.querySelector('[aria-label*="Sponsored" i], .puis-sponsored-label-text, [class*="sponsored-label" i]');
  if (explicit) return true;
  const shortLabels = [...el.querySelectorAll('span, a, i')].map(item => norm(item.innerText || item.textContent || item.getAttribute('aria-label') || ''));
  if (shortLabels.some(text => /^(Sponsored|赞助)$/i.test(text))) return true;
  return false;
};
const getAsin = (el) => {
  for (const attr of ['data-asin', 'asin', 'data-csa-c-asin']) {
    const value = el.getAttribute(attr);
    if (value && /^[A-Z0-9]{10}$/.test(value.trim())) return value.trim();
  }
  for (const a of el.querySelectorAll('a[href]')) {
    const match = a.href.match(asinUrlRe);
    if (match) return match[1];
  }
  const textMatch = norm(el.innerText || el.textContent || '').match(asinRe);
  return textMatch ? textMatch[1] : '';
};
const getUrl = (el, asin) => {
  const links = [...el.querySelectorAll('a[href]')];
  for (const a of links) {
    if (asin && a.href.includes(asin)) return absUrl(a.href);
  }
  for (const a of links) {
    if (/\/(?:dp|gp\/product)\//i.test(a.href)) return absUrl(a.href);
  }
  return '';
};
const getTitle = (el) => {
  const selectors = ['h2 a span', 'h2 span', 'a.a-link-normal span', 'img[alt]', '.p13n-sc-truncate'];
  for (const selector of selectors) {
    const item = el.querySelector(selector);
    if (!item) continue;
    const text = norm(item.getAttribute('alt') || item.innerText || item.textContent || '');
    if (text && text.length > 5) return text;
  }
  return '';
};
const getSellerCountryFlagCode = (el) => {
  const flagElements = [...el.querySelectorAll('[class*="flag-icon-"], [class*="icp-nav-flag-"]')];
  for (const flag of flagElements) {
    const classText = String(flag.getAttribute('class') || '');
    const match = classText.match(/(?:flag-icon|icp-nav-flag)-([a-z]{2})\b/i);
    if (match) return match[1].toLowerCase();
    const hint = norm(flag.getAttribute('title') || flag.getAttribute('aria-label') || '');
    if (hint) return hint;
  }
  return '';
};
const selectors = [
  '.s-result-item[data-asin]:not([data-asin=""])',
  '[data-component-type="s-search-result"][data-asin]:not([data-asin=""])',
  '#gridItemRoot',
  '.zg-grid-general-faceout',
  '.p13n-grid-content',
  '[data-asin]:not([data-asin=""])'
];
const elements = [];
const seenElements = new Set();
for (const selector of selectors) {
  for (const el of document.querySelectorAll(selector)) {
    if (seenElements.has(el)) continue;
    seenElements.add(el);
    elements.push(el);
  }
}
const seenAsins = new Set();
const cards = [];
for (const el of elements) {
  const asin = getAsin(el);
  if (!asin || seenAsins.has(asin)) continue;
  const sponsored = isSponsored(el);
  if (sponsored && !includeSponsored) continue;
  seenAsins.add(asin);
  cards.push({
    asin,
    title: getTitle(el),
    product_url: getUrl(el, asin),
    rank: String(cards.length + 1),
    is_sponsored: sponsored ? 'yes' : 'no',
    seller_country_flag_code: getSellerCountryFlagCode(el),
    text: norm(el.innerText || el.textContent || '')
  });
}
return cards;
"""
    try:
        return list(driver.execute_script(script, include_sponsored) or [])
    except (JavascriptException, WebDriverException):
        return []


def merge_front_product_data(
    driver: WebDriver,
    runtime: FrontRuntimeConfig,
    current: Dict[str, Any],
    plugin_status: str,
) -> List[Dict[str, Any]]:
    cards = extract_front_product_cards(driver, runtime.include_sponsored)
    table_rows = extract_table_rows(driver)
    table_by_asin: Dict[str, Dict[str, str]] = {}
    for row in table_rows:
        asin = str(row.get("asin") or "")
        if not asin:
            continue
        parsed = parse_table_row_fields(row)
        target = table_by_asin.setdefault(asin, {})
        for key, value in parsed.items():
            if value and not target.get(key):
                target[key] = value

    records: List[Dict[str, Any]] = []
    page_number = int(current.get("page_number") or 1)
    for card in cards:
        asin = str(card.get("asin") or "")
        if not asin:
            continue
        record: Dict[str, Any] = {
            "source_type": current.get("source_type", ""),
            "source_id": current.get("source_id", ""),
            "keyword": current.get("keyword", ""),
            "search_sort_order": current.get("search_sort_order", ""),
            "store_url": current.get("store_url", ""),
            "store_name": current.get("store_name", ""),
            "store_sort_order": current.get("store_sort_order", ""),
            "category_path": current.get("category_path", ""),
            "category_name": current.get("category_name", ""),
            "category_node_id": current.get("category_node_id", ""),
            "source_url": current.get("source_url", current.get("page_url", "")),
            "page_url": driver.current_url,
            "page_number": page_number,
            "rank": card.get("rank") or "",
            "is_sponsored": card.get("is_sponsored") or "unknown",
            "asin": asin,
            "title": card.get("title") or "",
            "product_url": card.get("product_url") or "",
            "scraped_at": now_iso(),
            "load_status": plugin_status,
            "note": "",
        }
        text = str(card.get("text") or "")
        for field_name in REQUESTED_DATA_FIELDS:
            record[field_name] = ""
        for field_name, value in table_by_asin.get(asin, {}).items():
            if field_name in REQUESTED_DATA_FIELDS and value:
                record[field_name] = value
        selector_values = extract_by_selectors(driver, card, runtime.field_selectors)
        for field_name, value in selector_values.items():
            if field_name in REQUESTED_DATA_FIELDS and value:
                record[field_name] = normalize_space(str(value))
        for field_name in REQUESTED_DATA_FIELDS:
            if not record.get(field_name):
                record[field_name] = parse_field_from_text(field_name, text)
        if not record.get("seller_country"):
            record["seller_country"] = country_from_flag_code_or_text(str(card.get("seller_country_flag_code") or ""))
        missing_count = sum(1 for field_name in REQUESTED_DATA_FIELDS if not record.get(field_name))
        if plugin_status != "ok":
            record["note"] = "插件数据加载超时，已保存页面可见数据"
        elif missing_count == len(REQUESTED_DATA_FIELDS):
            record["note"] = "插件未展示或选择器未匹配"
        records.append(record)
    return records


def front_page_key(current: Dict[str, Any], page_url: str) -> str:
    return "|".join(
        [
            str(current.get("source_type") or ""),
            str(current.get("source_id") or ""),
            f"page:{current.get('page_number') or 1}",
            clean_url(page_url),
        ]
    )


def log_front_failure(
    failures_path: Path,
    state: FrontStateStore,
    current: Dict[str, Any],
    reason: str,
    message: str,
    page_url: str,
) -> None:
    append_jsonl(
        failures_path,
        {
            "time": now_iso(),
            "source_type": current.get("source_type", ""),
            "keyword": current.get("keyword", ""),
            "search_sort_order": current.get("search_sort_order", ""),
            "store_url": current.get("store_url", ""),
            "store_name": current.get("store_name", ""),
            "store_sort_order": current.get("store_sort_order", ""),
            "category_path": current.get("category_path", ""),
            "page_number": current.get("page_number", ""),
            "page_url": page_url,
            "reason": reason,
            "message": message,
        },
    )
    state.log_failure()


def should_stop_on_repeated_store_page(current: Dict[str, Any], records: Sequence[Dict[str, Any]]) -> bool:
    if current.get("source_type") != "storefront":
        return False
    previous = set(current.get("previous_page_asins") or [])
    current_asins = {str(record.get("asin") or "") for record in records if record.get("asin")}
    return bool(previous and current_asins and previous == current_asins)


def update_next_page_or_finish(
    driver: WebDriver,
    runtime: FrontRuntimeConfig,
    state: FrontStateStore,
    current: Dict[str, Any],
    records: Sequence[Dict[str, Any]],
) -> None:
    source_type = current.get("source_type")
    page_number = int(current.get("page_number") or 1)
    if not records:
        state.finish_current_source("empty_page")
        return
    if should_stop_on_repeated_store_page(current, records):
        state.finish_current_source("repeated_asins")
        return

    next_url = find_next_page_url(driver)
    if not next_url:
        state.finish_current_source("no_next_page")
        return

    seen_urls = [clean_url(url) for url in current.get("seen_page_urls") or []]
    current_clean_url = clean_url(driver.current_url)
    if current_clean_url not in seen_urls:
        seen_urls.append(current_clean_url)
    next_clean_url = clean_url(next_url)
    if next_clean_url in seen_urls:
        state.finish_current_source("repeated_next_url")
        return

    if source_type == "keyword_search" and page_number >= runtime.max_pages_per_keyword:
        state.finish_current_source("keyword_page_limit")
        return
    if source_type == "storefront" and runtime.store_page_limit is not None and page_number >= runtime.store_page_limit:
        state.finish_current_source("store_page_limit")
        return

    current["page_number"] = page_number + 1
    current["page_url"] = next_url
    current["seen_page_urls"] = seen_urls
    current["previous_page_asins"] = [str(record.get("asin") or "") for record in records if record.get("asin")]
    state.set_current(current)


def add_unique(values: List[str], value: Any) -> None:
    text = normalize_space(str(value or ""))
    if text and text not in values:
        values.append(text)


def numeric_sort_value(value: Any, fallback: int = 1_000_000) -> int:
    try:
        text = normalize_space(str(value or ""))
        match = re.search(r"\d+", text)
        return int(match.group(0)) if match else fallback
    except (TypeError, ValueError):
        return fallback


def build_front_dedup_rows(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    accumulators: Dict[str, Dict[str, List[str]]] = {}
    best_keys: Dict[str, tuple[int, int]] = {}

    for row in records:
        asin = str(row.get("asin") or "")
        if not asin:
            continue
        target = grouped.setdefault(asin, {})
        acc = accumulators.setdefault(
            asin,
            {
                "source_types": [],
                "source_keywords": [],
                "source_search_sort_orders": [],
                "source_store_urls": [],
                "source_store_names": [],
                "source_store_sort_orders": [],
                "source_category_paths": [],
                "source_page_urls": [],
                "notes": [],
                "statuses": [],
            },
        )
        add_unique(acc["source_types"], row.get("source_type") or "bsr_category")
        add_unique(acc["source_keywords"], row.get("keyword"))
        add_unique(acc["source_search_sort_orders"], row.get("search_sort_order"))
        add_unique(acc["source_store_urls"], row.get("store_url"))
        add_unique(acc["source_store_names"], row.get("store_name"))
        add_unique(acc["source_store_sort_orders"], row.get("store_sort_order"))
        add_unique(acc["source_category_paths"], row.get("category_path"))
        add_unique(acc["source_page_urls"], row.get("page_url") or row.get("category_url"))
        add_unique(acc["notes"], row.get("note"))
        add_unique(acc["statuses"], row.get("load_status"))

        for key in ["asin", "title", "product_url", "scraped_at"]:
            if row.get(key) and not target.get(key):
                target[key] = row[key]
        for field_name in REQUESTED_DATA_FIELDS:
            if row.get(field_name) and not target.get(field_name):
                target[field_name] = row[field_name]

        page_number = numeric_sort_value(row.get("page_number"))
        rank = numeric_sort_value(row.get("rank"))
        best_key = (page_number, rank)
        if asin not in best_keys or best_key < best_keys[asin]:
            best_keys[asin] = best_key
            target["best_page_number"] = row.get("page_number", "")
            target["best_rank"] = row.get("rank", "")

        target["appearance_count"] = int(target.get("appearance_count") or 0) + 1

    output: List[Dict[str, Any]] = []
    for asin, row in grouped.items():
        acc = accumulators.get(asin, {})
        merged = dict(row)
        merged["source_types"] = " ; ".join(acc.get("source_types", []))
        merged["source_keywords"] = " ; ".join(acc.get("source_keywords", []))
        merged["source_search_sort_orders"] = " ; ".join(acc.get("source_search_sort_orders", []))
        merged["source_store_urls"] = " ; ".join(acc.get("source_store_urls", []))
        merged["source_store_names"] = " ; ".join(acc.get("source_store_names", []))
        merged["source_store_sort_orders"] = " ; ".join(acc.get("source_store_sort_orders", []))
        merged["source_category_paths"] = " ; ".join(acc.get("source_category_paths", []))
        merged["source_page_urls"] = " ; ".join(acc.get("source_page_urls", []))
        merged["load_status"] = "ok" if "ok" in acc.get("statuses", []) else " ; ".join(acc.get("statuses", []))
        merged["note"] = " ; ".join(acc.get("notes", []))
        output.append(merged)
    output.sort(key=lambda item: (numeric_sort_value(item.get("best_page_number")), numeric_sort_value(item.get("best_rank")), item.get("asin", "")))
    return output


def write_front_sheet(ws: Any, headers: Sequence[str], rows: Sequence[Dict[str, Any]], raw_headers: bool = False) -> None:
    ws.append(list(headers))
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
    for row in rows:
        if raw_headers:
            ws.append([row.get(header, "") for header in headers])
        else:
            ws.append([row.get(field, "") for field, header in FRONT_FIELD_TO_HEADER.items() if header in headers])
    for column_index, header in enumerate(headers, start=1):
        width = min(max(len(str(header)) + 2, 12), 42)
        ws.column_dimensions[get_column_letter(column_index)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def write_front_workbook(records_path: Path, failures_path: Path, output_xlsx: Path) -> None:
    if Workbook is None:
        raise UserFacingError("缺少 openpyxl，无法生成 Excel。")
    records = read_jsonl(records_path)
    failures = read_jsonl(failures_path)
    wb = Workbook()
    ws = wb.active
    ws.title = "ASIN去重总表"
    write_front_sheet(ws, FRONT_DEDUP_HEADERS, build_front_dedup_rows(records))

    ws_fail = wb.create_sheet("失败页面")
    failure_headers = ["time", "source_type", "keyword", "search_sort_order", "store_url", "store_name", "store_sort_order", "category_path", "page_number", "page_url", "reason", "message"]
    write_front_sheet(ws_fail, failure_headers, failures, raw_headers=True)

    ensure_dir(output_xlsx.parent)
    wb.save(output_xlsx)


def run_bsr_category_mode(raw_config: Dict[str, Any], runtime: FrontRuntimeConfig, dry_run: bool, no_resume: bool) -> int:
    category_runtime = build_category_runtime_config(raw_config, DEFAULT_CONFIG, no_resume)
    result = run_category_crawl(category_runtime, dry_run)
    if dry_run:
        return result
    job_dir = category_runtime.outputs_root / category_runtime.job_id
    records_path = job_dir / "records.jsonl"
    failures_path = job_dir / "failures.jsonl"
    output_xlsx = job_dir / "dedup_total.xlsx"
    write_front_workbook(records_path, failures_path, output_xlsx)
    print(f"已生成 ASIN 去重总表：{output_xlsx}")
    return result


def run_front_modes(raw_config: Dict[str, Any], runtime: FrontRuntimeConfig, dry_run: bool) -> int:
    initial_queue = build_initial_queue(runtime)
    job_dir = ensure_dir(runtime.outputs_root / runtime.job_id)
    records_path = job_dir / "records.jsonl"
    failures_path = job_dir / "failures.jsonl"
    state_path = job_dir / "state.json"
    output_xlsx = job_dir / "dedup_total.xlsx"
    debug_dir = job_dir / "debug_snapshots"

    print(f"任务目录：{job_dir}")
    print(f"任务模式：{runtime.mode}")
    print(f"输入数量：{len(initial_queue)}")
    print(f"输出表格：{output_xlsx}")
    if dry_run:
        print("dry-run：配置和输入表检查完成，未打开浏览器。")
        return 0
    if not runtime.resume:
        for old_file in (records_path, failures_path, output_xlsx):
            if old_file.exists():
                old_file.unlink()

    state = FrontStateStore(state_path, runtime, initial_queue)
    state.load_or_create()
    driver = start_driver(runtime)
    batch_pause = BatchPauseScheduler(runtime)  # type: ignore[arg-type]

    def restart_plugin_driver(current_driver: WebDriver, page_url: str, wait_seconds: float) -> WebDriver:
        nonlocal driver
        try:
            current_driver.quit()
        except WebDriverException:
            pass
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        driver = start_driver(runtime)  # type: ignore[arg-type]
        driver.get(page_url)
        try:
            wait_for_amazon_products(driver, runtime)  # type: ignore[arg-type]
        except TimeoutException:
            pass
        return driver

    try:
        while True:
            current = state.next_work()
            if not current:
                print("队列已完成。")
                break
            page_number = int(current.get("page_number") or 1)
            page_url = str(current.get("page_url") or "")
            label = current.get("keyword") or current.get("store_name") or current.get("store_url") or page_url
            print(f"处理：{label} / 第 {page_number} 页")

            try:
                driver.get(page_url)
                if current.get("source_type") == "storefront":
                    prepare_storefront_page(driver, runtime, current)
                    state.set_current(current)
                if not wait_for_page_or_manual_front(driver, runtime, state, failures_path, debug_dir, current):
                    log_front_failure(failures_path, state, current, "no_product_cards", "页面未检测到商品卡片", driver.current_url)
                    state.finish_current_source("page_wait_failed")
                    sleep_between_pages(runtime)
                    continue

                plugin_status = wait_for_sellersprite_data_or_prompt(
                    driver,
                    runtime,  # type: ignore[arg-type]
                    on_manual_pause=lambda reason, url: state.mark_manual_pause(reason, url),
                    on_manual_resume=state.clear_manual_pause,
                    restart_driver=restart_plugin_driver,
                )
                if plugin_status == "blocked":
                    log_front_failure(failures_path, state, current, "verification_timeout", "人工处理超时", driver.current_url)
                    if runtime.save_debug_snapshots:
                        save_debug_snapshot(driver, debug_dir, "verification_timeout")
                    break

                key = front_page_key(current, driver.current_url)
                records: List[Dict[str, Any]] = []
                if state.is_page_completed(key):
                    records = merge_front_product_data(driver, runtime, current, plugin_status)
                    print("当前页已在断点中标记完成，跳过写入。")
                else:
                    records = merge_front_product_data(driver, runtime, current, plugin_status)
                    for record in records:
                        append_jsonl(records_path, record)
                    state.mark_page_completed(key, len(records))
                    print(f"写入商品 {len(records)} 条，插件状态：{plugin_status}")
                    batch_pause.after_completed_page()
                    if plugin_status != "ok" and runtime.save_debug_snapshots:
                        save_debug_snapshot(driver, debug_dir, f"plugin_{plugin_status}_{page_number}")

                update_next_page_or_finish(driver, runtime, state, current, records)
                sleep_between_pages(runtime)
            except TimeoutException as exc:
                log_front_failure(failures_path, state, current, "page_timeout", str(exc), page_url)
                if runtime.save_debug_snapshots:
                    save_debug_snapshot(driver, debug_dir, "page_timeout")
                state.finish_current_source("page_timeout")
            except WebDriverException as exc:
                log_front_failure(failures_path, state, current, "webdriver_error", str(exc)[:500], page_url)
                if runtime.save_debug_snapshots:
                    save_debug_snapshot(driver, debug_dir, "webdriver_error")
                state.finish_current_source("webdriver_error")
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass

    write_front_workbook(records_path, failures_path, output_xlsx)
    print(f"已生成 ASIN 去重总表：{output_xlsx}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified Amazon front crawler with SellerSprite extension data.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只检查配置，不打开浏览器")
    parser.add_argument("--no-resume", action="store_true", help="忽略已有断点，重新开始任务")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = ROOT_DIR / config_path
    raw_config = load_json(config_path)
    runtime = build_front_runtime_config(raw_config, args.no_resume)
    if runtime.mode == "bsr_category":
        return run_bsr_category_mode(raw_config, runtime, args.dry_run, args.no_resume)
    return run_front_modes(raw_config, runtime, args.dry_run)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UserFacingError as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        raise SystemExit(2)
