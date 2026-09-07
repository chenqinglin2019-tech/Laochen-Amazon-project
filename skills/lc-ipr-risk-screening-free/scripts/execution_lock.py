"""Nonblocking process lock for a complete task dispatcher on POSIX/Windows."""
from contextlib import contextmanager
from pathlib import Path
import os


@contextmanager
def execution_lock(task_dir: Path, name: str):
    if name not in {"api", "browser"}:
        raise ValueError("Unknown execution lock")
    with (task_dir / f".{name}-execution.lock").open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0, 2)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError(f"{name.upper()}_EXECUTION_ALREADY_RUNNING") from None
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
