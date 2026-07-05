#!/usr/bin/env python3
"""
Local launcher for the Amazon image-search competitor crawler.

Usage:
  python scripts/run_amazon_image_competitor_crawl.py
  python scripts/run_amazon_image_competitor_crawl.py --config config/amazon_image_competitors.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT_DIR / "config" / "amazon_image_competitors.json"
CRAWLER = ROOT_DIR / "scripts" / "amazon_image_competitor_crawler.py"
VENV_PYTHON = ROOT_DIR / ".venv" / "bin" / "python"


class LauncherError(RuntimeError):
    pass


def load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LauncherError(f"没有找到配置文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise LauncherError(f"配置文件不是有效的 JSON：{path}") from exc


def pick_python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def build_command(config_path: Path, dry_run: bool, no_resume: bool) -> List[str]:
    command = [
        pick_python(),
        "-u",
        str(CRAWLER),
        "--config",
        str(config_path),
    ]
    if dry_run:
        command.append("--dry-run")
    if no_resume:
        command.append("--no-resume")
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Amazon image-search competitor crawler from a local config file.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="本地配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只检查配置，不打开浏览器")
    parser.add_argument("--no-resume", action="store_true", help="忽略已有断点，重新开始任务")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = ROOT_DIR / config_path
    load_json(config_path)
    command = build_command(config_path, args.dry_run, args.no_resume)
    print(f"配置文件：{config_path}")
    completed = subprocess.run(command, cwd=str(ROOT_DIR))
    return int(completed.returncode)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LauncherError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(2)
