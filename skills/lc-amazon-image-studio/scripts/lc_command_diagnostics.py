"""Observe existing commands without changing their authentication or QA gates.

The outer CLI calls ``run_observed_command(args, operation)`` after choosing its
normal command path. The operation returns its usual exit code and can expose
``args._command_error`` / ``args._command_result``. Failed staged work may roll
back; observations are then persisted separately through the existing short
manifest lock, never by rewriting that stale staged manifest.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

from lc_inputs import image_input_paths
from lc_runtime_status import (diagnostic_input_fingerprint, record_command_failure,
                               record_command_success, record_interval, _clean_error)


OBSERVED_COMMANDS = {"prepare", "plan", "compose", "postprocess", "qa", "finalize",
                     "review-prepare", "review-submit", "delivery-check", "deliver", "compact"}
_PARAMETERS = {"jobs", "job", "packet", "annotations", "force", "tool_capacity",
               "tool_capacity_source", "tool_capacity_reason"}


def _sha(path):
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError:
        return "MISSING"


def _jsonable(value):
    if isinstance(value, Path):
        return str(value.expanduser().resolve())
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _file_identity(value):
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    try:
        stat = path.stat()
        return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                "inode": stat.st_ino}
    except FileNotFoundError:
        return {"path": str(path), "missing": True}


def runtime_identity():
    """Cheap installed-runtime identity, without running Node/doctor/browser.

    Runtime repair must unlock a repeated failure even when project files did
    not change. These are known rendering paths/package records, never account
    config or credentials; the identity is included only in a digest.
    """
    root = Path(__file__).parent.parent
    dependency = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
    nodes = [os.environ.get("LC_LAYOUT_NODE"), shutil.which("node"), dependency / "node/bin/node"]
    modules = [os.environ.get("LC_LAYOUT_NODE_MODULES"), root / "node_modules", dependency / "node/node_modules"]
    packages = {}
    for module, distribution in (("PIL", "Pillow"), ("numpy", "numpy")):
        spec = importlib.util.find_spec(module)
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = None
        packages[module] = {"version": version, "origin": _file_identity(spec.origin) if spec else None}
    browsers = [os.environ.get("LC_LAYOUT_CHROMIUM")]
    cache_roots = [Path.home() / "Library/Caches/ms-playwright", Path.home() / ".cache/ms-playwright"]
    for name in ("LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH"):
        if os.environ.get(name):
            cache_roots.append(Path(os.environ[name]) / "ms-playwright" if name == "LOCALAPPDATA" else Path(os.environ[name]))
    for cache in cache_roots:
        for pattern in ("chromium*/chrome-headless-shell*/chrome-headless-shell",
                        "chromium*/chrome-headless-shell*/headless_shell.exe", "chromium*/chrome-*/chrome",
                        "chromium*/chrome-*/chrome.exe", "chromium*/chrome-*/Chromium.app/Contents/MacOS/Chromium"):
            browsers.extend(sorted(cache.glob(pattern)))
    return {"python": {"version": sys.version, "executable": _file_identity(sys.executable)},
            "packages": packages, "nodes": [_file_identity(path) for path in nodes if path],
            "playwright": [{"root": str(Path(path).expanduser().resolve()),
                            "package_sha256": _sha(Path(path) / "playwright/package.json")}
                           for path in modules if path],
            "browsers": [_file_identity(path) for path in browsers if path],
            "layout_runtime_sha256": _sha(root / "assets/layout-runtime.json")}


def _selected(manifest, parameters):
    if parameters.get("job"):
        return [parameters["job"]]
    if parameters.get("jobs"):
        return sorted(set(parameters["jobs"]))
    return []  # Historical meaning: command scope is the whole project.


def _paths(manifest, base, jobs, parameters):
    result = image_input_paths(manifest, base, job_ids=set(jobs) if jobs else None)
    for key in ("packet", "annotations"):
        if parameters.get(key):
            result.add((base / Path(parameters[key]).expanduser()).resolve())
    return result


def input_fingerprint(manifest, base, command, jobs, parameters, *, file_hashes=None):
    base = Path(base).resolve()
    paths = _paths(manifest, base, jobs, parameters)
    files = {str(path): file_hashes.get(str(path), "MISSING") if file_hashes is not None else _sha(path)
             for path in sorted(paths)}
    # A legitimate code fix also unlocks diagnosis. Diagnostic bookkeeping and
    # tool output formatting are deliberately not business implementation here.
    script_dir = Path(__file__).parent
    rules = {name: _sha(script_dir / name) for name in
             ("lc_image_pipeline.py", "lc_workflow.py", "lc_layout.py", "lc_quality.py", "lc_delivery.py")}
    return diagnostic_input_fingerprint(manifest, command, jobs,
        {"arguments": parameters, "actual_files": files, "implementation": rules,
         "runtime": runtime_identity()})


def diagnostic_is_current(manifest, base, record):
    spec = record.get("input_spec")
    if not isinstance(spec, dict):
        return True  # Older explicit records have no reconstructable file view.
    try:
        return record.get("input_fingerprint") == input_fingerprint(manifest, base,
            record["command"], spec.get("jobs", []), spec.get("parameters", {}))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _normalized_error(error, base):
    pattern = r"(?P<base>(?:[\\/]|[A-Za-z]:[\\/])[^\n\"']*?)[\\/]\.lc-transactions[\\/][^\\/\s]+[\\/]workspace(?=$|[\\/\s\"':,])"
    def canonical(match):
        # macOS /var versus /private/var aliases must not split one failure
        # streak; do not normalize an unrelated project's path.
        return str(base) if Path(match["base"]).resolve() == base else match[0]
    return re.sub(pattern, canonical, str(error))


def capture_context(args):
    import lc_image_pipeline as p
    path = Path(args.manifest).expanduser().resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    parameters = {key: _jsonable(getattr(args, key)) for key in _PARAMETERS
                  if hasattr(args, key) and getattr(args, key) is not None}
    jobs = _selected(manifest, parameters)
    # Preserve the existing atomic rejection contract for malformed/retired
    # manifests and unknown scopes. Let the original command report its own
    # error; diagnostics cannot turn invalid input into a newly written project.
    try:
        available = {job["id"] for job in manifest.get("jobs", [])}
        if set(jobs) - available or p.validate_manifest(manifest, path.parent, check_files=False):
            return None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    paths = _paths(manifest, path.parent, jobs, parameters)
    return {"path": path, "manifest": manifest, "parameters": parameters, "jobs": jobs,
            "file_hashes": {str(file): _sha(file) for file in paths}}


def _failure_scope(context, error):
    candidates = context["jobs"] or [job["id"] for job in context["manifest"].get("jobs", [])]
    mentioned = [job for job in candidates if re.search(r"(?<![\w-])" + re.escape(job) + r"(?![\w-])", error)]
    return mentioned or context["jobs"]


def persist_observation(args, context, code, started_at, finished_at, *, error=None, result=None):
    import lc_image_pipeline as p
    from lc_workflow import manifest_lock
    base = context["path"].parent
    errors = result.get("errors", []) if isinstance(result, dict) else []
    failures = []
    for item in errors:
        if not isinstance(item, dict) or not item.get("error"):
            continue
        identifier = item.get("job", item.get("id"))
        scopes = [identifier] if isinstance(identifier, str) else context["jobs"]
        failures.append((scopes, _normalized_error(item["error"], base)))
    if error:
        normalized = _normalized_error(error, base)
        if not failures:
            failures.append((_failure_scope(context, normalized), normalized))
    elif code and not failures:
        failures.append((context["jobs"], f"Command returned exit code {code} without a structured error"))
    # Compute against the pre-command view and actual pre-command bytes. A
    # failed transaction's temporary work never becomes the diagnostic input.
    prepared = []
    for jobs, message in failures:
        fingerprint = input_fingerprint(context["manifest"], base, args.command, jobs,
            context["parameters"], file_hashes=context["file_hashes"])
        prepared.append((jobs, message, fingerprint))
    with manifest_lock(context["path"]):
        current = p.read_json(context["path"])
        for jobs, message, fingerprint in prepared:
            record_command_failure(current, args.command, fingerprint, message,
                                   job_ids=jobs, now=finished_at)
            current["runtime_diagnostics"]["command_failures"][-1]["input_spec"] = {
                "jobs": jobs, "parameters": copy.deepcopy(context["parameters"])}
        if not failures and code == 0:
            record_command_success(current, args.command, job_ids=context["jobs"])
        if isinstance(result, dict):
            succeeded = result.get("results", result.get("packets", []))
            for item in succeeded if isinstance(succeeded, list) else []:
                identifier = item.get("job", item.get("id")) if isinstance(item, dict) else None
                if isinstance(identifier, str) and not item.get("error"):
                    record_command_success(current, args.command, job_ids=[identifier])
        record_interval(current, "local", started_at, finished_at, event_id=uuid.uuid4().hex)
        p.write_json(context["path"], current)


def run_observed_command(args, operation):
    """One outer main hook; errors in diagnostics cannot overwrite command results.

    Do not call inside a held manifest lock. ``status`` is deliberately excluded
    and remains completely read-only. No authentication handling occurs here.
    """
    if args.command not in OBSERVED_COMMANDS or not getattr(args, "manifest", None):
        return operation()
    try:
        context = capture_context(args)
    except (OSError, ValueError, TypeError) as exc:
        print("Command diagnostics unavailable: " + _clean_error(exc), file=sys.stderr)
        return operation()
    if context is None:
        return operation()
    records = context["manifest"].get("runtime_diagnostics", {}).get("command_failures", [])
    latest = {}
    for record in records:
        latest[record.get("scope")] = record
    for record in latest.values():
        if (record.get("command") == args.command and record.get("diagnosis_required")
                and record.get("input_spec", {}).get("parameters") == context["parameters"]
                and diagnostic_is_current(context["manifest"], context["path"].parent, record)):
            message = ("REPEATED_COMMAND_DIAGNOSIS_REQUIRED: unchanged inputs produced the same failure twice; "
                       "diagnose the affected jobs before repeating this command")
            args._command_error = message
            print(message, file=sys.stderr)
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "command": args.command, "error": message,
                                  "diagnosis": {"jobs": record.get("jobs", []), "error": record.get("error")}},
                                 ensure_ascii=False))
            return 2
    started = time.time()
    code, raised = 2, None
    for field in ("_command_error", "_command_result"):
        if hasattr(args, field):
            delattr(args, field)
    try:
        code = operation()
        return code
    except BaseException as exc:
        raised = exc
        raise
    finally:
        finished = time.time()
        try:
            persist_observation(args, context, code, started, finished,
                error=str(raised) if raised else getattr(args, "_command_error", None),
                result=getattr(args, "_command_result", None))
        except (OSError, ValueError, TypeError, TimeoutError) as exc:
            print("Command diagnostics could not be persisted: " + _clean_error(exc), file=sys.stderr)
