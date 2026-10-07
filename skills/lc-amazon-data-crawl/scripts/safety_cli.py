#!/usr/bin/env python3
"""Inspect or clear the machine-wide crawler safety state.

  safety_cli.py status
  safety_cli.py guard
  safety_cli.py clear --confirm-reviewed

``clear`` removes an expired risk pause after the user confirmed the browser
shows normal Amazon/SellerSprite pages.  It never shortens an active pause.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from browser_runtime import pid_is_running
from safety_control import LocalSafetyController


def _pid_alive(pid: object) -> bool:
    try:
        value = int(pid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return value > 0 and pid_is_running(value)


def status(controller: LocalSafetyController) -> int:
    now = dt.datetime.now().replace(microsecond=0)
    pause = controller._load_pause()
    traffic = controller._load_traffic()
    holder = controller.lock_holder()
    running = controller.lock_is_held()
    report = {
        "risk_pause": None,
        "crawler_running": running,
        "running_pid": holder.get("pid") if running else None,
        "running_job": holder.get("job") if running else None,
        "rest_until": traffic.get("rest_until"),
        "next_allowed_at": traffic.get("next_allowed_at"),
        "navigation_attempts_global": int(traffic.get("actions_count") or 0),
        "pause_file": str(controller.pause_path),
    }
    if pause:
        not_before = controller._parse_iso(pause.get("not_before"))
        report["risk_pause"] = {
            "platform": pause.get("platform"),
            "reason": pause.get("reason"),
            "kind": pause.get("kind"),
            "detected_at": pause.get("detected_at"),
            "not_before": pause.get("not_before"),
            "expired": bool(not_before and now >= not_before),
            "job": pause.get("job"),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def guard(controller: LocalSafetyController) -> int:
    """Refuse before touching the browser when another crawl owns this machine."""
    # The lock itself is the truth; the holder record is only for the message.
    holder = controller.lock_holder()
    if controller.lock_is_held():
        print(
            f"本机已有采集进程在运行（进程 {holder.get('pid')}，任务 {holder.get('job') or '未知'}）；"
            "未启动浏览器，也未开始新任务。",
            file=sys.stderr,
        )
        return 50
    return 0


def clear(controller: LocalSafetyController, confirmed: bool) -> int:
    pause = controller._load_pause()
    if pause is None:
        print("当前没有风险暂停。")
        return 0
    not_before = controller._parse_iso(pause.get("not_before"))
    now = dt.datetime.now().replace(microsecond=0)
    if not_before and now < not_before:
        print(f"风险暂停尚未到期（{not_before.isoformat(sep=' ')}），不能提前解除。", file=sys.stderr)
        return 21
    if not confirmed:
        print("需要用户确认浏览器已恢复正常后，加 --confirm-reviewed 再执行。", file=sys.stderr)
        return 30
    controller.pause_path.unlink(missing_ok=True)
    print(f"已解除风险暂停（{pause.get('platform')}/{pause.get('reason')}）。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="本机采集安全状态")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("guard")
    clear_parser = sub.add_parser("clear")
    clear_parser.add_argument("--confirm-reviewed", action="store_true")
    args = parser.parse_args()
    controller = LocalSafetyController()
    if args.command == "status":
        return status(controller)
    if args.command == "guard":
        return guard(controller)
    return clear(controller, args.confirm_reviewed)


if __name__ == "__main__":
    raise SystemExit(main())
