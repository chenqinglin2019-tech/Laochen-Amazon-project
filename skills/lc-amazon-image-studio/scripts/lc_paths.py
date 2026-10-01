"""Per-user locations shared by runtime, authentication pass and template library.

Standard library only; values are computed at call time so tests can patch
``platform.system`` and environment variables.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

APP = "lc-amazon-image-studio"


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")


def cache_home() -> Path:
    """Runtime/auth cache: %LOCALAPPDATA%\\lc-amazon-image-studio or ~/.cache/lc-amazon-image-studio."""
    override = os.environ.get("LC_AMAZON_STUDIO_CACHE")
    if override:
        return Path(override).expanduser()
    return local_appdata() / APP if is_windows() else Path.home() / ".cache" / APP


def app_home() -> Path:
    """User data home that survives skill upgrades (template library lives here)."""
    override = os.environ.get("LC_AMAZON_STUDIO_HOME")
    if override:
        return Path(override).expanduser()
    return local_appdata() / APP if is_windows() else Path.home() / (".lc-amazon-image-studio")


def library_dir(explicit: str | os.PathLike | None = None) -> Path:
    """Template library: --library-dir > $LC_TEMPLATE_LIBRARY_DIR > <app_home>/library."""
    if explicit:
        return Path(explicit).expanduser()
    override = os.environ.get("LC_TEMPLATE_LIBRARY_DIR")
    if override:
        return Path(override).expanduser()
    return app_home() / "library"
