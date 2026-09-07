"""Optimistic file transactions for expensive local image commands.

The authoritative Manifest lock is held only for snapshot/commit. A private
copy-on-write workspace prevents Pillow/browser writes from touching live files.
Commit is a journaled, recoverable multi-file operation, not a filesystem-wide
atomic rename. Every writer must call ``recover_pending`` after taking the lock.
"""
from __future__ import annotations

import contextlib
import copy
import ctypes
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


class TransactionConflict(ValueError):
    """A stale worker is never allowed to overwrite a newer result."""


_AREA = ".lc-transactions"
_MISSING = object()
_VOLATILE = {"jobs", "network_health", "concurrency", "anchor_job_id", "generation_gate",
             "delivery_artifacts", "timings", "metrics", "transaction_timings"}
_DERIVED = {"quality_metrics", "image_size", "product_pixel_size", "edge_signal",
            "reference_crops", "sha256"}
_GLOBAL_FILES = {"execution_plan.json", "qa_report.json", "delivery_report.json",
                 "final/contact_sheet.png", "review/micro_detail_contact_sheet.png",
                 "review/micro_detail_contact_sheet.cache.json"}
_SKIP_DIRS = {_AREA, ".git", "revision", "__pycache__", "node_modules"}
_SKIP_SUFFIXES = {".zip", ".html", ".lock", ".tmp"}


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == payload:
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _sha(path):
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _token(path):
    try:
        stat = Path(path).stat()
        return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    except FileNotFoundError:
        return None


def _clone(source, destination, metrics):
    """Clone a private inode. Never hard-link writable image artifacts."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    cloned = False
    if sys.platform == "darwin":
        library = ctypes.CDLL(None, use_errno=True)
        clonefile = getattr(library, "clonefile", None)
        if clonefile:
            clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
            clonefile.restype = ctypes.c_int
            cloned = clonefile(os.fsencode(source), os.fsencode(destination), 0) == 0
    elif sys.platform.startswith("linux"):
        try:
            import fcntl
            with source.open("rb") as src, destination.open("xb") as dst:
                fcntl.ioctl(dst.fileno(), 0x40049409, src.fileno())  # FICLONE
            cloned = True
        except OSError:
            if destination.exists():
                destination.unlink()
    if cloned:
        metrics["cloned_files"] += 1
    else:
        shutil.copy2(source, destination)
        metrics["copied_bytes"] += source.stat().st_size
    # Preserve nanosecond mtime so unchanged clones need no image re-hash.
    shutil.copystat(source, destination)


def _files(root, declared=()):
    seen = set()
    for directory, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in _SKIP_DIRS and not name.startswith(".")]
        for name in names:
            path = Path(directory) / name
            if name.startswith(".") or path.suffix.lower() in _SKIP_SUFFIXES or path.is_symlink():
                continue
            seen.add(str(path.relative_to(root)))
            yield path
    # A directory name is not an artifact type: revision may hold a live image
    # dependency as well as old HTML/ZIP reports. Include only declared files,
    # never traverse an otherwise excluded history directory wholesale.
    for relative in sorted(declared):
        path = root / relative
        if relative not in seen and path.is_file() and not path.is_symlink():
            yield path


def _strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, str):
        yield value


def _declared_project_files(manifest, base):
    declared = set()
    # Validation checks assets for ALL jobs, including jobs not selected to run.
    for value in _strings(manifest):
        if not value or len(value) > 4096 or "\n" in value or "://" in value:
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base / path
        try:
            relative = path.relative_to(base)
            if (".." not in relative.parts and relative.parts and relative.parts[0] != _AREA
                    and path.is_file() and not path.is_symlink()
                    and path.resolve().is_relative_to(base)):
                declared.add(str(relative))
        except (OSError, ValueError):
            continue
    return declared


def _input_projection(manifest):
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(child) for key, child in value.items() if key not in _DERIVED}
        if isinstance(value, list):
            return [clean(child) for child in value]
        return value
    result = clean({key: value for key, value in manifest.items() if key not in _VOLATILE})
    for detail in result.get("critical_details", []):
        # Confirmation/location are evidence; this status is computed by prepare.
        detail.pop("status", None)
    return result


def _dependencies(manifest, selected, base):
    values = [_input_projection(manifest)]
    values.extend(job for job in manifest["jobs"] if job["id"] in selected)
    result = set()
    for value in _strings(values):
        if not value or len(value) > 4096 or "\n" in value or "://" in value:
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        try:
            if candidate.is_file():
                result.add(candidate.resolve())
        except (OSError, ValueError):
            continue
    for job_id in selected:
        job = next(job for job in manifest["jobs"] if job["id"] == job_id)
        for field in ("raw_output", "final_output"):
            if job.get(field):
                result.add((base / job[field]).resolve())
        for directory in ("review/layouts", "review/image_layers", "review/packets", "prompts", "repairs"):
            folder = base / directory
            if folder.is_dir():
                result.update(path.resolve() for path in folder.glob(f"{job_id}*") if path.is_file()
                              and _artifact_owner(str(path.relative_to(base)), manifest) == job_id)
        folder = base / "review/details" / job_id
        if folder.is_dir():
            result.update(path.resolve() for path in folder.rglob("*") if path.is_file())
        folder = base / "title_effects" / job_id
        if folder.is_dir():
            result.update(path.resolve() for path in folder.rglob("*") if path.is_file())
    return result


def _artifact_owner(relative, manifest):
    for job in sorted(manifest["jobs"], key=lambda item: len(item["id"]), reverse=True):
        if relative in {job.get("raw_output"), job.get("final_output"), job.get("prompt_file")}:
            return job["id"]
        parent, name = str(Path(relative).parent), Path(relative).name
        if parent == "review/details/" + job["id"]:
            return job["id"]
        if relative.startswith("title_effects/" + job["id"] + "/"):
            return job["id"]
        if parent in {"review/layouts", "review/image_layers", "review/packets", "prompts", "repairs"}:
            if name.startswith(job["id"] + ".") or name.startswith(job["id"] + "-") or name.startswith(job["id"] + "__"):
                return job["id"]
    return None


def _map_outputs(value, source, target, *, all_strings=False):
    """Inputs keep their exact reference spelling; only output fields relocate."""
    if isinstance(value, dict):
        return {key: _map_outputs(child, source, target,
                                 all_strings=all_strings or key in {"output_path", "preview_path", "packet"})
                for key, child in value.items()}
    if isinstance(value, list):
        return [_map_outputs(child, source, target, all_strings=all_strings) for child in value]
    if all_strings and isinstance(value, str):
        return value.replace(str(source) + os.sep, str(target) + os.sep)
    return value


def _merge(before, current, proposed, location="manifest"):
    if proposed == before:
        return _MISSING if current is _MISSING else copy.deepcopy(current)
    if current == before or proposed == current:
        return _MISSING if proposed is _MISSING else copy.deepcopy(proposed)
    if all(isinstance(value, dict) for value in (before, current, proposed)):
        merged = {}
        for key in set(before) | set(current) | set(proposed):
            value = _merge(before.get(key, _MISSING), current.get(key, _MISSING),
                           proposed.get(key, _MISSING), location + "." + key)
            if value is not _MISSING:
                merged[key] = value
        return merged
    if all(isinstance(value, list) for value in (before, current, proposed)) and all(
            isinstance(item, dict) and isinstance(item.get("id"), str)
            for value in (before, current, proposed) for item in value):
        maps = [{item["id"]: item for item in value} for value in (before, current, proposed)]
        merged = _merge(*maps, location=location)
        order = list(dict.fromkeys(item["id"] for value in (current, proposed) for item in value))
        return [merged[key] for key in order if key in merged]
    raise TransactionConflict(f"STALE_TRANSACTION: shared field changed: {location}")


def _merge_qa(current, proposed, selected):
    merged = copy.deepcopy(current or proposed)
    # Project forks may start with an older project's report. The staged
    # operation owns report metadata; only unselected job results are retained.
    # Keeping old metadata also breaks the overview's digest(report) binding.
    for key, value in proposed.items():
        if key not in {"jobs", "summary"}:
            merged[key] = copy.deepcopy(value)
    old = {job["id"]: job for job in merged.get("jobs", [])}
    for job in proposed.get("jobs", []):
        if job["id"] in selected:
            old[job["id"]] = copy.deepcopy(job)
    order = list(dict.fromkeys(job["id"] for value in (merged, proposed) for job in value.get("jobs", [])))
    merged["jobs"] = [old[key] for key in order]
    counts = dict.fromkeys(("passed", "repair_needed", "blocked", "failed", "review_pending"), 0)
    for job in merged["jobs"]:
        state = job.get("status")
        key = "passed" if state == "qa_passed" else state if state in counts else "repair_needed"
        counts[key] += 1
    merged["summary"] = counts
    return merged


def _target(base, relative):
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts or not value.parts:
        raise TransactionConflict(f"UNSAFE_TRANSACTION_PATH: {relative}")
    path = base / value
    if not path.resolve().is_relative_to(base.resolve()):
        raise TransactionConflict(f"UNSAFE_TRANSACTION_PATH: {relative}")
    return path


def _refresh_dispatch_output(stream, command_name, plan):
    """Never hand the caller a dispatch list computed before concurrent ingest."""
    payload = stream.getvalue()
    try:
        value, offset = json.JSONDecoder().raw_decode(payload)
    except (ValueError, TypeError):
        return
    if not isinstance(value, dict):
        return
    if command_name == "plan":
        value = {**value, **plan}
    elif "dispatch" in value:
        value["dispatch"] = plan["dispatch"]
    else:
        return
    stream.seek(0)
    stream.truncate()
    stream.write(json.dumps(value, ensure_ascii=False, indent=2) + payload[offset:])


def recover_pending(manifest_path):
    """Recover interrupted promotions. Caller MUST already own manifest_lock."""
    manifest_path = Path(manifest_path).resolve()
    area = manifest_path.parent / _AREA
    if not area.is_dir():
        return
    for journal_path in sorted(area.glob("*/journal.json")):
        journal = _json(journal_path)
        if journal.get("state") != "committing":
            continue
        current_hash = _sha(manifest_path)
        if (current_hash == journal["after_manifest_sha256"] and
                (current_hash != journal["before_manifest_sha256"] or
                 all(_sha(_target(manifest_path.parent, item["relative"])) == item["new_sha256"]
                     for item in journal["files"]))):
            journal["state"] = "committed"
        elif current_hash == journal["before_manifest_sha256"]:
            for item in reversed(journal["files"]):
                target = _target(manifest_path.parent, item["relative"])
                if _sha(target) == item["new_sha256"]:
                    backup = journal_path.parent / "backup" / item["relative"]
                    if item["old_sha256"] is None:
                        target.unlink()
                    elif backup.is_file() and _sha(backup) == item["old_sha256"]:
                        os.replace(backup, target)
                    else:
                        raise TransactionConflict(f"TRANSACTION_RECOVERY_REQUIRED: missing backup: {target}")
                elif _sha(target) != item["old_sha256"]:
                    raise TransactionConflict(f"TRANSACTION_RECOVERY_REQUIRED: newer artifact: {target}")
            journal["state"] = "rolled_back"
        else:
            raise TransactionConflict("TRANSACTION_RECOVERY_REQUIRED: manifest changed before pending recovery")
        _atomic(journal_path, _bytes(journal))


def run_staged_command(manifest_path, job_ids, operation, *, command_name):
    """Run ``operation(private_manifest_path)`` and commit selected jobs only.

    The operation returns its exit code/result. A normal nonzero return can still
    commit its explicit failure status; an exception cannot publish partial work.
    A stale transaction raises TransactionConflict and retains isolated artifacts.
    """
    from lc_workflow import manifest_lock
    manifest_path = Path(manifest_path).expanduser().resolve()
    base = manifest_path.parent
    started = time.monotonic()
    wait_started = started
    with manifest_lock(manifest_path):
        snapshot_lock_wait = time.monotonic() - wait_started
        snapshot_lock_started = time.monotonic()
        snapshot = _json(manifest_path)
        available = {job["id"] for job in snapshot.get("jobs", [])}
        selected = available if job_ids is None else set(job_ids)
        if not selected or selected - available:
            raise ValueError(f"Unknown or empty transaction jobs: {sorted(selected - available)}")
        snapshot_tokens = {str(path): _token(path) for path in _dependencies(snapshot, selected, base)}
        snapshot_lock_hold = time.monotonic() - snapshot_lock_started
    metrics = {"command": command_name, "jobs": sorted(selected), "cloned_files": 0,
               "copied_bytes": 0, "snapshot_lock_wait_seconds": round(snapshot_lock_wait, 6),
               "snapshot_lock_hold_seconds": round(snapshot_lock_hold, 6)}
    area = base / _AREA
    area.mkdir(exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix="tx-", dir=area))
    stage = transaction / "workspace"
    stage.mkdir()
    journal_path = transaction / "journal.json"
    journal = {"state": "running", "command": command_name, "jobs": sorted(selected), "metrics": metrics}
    _atomic(journal_path, _bytes(journal))
    initial = {}
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        clone_started = time.monotonic()
        declared = _declared_project_files(snapshot, base)
        for source in _files(base, declared):
            relative = str(source.relative_to(base))
            if source == manifest_path:
                continue
            destination = stage / relative
            _clone(source, destination, metrics)
            initial[relative] = {"stage_token": _token(destination), "source_token": _token(source)}
            if source.suffix == ".json":
                try:
                    initial[relative]["json"] = _json(destination)
                except (ValueError, OSError):
                    pass
        for path, token in snapshot_tokens.items():
            if _token(path) != token:
                raise TransactionConflict(f"STALE_TRANSACTION: input changed during snapshot: {path}")
        stage_manifest = stage / manifest_path.name
        _atomic(stage_manifest, _bytes(_map_outputs(snapshot, base, stage)))
        metrics["snapshot_seconds"] = round(time.monotonic() - clone_started, 6)
        work_started = time.monotonic()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = operation(stage_manifest)
        metrics["work_seconds"] = round(time.monotonic() - work_started, 6)
        proposed = _map_outputs(_json(stage_manifest), stage, base, all_strings=True)
        proposed_jobs = {job["id"]: job for job in proposed.get("jobs", [])}
        before_jobs = {job["id"]: job for job in snapshot["jobs"]}
        if set(proposed_jobs) != available:
            raise TransactionConflict("STAGED_JOB_SET_CHANGED: worker cannot add/remove jobs")
        if any(proposed_jobs[key] != before_jobs[key] for key in available - selected):
            raise TransactionConflict("UNSCOPED_JOB_WRITE: worker changed an unselected job")
        changed = {}
        for path in _files(stage, declared):
            relative = str(path.relative_to(stage))
            if path == stage_manifest or relative in _GLOBAL_FILES:
                continue
            prior = initial.get(relative)
            if prior and _token(path) == prior["stage_token"]:
                continue
            # Canonicalize textual outputs BEFORE hashing/promoting.
            if path.suffix in {".json", ".txt", ".md"}:
                payload = path.read_bytes().replace(os.fsencode(str(stage) + os.sep), os.fsencode(str(base) + os.sep))
                _atomic(path, payload)
            output_hash = _sha(path)
            if _sha(base / relative) != output_hash:
                owner = _artifact_owner(relative, snapshot)
                if owner is not None and owner not in selected:
                    raise TransactionConflict(f"UNSCOPED_ARTIFACT_WRITE: {relative}")
                derived = (relative.startswith(("detail_refs/", "review/source_quality/")) or
                           relative == snapshot.get("style_reference_selection_path", "style_reference_selection.json"))
                if owner is None and not derived and (relative in declared or str((base / relative).resolve()) in snapshot_tokens):
                    raise TransactionConflict(f"INPUT_ARTIFACT_WRITE: {relative}")
                changed[relative] = output_hash
        wait_started = time.monotonic()
        with manifest_lock(manifest_path):
            metrics["commit_lock_wait_seconds"] = round(time.monotonic() - wait_started, 6)
            commit_started = time.monotonic()
            latest = _json(manifest_path)
            latest_jobs = {job["id"]: job for job in latest.get("jobs", [])}
            if set(latest_jobs) != available:
                raise TransactionConflict("STALE_TRANSACTION: job inventory changed")
            if _input_projection(latest) != _input_projection(snapshot):
                raise TransactionConflict("STALE_TRANSACTION: shared design/evidence inputs changed")
            for key in selected:
                if latest_jobs[key] != before_jobs[key]:
                    raise TransactionConflict(f"STALE_TRANSACTION: job changed: {key}")
            for path, token in snapshot_tokens.items():
                if _token(path) != token:
                    raise TransactionConflict(f"STALE_TRANSACTION: input artifact changed: {path}")
            merged = _merge({k: v for k, v in snapshot.items() if k != "jobs"},
                            {k: v for k, v in latest.items() if k != "jobs"},
                            {k: v for k, v in proposed.items() if k != "jobs"})
            merged["jobs"] = [copy.deepcopy(proposed_jobs[job["id"]] if job["id"] in selected else job)
                              for job in latest["jobs"]]
            for relative in list(changed):
                expected = initial.get(relative, {}).get("source_token")
                target = _target(base, relative)
                if _token(target) != expected:
                    if _sha(target) == changed[relative]:
                        del changed[relative]
                    elif (relative.endswith(".json") and "json" in initial.get(relative, {}) and target.is_file()):
                        value = _merge(initial[relative]["json"], _json(target), _json(stage / relative), relative)
                        _atomic(stage / relative, _bytes(value))
                        changed[relative] = _sha(stage / relative)
                    else:
                        raise TransactionConflict(f"STALE_TRANSACTION: output path changed: {relative}")
            qa = stage / "qa_report.json"
            if qa.is_file():
                proposed_qa = _json(qa)
                old_qa = _json(base / "qa_report.json") if (base / "qa_report.json").is_file() else {}
                value = _merge_qa(old_qa, proposed_qa, selected)
                _atomic(qa, _bytes(value))
                if _sha(qa) != _sha(base / "qa_report.json"):
                    changed["qa_report.json"] = _sha(qa)
            # Only whole-project finalize may publish a snapshot-wide contact sheet.
            if command_name == "finalize" and selected == available:
                for relative in _GLOBAL_FILES - {"qa_report.json", "execution_plan.json", "delivery_report.json"}:
                    if (stage / relative).is_file() and _sha(stage / relative) != _sha(base / relative):
                        changed[relative] = _sha(stage / relative)
            else:
                if "delivery_artifacts" in latest:
                    merged["delivery_artifacts"] = copy.deepcopy(latest["delivery_artifacts"])
                else:
                    merged.pop("delivery_artifacts", None)
            # A tiny plan is rebuilt from merged state, never copied from a stale worker.
            plan = None
            try:
                from lc_image_pipeline import execution_plan
                plan = execution_plan(merged)
                _atomic(stage / "execution_plan.json", _bytes(plan))
                if _sha(stage / "execution_plan.json") != _sha(base / "execution_plan.json"):
                    changed["execution_plan.json"] = _sha(stage / "execution_plan.json")
            except KeyError:
                if not snapshot.get("test_fixture"):
                    raise
            manifest_payload = _bytes(merged)
            journal.update(state="committing", before_manifest_sha256=_sha(manifest_path),
                           after_manifest_sha256=hashlib.sha256(manifest_payload).hexdigest(), files=[])
            for relative, output_hash in sorted(changed.items()):
                target = _target(base, relative)
                old_hash = _sha(target)
                if target.exists():
                    _clone(target, transaction / "backup" / relative, metrics)
                journal["files"].append({"relative": relative, "old_sha256": old_hash, "new_sha256": output_hash})
            _atomic(journal_path, _bytes(journal))
            try:
                for item in journal["files"]:
                    target = _target(base, item["relative"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(stage / item["relative"], target)
                _atomic(manifest_path, manifest_payload)
                journal["state"] = "committed"
                metrics["commit_seconds"] = round(time.monotonic() - commit_started, 6)
                metrics["total_seconds"] = round(time.monotonic() - started, 6)
                _atomic(journal_path, _bytes(journal))
            except BaseException:
                recover_pending(manifest_path)
                raise
        # Keep only a tiny timing journal after success; failures retain artifacts.
        shutil.rmtree(stage)
        if (transaction / "backup").is_dir():
            shutil.rmtree(transaction / "backup")
        if plan is not None:
            _refresh_dispatch_output(stdout, command_name, plan)
            if isinstance(result, dict) and "dispatch" in result:
                result = {**result, "dispatch": plan["dispatch"]}
        return result
    except BaseException:
        # A staged success is provisional until CAS and file commit succeed.
        # The caller emits the single failure result; never flush a false pass.
        stdout.seek(0)
        stdout.truncate(0)
        if journal.get("state") == "running":
            journal["state"] = "rejected"
            _atomic(journal_path, _bytes(journal))
        raise
    finally:
        if stdout.getvalue():
            print(stdout.getvalue().replace(str(stage), str(base)), end="")
        if stderr.getvalue():
            print(stderr.getvalue().replace(str(stage), str(base)), end="", file=sys.stderr)
