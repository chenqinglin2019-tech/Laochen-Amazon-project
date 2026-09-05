#!/usr/bin/env python3
"""Install or update the bundled 飞鱼神图 app in Codex Harness custom space."""

from __future__ import annotations

import argparse
import datetime as dt
import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys


SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = SKILL_ROOT / "assets" / "codex-harness-app"
SOURCE_CLI = SKILL_ROOT / "scripts" / "feiyushentu_amazon.py"
DEFAULT_APPS_ROOT = Path("/var/lib/skilldeck-custom/apps")
GUIDE_PATH = Path("/opt/skilldeck/share/diy.md")
APP_SLUG = "amazon-image-generator"
APP_NAME = "飞鱼神图"


class InstallError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the 飞鱼神图 custom app without copying user data or tokens."
    )
    parser.add_argument("--apps-root", type=Path, default=DEFAULT_APPS_ROOT)
    parser.add_argument("--no-start", action="store_true", help="Install files but do not start the backend.")
    parser.add_argument(
        "--skip-harness-check",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"Cannot read valid manifest: {path}") from exc
    if not isinstance(value, dict):
        raise InstallError(f"Manifest must be an object: {path}")
    return value


def validate_inputs(apps_root: Path, skip_harness_check: bool) -> None:
    if not TEMPLATE_ROOT.is_dir() or not SOURCE_CLI.is_file():
        raise InstallError("The skill package is incomplete: Harness template or API helper is missing.")
    template_manifest = load_manifest(TEMPLATE_ROOT / "app.json")
    if template_manifest.get("name") != APP_NAME or template_manifest.get("icon") is not None:
        raise InstallError("Bundled manifest must use the verified text-only 飞鱼神图 navigation entry.")
    if not skip_harness_check and not GUIDE_PATH.is_file():
        raise InstallError("Codex Harness was not detected; expected /opt/skilldeck/share/diy.md.")
    if not skip_harness_check and os.geteuid() != 0:
        raise InstallError("Run the Harness app installer as root so installation is not left partially updated.")
    if not skip_harness_check:
        try:
            pwd.getpwnam("skilldeck")
            grp.getgrnam("skilldeck")
        except KeyError as exc:
            raise InstallError("Codex Harness user/group 'skilldeck' is unavailable.") from exc
    if not apps_root.is_absolute():
        raise InstallError("--apps-root must be an absolute path.")


def verify_existing_app(target: Path) -> None:
    manifest_path = target / "app.json"
    if not target.exists() or not any(target.iterdir()):
        return
    if not manifest_path.is_file():
        raise InstallError(f"Refusing to replace an unrecognized non-empty directory: {target}")
    manifest = load_manifest(manifest_path)
    if manifest.get("name") != APP_NAME or manifest.get("manifest") != 1:
        raise InstallError(f"Refusing to replace a different custom app: {target}")


def backup_code(target: Path) -> Path | None:
    existing = [name for name in ("app.json", "web", "backend") if (target / name).exists()]
    if not existing:
        return None
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = target / ".install-backups" / stamp
    suffix = 1
    while backup.exists():
        backup = target / ".install-backups" / f"{stamp}-{suffix}"
        suffix += 1
    backup.mkdir(parents=True)
    for name in existing:
        source = target / name
        destination = backup / name
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    return backup


def stop_existing_backend(target: Path) -> bool:
    pid_file = target / "data" / "backend.pid"
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    command_path = Path(f"/proc/{pid}/cmdline")
    try:
        command = command_path.read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError as exc:
        raise InstallError(f"Cannot verify existing backend process {pid}.") from exc
    expected = str(target / "backend" / "server.py")
    if expected not in command:
        raise InstallError(f"PID file points to an unrelated process; refusing to stop PID {pid}.")
    result = subprocess.run(
        [str(target / "backend" / "stop.sh")],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise InstallError(f"Existing backend stop failed: {message}")
    return True


def replace_code(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in ("web", "backend"):
        destination = target / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(TEMPLATE_ROOT / name, destination)
    shutil.copy2(TEMPLATE_ROOT / "app.json", target / "app.json")
    vendor = target / "backend" / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_CLI, vendor / SOURCE_CLI.name)
    for directory in (target / "data", target / "data" / "uploads", target / "data" / "generated"):
        directory.mkdir(parents=True, exist_ok=True)


def set_modes(target: Path) -> None:
    for path in target.rglob("*"):
        if ".install-backups" in path.parts:
            continue
        if path.is_dir():
            path.chmod(0o750)
        elif path == target / "data" / "feiyushentu.toml":
            path.chmod(0o600)
        elif path.name in {"start.sh", "stop.sh", "server.py", "feiyushentu_amazon.py"}:
            path.chmod(0o750)
        else:
            path.chmod(0o640)


def set_ownership(target: Path, skip_harness_check: bool) -> None:
    if skip_harness_check:
        return
    try:
        skilldeck_user = pwd.getpwnam("skilldeck")
        skilldeck_group = grp.getgrnam("skilldeck")
    except KeyError as exc:
        raise InstallError("Codex Harness user/group 'skilldeck' is unavailable.") from exc
    for path in [target, *target.rglob("*")]:
        if ".install-backups" in path.parts:
            continue
        uid = skilldeck_user.pw_uid if target / "data" == path or target / "data" in path.parents else 0
        os.chown(path, uid, skilldeck_group.gr_gid)


def start_backend(target: Path) -> None:
    result = subprocess.run(
        [str(target / "backend" / "start.sh")],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise InstallError(f"Backend start failed: {message}")


def main() -> int:
    args = parse_args()
    apps_root = args.apps_root.resolve()
    target = apps_root / APP_SLUG
    try:
        validate_inputs(apps_root, args.skip_harness_check)
        apps_root.mkdir(parents=True, exist_ok=True)
        verify_existing_app(target)
        stopped_existing_backend = stop_existing_backend(target)
        backup = backup_code(target)
        replace_code(target)
        set_modes(target)
        set_ownership(target, args.skip_harness_check)
        if not args.no_start:
            start_backend(target)
    except InstallError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "app_dir": str(target),
                "entry": f"/custom/apps/{APP_SLUG}/index.html",
                "backend_started": not args.no_start,
                "previous_backend_stopped": stopped_existing_backend,
                "backup": str(backup) if backup else None,
                "data_preserved": True,
                "token_copied": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
