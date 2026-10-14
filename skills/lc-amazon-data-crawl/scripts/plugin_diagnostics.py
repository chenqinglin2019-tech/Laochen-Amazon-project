#!/usr/bin/env python3
"""Read-only front-backend diagnostics and explicit interrupted-download review."""
import argparse
import json
import shutil
import sys

from run_outcome import _atomic_write_json, classify_exception
from safety_control import LocalSafetyController, default_safety_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-export", action="store_true")
    parser.add_argument("--confirm-no-active-download", action="store_true")
    args = parser.parse_args()
    path = default_safety_root() / "plugin-export-state.json"
    if args.review_export:
        safety = LocalSafetyController()
        try:
            safety.acquire()
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if not args.confirm_no_active_download:
                print(json.dumps({"pending": data.get("pending"), "next_action":
                    "检查 Chrome 下载，确认没有进行中或另存为待处理的导出后，使用 --confirm-no-active-download。"}, ensure_ascii=False))
                return 30 if data.get("pending") else 0
            data.pop("pending", None)
            _atomic_write_json(path, data)  # Preserve export deadline and consumed IDs.
            return 0
        except Exception as exc:
            outcome = classify_exception(exc)
            print(f"{outcome.status}: {outcome.message}", file=sys.stderr)
            return outcome.exit_code
        finally:
            safety.release()
    print(json.dumps({"front_backend": "opencli", "opencli": shutil.which("opencli") or "missing",
                      "front_testing_browser_required": False,
                      "browser_setup": "日常 Chrome 安装 OpenCLI Bridge 与卖家精灵；用户选好工作页后绑定。",
                      "image_backend": "opencli", "image_testing_browser_required": False,
                      "image_requirement": "找同款前须确认退出卖家精灵登录；不上传图片。",
                      "legacy_modes": "仅类目模式使用现有 CDP 和专用浏览器。"}, ensure_ascii=False, indent=2))
    return 0 if shutil.which("opencli") else 30


if __name__ == "__main__":
    raise SystemExit(main())
