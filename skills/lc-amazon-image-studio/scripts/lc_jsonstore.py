"""Small, dependency-free JSON storage helpers shared by the template library (V8).

`selection_lock` serializes a read/modify/write of one file across processes
(fcntl on Mac/Linux, msvcrt on Windows, bounded wait); `write_json_atomic` durably
replaces a JSON file without sharing a temporary name between writers. Moved
verbatim from the V7 `lc_style_reference` module so the library no longer pulls
in the old pipeline.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

SELECTION_LOCK_TIMEOUT_SECONDS = 60


@contextlib.contextmanager
def _selection_lock(selection_path: Path) -> Iterator[None]:
    """Serialize the complete selection read/select/commit transaction."""
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = selection_path.with_name(f".{selection_path.name}.lock")
    # Keep this lock file rather than unlinking it after release: a late opener
    # must lock the same inode as any process already waiting on it.
    deadline = time.monotonic() + SELECTION_LOCK_TIMEOUT_SECONDS
    with lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            while True:  # bounded: a crashed holder must not block every later command forever
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"STYLE_SELECTION_BUSY: {lock_path} is locked by another process") from None
                    time.sleep(0.05)
        else:  # pragma: no cover - exercised on Windows hosts.
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            while True:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"STYLE_SELECTION_BUSY: {lock_path} is locked by another process") from None
                    time.sleep(0.05)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - exercised on Windows hosts.
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _fsync_directory(path: Path) -> None:
    """Best-effort directory sync after an already-synced atomic replacement."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Some filesystems cannot fsync directories; the file itself was synced.
        pass
    finally:
        os.close(descriptor)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    """Durably replace JSON without sharing a temporary name between writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


selection_lock = _selection_lock
write_json_atomic = _write_json
