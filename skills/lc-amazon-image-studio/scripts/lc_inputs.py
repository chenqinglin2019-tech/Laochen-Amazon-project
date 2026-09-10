"""Current image-input closure shared by retention and private transactions.

This inventory never changes prompt ordering or fingerprints. Historical
attempts are not inputs merely because they were recorded; an adopted repair
target or actual attachment remains an input regardless of its directory.
"""
from __future__ import annotations

from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


def _objects(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _image_values(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and (key.endswith(("_path", "_asset")) or key in {"path", "image"}):
                if Path(item).suffix.lower() in IMAGE_SUFFIXES:
                    yield item
            elif isinstance(item, (dict, list)):
                yield from _image_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _image_values(item)


def _reference_ids(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("reference_id") and isinstance(item, str):
                yield item
            elif key.endswith("reference_ids") or key == "evidence_refs":
                if isinstance(item, list):
                    yield from (entry for entry in item if isinstance(entry, str))
            elif key in {"source_reference_hashes", "reviewed_source_hashes"} and isinstance(item, dict):
                yield from item
            elif isinstance(item, (dict, list)):
                yield from _reference_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _reference_ids(item)


def image_input_paths(manifest: dict, base: Path, *, job_ids: set[str] | None = None) -> set[Path]:
    """Return declared current image dependencies, including missing paths.

    ``None`` retains every project reference; a selected job set retains its
    references recursively. Missing paths must remain visible to validation and
    CAS rather than disappearing from the dependency inventory.
    """
    base = Path(base).resolve()
    jobs = [job for job in _objects(manifest.get("jobs")) if job_ids is None or job.get("id") in job_ids]
    refs = {ref.get("id"): ref for ref in _objects(manifest.get("references")) if isinstance(ref.get("id"), str)}
    selected = set(refs) if job_ids is None else set()
    values = []
    for job in jobs:
        selected.update(_reference_ids({key: item for key, item in job.items()
                                        if key not in {"generation_attempts", "review_history", "metrics"}}))
        values.extend(job.get(key) for key in ("raw_output", "final_output", "background_asset"))
        attachments = job.get("generation_reference_paths")
        if isinstance(attachments, list):
            values.extend(path for path in attachments if isinstance(path, str))
        for key in ("prompt_edit", "product_layers", "layout", "panel_sources", "disclosure_extra_images", "background_normalization"):
            values.extend(_image_values(job.get(key)))
        effect = job.get("title_effect_state") or {}
        if isinstance(effect, dict):
            for key in ("guide", "candidate"):
                values.extend(_image_values(effect.get(key)))
            descriptor = effect.get("descriptor") or {}
            if isinstance(descriptor, dict):
                values.extend(_image_values(descriptor.get("sources")))
        for detail in _objects(manifest.get("critical_details")):
            if (detail.get("priority") in {"P0", "P1"}
                    and (detail.get("visibility") or {}).get(job.get("id")) == "required"):
                selected.update(_reference_ids(detail.get("locations")))
    # Actual attachments can name a reference without also naming its ID.
    by_path = {str((base / ref["path"]).resolve()): rid for rid, ref in refs.items() if isinstance(ref.get("path"), str)}
    for value in values:
        if isinstance(value, str) and value:
            selected.add(by_path.get(str((base / Path(value).expanduser()).resolve())))
    pending = list(selected)
    while pending:
        ref = refs.get(pending.pop(), {})
        values.append(ref.get("path"))
        for rid in _reference_ids(ref.get("provenance")):
            if rid not in selected:
                selected.add(rid)
                pending.append(rid)
    result = set()
    for value in values:
        if isinstance(value, str) and value and Path(value).suffix.lower() in IMAGE_SUFFIXES:
            result.add((base / Path(value).expanduser()).resolve())
    return result
