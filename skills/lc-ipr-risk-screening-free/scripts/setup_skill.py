#!/usr/bin/env python3
"""Initialize empty local files and inspect/install this Skill's existing dependencies.

No cloud auth, task creation, source request, browser launch or credential output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from urllib.parse import urlsplit

from platform_runtime import inspect_platform

ROOT = Path(__file__).resolve().parents[1]
PYTHON_MIN = (3, 12)
NODE_MIN = 22


def _environment():
    # Installers and dependency probes have no reason to inherit account secrets.
    from common import ENV_CREDENTIALS
    result = {key: value for key, value in os.environ.items()
              if key not in set(ENV_CREDENTIALS.values()) | {"LAOCHEN_BACKEND_URL", "LAOCHEN_AUTH_PASSED", "PYTHONPATH", "PYTHONHOME", "PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PIP_CONFIG_FILE", "PIP_REQUIRE_VIRTUALENV", "npm_config_global", "NPM_CONFIG_GLOBAL"}}
    result.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PIP_CONFIG_FILE=os.devnull, npm_config_global="false")
    return result


def _probe(command, timeout=10):
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", check=False, timeout=timeout, env=_environment())
        return result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.SubprocessError):
        return None, "", ""


def _json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _regular(path):
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _env_rows(text):
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)\s*=\s*(.*)", line)
        if not match or match[1] in result:
            raise ValueError("ENV_TEMPLATE_INVALID")
        value = match[2]
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError("ENV_TEMPLATE_INVALID")
            value = value[1:-1]
        if "\x00" in value:
            raise ValueError("ENV_TEMPLATE_INVALID")
        result[match[1]] = value
    return result


def initialize(root=ROOT):
    """Create only absent files; existing bytes AND permissions are untouched."""
    templates = {"config.json": root / "config.example.json", ".env": root / ".env.example"}
    payloads = {name: path.read_bytes() for name, path in templates.items()}
    config = json.loads(payloads["config.json"].decode("utf-8-sig"))
    if not isinstance(config, dict) or config.get("backend_token") != "":
        raise ValueError("CONFIG_TEMPLATE_MUST_HAVE_EMPTY_TOKEN")
    if any(_env_rows(payloads[".env"].decode("utf-8-sig")).values()):
        raise ValueError("ENV_TEMPLATE_MUST_BE_EMPTY")
    result = []
    for name, data in payloads.items():
        path = root / name
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            result.append({"file": name, "status": "preserved_existing"})
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        result.append({"file": name, "status": "created_empty"})
    return result


def local_file_checks(root=ROOT):
    """Reuse runtime parsing, without allowing a probe to read another install."""
    from common import _backend_config, _local_env_values, CredentialFileError
    import common
    from unittest.mock import patch
    result = {}
    with patch.object(common, "skill_root", return_value=root):
        for name, reader in (("config.json", _backend_config), (".env", _local_env_values)):
            try:
                value = reader()
                if name == "config.json":
                    url = urlsplit(str(value.get("backend_url") or ""))
                    valid_url = url.scheme in {"https", "http"} and bool(url.hostname) and not url.username and not url.password
                    # Match the frozen auth package's truthiness and conversion;
                    # configured only means a value is selected, not authenticated.
                    environment_token = os.environ.get("LAOCHEN_BACKEND_TOKEN")
                    token_source = "environment" if environment_token else "config" if str(value.get("backend_token", "")) else None
                    result[name] = {"status": ("configured" if token_source else "needs_token") if valid_url else "invalid",
                                    "backend_url_valid": bool(valid_url), "token_source": token_source}
                else:
                    values, errors = value
                    result[name] = {"status": "invalid" if errors else "valid",
                                    "configured_fields": sorted(k for k, v in values.items() if v.strip()),
                                    "invalid_fields": sorted(errors)}
            except (CredentialFileError, ValueError, OSError) as exc:
                # CredentialFileError contains fixed value-free codes. Other error texts may not.
                reason = str(exc) if isinstance(exc, CredentialFileError) else "CONFIG_FILE_INVALID"
                result[name] = {"status": "invalid", "reason": reason}
    return result


def python_probe(executable):
    code = ("import json,sys,importlib.util,importlib.metadata; "
            f"sys.path.insert(0,{str(Path(__file__).resolve().parent)!r}); "
            "from platform_runtime import inspect_platform; "
            "s=importlib.util.find_spec('pypdf'); "
            "print(json.dumps({'version':list(sys.version_info[:3]),'executable':sys.executable,'pypdf':bool(s),"
            "'pypdf_version':importlib.metadata.version('pypdf') if s else None,"
            "'is_venv':sys.prefix!=sys.base_prefix,'prefix':sys.prefix,'platform':inspect_platform()}))")
    rc, stdout, _ = _probe([str(executable), "-c", code])
    try:
        value = json.loads(stdout) if rc == 0 else {}
        version = value.get("version", [])
        if not isinstance(version, list) or len(version) != 3 or not all(type(x) is int for x in version):
            return None
        value["supported"] = tuple(version[:2]) >= PYTHON_MIN
        return value
    except (ValueError, TypeError):
        return None


def select_python(root=ROOT, explicit=None):
    local = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    explicit = explicit or os.environ.get("LC_IPR_PYTHON")
    if explicit:
        return str(Path(explicit).expanduser()) if Path(explicit).is_absolute() or "/" in explicit or "\\" in explicit else explicit
    candidates = [str(local), sys.executable, "python3.14", "python3.13", "python3.12", "python3", "python"]
    found = []
    for candidate in dict.fromkeys(candidates):
        if candidate == str(local) and not local.is_file():
            continue
        probe = python_probe(candidate)
        if probe:
            found.append((candidate, probe))
            if probe["supported"]:
                return candidate
    return found[0][0] if found else None


def _browser_check(root, runtime):
    node = shutil.which("node")
    if not node:
        return {"status": "missing_node", "path": None}
    helper = root / "tools/cdp/platform-runtime.mjs"
    rc, text, _ = _probe([node, str(helper), "--chrome", str(runtime.get("cdp", {}).get("chrome_executable") or "")])
    try:
        value = json.loads(text)
        return value if rc == 0 and isinstance(value, dict) else {"status": "missing", "path": None}
    except ValueError:
        return {"status": "probe_failed", "path": None}


def inspect_install(root=ROOT, python=None):
    bootstrap_platform = inspect_platform()
    interpreter = select_python(root, python)
    py = python_probe(interpreter) if interpreter else None
    platform_info = py.get("platform", bootstrap_platform) if py else bootstrap_platform
    node = shutil.which("node")
    rc, stdout, _ = _probe([node, "--version"]) if node else (None, "", "")
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", stdout) if rc == 0 else None
    node_result = {"path": node, "version": match[0].strip() if match else None,
                   "supported": bool(match and int(match[1]) >= NODE_MIN)}
    runtime = _json(root / "references/runtime-config.json")
    browser = _browser_check(root, runtime)
    dependency = root / "tools/cdp/node_modules/playwright-core/package.json"
    expected = _json(root / "tools/cdp/package.json")["dependencies"]["playwright-core"]
    try:
        installed = _json(dependency).get("version")
    except (OSError, ValueError):
        installed = None
    poppler = shutil.which("pdftoppm")
    rc, out, err = _probe([poppler, "-v"]) if poppler else (None, "", "")
    version = re.search(r"pdftoppm version ([0-9.]+)", out + err)
    pdf = {"pdftoppm_path": poppler, "available": rc == 0 and bool(version),
           "version": version[1] if version else None}
    component = platform_info.get("auth_binary_name")
    binary = root / "tools/bin" / component if component else None
    hashes = runtime.get("auth", {}).get("binary_sha256", {})
    auth = {"file": component, "hash_matches": bool(binary and _regular(binary) and
            hashlib.sha256(binary.read_bytes()).hexdigest() == hashes.get(component))}
    files = local_file_checks(root)
    deps_ready = bool(py and py["supported"] and py["pypdf"] and py.get("pypdf_version") == "6.10.0" and node_result["supported"]
                      and installed == expected and browser.get("status") == "available" and pdf["available"])
    configured = files["config.json"]["status"] == "configured" and files[".env"]["status"] == "valid"
    runs = Path(str(runtime.get("default_runs_dir") or "runs-free")).expanduser()
    if not runs.is_absolute():
        runs = root / runs
    ancestor = runs
    while not ancestor.exists() and ancestor.parent != ancestor:
        ancestor = ancestor.parent
    return {"schema": "IPR-INSTALL-CHECK/1.0", "platform": platform_info, "bootstrap_platform": bootstrap_platform, "python": py,
            "node": node_result, "playwright_core": {"expected": expected, "installed": installed},
            "chrome": browser, "pdf_renderer": pdf, "auth_component": auth, "local_files": files,
            "default_runs_dir": str(runs), "runs_parent_writable_hint": os.access(ancestor, os.W_OK),
            "status": "ready_for_auth" if platform_info["compatible"] and deps_ready and configured and auth["hash_matches"] and os.access(ancestor, os.W_OK) else "needs_setup",
            "native_validation": "not_run", "cloud_auth": "not_run", "browser_launch": "not_run",
            "windows_permissions_note": "Windows access control is inherited from the current user's directory; Unix mode 0600 is not an ACL proof." if os.name == "nt" else None}


def install_dependencies(root=ROOT, python=None):
    """Install only existing locked dependencies in local directories; no global pip."""
    executable = select_python(root, python)
    py = python_probe(executable) if executable else None
    if not py or not py["supported"]:
        raise ValueError("PYTHON_3_12_OR_LATER_REQUIRED")
    local = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if (root / ".venv").is_symlink():
        raise ValueError("LINKED_VENV_NOT_ALLOWED")
    if local.exists():
        current = python_probe(local)
        if not current or not current["supported"]:
            raise ValueError("EXISTING_VENV_UNSUPPORTED_NOT_OVERWRITTEN")
    elif (root / ".venv").exists():
        raise ValueError("EXISTING_VENV_INCOMPLETE_NOT_OVERWRITTEN")
    else:
        _run_install([executable, "-m", "venv", str(root / ".venv")], root)
    current = python_probe(local)
    if not current or not current.get("is_venv") or Path(str(current.get("prefix") or "")).resolve() != (root / ".venv").resolve():
        raise ValueError("LOCAL_VENV_IDENTITY_INVALID")
    _run_install([str(local), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(root / "requirements.txt")], root)
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise ValueError("NPM_UNAVAILABLE")
    command = [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefix", str(root / "tools/cdp")]
    if os.name == "nt":
        # Invoke npm's JavaScript entry directly. No cmd.exe quoting, percent
        # expansion or credential-bearing registry text enters a shell.
        node = shutil.which("node")
        npm_cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not node or not npm_cli.is_file():
            raise ValueError("NPM_NODE_ENTRY_UNAVAILABLE")
        command = [node, str(npm_cli), *command[1:]]
    _run_install(command, root / "tools/cdp")
    return {"status": "dependencies_installed", "python": str(local), "global_packages_changed": False,
            "external_requirements": ["Node.js 22 or later", "Google Chrome desktop", "Poppler pdftoppm and its native libraries"]}


def _run_install(command, cwd):
    try:
        result = subprocess.run(command, cwd=cwd, env=_environment(), capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("DEPENDENCY_INSTALL_UNAVAILABLE") from None
    if result.returncode:
        # npm/pip may print authenticated registry URLs: never echo raw output.
        raise ValueError("DEPENDENCY_INSTALL_FAILED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--init", action="store_true")
    action.add_argument("--check", action="store_true")
    action.add_argument("--install-deps", action="store_true")
    parser.add_argument("--python", help="Explicit local Python executable, never shell code")
    args = parser.parse_args()
    try:
        if args.init:
            value = {"status": "initialized", "files": initialize()}
        elif args.install_deps:
            value = install_dependencies(python=args.python)
        else:
            value = inspect_install(python=args.python)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value["status"] not in {"needs_setup"} else 2
    except (ValueError, OSError) as exc:
        reason = str(exc) if re.fullmatch(r"[A-Z][A-Z0-9_]{3,100}", str(exc)) else "SETUP_FAILED_CHECK_LOCAL_PREREQUISITES"
        print(json.dumps({"status": "setup_failed", "reason": reason}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
