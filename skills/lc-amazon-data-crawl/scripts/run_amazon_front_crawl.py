#!/usr/bin/env python3
"""
Local launcher for the unified Amazon front crawler.

Usage:
  python scripts/run_amazon_front_crawl.py
  python scripts/run_amazon_front_crawl.py --config config/amazon_front_crawler.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT_DIR / "config" / "amazon_front_crawler.json"
CRAWLER = ROOT_DIR / "scripts" / "amazon_front_crawler.py"
VENV_PYTHONS = (
    ROOT_DIR / ".venv-scrapling" / "bin" / "python",
    ROOT_DIR / ".venv" / "bin" / "python",
)


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
    for candidate in VENV_PYTHONS:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def build_command(
    config_path: Path,
    dry_run: bool,
    no_resume: bool,
    resume_after_review: bool = False,
    operation_mode: str = "",
) -> List[str]:
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
    if resume_after_review:
        command.append("--resume-after-review")
    if operation_mode:
        command.extend(("--operation-mode", operation_mode))
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the unified Amazon front crawler from a local config file.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="本地配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只检查配置，不打开浏览器")
    parser.add_argument("--no-resume", action="store_true", help="忽略已有断点，重新开始任务")
    parser.add_argument("--operation-mode", choices=("supervised", "unattended"))
    parser.add_argument(
        "--resume-after-review",
        action="store_true",
        help="风险暂停到期且已人工复核后，尝试恢复原待处理页面一次",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = ROOT_DIR / config_path
    load_json(config_path)
    command = build_command(
        config_path,
        args.dry_run,
        args.no_resume,
        args.resume_after_review,
        args.operation_mode or "",
    )
    print(f"配置文件：{config_path}")
    completed = subprocess.run(command, cwd=str(ROOT_DIR))
    return int(completed.returncode)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LauncherError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(2)
