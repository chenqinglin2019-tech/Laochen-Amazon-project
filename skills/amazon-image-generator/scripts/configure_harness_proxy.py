#!/usr/bin/env python3
"""Apply one verified, app-scoped Nginx proxy for the 飞鱼神图 Harness app."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


MARKER = "# managed-by: amazon-image-generator"
LOCATION = "/custom-api/amazon-image-generator/"


class ProxyError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure the verified, scoped 飞鱼神图 Nginx proxy."
    )
    parser.add_argument("--config-file", type=Path, required=True)
    parser.add_argument("--backend-port", type=int, default=39081)
    parser.add_argument("--nginx-bin", type=Path)
    parser.add_argument(
        "--verify-origin",
        action="append",
        default=[],
        help="Public Harness origin to verify after applying, for example https://example.com. Repeat as needed.",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--apply",
        action="store_true",
        help="Apply the managed configuration after the caller verifies the include directory.",
    )
    action.add_argument(
        "--remove",
        action="store_true",
        help="Remove only a configuration carrying this app's management marker.",
    )
    parser.add_argument("--skip-root-check", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def find_nginx_binary(requested: Path | None) -> Path:
    candidates = []
    if requested is not None:
        candidates.append(requested)
    discovered = shutil.which("nginx")
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend(
        [
            Path("/www/server/nginx/sbin/nginx"),
            Path("/usr/sbin/nginx"),
            Path("/usr/local/sbin/nginx"),
        ]
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise ProxyError("Cannot find an executable Nginx binary; pass --nginx-bin explicitly.")


def validate(args: argparse.Namespace, config_file: Path, nginx_bin: Path) -> None:
    if not args.skip_root_check and os.geteuid() != 0:
        raise ProxyError("Run the proxy configurator as root.")
    if not config_file.is_absolute() or config_file.suffix != ".conf":
        raise ProxyError("--config-file must be an absolute .conf path in a verified Nginx include directory.")
    if config_file.name != "amazon-image-generator.conf":
        raise ProxyError("--config-file must be named amazon-image-generator.conf.")
    if not config_file.parent.is_dir():
        raise ProxyError(f"Verified Nginx include directory does not exist: {config_file.parent}")
    if config_file.is_symlink():
        raise ProxyError(f"Refusing to replace a symlink: {config_file}")
    if not 1024 <= args.backend_port <= 65535:
        raise ProxyError("--backend-port must be a high port between 1024 and 65535.")
    if not nginx_bin.is_file():
        raise ProxyError(f"Nginx binary does not exist: {nginx_bin}")
    if args.apply and not args.verify_origin:
        raise ProxyError("At least one --verify-origin is required when applying the proxy.")
    for origin in args.verify_origin:
        parsed = urllib.parse.urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ProxyError(f"Invalid public Harness origin: {origin}")


def render_config(port: int) -> str:
    return f"""{MARKER}
location ^~ {LOCATION} {{
    proxy_pass http://127.0.0.1:{port}/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}}
"""


def run_nginx(nginx_bin: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nginx_bin), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


def verify_public_health(origins: list[str]) -> list[str]:
    verified = []
    for origin in origins:
        endpoint = origin.rstrip("/") + LOCATION + "health"
        request = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                content_type = str(response.headers.get("Content-Type") or "").lower()
                body = response.read(1024 * 1024)
                status = response.status
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise ProxyError(f"Public API health check failed for {endpoint}: {exc}") from exc
        if status != 200 or "application/json" not in content_type:
            raise ProxyError(
                f"Public API health check for {endpoint} returned HTTP {status} with {content_type or 'no content type'}"
            )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProxyError(f"Public API health check for {endpoint} did not return valid JSON") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise ProxyError(f"Public API health check for {endpoint} returned an unexpected JSON envelope")
        verified.append(endpoint)
    return verified


def restore(config_file: Path, previous: bytes | None, previous_mode: int | None) -> None:
    if previous is None:
        config_file.unlink(missing_ok=True)
        return
    config_file.write_bytes(previous)
    if previous_mode is not None:
        config_file.chmod(previous_mode)


def apply_config(
    config_file: Path,
    content: str,
    nginx_bin: Path,
    verify_origins: list[str],
) -> tuple[bool, Path | None, list[str]]:
    previous = config_file.read_bytes() if config_file.exists() else None
    previous_mode = (config_file.stat().st_mode & 0o777) if config_file.exists() else None
    if previous is not None and not previous.decode("utf-8", "replace").startswith(MARKER):
        raise ProxyError(f"Refusing to replace an unmanaged Nginx file: {config_file}")
    unchanged = previous == content.encode("utf-8")
    backup = None
    if previous is not None and not unchanged:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = config_file.with_name(f"{config_file.name}.backup.{stamp}")
        suffix = 1
        while backup.exists():
            backup = config_file.with_name(f"{config_file.name}.backup.{stamp}-{suffix}")
            suffix += 1
        backup.write_bytes(previous)
        backup.chmod(previous_mode or 0o640)
    if not unchanged:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{config_file.name}.", suffix=".tmp", dir=config_file.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o640)
            os.replace(temporary, config_file)
        finally:
            temporary.unlink(missing_ok=True)
    tested = run_nginx(nginx_bin, "-t")
    if tested.returncode != 0:
        restore(config_file, previous, previous_mode)
        message = tested.stderr.strip() or tested.stdout.strip() or "unknown error"
        raise ProxyError(f"Nginx configuration test failed and was rolled back: {message}")
    reloaded = run_nginx(nginx_bin, "-s", "reload")
    if reloaded.returncode != 0:
        restore(config_file, previous, previous_mode)
        run_nginx(nginx_bin, "-t")
        message = reloaded.stderr.strip() or reloaded.stdout.strip() or "unknown error"
        raise ProxyError(f"Nginx reload failed and the file was rolled back: {message}")
    try:
        verified = verify_public_health(verify_origins)
    except ProxyError as exc:
        restore(config_file, previous, previous_mode)
        rollback_test = run_nginx(nginx_bin, "-t")
        rollback_reload = run_nginx(nginx_bin, "-s", "reload") if rollback_test.returncode == 0 else None
        rollback_ok = rollback_test.returncode == 0 and rollback_reload is not None and rollback_reload.returncode == 0
        suffix = "" if rollback_ok else " Nginx rollback validation or reload also failed; inspect immediately."
        raise ProxyError(f"{exc}; the managed file was rolled back.{suffix}") from exc
    return unchanged, backup, verified


def remove_config(config_file: Path, nginx_bin: Path) -> tuple[bool, Path | None, bool]:
    if not config_file.exists():
        return True, None, False
    previous = config_file.read_bytes()
    previous_mode = config_file.stat().st_mode & 0o777
    if not previous.decode("utf-8", "replace").startswith(MARKER):
        raise ProxyError(f"Refusing to remove an unmanaged Nginx file: {config_file}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = config_file.with_name(f"{config_file.name}.removed.{stamp}")
    suffix = 1
    while backup.exists():
        backup = config_file.with_name(f"{config_file.name}.removed.{stamp}-{suffix}")
        suffix += 1
    backup.write_bytes(previous)
    backup.chmod(previous_mode)
    config_file.unlink()

    tested = run_nginx(nginx_bin, "-t")
    if tested.returncode != 0:
        restore(config_file, previous, previous_mode)
        message = tested.stderr.strip() or tested.stdout.strip() or "unknown error"
        raise ProxyError(f"Nginx configuration test failed and removal was rolled back: {message}")
    reloaded = run_nginx(nginx_bin, "-s", "reload")
    if reloaded.returncode != 0:
        restore(config_file, previous, previous_mode)
        run_nginx(nginx_bin, "-t")
        message = reloaded.stderr.strip() or reloaded.stdout.strip() or "unknown error"
        raise ProxyError(f"Nginx reload failed and removal was rolled back: {message}")
    return False, backup, True


def main() -> int:
    args = parse_args()
    # Preserve the final path component so validate() can reject symlinks.
    # resolve() here would silently follow a link before the safety check.
    config_file = args.config_file
    try:
        nginx_bin = find_nginx_binary(args.nginx_bin)
        validate(args, config_file, nginx_bin)
        if args.remove:
            unchanged, backup, reloaded = remove_config(config_file, nginx_bin)
            action = "remove"
        else:
            unchanged, backup, verified = apply_config(
                config_file,
                render_config(args.backend_port),
                nginx_bin,
                args.verify_origin,
            )
            reloaded = True
            action = "apply"
        if args.remove:
            verified = []
    except (OSError, ProxyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "action": action,
                "config_file": str(config_file),
                "backend": f"http://127.0.0.1:{args.backend_port}/",
                "location": LOCATION,
                "unchanged": unchanged,
                "backup": str(backup) if backup else None,
                "nginx_reloaded": reloaded,
                "verified_health_urls": verified,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
