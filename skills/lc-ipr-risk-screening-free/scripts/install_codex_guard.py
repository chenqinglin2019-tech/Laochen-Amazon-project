#!/usr/bin/env python3
"""Merge/uninstall this skill's hooks without granting trust or changing other hooks."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid

from codex_guard import read, save, script_revision
from runtime_compat import install_existing_dependencies
install_existing_dependencies()
import tomllib

LABEL = "LC IPR completion guard"
EVENTS = ("SessionStart", "UserPromptSubmit", "Stop", "Interrupt")


def definition(home=None):
    scripts = Path(__file__).resolve().parent
    revision = script_revision()
    # Preserve the venv interpreter path: resolving its symlink loses dependencies.
    argv = [os.path.abspath(sys.executable), "-B", str(scripts / "codex_guard.py"), "hook", "--revision", revision]
    if home is not None:
        argv += ["--runtime-root", str(Path(home).expanduser().resolve() / "lc-ipr-guard")]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    return {event: [{"hooks": [{"type": "command", "command": command,
        "timeout": 3 if event == "Interrupt" else 120, "statusMessage": LABEL}]}] for event in EVENTS}


def without_ours(config):
    value = json.loads(json.dumps(config))
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("HOOKS_CONFIG_INVALID")
    for event in EVENTS:
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError("HOOK_EVENT_CONFIG_INVALID")
        retained = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError("HOOK_GROUP_CONFIG_INVALID")
            handlers = group["hooks"]
            def ours(handler):
                return (handler.get("statusMessage") == LABEL and
                        "codex_guard.py" in handler.get("command", ""))
            remaining = [h for h in handlers if not ours(h)]
            if remaining or not handlers:
                retained.append(group | {"hooks": remaining})
        if retained:
            hooks[event] = retained
        else:
            hooks.pop(event, None)
    return value


def install(home, *, uninstall=False):
    home = Path(home).expanduser().resolve()
    path = home / "hooks.json"
    config = read(path, {})
    inline = home / "config.toml"
    warnings = []
    if inline.is_file():
        settings = tomllib.loads(inline.read_text(encoding="utf-8"))
        if settings.get("hooks"):
            # Refuse to silently mix representations; let the owner choose migration.
            if not uninstall:
                raise ValueError("INLINE_HOOKS_EXIST: review and consolidate before installing hooks.json")
        if settings.get("features", {}).get("hooks") is False:
            warnings.append("HOOKS_DISABLED_IN_CONFIG")
    updated = without_ours(config)
    if not uninstall:
        for event, groups in definition(home).items():
            if updated["hooks"].get(event):
                warnings.append("OTHER_" + event.upper() + "_HOOKS_REQUIRE_CONFLICT_REVIEW")
            updated["hooks"].setdefault(event, []).extend(groups)
    changed = updated != config
    backup = None
    if changed:
        if path.exists():
            backup = path.with_name("hooks.json.ipr-backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
            shutil.copy2(path, backup)
        save(path, updated)
    result = {"installed": not uninstall, "changed": changed, "config": str(path),
        "backup": str(backup) if backup else None, "warnings": warnings,
        "protection": "not_enabled_until_native_trust_and_desktop_smoke_test" if not uninstall else "uninstalled",
        "native_trust": "User must review and trust these exact definitions through Codex /hooks; never bypass trust.",
        "desktop_smoke": "not_run"}
    save(home / "lc-ipr-guard" / "installation.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    print(json.dumps({"hooks": definition(args.codex_home)} if args.preview else install(args.codex_home, uninstall=args.uninstall),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
