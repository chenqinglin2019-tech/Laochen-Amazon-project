#!/usr/bin/env python3
"""Build a clean distributable zip of this skill (standard library only).

Generates a blank config.json; never copies local credentials, caches, transaction folders,
macOS metadata or the in-skill user template file (the user library lives in the
per-user data directory). Tests are excluded unless --with-tests. Auth binaries
are verified against references/auth-binaries.json before packaging.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "lc-amazon-image-studio"
PLATFORM_BINARIES = {"mac": ("lc-auth-check-darwin-amd64", "lc-auth-check-darwin-arm64"),
                     "win": ("lc-auth-check-windows-amd64.exe",), "linux": ("lc-auth-check-linux-amd64",)}
NEVER = {"config.json", ".DS_Store"}
NEVER_DIRS = {"__pycache__", "__MACOSX", ".lc-transactions", ".lc-compaction", ".git", "node_modules"}
NEVER_PATHS = {"assets/layouts/design_templates.user.json"}


def is_test(relative: str) -> bool:
    name = Path(relative).name
    return (name.startswith("test_") or name.startswith("benchmark_") or name == "pipeline_test_support.py"
            or relative.startswith("scripts/fixtures/"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect(with_tests: bool, platform: str):
    document = json.loads((ROOT / "references/auth-binaries.json").read_text(encoding="utf-8"))
    if document.get("schema") != "LC-AUTH-BINARIES/1.0":
        raise SystemExit("Invalid auth binary manifest; refusing to package")
    manifest = document["sha256"]
    wanted = (set(name for names in PLATFORM_BINARIES.values() for name in names)
              if platform == "all" else set(PLATFORM_BINARIES[platform]))
    # Validate the complete selection first. rglob alone silently skipped missing
    # binaries and could create a release unusable on a recipient's platform.
    for name in sorted(wanted):
        path = ROOT / "tools/bin" / name
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"Missing auth binary: {name}; refusing to package")
        if sha256(path) != manifest.get(name):
            raise SystemExit(f"Auth binary hash mismatch: {name}; refusing to package")
    files, skipped = [], []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(ROOT).as_posix()
        parts = set(Path(relative).parts)
        if path.name in NEVER or parts & NEVER_DIRS or relative in NEVER_PATHS or path.suffix in {".pyc", ".pyo"}:
            skipped.append(relative)
            continue
        if not with_tests and is_test(relative):
            skipped.append(relative)
            continue
        if relative.startswith("tools/bin/"):
            if path.name not in wanted:
                skipped.append(relative)
                continue
        files.append((path, relative))
    return files, skipped


def build(out_dir: Path, with_tests: bool, platform: str, name: str) -> dict:
    files, skipped = collect(with_tests, platform)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, relative in files:
            info = zipfile.ZipInfo(f"{NAME}/{relative}", date_time=(2026, 9, 30, 0, 0, 0))
            info.create_system = 3  # Preserve Unix modes even when built on Windows.
            mode = 0o755 if relative.startswith("tools/bin/") else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
        config = {"backend_url": "https://mcp.yixunkuajing.com", "backend_token": ""}
        info = zipfile.ZipInfo(f"{NAME}/config.json", date_time=(2026, 9, 30, 0, 0, 0))
        info.create_system = 3
        info.external_attr = (0o100000 | 0o600) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, json.dumps(config, indent=2) + "\n")
    return {"zip": str(target), "sha256": sha256(target), "files": len(files) + 1, "bytes": target.stat().st_size,
            "excluded": len(skipped), "with_tests": with_tests, "platform": platform,
            "contains_config_json": True, "config_token_empty": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT.parent)
    parser.add_argument("--name", default=f"{NAME}-v7")
    parser.add_argument("--with-tests", action="store_true", help="Maintainer package including tests and fixtures")
    parser.add_argument("--platform", choices=("all", "mac", "win", "linux"), default="all",
                        help="Only include the auth checker(s) for one platform")
    args = parser.parse_args(argv)
    result = build(args.out, args.with_tests, args.platform, args.name)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["config_token_empty"] else 2


if __name__ == "__main__":
    sys.exit(main())
