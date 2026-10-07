#!/usr/bin/env python3
"""Build a distributable zip of this skill.

  python3 scripts/package_skill.py [--output PATH] [--allow-token]

Excludes caches, VCS data, macOS metadata, local credentials, crawl outputs,
browser profiles and runner/venv folders. Refuses to package when config.json
carries a non-empty backend_token (or a Doubao credential file has an api_key)
unless --allow-token is given. Secret values are never printed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import sys
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


SKILL_DIR = Path(__file__).resolve().parent.parent
ARCHIVE_ROOT = "lc-amazon-data-crawl"

EXCLUDED_DIR_NAMES = {
    "__pycache__",
    "__MACOSX",
    ".git",
    ".claude",
    ".skill-opt",
    ".venv",
    ".venv-scrapling",
    "outputs",
    "chrome_profiles",
    "lc-amazon-data-crawl-runner",
    "node_modules",
}
EXCLUDED_FILE_PATTERNS = (
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "._*",
    "config.local.json",
    ".config.local.*",
    "*.zip",
)
# Real (non-example) Doubao credential files must never ship with a key.
DOUBAO_CREDENTIAL_NAMES = ("doubao_embedding_vision.json", "doubao_same_product_mini.json")


class PackageError(RuntimeError):
    pass


def is_excluded(relative: Path) -> bool:
    if any(part in EXCLUDED_DIR_NAMES for part in relative.parts[:-1]):
        return True
    name = relative.name
    if name in EXCLUDED_DIR_NAMES:
        return True
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in EXCLUDED_FILE_PATTERNS)


def iter_package_files(skill_dir: Path, output: Optional[Path] = None) -> List[Path]:
    files: List[Path] = []
    resolved_output = output.resolve() if output else None
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(skill_dir)
        if is_excluded(relative):
            continue
        if resolved_output is not None and path.resolve() == resolved_output:
            continue
        files.append(relative)
    return files


def _non_empty_field(path: Path, field: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and bool(str(payload.get(field) or "").strip())


def secret_findings(skill_dir: Path, files: Iterable[Path]) -> List[str]:
    findings: List[str] = []
    config = skill_dir / "config.json"
    if not config.is_file():
        raise PackageError("缺少 config.json；发布包必须包含空令牌的 config.json。")
    if _non_empty_field(config, "backend_token"):
        findings.append("config.json: token present")
    for relative in files:
        if relative.name in DOUBAO_CREDENTIAL_NAMES and _non_empty_field(skill_dir / relative, "api_key"):
            findings.append(f"{relative.as_posix()}: api_key present")
    return findings


def build_package(
    skill_dir: Path,
    output: Path,
    allow_token: bool = False,
) -> List[Path]:
    files = iter_package_files(skill_dir, output)
    findings = secret_findings(skill_dir, files)
    if findings and not allow_token:
        raise PackageError(
            "拒绝打包，发现凭据（不显示其值）：" + "; ".join(findings)
            + "。请清空后重试，或确认要分发时加 --allow-token。"
        )
    if output.exists():
        # Existing archives (including the original upload) are never replaced.
        raise PackageError(f"输出文件已存在，未覆盖：{output}。请换一个 --output 文件名。")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in files:
            archive.write(skill_dir / relative, f"{ARCHIVE_ROOT}/{relative.as_posix()}")
    temporary.replace(output)
    return files


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="打包 lc-amazon-data-crawl Skill 发布 zip。")
    parser.add_argument(
        "--output",
        default=str(SKILL_DIR.parent / f"{ARCHIVE_ROOT}-{dt.date.today():%Y%m%d}.zip"),
        help="输出 zip 路径（默认 Skill 目录旁边的带日期文件名；已存在的文件不会被覆盖）",
    )
    parser.add_argument(
        "--allow-token",
        action="store_true",
        help="明确允许打包带令牌/密钥的配置（仅限私下分发给本人）",
    )
    parser.add_argument("--skill-dir", default=str(SKILL_DIR), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    skill_dir = Path(args.skill_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    try:
        files = build_package(skill_dir, output, allow_token=args.allow_token)
    except PackageError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"已生成 {output}（{len(files)} 个文件）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
