#!/usr/bin/env python3
"""Check SellerSprite readiness on the first real target without writing crawl data.

Prints one JSON report and exits with the shared run_outcome codes:
0 ready, 20 data still loading / page temporarily unavailable, 21 risk pause,
30 needs a human (no browser, plugin missing, login, verification),
40 config error, 50 another crawl holds the lock, 2 unexpected error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from selenium.common.exceptions import TimeoutException, WebDriverException

from amazon_category_rank_crawler import (
    DeliveryLocationUnconfirmedError,
    UserFacingError,
    VerificationUnconfirmedError,
    build_runtime_config,
    get_sellersprite_readiness,
    load_json,
    open_amazon_page,
    safe_sellersprite_readiness,
    start_driver,
    wait_for_amazon_products,
    wait_for_sellersprite_data,
)
from amazon_front_crawler import (
    NEXT_ACTION_BROWSER,
    NEXT_ACTION_SELLERSPRITE_ABSENT,
    NEXT_ACTION_SELLERSPRITE_LOGIN,
    NEXT_ACTION_SELLERSPRITE_VERIFY,
    build_front_runtime_config,
    build_initial_queue,
    prepare_storefront_page,
    storefront_landing_url,
    wait_for_storefront_plugin_page,
)
from amazon_image_competitor_crawler import (
    build_image_runtime_config,
    load_products,
)
from amazon_page_recovery import TransientAmazonPageUnavailable
import run_outcome
from safety_control import LocalSafetyController, SafetyPausedError


# status -> (exit code, next action)
CHECK_STATUS = {
    "ready": (run_outcome.EXIT_COMPLETED, "卖家精灵数据正常，可以开始正式运行。"),
    "data_loading": (
        run_outcome.EXIT_RETRY_LATER,
        "插件已注入但字段还没稳定显示：稍等 1–2 分钟再运行一次 sellersprite-check。",
    ),
    "timeout": (
        run_outcome.EXIT_RETRY_LATER,
        "插件已注入但字段还没稳定显示：稍等 1–2 分钟再运行一次 sellersprite-check。",
    ),
    "ready_candidate": (
        run_outcome.EXIT_RETRY_LATER,
        "插件已注入但字段还没稳定显示：稍等 1–2 分钟再运行一次 sellersprite-check。",
    ),
    "page_unavailable": (
        run_outcome.EXIT_RETRY_LATER,
        "Amazon 页面暂时打不开：稍后重新运行 sellersprite-check。",
    ),
    "plugin_absent": (run_outcome.EXIT_NEEDS_HUMAN, NEXT_ACTION_SELLERSPRITE_ABSENT),
    "login_required": (run_outcome.EXIT_NEEDS_HUMAN, NEXT_ACTION_SELLERSPRITE_LOGIN),
    "blocked": (run_outcome.EXIT_NEEDS_HUMAN, NEXT_ACTION_SELLERSPRITE_VERIFY),
    "browser_unreachable": (run_outcome.EXIT_NEEDS_HUMAN, NEXT_ACTION_BROWSER),
    "config_error": (run_outcome.EXIT_CONFIG_ERROR, run_outcome.DEFAULT_NEXT_ACTION["config_error"]),
    "risk_pause": (run_outcome.EXIT_RISK_PAUSE, run_outcome.DEFAULT_NEXT_ACTION["risk_pause"]),
    "lock_held": (run_outcome.EXIT_LOCK_HELD, run_outcome.DEFAULT_NEXT_ACTION["lock_held"]),
    "error": (run_outcome.EXIT_UNEXPECTED, run_outcome.DEFAULT_NEXT_ACTION["error"]),
}


def resolve_check_target(raw: Dict[str, Any], config_path: Path) -> Tuple[Any, str, Dict[str, Any]]:
    if "products_file" in raw or "result_mode" in raw:
        runtime = build_image_runtime_config(raw, no_resume=False)
        runtime.sellersprite_required = True
        products = load_products(runtime.products_file, runtime.marketplace_domain)
        if not products:
            raise UserFacingError("以图搜图输入表没有可用商品，无法检查卖家精灵页面数据。")
        current = products[0]
        url = str(current.get("source_product_url") or "")
        if not url:
            raise UserFacingError(
                "首条以图搜图输入没有 ASIN 或商品URL，无法检查卖家精灵页面数据。"
            )
        return runtime, url, current

    if str(raw.get("mode") or "").lower() in {"keyword_search", "storefront", "bsr_category"}:
        runtime = build_front_runtime_config(raw, no_resume=False)
        if runtime.mode == "bsr_category":
            # bsr has no front queue; its first target is the start URL.
            return runtime, runtime.start_url, {"page_url": runtime.start_url, "source_type": "bsr_category"}
        queue = build_initial_queue(runtime)
        if not queue:
            raise UserFacingError("配置没有可用于卖家精灵检查的目标页面。")
        current = queue[0]
        return runtime, storefront_landing_url(current), current

    runtime = build_runtime_config(raw, config_path, no_resume=False)
    return runtime, runtime.start_url, {"page_url": runtime.start_url}


def exit_code_for_status(status: str) -> int:
    return CHECK_STATUS.get(status, CHECK_STATUS["error"])[0]


def emit_report(status: str, report: Optional[Dict[str, Any]] = None, *, message: str = "") -> int:
    exit_code, next_action = CHECK_STATUS.get(status, CHECK_STATUS["error"])
    payload = dict(report or {})
    payload["status"] = status
    payload["exit_code"] = exit_code
    payload["next_action"] = next_action
    pending = payload.get("pending_asins") or {}
    if status == "timeout" and pending and all(reason == "plugin_box_missing" for reason in pending.values()):
        payload["next_action"] = "未找到逐商品插件卡片；检查商品信息展示与视口加载，再运行预检。插件字段门禁保持启用。"
    if message:
        payload["message"] = message
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check CDP, Chrome profile and SellerSprite data readiness."
    )
    parser.add_argument("--config", required=True, help="抓取配置文件")
    args = parser.parse_args(argv)

    try:
        config_path = Path(args.config).expanduser().resolve()
        raw = load_json(config_path)
        if not isinstance(raw, dict):
            raise UserFacingError("配置文件必须是 JSON 对象。")
        runtime, target_url, current = resolve_check_target(raw, config_path)
    except (UserFacingError, OSError, ValueError, TypeError) as exc:
        return emit_report("config_error", message=str(exc))

    driver = None
    final_status = "error"
    safety = LocalSafetyController(mode=str(getattr(runtime, "operation_mode", "supervised") or "supervised"))
    safety.job_label = "sellersprite-check"
    try:
        safety.acquire()
        safety.begin()
        setattr(runtime, "safety", safety)
        try:
            driver = start_driver(runtime)
        except (UserFacingError, WebDriverException) as exc:
            final_status = "browser_unreachable"
            return emit_report(final_status, message=str(exc))
        open_amazon_page(driver, target_url, runtime)
        if getattr(runtime, "mode", "") == "storefront":
            prepare_storefront_page(driver, runtime, current)
        try:
            wait_for_amazon_products(driver, runtime)
        except TimeoutException:
            pass
        if getattr(runtime, "mode", "") == "storefront":
            plugin_status = wait_for_storefront_plugin_page(
                driver, runtime, time.monotonic() + runtime.plugin_timeout
            )
        else:
            plugin_status = wait_for_sellersprite_data(driver, runtime)
        full_report = get_sellersprite_readiness(driver)
        report = safe_sellersprite_readiness(full_report)
        if getattr(runtime, "mode", "") == "storefront":
            report["pending_asins"] = full_report.get("pending_asins", {})
        final_status = str(report.get("status") or plugin_status)
        if final_status == "ok":
            final_status = "ready"
        return emit_report(final_status, report)
    except SafetyPausedError as exc:
        outcome = run_outcome.classify_exception(exc)
        final_status = outcome.status if outcome.status in CHECK_STATUS else "error"
        report = {"resume_at": outcome.resume_at} if outcome.resume_at else {}
        return emit_report(final_status, report, message=str(exc))
    except (VerificationUnconfirmedError, DeliveryLocationUnconfirmedError) as exc:
        final_status = "blocked"
        return emit_report(final_status, message=str(exc))
    except (TransientAmazonPageUnavailable, TimeoutException, WebDriverException) as exc:
        final_status = "page_unavailable"
        return emit_report(final_status, message=str(exc))
    except UserFacingError as exc:
        final_status = "error"
        return emit_report(final_status, message=str(exc))
    finally:
        if driver is not None:
            try:
                if final_status != "ready" and hasattr(driver, "detach"):
                    driver.detach()
                else:
                    driver.quit()
            except WebDriverException:
                pass
        safety.release()


if __name__ == "__main__":
    raise SystemExit(main())
