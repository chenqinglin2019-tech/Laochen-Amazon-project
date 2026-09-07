"""Compact delivery and evidence-bound, reversible-cache cleanup.

This module never supplies review verdicts. Evidence is captured only after the
caller's real QA and delivery gates pass. A missing disposable artifact may use
its recorded hash; an existing file is always hashed, so replacement is detected.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from lc_assets import digest, file_hash, file_hash_context

COMPACT_DEFAULTS = {"name": "compact_jpg", "jpeg_quality": 92}
EVIDENCE_VERSION = 1
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


def resolve_delivery_profile(manifest: dict) -> dict:
    value = manifest.get("delivery_profile")
    if value is None or value == "legacy":
        return {"name": "legacy"}
    if isinstance(value, str):
        value = {"name": value}
    if not isinstance(value, dict) or value.get("name") not in {"legacy", "compact_jpg"}:
        raise ValueError("delivery_profile.name must be legacy or compact_jpg")
    if value["name"] == "legacy":
        return {"name": "legacy"}
    # Older projects may explicitly retain the former default. It is ignored
    # when false, while true is rejected so this pipeline cannot create HTML.
    if value.get("standalone_html") is True:
        raise ValueError("Standalone HTML delivery is no longer supported")
    value = {key: item for key, item in value.items()
             if key not in {"standalone_html", "preview_long_edge", "preview_quality"}}
    profile = {**COMPACT_DEFAULTS, **value}
    if type(profile["jpeg_quality"]) is not int or profile["jpeg_quality"] not in {92, 95}:
        raise ValueError("Compact JPEG quality must be 92 or 95")
    return profile


def apply_delivery_profile(manifest: dict, job: dict) -> None:
    """Apply before computing export fingerprints; never rebind an old approval."""
    profile = resolve_delivery_profile(manifest)
    if profile["name"] == "legacy":
        return
    output = job.get("final_output")
    if not isinstance(output, str) or not output:
        raise ValueError("A final_output path is required before applying delivery_profile")
    job["final_output"] = str(Path(output).with_suffix(".jpg"))
    settings = job.setdefault("export", {})
    settings.setdefault("quality", profile["jpeg_quality"])
    if type(settings["quality"]) is not int or settings["quality"] not in {92, 95}:
        raise ValueError("Compact per-image export.quality must be 92 or 95")


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _inside(base: Path, value: str | Path) -> Path:
    """Reject traversal and symlinks, including symlinked parent directories."""
    base = base.resolve()
    path = Path(value).expanduser()
    path = path if path.is_absolute() else base / path
    if not path.resolve().is_relative_to(base):
        raise ValueError(f"Path escapes project: {value}")
    current = path
    while True:
        if current.is_symlink():
            raise ValueError(f"Symlink is not a managed artifact: {value}")
        if current.resolve() == base:
            break
        if current == current.parent:
            raise ValueError(f"Path escapes project: {value}")
        current = current.parent
    return path.resolve()


def _cache_path(base: Path, value: str | Path) -> Path:
    path = _inside(base, value)
    relative = path.relative_to(base.resolve()).as_posix()
    directories = ("review/layouts/", "review/image_layers/", "review/details/", "review/source_quality/")
    exact = {"final/contact_sheet.png", "review/micro_detail_contact_sheet.png"}
    if path.suffix.lower() not in _IMAGE_SUFFIXES or not (relative.startswith(directories) or relative in exact):
        raise ValueError(f"Not an owned rebuildable image cache: {relative}")
    return path


def _read_evidence(manifest: dict, job: dict | None, base: Path, *, input_key: str = "input_files") -> dict | None:
    if resolve_delivery_profile(manifest)["name"] != "compact_jpg":
        return None
    key = job["id"] if job else "_project"
    binding = manifest.get("review_evidence", {}).get(key)
    if not isinstance(binding, dict):
        return None
    try:
        path = _inside(base, binding["path"])
        if file_hash(path) != binding.get("sha256"):
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != EVIDENCE_VERSION or data.get("project_id") != manifest.get("project_id"):
            return None
        if data.get("job_id") != key:
            return None
        if job and (job.get("status") != "qa_passed" or data.get("qa_fingerprint") != job.get("qa_fingerprint")
                    or data.get("qa_report_fingerprint") != job.get("qa_report_fingerprint")):
            return None
        if input_key not in data:
            return None
        for value, expected in data[input_key].items():
            source = Path(value) if Path(value).is_absolute() else base / value
            if not source.is_file() or file_hash(source) != expected:
                return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def artifact_sha256(manifest: dict, job: dict | None, base: Path, path: Path) -> str | None:
    """Use with current QA fingerprints, never as a substitute for the QA gate."""
    base = base.resolve()
    try:
        path = _cache_path(base, path)
    except ValueError:
        return None
    if path.is_file():
        return file_hash(path)
    evidence = _read_evidence(manifest, job, base)
    return (evidence or {}).get("cache_artifacts", {}).get(path.relative_to(base).as_posix())


def source_cache_metadata_is_current(manifest: dict, base: Path) -> bool:
    """Only the exact index captured at real QA may stand in for missing rasters."""
    record = _read_evidence(manifest, None, base, input_key="source_input_files")
    index = base / "review" / "source_quality" / "index.json"
    return bool(record and index.is_file() and record.get("source_index_sha256") == file_hash(index))


def retained_input_paths(manifest: dict, base: Path) -> set[Path]:
    """All retained image inputs, including reused assets in nominal cache dirs."""
    result: set[Path] = set()
    values = [ref.get("path") for ref in manifest.get("references", [])]
    values += [job.get(key) for job in manifest.get("jobs", [])
               for key in ("raw_output", "final_output", "background_asset")]
    # Layers and panels can point at adopted assets outside source/ and raw/.
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str) and (key.endswith("_path") or key.endswith("_asset") or key in {"path", "image"}):
                    if Path(item).suffix.lower() in _IMAGE_SUFFIXES:
                        values.append(item)
                elif isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    for job in manifest.get("jobs", []):
        for key in ("product_layers", "layout", "panel_sources"):
            visit(job.get(key))
        effect = job.get("title_effect_state", {})
        for key in ("guide", "candidate"):
            visit(effect.get(key))
        visit(effect.get("descriptor", {}).get("sources"))
    for value in values:
        if value:
            path = Path(value).expanduser()
            result.add((path if path.is_absolute() else base / path).resolve())
    return result


def _job_input_paths(manifest: dict, job: dict, base: Path) -> set[Path]:
    from lc_quality import _reference_ids
    selected = set(_reference_ids(manifest, job))
    def references(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "reference_id" and isinstance(item, str):
                    selected.add(item)
                elif isinstance(item, (dict, list)):
                    references(item)
        elif isinstance(value, list):
            for item in value:
                references(item)
    references(job.get("layout", {}))
    refs = {ref["id"]: ref for ref in manifest.get("references", [])}
    pending = list(selected)
    while pending:
        ref = refs.get(pending.pop(), {})
        for rid in ref.get("provenance", {}).get("source_reference_ids", []):
            if rid not in selected:
                selected.add(rid)
                pending.append(rid)
    scoped = {**manifest, "jobs": [job], "references": [ref for rid, ref in refs.items() if rid in selected]}
    return retained_input_paths(scoped, base)


def _retired_path(base: Path, value: str | Path) -> Path:
    path = _inside(base, value)
    if path.relative_to(base).parts[0] != "raw" or path.suffix.lower() not in _IMAGE_SUFFIXES:
        raise ValueError("Retired attempt must be a registered image below raw/")
    return path


def _snapshot_files(paths: set[Path], base: Path) -> dict:
    result = {}
    for path in sorted(paths):
        if not path.is_file():
            raise ValueError(f"Retained input is missing: {path}")
        label = str(path.relative_to(base)) if path.is_relative_to(base) else str(path)
        result[label] = file_hash(path)
    return result


def persist_review_evidence(manifest: dict, base: Path, qa_report: dict,
                            qa_fingerprint_fn: Callable[[dict, dict, Path], str],
                            *, stage_fingerprints_fn: Callable | None = None) -> dict:
    """Persist real approved evidence before cleanup; caller must save manifest.

    Each original report remains available in the evidence file. No new pass or
    observation is created here. The digest comparison is required even when all
    job statuses already say qa_passed.
    """
    base = base.resolve()
    if resolve_delivery_profile(manifest)["name"] != "compact_jpg":
        raise ValueError("Evidence compaction requires explicit compact_jpg profile")
    jobs = manifest.get("jobs", [])
    if not jobs or any(job.get("status") != "qa_passed" for job in jobs):
        raise ValueError("All jobs must complete actual QA before project compaction")
    reports = {item.get("id"): item for item in qa_report.get("jobs", [])}
    inputs = _snapshot_files(retained_input_paths(manifest, base), base)
    records = {}
    for job in jobs:
        report = reports.get(job["id"], {})
        if (report.get("status") != "qa_passed" or digest(report) != job.get("qa_report_fingerprint")
                or qa_fingerprint_fn(manifest, job, base) != job.get("qa_fingerprint")):
            raise ValueError(f"{job['id']}: current actual QA binding is required")
        final = _inside(base, job["final_output"])
        if file_hash(final) != job.get("qa_final_sha256"):
            raise ValueError(f"{job['id']}: final changed after review")
        candidates = [base / "review" / directory / f"{job['id']}{suffix}.png"
                      for directory, suffix in (("layouts", ""), ("layouts", "-360"), ("layouts", "-background"), ("layouts", "-glyphs"), ("image_layers", ""))]
        candidates += [base / detail["comparison_path"] for detail in report.get("details", []) if detail.get("comparison_path")]
        artifacts = {}
        for candidate in candidates:
            path = _cache_path(base, candidate)
            actual = artifact_sha256(manifest, job, base, path)
            if actual:
                artifacts[path.relative_to(base).as_posix()] = actual
        records[job["id"]] = {"version": EVIDENCE_VERSION, "project_id": manifest.get("project_id"),
                              "job_id": job["id"], "qa_fingerprint": job["qa_fingerprint"],
                              "qa_report_fingerprint": job["qa_report_fingerprint"],
                              "review_report": copy.deepcopy(report), "input_files": _snapshot_files(_job_input_paths(manifest, job, base), base),
                              "stage_fingerprints": stage_fingerprints_fn(manifest, job, base) if stage_fingerprints_fn else {},
                              "cache_artifacts": artifacts}
    project_artifacts = {}
    for relative in ("final/contact_sheet.png", "review/micro_detail_contact_sheet.png"):
        actual = artifact_sha256(manifest, None, base, base / relative)
        if actual:
            project_artifacts[relative] = actual
    # Only files named by the pipeline-owned index are cache candidates, never
    # arbitrary user files found by recursively scanning a review directory.
    index = base / "review" / "source_quality" / "index.json"
    if index.is_file():
        for entry in json.loads(index.read_text(encoding="utf-8")).get("entries", {}).values():
            for filename, expected in entry.get("artifacts", {}).items():
                path = _cache_path(base, index.parent / filename)
                if path.is_file() and file_hash(path) == expected:
                    project_artifacts[path.relative_to(base).as_posix()] = expected
    retired = {}
    protected = retained_input_paths(manifest, base)
    for job in jobs:
        for attempt in job.get("generation_attempts", []):
            value = attempt.get("retained_artifact_path")
            if not value or attempt.get("status") != "ingested":
                continue
            path = _retired_path(base, value)
            if path not in protected and path.is_file() and file_hash(path) == attempt.get("artifact_sha256"):
                retired[path.relative_to(base).as_posix()] = attempt["artifact_sha256"]
    records["_project"] = {"version": EVIDENCE_VERSION, "project_id": manifest.get("project_id"),
                           "job_id": "_project", "input_files": inputs, "cache_artifacts": project_artifacts,
                           "source_index_sha256": file_hash(index) if index.is_file() else None,
                           "retired_artifacts": retired,
                           "qa_report_sha256": digest(qa_report)}
    source_view = {**manifest, "jobs": [{"product_layers": job.get("product_layers", [])} for job in jobs]}
    records["_project"]["source_input_files"] = _snapshot_files(retained_input_paths(source_view, base), base)
    # Content-addressing preserves prior evidence and makes retries idempotent.
    bindings = {}
    for key, record in records.items():
        path = base / "review" / "evidence" / f"{digest(record)}.json"
        if not path.exists():
            _write_json(path, record)
        elif json.loads(path.read_text(encoding="utf-8")) != record:
            raise ValueError("Existing review evidence was modified")
        bindings[key] = {"path": path.relative_to(base).as_posix(), "sha256": file_hash(path)}
    manifest["review_evidence"] = bindings
    return bindings


def compact_project(manifest: dict, base: Path, *, manifest_path: Path,
                    delivery_check_fn: Callable[[dict, Path], dict],
                    qa_fingerprint_fn: Callable[[dict, dict, Path], str],
                    stage_fingerprints_fn: Callable | None = None) -> dict:
    """Caller holds its manifest lock. Preserve inputs; delete only bound caches."""
    base = base.resolve()
    manifest_path = _inside(base, manifest_path)
    if resolve_delivery_profile(manifest)["name"] != "compact_jpg":
        raise ValueError("Old projects must explicitly adopt compact_jpg before cleanup")
    before = delivery_check_fn(manifest, base)
    if not before.get("ready"):
        raise ValueError("Delivery gate must pass before cleanup")
    qa_report = json.loads((base / "qa_report.json").read_text(encoding="utf-8"))
    persist_review_evidence(manifest, base, qa_report, qa_fingerprint_fn,
                            stage_fingerprints_fn=stage_fingerprints_fn)
    protected = retained_input_paths(manifest, base)
    candidates = {}
    for job in [*manifest.get("jobs", []), None]:
        record = _read_evidence(manifest, job, base)
        if record is None:
            raise ValueError("Review evidence binding failed before cleanup")
        for relative, expected in {**record["cache_artifacts"], **record.get("retired_artifacts", {})}.items():
            path = _retired_path(base, relative) if relative in record.get("retired_artifacts", {}) else _cache_path(base, relative)
            if path.resolve() in protected or not path.exists():
                continue
            if file_hash(path) != expected:
                raise ValueError(f"Cache changed after actual review: {relative}")
            candidates[path] = expected
    # This durable manifest write must precede deletion: an interrupted cleanup
    # remains resumable and all surviving/missing caches still have real evidence.
    _write_json(manifest_path, manifest)
    removed, reclaimed = [], 0
    for path, expected in candidates.items():
        (_retired_path if path.relative_to(base).parts[0] == "raw" else _cache_path)(base, path)
        if file_hash(path) != expected:
            raise ValueError(f"Cache changed during cleanup: {path}")
        reclaimed += path.stat().st_size
        path.unlink()
        removed.append(path.relative_to(base).as_posix())
    after = delivery_check_fn(manifest, base)
    if not after.get("ready"):
        raise ValueError("Delivery gate failed after cleanup; retained inputs and evidence are intact")
    _write_json(manifest_path, manifest)
    return {"ready": True, "removed": removed, "reclaimed_bytes": reclaimed,
            "retained_input_files": len(protected), "model_calls": 0,
            "project_bytes": sum(path.stat().st_size for path in base.rglob("*") if path.is_file() and not path.is_symlink()),
            "delivery_result": after}


def _approved_delivery_images(manifest: dict, base: Path) -> list[dict]:
    """Validate current approved bytes, without repeating the full product gate."""
    images, paths = [], set()
    for job in manifest.get("jobs", []):
        identifier = job.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", identifier):
            raise ValueError("Delivery image requires a valid job ID")
        held = (job.get("hold") is True or job.get("publication_status") == "hold"
                or (not job.get("required", True) and "specs_hold" in identifier))
        if held or job.get("status") != "qa_passed":
            if job.get("required", True):
                raise ValueError(f"{job.get('id')}: required image is not approved for delivery")
            continue
        value = job.get("final_output")
        if not isinstance(value, str) or not value:
            raise ValueError(f"{identifier}: final_output is required")
        source = _inside(base, value)
        expected = job.get("qa_final_sha256")
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg"} or not source.is_file():
            raise ValueError(f"{identifier}: approved final image is missing or unsupported")
        if source in paths:
            raise ValueError("Delivery images may not share the same final output path")
        paths.add(source)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or file_hash(source) != expected:
            raise ValueError(f"{identifier}: final image changed after QA")
        images.append({"job_id": identifier, "filename": source.name, "source": source, "sha256": expected})
    if not images:
        raise ValueError("No current QA-approved images are available for delivery")
    # Flatten without losing original names unless two legacy subfolders clash.
    names = [image["filename"].casefold() for image in images]
    for image in images:
        if names.count(image["filename"].casefold()) > 1:
            image["filename"] = image["job_id"] + "--" + image["filename"]
    if len({image["filename"].casefold() for image in images}) != len(images):
        raise ValueError("Delivery filenames still collide after job-ID disambiguation")
    return images


def _directory_matches(base: Path, directory: Path, images: list[dict], *, hashes: bool) -> bool:
    try:
        directory = _inside(base, directory)
        if not directory.is_dir():
            return False
        entries = list(directory.iterdir())
        if {path.name for path in entries} != {image["filename"] for image in images}:
            return False
        if any(path.is_symlink() or not path.is_file() for path in entries):
            return False
        return not hashes or all(file_hash(_inside(base, directory / image["filename"])) == image["sha256"] for image in images)
    except (OSError, ValueError):
        return False


def _directory_result(directory: Path, images: list[dict], *, reused: bool, copied_files: int) -> dict:
    return {"output_dir": str(directory), "images": [
        {"job_id": image["job_id"], "filename": image["filename"], "path": str(directory / image["filename"]), "sha256": image["sha256"]}
        for image in images], "image_count": len(images), "reused": reused, "copied_files": copied_files}


def prepare_delivery_directory(manifest: dict, base: Path, *, delivery_result: dict) -> dict:
    """Expose only current approved images as a flat directory, never a ZIP.

    The caller holds its manifest lock and supplies the successful delivery gate
    for this same state (the post-cleanup result for compact projects). This
    helper checks current final bytes and directory contents, not the full QA
    graph again. Version-folder publication also has its own lock for callers
    that prepare the same already-approved manifest concurrently.
    """
    if not isinstance(delivery_result, dict) or delivery_result.get("ready") is not True:
        raise ValueError("A successful current delivery gate is required")
    if delivery_result.get("project_id", manifest.get("project_id")) != manifest.get("project_id"):
        raise ValueError("Delivery gate belongs to a different project")
    base = Path(base).resolve()
    with file_hash_context(fresh=True):
        images = _approved_delivery_images(manifest, base)
        final = _inside(base, "final")
        if all(image["source"].parent == final for image in images) and _directory_matches(base, final, images, hashes=False):
            return _directory_result(final, images, reused=True, copied_files=0)
        root = _inside(base, "delivery")
        if root.exists() and not root.is_dir():
            raise ValueError("The delivery output root is occupied by a user file")
        root.mkdir(parents=True, exist_ok=True)
        from lc_style_reference import _selection_lock
        lock_target = root / "directory-delivery"
        _inside(base, root / ".directory-delivery.lock")
        with _selection_lock(lock_target):
            _inside(base, root)
            # Re-read approval bytes after lock acquisition; no inherited digest
            # is valid across another writer's directory publication interval.
            with file_hash_context(fresh=True):
                images = _approved_delivery_images(manifest, base)
                inventory = [{key: image[key] for key in ("job_id", "filename", "sha256")} for image in images]
                binding = {"version": 1, "project_id": manifest.get("project_id"), "images": inventory}
                for marker in sorted(root.glob(".images-v*.json")):
                    if marker.is_symlink() or not marker.is_file():
                        continue
                    try:
                        record = json.loads(marker.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    if record != binding:
                        continue
                    directory = root / marker.name[1:-5]
                    if _directory_matches(base, directory, images, hashes=True):
                        return _directory_result(directory, images, reused=True, copied_files=0)
                version = 1
                while True:
                    name = f"images-v{version:03d}"
                    directory, marker = root / name, root / f".{name}.json"
                    if not directory.exists() and not directory.is_symlink() and not marker.exists() and not marker.is_symlink():
                        break
                    version += 1
                temporary = Path(tempfile.mkdtemp(prefix=".images-stage-", dir=root))
                try:
                    for image in images:
                        source = _inside(base, image["source"])
                        target = temporary / image["filename"]
                        shutil.copy2(source, target)
                        if file_hash(target) != image["sha256"]:
                            raise ValueError(f"{image['job_id']}: copied final image failed hash verification")
                    # Detect source replacement (including symlinks) before the
                    # directory is published and preserve every original path.
                    for image in images:
                        if file_hash(_inside(base, image["source"])) != image["sha256"]:
                            raise ValueError(f"{image['job_id']}: final changed while preparing delivery")
                    if directory.exists() or directory.is_symlink() or marker.exists() or marker.is_symlink():
                        raise ValueError("Delivery destination became occupied; no user files were overwritten")
                    directory.mkdir()  # Exclusive allocation; never replace an existing user directory.
                    for image in images:
                        # Exclusive publication of already-copied private inodes.
                        # These are not links to the original QA output files.
                        source, target = temporary / image["filename"], directory / image["filename"]
                        try:
                            os.link(source, target)
                        except OSError:
                            # FAT/network filesystems may not support hard links;
                            # exclusive creation retains the no-overwrite contract.
                            with source.open("rb") as input_stream, target.open("xb") as output_stream:
                                shutil.copyfileobj(input_stream, output_stream)
                            shutil.copystat(source, target)
                        if file_hash(target) != image["sha256"]:
                            raise ValueError(f"{image['job_id']}: published image failed hash verification")
                    with marker.open("x", encoding="utf-8") as stream:
                        json.dump(binding, stream, ensure_ascii=False, indent=2, allow_nan=False)
                        stream.write("\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
                return _directory_result(directory, images, reused=False, copied_files=len(images))
