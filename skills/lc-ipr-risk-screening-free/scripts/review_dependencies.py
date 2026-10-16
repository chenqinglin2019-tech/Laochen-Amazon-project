"""Process-local observations of files checked by the real review validator."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from common import sha256_file

_COLLECTOR = ContextVar('ipr_checked_review_dependencies', default=None)


@contextmanager
def collect():
    files = {}
    token = _COLLECTOR.set(files)
    try:
        yield files
    finally:
        _COLLECTOR.reset(token)


def checked(path, digest):
    """Called only after the existing protocol has verified the expected hash."""
    files = _COLLECTOR.get()
    if files is None:
        return
    # Preserve the path actually opened, including a symlink's name: resolving
    # its target here would miss a subsequent retargeting of that original name.
    name = str(Path(path).absolute())
    if name in files and files[name] != digest:
        raise ValueError('DELIVERY_REVIEW_DEPENDENCY_CHANGED_DURING_CHECK')
    files[name] = digest


def errors(files):
    for name, expected in files.items():
        try:
            path = Path(name)
            if not path.is_file() or sha256_file(path) != expected:
                return ['DELIVERY_REVIEW_DEPENDENCY_CHANGED']
        except OSError:
            return ['DELIVERY_REVIEW_DEPENDENCY_CHANGED']
    return []
