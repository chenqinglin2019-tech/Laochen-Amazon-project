#!/usr/bin/env python3
"""Read-only installation checks. No credentials, account requests or pass writes."""

import argparse
import json
import os
import platform
import subprocess
import sys

# Importing the helper must not create __pycache__ in a fresh recipient install.
sys.dont_write_bytecode = True
import auth_gate


def inspect_installation():
    report = {
        "scope": "installation_only", "system": platform.system(),
        "machine": platform.machine(), "credentials_read": False,
        "network_tested": False, "account_tested": False, "files_changed": False,
        "quarantine_present": None, "issues": [],
    }
    try:
        binary = auth_gate.auth_binary()
        report["binary"] = binary.name
        auth_gate.verify_binary(binary)
    except SystemExit as error:
        report["integrity_ok"] = False
        report["issues"].append(str(error))
        report["installation_ok"] = False
        return report
    report["integrity_ok"] = True
    try:
        report["mode"] = oct(binary.stat().st_mode & 0o777)
        report["readable"] = os.access(binary, os.R_OK)
        report["writable"] = os.access(binary, os.W_OK)
        if platform.system().lower() != "windows":
            report["executable"] = os.access(binary, os.X_OK)
            if not report["executable"]:
                report["issues"].append("EXECUTE_PERMISSION_MISSING: 入口将尝试修复；目录须允许修改组件权限。")
        if platform.system().lower() == "darwin":
            result = subprocess.run(["/usr/bin/xattr", str(binary)], text=True,
                                    encoding="utf-8", capture_output=True, check=True, timeout=10)
            report["quarantine_present"] = "com.apple.quarantine" in result.stdout.splitlines()
            if report["quarantine_present"]:
                report["issues"].append("QUARANTINE_PRESENT: 入口将只清理已校验组件的隔离标记；宿主须允许此操作。")
    except (OSError, UnicodeError, subprocess.SubprocessError):
        report["issues"].append("INSTALLATION_INSPECTION_FAILED: 请检查目录或 /usr/bin/xattr 访问权限。")
    report["installation_ok"] = not report["issues"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output JSON (also the default)")
    parser.parse_args(argv)
    report = inspect_installation()
    # ASCII JSON also works on legacy Windows code pages; no local paths/logs.
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["installation_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
