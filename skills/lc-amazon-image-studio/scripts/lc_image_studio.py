#!/usr/bin/env python3
"""V8 entrypoint. Route historical projects without importing or modifying V7."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def option(argv, name):
    for index, value in enumerate(argv):
        if value.startswith(name + "="):
            return value.split("=", 1)[1]
        if value == name and index + 1 < len(argv):
            return argv[index + 1]
    return None


def route(argv):
    requested = option(argv, "--workflow-policy")
    if requested not in (None, "one_pass_v1", "legacy"):
        raise ValueError("UNKNOWN_WORKFLOW_POLICY")
    manifest = option(argv, "--manifest")
    if manifest:
        data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("MANIFEST_MUST_BE_OBJECT")
        policy = data.get("workflow_policy")
        if requested and requested != (policy or "legacy"):
            raise ValueError("WORKFLOW_POLICY_CONFLICT: no automatic migration")
    else:
        policy = requested or "one_pass_v1"
    if policy in (None, "legacy"):
        return "legacy"
    if policy != "one_pass_v1":
        raise ValueError("UNKNOWN_WORKFLOW_POLICY")
    return "one_pass_v1"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        selected = route(argv)
        if selected == "legacy":
            forwarded = []
            skip = False
            for value in argv:
                if skip:
                    skip = False
                elif value == "--workflow-policy":
                    skip = True
                elif not value.startswith("--workflow-policy="):
                    forwarded.append(value)
            return subprocess.run([sys.executable, str(SCRIPT_DIR / "lc_image_pipeline.py"),
                                   *forwarded], check=False).returncode
        if sys.version_info < (3, 11):
            raise ValueError("PYTHON_3_11_REQUIRED: use python3.12 or py -3.12")
        from lc_one_pass import run
        return run(argv)
    except (OSError, ValueError, ImportError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
