"""Layout runtime doctor for `runtime_bootstrap verify`.

Same checks as `lc_layout.py --doctor`, but loaded through lc_layout_style first so
the runtime discovery accepts a pinned Chrome for Testing build that prints
nothing for `--version` (common on Windows) when its version manifest or the
Playwright revision confirms it. Prints one JSON object; exit 0 when passed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True

import lc_layout_style  # noqa: E402,F401  installs the Chromium detection fallback
import lc_layout  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    result = lc_layout.doctor()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
