"""Read-only host/process diagnostics; this is not a cloud authorization gate."""
from __future__ import annotations

import ctypes
import platform
import struct
import subprocess
import sys

_ARCH = {"arm64": "arm64", "aarch64": "arm64", "amd64": "x64", "x86_64": "x64", "x86": "x86", "i386": "x86", "i686": "x86"}


def _sysctl(name):
    try:
        result = subprocess.run(["/usr/sbin/sysctl", "-in", name], capture_output=True,
                                text=True, encoding="utf-8", timeout=3, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _windows_architectures():
    """IsWow64Process2 distinguishes ARM hosts, x64 emulation and 32-bit Python."""
    try:
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        get_process = kernel.GetCurrentProcess
        get_process.restype = wintypes.HANDLE
        query = kernel.IsWow64Process2
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.USHORT), ctypes.POINTER(wintypes.USHORT)]
        query.restype = wintypes.BOOL
        process, native = wintypes.USHORT(), wintypes.USHORT()
        if not query(get_process(), ctypes.byref(process), ctypes.byref(native)):
            return "unknown", "unknown"
        values = {0x014c: "x86", 0x8664: "x64", 0xAA64: "arm64"}
        return values.get(native.value, "unknown"), values.get(process.value or native.value, "unknown")
    except (AttributeError, OSError):
        return "unknown", "unknown"


def classify_platform(*, system, os_version="", os_build=None, host_arch="unknown",
                      process_arch="unknown", process_bits=0, translation="none"):
    """Pure support policy, independently testable without impersonating an OS."""
    name = {"Darwin": "macos", "Windows": "windows"}.get(system, system.lower())
    result = {"system": name, "os_version": os_version, "os_build": os_build,
              "host_arch": host_arch, "process_arch": process_arch, "process_bits": process_bits,
              "translation": translation, "compatible": False, "status": "unsupported",
              "reasons": [], "auth_binary_name": None, "native_validation": "not_run"}
    if process_bits != 64:
        result["reasons"].append("PROCESS_64_BIT_REQUIRED")
    elif name == "macos":
        try:
            major = int(os_version.split(".")[0])
        except (ValueError, AttributeError):
            major = 0
        if major < 14:
            result["reasons"].append("MACOS_14_OR_LATER_REQUIRED")
        elif (host_arch, process_arch, translation) in {
                ("arm64", "arm64", "none"), ("x64", "x64", "none"),
                ("arm64", "x64", "rosetta")}:
            result.update(compatible=True, status="compatible_pending_native_validation",
                          auth_binary_name="lc-ipr-auth-check-darwin-" + ("arm64" if process_arch == "arm64" else "amd64"))
        else:
            result["reasons"].append("MAC_ARCHITECTURE_UNVERIFIED")
    elif name == "windows":
        if host_arch != "x64" or process_arch != "x64" or translation != "none":
            result["reasons"].append("WINDOWS_NATIVE_X64_REQUIRED")
        elif os_build not in {19045, 26100, 26200}:
            result["reasons"].append("WINDOWS_VERSION_NOT_IN_VALIDATED_TARGETS")
        else:
            result.update(compatible=True, status="compatible_pending_native_validation",
                          auth_binary_name="lc-ipr-auth-check-windows-amd64.exe")
            result["windows_release"] = {19045: "10 22H2", 26100: "11 24H2", 26200: "11 25H2"}[os_build]
    else:
        result["reasons"].append("FULL_WORKFLOW_PLATFORM_NOT_SUPPORTED")
    return result


def inspect_platform():
    system = platform.system()
    process = _ARCH.get(platform.machine().lower(), "unknown")
    host, translation, build = process, "none", None
    version = platform.release()
    if system == "Darwin":
        version = platform.mac_ver()[0]
        translated = _sysctl("sysctl.proc_translated")
        hardware_arm = _sysctl("hw.optional.arm64")
        if translated == "1":
            host, translation = "arm64", "rosetta"
        elif hardware_arm == "1":
            host = "arm64"
            if process != "arm64":
                translation = "unknown"
    elif system == "Windows":
        host, process = _windows_architectures()
        try:
            win = sys.getwindowsversion()
            version, build = f"{win.major}.{win.minor}.{win.build}", win.build
        except AttributeError:
            pass
        if host != process:
            translation = "emulated" if host != "unknown" and process != "unknown" else "unknown"
    return classify_platform(system=system, os_version=version, os_build=build,
                             host_arch=host, process_arch=process,
                             process_bits=struct.calcsize("P") * 8, translation=translation)
