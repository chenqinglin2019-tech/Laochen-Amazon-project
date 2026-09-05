#!/usr/bin/env python3
"""Safely remove the 飞鱼神图 app from Codex Harness by archiving it."""

from __future__ import annotations

import argparse
import datetime as dt
import grp
import json
import os
from pathlib import Path
import pwd
import sys

from install_harness_app import (
    APP_NAME,
    APP_SLUG,
    DEFAULT_APPS_ROOT,
    GUIDE_PATH,
    InstallError,
    load_manifest,
    stop_existing_backend,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove the 飞鱼神图 Harness module from the live app list and preserve it as an archive."
    )
    parser.add_argument("--apps-root", type=Path, default=DEFAULT_APPS_ROOT)
    parser.add_argument(
        "--archive-root",
        type=Path,
        help="Archive directory; defaults to a removed/ sibling of apps/.",
    )
    parser.add_argument("--skip-harness-check", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def validate_environment(apps_root: Path, archive_root: Path, skip_harness_check: bool) -> None:
    if not apps_root.is_absolute() or not archive_root.is_absolute():
        raise InstallError("App and archive roots must be absolute paths.")
    if archive_root == apps_root or apps_root in archive_root.parents:
        raise InstallError("Archive root must be outside the live Harness apps directory.")
    if not skip_harness_check and not GUIDE_PATH.is_file():
        raise InstallError("Codex Harness was not detected; expected /opt/skilldeck/share/diy.md.")
    if not skip_harness_check and os.geteuid() != 0:
        raise InstallError("Run the Harness module remover as root so removal is not left incomplete.")
    if not skip_harness_check:
        try:
            pwd.getpwnam("skilldeck")
            grp.getgrnam("skilldeck")
        except KeyError as exc:
            raise InstallError("Codex Harness user/group 'skilldeck' is unavailable.") from exc


def verify_target(target: Path) -> bool:
    if not target.exists():
        return False
    if not target.is_dir():
        raise InstallError(f"Refusing to remove a non-directory target: {target}")
    manifest_path = target / "app.json"
    if not manifest_path.is_file():
        raise InstallError(f"Refusing to remove an unrecognized app without app.json: {target}")
    manifest = load_manifest(manifest_path)
    if manifest.get("manifest") != 1 or manifest.get("name") != APP_NAME:
        raise InstallError(f"Refusing to remove a different custom app: {target}")
    return True


def choose_archive_path(archive_root: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = archive_root / f"{APP_SLUG}-{stamp}"
    suffix = 1
    while destination.exists():
        destination = archive_root / f"{APP_SLUG}-{stamp}-{suffix}"
        suffix += 1
    return destination


def prepare_archive_root(archive_root: Path, skip_harness_check: bool) -> None:
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_root.chmod(0o750)
    if not skip_harness_check:
        group = grp.getgrnam("skilldeck")
        os.chown(archive_root, 0, group.gr_gid)


def main() -> int:
    args = parse_args()
    apps_root = args.apps_root.resolve()
    archive_root = (
        args.archive_root.resolve()
        if args.archive_root is not None
        else apps_root.parent / "removed"
    )
    target = apps_root / APP_SLUG
    try:
        validate_environment(apps_root, archive_root, args.skip_harness_check)
        if not verify_target(target):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "already_absent": True,
                        "app_dir": str(target),
                        "archive": None,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        backend_stopped = stop_existing_backend(target)
        prepare_archive_root(archive_root, args.skip_harness_check)
        destination = choose_archive_path(archive_root)
        target.rename(destination)
    except (InstallError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "already_absent": False,
                "app_dir": str(target),
                "archive": str(destination),
                "backend_stopped": backend_stopped,
                "data_preserved": True,
                "skill_removed": False,
                "host_ingress_changed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
