"""Small macOS foreground checks. Unknown state is never treated as unlocked."""
from __future__ import annotations

import plistlib
import datetime as dt
import os
import subprocess
import sys
import time

from run_outcome import CrawlStop, EXIT_NEEDS_HUMAN


class DesktopUnavailable(CrawlStop):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason, exit_code=EXIT_NEEDS_HUMAN,
                         next_action="保持电脑解锁和专用采集窗口可见后，恢复同一任务。")


def start_foreground_power_assertion(runtime):
    """Keep a dedicated foreground awake only for this supervisor's lifetime."""
    if sys.platform != "darwin" or not getattr(runtime, "sellersprite_required", False):
        return None
    return subprocess.Popen(
        ["/usr/bin/caffeinate", "-di", "-w", str(os.getpid())],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def stop_foreground_power_assertion(process):
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        # caffeinate -w also releases the assertion when this supervisor exits.
        pass


def desktop_state() -> str:
    if sys.platform != "darwin":
        return "unsupported"
    try:
        result = subprocess.run(["/usr/sbin/ioreg", "-n", "Root", "-d1", "-a"],
                                capture_output=True, timeout=3, check=True)
        roots = plistlib.loads(result.stdout)
        def find(value):
            if isinstance(value, dict):
                if isinstance(value.get("IOConsoleLocked"), bool):
                    return "locked" if value["IOConsoleLocked"] else "unlocked"
                for child in value.values():
                    state = find(child)
                    if state:
                        return state
            elif isinstance(value, list):
                for child in value:
                    state = find(child)
                    if state:
                        return state
            return None
        return find(roots) or "unknown"
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unknown"


def activate_browser(pid: int) -> bool:
    if sys.platform != "darwin":
        return False
    script = ("ObjC.import('AppKit'); var app = $.NSRunningApplication."
              f"runningApplicationWithProcessIdentifier({int(pid)}); "
              "app ? Boolean(app.activateWithOptions(3)) : false;")
    try:
        result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", script],
                                capture_output=True, text=True, timeout=3)
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def wait_for_desktop(runtime, stop_event=None) -> None:
    state = desktop_state()
    if state == "unsupported":
        return
    budget = max(float(getattr(runtime, "manual_pause_timeout", 900)), 0)
    deadline = time.monotonic() + budget
    wall_deadline = time.time() + budget
    waited = False
    def remaining():
        return min(deadline - time.monotonic(), wall_deadline - time.time())
    while state == "locked":
        seconds = remaining()
        if seconds <= 0:
            raise DesktopUnavailable("desktop_wait_timeout")
        waited = True
        safety = getattr(runtime, "safety", None)
        if safety:
            safety.heartbeat("manual_wait", until=dt.datetime.fromtimestamp(wall_deadline).isoformat(timespec="seconds"), detail="电脑锁屏；解锁后自动复核继续")
        if stop_event is not None:
            if stop_event.wait(min(2, seconds)):
                raise DesktopUnavailable("desktop_wait_cancelled")
        else:
            time.sleep(min(2, seconds))
        state = desktop_state()
    if waited and remaining() <= 0:
        raise DesktopUnavailable("desktop_wait_timeout")
    if state != "unlocked":
        raise DesktopUnavailable("desktop_locked" if state == "locked" else "desktop_state_unknown")


def ensure_page_desktop(driver, runtime, stop_event=None, *, wall_clock=False) -> float:
    """Pause active loading when a desktop locks, before reading more DOM."""
    if not getattr(driver, "is_cdp_driver", False) or not getattr(runtime, "sellersprite_required", False):
        return 0.0
    state = desktop_state()
    if state in {"unlocked", "unsupported"}:
        return 0.0
    clock = time.time if wall_clock else time.monotonic
    started = clock()
    wait_for_desktop(runtime, stop_event)
    driver.set_foreground_runtime(runtime, stop_event)
    driver.prepare_foreground()
    return max(0.0, clock() - started)
