"""Process-local isolation shared by offline verification entry points."""

from __future__ import annotations

from contextlib import contextmanager
import os
from unittest.mock import patch

from common import ENV_CREDENTIALS


def offline_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Keep runtime controls while excluding every inherited credential."""
    environment = dict(os.environ if source is None else source)
    for name in ENV_CREDENTIALS.values():
        environment.pop(name, None)
    environment["LC_IPR_OFFLINE_TESTS"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


@contextmanager
def isolated_test_environment():
    """Protect fixture generation in this process as well as its children."""
    with patch.dict(os.environ, offline_environment(), clear=True):
        yield
