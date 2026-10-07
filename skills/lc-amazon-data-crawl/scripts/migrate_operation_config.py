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


# Traffic/wait keys are decided by operation_mode at runtime
# (safety_control.apply_operation_policy) and plugin retry/relaunch keys only fed
# unreachable code.  Keeping them in configs suggested they were tunable, so
# setup removes them; everything else (business settings) is left untouched.
POLICY_CONTROLLED_KEYS = (
    "page_timeout",
    "plugin_timeout",
    "page_scroll_max_rounds",
    "page_scroll_wait_seconds",
    "page_scroll_stable_rounds",
    "manual_pause_timeout",
    "delay_seconds_min",
    "delay_seconds_max",
    "batch_pause_pages_min",
    "batch_pause_pages_max",
    "batch_pause_seconds_min",
    "batch_pause_seconds_max",
    "amazon_page_unavailable_retry_schedule_seconds",
    "storefront_plugin_stable_seconds",
    "find_similar_timeout",
    "lens_results_timeout",
    "plugin_retry_attempts",
    "plugin_retry_wait_seconds_min",
    "plugin_retry_wait_seconds_max",
    "plugin_relaunch_retry_attempts",
    "plugin_relaunch_wait_seconds",
    "plugin_second_relaunch_retry_attempts",
    "plugin_second_relaunch_wait_seconds",
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
    for key in POLICY_CONTROLLED_KEYS:
        config.pop(key, None)
    updated = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    if json.loads(original) == config:
        return False
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        if hasattr(os, "fchmod"):  # absent on Windows before Python 3.13
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
        if isinstance(value, dict) and any(key in value for key in POLICY_CONTROLLED_KEYS) and any(
            key in value for key in ("mode", "find_similar_timeout", "root_categories")
        ):
            migrate(path)
