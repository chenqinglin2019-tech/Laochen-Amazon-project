"""Migrate only crawler traffic/wait settings in an existing runner."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


CONFIG_NAMES = (
    "amazon_front_keyword_search.json",
    "amazon_front_bsr_category.json",
    "amazon_front_storefront.json",
    "amazon_front_crawler.json",
    "category_rank_crawler.json",
    "amazon_image_competitors.json",
)


def migrate(path: Path) -> bool:
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    config = json.loads(original)
    if not isinstance(config, dict):
        raise ValueError(f"配置必须是 JSON 对象：{path}")
    mode = config.get("operation_mode", "supervised")
    if mode not in ("supervised", "unattended"):
        raise ValueError(f"operation_mode 无效：{path}")
    config["operation_mode"] = mode
    config.update(
        delay_seconds_min=20 if mode == "supervised" else 45,
        delay_seconds_max=30 if mode == "supervised" else 75,
        batch_pause_pages_min=20 if mode == "supervised" else 10,
        batch_pause_pages_max=20 if mode == "supervised" else 10,
        batch_pause_seconds_min=180 if mode == "supervised" else 900,
        batch_pause_seconds_max=300 if mode == "supervised" else 1200,
        manual_pause_timeout=900 if mode == "supervised" else 0,
        page_timeout=90,
        page_scroll_max_rounds=18,
        page_scroll_stable_rounds=2,
        amazon_page_unavailable_retry_schedule_seconds=(
            [[60, 60]] if mode == "supervised" else [[120, 120], [300, 300]]
        ),
    )
    image = "find_similar_timeout" in config or path.name == "amazon_image_competitors.json"
    if image:
        if mode == "supervised":
            config.update(find_similar_timeout=20, lens_results_timeout=40, plugin_timeout=20, page_scroll_wait_seconds=2.0)
        else:
            config.update(find_similar_timeout=12, lens_results_timeout=60, plugin_timeout=180, page_scroll_wait_seconds=1.0)
    else:
        config["plugin_timeout"] = 40 if mode == "supervised" else 180
        if config.get("mode") == "storefront":
            config["storefront_plugin_stable_seconds"] = 10.0
        if mode == "supervised":
            config["page_scroll_wait_seconds"] = 2.0
        else:
            config["page_scroll_wait_seconds"] = 1.0
    updated = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    if json.loads(original) == config:
        return False
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, path.stat().st_mode & 0o777)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated)
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
    return True


if __name__ == "__main__":
    root = Path(sys.argv[1])
    for path in sorted(root.glob("*.json")):
        if path.name in CONFIG_NAMES:
            migrate(path)
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and "batch_pause_pages_min" in value and any(
            key in value for key in ("mode", "find_similar_timeout", "root_categories")
        ):
            migrate(path)
