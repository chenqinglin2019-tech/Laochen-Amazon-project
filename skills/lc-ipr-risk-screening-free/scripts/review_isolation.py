"""Isolation backends for the final-review host.

``macos-sandbox`` keeps the original kernel read boundary (``sandbox-exec``) and is
unchanged. ``tool-free-process`` is the only backend available off macOS: the same
``codex exec`` command with every tool, plugin and MCP disabled, one fresh temporary
workspace per session, and the host's trace check that rejects any event other than
an agent message, reasoning or error (``report_review_host.parse_agent_trace``).
It has no kernel-level read denial and says so in every audit it writes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

MACOS = "macos-sandbox"
TOOL_FREE = "tool-free-process"
BACKENDS = ("auto", MACOS, TOOL_FREE)
METHOD_MACOS = "macos_sandbox_exec"
METHOD_TOOL_FREE = "tool_free_process"
POLICY_SCHEMA = "IPR-REVIEW-ISOLATION-POLICY/1.0"
SETTINGS_FILE = Path(__file__).resolve().parent.parent / "references" / "review-host.json"
MACOS_DEFAULT_BINARY = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
# Every feature the review command turns off; the policy file records them and the validator requires them.
DISABLED_FEATURES = ("shell_snapshot", "shell_tool", "unified_exec", "code_mode_host", "code_mode",
                     "code_mode_only", "plugins", "remote_plugin", "skill_search",
                     "skill_mcp_dependency_install", "apps", "unbounded_connection_retries")
_DEFAULT_SETTINGS = {"model": "gpt-6-astra", "model_context_window": 872000,
                     "model_auto_compact_token_limit": 800000, "model_reasoning_effort": "medium",
                     "provider_base_url": "https://chatgpt.com/backend-api/codex",
                     "tool_free_codex_sandbox": "read-only"}
# Only consulted by tool-free-process. If a Windows Codex build rejects read-only at startup the
# smoke test may switch it; every tool stays disabled and the trace check still applies.
TOOL_FREE_SANDBOX_MODES = ("read-only", "danger-full-access")
_WRAPPER_SUFFIXES = {".cmd", ".bat", ".ps1"}
_hash_cache: dict[tuple[str, int, int], str] = {}


def macos_sandbox_available() -> bool:
    return sys.platform == "darwin" and SANDBOX_EXEC.is_file()


def select_backend(requested: str = "auto") -> str:
    if requested not in BACKENDS:
        raise ValueError("REVIEW_ISOLATION_BACKEND_INVALID")
    if requested == MACOS or (requested == "auto" and sys.platform == "darwin"):
        # A Mac never falls back silently: the kernel boundary is the documented default there.
        if not macos_sandbox_available():
            raise ValueError("REPORT_REVIEW_HOST_MACOS_SANDBOX_REQUIRED")
        return MACOS
    return TOOL_FREE


def review_settings() -> dict:
    """Model settings; the shipped defaults equal the values this host always used."""
    settings = dict(_DEFAULT_SETTINGS)
    if SETTINGS_FILE.is_file():
        try:
            loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("REVIEW_HOST_SETTINGS_INVALID") from None
        if not isinstance(loaded, dict) or loaded.get("schema") != "IPR-REVIEW-HOST-SETTINGS/1.0":
            raise ValueError("REVIEW_HOST_SETTINGS_INVALID")
        settings.update({key: loaded[key] for key in _DEFAULT_SETTINGS if key in loaded})
    for key in ("model_context_window", "model_auto_compact_token_limit"):
        if type(settings[key]) is not int or settings[key] <= 0:
            raise ValueError("REVIEW_HOST_SETTINGS_INVALID")
    if not all(isinstance(settings[key], str) and settings[key] for key in
               ("model", "model_reasoning_effort", "provider_base_url")):
        raise ValueError("REVIEW_HOST_SETTINGS_INVALID")
    if settings["tool_free_codex_sandbox"] not in TOOL_FREE_SANDBOX_MODES:
        raise ValueError("REVIEW_HOST_SETTINGS_INVALID")
    return settings


def resolve_codex_binary(explicit, backend: str) -> Path:
    """--codex-binary, then LC_IPR_CODEX_BINARY, then (off macOS) a native codex on PATH."""
    candidate = explicit or os.environ.get("LC_IPR_CODEX_BINARY")
    if not candidate:
        if backend == MACOS or sys.platform == "darwin":
            candidate = MACOS_DEFAULT_BINARY
        else:
            candidate = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if not candidate:
        raise ValueError("REPORT_REVIEW_HOST_NATIVE_CLI_REQUIRED: pass --codex-binary or set LC_IPR_CODEX_BINARY")
    path = Path(candidate)
    if path.suffix.lower() in _WRAPPER_SUFFIXES:
        # cmd.exe/PowerShell re-parse the -c settings; only a native executable is accepted.
        raise ValueError("REPORT_REVIEW_HOST_NATIVE_CLI_REQUIRED: a script wrapper is not accepted")
    return path


def _binary_sha256(binary: Path) -> str:
    stat = binary.stat()
    key = (str(binary), stat.st_size, stat.st_mtime_ns)
    if key not in _hash_cache:
        digest = hashlib.sha256()
        with binary.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
        _hash_cache[key] = digest.hexdigest()
    return _hash_cache[key]


def _instruction_files_above(workspace: Path) -> list[str]:
    found = []
    for directory in [workspace, *workspace.parents]:
        for name in ("AGENTS.md", "AGENTS.override.md"):
            if (directory / name).is_file():
                found.append(str(directory / name))
    return found


def login_status(binary: Path, workspace: Path, environment: dict, *, profile: Path | None = None) -> None:
    """Require the existing ChatGPT login; sandboxed on macOS, plain elsewhere."""
    command = ([str(SANDBOX_EXEC), "-f", str(profile)] if profile is not None else []) + [str(binary), "login", "status"]
    result = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=15)
    if result.returncode != 0 or "Logged in using ChatGPT" not in result.stdout + result.stderr:
        raise ValueError("REVIEW_HOST_EXISTING_CHATGPT_LOGIN_REQUIRED")


def write_policy(path: Path, binary: Path, workspace: Path, environment: dict, *, image_names=()) -> dict:
    """Record what a tool-free session was and was not isolated by (no kernel read boundary)."""
    agents = _instruction_files_above(workspace)
    if agents:
        # The model would receive project instructions the host never put in the frozen packet.
        raise ValueError("REVIEW_ISOLATION_INSTRUCTION_FILE_IN_WORKSPACE_PARENTS")
    try:
        version = subprocess.run([str(binary), "--version"], cwd=workspace, env=environment, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=15).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        version = None
    policy = {"schema": POLICY_SCHEMA, "isolation_method": METHOD_TOOL_FREE, "kernel_read_boundary": False,
              "codex_binary": str(binary), "codex_binary_sha256": _binary_sha256(binary), "codex_version": version,
              "disabled_features": list(DISABLED_FEATURES),
              "codex_sandbox_flag": review_settings()["tool_free_codex_sandbox"],
              "workspace": str(workspace), "workspace_files": sorted(p.name for p in workspace.iterdir()),
              "image_attachments": sorted(image_names), "instruction_files_above_workspace": agents,
              "input_transport": "host_stdin",
              "tool_activity_enforcement": "trace_accepts_only_agent_message_reasoning_error"}
    path.write_text(json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return policy


def validate_policy(policy_path: Path, audit: dict) -> None:
    """Validator side of write_policy: a tool-free audit must carry a matching, complete policy."""
    try:
        policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("FINAL_REVIEW_MODULE_ISOLATION_POLICY_INVALID") from None
    if (not isinstance(policy, dict) or policy.get("schema") != POLICY_SCHEMA
            or policy.get("isolation_method") != METHOD_TOOL_FREE or policy.get("kernel_read_boundary") is not False
            or set(policy.get("disabled_features", [])) != set(DISABLED_FEATURES)
            or policy.get("instruction_files_above_workspace") != []
            or audit.get("isolation_method") != METHOD_TOOL_FREE or audit.get("kernel_read_boundary") is not False
            or audit.get("controls") != []):
        raise ValueError("FINAL_REVIEW_MODULE_ISOLATION_POLICY_INVALID")
