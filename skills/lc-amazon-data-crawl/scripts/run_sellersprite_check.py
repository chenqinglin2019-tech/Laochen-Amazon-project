#!/usr/bin/env python3
"""Check SellerSprite readiness on the first real target without writing crawl data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from selenium.common.exceptions import TimeoutException, WebDriverException

from amazon_category_rank_crawler import (
    UserFacingError,
    build_runtime_config,
    get_sellersprite_readiness,
    load_json,
    safe_sellersprite_readiness,
    start_driver,
    wait_for_amazon_products,
    wait_for_sellersprite_data,
)
from amazon_front_crawler import (
    build_front_runtime_config,
    build_initial_queue,
    prepare_storefront_page,
)
from amazon_image_competitor_crawler import (
    build_image_runtime_config,
    load_products,
)


def resolve_check_target(raw: Dict[str, Any], config_path: Path) -> Tuple[Any, str, Dict[str, Any]]:
    if "products_file" in raw or "result_mode" in raw:
        runtime = build_image_runtime_config(raw, no_resume=False)
        runtime.sellersprite_required = True
        products = load_products(runtime.products_file, runtime.marketplace_domain)
        current = products[0]
        url = str(current.get("source_product_url") or "")
        if not url:
            raise UserFacingError(
                "首条以图搜图输入没有 ASIN 或商品URL，无法检查卖家精灵页面数据。"
            )
        return runtime, url, current

    if str(raw.get("mode") or "").lower() in {"keyword_search", "storefront", "bsr_category"}:
        runtime = build_front_runtime_config(raw, no_resume=False)
        queue = build_initial_queue(runtime)
        if not queue:
            raise UserFacingError("配置没有可用于卖家精灵检查的目标页面。")
        current = queue[0]
        return runtime, str(current.get("page_url") or ""), current

    runtime = build_runtime_config(raw, config_path, no_resume=False)
    return runtime, runtime.start_url, {"page_url": runtime.start_url}


def exit_code_for_status(status: str) -> int:
    return {
        "ready": 0,
        "plugin_absent": 3,
        "login_required": 4,
        "data_loading": 5,
        "blocked": 6,
    }.get(status, 7)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check CDP, Chrome profile and SellerSprite data readiness."
    )
    parser.add_argument("--config", required=True, help="抓取配置文件")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    raw = load_json(config_path)
    runtime, target_url, current = resolve_check_target(raw, config_path)
    driver = None
    final_status = "browser_unreachable"
    try:
        driver = start_driver(runtime)
        driver.get(target_url)
        if getattr(runtime, "mode", "") == "storefront":
            prepare_storefront_page(driver, runtime, current)
        try:
            wait_for_amazon_products(driver, runtime)
        except TimeoutException:
            pass
        plugin_status = wait_for_sellersprite_data(driver, runtime)
        report = safe_sellersprite_readiness(get_sellersprite_readiness(driver))
        final_status = str(report.get("status") or plugin_status)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return exit_code_for_status(final_status)
    except (UserFacingError, WebDriverException) as exc:
        report = {
            "status": "browser_unreachable",
            "message": str(exc),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    finally:
        if driver is not None:
            try:
                if final_status != "ready" and hasattr(driver, "detach"):
                    driver.detach()
                else:
                    driver.quit()
            except WebDriverException:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
