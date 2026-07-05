#!/usr/bin/env python3
"""
Amazon image-search competitor crawler.

The crawler reads a product list, resolves each row to a main image, searches
Amazon Lens in a visible Chrome session, filters the visual-search candidates
with a vision model, then writes SellerSprite-enriched competitor rows.

It does not solve CAPTCHA or bypass verification. If Amazon or SellerSprite
verification appears, it saves state and waits for manual handling.
"""

from __future__ import annotations

import argparse
import base64
from copy import copy as copy_style
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html as html_lib
import json
import math
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote_plus, urlparse

import requests
from selenium.common.exceptions import JavascriptException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
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
    clean_url,
    config_bool,
    config_float,
    config_int,
    config_text,
    country_from_flag_code_or_text,
    detect_block,
    dump_json,
    ensure_dir,
    extract_by_selectors,
    extract_table_rows,
    load_json,
    normalize_header,
    normalize_space,
    now_iso,
    now_ts,
    parse_field_from_text,
    parse_table_row_fields,
    plugin_node_count,
    preload_page_data_with_scroll,
    read_jsonl,
    resolve_path,
    save_debug_snapshot,
    sleep_between_pages,
    slugify,
    start_driver,
    try_activate_plugin,
    wait_for_manual_clear,
    wait_for_amazon_products,
    wait_for_sellersprite_data,
)
from amazon_front_crawler import pick_column, read_input_rows


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT_DIR / "config" / "amazon_image_competitors.json"
ASIN_RE = re.compile(r"\b([A-Z0-9]{10})\b", re.I)
URL_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?#]|$)", re.I)

MARKETPLACE_DOMAINS = {
    "us": "amazon.com",
    "usa": "amazon.com",
    "美国": "amazon.com",
    "美国站": "amazon.com",
    "amazon.com": "amazon.com",
    "ca": "amazon.ca",
    "加拿大": "amazon.ca",
    "加拿大站": "amazon.ca",
    "amazon.ca": "amazon.ca",
    "mx": "amazon.com.mx",
    "墨西哥": "amazon.com.mx",
    "墨西哥站": "amazon.com.mx",
    "amazon.com.mx": "amazon.com.mx",
    "uk": "amazon.co.uk",
    "gb": "amazon.co.uk",
    "英国": "amazon.co.uk",
    "英国站": "amazon.co.uk",
    "amazon.co.uk": "amazon.co.uk",
    "de": "amazon.de",
    "德国": "amazon.de",
    "德国站": "amazon.de",
    "amazon.de": "amazon.de",
    "fr": "amazon.fr",
    "法国": "amazon.fr",
    "法国站": "amazon.fr",
    "amazon.fr": "amazon.fr",
    "it": "amazon.it",
    "意大利": "amazon.it",
    "意大利站": "amazon.it",
    "amazon.it": "amazon.it",
    "es": "amazon.es",
    "西班牙": "amazon.es",
    "西班牙站": "amazon.es",
    "amazon.es": "amazon.es",
    "jp": "amazon.co.jp",
    "日本": "amazon.co.jp",
    "日本站": "amazon.co.jp",
    "amazon.co.jp": "amazon.co.jp",
    "au": "amazon.com.au",
    "澳洲": "amazon.com.au",
    "澳大利亚": "amazon.com.au",
    "澳洲站": "amazon.com.au",
    "amazon.com.au": "amazon.com.au",
    "in": "amazon.in",
    "印度": "amazon.in",
    "印度站": "amazon.in",
    "amazon.in": "amazon.in",
    "nl": "amazon.nl",
    "荷兰": "amazon.nl",
    "荷兰站": "amazon.nl",
    "amazon.nl": "amazon.nl",
    "se": "amazon.se",
    "瑞典": "amazon.se",
    "瑞典站": "amazon.se",
    "amazon.se": "amazon.se",
    "pl": "amazon.pl",
    "波兰": "amazon.pl",
    "波兰站": "amazon.pl",
    "amazon.pl": "amazon.pl",
    "ae": "amazon.ae",
    "阿联酋": "amazon.ae",
    "阿联酋站": "amazon.ae",
    "amazon.ae": "amazon.ae",
    "sa": "amazon.sa",
    "沙特": "amazon.sa",
    "沙特站": "amazon.sa",
    "amazon.sa": "amazon.sa",
    "sg": "amazon.sg",
    "新加坡": "amazon.sg",
    "新加坡站": "amazon.sg",
    "amazon.sg": "amazon.sg",
    "br": "amazon.com.br",
    "巴西": "amazon.com.br",
    "巴西站": "amazon.com.br",
    "amazon.com.br": "amazon.com.br",
    "za": "amazon.co.za",
    "南非": "amazon.co.za",
    "南非站": "amazon.co.za",
    "amazon.co.za": "amazon.co.za",
}

INPUT_ALIASES = {
    "source_asin": ["asin", "ASIN", "源ASIN", "产品ASIN", "被抓取ASIN", "来源ASIN"],
    "product_url": ["product_url", "商品URL", "产品URL", "链接", "商品链接", "亚马逊链接"],
    "image_url": ["image_url", "主图URL", "图片URL", "主图链接", "图片链接"],
    "image_path": ["image_path", "主图路径", "图片路径", "本地图片", "本地图片路径"],
    "note": ["note", "备注"],
}

IMAGE_COMPETITOR_HEADERS = [
    "来源ASIN",
    "竞品ASIN",
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
    "商品标题",
    "商品URL",
    "来源商品URL",
    "来源主图",
    "同款置信度",
    "同款判断原因",
    "抓取时间",
    "加载状态",
    "备注",
]

IMAGE_COMPETITOR_FIELD_TO_HEADER = {
    "source_asin": "来源ASIN",
    "asin": "竞品ASIN",
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
    "title": "商品标题",
    "product_url": "商品URL",
    "source_product_url": "来源商品URL",
    "source_image": "来源主图",
    "match_confidence": "同款置信度",
    "match_reason": "同款判断原因",
    "scraped_at": "抓取时间",
    "load_status": "加载状态",
    "note": "备注",
}

CANDIDATE_HEADERS = [
    "source_id",
    "source_asin",
    "asin",
    "title",
    "product_url",
    "candidate_image_url",
    "rank",
    "is_competitor",
    "confidence",
    "reason",
    "load_status",
]

COUNT_COLUMN_HEADER = "相似竞品数量"

EMBEDDING_CACHE: Dict[str, List[float]] = {}


@dataclass
class ImageCompetitorRuntimeConfig:
    job_id: str
    outputs_root: Path
    products_file: Path
    marketplace: str
    marketplace_domain: str
    lens_url_template: str
    search_strategy: str
    find_similar_timeout: int
    lens_results_timeout: int
    max_candidates_per_source: int
    max_competitors_per_source: int
    result_mode: str
    min_match_confidence: float
    include_source_as_competitor: bool
    match_mode: str
    vision_model: str
    openai_api_key_env: str
    openai_base_url: str
    openai_api_path: str
    vision_batch_size: int
    vision_timeout: int
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
    sellersprite_on_lens: bool
    enrich_accepted_results: bool
    enrichment_page_timeout: int
    enrichment_plugin_timeout: int
    field_selectors: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def lens_url(self) -> str:
        return self.lens_url_template.format(domain=self.marketplace_domain)

    @property
    def is_count_only(self) -> bool:
        return self.result_mode == "count_only"


class ImageCompetitorStateStore:
    def __init__(self, path: Path, runtime: ImageCompetitorRuntimeConfig, initial_queue: Sequence[Dict[str, Any]]) -> None:
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
            "mode": "image_competitor",
            "created_at": now_iso(),
            "marketplace": self.runtime.marketplace_domain,
            "queue": self.initial_queue,
            "current": None,
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

    def finish_current_source(self, reason: str = "", count: int = 0) -> None:
        current = self.data.get("current")
        if current:
            source_id = str(current.get("source_id") or "")
            done = set(self.data.setdefault("completed_sources", []))
            done.add(source_id)
            self.data["completed_sources"] = sorted(done)
            self.data.setdefault("completed_source_reasons", {})[source_id] = reason
        self.data["records_count"] = int(self.data.get("records_count") or 0) + count
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


def prompt_marketplace() -> str:
    print("请输入 Amazon 站点，例如：美国站、amazon.com、德国站、amazon.de。")
    try:
        return input("站点：").strip()
    except EOFError:
        return ""


def normalize_marketplace(value: str) -> str:
    text = normalize_space(value).lower()
    if text in MARKETPLACE_DOMAINS:
        return MARKETPLACE_DOMAINS[text]
    text = text.removeprefix("https://").removeprefix("http://").strip("/")
    text = text.removeprefix("www.")
    if text in MARKETPLACE_DOMAINS:
        return MARKETPLACE_DOMAINS[text]
    if text.startswith("amazon.") or ".amazon." in text:
        return text
    raise UserFacingError(f"暂不识别的 Amazon 站点：{value}")


def parse_asin(value: str) -> str:
    text = normalize_space(value).upper()
    match = URL_ASIN_RE.search(text)
    if match:
        return match.group(1).upper()
    match = ASIN_RE.search(text)
    return match.group(1).upper() if match else ""


def product_url_for_asin(domain: str, asin: str) -> str:
    return f"https://www.{domain}/dp/{asin}"


def build_image_runtime_config(config: Dict[str, Any], no_resume: bool) -> ImageCompetitorRuntimeConfig:
    marketplace = config_text(config, "marketplace")
    if not marketplace:
        marketplace = prompt_marketplace()
    if not marketplace:
        raise UserFacingError("执行以图搜图抓取前必须输入 Amazon 站点。")
    marketplace_domain = normalize_marketplace(marketplace)

    products_file = resolve_path(config_text(config, "products_file", "inputs/image_competitors.csv"))
    if not products_file.exists():
        raise UserFacingError(f"没有找到产品清单：{products_file}")

    extension_path_text = config_text(config, "extension_path")
    extension_path = resolve_path(extension_path_text) if extension_path_text else Path("")
    browser_mode = config_text(config, "browser_mode", "launch").lower()
    if browser_mode not in {"launch", "attach", "reuse"}:
        raise UserFacingError("以图搜图上传图片需要 Selenium 控制文件上传，browser_mode 只支持 launch、attach 或 reuse。")
    if browser_mode == "launch" and extension_path_text and not extension_path.exists():
        raise UserFacingError(f"没有找到卖家精灵扩展目录：{extension_path}")

    min_delay = config_float(config, "delay_seconds_min", 6)
    max_delay = config_float(config, "delay_seconds_max", 12)
    if max_delay < min_delay:
        max_delay = min_delay
    batch_pages_min = config_int(config, "batch_pause_pages_min", 20) or 0
    batch_pages_max = config_int(config, "batch_pause_pages_max", 36) or 0
    if batch_pages_max and batch_pages_max < batch_pages_min:
        batch_pages_max = batch_pages_min
    batch_seconds_min = config_float(config, "batch_pause_seconds_min", 60)
    batch_seconds_max = config_float(config, "batch_pause_seconds_max", 150)
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

    min_confidence = config_float(config, "min_match_confidence", 0.85)
    if min_confidence < 0 or min_confidence > 1:
        raise UserFacingError("配置项 min_match_confidence 必须在 0-1 之间。")
    result_mode = (config_text(config, "result_mode", "detail").lower() or "detail").replace("-", "_")
    if result_mode not in {"detail", "count_only"}:
        raise UserFacingError("配置项 result_mode 只支持 detail 或 count_only。")
    sellersprite_on_lens = config_bool(config, "sellersprite_on_lens", False)
    enrich_accepted_results = config_bool(config, "enrich_accepted_results", True)
    if result_mode == "count_only":
        sellersprite_on_lens = False
        enrich_accepted_results = False

    return ImageCompetitorRuntimeConfig(
        job_id=slugify(config_text(config, "job_id") or f"amazon-image-competitors-{now_ts()}"),
        outputs_root=resolve_path(config_text(config, "outputs_root", "outputs")),
        products_file=products_file,
        marketplace=marketplace,
        marketplace_domain=marketplace_domain,
        lens_url_template=config_text(config, "lens_url_template", "https://www.{domain}/Lens/b?ie=UTF8&node=206517768011"),
        search_strategy=config_text(config, "search_strategy", "sellersprite_find_similar_first").lower()
        or "sellersprite_find_similar_first",
        find_similar_timeout=config_int(config, "find_similar_timeout", 12) or 12,
        lens_results_timeout=config_int(config, "lens_results_timeout", 60) or 60,
        max_candidates_per_source=config_int(config, "max_candidates_per_source", 24) or 24,
        max_competitors_per_source=config_int(config, "max_competitors_per_source", 12) or 12,
        result_mode=result_mode,
        min_match_confidence=min_confidence,
        include_source_as_competitor=config_bool(config, "include_source_as_competitor", False),
        match_mode=config_text(config, "match_mode", "chat").lower() or "chat",
        vision_model=config_text(config, "vision_model", "gpt-5.4-mini"),
        openai_api_key_env=config_text(config, "openai_api_key_env", "OPENAI_API_KEY") or "OPENAI_API_KEY",
        openai_base_url=config_text(config, "openai_base_url", "https://api.openai.com/v1").rstrip("/"),
        openai_api_path=config_text(config, "openai_api_path", "responses").strip("/"),
        vision_batch_size=config_int(config, "vision_batch_size", 6) or 6,
        vision_timeout=config_int(config, "vision_timeout", 120) or 120,
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
        plugin_relaunch_retry_attempts=max(config_int(config, "plugin_relaunch_retry_attempts", 0) or 0, 0),
        plugin_relaunch_wait_seconds=max(config_float(config, "plugin_relaunch_wait_seconds", 300) or 0, 0),
        plugin_second_relaunch_retry_attempts=max(config_int(config, "plugin_second_relaunch_retry_attempts", 0) or 0, 0),
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
        sellersprite_on_lens=sellersprite_on_lens,
        enrich_accepted_results=enrich_accepted_results,
        enrichment_page_timeout=config_int(config, "enrichment_page_timeout", 25) or 25,
        enrichment_plugin_timeout=config_int(config, "enrichment_plugin_timeout", 20) or 20,
        field_selectors={} if result_mode == "count_only" else field_selectors,
    )


def load_products(path: Path, marketplace_domain: str, dedupe: bool = True) -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []
    seen = set()
    rows = read_input_rows(path)
    for index, row in enumerate(rows, start=2):
        source_asin = parse_asin(pick_column(row, INPUT_ALIASES["source_asin"]))
        product_url = pick_column(row, INPUT_ALIASES["product_url"])
        image_url = pick_column(row, INPUT_ALIASES["image_url"])
        image_path = pick_column(row, INPUT_ALIASES["image_path"])
        note = pick_column(row, INPUT_ALIASES["note"])
        if not source_asin and product_url:
            source_asin = parse_asin(product_url)
        if source_asin and not product_url:
            product_url = product_url_for_asin(marketplace_domain, source_asin)
        base_source_id = source_asin or product_url or image_url or image_path or f"row-{index}"
        source_id = base_source_id if dedupe else f"{base_source_id}#row-{index}"
        if dedupe and source_id in seen:
            continue
        if not any([source_asin, product_url, image_url, image_path]):
            continue
        products.append(
            {
                "source_id": source_id,
                "source_asin": source_asin,
                "source_product_url": product_url,
                "input_image_url": image_url,
                "input_image_path": image_path,
                "input_row": index,
                "input_note": note,
            }
        )
        if dedupe:
            seen.add(source_id)
    if not products:
        raise UserFacingError("产品清单必须至少包含 ASIN、商品URL、主图URL 或本地图片路径中的一列。")
    return products


def log_failure(
    failures_path: Path,
    state: ImageCompetitorStateStore,
    current: Dict[str, Any],
    reason: str,
    message: str,
    page_url: str = "",
) -> None:
    append_jsonl(
        failures_path,
        {
            "time": now_iso(),
            "source_id": current.get("source_id", ""),
            "source_asin": current.get("source_asin", ""),
            "source_product_url": current.get("source_product_url", ""),
            "input_row": current.get("input_row", ""),
            "page_url": page_url,
            "reason": reason,
            "message": message,
        },
    )
    state.log_failure()


def request_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }


def guess_image_suffix(url: str, content_type: str = "") -> str:
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    if guessed and guessed.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if guessed.lower() == ".jpe" else guessed.lower()
    path_suffix = Path(urlparse(url).path).suffix.lower()
    if path_suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return path_suffix
    return ".jpg"


def download_image(url: str, target_dir: Path, stem: str, timeout: int = 45) -> Path:
    ensure_dir(target_dir)
    response = requests.get(url, headers=request_headers(), timeout=timeout)
    response.raise_for_status()
    suffix = guess_image_suffix(url, response.headers.get("content-type", ""))
    path = target_dir / f"{slugify(stem)}{suffix}"
    path.write_bytes(response.content)
    return path


def image_url_to_data_url(url: str, timeout: int = 45) -> str:
    response = requests.get(url, headers=request_headers(), timeout=timeout)
    response.raise_for_status()
    mime = (response.headers.get("content-type") or "image/jpeg").split(";")[0].strip() or "image/jpeg"
    encoded = base64.b64encode(response.content).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def resolve_local_image_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.exists():
        raise UserFacingError(f"没有找到本地图片：{path}")
    return path


def extract_main_image_url(driver: WebDriver) -> str:
    script = r"""
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const absUrl = (url) => {
  try { return new URL(url, location.href).href; } catch (err) { return url || ''; }
};
const usableUrl = (url) => !!url && !/^data:image\//i.test(url) && !/grey-pixel|transparent-pixel/i.test(url);
const pickFromDynamic = (el) => {
  const raw = el.getAttribute('data-a-dynamic-image') || '';
  if (!raw) return '';
  try {
    const data = JSON.parse(raw);
    let best = '';
    let bestArea = 0;
    for (const [url, size] of Object.entries(data)) {
      if (!usableUrl(url)) continue;
      const width = Array.isArray(size) ? Number(size[0] || 0) : 0;
      const height = Array.isArray(size) ? Number(size[1] || 0) : 0;
      const area = width * height;
      if (url && area >= bestArea) {
        best = url;
        bestArea = area;
      }
    }
    return best;
  } catch (err) {
    return '';
  }
};
const selectors = [
  '#landingImage',
  '#imgTagWrapperId img',
  '#main-image',
  '#ebooksImgBlkFront',
  '#imageBlock img',
  'img[data-a-dynamic-image]',
  'img.a-dynamic-image'
];
for (const selector of selectors) {
  const el = document.querySelector(selector);
  if (!el) continue;
  const dynamic = pickFromDynamic(el);
  if (dynamic) return absUrl(dynamic);
  const sources = [
    el.getAttribute('data-old-hires') || '',
    el.currentSrc || '',
    el.src || '',
    el.getAttribute('data-src') || '',
    el.getAttribute('src') || ''
  ];
  for (const src of sources) {
    if (usableUrl(src)) return absUrl(src);
  }
}
const imgs = [...document.querySelectorAll('img')].map(img => ({
  src: img.currentSrc || img.src || img.getAttribute('data-src') || '',
  alt: norm(img.getAttribute('alt') || ''),
  area: (img.naturalWidth || img.width || 0) * (img.naturalHeight || img.height || 0)
})).filter(item => usableUrl(item.src) && item.area > 10000);
imgs.sort((a, b) => b.area - a.area);
return imgs.length ? absUrl(imgs[0].src) : '';
"""
    try:
        return normalize_space(str(driver.execute_script(script) or ""))
    except (JavascriptException, WebDriverException):
        return ""


def resolve_source_image(
    driver: WebDriver,
    runtime: ImageCompetitorRuntimeConfig,
    current: Dict[str, Any],
    image_dir: Path,
) -> Path:
    raw_path = normalize_space(str(current.get("input_image_path") or ""))
    if raw_path:
        path = resolve_local_image_path(raw_path)
        current["source_image"] = str(path)
        return path

    image_url = normalize_space(str(current.get("input_image_url") or ""))
    if not image_url:
        product_url = normalize_space(str(current.get("source_product_url") or ""))
        if not product_url:
            source_asin = normalize_space(str(current.get("source_asin") or ""))
            if source_asin:
                product_url = product_url_for_asin(runtime.marketplace_domain, source_asin)
                current["source_product_url"] = product_url
        if not product_url:
            raise UserFacingError("该行没有可用的图片、ASIN 或商品链接。")
        driver.get(product_url)
        block_reason = detect_block(driver)
        if block_reason:
            raise UserFacingError(f"打开来源商品页时遇到验证：{block_reason}")
        WebDriverWait(driver, runtime.page_timeout).until(lambda d: bool(extract_main_image_url(d)))
        image_url = extract_main_image_url(driver)
        if not image_url:
            raise UserFacingError("商品页没有提取到主图。")
        current["input_image_url"] = image_url

    image_path = download_image(image_url, image_dir, str(current.get("source_id") or "source"))
    current["source_image"] = image_url
    return image_path


def ensure_lens_supported(
    driver: WebDriver,
    runtime: ImageCompetitorRuntimeConfig,
    state: ImageCompetitorStateStore,
    failures_path: Path,
    debug_dir: Path,
) -> None:
    driver.get(runtime.lens_url)
    block_reason = detect_block(driver)
    if block_reason:
        state.mark_manual_pause(block_reason, driver.current_url)
        cleared = wait_for_manual_clear(driver, block_reason, runtime.manual_pause_timeout)
        if cleared:
            state.clear_manual_pause()
        if not cleared:
            if runtime.save_debug_snapshots:
                save_debug_snapshot(driver, debug_dir, f"lens_{block_reason}")
            raise UserFacingError("Amazon Lens 页面验证处理超时。")

    def has_file_input(d: WebDriver) -> bool:
        try:
            return bool(d.execute_script("return !!document.querySelector('input[type=file]');"))
        except (JavascriptException, WebDriverException):
            return False

    try:
        WebDriverWait(driver, min(runtime.page_timeout, 45)).until(has_file_input)
    except TimeoutException as exc:
        if runtime.save_debug_snapshots:
            save_debug_snapshot(driver, debug_dir, f"lens_unsupported_{runtime.marketplace_domain}")
        append_jsonl(
            failures_path,
            {
                "time": now_iso(),
                "source_id": "",
                "source_asin": "",
                "page_url": driver.current_url,
                "reason": "lens_unsupported",
                "message": f"{runtime.marketplace_domain} 当前页面未检测到 Amazon 以图搜图上传入口。",
            },
        )
        raise UserFacingError(
            f"{runtime.marketplace_domain} 当前未检测到 Amazon 以图搜图上传入口，无法执行后续任务。"
        ) from exc


def upload_image_to_lens(driver: WebDriver, runtime: ImageCompetitorRuntimeConfig, image_path: Path) -> None:
    driver.get(runtime.lens_url)
    WebDriverWait(driver, runtime.page_timeout).until(
        lambda d: bool(d.execute_script("return !!document.querySelector('input[type=file]');"))
    )
    script = r"""
const input = document.querySelector('input[type=file]');
if (!input) return false;
input.removeAttribute('hidden');
input.style.display = 'block';
input.style.visibility = 'visible';
input.style.opacity = '1';
input.style.position = 'fixed';
input.style.left = '8px';
input.style.top = '8px';
input.style.zIndex = '2147483647';
return true;
"""
    ok = bool(driver.execute_script(script))
    if not ok:
        raise UserFacingError("Amazon Lens 页面未找到图片上传控件。")
    input_el = driver.find_element(By.CSS_SELECTOR, "input[type=file]")
    input_el.send_keys(str(image_path.resolve()))


def trigger_sellersprite_find_similar(driver: WebDriver, runtime: ImageCompetitorRuntimeConfig, current: Dict[str, Any]) -> bool:
    product_url = normalize_space(str(current.get("source_product_url") or ""))
    source_asin = normalize_space(str(current.get("source_asin") or ""))
    if not product_url and source_asin:
        product_url = product_url_for_asin(runtime.marketplace_domain, source_asin)
        current["source_product_url"] = product_url
    if not product_url:
        return False
    try:
        current_url = normalize_space(str(getattr(driver, "current_url", "") or ""))
        if not (source_asin and source_asin.upper() in current_url.upper()):
            driver.get(product_url)
        WebDriverWait(driver, min(runtime.page_timeout, 45)).until(lambda d: bool(extract_main_image_url(d)))
        script = r"""
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const fireMouse = (el, type) => el && el.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
const image = document.querySelector('#landingImage,#imgTagWrapperId img,#main-image,img[data-a-dynamic-image],img.a-dynamic-image');
if (image) {
  image.scrollIntoView({block: 'center', inline: 'center'});
  fireMouse(image, 'mouseover');
  fireMouse(image, 'mouseenter');
  fireMouse(image, 'mousemove');
}
return true;
"""
        driver.execute_script(script)
        time.sleep(1.5)
        before_handles = set(driver.window_handles)
        clicked = bool(
            driver.execute_script(
                r"""
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const visible = (el) => {
  const r = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
};
const candidates = [...document.querySelectorAll('button,a,div,span')]
  .filter(el => visible(el))
  .map(el => ({el, text: norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '')}))
  .filter(item => /(^|\s)(找相似|Find Similar|Similar)(\s|$)/i.test(item.text) || item.text === '找相似')
  .sort((a, b) => {
    const ar = a.el.getBoundingClientRect();
    const br = b.el.getBoundingClientRect();
    return (ar.width * ar.height) - (br.width * br.height);
  });
if (!candidates.length) return false;
candidates[0].el.click();
return true;
"""
            )
        )
        if not clicked:
            return False
        WebDriverWait(driver, min(runtime.page_timeout, runtime.find_similar_timeout)).until(
            lambda d: switch_to_find_similar_result(d, before_handles)
        )
        return True
    except (JavascriptException, TimeoutException, WebDriverException):
        return False


def switch_to_find_similar_result(driver: WebDriver, before_handles: set[str]) -> bool:
    try:
        handles = set(driver.window_handles)
        new_handles = list(handles - before_handles)
        if new_handles:
            driver.switch_to.window(new_handles[-1])
        url = str(getattr(driver, "current_url", "") or "").lower()
        return (
            "stylesnap" in url
            or "searchtype=flow" in url
            or bool(extract_lens_candidate_cards(driver, include_text=False))
        )
    except (JavascriptException, WebDriverException):
        return False


def run_image_search(
    driver: WebDriver,
    runtime: ImageCompetitorRuntimeConfig,
    current: Dict[str, Any],
    source_image_path: Path,
) -> str:
    if runtime.search_strategy in {"sellersprite_find_similar_first", "find_similar_first"}:
        if trigger_sellersprite_find_similar(driver, runtime, current):
            return "sellersprite_find_similar"
    upload_image_to_lens(driver, runtime, source_image_path)
    return "amazon_upload"


def wait_for_lens_results(driver: WebDriver, runtime: ImageCompetitorRuntimeConfig) -> None:
    def has_results(d: WebDriver) -> bool:
        try:
            cards = extract_lens_candidate_cards(d, include_text=False)
            return len(cards) > 0
        except WebDriverException:
            return False

    WebDriverWait(driver, min(runtime.page_timeout, runtime.lens_results_timeout)).until(has_results)


def wait_for_lens_sellersprite_data(
    driver: WebDriver,
    runtime: ImageCompetitorRuntimeConfig,
    timeout_seconds: Optional[float] = None,
) -> str:
    if runtime.activate_plugin:
        try_activate_plugin(driver)
    preload_page_data_with_scroll(driver, runtime)
    timeout = runtime.plugin_timeout if timeout_seconds is None else max(float(timeout_seconds), 1)
    deadline = time.time() + timeout
    stable_seen = 0
    last_signature = ""
    while time.time() < deadline:
        if detect_block(driver):
            return "blocked"
        cards = extract_lens_candidate_cards(driver, include_text=True)
        table_rows = extract_table_rows(driver)
        parsed_table_rows = 0
        for row in table_rows:
            parsed = parse_table_row_fields(row)
            if sum(1 for value in parsed.values() if value) >= 2:
                parsed_table_rows += 1
        parsed_cards = 0
        for card in cards:
            text = str(card.get("text") or "")
            parsed_count = sum(1 for field_name in REQUESTED_DATA_FIELDS if parse_field_from_text(field_name, text))
            if parsed_count >= 2:
                parsed_cards += 1
        node_count = plugin_node_count(driver)
        signature = f"{node_count}:{len(cards)}:{len(table_rows)}:{parsed_table_rows}:{parsed_cards}"
        if cards and (parsed_table_rows > 0 or parsed_cards > 0 or (node_count > 0 and table_rows)):
            if signature == last_signature:
                stable_seen += 1
            else:
                stable_seen = 0
            if stable_seen >= 1:
                return "ok"
        last_signature = signature
        time.sleep(1)
    return "plugin_timeout"


def strip_html_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style|svg)\b.*?</\1>", " ", value or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return normalize_space(html_lib.unescape(text))


def first_html_attr(block: str, attr_name: str) -> str:
    pattern = rf"""{re.escape(attr_name)}\s*=\s*["']([^"']+)["']"""
    match = re.search(pattern, block, re.I)
    return html_lib.unescape(match.group(1)) if match else ""


def extract_lens_candidate_cards_from_html(page_html: str, include_text: bool = True) -> List[Dict[str, Any]]:
    article_pattern = re.compile(
        r"""<article\b(?=[^>]*\bdata-csa-c-item-type\s*=\s*["']asin["'])(?P<attrs>[^>]*)>(?P<body>.*?)</article>""",
        re.I | re.S,
    )
    cards: List[Dict[str, Any]] = []
    seen_asins = set()
    for match in article_pattern.finditer(page_html or ""):
        attrs = match.group("attrs") or ""
        body = match.group("body") or ""
        raw_item_id = first_html_attr(attrs, "data-csa-c-item-id")
        asin_match = (
            re.search(r"\basin\.([A-Z0-9]{10})\b", raw_item_id, re.I)
            or re.search(r"\b([A-Z0-9]{10})\b", raw_item_id, re.I)
            or re.search(r"\bASIN\s*:?\s*([A-Z0-9]{10})\b", strip_html_text(body), re.I)
        )
        if not asin_match:
            continue
        asin = asin_match.group(1).upper()
        if asin in seen_asins:
            continue
        product_match = re.search(
            rf"""href\s*=\s*["']([^"']*/(?:dp|gp/product)/{re.escape(asin)}[^"']*)["']""",
            body,
            re.I,
        )
        product_url = html_lib.unescape(product_match.group(1)) if product_match else ""
        image_match = re.search(r"""<img\b[^>]*\bsrc\s*=\s*["']([^"']*m\.media-amazon\.com/images/[^"']+)["']""", body, re.I)
        image_url = html_lib.unescape(image_match.group(1)) if image_match else ""
        title_match = re.search(r"""<h5\b[^>]*>(.*?)</h5>""", body, re.I | re.S)
        title = strip_html_text(title_match.group(1)) if title_match else ""
        rank = first_html_attr(attrs, "data-csa-c-posx") or str(len(cards) + 1)
        seen_asins.add(asin)
        cards.append(
            {
                "asin": asin,
                "title": title,
                "product_url": product_url,
                "candidate_image_url": image_url,
                "rank": str(rank),
                "seller_country_flag_code": "",
                "text": strip_html_text(body) if include_text else "",
            }
        )
    return cards


def extract_lens_candidate_cards(driver: WebDriver, include_text: bool = True) -> List[Dict[str, Any]]:
    script = r"""
const includeText = arguments[0];
const asinRe = /\b([A-Z0-9]{10})\b/;
const asinUrlRe = /\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?#]|$)/i;
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const absUrl = (href) => {
  try { return new URL(href, location.href).href; } catch (err) { return href || ''; }
};
const imageFromSrcset = (value) => {
  if (!value) return '';
  const parts = value.split(',').map(part => part.trim()).filter(Boolean);
  let best = '';
  let bestWidth = 0;
  for (const part of parts) {
    const items = part.split(/\s+/);
    const url = items[0] || '';
    const width = Number((items[1] || '').replace(/[^\d.]/g, '')) || 0;
    if (url && width >= bestWidth) {
      best = url;
      bestWidth = width;
    }
  }
  return best;
};
const getAsin = (el) => {
  for (const attr of ['data-asin', 'asin', 'data-csa-c-asin', 'data-csa-c-item-id']) {
    const value = el.getAttribute(attr);
    if (!value) continue;
    const cleaned = value.trim();
    if (/^[A-Z0-9]{10}$/i.test(cleaned)) return cleaned.toUpperCase();
    const attrMatch = cleaned.match(/(?:^|[.:_-])([A-Z0-9]{10})(?:$|[.:_-])/i) || cleaned.match(/\basin\.([A-Z0-9]{10})\b/i);
    if (attrMatch) return attrMatch[1].toUpperCase();
  }
  for (const a of el.querySelectorAll('a[href]')) {
    const match = a.href.match(asinUrlRe);
    if (match) return match[1].toUpperCase();
  }
  const textMatch = norm(el.innerText || el.textContent || '').match(asinRe);
  return textMatch ? textMatch[1].toUpperCase() : '';
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
const getImageUrl = (el) => {
  const imgs = [...el.querySelectorAll('img')];
  let best = '';
  let bestArea = 0;
  for (const img of imgs) {
    const src = img.currentSrc || img.getAttribute('data-old-hires') || img.src || img.getAttribute('data-src') || imageFromSrcset(img.getAttribute('srcset') || '');
    if (!src) continue;
    const area = (img.naturalWidth || img.width || 0) * (img.naturalHeight || img.height || 0);
    if (!best || area >= bestArea) {
      best = src;
      bestArea = area;
    }
  }
  return absUrl(best);
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
const isExcludedContainer = (el) => {
  for (let cur = el; cur && cur !== document.body; cur = cur.parentElement) {
    const id = String(cur.id || '').toLowerCase();
    const cls = String(cur.className || '').toLowerCase();
    if (['nav-belt', 'navbar', 'nav-main', 'navfooter', 'ewc-content', 'nav-flyout-ewc'].includes(id)) return true;
    if (id.includes('ewc') || cls.includes('ewc') || cls.includes('cart')) return true;
  }
  const hrefs = [...el.querySelectorAll('a[href]')].map(a => a.href).join(' ');
  if (/ewc_|\/cart|\/gp\/cart|ref=ewc/i.test(hrefs)) return true;
  return false;
};
const selectors = [
  'article.cellContainer[data-csa-c-item-type="asin"]',
  'article[data-csa-c-item-id*=".asin."]',
  '[data-csa-c-item-id*=".asin."]',
  '#product_grid_container article',
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
    if (isExcludedContainer(el)) continue;
    seenElements.add(el);
    elements.push(el);
  }
}
const seenAsins = new Set();
const cards = [];
for (const el of elements) {
  const asin = getAsin(el);
  if (!asin || seenAsins.has(asin)) continue;
  const productUrl = getUrl(el, asin);
  if (/ewc_|\/cart|\/gp\/cart|ref=ewc/i.test(productUrl)) continue;
  const imageUrl = getImageUrl(el);
  seenAsins.add(asin);
  cards.push({
    asin,
    title: getTitle(el),
    product_url: productUrl,
    candidate_image_url: imageUrl,
    rank: String(cards.length + 1),
    seller_country_flag_code: getSellerCountryFlagCode(el),
    text: includeText ? norm(el.innerText || el.textContent || '') : ''
  });
}
return cards;
"""
    try:
        cards = list(driver.execute_script(script, include_text) or [])
        if cards:
            return cards
    except (JavascriptException, WebDriverException):
        pass
    try:
        return extract_lens_candidate_cards_from_html(str(driver.page_source or ""), include_text=include_text)
    except WebDriverException:
        return []


def collect_lens_candidate_cards(
    driver: WebDriver,
    runtime: ImageCompetitorRuntimeConfig,
    include_text: bool = True,
) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    seen_asins = set()

    def merge(cards: Sequence[Dict[str, Any]]) -> None:
        for card in cards:
            asin = str(card.get("asin") or "").upper()
            if not asin or asin in seen_asins:
                continue
            copied = dict(card)
            copied["asin"] = asin
            copied["rank"] = copied.get("rank") or str(len(collected) + 1)
            collected.append(copied)
            seen_asins.add(asin)

    merge(extract_lens_candidate_cards(driver, include_text=include_text))
    if len(collected) >= runtime.max_candidates_per_source:
        return collected[: runtime.max_candidates_per_source]

    stable_rounds = 0
    scroll_attempts = min(8, max(2, math.ceil(runtime.max_candidates_per_source / 12)))
    for _ in range(scroll_attempts):
        previous_count = len(collected)
        try:
            driver.execute_script(
                r"""
const scrollables = [document.scrollingElement, document.documentElement, document.body]
  .filter(Boolean);
for (const el of scrollables) {
  try { el.scrollBy(0, Math.max(600, window.innerHeight * 0.85)); } catch (err) {}
}
const grids = [
  '#product_grid_container',
  '[data-testid*="grid"]',
  '[class*="ProductGrid"]',
  '[class*="product-grid"]'
].flatMap(selector => [...document.querySelectorAll(selector)]);
for (const grid of grids) {
  try { grid.scrollBy(0, Math.max(600, window.innerHeight * 0.85)); } catch (err) {}
}
"""
            )
        except (JavascriptException, WebDriverException):
            break
        time.sleep(0.8)
        merge(extract_lens_candidate_cards(driver, include_text=include_text))
        if len(collected) >= runtime.max_candidates_per_source:
            break
        stable_rounds = stable_rounds + 1 if len(collected) == previous_count else 0
        if stable_rounds >= 2:
            break
    return collected[: runtime.max_candidates_per_source]


def merge_lens_product_data(
    driver: WebDriver,
    runtime: ImageCompetitorRuntimeConfig,
    current: Dict[str, Any],
    plugin_status: str,
) -> List[Dict[str, Any]]:
    include_plugin_data = not runtime.is_count_only
    cards = collect_lens_candidate_cards(driver, runtime, include_text=include_plugin_data)
    table_rows = extract_table_rows(driver) if include_plugin_data else []
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
    for card in cards[: runtime.max_candidates_per_source]:
        asin = str(card.get("asin") or "")
        if not asin:
            continue
        record: Dict[str, Any] = {
            "source_type": "image_search",
            "source_id": current.get("source_id", ""),
            "source_asin": current.get("source_asin", ""),
            "source_product_url": current.get("source_product_url", ""),
            "source_image": current.get("source_image") or current.get("input_image_url") or current.get("input_image_path") or "",
            "input_row": current.get("input_row", ""),
            "asin": asin,
            "title": card.get("title") or "",
            "product_url": card.get("product_url") or "",
            "candidate_image_url": card.get("candidate_image_url") or "",
            "rank": card.get("rank") or "",
            "scraped_at": now_iso(),
            "load_status": plugin_status,
            "note": "",
        }
        text = str(card.get("text") or "")
        for field_name in REQUESTED_DATA_FIELDS:
            record[field_name] = ""
        if include_plugin_data:
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


def image_to_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def image_ref_to_embedding_input(image_ref: str) -> Dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": image_ref}}


def call_multimodal_embedding(runtime: ImageCompetitorRuntimeConfig, image_ref: str) -> List[float]:
    api_key = os.environ.get(runtime.openai_api_key_env)
    if not api_key:
        raise UserFacingError(f"缺少视觉模型 API Key，请先设置环境变量 {runtime.openai_api_key_env}。")
    payload = {
        "model": runtime.vision_model,
        "input": [image_ref_to_embedding_input(image_ref)],
        "encoding_format": "float",
    }
    response = requests.post(
        f"{runtime.openai_base_url}/{runtime.openai_api_path}",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=runtime.vision_timeout,
    )
    if response.status_code >= 400:
        raise UserFacingError(f"多模态向量模型调用失败：HTTP {response.status_code} {response.text[:500]}")
    data = response.json()
    items = data.get("data") or []
    if isinstance(items, dict):
        item = items
    elif isinstance(items, list) and items and isinstance(items[0], dict):
        item = items[0]
    else:
        raise UserFacingError(f"多模态向量模型返回格式异常：{str(data)[:500]}")
    embedding = item.get("embedding")
    if not isinstance(embedding, list):
        raise UserFacingError(f"多模态向量模型未返回 embedding：{str(data)[:500]}")
    return [float(value) for value in embedding]


def call_multimodal_embedding_cached(runtime: ImageCompetitorRuntimeConfig, image_ref: str) -> List[float]:
    digest = hashlib.sha256(image_ref.encode("utf-8", errors="ignore")).hexdigest()
    cache_key = f"{runtime.openai_base_url}|{runtime.vision_model}|{digest}"
    cached = EMBEDDING_CACHE.get(cache_key)
    if cached is not None:
        return cached
    embedding = call_multimodal_embedding(runtime, image_ref)
    EMBEDDING_CACHE[cache_key] = embedding
    return embedding


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if not norm_left or not norm_right:
        return 0.0
    return dot / (norm_left * norm_right)


def extract_response_text(data: Dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = (choices[0] or {}).get("message") if isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts)
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts: List[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
            output_text = content.get("output_text")
            if isinstance(output_text, str):
                parts.append(output_text)
    return "\n".join(parts)


def parse_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def build_match_prompt(min_confidence: float, candidates: Sequence[Dict[str, Any]]) -> str:
    candidate_lines = []
    for index, candidate in enumerate(candidates, start=1):
        candidate_lines.append(
            f"{index}. ASIN={candidate.get('asin','')} title={candidate.get('title','')} rank={candidate.get('rank','')}"
        )
    return (
        "你是电商同款竞品视觉审核员。基准图片是来源商品，后面每张候选图片是亚马逊以图搜图结果。\n"
        "核心任务：判断候选图片里的“商品主体”是否和基准图片里的商品主体属于同款/可替代竞品。\n\n"
        "必须遵守的判断规则：\n"
        "1. 只看商品本体，不看整张图片构图、背景、白底、堆叠方式、上方单品+下方集合的版式、光影风格、拍摄角度或模特姿势。\n"
        "2. 先判断硬性门槛：商品类型、用途、核心结构必须一致。只是主题相近、节日氛围相近、构图相近，不能判为同款。\n"
        "3. 重点比较主体细节：形状比例、轮廓、表面纹理/分瓣/凹槽、顶部五金/挂绳/挂环、材质质感、颜色组合、套装构成。\n"
        "4. 允许差异：品牌不同、卖家不同、颜色数量略有不同、展示数量不同、套装/售卖个数不同、配件数量不同、主图排列方式不同。\n"
        "5. 如果候选只是图片排版或构图更像基准图，但商品细节明显不同，必须降低置信度。\n"
        "6. 如果候选构图不一样，但商品本体的核心形态、材质、颜色组合、五金/配件结构高度一致，应该给更高置信度。\n\n"
        "置信度标尺：\n"
        "- 0.90-1.00：几乎同款，商品本体细节高度一致。\n"
        "- 0.80-0.89：高置信同款，只有数量、颜色展示、角度、配件数量等轻微差异。\n"
        "- 0.65-0.79：疑似同款/强竞品，主体一致但关键细节有一些差异。\n"
        "- 0.40-0.64：同类但不同款，不能保留为同款竞品。\n"
        "- 0.00-0.39：明显不同商品。\n\n"
        f"只有 confidence >= {min_confidence:.2f} 且商品主体确实一致时，is_competitor 才能为 true。\n"
        "请只返回 JSON，不要输出解释性正文。格式："
        "{\"matches\":[{\"asin\":\"...\",\"is_competitor\":true,\"confidence\":0.0,"
        "\"reason\":\"简短说明主体商品为何同款或不同款\","
        "\"matched_features\":[\"匹配细节\"],\"different_features\":[\"差异细节\"],"
        "\"composition_similarity_ignored\":true}]}。\n"
        "候选列表：\n"
        + "\n".join(candidate_lines)
    )


def call_openai_vision(
    runtime: ImageCompetitorRuntimeConfig,
    source_image_path: Path,
    candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    api_key = os.environ.get(runtime.openai_api_key_env)
    if not api_key:
        raise UserFacingError(f"缺少视觉模型 API Key，请先设置环境变量 {runtime.openai_api_key_env}。")

    content: List[Dict[str, Any]] = [
        {"type": "input_text", "text": build_match_prompt(runtime.min_match_confidence, candidates)},
        {"type": "input_text", "text": "基准图片："},
        {"type": "input_image", "image_url": image_to_data_url(source_image_path)},
    ]
    for index, candidate in enumerate(candidates, start=1):
        image_url = normalize_space(str(candidate.get("candidate_image_url") or ""))
        if not image_url:
            continue
        content.append({"type": "input_text", "text": f"候选 {index} / ASIN {candidate.get('asin','')}："})
        content.append({"type": "input_image", "image_url": image_url})

    if runtime.openai_api_path.endswith("chat/completions"):
        chat_content: List[Dict[str, Any]] = []
        for item in content:
            if item.get("type") == "input_text":
                chat_content.append({"type": "text", "text": item.get("text", "")})
            elif item.get("type") == "input_image":
                chat_content.append({"type": "image_url", "image_url": {"url": item.get("image_url", "")}})
        payload = {
            "model": runtime.vision_model,
            "messages": [{"role": "user", "content": chat_content}],
            "max_tokens": 1800,
            "temperature": 0,
        }
    else:
        payload = {
            "model": runtime.vision_model,
            "input": [{"role": "user", "content": content}],
            "max_output_tokens": 1800,
            "temperature": 0,
        }
    response = requests.post(
        f"{runtime.openai_base_url}/{runtime.openai_api_path}",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=runtime.vision_timeout,
    )
    if response.status_code >= 400:
        raise UserFacingError(f"视觉模型调用失败：HTTP {response.status_code} {response.text[:500]}")
    data = response.json()
    text = extract_response_text(data)
    try:
        parsed = parse_json_object(text)
    except json.JSONDecodeError as exc:
        raise UserFacingError(f"视觉模型返回内容不是有效 JSON：{text[:500]}") from exc
    matches = parsed.get("matches") if isinstance(parsed, dict) else []
    return [dict(item) for item in matches if isinstance(item, dict)]


def filter_high_confidence_competitors(
    runtime: ImageCompetitorRuntimeConfig,
    source_image_path: Path,
    source_image_ref: str,
    records: Sequence[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    output: List[Dict[str, Any]] = []
    decisions: Dict[str, Dict[str, Any]] = {}
    source_asin = ""
    for record in records:
        source_asin = str(record.get("source_asin") or "").upper()
        if source_asin:
            break

    by_asin: Dict[str, Dict[str, Any]] = {}
    candidates: List[Dict[str, Any]] = []
    for record in records:
        asin = str(record.get("asin") or "").upper()
        if not asin:
            continue
        copied = dict(record)
        copied["asin"] = asin
        by_asin[asin] = copied
        if source_asin and asin == source_asin and not runtime.include_source_as_competitor:
            decisions[asin] = {
                "is_competitor": False,
                "match_confidence": "",
                "match_reason": "候选 ASIN 与来源 ASIN 相同，已按配置排除。",
            }
            continue
        if not copied.get("candidate_image_url"):
            decisions[asin] = {
                "is_competitor": False,
                "match_confidence": "",
                "match_reason": "候选商品缺少可识别图片。",
            }
            continue
        candidates.append(copied)

    def rank_value(item: Dict[str, Any]) -> int:
        match = re.match(r"\d+", str(item.get("rank") or ""))
        return int(match.group(0)) if match else 9999

    if runtime.match_mode == "embedding":
        source_refs = [image_to_data_url(source_image_path)]
        if source_image_ref and source_image_ref not in source_refs:
            source_refs.append(source_image_ref)
        source_embedding: Optional[List[float]] = None
        source_errors: List[str] = []
        for source_ref in source_refs:
            try:
                source_embedding = call_multimodal_embedding_cached(runtime, source_ref)
                break
            except UserFacingError as exc:
                source_errors.append(str(exc)[:240])
        if source_embedding is None:
            raise UserFacingError("来源图片向量识别失败：" + " | ".join(source_errors))

        def embed_candidate(candidate: Dict[str, Any]) -> tuple[str, Optional[List[float]], str]:
            asin = str(candidate.get("asin") or "").upper()
            image_url = normalize_space(str(candidate.get("candidate_image_url") or ""))
            if not asin or not image_url:
                return asin, None, "候选商品缺少可识别图片。"
            try:
                return asin, call_multimodal_embedding_cached(runtime, image_url), ""
            except UserFacingError as exc:
                first_error = str(exc)[:180]
            try:
                data_url = image_url_to_data_url(image_url, timeout=min(runtime.vision_timeout, 45))
                return asin, call_multimodal_embedding_cached(runtime, data_url), "候选图片 URL 识别失败后已改用本地转码图片。"
            except (UserFacingError, requests.RequestException) as exc:
                return asin, None, f"候选图片识别失败：{first_error}；本地转码重试失败：{str(exc)[:180]}"

        max_workers = min(max(runtime.vision_batch_size, 1), 4, max(len(candidates), 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(embed_candidate, candidate) for candidate in candidates]
            for future in as_completed(futures):
                asin, candidate_embedding, note = future.result()
                if not asin or asin not in by_asin:
                    continue
                candidate = by_asin[asin]
                if candidate_embedding is None:
                    candidate["is_competitor"] = False
                    candidate["match_confidence"] = ""
                    candidate["match_reason"] = note
                    decisions[asin] = {
                        "is_competitor": False,
                        "match_confidence": "",
                        "match_reason": note,
                    }
                    continue
                confidence = cosine_similarity(source_embedding, candidate_embedding)
                is_competitor = confidence >= runtime.min_match_confidence
                candidate["is_competitor"] = is_competitor
                candidate["match_confidence"] = round(confidence, 4)
                candidate["match_reason"] = (
                    f"多模态图片向量相似度 {confidence:.4f}，阈值 {runtime.min_match_confidence:.2f}。"
                )
                if note:
                    candidate["match_reason"] = f"{candidate['match_reason']} {note}"
                decisions[asin] = {
                    "is_competitor": is_competitor,
                    "match_confidence": candidate["match_confidence"],
                    "match_reason": candidate["match_reason"],
                }
                if is_competitor:
                    output.append(candidate)
        output.sort(key=lambda item: (-float(item.get("match_confidence") or 0), rank_value(item)))
        if runtime.is_count_only:
            return output, decisions
        return output[: runtime.max_competitors_per_source], decisions

    batch_size = max(runtime.vision_batch_size, 1)
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        matches = call_openai_vision(runtime, source_image_path, batch)
        for match in matches:
            asin = str(match.get("asin") or "").upper()
            if not asin or asin not in by_asin:
                continue
            try:
                confidence = float(match.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            is_competitor = bool(match.get("is_competitor"))
            candidate = by_asin[asin]
            candidate["is_competitor"] = is_competitor
            candidate["match_confidence"] = confidence
            candidate["match_reason"] = normalize_space(str(match.get("reason") or ""))
            decisions[asin] = {
                "is_competitor": is_competitor,
                "match_confidence": confidence,
                "match_reason": candidate["match_reason"],
            }
            if is_competitor and confidence >= runtime.min_match_confidence:
                output.append(candidate)
    output.sort(key=lambda item: (-float(item.get("match_confidence") or 0), rank_value(item)))
    if runtime.is_count_only:
        return output, decisions
    return output[: runtime.max_competitors_per_source], decisions


def amazon_search_url_for_asin(domain: str, asin: str) -> str:
    return f"https://www.{domain}/s?k={quote_plus(asin)}"


def enrich_accepted_records(
    driver: WebDriver,
    runtime: ImageCompetitorRuntimeConfig,
    records: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not runtime.enrich_accepted_results or not records:
        return [dict(record) for record in records]

    enriched_records = [dict(record) for record in records]
    old_page_timeout = runtime.page_timeout
    old_plugin_timeout = runtime.plugin_timeout
    runtime.page_timeout = min(runtime.page_timeout, runtime.enrichment_page_timeout)
    runtime.plugin_timeout = runtime.enrichment_plugin_timeout
    try:
        for record in enriched_records:
            asin = str(record.get("asin") or "").upper()
            if not asin:
                continue
            driver.get(amazon_search_url_for_asin(runtime.marketplace_domain, asin))
            block_reason = detect_block(driver)
            if block_reason:
                record["load_status"] = "blocked"
                record["note"] = f"补抓卖家精灵数据时遇到验证：{block_reason}"
                break
            try:
                wait_for_amazon_products(driver, runtime)  # type: ignore[arg-type]
            except TimeoutException:
                pass
            plugin_status = wait_for_sellersprite_data(driver, runtime)  # type: ignore[arg-type]
            if plugin_status == "blocked":
                record["load_status"] = "blocked"
                record["note"] = "补抓卖家精灵数据时遇到验证。"
                break
            source_context = {
                "source_id": record.get("source_id", ""),
                "source_asin": record.get("source_asin", ""),
                "source_product_url": record.get("source_product_url", ""),
                "source_image": record.get("source_image", ""),
                "input_row": record.get("input_row", ""),
            }
            page_records = merge_lens_product_data(driver, runtime, source_context, plugin_status)
            match = next((item for item in page_records if str(item.get("asin") or "").upper() == asin), None)
            if not match:
                record["load_status"] = f"enrich_{plugin_status}_not_found"
                if not record.get("note"):
                    record["note"] = "补抓页未定位到该 ASIN，保留以图搜图候选信息。"
                continue
            for field_name in REQUESTED_DATA_FIELDS:
                if match.get(field_name):
                    record[field_name] = match[field_name]
            for field_name in ("title", "product_url", "candidate_image_url"):
                if match.get(field_name):
                    record[field_name] = match[field_name]
            record["load_status"] = plugin_status
            missing_count = sum(1 for field_name in REQUESTED_DATA_FIELDS if not record.get(field_name))
            if plugin_status == "ok" and missing_count < len(REQUESTED_DATA_FIELDS):
                if record.get("note") == "插件数据加载超时，已保存页面可见数据":
                    record["note"] = ""
            elif not record.get("note"):
                record["note"] = "补抓页未完整展示卖家精灵字段。"
    finally:
        runtime.page_timeout = old_page_timeout
        runtime.plugin_timeout = old_plugin_timeout
    return enriched_records


def build_candidate_audit_rows(
    records: Sequence[Dict[str, Any]],
    accepted: Sequence[Dict[str, Any]],
    decisions: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    accepted_by_asin = {str(row.get("asin") or ""): row for row in accepted}
    rows: List[Dict[str, Any]] = []
    for record in records:
        asin = str(record.get("asin") or "")
        accepted_row = accepted_by_asin.get(asin)
        decision = decisions.get(asin, {})
        rows.append(
            {
                "source_id": record.get("source_id", ""),
                "source_asin": record.get("source_asin", ""),
                "asin": asin,
                "title": record.get("title", ""),
                "product_url": record.get("product_url", ""),
                "candidate_image_url": record.get("candidate_image_url", ""),
                "rank": record.get("rank", ""),
                "is_competitor": decision.get("is_competitor", accepted_row.get("is_competitor", False) if accepted_row else False),
                "confidence": decision.get("match_confidence", accepted_row.get("match_confidence", "") if accepted_row else ""),
                "reason": decision.get("match_reason", accepted_row.get("match_reason", "") if accepted_row else ""),
                "load_status": record.get("load_status", ""),
            }
        )
    return rows


def write_sheet(ws: Any, headers: Sequence[str], rows: Sequence[Dict[str, Any]], field_to_header: Optional[Dict[str, str]] = None) -> None:
    ws.append(list(headers))
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
    for row in rows:
        if field_to_header:
            ws.append([row.get(field, "") for field, header in field_to_header.items() if header in headers])
        else:
            ws.append([row.get(header, "") for header in headers])
    for column_index, header in enumerate(headers, start=1):
        width = min(max(len(str(header)) + 2, 12), 42)
        ws.column_dimensions[get_column_letter(column_index)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def replace_sheet(wb: Any, title: str) -> Any:
    if title in wb.sheetnames:
        wb.remove(wb[title])
    return wb.create_sheet(title)


def write_workbook(
    source_workbook_path: Path,
    records_path: Path,
    candidates_path: Path,
    failures_path: Path,
    output_xlsx: Path,
) -> None:
    if load_workbook is None:
        raise UserFacingError("缺少 openpyxl，无法生成 Excel。")
    records = read_jsonl(records_path)
    candidates = read_jsonl(candidates_path)
    failures = read_jsonl(failures_path)

    wb = load_workbook(source_workbook_path)
    ws = replace_sheet(wb, "同款竞品结果")
    write_sheet(ws, IMAGE_COMPETITOR_HEADERS, records, IMAGE_COMPETITOR_FIELD_TO_HEADER)

    ws_candidates = replace_sheet(wb, "全部候选")
    write_sheet(ws_candidates, CANDIDATE_HEADERS, candidates)

    ws_fail = replace_sheet(wb, "失败记录")
    failure_headers = ["time", "source_id", "source_asin", "source_product_url", "input_row", "page_url", "reason", "message"]
    write_sheet(ws_fail, failure_headers, failures)

    ensure_dir(output_xlsx.parent)
    wb.save(output_xlsx)


def count_display_value(runtime: ImageCompetitorRuntimeConfig, accepted_count: int) -> int | str:
    if accepted_count >= runtime.max_candidates_per_source:
        return f"{runtime.max_candidates_per_source}+"
    return accepted_count


def append_count_result(
    counts_path: Path,
    runtime: ImageCompetitorRuntimeConfig,
    current: Dict[str, Any],
    search_method: str,
    plugin_status: str,
    candidate_count: int,
    accepted_count: int,
) -> None:
    append_jsonl(
        counts_path,
        {
            "time": now_iso(),
            "source_id": current.get("source_id", ""),
            "source_asin": current.get("source_asin", ""),
            "source_product_url": current.get("source_product_url", ""),
            "input_row": current.get("input_row", ""),
            "search_method": search_method,
            "plugin_status": plugin_status,
            "candidate_count": candidate_count,
            "similar_count": accepted_count,
            "count_display": count_display_value(runtime, accepted_count),
            "max_candidates_per_source": runtime.max_candidates_per_source,
        },
    )


def load_count_results(counts_path: Path) -> Dict[int, Dict[str, Any]]:
    results: Dict[int, Dict[str, Any]] = {}
    for row in read_jsonl(counts_path):
        try:
            input_row = int(row.get("input_row") or 0)
        except (TypeError, ValueError):
            continue
        if input_row >= 2:
            results[input_row] = row
    return results


def copy_header_style(ws: Any, source_col: int, target_col: int) -> None:
    if source_col < 1 or target_col < 1:
        return
    source = ws.cell(row=1, column=source_col)
    target = ws.cell(row=1, column=target_col)
    if source.has_style:
        target._style = copy_style(source._style)
    if source.number_format:
        target.number_format = source.number_format
    if source.alignment:
        target.alignment = copy_style(source.alignment)
    if source.fill:
        target.fill = copy_style(source.fill)
    if source.font:
        target.font = copy_style(source.font)


def write_count_only_workbook(
    source_workbook_path: Path,
    counts_path: Path,
    output_xlsx: Path,
) -> None:
    if load_workbook is None or Workbook is None:
        raise UserFacingError("缺少 openpyxl，无法生成 Excel。")
    count_results = load_count_results(counts_path)

    if source_workbook_path.suffix.lower() in {".xlsx", ".xlsm"}:
        wb = load_workbook(source_workbook_path)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        rows = read_input_rows(source_workbook_path)
        headers = list(rows[0].keys()) if rows else []
        ws.append(headers)
        for row in rows:
            ws.append([row.get(header, "") for header in headers])

    header_row = 1
    count_col = 0
    for column_index in range(1, ws.max_column + 1):
        header = normalize_space(str(ws.cell(row=header_row, column=column_index).value or ""))
        if header == COUNT_COLUMN_HEADER:
            count_col = column_index
            break
    if count_col == 0:
        count_col = ws.max_column + 1
        if count_col > 1:
            copy_header_style(ws, count_col - 1, count_col)
        ws.cell(row=header_row, column=count_col).value = COUNT_COLUMN_HEADER

    for row_index, result in count_results.items():
        value = result.get("count_display")
        if value is None or value == "":
            value = result.get("similar_count", "")
        ws.cell(row=row_index, column=count_col).value = value

    ws.column_dimensions[get_column_letter(count_col)].width = max(
        ws.column_dimensions[get_column_letter(count_col)].width or 0,
        len(COUNT_COLUMN_HEADER) + 4,
    )
    ensure_dir(output_xlsx.parent)
    wb.save(output_xlsx)


def run_image_competitor_crawl(runtime: ImageCompetitorRuntimeConfig, dry_run: bool) -> int:
    initial_queue = load_products(runtime.products_file, runtime.marketplace_domain, dedupe=not runtime.is_count_only)
    job_dir = ensure_dir(runtime.outputs_root / runtime.job_id)
    records_path = job_dir / "records.jsonl"
    candidates_path = job_dir / "candidates.jsonl"
    failures_path = job_dir / "failures.jsonl"
    counts_path = job_dir / "counts.jsonl"
    state_path = job_dir / "state.json"
    output_suffix = "相似竞品数量" if runtime.is_count_only else "同款竞品结果"
    output_xlsx = job_dir / f"{runtime.products_file.stem}_{output_suffix}.xlsx"
    debug_dir = job_dir / "debug_snapshots"
    image_dir = ensure_dir(job_dir / "source_images")

    print(f"任务目录：{job_dir}")
    print(f"任务模式：image_competitor/{runtime.result_mode}")
    print(f"Amazon 站点：{runtime.marketplace_domain}")
    print(f"输入数量：{len(initial_queue)}")
    print(f"输出表格：{output_xlsx}")
    if dry_run:
        print("dry-run：配置和输入表检查完成，未打开浏览器。")
        return 0
    if not os.environ.get(runtime.openai_api_key_env):
        raise UserFacingError(
            f"缺少外部图片识别 API Key 环境变量：{runtime.openai_api_key_env}。"
            "请先配置该环境变量，或在配置文件中把 openai_api_key_env 改成实际使用的变量名。"
        )

    if not runtime.resume:
        for old_file in (records_path, candidates_path, failures_path, counts_path, output_xlsx):
            if old_file.exists():
                old_file.unlink()

    state = ImageCompetitorStateStore(state_path, runtime, initial_queue)
    state.load_or_create()
    driver = start_driver(runtime)
    batch_pause = BatchPauseScheduler(runtime)  # type: ignore[arg-type]
    try:
        if runtime.search_strategy not in {"sellersprite_find_similar_first", "find_similar_first"}:
            ensure_lens_supported(driver, runtime, state, failures_path, debug_dir)
        while True:
            current = state.next_work()
            if not current:
                print("队列已完成。")
                break
            label = current.get("source_asin") or current.get("source_product_url") or current.get("source_id")
            print(f"处理：{label}")
            try:
                source_image_path = resolve_source_image(driver, runtime, current, image_dir)
                state.set_current(current)

                search_method = run_image_search(driver, runtime, current, source_image_path)
                current["image_search_method"] = search_method
                block_reason = detect_block(driver)
                if block_reason:
                    state.mark_manual_pause(block_reason, driver.current_url)
                    cleared = wait_for_manual_clear(driver, block_reason, runtime.manual_pause_timeout)
                    if cleared:
                        state.clear_manual_pause()
                    if not cleared:
                        log_failure(failures_path, state, current, block_reason, "人工处理超时", driver.current_url)
                        if runtime.save_debug_snapshots:
                            save_debug_snapshot(driver, debug_dir, block_reason)
                        break

                try:
                    wait_for_lens_results(driver, runtime)
                except TimeoutException:
                    if search_method == "sellersprite_find_similar":
                        upload_image_to_lens(driver, runtime, source_image_path)
                        search_method = "amazon_upload_after_find_similar_timeout"
                        block_reason = detect_block(driver)
                        if block_reason:
                            state.mark_manual_pause(block_reason, driver.current_url)
                            cleared = wait_for_manual_clear(driver, block_reason, runtime.manual_pause_timeout)
                            if cleared:
                                state.clear_manual_pause()
                            if not cleared:
                                log_failure(failures_path, state, current, block_reason, "人工处理超时", driver.current_url)
                                if runtime.save_debug_snapshots:
                                    save_debug_snapshot(driver, debug_dir, block_reason)
                                break
                        wait_for_lens_results(driver, runtime)
                    else:
                        raise
                if runtime.sellersprite_on_lens:
                    plugin_status = wait_for_lens_sellersprite_data(driver, runtime)
                    if plugin_status == "blocked":
                        log_failure(failures_path, state, current, "verification_timeout", "人工处理超时", driver.current_url)
                        if runtime.save_debug_snapshots:
                            save_debug_snapshot(driver, debug_dir, "verification_timeout")
                        break
                else:
                    plugin_status = "skipped_on_lens"

                candidate_records = merge_lens_product_data(driver, runtime, current, plugin_status)
                accepted_records, decisions = filter_high_confidence_competitors(
                    runtime,
                    source_image_path,
                    normalize_space(str(current.get("source_image") or current.get("input_image_url") or "")),
                    candidate_records,
                )
                needs_enrichment = runtime.enrich_accepted_results and accepted_records and (
                    plugin_status != "ok"
                    or any(
                        sum(1 for field_name in REQUESTED_DATA_FIELDS if row.get(field_name))
                        < max(3, len(REQUESTED_DATA_FIELDS) // 3)
                        for row in accepted_records
                    )
                )
                if needs_enrichment:
                    accepted_records = enrich_accepted_records(driver, runtime, accepted_records)
                candidate_audit_rows = build_candidate_audit_rows(candidate_records, accepted_records, decisions)

                for row in candidate_audit_rows:
                    append_jsonl(candidates_path, row)
                for row in accepted_records:
                    append_jsonl(records_path, row)
                if runtime.is_count_only:
                    append_count_result(
                        counts_path,
                        runtime,
                        current,
                        search_method,
                        plugin_status,
                        len(candidate_records),
                        len(accepted_records),
                    )
                state.finish_current_source("ok", count=len(accepted_records))
                print(
                    f"搜索方式：{search_method}；候选 {len(candidate_records)} 条，"
                    f"相似竞品 {count_display_value(runtime, len(accepted_records))} 条，插件状态：{plugin_status}"
                )
                batch_pause.after_completed_page()
                sleep_between_pages(runtime)
            except (TimeoutException, requests.RequestException) as exc:
                log_failure(failures_path, state, current, "runtime_error", str(exc)[:500], getattr(driver, "current_url", ""))
                if runtime.save_debug_snapshots:
                    save_debug_snapshot(driver, debug_dir, "runtime_error")
                state.finish_current_source("runtime_error")
            except (UserFacingError, WebDriverException) as exc:
                log_failure(failures_path, state, current, "crawler_error", str(exc)[:500], getattr(driver, "current_url", ""))
                if runtime.save_debug_snapshots:
                    save_debug_snapshot(driver, debug_dir, "crawler_error")
                state.finish_current_source("crawler_error")
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass

    if runtime.is_count_only:
        write_count_only_workbook(runtime.products_file, counts_path, output_xlsx)
        print(f"已生成相似竞品数量表：{output_xlsx}")
    else:
        write_workbook(runtime.products_file, records_path, candidates_path, failures_path, output_xlsx)
        print(f"已生成以图搜图竞品表：{output_xlsx}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Amazon image-search competitor crawler with SellerSprite data.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只检查配置，不打开浏览器")
    parser.add_argument("--no-resume", action="store_true", help="忽略已有断点，重新开始任务")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = ROOT_DIR / config_path
    raw_config = load_json(config_path)
    runtime = build_image_runtime_config(raw_config, args.no_resume)
    return run_image_competitor_crawl(runtime, args.dry_run)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UserFacingError as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        raise SystemExit(2)
