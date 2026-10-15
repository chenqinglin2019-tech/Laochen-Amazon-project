#!/usr/bin/env python3
"""Keyword/store collection through SellerSprite's public panel and native exports."""
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import replace
import hashlib
import json
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from opencli_bridge import OpenCliBridge, cli_command
from opencli_read_recovery import ReadRecovery, BridgeReadRecoveryExhausted
from run_outcome import (CrawlStop, _atomic_write_json, classify_exception, completed_outcome,
                         config_error, finalize_run, needs_human, retry_later, start_new_run)
from safety_control import LocalSafetyController, RiskSignal, classify_amazon_risk, classify_sellersprite_risk
from sellersprite_export import parse_export, verify_export, write_outputs

DEFAULT_LIMITS = {"storefront": 1008, "keyword_search": 2000}
MARKETPLACES = {"amazon.com", "amazon.co.uk", "amazon.de", "amazon.fr", "amazon.es", "amazon.it",
                "amazon.ca", "amazon.co.jp", "amazon.in", "amazon.com.mx", "amazon.com.au",
                "amazon.ae", "amazon.nl", "amazon.pl", "amazon.se", "amazon.sa", "amazon.sg",
                "amazon.com.br", "amazon.com.tr"}
STATE_SCHEMA = "sellersprite-panel-v1"


def limit_value(value: Any, default: int) -> int | None:
    if value == "all":
        return None
    if value is None:
        raise config_error('数量上限必须为正整数或 "all"，不能为 null。')
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise config_error('数量上限必须为正整数或 "all"。')
    return value


def source_identity(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme != "https" or host not in MARKETPLACES:
        raise config_error("目标必须为受支持的 HTTPS Amazon 页面。")
    params = parse_qs(parsed.query)
    seller = (params.get("me") or params.get("seller") or params.get("merchant") or [""])[0]
    keyword = (params.get("k") or [""])[0]
    if seller:
        return host, "storefront", seller.upper()
    if keyword and (parsed.path == "/s" or parsed.path.startswith("/s/")):
        return host, "keyword_search", " ".join(keyword.split()).casefold()
    raise config_error("请使用关键词搜索页或包含 me/seller 参数的卖家商品页；品牌 Stores 首页不能直接替代卖家商品列表。")


def canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def validate_config(raw: dict, root: Path) -> dict:
    if not isinstance(raw, dict):
        raise config_error("配置文件必须是 JSON 对象。")
    mode = raw.get("mode")
    if not isinstance(mode, str) or mode not in DEFAULT_LIMITS:
        raise config_error("插件模式仅支持 storefront 和 keyword_search。")
    if raw.get("browser_backend", "opencli") != "opencli" or any(
        raw.get(key) not in (None, "") for key in ("max_pages_per_keyword", "store_page_limit")):
        raise config_error("旧分页/CDP 配置不能直接用于插件采集。请按 references/plugin-collection.md 创建新配置和新 job_id；页数不等于加载轮数。")
    job_id = raw.get("job_id", "")
    if not isinstance(job_id, str) or not re.fullmatch(r"[\w.-]+", job_id) or job_id in {".", ".."}:
        raise config_error("job_id 必须为不含目录分隔符的非空名称。")
    entry = raw.get("entry_mode", "current_tab")
    if not isinstance(entry, str) or entry not in {"current_tab", "batch"}:
        raise config_error("entry_mode 仅支持 current_tab 或 batch。")
    operation = raw.get("operation_mode", "supervised")
    if not isinstance(operation, str) or operation not in {"supervised", "unattended"}:
        raise config_error("operation_mode 仅支持 supervised 或 unattended。")
    if raw.get("browser_tab_concurrency", 1) != 1:
        raise config_error("插件采集仅支持单工作标签。")
    for key in ("include_sponsored", "resume"):
        if key in raw and not isinstance(raw[key], bool):
            raise config_error(f"{key} 必须是 JSON 布尔值。")
    from amazon_category_rank_crawler import build_product_filter_config
    try:
        filters = build_product_filter_config(raw).as_dict()
    except Exception as exc:
        raise config_error(str(exc)) from exc
    host = str(raw.get("marketplace_domain", "amazon.com")).lower().removeprefix("www.")
    if host not in MARKETPLACES:
        raise config_error("不支持的 marketplace_domain。")
    cfg = {**raw, "mode": mode, "entry_mode": entry, "job_id": job_id, "root": root,
           "browser_backend": "opencli", "operation_mode": operation, "marketplace_domain": host,
           "product_filters": filters, "include_sponsored": raw.get("include_sponsored", True)}
    for name, default in (("store_max_records", 1008), ("keyword_max_records", 2000)):
        cfg[name] = limit_value(raw.get(name, default), default)
    output_value = raw.get("outputs_root", "outputs")
    if not isinstance(output_value, str) or not output_value.strip():
        raise config_error("outputs_root 必须为非空路径字符串。")
    output_root = Path(output_value).expanduser()
    cfg["job_dir"] = (output_root if output_root.is_absolute() else root / output_root) / job_id
    return cfg


def source_task(url: str, sort_order: str = "", store_name: str = "") -> dict:
    host, kind, value = source_identity(url)
    if not sort_order:
        from amazon_front_crawler import SEARCH_SORT_OPTIONS
        requested_sort = parse_qs(urlsplit(url).query).get("s", ["featured-rank"])[0]
        sort_order = next((label for label, code in SEARCH_SORT_OPTIONS.items() if code == requested_sort), requested_sort)
    return {"source": "|".join((host, kind, value)), "source_type": kind, "marketplace": host,
            "keyword": value if kind == "keyword_search" else "",
            "store_url": url if kind == "storefront" else "", "store_name": store_name,
            "sort_order": sort_order, "url": canonical_url(url),
            "key": hashlib.sha256(f"{host}|{kind}|{value}|{sort_order}".encode()).hexdigest()[:20]}


def build_tasks(cfg: dict) -> list[dict]:
    if cfg["entry_mode"] == "current_tab":
        return []
    from amazon_front_crawler import SEARCH_SORT_OPTIONS, load_keywords, load_storefronts
    key = "store_urls_file" if cfg["mode"] == "storefront" else "keywords_file"
    filename = cfg.get(key)
    if not isinstance(filename, str) or not filename.strip():
        raise config_error(f"批量模式需要 {key}。")
    path = Path(filename).expanduser()
    if not path.is_absolute():
        path = cfg["root"] / path
    try:
        items = load_storefronts(path) if cfg["mode"] == "storefront" else load_keywords(path)
    except Exception as exc:
        raise config_error(f"输入文件无法读取：{exc}") from exc
    sorts_key = "store_sort_orders" if cfg["mode"] == "storefront" else "keyword_sort_orders"
    sorts = cfg.get(sorts_key) or ["Featured"]
    if not isinstance(sorts, list) or any(not isinstance(s, str) or s not in SEARCH_SORT_OPTIONS for s in sorts):
        raise config_error(f"{sorts_key} 包含不支持的排序。")
    tasks, keys = [], set()
    for item in items:
        for sort in dict.fromkeys(sorts):
            if cfg["mode"] == "storefront":
                original = item["store_url"]
                host, kind, seller = source_identity(original)
                if kind != "storefront":
                    raise config_error("店铺输入包含非店铺链接。")
                url = f"https://www.{host}/s?" + urlencode({"me": seller, "s": SEARCH_SORT_OPTIONS[sort]})
                task = source_task(url, sort, item.get("store_name", ""))
            else:
                url = f"https://www.{cfg['marketplace_domain']}/s?" + urlencode({"k": item, "s": SEARCH_SORT_OPTIONS[sort]})
                task = source_task(url, sort)
            if task["key"] not in keys:
                tasks.append(task)
                keys.add(task["key"])
    if not tasks:
        raise config_error("输入中没有可采集的目标。")
    return tasks


def fingerprint(cfg: dict, tasks: list[dict]) -> str:
    values = {key: cfg.get(key) for key in ("mode", "entry_mode", "store_max_records", "keyword_max_records",
                                         "product_filters", "include_sponsored", "marketplace_domain", "start_url")}
    values.update(schema=STATE_SCHEMA, tasks=tasks)
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class PanelState:
    def __init__(self, path: Path, plan_hash: str):
        self.path = path
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise config_error("断点无法读取；请保留文件并检查，不会覆盖。") from exc
            if self.data.get("schema") != STATE_SCHEMA or self.data.get("fingerprint") != plan_hash:
                raise config_error("断点属于旧流程或配置/输入已变化；请使用新 job_id。")
        else:
            self.data = {"schema": STATE_SCHEMA, "fingerprint": plan_hash, "sources": {}, "tasks": {},
                         "browser": {}, "current_task": None}

    def save(self) -> None:
        _atomic_write_json(self.path, self.data)

    def budget(self, task: dict, cap: int | None) -> int | None:
        # Count committed snapshots once, never the sum of cumulative exports.
        used = sum(t.get("retained_count", 0) for key, t in self.data["tasks"].items()
                   if t.get("source") == task["source"] and key != task["key"])
        return None if cap is None else max(cap - used, 0)

    def commit(self, task: dict, records: list[dict], report: dict, cap: int | None, reason: str) -> dict:
        remaining = self.budget(task, cap)
        retained = records if remaining is None else records[:remaining]
        payload = {**task, **report, "retained_count": len(retained), "records": retained,
                   "finish_reason": reason, "complete": reason in {"limit_reached", "source_exhausted", "store_no_results"}}
        self.data["tasks"][task["key"]] = payload
        self.data["sources"].setdefault(task["source"], {})["loads_since_export"] = 0
        active = self.data.get("current_task") or {}
        if active.get("key") == task["key"]:
            active.update(loads_since_export=0, load_pending=False)
        self.save()
        return payload


class PluginCrawler:
    def __init__(self, cfg: dict, state: PanelState, bridge: OpenCliBridge, safety: LocalSafetyController,
                 *, now: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.state, self.bridge, self.safety = cfg, state, bridge, safety
        self.now, self.sleep = now, sleep
        self.read_recovery = ReadRecovery(bridge, state.data, state.save, safety, now=now, sleep=sleep)
        self.job_dir = cfg["job_dir"]
        self.export_state_path = safety.storage_root / "plugin-export-state.json"
        self.safety.status_path = self.job_dir / "run_heartbeat.json"

    def wait(self, seconds: float, phase: str = "waiting", detail: str = "") -> None:
        deadline = self.now() + seconds
        while self.now() < deadline:
            self.safety.heartbeat(phase, until=dt.datetime.fromtimestamp(deadline).isoformat(), detail=detail)
            self.sleep(min(2, max(deadline - self.now(), 0)))

    def observation_now(self):
        return self.now() - self.read_recovery.blocked_seconds

    def snapshot(self) -> dict:
        return self.read_recovery.read("panel_snapshot", self._snapshot_once)

    def _snapshot_once(self) -> dict:
        snap = self.bridge.panel()
        if snap.get("signin"):
            raise needs_human("Amazon 弹出了登录页；本工具不使用也不需要 Amazon 买家账号，本条采集已停止。请稍后重试，不要登录买家账号。")
        risk = classify_amazon_risk(http_status=None, title=snap.get("title", ""), body_text=snap.get("amazon_error", ""))
        risk = risk or classify_sellersprite_risk(snap.get("messages", ""))
        if snap.get("captcha"):
            risk = RiskSignal("sellersprite", "captcha_or_robot_check", "卖家精灵要求验证码或机器人验证。")
        if risk:
            self.safety.trip(risk, page_url=snap.get("url", ""))
        if snap.get("guest"):
            raise needs_human("卖家精灵处于游客/未登录状态，请在工作页登录插件后恢复。")
        self.safety.note_risk_checked()
        return snap

    def remote(self, action: str, **kwargs: Any) -> dict:
        self.snapshot()  # Always check risk/URL before waiting and again before clicking.
        self.safety.before_remote_action("plugin:" + action)
        self.snapshot()
        return self.bridge.panel(action, **kwargs)

    def stable(self, *, after_count: int | None = None) -> dict:
        duration = 180  # Background Chrome can delay extension timers; keep waiting without re-clicking.
        deadline = self.observation_now() + duration
        previous, stable_since = None, self.observation_now()
        while self.observation_now() < deadline:
            generation = self.read_recovery.generation
            snap = self.snapshot()
            if generation != self.read_recovery.generation:
                previous, stable_since = None, self.observation_now()
            signature = (snap.get("count"), snap.get("busy"), snap.get("more"), snap.get("amazon_no_results"),
                         tuple(row.get("text", "") for row in snap.get("rows", [])))
            if signature != previous:
                previous, stable_since = signature, self.observation_now()
            if self.cfg["mode"] == "storefront" and snap.get("amazon_no_results") and self.observation_now() - stable_since >= 10:
                return snap
            if snap.get("panel") and snap.get("count") is not None and not snap.get("busy") and self.observation_now() - stable_since >= 10:
                if after_count is None or snap["count"] > after_count or not snap.get("more"):
                    return snap
            self.wait(2, "plugin_wait", "等待插件计数与可观察字段稳定")
        raise retry_later("插件加载无进展或字段未稳定，未将其判为采集结束。")

    def local(self, action: str, **kwargs: Any) -> dict:
        self.snapshot()
        result = self.bridge.panel(action, **kwargs)
        self.wait(0.3, "plugin_wait", action)
        return result

    def prepare(self) -> dict:
        snap = self.snapshot()
        if self.cfg["mode"] == "storefront" and snap.get("amazon_no_results"):
            return self.stable()
        injection_deadline = self.observation_now() + 20
        while snap.get("installed") is False and self.observation_now() < injection_deadline:
            self.wait(2, "plugin_wait", "等待插件注入公开 DOM")
            snap = self.snapshot()
        if not snap.get("panel"):
            self.remote("open")
            snap = self.stable()
            if self.cfg["mode"] == "storefront" and snap.get("amazon_no_results"):
                return snap
        self.local("filter_open")
        self.local("filter_reset")
        self.local("filter_close")
        self.local("select_open", kind="product")
        self.local("select_option", kind="product")
        show = self.local("select_open", kind="show")
        if not show.get("absent"):
            self.local("select_option", kind="show")
        self.local("select_open", kind="badges")
        for _ in range(40):
            if self.local("badges_all").get("ready"):
                break
        else:
            raise needs_human("商品标识范围无法恢复为全部。")
        self.local("select_close", kind="badges")
        self.local("dedup_off")
        for _ in range(3):
            if self.local("clear_selection").get("ready"):
                break
        else:
            raise needs_human("无法清空产品勾选，停止以免只导出部分商品。")
        self.local("columns_open")
        self.local("columns_all")
        self.local("columns_save")
        self.local("export_options_open")
        self.local("export_options_off")
        self.local("export_options_close")
        return self.stable()

    def _read_export_state(self) -> dict:
        try:
            return json.loads(self.export_state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (ValueError, OSError) as exc:
            raise needs_human("导出节流状态无法读取，请检查；不会清零后重新下载。") from exc

    def export(self, task: dict, snapshot: dict) -> tuple[list[dict], dict]:
        # Update the vendor's cached sorted list using its public header, not Vue internals.
        self.local("reset_order")
        snapshot = self.stable()
        export_state = self._read_export_state()
        pending = export_state.get("pending")
        if pending and (pending.get("job") != self.cfg["job_id"] or pending.get("task") != task["key"]):
            raise needs_human("另一个目标的导出结果尚未确认。请先检查 Chrome 下载并用 plugin-export-review 处理，避免重复下载。")
        if not pending:
            self.wait(max(float(export_state.get("next_allowed_at", 0)) - self.now(), 0), detail="导出间隔至少 60 秒")
        # Native product names are Products(N)-US or Search(keyword)-N-US.
        country = {"amazon.com": "US", "amazon.co.uk": "UK", "amazon.co.jp": "JP", "amazon.com.au": "AU", "amazon.com.mx": "MX", "amazon.com.br": "BR"}.get(task["marketplace"], task["marketplace"].split(".")[-1].upper())
        keyword = parse_qs(urlsplit(snapshot["url"]).query).get("k", [task.get("keyword", "")])[0]
        keyword_slug = keyword.replace(" ", "-")
        pattern = (f"Products({snapshot['count']})" if task["source_type"] == "storefront"
                   else f"Search({keyword_slug})-{snapshot['count']}") + f"-{country}"
        if pending and pending.get("plugin_count", snapshot["count"]) != snapshot["count"]:
            raise needs_human("未确认导出后面板数量已变化；先处理 Chrome 下载，再恢复任务。")
        for attempt in range(2):
            if pending:
                started = pending["started_at"]  # Reconcile the original attempt; never click again.
            else:
                self.snapshot()
                self.safety.before_remote_action("plugin:export")
                self.snapshot()
                started = self.now()
                pending = {"started_at": started, "pattern": pattern, "task": task["key"],
                           "job": self.cfg["job_id"], "plugin_count": snapshot["count"]}
                export_state.update(pending=pending, next_allowed_at=started + 60)
                _atomic_write_json(self.export_state_path, export_state)
                self.bridge.panel("export")
            deadline, seen_interrupted = self.observation_now() + 120, None
            while self.observation_now() < deadline:
                self.wait(2, "plugin_wait", "核验下载状态")
                self.snapshot()
                self.safety.heartbeat("plugin_wait", detail="等待本次原生导出下载完成")
                result = pending.get("download") or self.read_recovery.read(
                    "download_status", lambda: self.download_status(pattern, started))
                filename = result.get("filename")
                if not filename or result.get("id") is None:
                    continue
                path = Path(pending.get("raw_file") or filename)
                if result.get("id") in export_state.get("download_ids", []):
                    continue
                if pattern not in Path(filename).name:
                    continue
                origin = urlsplit(snapshot["url"])
                if not str(result.get("url", "")).startswith(f"blob:{origin.scheme}://{origin.netloc}/"):
                    continue
                if result.get("state") == "interrupted" and result.get("id") is not None:
                    seen_interrupted = result
                    break
                if not result.get("downloaded") or result.get("state") != "complete" or not path.is_file() or path.stat().st_mtime < started - 1:
                    continue
                if path.suffix.lower() != ".xlsx":
                    continue
                raw_dir = self.job_dir / "raw_exports"
                raw_dir.mkdir(parents=True, exist_ok=True)
                saved = raw_dir / f"{task['key']}-{int(started)}-{result['id']}.xlsx"
                if path != saved:
                    shutil.copy2(path, saved)
                pending.update(raw_file=str(saved), download=result)
                _atomic_write_json(self.export_state_path, export_state)
                report = {"raw_file": str(saved), "plugin_count": snapshot["count"], "download_id": result["id"]}
                try:
                    rows, parsed_report = parse_export(saved, task["marketplace"])
                    report.update(parsed_report)
                    verify_export(rows, report, snapshot)
                except CrawlStop as exc:
                    report.update(validation="failed", validation_error=str(exc))
                    _atomic_write_json(saved.with_suffix(".json"), report)
                    raise
                report["validation"] = "passed"
                _atomic_write_json(saved.with_suffix(".json"), report)
                timestamp = dt.datetime.fromtimestamp(self.now()).isoformat()
                for row in rows:
                    row.update({key: task.get(key, "") for key in ("source_type", "keyword", "store_url", "store_name", "sort_order")})
                    row.update(page_url=snapshot["url"], scraped_at=timestamp, load_status="ok", collection_method="plugin_export", plugin_fields_status="loaded")
                return rows, report
            if not seen_interrupted:
                raise needs_human("120 秒内未能确认本次下载，保留待确认状态；请检查下载或另存为提示，不会盲目重试。")
            export_state.pop("pending", None)
            pending = None
            _atomic_write_json(self.export_state_path, export_state)
            if attempt == 0:
                self.wait(max(export_state["next_allowed_at"] - self.now(), 0), detail="失败导出冷却后仅重试一次")
        raise retry_later("原生导出明确失败两次，已停止。")

    def download_status(self, pattern, started):
        # Recheck URL, document, login and risk before each download-status retry.
        self._snapshot_once()
        return self.bridge.wait_download(pattern, max(5000, int((self.now() - started + 5) * 1000)))

    def acknowledge_export(self, task: dict, report: dict) -> None:
        ledger = self._read_export_state()
        pending = ledger.get("pending") or {}
        if (pending.get("job") == self.cfg["job_id"] and pending.get("task") == task["key"]
                and (pending.get("download") or {}).get("id") == report.get("download_id")):
            ledger["download_ids"] = (ledger.get("download_ids", []) + [report["download_id"]])[-200:]
            ledger.pop("pending", None)
            _atomic_write_json(self.export_state_path, ledger)

    def cap(self, task: dict) -> int | None:
        return self.cfg["store_max_records" if task["source_type"] == "storefront" else "keyword_max_records"]

    def skip_missing_store(self, task: dict, snap: dict) -> bool:
        if task["source_type"] != "storefront" or not snap.get("amazon_no_results"):
            return False
        previous = self.state.data["tasks"].get(task["key"], {})
        report = {k: v for k, v in previous.items() if k != "records"}
        report.update(skipped=True, skip_reason="Amazon 店铺商品页明确显示无搜索结果（店铺消失或暂无可售商品）。")
        self.state.commit(task, previous.get("records", []), report, self.cap(task), "store_no_results")
        skipped = self.state.data.setdefault("skipped_items", [])
        if not any(item.get("key") == task["key"] for item in skipped):
            skipped.append({**task, "reason": "store_no_results", "message": report["skip_reason"]})
        self.state.data["current_task"] = None
        self.state.save()
        self.materialize()
        print(f"跳过 {task.get('store_name') or task['source']}：{report['skip_reason']}", flush=True)
        return True

    def run_task(self, task: dict, *, prepared: bool = False) -> None:
        self.safety.set_work_key(task["key"])
        cap = self.cap(task)
        remaining = self.state.budget(task, cap)
        if remaining == 0:
            return
        active = self.state.data.get("current_task") or {}
        loads = self.state.data["sources"].get(task["source"], {}).get("loads_since_export",
                    active.get("loads_since_export", 0) if active.get("key") == task["key"] else 0)
        snap = self.stable() if prepared else self.prepare()
        if self.skip_missing_store(task, snap):
            return
        if prepared and active.get("load_pending") and snap["count"] > active.get("plugin_count", 0):
            loads += 1
        if prepared and snap["count"] < active.get("plugin_count", 0):
            raise needs_human("恢复页条数回退；请重新核对筛选或刷新工作页后恢复，以新快照替换旧快照。")
        while True:
            self.state.data["sources"].setdefault(task["source"], {})["loads_since_export"] = loads
            self.state.data["current_task"] = {**task, "loads_since_export": loads,
                                               "plugin_count": snap["count"], "document_id": self.bridge.document_id}
            self.state.save()
            reason = "limit_reached" if remaining is not None and snap["count"] >= remaining else ""
            if not reason and not snap.get("more") and snap.get("more_count", 0) == 0:
                if snap["count"] > 0 or snap.get("empty"):
                    reason = "source_exhausted"
            if reason or loads >= 100:
                if snap["count"] == 0:
                    rows, report = [], {"plugin_count": 0, "exported_count": 0, "raw_file": ""}
                else:
                    rows, report = self.export(task, snap)
                self.state.commit(task, rows, report, cap, reason or "checkpoint")
                self.acknowledge_export(task, report)
                self.materialize()
                self.safety.complete_review_success()
                loads = 0
                if reason:
                    self.state.data["current_task"] = None
                    self.state.save()
                    return
            before = snap["count"]
            self.state.data["current_task"]["load_pending"] = True
            self.state.save()
            self.remote("load")
            try:
                snap = self.stable(after_count=before)
            except CrawlStop as exc:
                if exc.exit_code != 20 or isinstance(exc, BridgeReadRecoveryExhausted):
                    raise
                schedule = [60] if self.cfg["operation_mode"] == "supervised" else [120, 300]
                for delay in schedule:
                    self.wait(delay, "retry_wait", "加载无进展后复查")
                    current = self.snapshot()
                    if current.get("busy"):
                        continue  # Do not double-click a still-running request.
                    if current.get("count", 0) > before or not current.get("more"):
                        snap = self.stable(after_count=before)
                        break
                    self.remote("load")
                    try:
                        snap = self.stable(after_count=before)
                        break
                    except CrawlStop as retry_error:
                        if retry_error.exit_code != 20 or isinstance(retry_error, BridgeReadRecoveryExhausted):
                            raise
                else:
                    raise exc
            if self.skip_missing_store(task, snap):
                return
            if snap["count"] < before:
                raise needs_human("插件条数回退，可能被手动刷新或更改筛选，停止以免混写。")
            loads += 1
            self.state.data["sources"].setdefault(task["source"], {})["loads_since_export"] = loads
            self.state.data["current_task"].update(loads_since_export=loads, plugin_count=snap["count"], load_pending=False)
            self.state.save()

    def materialize(self) -> None:
        tasks = list(self.state.data["tasks"].values())
        records = [row for task in tasks for row in task.get("records", [])]
        reports = [{key: value for key, value in task.items() if key != "records"} for task in tasks]
        quality = write_outputs(self.job_dir, records, reports, self.cfg["product_filters"], self.cfg["include_sponsored"])
        quality["unverified_exports"] = []
        for sidecar in sorted((self.job_dir / "raw_exports").glob("*.json")):
            report = json.loads(sidecar.read_text(encoding="utf-8"))
            if report.get("validation") == "failed":
                quality["unverified_exports"].append(report)
        _atomic_write_json(self.job_dir / "quality_report.json", quality)
        _atomic_write_json(self.job_dir / "run_summary.json", {**quality, "collection_method": "plugin_export",
                                                       "skipped_items": self.state.data.get("skipped_items", [])})


def connect_work_page(crawler: PluginCrawler) -> dict:
    saved = crawler.state.data.get("browser") or {}
    if saved.get("target"):
        crawler.bridge.target = saved["target"]
        page = crawler.read_recovery.read("target", crawler.bridge.validate_target)
        if canonical_url(page["url"]) != saved.get("url"):
            raise needs_human("原工作页网址已被修改，停止操作。")
    else:
        page = crawler.bridge.bind()
    source_identity(page["url"])
    crawler.bridge.expected_url = canonical_url(page["url"])
    crawler.bridge.document_id = saved.get("document_id", "")
    # Persist the lease before the first snapshot can time out.
    crawler.state.data["browser"] = {"session": crawler.bridge.session, "target": crawler.bridge.target,
                                      "url": crawler.bridge.expected_url,
                                      "document_id": crawler.bridge.document_id}
    crawler.state.save()
    doc = crawler.snapshot().get("document_id", "")
    active = crawler.state.data.get("current_task") or {}
    if doc and doc == active.get("document_id"):
        crawler.bridge.document_id = doc
    else:
        doc = uuid.uuid4().hex
        crawler.bridge.panel("mark", id=doc)
        crawler.bridge.document_id = doc
        crawler.state.data["current_task"] = None
    crawler.state.data["browser"] = {"session": crawler.bridge.session, "target": crawler.bridge.target,
                                      "url": crawler.bridge.expected_url, "document_id": doc}
    crawler.state.save()
    return page


def run(cfg: dict, tasks: list[dict], *, resume_after_review: bool = False, rebind: bool = False,
        check_only: bool = False) -> int:
    job_dir = cfg["job_dir"]
    state = PanelState(job_dir / "state.json", fingerprint(cfg, tasks))
    job_dir.mkdir(parents=True, exist_ok=True)
    mode = cfg["operation_mode"]
    safety = LocalSafetyController(mode=mode, traffic_profile="plugin")
    safety.job_label = cfg["job_id"]
    outcome = completed_outcome(0)
    crawler = None
    try:
        safety.acquire()
        safety.begin(resume_after_review=resume_after_review)
        if rebind:
            state.data.pop(ReadRecovery.KEY, None)
            state.data["browser"] = {}
            state.data["current_task"] = None
        if state.data.get("finished") and not check_only:
            count = len(state.data.get("skipped_items", []))
            if count:
                outcome = replace(completed_outcome(count), message=f"任务完成，{count} 个无搜索结果的店铺已跳过。",
                                  next_action="交付已采集表格，并说明 skipped_items 中无搜索结果的店铺。")
            return outcome.exit_code
        session = state.data.get("browser", {}).get("session") or "lc-panel-" + uuid.uuid4().hex[:12]
        bridge = OpenCliBridge(session)
        crawler = PluginCrawler(cfg, state, bridge, safety)
        for committed in state.data["tasks"].values():
            if committed.get("download_id") is not None:
                crawler.acknowledge_export(committed, committed)
        page = connect_work_page(crawler)
        current = source_task(page["url"])
        if cfg["entry_mode"] == "current_tab":
            if current["source_type"] != cfg["mode"]:
                raise config_error("绑定页面类型与 mode 不符。")
            if cfg.get("start_url") and source_identity(cfg["start_url"]) != source_identity(page["url"]):
                raise config_error("当前标签与 start_url 指定的目标不一致，未执行点击。")
            saved_source = state.data.get("bound_source")
            if saved_source and saved_source != current["source"]:
                raise config_error("恢复时的当前标签不是原来源；请打开原来源或使用新 job_id。")
            state.data["bound_source"] = current["source"]
            tasks = [current]
        if check_only:
            snap = crawler.snapshot()
            print(json.dumps({key: snap.get(key) for key in ("url", "panel", "count", "busy", "more")}, ensure_ascii=False))
            if not snap.get("panel"):
                raise needs_human("请在原工作页打开卖家精灵产品查询面板。")
            return 0
        for task in tasks:
            if state.data["tasks"].get(task["key"], {}).get("complete") or crawler.state.budget(task, crawler.cap(task)) == 0:
                continue
            active = state.data.get("current_task") or {}
            continuing = active.get("key") == task["key"] and active.get("document_id") == bridge.document_id
            if cfg["entry_mode"] == "batch" and not continuing and bridge.expected_url != task["url"]:
                safety.set_work_key(task["key"])
                crawler.snapshot()
                safety.before_remote_action("plugin:navigate")
                crawler.snapshot()
                bridge.navigate(task["url"])
                crawler.wait(2, "plugin_wait", "等待工作页导航")
                deadline = crawler.observation_now() + 90
                while True:
                    snap = crawler.snapshot()
                    try:
                        matched = source_identity(snap["url"]) == source_identity(task["url"])
                    except CrawlStop:
                        matched = False
                    if matched:
                        break
                    if crawler.observation_now() >= deadline:
                        raise retry_later("工作页导航未到达指定目标。")
                    crawler.wait(2, "plugin_wait")
                bridge.expected_url = canonical_url(snap["url"])
                doc = uuid.uuid4().hex
                bridge.panel("mark", id=doc)
                bridge.document_id = doc
                state.data["browser"].update(url=bridge.expected_url, document_id=doc)
                state.save()
            crawler.run_task(task, prepared=continuing)
        crawler.materialize()
        state.data["finished"] = True
        state.save()
        skipped_count = len(state.data.get("skipped_items", []))
        if skipped_count:
            outcome = replace(completed_outcome(skipped_count), message=f"任务完成，{skipped_count} 个无搜索结果的店铺已跳过。",
                              next_action="交付已采集表格，并说明 skipped_items 中无搜索结果的店铺；同一 job_id 不重复采集已跳过目标。")
    except KeyboardInterrupt:
        outcome = classify_exception(retry_later("用户中断，已提交的导出与断点已保留。"))
    except Exception as exc:
        outcome = classify_exception(exc)
        pause = safety._load_pause()
        if outcome.status == "risk_pause" and pause and pause.get("reason") == "captcha_or_robot_check":
            outcome = replace(outcome, next_action="验证码暂停，默认 24 小时；用户确认本次验证已通过后，可立即用原命令加 --resume-after-review 提前复核恢复。仍有验证码则停止。")
    finally:
        if crawler and outcome.exit_code and not check_only:
            # Preserve a useful partial workbook; never perform browser actions in cleanup.
            try:
                crawler.materialize()
            except Exception:
                pass
        if safety._lock_handle is not None:
            if crawler and not check_only:
                summary_path = job_dir / "run_summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
                summary["partial"] = outcome.exit_code not in (0, 10)
                summary["current_target"] = state.data.get("current_task")
                _atomic_write_json(summary_path, summary)
            state.save()
            if not check_only:
                finalize_run(job_dir, outcome)
        safety.fail_review()
        safety.release()
    print(f"{outcome.status}: {outcome.message}", flush=True)
    return outcome.exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--rebind", action="store_true", help="用户选好新工作页后，显式重新绑定；重采未完成目标")
    parser.add_argument("--operation-mode", choices=("supervised", "unattended"))
    parser.add_argument("--resume-after-review", action="store_true")
    args = parser.parse_args(argv)
    cfg = None
    try:
        path = Path(args.config).expanduser().resolve()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise config_error("配置文件必须是 JSON 对象。")
        if args.operation_mode:
            raw["operation_mode"] = args.operation_mode
        cfg = validate_config(raw, Path(__file__).resolve().parent.parent)
        tasks = build_tasks(cfg)
        if (args.no_resume or raw.get("resume") is False) and (cfg["job_dir"] / "state.json").exists():
            raise config_error("不覆盖已有任务，请为重新采集使用新 job_id。")
        PanelState(cfg["job_dir"] / "state.json", fingerprint(cfg, tasks))
        if args.dry_run:
            cli_command()
            print(json.dumps({"valid": True, "backend": "opencli", "entry_mode": cfg["entry_mode"],
                              "store_max_records": cfg["store_max_records"] or "all",
                              "keyword_max_records": cfg["keyword_max_records"] or "all",
                              "targets": len(tasks), "job_dir": str(cfg["job_dir"])}, ensure_ascii=False))
            return 0
        start_new_run()
        return run(cfg, tasks, resume_after_review=args.resume_after_review, rebind=args.rebind, check_only=args.check_only)
    except Exception as exc:
        outcome = classify_exception(exc)
        print(f"{outcome.status}: {outcome.message}", file=sys.stderr)
        return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
