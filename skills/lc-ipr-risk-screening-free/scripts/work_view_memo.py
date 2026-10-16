"""Cross-process memo of derived views, keyed by the exact state of the task directory.

The work view and the review input digest are pure functions of the task directory's files (plus the caller's
options and the skill's own code/config). Every CLI step re-derived them from scratch: the real run recomputed the
work view 17 times (138 s) and the review preparation 5 times (71 s). A memo entry is reused only while every file
under the task directory, every script and the configuration files are byte/stat-identical to when it was written;
nothing is ever reused across a change, and nothing here reads credentials (configuration files are keyed by size and mtime only).

Only best-estimate-risk-v1 tasks use the memo; ``LC_IPR_WORK_VIEW_MEMO=0`` disables it.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from common import atomic_write_json, load_json, sha256_json

VERSION = "work-view-memo-v2"
KEEP_PER_NAME = 4
CONTENT_HASH_LIMIT = 8 * 1024 * 1024       # larger retained originals are keyed by size and mtime
CONFIG_FILES = ("config.json", "config.local.json", "runtime-config.json", ".env")
# r5d21: the pipeline appends to its own run log, state file and step timings after every command, so the key changed
# before every step and the memo never served a pipeline run; no derived view reads these three files. Retained media
# (immutable originals) are keyed by size, mtime and inode instead of being hashed again on every step.
VOLATILE_FILES = ("pipeline-log.jsonl", "pipeline-state.json", "runtime-timings.jsonl")
# a host's own bookkeeping of its last call (written even when it had nothing to do); dispatch code reads it,
# no derived view does
VOLATILE_NAMES = ("last-run.json",)
STAT_KEYED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".pdf")


def enabled(task_dir) -> bool:
    if os.environ.get("LC_IPR_WORK_VIEW_MEMO") == "0":
        return False
    path = Path(task_dir) / "task.json"
    if not path.is_file():
        return False
    try:
        task = load_json(path)
    except (ValueError, OSError):
        return False
    return isinstance(task, dict) and bool(task.get("best_estimate_revision"))


def state_key(task_dir, options) -> str:
    """Digest of everything a derived view may depend on."""
    root = Path(task_dir).resolve()
    digest = hashlib.sha256()
    digest.update((VERSION + "\0" + str(root) + "\0" + sha256_json(options) + "\0").encode("utf-8"))
    for path in sorted(p for p in root.rglob("*") if not p.name.startswith(".")):
        # Dot files are lock files and the temporary files of atomic writes; a concurrent host (the text and visual
        # triage hosts run side by side) can remove one between listing and reading it.
        rel = path.relative_to(root).as_posix()
        if rel in VOLATILE_FILES or path.name in VOLATILE_NAMES:
            continue
        try:
            if not path.is_file():
                continue
            info = path.stat()
            content = (hashlib.sha256(path.read_bytes()).hexdigest()
                       if info.st_size <= CONTENT_HASH_LIMIT and path.suffix.lower() not in STAT_KEYED_SUFFIXES
                       else "%d:%d:%d" % (info.st_size, info.st_mtime_ns, info.st_ino))
        except FileNotFoundError:
            continue
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(content.encode("ascii"))
        digest.update(b"\n")
    scripts = Path(__file__).resolve().parent
    for path in sorted(scripts.glob("*.py")):
        info = path.stat()
        digest.update(("%s:%d:%d\n" % (path.name, info.st_size, info.st_mtime_ns)).encode("utf-8"))
    for name in CONFIG_FILES:
        path = scripts.parent / name
        if path.is_file():
            info = path.stat()      # stat only: credentials are never read here
            digest.update(("%s:%d:%d\n" % (name, info.st_size, info.st_mtime_ns)).encode("utf-8"))
    return digest.hexdigest()


def _store_dir(task_dir) -> Path:
    root = Path(task_dir).resolve()
    return Path(tempfile.gettempdir()) / "lc-ipr-work-view-memo" / hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:32]


def cached(task_dir, name: str, options, compute):
    """Return ``compute()``, served from the memo when the task directory state is unchanged."""
    import derivation_memo
    raw = compute

    def compute():
        # r5d21: one derivation checks each supplement file and event chain once (derivation_memo)
        with derivation_memo.active():
            return raw()
    if not enabled(task_dir):
        return compute()
    key = state_key(task_dir, options)
    store = _store_dir(task_dir)
    path = store / ("%s-%s.json" % (name, key[:40]))
    if path.is_file():
        try:
            saved = load_json(path)
        except (ValueError, OSError):
            saved = None
        if isinstance(saved, dict) and saved.get("key") == key and saved.get("name") == name:
            return deepcopy(saved["value"])
    value = compute()
    try:
        store.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, {"version": VERSION, "name": name, "key": key, "value": value})
        stale = sorted((p for p in store.glob(name + "-*.json") if p != path), key=lambda p: p.stat().st_mtime_ns)
        for old in stale[:-(KEEP_PER_NAME - 1)] if len(stale) >= KEEP_PER_NAME else []:
            old.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError):
        pass        # a memo that cannot be written only costs the next derivation
    return value
