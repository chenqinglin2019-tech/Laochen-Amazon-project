#!/usr/bin/env python3
"""Credential-safe entry point for the bundled CLI; Python 3.9+, no dependencies.

Config is authoritative, never merged with ambient credentials. Public responses
are parsed, redacted JSON. Raw subprocess logs and exception text stay private.
"""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import tempfile
from urllib.parse import quote, quote_plus, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITES = ("US", "UK", "CA", "IN", "JP", "DE", "FR", "IT", "ES")
ENV_KEYS = ("LAOCHEN_BACKEND_URL", "LAOCHEN_BACKEND_TOKEN")
REDACTED = "[REDACTED]"


class BackendError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def load_config(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=_reject_constant)
    except (OSError, ValueError):
        raise BackendError("config_unreadable", "Cannot read config.json as UTF-8 JSON; check the file and permissions.") from None
    if not isinstance(data, dict):
        raise BackendError("config_invalid", "config.json must contain a JSON object.")
    for key in ("backend_url", "backend_token"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise BackendError("config_missing", "Configure a nonempty string for %s before a backend request." % key)
        if value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise BackendError("config_invalid", "%s contains whitespace at its edges or control characters." % key)
    try:
        url = urlsplit(data["backend_url"])
        valid_url = url.scheme in ("http", "https") and bool(url.hostname) and url.username is None and url.password is None
        url.port  # Reject malformed ports without exposing the URL in an exception.
    except ValueError:
        valid_url = False
    if not valid_url:
        raise BackendError("config_invalid", "backend_url must be an HTTP(S) address without embedded credentials.")
    return {key: data[key] for key in ("backend_url", "backend_token")}


def select_cli():
    system, machine = platform.system(), platform.machine().lower()
    names = {("Darwin", "arm64"): "darwin-arm64", ("Darwin", "aarch64"): "darwin-arm64",
             ("Darwin", "x86_64"): "darwin-amd64", ("Darwin", "amd64"): "darwin-amd64",
             ("Linux", "x86_64"): "linux-amd64", ("Linux", "amd64"): "linux-amd64",
             ("Windows", "amd64"): "windows-amd64.exe", ("Windows", "x86_64"): "windows-amd64.exe"}
    suffix = names.get((system, machine))
    if suffix is None:
        raise BackendError("unsupported_platform", "No bundled CLI is available for this OS/architecture.")
    return ROOT / "tools" / "bin" / ("laochen-cli-" + suffix)


def _clear_quarantine(path):
    # Python exposes os.listxattr on Linux, but not on all macOS builds.
    listing = subprocess.run(["/usr/bin/xattr", str(path)], capture_output=True, timeout=10, check=False)
    if listing.returncode != 0:
        raise OSError("Cannot inspect quarantine")
    if b"com.apple.quarantine" in listing.stdout.splitlines():
        removed = subprocess.run(["/usr/bin/xattr", "-d", "com.apple.quarantine", str(path)],
                                 capture_output=True, timeout=10, check=False)
        if removed.returncode != 0:
            raise OSError("Cannot remove quarantine")


def prepare_cli(path):
    if not path.is_file():
        raise BackendError("cli_missing", "CLI executable is missing; check the Skill installation or --cli path.")
    try:
        if platform.system() != "Windows" and not path.stat().st_mode & stat.S_IXUSR:
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        if platform.system() == "Darwin":
            _clear_quarantine(path)
    except (OSError, subprocess.TimeoutExpired):
        raise BackendError("cli_permissions", "Cannot prepare CLI permissions for execution.") from None


def redact(value, secrets):
    """Redact parsed data, including escaped/URL-encoded forms in nested strings."""
    if isinstance(value, dict):
        return {redact(key, secrets): REDACTED if re.search(r"token|password|secret|authorization|backend_url", key, re.I)
                else redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        forms = set()
        for secret in secrets:
            if secret:
                forms.update((secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1],
                              quote(secret, safe=""), quote_plus(secret, safe=""), secret.replace("/", "\\/")))
        for secret in sorted(forms, key=len, reverse=True):
            value = value.replace(secret, REDACTED)
        value = re.sub(r"(?i)Bearer\s+\S+", "Bearer " + REDACTED, value)
    return value


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent),
                                         prefix="." + path.name + ".", delete=False) as handle:
            temporary = handle.name
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def run_cli(command, *, site, asins=None, keywords_file=None, listing_file=None,
            output=None, config=None, cli=None, timeout=None):
    """Return only safe data; exit_code is the actual child code, or None if absent.

    Explicit CLI/config paths support existing installations and offline tests.
    No credential flags, shell execution, environment fallback, or auto retries.
    """
    result = {"exit_code": None, "response": None}
    try:
        if command not in ("expand", "qa", "validate") or site not in SITES:
            raise BackendError("invalid_arguments", "Choose expand/qa/validate and an explicit supported site.")
        if command == "qa" and site != "US":
            raise BackendError("qa_us_only", "The current QA connector accepts US only; record the documented local skip for other sites.")
        timeout = (120 if command == "validate" else None) if timeout is None else timeout
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0):
            raise BackendError("invalid_arguments", "Timeout must be a finite positive number of seconds.")
        config_path = (Path(config) if config is not None else ROOT / "config.json").resolve()
        credentials = load_config(config_path)
        environment = os.environ.copy()
        secrets = list(credentials.values()) + [environment.get(key) for key in ENV_KEYS]
        environment.update(zip(ENV_KEYS, (credentials["backend_url"], credentials["backend_token"])))
        executable = Path(cli).resolve() if cli is not None else select_cli()
        arguments = [str(executable), command, "--site", site]
        input_path = None
        if command == "expand":
            if not isinstance(asins, str) or not asins.strip():
                raise BackendError("invalid_arguments", "expand requires --asins.")
            arguments += ["--asins", asins]
        else:
            source = keywords_file if command == "qa" else listing_file
            if source is None or not Path(source).is_file():
                raise BackendError("input_missing", "The required keywords/listing JSON file does not exist.")
            input_path = Path(source).resolve()
            if input_path in (config_path, executable):
                raise BackendError("invalid_arguments", "A credential file or executable cannot be used as product input.")
            arguments += ["--keywords-file" if command == "qa" else "--listing-file", str(input_path)]
        output_path = Path(output).resolve() if output is not None else None
        if output_path is not None and output_path in (config_path, executable, input_path):
            raise BackendError("invalid_output", "Output must not overwrite config, CLI, or source input.")
        prepare_cli(executable)
        # The CLI never receives the final task path. A private temporary file
        # prevents its raw --output response from bypassing the redaction step.
        with tempfile.TemporaryDirectory(prefix="listing-backend-") as directory:
            raw_path = Path(directory) / "response.json"
            if command != "validate":
                arguments += ["--output", str(raw_path)]
            try:
                completed = subprocess.run(arguments, env=environment, shell=False, capture_output=True,
                                           text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
            except subprocess.TimeoutExpired:
                raise BackendError("cli_timeout", "CLI timed out; no automatic retry was made. Check task state before retrying.") from None
            except OSError:
                raise BackendError("cli_unavailable", "CLI could not be executed; check its path, platform and permissions.") from None
            result["exit_code"] = completed.returncode
            try:
                # expand/qa require the full --output file; stdout may be truncated.
                raw = raw_path.read_text(encoding="utf-8-sig") if command != "validate" else completed.stdout
                response = json.loads(raw, parse_constant=_reject_constant)
                if not isinstance(response, dict):
                    raise ValueError("Expected a JSON object")
            except (OSError, ValueError, TypeError):
                raise BackendError("response_invalid", "CLI did not provide the required JSON object; raw logs are withheld to protect credentials.") from None
            result["response"] = redact(response, secrets)
        if output_path is not None:
            _write_json(output_path, result["response"])
        if completed.returncode != 0:
            raise BackendError("cli_failed", "CLI exited unsuccessfully; inspect its exit code and redacted response.")
        if command == "validate":
            failed = response.get("ok") is not True or response.get("errors") != []
        else:
            failed = (response.get("ok") is False or response.get("success") is False
                      or bool(response.get("error")) or bool(response.get("errors"))
                      or str(response.get("status", "")).lower() in ("failed", "error", "cancelled"))
        if failed:
            raise BackendError("backend_rejected", "Backend reported failure; the redacted response is retained.")
    except BackendError as error:
        result.update(error_code=error.code, failure_reason=str(error))
    except (OSError, ValueError, TypeError):
        result.update(error_code="local_io_error", failure_reason="Local input/output failed; check paths and permissions. Raw exception text is withheld.")
    return result


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes rejected arguments, which may be credentials.
        self.exit(2, "Invalid arguments; use --help. Supply credentials only through the config file.\n")


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("expand", "qa", "validate"):
        command = commands.add_parser(name)
        command.add_argument("--site", required=True, choices=SITES)
        command.add_argument("--asins" if name == "expand" else "--keywords-file" if name == "qa" else "--listing-file", required=True)
        command.add_argument("--output", required=name != "validate")
        command.add_argument("--config", help="Config file path; defaults to this Skill's config.json")
        command.add_argument("--cli", help="Optional executable path; otherwise selected for the current platform")
        command.add_argument("--timeout", type=float, help="Seconds; expand/qa keep CLI polling limits, validate defaults to 120")
    args = parser.parse_args(argv)
    result = run_cli(**vars(args))
    success = result["exit_code"] == 0 and "failure_reason" not in result
    summary = {"command": args.command, "status": "completed" if success else "failed",
               "exit_code": result["exit_code"]}
    if "failure_reason" in result:
        summary.update(error_code=result["error_code"], message=result["failure_reason"])
    if args.command == "validate" and args.output is None:
        summary["response"] = result["response"]
    print(json.dumps(summary, ensure_ascii=False))
    if success:
        return 0
    return result["exit_code"] if isinstance(result["exit_code"], int) and result["exit_code"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
