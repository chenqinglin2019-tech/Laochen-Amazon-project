"""Use the verified runtime selection so commands need no hand-copied paths.

runtime_bootstrap.py publishes selection.json after a real verification. The
pipeline CLI fills missing LC_LAYOUT_* variables from it and, when started with
an interpreter that lacks Pillow, relaunches itself once with the selected one.
Standard library only; never reads account data.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ENV_KEYS = {"LC_LAYOUT_NODE": "node", "LC_LAYOUT_NODE_MODULES": "modules", "LC_LAYOUT_CHROMIUM": "chromium"}
RELAUNCH_MARKER = "LC_RUNTIME_RELAUNCHED"
GUIDANCE = ("Pillow is required. Run `python scripts/runtime_bootstrap.py verify --json` from the skill root "
            "(installs are separate and need confirmation), then use its commands.python.")


def selection() -> dict:
    try:
        from runtime_bootstrap import RuntimeBootstrap
        value = RuntimeBootstrap()._selection()
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001 - a missing/invalid lock simply means "no selection"
        return {}


def apply_selected_runtime(environ=None) -> dict:
    """Fill only absent LC_LAYOUT_* values; explicit caller settings always win."""
    environ = os.environ if environ is None else environ
    if all(environ.get(key) for key in ENV_KEYS):
        return {}
    chosen = selection()
    applied = {}
    for env_key, selection_key in ENV_KEYS.items():
        value = chosen.get(selection_key)
        if not environ.get(env_key) and isinstance(value, str) and value and Path(value).exists():
            environ[env_key] = value
            applied[env_key] = value
    return applied


def relaunch_with_selected_python(script: str) -> None:
    """Called when Pillow is missing. Never returns: relaunches or exits with guidance."""
    if os.environ.get(RELAUNCH_MARKER) != "1" and Path(sys.argv[0]).name == Path(script).name:
        python = selection().get("python")
        # Compare unresolved paths: a venv interpreter is a symlink to its base
        # Python but has different site-packages (that is the point of it).
        if isinstance(python, str) and Path(python).is_file() and Path(python).absolute() != Path(sys.executable).absolute():
            env = dict(os.environ, **{RELAUNCH_MARKER: "1"})
            completed = subprocess.run([python, "-X", "utf8", *sys.argv], env=env)
            raise SystemExit(completed.returncode)
    raise SystemExit(GUIDANCE)
