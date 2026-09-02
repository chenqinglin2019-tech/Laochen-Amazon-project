#!/usr/bin/env python3
"""Atomically replace legacy Amazon runners after a verified build exists.

The transaction never overwrites an archive or canonical runner.  On any
failure it moves every directory back to its original path.  Chrome Profiles
and credential-like files receive metadata-only manifest entries; their bytes
are never opened by the manifest generator.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import signal
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


class MigrationError(RuntimeError):
    pass


class MigrationInterrupted(MigrationError):
    pass


PROFILE_DIRECTORY_NAMES = {"chrome_profiles", "chrome-profile", "chrome_profile"}
SENSITIVE_NAME_PARTS = (
    "cookie",
    "token",
    "secret",
    "password",
    "credential",
    "api_key",
    "apikey",
)
SENSITIVE_EXACT_NAMES = {
    "config.json",
    "doubao_embedding_vision.json",
    "doubao_same_product_mini.json",
}
SENSITIVE_DIRECTORY_NAMES = {"config", "credentials", "secrets"}


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _path_has_profile_component(relative_path: Path) -> bool:
    return any(part.lower() in PROFILE_DIRECTORY_NAMES for part in relative_path.parts)


def _is_sensitive(relative_path: Path) -> bool:
    name = relative_path.name.lower()
    path_parts = {part.lower() for part in relative_path.parts[:-1]}
    return (
        name in SENSITIVE_EXACT_NAMES
        or name == ".env"
        or name.startswith(".env.")
        or bool(path_parts & SENSITIVE_DIRECTORY_NAMES)
        or any(part in name for part in SENSITIVE_NAME_PARTS)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _directory_size_bytes(path: Path) -> int:
    completed = subprocess.run(
        ["du", "-sk", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    kib = int(completed.stdout.split()[0])
    return kib * 1024


def _iter_non_profile_files(root: Path) -> Iterable[Path]:
    for current_root, directory_names, file_names in os.walk(root):
        current = Path(current_root)
        relative_current = current.relative_to(root)
        directory_names[:] = [
            name
            for name in directory_names
            if not _path_has_profile_component(relative_current / name)
        ]
        for name in sorted(file_names):
            yield current / name


def _manifest_for_archived_root(
    original_path: Path,
    archived_path: Path,
) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    metadata_only_count = 0
    checksum_count = 0
    for path in _iter_non_profile_files(archived_path):
        relative = path.relative_to(archived_path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        entry: Dict[str, Any] = {
            "path": relative.as_posix(),
            "size_bytes": int(info.st_size),
            "modified_at": dt.datetime.fromtimestamp(
                info.st_mtime, tz=dt.timezone.utc
            ).isoformat(),
        }
        if stat.S_ISREG(info.st_mode) and not _is_sensitive(relative):
            entry["sha256"] = _sha256(path)
            checksum_count += 1
        else:
            entry["verification"] = "metadata_only_sensitive_or_non_regular"
            metadata_only_count += 1
        entries.append(entry)
    return {
        "original_path": str(original_path),
        "archived_path": str(archived_path),
        "size_bytes": _directory_size_bytes(archived_path),
        "modified_at": dt.datetime.fromtimestamp(
            archived_path.stat().st_mtime, tz=dt.timezone.utc
        ).isoformat(),
        "non_profile_checksum_count": checksum_count,
        "metadata_only_count": metadata_only_count,
        "profile_policy": "metadata_size_only_no_file_content_read",
        "files": entries,
    }


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _collect_launcher_modes(archived_roots: Sequence[Path]) -> List[Tuple[Path, int]]:
    launchers: List[Tuple[Path, int]] = []
    for root in archived_roots:
        candidates = [root / "lc-amazon-data-crawl.sh"]
        candidates.extend(
            path
            for path in root.iterdir()
            if path.is_file() and path.suffix.lower() in {".command", ".sh"}
        )
        seen = set()
        for path in candidates:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            mode = stat.S_IMODE(path.stat().st_mode)
            launchers.append((path, mode))
    return sorted(launchers, key=lambda item: str(item[0]))


def _disable_launchers(launcher_modes: Sequence[Tuple[Path, int]]) -> None:
    for path, original_mode in launcher_modes:
        os.chmod(path, original_mode & ~0o111)


def migrate(
    *,
    workspace: Path,
    build_dir: Path,
    canonical_dir: Path,
    archive_dir: Path,
    legacy_dirs: Sequence[Path],
) -> Path:
    workspace = workspace.resolve()
    build_dir = build_dir.resolve()
    canonical_dir = canonical_dir.resolve()
    archive_dir = archive_dir.resolve()
    legacy_dirs = [path.resolve() for path in legacy_dirs]

    for path in [build_dir, canonical_dir, archive_dir, *legacy_dirs]:
        if not _is_within(path, workspace):
            raise MigrationError(f"路径不在 workspace 内，拒绝迁移：{path}")
    if not build_dir.is_dir() or build_dir.is_symlink():
        raise MigrationError(f"已验证 build 目录不存在或不安全：{build_dir}")
    if archive_dir.exists():
        raise MigrationError(f"归档目标已存在，拒绝覆盖：{archive_dir}")
    if canonical_dir not in legacy_dirs:
        raise MigrationError("legacy_dirs 必须包含当前 canonical runner。")
    if len(set(legacy_dirs)) != len(legacy_dirs):
        raise MigrationError("legacy_dirs 不能重复。")
    for path in legacy_dirs:
        if not path.is_dir() or path.is_symlink():
            raise MigrationError(f"旧目录不存在或不是安全的真实目录：{path}")

    archive_parent_existed = archive_dir.parent.exists()
    archive_creation_started = False
    moved_legacy: List[Tuple[Path, Path]] = []
    disabled_launchers: List[Tuple[Path, int]] = []
    build_promotion_started = False
    manifest_path = archive_dir / "MANIFEST.sha256.json"
    try:
        archive_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Pre-register creation so an interrupt immediately after mkdir still
        # removes the empty transaction target during rollback.
        archive_creation_started = True
        os.mkdir(archive_dir, mode=0o700)
        for original in legacy_dirs:
            archived = archive_dir / original.name
            if archived.exists():
                raise MigrationError(f"归档子目录已存在：{archived}")
            # Register the intended move before rename.  If an interrupt lands
            # immediately after the syscall returns, rollback still knows the
            # exact pair and restores it from the paths that actually exist.
            moved_legacy.append((original, archived))
            os.rename(original, archived)

        archived_roots = [archived for _original, archived in moved_legacy]
        # Capture the complete permission journal before mutating any launcher.
        # Restoring an unchanged mode is harmless, so rollback can replay the
        # whole journal even if interruption lands after the first chmod.
        disabled_launchers = _collect_launcher_modes(archived_roots)
        _disable_launchers(disabled_launchers)
        payload = {
            "schema_version": 1,
            "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
            "workspace": str(workspace),
            "archive_mode": "0700",
            "disabled_launchers": [str(path) for path, _mode in disabled_launchers],
            "roots": [
                _manifest_for_archived_root(original, archived)
                for original, archived in moved_legacy
            ],
        }
        _write_json_atomic(manifest_path, payload)
        os.chmod(archive_dir, 0o700)

        if canonical_dir.exists():
            raise MigrationError(f"canonical 路径迁移后仍存在：{canonical_dir}")
        # As above, set the transaction marker before the rename so there is no
        # untracked post-syscall interruption window.
        build_promotion_started = True
        os.rename(build_dir, canonical_dir)
        return manifest_path
    except BaseException:
        if (
            build_promotion_started
            and canonical_dir.exists()
            and not build_dir.exists()
        ):
            os.rename(canonical_dir, build_dir)
        if manifest_path.exists():
            manifest_path.unlink()
        for launcher, original_mode in disabled_launchers:
            if launcher.exists():
                os.chmod(launcher, original_mode)
        for original, archived in reversed(moved_legacy):
            if archived.exists() and not original.exists():
                os.rename(archived, original)
        if archive_creation_started:
            try:
                archive_dir.rmdir()
            except OSError:
                pass
        if not archive_parent_existed:
            try:
                archive_dir.parent.rmdir()
            except OSError:
                pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--canonical-dir", required=True, type=Path)
    parser.add_argument("--archive-dir", required=True, type=Path)
    parser.add_argument("--legacy-dir", action="append", required=True, type=Path)
    args = parser.parse_args()
    previous_handlers: Dict[int, Any] = {}

    def interrupt_handler(signum: int, _frame: Any) -> None:
        raise MigrationInterrupted(f"迁移收到终止信号 {signum}，正在回滚。")

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, interrupt_handler)
    try:
        manifest = migrate(
            workspace=args.workspace,
            build_dir=args.build_dir,
            canonical_dir=args.canonical_dir,
            archive_dir=args.archive_dir,
            legacy_dirs=args.legacy_dir,
        )
    finally:
        for signum, previous_handler in previous_handlers.items():
            signal.signal(signum, previous_handler)
    print(f"唯一 runner 已切换；归档清单：{manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
