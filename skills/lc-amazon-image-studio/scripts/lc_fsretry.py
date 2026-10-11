"""File operations that tolerate brief Windows sharing violations.

On Windows, antivirus scanners, the search indexer, cloud-sync clients or a
concurrent `status` reader can hold a handle for a moment; `os.replace`,
`os.unlink` and `shutil.rmtree` then fail with WinError 5/32/33/145 although a
retry a few milliseconds later succeeds. These helpers retry only those errors,
only on Windows, for at most ~3 seconds, then raise an actionable FILE_IN_USE
error. On macOS/Linux they are plain pass-throughs.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

RETRY_WINERRORS = {5, 32, 33, 145}
# Originals captured at import: lc_fastpath may later wrap os.replace/os.unlink with
# these helpers on Windows, and the helpers must never call the wrappers.
_OS_REPLACE, _OS_UNLINK = os.replace, os.unlink
DELAYS = (0.02, 0.05, 0.1, 0.15, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25)  # ~2.9 s


def _retryable(exc):
    return os.name == "nt" and isinstance(exc, OSError) and getattr(exc, "winerror", None) in RETRY_WINERRORS


def _retry(operation, path, *args):
    for delay in DELAYS + (None,):
        try:
            return operation(*args)
        except OSError as exc:
            if delay is None or not _retryable(exc):
                if _retryable(exc):
                    raise OSError(exc.errno, f"FILE_IN_USE: close programs using {path} (viewer, sync or antivirus) "
                                             f"and retry: {exc}", str(path)) from exc
                raise
            time.sleep(delay)


def replace(src, dst):
    return _retry(_OS_REPLACE, dst, src, dst)


def unlink(path, missing_ok=True):
    try:
        return _retry(_OS_UNLINK, path, path)
    except FileNotFoundError:
        if not missing_ok:
            raise


def rmtree(path, best_effort=False):
    try:
        return _retry(shutil.rmtree, path, path)
    except FileNotFoundError:
        return None
    except OSError:
        if not best_effort:
            raise
        return None


def read_json(path, *, attempts=6):
    """Read JSON that another process may be atomically replacing right now."""
    path = Path(path)
    for index in range(attempts):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError) as exc:
            if index == attempts - 1 or (isinstance(exc, PermissionError) and os.name != "nt"):
                raise
            time.sleep(0.05 * (index + 1))
