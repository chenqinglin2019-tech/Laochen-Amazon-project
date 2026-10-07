"""Bounded local CDP probes and exact-profile browser recovery."""
from __future__ import annotations

import json
import argparse
import os
import signal
import subprocess
import time
import uuid
from urllib.parse import urlparse

from desktop_runtime import activate_browser, desktop_state
from start_cdp_browser import browser_settings, browser_version_info, resolve_chrome_binary, debugger_port, start_browser


def process_table():
    rows = subprocess.check_output(["ps", "-axo", "pid=,ppid=,lstart=,command="], text=True, timeout=3).splitlines()
    table = {}
    for row in rows:
        parts = row.strip().split(None, 7)
        if len(parts) != 8:
            continue
        pid, parent = int(parts[0]), int(parts[1])
        table[pid] = (parent, parts[7], " ".join(parts[2:7]))
    return table


def dedicated_processes(config):
    """Match executable, profile, PID and creation time, then current descendants."""
    binary = str(resolve_chrome_binary(config).resolve())
    settings = browser_settings(config)
    profile = str(settings[0].resolve())
    port = debugger_port(settings[2])
    table = process_table()
    roots = []
    for pid, (_, command, _) in table.items():
        if command.startswith(binary + " ") and "--type=" not in command and (
            "--user-data-dir=" + profile + " " in command + " "
        ) and ("--remote-debugging-port=" + str(port) + " " in command + " "):
            roots.append(pid)
    if len(roots) != 1:
        return {}
    selected = {roots[0]}
    while True:
        children = {pid for pid, (parent, _, _) in table.items() if parent in selected}
        if children <= selected:
            break
        selected |= children
    return {pid: table[pid] for pid in selected}


class LocalCdp:
    def __init__(self, address):
        import websocket  # Already a Selenium dependency; no new package.
        info = browser_version_info(address)
        if not info:
            raise RuntimeError("browser_endpoint_unavailable")
        url = info.get("webSocketDebuggerUrl", "")
        if urlparse(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("browser_endpoint_not_local")
        self.socket = websocket.create_connection(url, timeout=3, suppress_origin=True)
        self.sequence = 0

    def call(self, method, params=None, session=None, timeout=3):
        self.sequence += 1
        request = {"id": self.sequence, "method": method, "params": params or {}}
        if session:
            request["sessionId"] = session
        self.socket.send(json.dumps(request))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.socket.settimeout(max(deadline - time.monotonic(), 0.01))
            response = json.loads(self.socket.recv())
            if response.get("id") != self.sequence:
                continue
            if "error" in response:
                raise RuntimeError(str(response["error"]))
            return response.get("result") or {}
        raise TimeoutError(method)

    def close(self):
        self.socket.close()


def probe_browser(config):
    """A missing frame alone is inconclusive. Two browser-level failures differ."""
    state = desktop_state()
    if state != "unlocked":
        return {"status": "unknown", "reason": "desktop_" + state}
    processes = dedicated_processes(config)
    if not processes:
        return {"status": "unknown", "reason": "browser_identity_unconfirmed"}
    root = next(pid for pid, (parent, _, _) in processes.items() if parent not in processes)
    if not activate_browser(root):
        return {"status": "unknown", "reason": "browser_activation_unavailable"}
    _, _, address, _ = browser_settings(config)
    failures = 0
    for _ in range(2):
        cdp = None
        try:
            cdp = LocalCdp(address)
            cdp.call("Browser.getVersion")
            try:
                identities = cdp.call("SystemInfo.getProcessInfo").get("processInfo", [])
            except Exception:
                return {"status": "unknown", "reason": "browser_process_identity_unavailable"}
            # Fixed-port launches need not create DevToolsActivePort. Match the
            # actual endpoint PID to the executable/profile/creation-time root.
            if not any(p.get("type") == "browser" and int(p.get("id", 0)) == root for p in identities):
                return {"status": "unknown", "reason": "browser_profile_endpoint_mismatch"}
            break
        except Exception:
            failures += 1
        finally:
            if cdp:
                cdp.close()
    if failures == 2:
        return {"status": "browser_unresponsive", "reason": "two_browser_cdp_failures"}
    cdp = None
    target = None
    try:
        cdp = LocalCdp(address)
        target = cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = cdp.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        cdp.call("Page.bringToFront", session=session)
        token = uuid.uuid4().hex
        expression = ("new Promise(resolve => { let n=0; const end=setTimeout(()=>resolve({frames:n,hidden:document.hidden}),1800);"
                      "document.body.style.background='#d5f4df'; document.title='LC recovery probe';"
                      f"window.name='__lc_recovery_probe__{token}'; "
                      "function tick(){if(++n>=2){clearTimeout(end);resolve({frames:n,hidden:document.hidden});}else requestAnimationFrame(tick);}requestAnimationFrame(tick);})")
        result = cdp.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True}, session, 3)
        value = result.get("result", {}).get("value") or {}
        if value.get("frames", 0) < 2 or value.get("hidden") is not False:
            return {"status": "unknown", "reason": "probe_render_not_confirmed", "probe": value}
        cdp.call("Page.captureScreenshot", {"format": "png"}, session, 3)
        return {"status": "healthy", "reason": "local_probe_passed", "probe": value}
    except Exception as exc:
        return {"status": "unknown", "reason": "probe_failed", "error_type": type(exc).__name__}
    finally:
        if cdp:
            if target:
                try:
                    cdp.call("Target.closeTarget", {"targetId": target})
                except Exception:
                    pass
            cdp.close()


def restart_dedicated_browser(config):
    if desktop_state() != "unlocked":
        raise RuntimeError("desktop_not_unlocked")
    original = dedicated_processes(config)
    if not original:
        raise RuntimeError("browser_identity_unconfirmed")
    root = next(pid for pid, (parent, _, _) in original.items() if parent not in original)
    # Signal the root first and allow Chrome to close its own subprocesses.
    os.kill(root, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = process_table()
        if not any(current.get(pid, ())[1:] == identity[1:] for pid, identity in original.items()):
            break
        time.sleep(0.2)
    current = process_table()
    forced = []
    for pid in sorted(current, reverse=True):
        if pid in original and current[pid][1:] == original[pid][1:]:
            os.kill(pid, signal.SIGKILL)
            forced.append(pid)
    time.sleep(0.2)
    current = process_table()
    if any(current.get(pid, ())[1:] == identity[1:] for pid, identity in original.items()):
        raise RuntimeError("dedicated_browser_did_not_exit")
    start_browser(config)
    return {"terminated_root": root, "forced_pids": forced}


def main():
    from start_cdp_browser import load_config
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--action", required=True, choices=("probe", "restart"))
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        result = probe_browser(config) if args.action == "probe" else restart_dedicated_browser(config)
        print(json.dumps(result))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "unknown", "reason": "recovery_failed", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
