"""Small, credential-free file primitives for the V8 workflow."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from lc_fsretry import replace


class StudioError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def inside(base, value):
    base = Path(base).resolve()
    path = Path(value)
    path = path if path.is_absolute() else base / path
    if not path.resolve().is_relative_to(base):
        raise StudioError("PATH_OUTSIDE_PROJECT")
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise StudioError("SYMLINK_NOT_ALLOWED")
        if parent == base:
            break
    return path


def external_image(path):
    path = Path(path).expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise StudioError("IMAGE_MISSING_OR_SYMLINK")
    return path


def write_bytes(path, payload, *, immutable=False):
    path = Path(path)
    if path.exists():
        if path.read_bytes() == payload:
            return
        if immutable:
            raise StudioError("IMMUTABLE_ARTIFACT_CONFLICT")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".studio-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path, value):
    write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


@contextlib.contextmanager
def project_lock(manifest_path, timeout=10):
    """Stable lock inode; readers use atomic manifest snapshots without this lock."""
    path = Path(manifest_path).with_name(".one-pass.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            def acquire():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise StudioError("PROJECT_BUSY") from None
                time.sleep(.05)
        try:
            yield
        finally:
            release()
