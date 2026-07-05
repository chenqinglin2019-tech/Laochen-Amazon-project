#!/usr/bin/env python3
"""
Amazon category ranking crawler that reads SellerSprite extension data from a
visible Chrome session.

The crawler intentionally does not solve CAPTCHA or bypass verification. When
Amazon or SellerSprite verification appears, it saves a checkpoint and waits for
manual handling in the visible browser.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import select
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse
from urllib.request import urlopen

from selenium import webdriver
from selenium.common.exceptions import (
    JavascriptException,
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    Workbook = None


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT_DIR / "config" / "category_rank_crawler.json"
SELLERSPRITE_EXTENSION_ID = "lnbmbgocenenhhhdojdielgnmeflbnfb"
ASIN_RE = re.compile(r"\b([A-Z0-9]{10})\b")
URL_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?#]|$)", re.I)


OUTPUT_HEADERS = [
    "根类目URL",
    "类目路径",
    "类目名称",
    "类目节点ID",
    "类目URL",
    "页码",
    "排名",
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

FIELD_TO_HEADER = {
    "root_url": "根类目URL",
    "category_path": "类目路径",
    "category_name": "类目名称",
    "category_node_id": "类目节点ID",
    "category_url": "类目URL",
    "page_number": "页码",
    "rank": "排名",
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

REQUESTED_DATA_FIELDS = [
    "review_count",
    "rating_value",
    "seller_name",
    "brand_name",
    "seller_country",
    "sales_30_days_child",
    "sales_30_days_parent",
    "fba_fee",
    "gross_margin",
    "fulfillment_method",
    "delivery_duration",
    "launch_date",
    "organic_keywords_count",
    "ad_keywords_count",
]

HEADER_ALIASES = {
    "review_count": ["review", "ratings", "rating count", "评论", "评价", "ratings units sold", "number of ratings"],
    "rating_value": ["latest rating", "star", "评分", "星级", "rating"],
    "seller_name": ["seller", "卖家", "店铺"],
    "brand_name": ["brand", "品牌"],
    "seller_country": ["country", "国家", "所在地", "location"],
    "sales_30_days_child": ["units sold", "30 days", "30-day", "近30", "月销量", "销量", "子体"],
    "sales_30_days_parent": ["units sold", "30 days", "30-day", "近30", "月销量", "销量", "父体"],
    "fba_fee": ["fba fee", "fba fees", "fba费用", "配送费"],
    "gross_margin": ["gross margin", "margin", "毛利率", "利润率"],
    "fulfillment_method": ["fulfillment", "配送方式", "fba/fbm", "fulfilment"],
    "delivery_duration": ["delivery", "配送时长", "estimated delivery", "到达"],
    "launch_date": ["launch", "上架", "available since", "date first available"],
    "organic_keywords_count": ["organic", "自然搜索词", "自然词"],
    "ad_keywords_count": ["ad keyword", "sponsored", "广告搜索词", "广告词", "ppc"],
}

COUNTRY_BY_FLAG_CODE = {
    "ae": "阿联酋",
    "au": "澳大利亚",
    "be": "比利时",
    "br": "巴西",
    "ca": "加拿大",
    "ch": "瑞士",
    "cn": "中国",
    "de": "德国",
    "es": "西班牙",
    "fr": "法国",
    "gb": "英国",
    "hk": "中国香港",
    "ie": "爱尔兰",
    "in": "印度",
    "it": "意大利",
    "jp": "日本",
    "kr": "韩国",
    "mx": "墨西哥",
    "my": "马来西亚",
    "nl": "荷兰",
    "pl": "波兰",
    "sa": "沙特阿拉伯",
    "se": "瑞典",
    "sg": "新加坡",
    "th": "泰国",
    "tr": "土耳其",
    "tw": "中国台湾",
    "uk": "英国",
    "us": "美国",
    "vn": "越南",
}


class UserFacingError(RuntimeError):
    pass


def now_ts() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UserFacingError(f"没有找到配置文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise UserFacingError(f"配置文件不是有效 JSON：{path}") from exc


def dump_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def resolve_path(value: str, base: Path = ROOT_DIR) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path


def config_text(config: Dict[str, Any], key: str, default: str = "") -> str:
    value = config.get(key, default)
    return "" if value is None else str(value).strip()


def config_int(config: Dict[str, Any], key: str, default: Optional[int] = None) -> Optional[int]:
    value = config.get(key, default)
    if value in ("", None):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise UserFacingError(f"配置项 `{key}` 必须是数字或空值。") from exc


def config_float(config: Dict[str, Any], key: str, default: float) -> float:
    value = config.get(key, default)
    if value in ("", None):
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise UserFacingError(f"配置项 `{key}` 必须是数字。") from exc


def config_bool(config: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def slugify(value: str) -> str:
    value = value.strip() or "category-rank"
    value = re.sub(r"[\\/:*?\"<>|]+", " ", value)
    value = re.sub(r"\s+", "-", value)
    return value.strip("-_")[:90] or "category-rank"


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\u00a0", " ")).strip()


def normalize_header(value: str) -> str:
    value = normalize_space(value).lower()
    value = value.replace("（", "(").replace("）", ")")
    value = re.sub(r"[\s_:/|]+", " ", value)
    return value


def country_from_flag_code_or_text(value: str) -> str:
    text = normalize_space(value).strip().lower()
    if not text:
        return ""
    code_match = re.search(r"(?:flag-icon|icp-nav-flag)-([a-z]{2})\b", text)
    if code_match:
        text = code_match.group(1)
    text = text.removeprefix("flag-icon-").removeprefix("icp-nav-flag-")
    return COUNTRY_BY_FLAG_CODE.get(text, text.upper() if re.fullmatch(r"[a-z]{2}", text) else "")


def clean_url(url: str) -> str:
    parsed = urlparse(url)
    clean_query = []
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if key.lower() in {"ref", "qid", "sprefix", "crid", "rnid"}:
            continue
        for value in values:
            clean_query.append((key, value))
    query = "&".join(f"{key}={value}" for key, value in clean_query)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))


def validate_amazon_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UserFacingError("start_url 必须是 http 或 https 地址。")
    host = parsed.netloc.lower()
    if "amazon." not in host:
        raise UserFacingError("start_url 必须是 Amazon 类目页面地址。")


def extract_node_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("node", "rh"):
        values = query.get(key)
        if values:
            match = re.search(r"(\d{4,})", values[-1])
            if match:
                return match.group(1)
    matches = re.findall(r"/(\d{4,})(?:[/?#]|$)", parsed.path)
    if matches:
        return matches[-1]
    matches = re.findall(r"_(\d{4,})(?:[/?#_]|$)", url)
    return matches[-1] if matches else ""


def category_key(node: Dict[str, Any]) -> str:
    node_id = str(node.get("node_id") or "").strip()
    if node_id:
        return f"node:{node_id}"
    return f"url:{clean_url(str(node.get('url') or ''))}"


def page_key(node: Dict[str, Any], page_number: int, url: str) -> str:
    return f"{category_key(node)}|page:{page_number}|{clean_url(url)}"


def infer_category_name_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    parts = [part for part in path.split("/") if part]
    for part in reversed(parts):
        if not re.fullmatch(r"\d{4,}", part):
            return normalize_space(part.replace("-", " ").title())
    return "Amazon Category"


@dataclass
class RuntimeConfig:
    start_url: str
    job_id: str
    outputs_root: Path
    browser_mode: str
    chrome_binary: str
    chrome_user_data_dir: Path
    chrome_profile_directory: str
    debugger_address: str
    extension_path: Path
    include_root: bool
    max_depth: Optional[int]
    max_pages_per_category: Optional[int]
    max_categories: Optional[int]
    resume: bool
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


def build_runtime_config(config: Dict[str, Any], config_path: Path, no_resume: bool) -> RuntimeConfig:
    start_url = config_text(config, "start_url")
    if not start_url:
        raise UserFacingError("配置项 `start_url` 不能为空。")
    validate_amazon_url(start_url)

    job_id = config_text(config, "job_id") or f"category-rank-{now_ts()}"
    outputs_root = resolve_path(config_text(config, "outputs_root", "outputs"))
    browser_mode = config_text(config, "browser_mode", "launch").lower()
    if browser_mode not in {"launch", "attach", "reuse", "applescript"}:
        raise UserFacingError("配置项 `browser_mode` 只支持 launch、attach、reuse 或 applescript。")

    chrome_binary = config_text(config, "chrome_binary")
    chrome_user_data_dir = resolve_path(config_text(config, "chrome_user_data_dir", "chrome_profiles/category-rank-sellersprite"))
    chrome_profile_directory = config_text(config, "chrome_profile_directory", "Default") or "Default"
    debugger_address = config_text(config, "debugger_address", "127.0.0.1:9222")
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

    return RuntimeConfig(
        start_url=start_url,
        job_id=slugify(job_id),
        outputs_root=outputs_root,
        browser_mode=browser_mode,
        chrome_binary=chrome_binary,
        chrome_user_data_dir=chrome_user_data_dir,
        chrome_profile_directory=chrome_profile_directory,
        debugger_address=debugger_address,
        extension_path=extension_path,
        include_root=config_bool(config, "include_root", False),
        max_depth=config_int(config, "max_depth"),
        max_pages_per_category=config_int(config, "max_pages_per_category"),
        max_categories=config_int(config, "max_categories"),
        resume=False if no_resume else config_bool(config, "resume", True),
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


class StateStore:
    def __init__(self, path: Path, runtime: RuntimeConfig) -> None:
        self.path = path
        self.runtime = runtime
        self.data: Dict[str, Any] = {}

    def load_or_create(self) -> None:
        if self.runtime.resume and self.path.exists():
            self.data = load_json(self.path)
            return
        root_name = infer_category_name_from_url(self.runtime.start_url)
        root_node = {
            "url": self.runtime.start_url,
            "name": root_name,
            "path": [root_name],
            "node_id": extract_node_id(self.runtime.start_url),
            "depth": 0,
        }
        self.data = {
            "job_id": self.runtime.job_id,
            "start_url": self.runtime.start_url,
            "created_at": now_iso(),
            "queue": [root_node],
            "current": None,
            "seen_categories": [category_key(root_node)],
            "done_categories": [],
            "completed_pages": [],
            "processed_categories_count": 0,
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
        node = queue.pop(0)
        current = {
            "node": node,
            "page_number": 1,
            "page_url": node["url"],
            "children_enqueued": False,
            "children": [],
        }
        self.data["queue"] = queue
        self.data["current"] = current
        self.flush()
        return current

    def set_current(self, current: Optional[Dict[str, Any]]) -> None:
        self.data["current"] = current
        self.flush()

    def enqueue_children(self, children: Sequence[Dict[str, Any]]) -> int:
        queue = self.data.setdefault("queue", [])
        seen = set(self.data.setdefault("seen_categories", []))
        added = 0
        for child in children:
            key = category_key(child)
            if key in seen:
                continue
            seen.add(key)
            queue.append(child)
            added += 1
        self.data["seen_categories"] = sorted(seen)
        self.data["queue"] = queue
        self.flush()
        return added

    def mark_page_completed(self, key: str, count: int) -> None:
        completed = set(self.data.setdefault("completed_pages", []))
        completed.add(key)
        self.data["completed_pages"] = sorted(completed)
        self.data["records_count"] = int(self.data.get("records_count") or 0) + count
        self.flush()

    def is_page_completed(self, key: str) -> bool:
        return key in set(self.data.get("completed_pages") or [])

    def finish_current_category(self) -> None:
        current = self.data.get("current")
        if current:
            node = current.get("node") or {}
            done = set(self.data.setdefault("done_categories", []))
            done.add(category_key(node))
            self.data["done_categories"] = sorted(done)
            self.data["processed_categories_count"] = int(self.data.get("processed_categories_count") or 0) + 1
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


def start_driver(runtime: RuntimeConfig) -> WebDriver:
    if runtime.browser_mode == "applescript":
        return AppleScriptChromeDriver(runtime.page_timeout)  # type: ignore[return-value]
    options = Options()
    if runtime.browser_mode == "launch":
        launch_debug_chrome(runtime)
        options.add_experimental_option("debuggerAddress", runtime.debugger_address)
        return webdriver.Chrome(options=options)
    if runtime.browser_mode in {"attach", "reuse"}:
        if runtime.browser_mode == "reuse" and not wait_for_debugger(runtime.debugger_address, timeout=2):
            raise UserFacingError(
                "没有找到可复用的 Chrome 调试窗口。请先打开带调试端口的 Chrome，"
                f"或把 browser_mode 改回 launch。当前配置的调试地址是：{runtime.debugger_address}"
            )
        options.add_experimental_option("debuggerAddress", runtime.debugger_address)
        return webdriver.Chrome(options=options)

    raise UserFacingError(f"不支持的浏览器模式：{runtime.browser_mode}")


def launch_debug_chrome(runtime: RuntimeConfig) -> None:
    if wait_for_debugger(runtime.debugger_address, timeout=2):
        return
    chrome_binary = Path(runtime.chrome_binary)
    if runtime.chrome_binary and not chrome_binary.exists():
        raise UserFacingError(f"没有找到 Chrome：{runtime.chrome_binary}")
    ensure_dir(runtime.chrome_user_data_dir)
    port = parse_debugger_port(runtime.debugger_address)
    command = [
        runtime.chrome_binary,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={runtime.chrome_user_data_dir}",
        f"--profile-directory={runtime.chrome_profile_directory}",
        "--no-first-run",
        "--new-window",
        "about:blank",
    ]
    if runtime.extension_path and runtime.extension_path.exists():
        command.insert(-2, f"--load-extension={runtime.extension_path}")
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_for_debugger(runtime.debugger_address, timeout=90):
        raise UserFacingError(
            "Chrome 调试端口没有启动成功。请关闭刚打开的专用 Chrome 后重试，"
            "或把 browser_mode 改成 attach 并手动打开调试端口。"
        )


def parse_debugger_port(address: str) -> int:
    address = address.strip()
    if ":" not in address:
        raise UserFacingError("debugger_address 需要形如 127.0.0.1:9222。")
    try:
        return int(address.rsplit(":", 1)[-1])
    except ValueError as exc:
        raise UserFacingError("debugger_address 端口不是有效数字。") from exc


def wait_for_debugger(address: str, timeout: int) -> bool:
    deadline = time.time() + timeout
    endpoint = f"http://{address}/json/version"
    while time.time() < deadline:
        try:
            with urlopen(endpoint, timeout=2) as response:
                return response.status == 200
        except Exception:
            time.sleep(1)
    return False


def start_driver_legacy(runtime: RuntimeConfig) -> WebDriver:
    options = Options()
    if runtime.chrome_binary:
        options.binary_location = runtime.chrome_binary
    ensure_dir(runtime.chrome_user_data_dir)
    options.add_argument(f"--user-data-dir={runtime.chrome_user_data_dir}")
    options.add_argument(f"--profile-directory={runtime.chrome_profile_directory}")
    options.add_argument("--start-maximized")
    if runtime.extension_path and runtime.extension_path.exists():
        options.add_argument(f"--disable-extensions-except={runtime.extension_path}")
        options.add_argument(f"--load-extension={runtime.extension_path}")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(runtime.page_timeout)
    return driver


class AppleScriptElement:
    def __init__(self, text: str = "") -> None:
        self.text = text


class AppleScriptChromeDriver:
    is_applescript_driver = True

    def __init__(self, page_timeout: int) -> None:
        self.page_timeout = page_timeout
        self.set_page_load_timeout(page_timeout)
        try:
            self.execute_script("return String(123);")
        except WebDriverException as exc:
            raise UserFacingError(
                "当前 Chrome 还没有打开“允许 Apple 事件中的 JavaScript”。"
                "请在 Chrome 菜单栏选择：显示 > 开发者 > 允许 Apple 事件中的 JavaScript。"
            ) from exc

    def _run_osascript(self, script: str, *args: str) -> str:
        result = subprocess.run(
            ["osascript", "-e", script, *args],
            text=True,
            capture_output=True,
            timeout=max(self.page_timeout, 30),
        )
        if result.returncode != 0:
            raise WebDriverException((result.stderr or result.stdout or "").strip())
        return (result.stdout or "").rstrip("\n")

    def set_page_load_timeout(self, timeout: int) -> None:
        self.page_timeout = timeout

    def get(self, url: str) -> None:
        script = r'''
on run argv
  set targetUrl to item 1 of argv
  tell application "Google Chrome"
    activate
    if (count of windows) = 0 then make new window
    set URL of active tab of front window to targetUrl
  end tell
end run
'''
        self._run_osascript(script, url)

    @property
    def current_url(self) -> str:
        script = r'''
tell application "Google Chrome"
  if (count of windows) = 0 then return ""
  return URL of active tab of front window
end tell
'''
        return self._run_osascript(script)

    @property
    def title(self) -> str:
        script = r'''
tell application "Google Chrome"
  if (count of windows) = 0 then return ""
  return title of active tab of front window
end tell
'''
        return self._run_osascript(script)

    @property
    def page_source(self) -> str:
        return str(self.execute_script("return document.documentElement ? document.documentElement.outerHTML : '';") or "")

    def refresh(self) -> None:
        script = r'''
tell application "Google Chrome"
  if (count of windows) > 0 then reload active tab of front window
end tell
'''
        self._run_osascript(script)

    def quit(self) -> None:
        return None

    def save_screenshot(self, path: str) -> bool:
        return False

    def find_element(self, by: str = By.ID, value: Optional[str] = None) -> AppleScriptElement:
        if by == By.TAG_NAME and value and value.lower() == "body":
            text = str(self.execute_script("return document.body ? document.body.innerText : '';") or "")
            return AppleScriptElement(text)
        if by == By.CSS_SELECTOR and value:
            exists = bool(self.execute_script("return !!document.querySelector(arguments[0]);", value))
            if exists:
                text = str(self.execute_script("const el = document.querySelector(arguments[0]); return el ? (el.innerText || el.textContent || '') : '';", value) or "")
                return AppleScriptElement(text)
        raise NoSuchElementException(value or "")

    def execute_script(self, script: str, *args: Any) -> Any:
        js_args = json.dumps(list(args), ensure_ascii=False)
        wrapped = f"""
(function() {{
  const __codexArgs = {js_args};
  const __codexUserFn = function() {{
{script}
  }};
  const __codexResult = __codexUserFn.apply(window, __codexArgs);
  return JSON.stringify(__codexResult === undefined ? null : __codexResult);
}})();
"""
        apple_script = r'''
on run argv
  set jsPath to item 1 of argv
  set jsCode to read (POSIX file jsPath) as «class utf8»
  tell application "Google Chrome"
    if (count of windows) = 0 then make new window
    return execute active tab of front window javascript jsCode
  end tell
end run
'''
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=True) as fh:
            fh.write(wrapped)
            fh.flush()
            raw = self._run_osascript(apple_script, fh.name)
        if raw == "":
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JavascriptException(raw) from exc


def sleep_between_pages(runtime: RuntimeConfig) -> None:
    delay = random.uniform(runtime.delay_seconds_min, runtime.delay_seconds_max)
    time.sleep(delay)


class BatchPauseScheduler:
    def __init__(self, runtime: RuntimeConfig) -> None:
        self.runtime = runtime
        self.pages_since_pause = 0
        self.next_pause_after = self._pick_next_pause_after()

    def _pick_next_pause_after(self) -> int:
        min_pages = self.runtime.batch_pause_pages_min
        max_pages = self.runtime.batch_pause_pages_max
        if min_pages <= 0 or max_pages <= 0:
            return 0
        return random.randint(min_pages, max_pages)

    def after_completed_page(self) -> None:
        if not self.next_pause_after:
            return
        self.pages_since_pause += 1
        if self.pages_since_pause < self.next_pause_after:
            return
        duration = random.uniform(self.runtime.batch_pause_seconds_min, self.runtime.batch_pause_seconds_max)
        if duration > 0:
            print(f"已连续抓取 {self.pages_since_pause} 页，自动休息 {duration / 60:.1f} 分钟以降低风控风险。")
            time.sleep(duration)
        self.pages_since_pause = 0
        self.next_pause_after = self._pick_next_pause_after()


def safe_find_text(driver: WebDriver) -> str:
    try:
        return normalize_space(driver.find_element(By.TAG_NAME, "body").text)
    except WebDriverException:
        return ""


def detect_block(driver: WebDriver) -> Optional[str]:
    title = ""
    try:
        title = driver.title or ""
    except WebDriverException:
        pass
    text = safe_find_text(driver)
    haystack = f"{title}\n{text}".lower()
    if "sellersprite" in haystack or "卖家精灵" in haystack:
        sellersprite_verify_markers = [
            "slide to verify",
            "complete the verification",
            "enter the characters you see",
            "validatecaptcha",
            "captcha",
            "robot check",
            "机器人检测",
            "我不是机器人",
            "验证码",
        ]
        if any(marker in haystack for marker in sellersprite_verify_markers):
            return "sellersprite_verification"
    checks = [
        ("amazon_robot_check", ["robot check", "enter the characters you see", "validatecaptcha", "captcha", "机器人检测", "我不是机器人"]),
        ("amazon_sign_in", ["sign in", "authentication required", "enter your password", "请先登录亚马逊", "登录亚马逊"]),
        ("amazon_rate_limit", ["sorry", "unusual traffic", "request has been blocked", "异常流量", "请求被阻止"]),
        ("access_denied", ["access denied", "not authorized", "permission", "拒绝访问", "无权访问"]),
    ]
    for reason, markers in checks:
        if any(marker in haystack for marker in markers):
            if reason == "amazon_sign_in" and "amazon.com/ap/signin" not in driver.current_url:
                continue
            return reason
    return None


def wait_for_manual_continue(timeout: int) -> bool:
    deadline = time.time() + timeout
    prompt = "人工处理完成后按 Enter 继续；在 Codex 中请告诉我“继续”："
    while time.time() < deadline:
        remaining = max(0, deadline - time.time())
        print(prompt, flush=True)
        try:
            ready, _, _ = select.select([sys.stdin], [], [], min(remaining, 30))
        except (OSError, ValueError):
            ready = []
        if ready:
            try:
                line = sys.stdin.readline()
            except EOFError:
                return False
            if line == "":
                return False
            return True
        print("仍在等待人工确认继续。", flush=True)
    return False


def wait_for_manual_clear(driver: WebDriver, reason: str, timeout: int) -> bool:
    print(f"检测到需要人工处理：{reason}")
    print("脚本已暂停并保留当前页面。请在 Chrome 中手动输入验证数字或完成登录。")
    while wait_for_manual_continue(timeout):
        if not detect_block(driver):
            return True
        print("页面仍显示验证或限制，请继续处理后再确认。")
    return False


def wait_for_amazon_products(driver: WebDriver, runtime: RuntimeConfig) -> None:
    selectors = [
        "#gridItemRoot",
        ".zg-grid-general-faceout",
        ".p13n-grid-content",
        "[data-asin]:not([data-asin=''])",
        ".s-result-item[data-asin]:not([data-asin=''])",
    ]
    condition = EC.presence_of_element_located((By.CSS_SELECTOR, ",".join(selectors)))
    WebDriverWait(driver, runtime.page_timeout).until(condition)


def try_activate_plugin(driver: WebDriver) -> bool:
    script = r"""
const words = ['Product Research', 'SellerSprite', '卖家精灵', '产品调研', 'BSR'];
const isVisible = (el) => {
  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
};
const candidates = [...document.querySelectorAll('button,a,div,span')].filter(el => {
  const text = (el.innerText || el.textContent || '').trim();
  if (!text || text.length > 80 || !isVisible(el)) return false;
  return words.some(word => text.includes(word));
});
for (const el of candidates.slice(0, 5)) {
  try {
    el.click();
    return true;
  } catch (err) {}
}
return false;
"""
    try:
        return bool(driver.execute_script(script))
    except JavascriptException:
        return False


def plugin_node_count(driver: WebDriver) -> int:
    script = r"""
const selector = [
  '[id*="sellersprite" i]',
  '[class*="sellersprite" i]',
  '[id*="seller-sprite" i]',
  '[class*="seller-sprite" i]',
  '[id*="__ss" i]',
  '[class*="vxe-" i]',
  '[class*="ss-" i]',
  '[class*="sprite" i]'
].join(',');
return document.querySelectorAll(selector).length;
"""
    try:
        return int(driver.execute_script(script) or 0)
    except (JavascriptException, WebDriverException):
        return 0


def wait_for_user_plugin_action(driver: WebDriver, reason: str) -> None:
    print(f"卖家精灵插件需要人工处理：{reason}")
    print("请在当前 Chrome 窗口安装/启用卖家精灵插件，并完成登录。")
    print("处理完成后回到这里按 Enter；如果是 Codex 正在运行，请告诉我“已登录插件，继续”。")
    try:
        input("插件处理完成后按 Enter 继续：")
    except EOFError:
        pass
    try:
        driver.refresh()
    except WebDriverException:
        pass


def wait_for_sellersprite_data_or_prompt(
    driver: WebDriver,
    runtime: RuntimeConfig,
    on_manual_pause: Optional[Any] = None,
    on_manual_resume: Optional[Any] = None,
    restart_driver: Optional[Any] = None,
) -> str:
    def handle_block(current_driver: WebDriver) -> Optional[str]:
        if on_manual_pause:
            on_manual_pause("sellersprite_or_amazon_verification", current_driver.current_url)
        cleared = wait_for_manual_clear(current_driver, "sellersprite_or_amazon_verification", runtime.manual_pause_timeout)
        if cleared and on_manual_resume:
            on_manual_resume()
        return None if cleared else "blocked"

    def retry_with_refresh(current_driver: WebDriver, attempts: int, label: str) -> tuple[str, WebDriver]:
        last_status = "plugin_timeout"
        for attempt in range(1, attempts + 1):
            wait_seconds = random_plugin_retry_wait(runtime)
            print(
                f"{label} {attempt}/{attempts}：刷新当前页后最多等待 {wait_seconds:.1f} 秒，重新检测卖家精灵数据。"
            )
            try:
                current_driver.refresh()
            except WebDriverException:
                pass
            try:
                wait_for_amazon_products(current_driver, runtime)
            except TimeoutException:
                pass
            last_status = wait_for_sellersprite_data(current_driver, runtime, wait_seconds)
            if last_status == "ok":
                return last_status, current_driver
            if last_status == "blocked":
                blocked_result = handle_block(current_driver)
                if blocked_result:
                    return blocked_result, current_driver
        return last_status, current_driver

    while True:
        status = wait_for_sellersprite_data(driver, runtime)
        if status == "ok":
            return status
        if status == "blocked":
            blocked_result = handle_block(driver)
            if blocked_result:
                return blocked_result
            continue

        status, driver = retry_with_refresh(driver, runtime.plugin_retry_attempts, "卖家精灵数据未成功加载，自动重试")
        if status == "ok":
            return status
        if status == "blocked":
            return status

        if restart_driver is not None and runtime.plugin_relaunch_retry_attempts > 0:
            page_url = driver.current_url
            print(
                f"连续 {runtime.plugin_retry_attempts} 次仍未加载卖家精灵数据，关闭窗口并等待 "
                f"{runtime.plugin_relaunch_wait_seconds / 60:.1f} 分钟后重新拉起。"
            )
            driver = restart_driver(driver, page_url, runtime.plugin_relaunch_wait_seconds)
            status, driver = retry_with_refresh(driver, runtime.plugin_relaunch_retry_attempts, "重启浏览器后自动重试")
            if status == "ok":
                return status
            if status == "blocked":
                return status

        if restart_driver is not None and runtime.plugin_second_relaunch_retry_attempts > 0:
            page_url = driver.current_url
            print(
                f"重启后仍未加载卖家精灵数据，再次关闭窗口并等待 "
                f"{runtime.plugin_second_relaunch_wait_seconds / 60:.1f} 分钟后重新拉起。"
            )
            driver = restart_driver(driver, page_url, runtime.plugin_second_relaunch_wait_seconds)
            status, driver = retry_with_refresh(driver, runtime.plugin_second_relaunch_retry_attempts, "第二次重启浏览器后自动重试")
            if status == "ok":
                return status
            if status == "blocked":
                return status

        node_count = plugin_node_count(driver)
        if node_count <= 0:
            wait_for_user_plugin_action(driver, "当前页面未检测到卖家精灵插件注入，可能未安装、未启用或当前 Chrome 不是安装插件的用户资料。")
        else:
            wait_for_user_plugin_action(driver, "已检测到卖家精灵插件，但插件数据没有加载成功，通常是未登录、登录过期或插件弹窗需要确认。")
        try:
            wait_for_amazon_products(driver, runtime)
        except TimeoutException:
            pass


def extract_product_cards(driver: WebDriver) -> List[Dict[str, Any]]:
    script = r"""
const asinRe = /\b([A-Z0-9]{10})\b/;
const asinUrlRe = /\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?#]|$)/i;
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const absUrl = (href) => {
  try { return new URL(href, location.href).href; } catch (err) { return href || ''; }
};
const getAsin = (el) => {
  const attrs = ['data-asin', 'asin', 'data-csa-c-asin'];
  for (const attr of attrs) {
    const value = el.getAttribute(attr);
    if (value && /^[A-Z0-9]{10}$/.test(value.trim())) return value.trim();
  }
  const links = [...el.querySelectorAll('a[href]')].map(a => a.href);
  for (const href of links) {
    const match = href.match(asinUrlRe);
    if (match) return match[1];
  }
  const text = norm(el.innerText || el.textContent || '');
  const match = text.match(asinRe);
  return match ? match[1] : '';
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
const getRank = (el) => {
  const selectors = ['.zg-bdg-text', '.zg-badge-text', '[aria-label^="#"]'];
  for (const selector of selectors) {
    const item = el.querySelector(selector);
    if (!item) continue;
    const text = norm(item.getAttribute('aria-label') || item.innerText || item.textContent || '');
    const match = text.match(/#?\s*(\d{1,5})/);
    if (match) return match[1];
  }
  const text = norm(el.innerText || '');
  const match = text.match(/#\s*(\d{1,5})/);
  return match ? match[1] : '';
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
  '#gridItemRoot',
  '.zg-grid-general-faceout',
  '.p13n-grid-content',
  '.s-result-item[data-asin]:not([data-asin=""])',
  '[data-asin]:not([data-asin=""])'
];
const seenElements = new Set();
const cards = [];
for (const selector of selectors) {
  for (const el of document.querySelectorAll(selector)) {
    if (seenElements.has(el)) continue;
    seenElements.add(el);
    const asin = getAsin(el);
    if (!asin) continue;
    cards.push({
      asin,
      title: getTitle(el),
      product_url: getUrl(el, asin),
      rank: getRank(el),
      seller_country_flag_code: getSellerCountryFlagCode(el),
      text: norm(el.innerText || el.textContent || '')
    });
  }
}
const byAsin = new Map();
for (const card of cards) {
  if (!byAsin.has(card.asin) || card.text.length > byAsin.get(card.asin).text.length) {
    byAsin.set(card.asin, card);
  }
}
return [...byAsin.values()];
"""
    try:
        return list(driver.execute_script(script) or [])
    except (JavascriptException, WebDriverException):
        return []


def extract_table_rows(driver: WebDriver) -> List[Dict[str, Any]]:
    script = r"""
const asinRe = /\b([A-Z0-9]{10})\b/;
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const directCellText = (row) => {
  let cells = [...row.querySelectorAll(':scope > td, :scope > th, :scope > [role="cell"], :scope > [class*="cell"], :scope > div')];
  if (!cells.length) cells = [...row.children];
  return cells.map(cell => norm(cell.innerText || cell.textContent || '')).filter(Boolean);
};
const headerTexts = (row) => {
  const table = row.closest('table,[role="table"],[class*="table"],[class*="vxe"]');
  if (!table) return [];
  const headers = [...table.querySelectorAll('thead th, [role="columnheader"], .vxe-header--column')];
  return headers.map(cell => norm(cell.innerText || cell.textContent || '')).filter(Boolean);
};
const rows = [];
const selectors = ['tr', '[role="row"]', '.vxe-body--row', '[class*="body--row"]', '[class*="table-row"]'];
const seen = new Set();
for (const selector of selectors) {
  for (const row of document.querySelectorAll(selector)) {
    if (seen.has(row)) continue;
    seen.add(row);
    const text = norm(row.innerText || row.textContent || '');
    const match = text.match(asinRe);
    if (!match) continue;
    rows.push({
      asin: match[1],
      text,
      cells: directCellText(row),
      headers: headerTexts(row)
    });
  }
}
return rows;
"""
    try:
        return list(driver.execute_script(script) or [])
    except (JavascriptException, WebDriverException):
        return []


def extract_by_selectors(driver: WebDriver, card: Dict[str, Any], selectors: Dict[str, List[str]]) -> Dict[str, str]:
    if not selectors:
        return {}
    asin = card.get("asin") or ""
    script = r"""
const asin = arguments[0];
const selectorMap = arguments[1] || {};
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const cards = [...document.querySelectorAll('#gridItemRoot,.zg-grid-general-faceout,.p13n-grid-content,.s-result-item,[data-asin]')];
const card = cards.find(el => {
  if (el.getAttribute('data-asin') === asin) return true;
  return (el.innerText || el.textContent || '').includes(asin) || [...el.querySelectorAll('a[href]')].some(a => a.href.includes(asin));
});
const output = {};
for (const [field, selectors] of Object.entries(selectorMap)) {
  for (const selector of selectors || []) {
    let found = null;
    try {
      found = card ? card.querySelector(selector) : document.querySelector(selector);
    } catch (err) {
      found = null;
    }
    if (!found) continue;
    const text = norm(found.innerText || found.textContent || found.getAttribute('title') || found.getAttribute('aria-label') || '');
    if (text) {
      output[field] = text;
      break;
    }
  }
}
return output;
"""
    try:
        return dict(driver.execute_script(script, asin, selectors) or {})
    except (JavascriptException, WebDriverException):
        return {}


def split_lines(text: str) -> List[str]:
    lines = []
    for raw in re.split(r"[\n\r]+| {2,}", text or ""):
        line = normalize_space(raw)
        if line:
            lines.append(line)
    return lines


def value_near_labels(text: str, labels: Sequence[str]) -> str:
    lines = split_lines(text)
    lower_labels = [label.lower() for label in labels]
    for index, line in enumerate(lines):
        line_lower = line.lower()
        for label in lower_labels:
            if label not in line_lower:
                continue
            pattern = re.compile(re.escape(label), re.I)
            value = pattern.split(line, maxsplit=1)[-1]
            value = value.strip(" :：|-")
            if value and value.lower() != label:
                return value[:120]
            if index + 1 < len(lines):
                return lines[index + 1][:120]
    return ""


def first_regex(text: str, patterns: Sequence[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return normalize_space(match.group(1))
    return ""


def parse_field_from_text(field_name: str, text: str) -> str:
    text = normalize_space(text)
    if not text:
        return ""

    zh_value = parse_sellersprite_inline_field(field_name, text)
    if zh_value:
        return zh_value
    if field_name == "sales_30_days_parent":
        return ""

    if field_name == "review_count":
        return first_regex(text, [r"评分\(评分数\)[:：]\s*(?:[0-9.]+|N/A)\(([\d,]+|N/A)\)", r"([\d,]+)\s+(?:ratings?|reviews?)", r"(?:评论|评价)\D{0,8}([\d,]+)"])
    if field_name == "rating_value":
        return first_regex(text, [r"评分\(评分数\)[:：]\s*([0-9.]+|N/A)\((?:[\d,]+|N/A)\)", r"([1-5](?:\.\d)?)\s+out of\s+5", r"([1-5](?:\.\d)?)\s*(?:stars?|星)"])
    if field_name in {"sales_30_days", "sales_30_days_child", "sales_30_days_parent"}:
        return first_regex(text, [r"([\d,.]+[Kk万]?)\s*(?:units sold|sold|月销量|销量)", r"(?:30 days?|近30天)\D{0,12}([\d,.]+[Kk万]?)"])
    if field_name == "fba_fee":
        return first_regex(text, [r"FBA费用[:：]\s*(N/A|\$?\s*[\d,.]+)", r"FBA\D{0,20}(N/A|\$?\s*[\d,.]+)", r"(\$?\s*[\d,.]+)\s*FBA"])
    if field_name == "gross_margin":
        return first_regex(text, [r"毛利率[:：]\s*(N/A|[\d,.]+%)", r"([\d,.]+%)\s*(?:gross margin|margin|毛利率)", r"(?:gross margin|margin|毛利率)\D{0,12}([\d,.]+%)"])
    if field_name == "fulfillment_method":
        return first_regex(text, [r"\b(FBA|FBM|AMZ)\b"])
    if field_name in {"organic_keywords_count", "ad_keywords_count"}:
        return first_regex(text, [r"([\d,]+)\s*(?:keywords?|词)"])

    labels = HEADER_ALIASES.get(field_name, [])
    labelled = value_near_labels(text, labels)
    if labelled:
        return labelled
    return ""


def parse_sellersprite_inline_field(field_name: str, text: str) -> str:
    patterns = {
        "brand_name": [r"品牌[:：]\s*(.*?)\s+卖家[:：]"],
        "seller_name": [r"卖家[:：]\s*(.*?)\s+配送[:：]"],
        "seller_country": [r"卖家所处国家[:：]\s*([^\s]+)", r"卖家国家[:：]\s*([^\s]+)"],
        "sales_30_days": [r"近30天销量\(子体\)[:：]\s*([^\s]+)", r"近30天销量[:：]\s*([^\s]+)"],
        "sales_30_days_child": [r"近30天销量\(子体\)[:：]\s*([^\s]+)", r"近30天销量[:：]\s*([^\s]+)"],
        "sales_30_days_parent": [r"近30天销量\(父体\)[:：]\s*([^\s]+)"],
        "fba_fee": [r"FBA费用[:：]\s*(N/A|\$?\s*[\d,.]+)"],
        "gross_margin": [r"毛利率[:：]\s*(N/A|[\d,.]+%)"],
        "fulfillment_method": [r"配送[:：]\s*(FBA|FBM|AMZ)"],
        "delivery_duration": [r"(?<!Prime)配送时长[:：]\s*([^\s]+)"],
        "launch_date": [r"上架时间[:：]\s*(\d{4}-\d{2}-\d{2}(?:\s*\([^)]+\))?)"],
        "organic_keywords_count": [r"自然搜索词[:：]\s*([\d,]+)"],
        "ad_keywords_count": [r"广告(?:搜索|流量)词[:：]\s*([\d,]+)"],
    }
    if field_name in {"rating_value", "review_count"}:
        match = re.search(r"评分\(评分数\)[:：]\s*([0-9.]+|N/A)\(([\d,]+|N/A)\)", text)
        if match:
            return match.group(1) if field_name == "rating_value" else match.group(2)
    for pattern in patterns.get(field_name, []):
        match = re.search(pattern, text, re.I)
        if match:
            return normalize_space(match.group(1))
    return ""


def map_headers_to_fields(headers: Sequence[str]) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    for index, header in enumerate(headers):
        normalized = normalize_header(header)
        if not normalized:
            continue
        if "近30" in normalized and "父体" in normalized:
            mapping[index] = "sales_30_days_parent"
            continue
        if "近30" in normalized and "子体" in normalized:
            mapping[index] = "sales_30_days_child"
            continue
        for field_name, aliases in HEADER_ALIASES.items():
            if any(alias.lower() in normalized for alias in aliases):
                if field_name == "rating_value" and "count" in normalized:
                    continue
                mapping[index] = field_name
                break
    return mapping


def parse_table_row_fields(row: Dict[str, Any]) -> Dict[str, str]:
    output: Dict[str, str] = {}
    cells = [normalize_space(str(cell)) for cell in row.get("cells") or []]
    headers = [normalize_space(str(header)) for header in row.get("headers") or []]
    header_mapping = map_headers_to_fields(headers)
    for index, field_name in header_mapping.items():
        if index < len(cells) and cells[index]:
            output[field_name] = cells[index]
    text = str(row.get("text") or "")
    for field_name in REQUESTED_DATA_FIELDS:
        if not output.get(field_name):
            output[field_name] = parse_field_from_text(field_name, text)
    return output


def merge_product_data(
    driver: WebDriver,
    runtime: RuntimeConfig,
    node: Dict[str, Any],
    page_number: int,
    plugin_status: str,
) -> List[Dict[str, Any]]:
    cards = extract_product_cards(driver)
    table_rows = extract_table_rows(driver)
    table_by_asin: Dict[str, Dict[str, str]] = {}
    for row in table_rows:
        asin = str(row.get("asin") or "")
        if not asin:
            continue
        parsed = parse_table_row_fields(row)
        current = table_by_asin.setdefault(asin, {})
        for key, value in parsed.items():
            if value and not current.get(key):
                current[key] = value

    records: List[Dict[str, Any]] = []
    for card in cards:
        asin = str(card.get("asin") or "")
        if not asin:
            continue
        record: Dict[str, Any] = {
            "root_url": runtime.start_url,
            "category_path": " > ".join(str(part) for part in node.get("path") or []),
            "category_name": node.get("name") or "",
            "category_node_id": node.get("node_id") or "",
            "category_url": node.get("url") or "",
            "page_number": page_number,
            "rank": card.get("rank") or "",
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


def preload_page_data_with_scroll(driver: WebDriver, runtime: Any) -> None:
    if not bool(getattr(runtime, "page_scroll_before_extract", True)):
        return
    max_rounds = max(int(getattr(runtime, "page_scroll_max_rounds", 18) or 0), 0)
    if max_rounds <= 0:
        return
    step_ratio = float(getattr(runtime, "page_scroll_step_ratio", 0.85) or 0.85)
    if step_ratio <= 0:
        step_ratio = 0.85
    wait_seconds = max(float(getattr(runtime, "page_scroll_wait_seconds", 1.0) or 0), 0)
    stable_target = max(int(getattr(runtime, "page_scroll_stable_rounds", 2) or 1), 1)

    print("向下滚动页面，等待 Amazon 商品和卖家精灵插件数据加载。", flush=True)
    try:
        driver.execute_script("window.scrollTo(0, 0);")
    except (JavascriptException, WebDriverException):
        return
    if wait_seconds:
        time.sleep(min(wait_seconds, 0.5))

    last_signature = ""
    stable_rounds = 0
    for round_index in range(max_rounds):
        if detect_block(driver):
            return
        if round_index == 0 and bool(getattr(runtime, "activate_plugin", True)):
            try_activate_plugin(driver)
        try:
            metrics = driver.execute_script(
                r"""
const stepRatio = Number(arguments[0]) || 0.85;
const asinRe = /\b[A-Z0-9]{10}\b/;
const asinGlobalRe = /\b[A-Z0-9]{10}\b/g;
const pluginSelector = [
  '[id*="sellersprite" i]',
  '[class*="sellersprite" i]',
  '[id*="seller-sprite" i]',
  '[class*="seller-sprite" i]',
  '[id*="__ss" i]',
  '[class*="vxe-" i]',
  '[class*="ss-" i]',
  '[class*="sprite" i]'
].join(',');
const productSelector = [
  '#gridItemRoot',
  '.zg-grid-general-faceout',
  '.p13n-grid-content',
  '.s-result-item[data-asin]:not([data-asin=""])',
  '[data-asin]:not([data-asin=""])'
].join(',');
const tableRowSelector = [
  'tr',
  '[role="row"]',
  '.vxe-body--row',
  '[class*="body--row"]',
  '[class*="table-row"]'
].join(',');
const scrollSelector = [
  pluginSelector,
  '.vxe-table--body-wrapper',
  '[class*="vxe-table--body-wrapper"]',
  '[class*="el-table__body-wrapper"]',
  '[class*="table-body"]',
  '[role="grid"]',
  '[role="table"]'
].join(',');
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const isScrollable = (el) => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden') return false;
  return (el.scrollHeight || 0) > (el.clientHeight || 0) + 40;
};
const root = document.scrollingElement || document.documentElement || document.body;
const scrollables = [root, document.documentElement, document.body, ...document.querySelectorAll(scrollSelector)];
const seen = new Set();
for (const el of scrollables) {
  if (!el || seen.has(el)) continue;
  seen.add(el);
  if (el !== root && !isScrollable(el)) continue;
  try { el.scrollBy(0, Math.max(500, window.innerHeight * stepRatio)); } catch (err) {}
}
const bodyText = document.body ? (document.body.innerText || document.body.textContent || '') : '';
const asins = new Set((bodyText.match(asinGlobalRe) || []));
for (const el of document.querySelectorAll(productSelector)) {
  const asin = el.getAttribute('data-asin') || '';
  if (asin) asins.add(asin);
}
const pluginNodes = document.querySelectorAll(pluginSelector).length;
const tableRows = [...document.querySelectorAll(tableRowSelector)].filter(row => asinRe.test(norm(row.innerText || row.textContent || ''))).length;
const scrollTop = root ? (root.scrollTop || window.scrollY || 0) : window.scrollY;
const scrollHeight = root ? root.scrollHeight : document.documentElement.scrollHeight;
const viewport = window.innerHeight || document.documentElement.clientHeight || 0;
return {
  asinCount: asins.size,
  pluginNodes,
  tableRows,
  textLength: bodyText.length,
  scrollTop,
  scrollHeight,
  atBottom: scrollTop + viewport >= scrollHeight - 20
};
""",
                step_ratio,
            )
        except (JavascriptException, WebDriverException):
            return
        if not isinstance(metrics, dict):
            return
        signature = (
            f"{metrics.get('scrollHeight')}:{metrics.get('asinCount')}:"
            f"{metrics.get('pluginNodes')}:{metrics.get('tableRows')}:{metrics.get('textLength')}"
        )
        if bool(metrics.get("atBottom")) and signature == last_signature:
            stable_rounds += 1
        else:
            stable_rounds = 0
        last_signature = signature
        if stable_rounds >= stable_target:
            break
        if wait_seconds:
            time.sleep(wait_seconds)


def wait_for_sellersprite_data(driver: WebDriver, runtime: RuntimeConfig, timeout_seconds: Optional[float] = None) -> str:
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
        node_count = plugin_node_count(driver)
        cards = extract_product_cards(driver)
        rows = extract_table_rows(driver)
        non_empty_plugin_rows = 0
        for row in rows:
            parsed = parse_table_row_fields(row)
            if sum(1 for value in parsed.values() if value) >= 2:
                non_empty_plugin_rows += 1
        non_empty_card_rows = 0
        for card in cards:
            text = str(card.get("text") or "")
            parsed_count = sum(1 for field_name in REQUESTED_DATA_FIELDS if parse_sellersprite_inline_field(field_name, text))
            if parsed_count >= 3:
                non_empty_card_rows += 1
        signature = f"{node_count}:{len(cards)}:{len(rows)}:{non_empty_plugin_rows}:{non_empty_card_rows}"
        if node_count > 0 and cards and (non_empty_plugin_rows > 0 or rows or non_empty_card_rows > 0):
            if signature == last_signature:
                stable_seen += 1
            else:
                stable_seen = 0
            if stable_seen >= 2:
                return "ok"
        last_signature = signature
        time.sleep(2)
    return "plugin_timeout"


def random_plugin_retry_wait(runtime: RuntimeConfig) -> float:
    return random.uniform(runtime.plugin_retry_wait_seconds, runtime.plugin_retry_wait_seconds_max)


def discover_child_categories(driver: WebDriver, node: Dict[str, Any]) -> List[Dict[str, Any]]:
    script = r"""
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const absUrl = (href) => {
  try { return new URL(href, location.href).href; } catch (err) { return href || ''; }
};
const nodeIdFromUrl = (url) => {
  const decoded = decodeURIComponent(url || '');
  const nodeMatch = decoded.match(/[?&]node=(\d{4,})/);
  if (nodeMatch) return nodeMatch[1];
  const pathMatches = [...decoded.matchAll(/\/(\d{4,})(?:[/?#]|$)/g)].map(m => m[1]);
  if (pathMatches.length) return pathMatches[pathMatches.length - 1];
  const refMatches = [...decoded.matchAll(/_(\d{4,})(?:[/?#_]|$)/g)].map(m => m[1]);
  return refMatches.length ? refMatches[refMatches.length - 1] : '';
};
const currentNodeId = nodeIdFromUrl(location.href);
const browseRoot = document.querySelector('#zg_browseRoot,#zg-left-col,[data-testid="departments"],#departments,#s-refinements') || document.body;
let anchors = [];
const selected = browseRoot.querySelector('.zg_selected,.a-color-state,[aria-current="page"],span[aria-current],strong');
const selectedLi = selected ? selected.closest('li') : null;
if (selectedLi) {
  const childLists = [...selectedLi.children].filter(el => el.tagName && el.tagName.toLowerCase() === 'ul');
  for (const list of childLists) {
    anchors.push(...[...list.querySelectorAll('a[href]')].filter(a => a.closest('ul') === list || a.closest('li')?.parentElement === list));
  }
  const nextLi = selectedLi.nextElementSibling && selectedLi.nextElementSibling.matches('li') ? selectedLi.nextElementSibling : null;
  if (nextLi) {
    anchors.push(...nextLi.querySelectorAll('a[href]'));
  }
}
if (!anchors.length) {
  const selectedParent = selectedLi || browseRoot;
  anchors = [...selectedParent.querySelectorAll(':scope > ul a[href], :scope > div > ul a[href]')];
}
const seen = new Set();
const output = [];
for (const a of anchors) {
  const name = norm(a.innerText || a.textContent || a.getAttribute('aria-label') || '');
  const href = absUrl(a.getAttribute('href') || a.href || '');
  const childNodeId = nodeIdFromUrl(href);
  if (!name || !href || !childNodeId || childNodeId === currentNodeId) continue;
  if (!/amazon\./i.test(href)) continue;
  const key = childNodeId || href;
  if (seen.has(key)) continue;
  seen.add(key);
  output.push({name, url: href, node_id: childNodeId});
}
return output;
"""
    try:
        raw_children = list(driver.execute_script(script) or [])
    except (JavascriptException, WebDriverException):
        raw_children = []

    parent_path = [str(part) for part in node.get("path") or []]
    depth = int(node.get("depth") or 0) + 1
    children: List[Dict[str, Any]] = []
    for child in raw_children:
        name = normalize_space(str(child.get("name") or ""))
        url = str(child.get("url") or "")
        if not name or not url:
            continue
        children.append(
            {
                "url": url,
                "name": name,
                "path": parent_path + [name],
                "node_id": str(child.get("node_id") or extract_node_id(url)),
                "depth": depth,
            }
        )
    return children


def extract_current_category_path(driver: WebDriver) -> List[str]:
    script = r"""
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim().replace(/\(Current\)$/i, '').trim();
const root = document.querySelector('#zg-left-col,#zg_browseRoot,#departments,#s-refinements');
if (!root) return [];
const output = [];
for (const a of root.querySelectorAll('li[class*="browse-up"] a[href], li[class*="browse-up"] span a[href]')) {
  const text = norm(a.innerText || a.textContent || '');
  if (text && !/^any department$/i.test(text)) output.push(text);
}
const selected = root.querySelector('[aria-current="page"], [class*="selected"]');
if (selected) {
  const text = norm(selected.innerText || selected.textContent || '');
  if (text && !output.includes(text)) output.push(text);
}
return output;
"""
    try:
        values = list(driver.execute_script(script) or [])
    except (JavascriptException, WebDriverException):
        values = []
    return [normalize_space(str(value)) for value in values if normalize_space(str(value))]


def should_descend(runtime: RuntimeConfig, node: Dict[str, Any], children: Sequence[Dict[str, Any]]) -> bool:
    if not children:
        return False
    depth = int(node.get("depth") or 0)
    if runtime.max_depth is not None and depth >= runtime.max_depth:
        return False
    return True


def find_next_page_url(driver: WebDriver) -> str:
    script = r"""
const absUrl = (href) => {
  try { return new URL(href, location.href).href; } catch (err) { return href || ''; }
};
const selectors = [
  'li.a-last a[href]',
  'ul.a-pagination a[aria-label*="Next" i]',
  'a[aria-label*="Next" i]',
  'a.s-pagination-next[href]'
];
for (const selector of selectors) {
  const el = document.querySelector(selector);
  if (el && !el.closest('.a-disabled')) return absUrl(el.getAttribute('href') || el.href || '');
}
const links = [...document.querySelectorAll('a[href]')].filter(a => /next|下一页|后一页/i.test(a.innerText || a.getAttribute('aria-label') || ''));
for (const link of links) return absUrl(link.getAttribute('href') || link.href || '');
return '';
"""
    try:
        return str(driver.execute_script(script) or "")
    except (JavascriptException, WebDriverException):
        return ""


def save_debug_snapshot(driver: WebDriver, debug_dir: Path, label: str) -> None:
    ensure_dir(debug_dir)
    safe_label = slugify(label)
    html_path = debug_dir / f"{now_ts()}_{safe_label}.html"
    png_path = debug_dir / f"{now_ts()}_{safe_label}.png"
    try:
        html_path.write_text(driver.page_source, encoding="utf-8")
    except WebDriverException:
        pass
    try:
        driver.save_screenshot(str(png_path))
    except WebDriverException:
        pass


def log_failure(
    failures_path: Path,
    state: StateStore,
    runtime: RuntimeConfig,
    node: Dict[str, Any],
    page_number: int,
    url: str,
    reason: str,
    message: str,
) -> None:
    append_jsonl(
        failures_path,
        {
            "time": now_iso(),
            "root_url": runtime.start_url,
            "category_path": " > ".join(str(part) for part in node.get("path") or []),
            "category_name": node.get("name") or "",
            "category_node_id": node.get("node_id") or "",
            "category_url": node.get("url") or "",
            "page_number": page_number,
            "page_url": url,
            "reason": reason,
            "message": message,
        },
    )
    state.log_failure()


def write_workbook(records_path: Path, failures_path: Path, output_xlsx: Path) -> None:
    if Workbook is None:
        raise UserFacingError("缺少 openpyxl，无法生成 Excel。")
    records = read_jsonl(records_path)
    failures = read_jsonl(failures_path)

    wb = Workbook()
    ws = wb.active
    ws.title = "总表"
    write_sheet(ws, OUTPUT_HEADERS, records)

    dedup_rows = build_dedup_rows(records)
    ws_dedup = wb.create_sheet("去重ASIN表")
    write_sheet(ws_dedup, OUTPUT_HEADERS, dedup_rows)

    ws_fail = wb.create_sheet("失败页面")
    failure_headers = ["time", "category_path", "category_name", "category_node_id", "page_number", "page_url", "reason", "message"]
    write_sheet(ws_fail, failure_headers, failures, raw_headers=True)

    ensure_dir(output_xlsx.parent)
    wb.save(output_xlsx)


def write_sheet(ws: Any, headers: Sequence[str], rows: Sequence[Dict[str, Any]], raw_headers: bool = False) -> None:
    ws.append(list(headers))
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
    for row in rows:
        if raw_headers:
            ws.append([row.get(header, "") for header in headers])
        else:
            ws.append([row.get(field, "") for field, header in FIELD_TO_HEADER.items() if header in headers])
    for column_index, header in enumerate(headers, start=1):
        width = min(max(len(str(header)) + 2, 12), 36)
        letter = get_column_letter(column_index)
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def build_dedup_rows(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    paths: Dict[str, List[str]] = {}
    for row in records:
        asin = str(row.get("asin") or "")
        if not asin:
            continue
        target = grouped.setdefault(asin, dict(row))
        for key, value in row.items():
            if value and not target.get(key):
                target[key] = value
        path = str(row.get("category_path") or "")
        if path:
            paths.setdefault(asin, [])
            if path not in paths[asin]:
                paths[asin].append(path)
    output = []
    for asin, row in grouped.items():
        merged = dict(row)
        merged["category_path"] = " ; ".join(paths.get(asin) or [])
        output.append(merged)
    return output


def run_crawl(runtime: RuntimeConfig, dry_run: bool) -> int:
    job_dir = ensure_dir(runtime.outputs_root / runtime.job_id)
    records_path = job_dir / "records.jsonl"
    failures_path = job_dir / "failures.jsonl"
    state_path = job_dir / "state.json"
    output_xlsx = job_dir / f"total_{runtime.job_id}_merged.xlsx"
    debug_dir = job_dir / "debug_snapshots"

    print(f"任务目录：{job_dir}")
    print(f"起始类目：{runtime.start_url}")
    print(f"浏览器模式：{runtime.browser_mode}")
    print(f"输出表格：{output_xlsx}")
    if dry_run:
        print("dry-run：配置检查完成，未打开浏览器。")
        return 0
    if not runtime.resume:
        for old_file in (records_path, failures_path, output_xlsx):
            if old_file.exists():
                old_file.unlink()

    state = StateStore(state_path, runtime)
    state.load_or_create()
    driver = start_driver(runtime)
    batch_pause = BatchPauseScheduler(runtime)

    def restart_plugin_driver(current_driver: WebDriver, page_url: str, wait_seconds: float) -> WebDriver:
        nonlocal driver
        try:
            current_driver.quit()
        except WebDriverException:
            pass
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        driver = start_driver(runtime)
        driver.get(page_url)
        try:
            wait_for_amazon_products(driver, runtime)
        except TimeoutException:
            pass
        return driver

    try:
        processed_in_this_run = 0
        while True:
            if runtime.max_categories is not None and processed_in_this_run >= runtime.max_categories:
                print("达到 max_categories，本次停止；可继续 resume。")
                break
            current = state.next_work()
            if not current:
                print("队列已完成。")
                break

            node = current["node"]
            page_number = int(current.get("page_number") or 1)
            page_url = str(current.get("page_url") or node["url"])
            print(f"处理类目：{' > '.join(node.get('path') or [])} / 第 {page_number} 页")

            try:
                driver.get(page_url)
                wait_for_page_or_manual(driver, runtime, state, failures_path, debug_dir, node, page_number, page_url)
                page_path = extract_current_category_path(driver)
                if page_path:
                    node["path"] = page_path
                    node["name"] = page_path[-1]
                    node["node_id"] = node.get("node_id") or extract_node_id(driver.current_url)
                    current["node"] = node
                    state.set_current(current)
                children = []
                if page_number == 1 and not current.get("children_enqueued"):
                    children = discover_child_categories(driver, node)
                    current["children"] = children
                    current["children_enqueued"] = True
                    state.set_current(current)

                descend = should_descend(runtime, node, children)
                if descend and not runtime.include_root:
                    added = state.enqueue_children(children)
                    print(f"发现下级类目 {len(children)} 个，新增 {added} 个；跳过当前中间节点。")
                    state.finish_current_category()
                    processed_in_this_run += 1
                    sleep_between_pages(runtime)
                    continue

                plugin_status = wait_for_sellersprite_data_or_prompt(
                    driver,
                    runtime,
                    on_manual_pause=lambda reason, url: state.mark_manual_pause(reason, url),
                    on_manual_resume=state.clear_manual_pause,
                    restart_driver=restart_plugin_driver,
                )
                if plugin_status == "blocked":
                    log_failure(failures_path, state, runtime, node, page_number, page_url, "verification_timeout", "人工处理超时")
                    save_debug_snapshot(driver, debug_dir, "verification_timeout")
                    break

                key = page_key(node, page_number, page_url)
                records: List[Dict[str, Any]] = []
                if state.is_page_completed(key):
                    print("当前页已在断点中标记完成，跳过写入。")
                else:
                    records = merge_product_data(driver, runtime, node, page_number, plugin_status)
                    for record in records:
                        append_jsonl(records_path, record)
                    state.mark_page_completed(key, len(records))
                    print(f"写入商品 {len(records)} 条，插件状态：{plugin_status}")
                    batch_pause.after_completed_page()
                    if plugin_status != "ok" and runtime.save_debug_snapshots:
                        save_debug_snapshot(driver, debug_dir, f"plugin_{plugin_status}_{extract_node_id(page_url)}_{page_number}")

                if page_number == 1 and children and runtime.include_root:
                    added = state.enqueue_children(children)
                    print(f"当前节点已抓取，同时新增下级类目 {added} 个。")

                next_url = find_next_page_url(driver)
                page_limit = runtime.max_pages_per_category
                if next_url and (page_limit is None or page_number < page_limit):
                    current["page_number"] = page_number + 1
                    current["page_url"] = next_url
                    state.set_current(current)
                else:
                    state.finish_current_category()
                    processed_in_this_run += 1
                sleep_between_pages(runtime)
            except TimeoutException as exc:
                log_failure(failures_path, state, runtime, node, page_number, page_url, "page_timeout", str(exc))
                if runtime.save_debug_snapshots:
                    save_debug_snapshot(driver, debug_dir, "page_timeout")
                state.finish_current_category()
                processed_in_this_run += 1
            except WebDriverException as exc:
                log_failure(failures_path, state, runtime, node, page_number, page_url, "webdriver_error", str(exc)[:500])
                if runtime.save_debug_snapshots:
                    save_debug_snapshot(driver, debug_dir, "webdriver_error")
                state.finish_current_category()
                processed_in_this_run += 1
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass

    write_workbook(records_path, failures_path, output_xlsx)
    print(f"已生成 Excel：{output_xlsx}")
    return 0


def wait_for_page_or_manual(
    driver: WebDriver,
    runtime: RuntimeConfig,
    state: StateStore,
    failures_path: Path,
    debug_dir: Path,
    node: Dict[str, Any],
    page_number: int,
    page_url: str,
) -> None:
    block_reason = detect_block(driver)
    if block_reason:
        state.mark_manual_pause(block_reason, driver.current_url)
        cleared = wait_for_manual_clear(driver, block_reason, runtime.manual_pause_timeout)
        if cleared:
            state.clear_manual_pause()
        if not cleared:
            log_failure(failures_path, state, runtime, node, page_number, page_url, block_reason, "人工处理超时")
            if runtime.save_debug_snapshots:
                save_debug_snapshot(driver, debug_dir, block_reason)
            raise TimeoutException(block_reason)
    wait_for_amazon_products(driver, runtime)


def main() -> int:
    parser = argparse.ArgumentParser(description="Amazon category ranking crawler with SellerSprite extension data.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只检查配置，不打开浏览器")
    parser.add_argument("--no-resume", action="store_true", help="忽略已有断点，重新开始任务")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = ROOT_DIR / config_path
    runtime = build_runtime_config(load_json(config_path), config_path, args.no_resume)
    return run_crawl(runtime, args.dry_run)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UserFacingError as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        raise SystemExit(2)
