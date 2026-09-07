"""Versioned per-image dependencies and evidence-checked migration of bound pixels."""
from __future__ import annotations

import copy
import time


def critical_detail_dependencies(manifest, job, selected_ids=None):
    scoped = job.get("generation_dependency_version", 1) == 2
    result = []
    for detail in manifest.get("critical_details", []):
        if selected_ids is not None and detail["id"] not in selected_ids:
            continue
        value = {key: copy.deepcopy(item) for key, item in detail.items()
                 if key not in {"status", "reference_crops"}}
        if scoped:
            value["visibility"] = {job["id"]: detail.get("visibility", {}).get(job["id"], "optional")}
        result.append(value)
    return result


def attempt_generation_binding(job, attempt):
    """Keep original dispatch hashes immutable while resolving a proven migration."""
    original = attempt.get("prompt_hash")
    for record in reversed(job.get("dependency_migrations", [])):
        proof = record.get("proof", {})
        if (record.get("old_generation") == original and proof.get("kind") == "ingested_attempt"
                and proof.get("attempt_id") == attempt.get("id")
                and record.get("raw_sha256") == attempt.get("artifact_sha256")):
            return record["new_generation"]
    return original


def migrate_dependencies(manifest, base, source_view, job_ids, *, source_kind="historical_snapshot", allow_project_fork=False):
    """Rebind only when a real artifact proves the old hash and scoped inputs agree.

    Reconstructed views are permitted, but never represented as historical files:
    they must reproduce a previously ingested attempt's exact generation hash.
    No source pixels, prompts, attempt counts, or historical attempt hashes change.
    """
    import lc_image_pipeline as p
    if source_kind not in {"historical_snapshot", "reconstructed_verified_dependency_view"}:
        raise p.PipelineError("Unsupported dependency source kind")
    if source_view.get("project_id") != manifest.get("project_id") and not allow_project_fork:
        raise p.PipelineError("Dependency source view must describe the same project")
    selected = p.job_selection(manifest, job_ids)
    source_hash = p.digest(source_view)
    changes, results = [], []
    for job in manifest["jobs"]:
        if job["id"] not in selected:
            continue
        if job.get("generation_dependency_version", 1) == 2:
            results.append({"job": job["id"], "cached": True})
            continue
        old = p.find_by_id(source_view.get("jobs", []), job["id"])
        if old is None or old.get("generation_dependency_version", 1) != 1:
            raise p.PipelineError(f"{job['id']}: legacy source job is required")
        if job.get("status") == "generating":
            raise p.PipelineError(f"{job['id']}: wait for the active tool result and ingest before migration")
        old_generation = p.generation_fingerprint(source_view, old, base)
        raw = p.resolve_project_path(job.get("raw_output"), base, "raw_output")
        if raw is None or not raw.is_file():
            raise p.PipelineError(f"{job['id']}: bound raw artifact is required; new jobs can declare version 2 before prepare")
        raw_sha = p.sha256_file(raw)
        if job.get("bound_raw_sha256") != raw_sha:
            raise p.PipelineError(f"{job['id']}: current raw binding is missing or changed")
        attempts = job.get("generation_attempts", []) + old.get("generation_attempts", [])
        attempt = next((value for value in attempts if value.get("status") == "ingested"
                        and value.get("prompt_hash") == old_generation
                        and value.get("artifact_sha256") == raw_sha), None)
        if attempt:
            proof = {"kind": "ingested_attempt", "attempt_id": attempt["id"], "record_sha256": p.digest(attempt)}
        elif (source_kind == "historical_snapshot" and old.get("generated_prompt_hash") == old_generation
              and old.get("bound_raw_sha256") == raw_sha):
            proof = {"kind": "bound_raw_snapshot", "record_sha256": p.digest(old)}
        else:
            raise p.PipelineError(f"{job['id']}: source view does not reproduce an actual bound generation hash and artifact")
        old_scoped, new = copy.deepcopy(old), copy.deepcopy(job)
        old_scoped["generation_dependency_version"] = new["generation_dependency_version"] = 2
        expected = p.current_fingerprints(source_view, old_scoped, base)
        actual = p.current_fingerprints(manifest, new, base)
        if expected["generation"] != actual["generation"]:
            raise p.PipelineError(f"{job['id']}: this image's scoped generation inputs changed; migration cannot authorize reused pixels")
        old_prompt = p.compile_job_prompt(source_view, copy.deepcopy(old), base)[0]
        new_prompt = p.compile_job_prompt(manifest, copy.deepcopy(new), base)[0]
        if old_prompt != new_prompt:
            raise p.PipelineError(f"{job['id']}: prompt bytes changed")
        record = {"version": 1, "source_kind": source_kind, "source_view_sha256": source_hash,
                  "source_project_id": source_view.get("project_id"), "target_project_id": manifest.get("project_id"),
                  "project_fork": source_view.get("project_id") != manifest.get("project_id"),
                  "old_generation": old_generation, "new_generation": actual["generation"],
                  "raw_sha256": raw_sha, "prompt_sha256": p.digest(old_prompt), "proof": proof,
                  "verified_at": time.time()}
        new.setdefault("dependency_migrations", []).append(record)
        new.update(prompt_hash=actual["generation"], generated_prompt_hash=actual["generation"], fingerprints=actual)
        if attempt and new.get("active_attempt_id") == attempt["id"]:
            new["attempt_prompt_hash"] = attempt["prompt_hash"]
        # A generation-dependency migration is not a new visual approval. Preserve
        # evidence and pixels, but prepare fresh QA bindings under the current rules.
        for key in ("qa_fingerprint", "qa_final_sha256", "qa_report_fingerprint", "review_request"):
            new.pop(key, None)
        if new.get("status") not in {"blocked", "failed"}:
            new["status"] = "generated"
        new["qa_invalidated_reason"] = "DEPENDENCY_SCOPE_MIGRATED_REVIEW_REQUIRED"
        changes.append((job, new))
        results.append({"job": job["id"], "cached": False, **record})
    if changes:
        # Save the exact supplied dependency view, including the truthful source
        # kind in each job record. A reconstructed view is not a historical backup.
        audit = base / "review" / "dependency_migrations" / f"{source_hash}.json"
        if not audit.is_file():
            p.write_json(audit, source_view)
        elif p.digest(p.read_json(audit)) != source_hash:
            raise p.PipelineError("Dependency migration audit artifact was modified")
        for job, new in changes:
            job.clear()
            job.update(new)
    return {"jobs": results, "model_calls": 0, "raw_pixels_changed": False}


def scoped_review_dependencies(manifest, job):
    """Opt in explicitly; existing manifests retain their historical review scope."""
    return job.get("review_dependency_version", manifest.get("review_dependency_version", 1)) == 2


def title_effect_dependencies(job, base, *, phase="layout"):
    """A local title effect never belongs in the product generation dependency set."""
    from lc_title_effects import dependencies
    return dependencies(job, base, phase=phase)


def evidence_dependencies(manifest, job, base=None):
    """Return the transitive evidence actually consumed by one image.

    Claims, panels, layers and generated references can all introduce real-photo
    dependencies. Keep unresolved identifiers in the payload instead of silently
    dropping them. Actual file bytes bind evidence even before assess_sources has
    refreshed its recorded SHA. Shared identity/rules remain shared dependencies.
    """
    import lc_image_pipeline as p
    references = {item["id"]: item for item in manifest.get("references", [])}
    facts = {item["id"]: item for item in manifest.get("facts", [])}
    details = {item["id"]: item for item in manifest.get("critical_details", [])}
    catalog = {**details, **facts, **references}
    pending, seen = [], set()

    def add(value):
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            pending.append(value)

    def links(value, *, evidence=False):
        if isinstance(value, str):
            if evidence and value in catalog:
                add(value)
        elif isinstance(value, list):
            for child in value:
                links(child, evidence=evidence)
        elif isinstance(value, dict):
            for key, child in value.items():
                if key in {"reference_id", "pixel_source_reference_id", "fact_id", "detail_id"}:
                    add(child)
                elif key in {"source_reference_ids", "selected_reference_ids", "evidence_refs", "claim_ids", "fact_ids", "detail_ids"}:
                    if isinstance(child, list):
                        for identifier in child:
                            add(identifier)
                elif key == "source_reference_hashes" and isinstance(child, dict):
                    for identifier in child:
                        add(identifier)
                else:
                    links(child, evidence=key == "evidence")

    # Do not traverse historical QA, previous packets or timing records.
    links({key: job.get(key) for key in ("source_reference_ids", "pixel_source_reference_id", "claim_ids",
           "render_decision", "product_layers", "layout", "copy", "text_overlays")})
    for detail in details.values():
        if detail.get("visibility", {}).get(job["id"], "optional") in {"required", "hidden"}:
            add(detail["id"])
    # Diagnostics contain target_previews for every consuming image and cache
    # paths. Their cross-job lifecycle is not evidence. Source bytes, source
    # geometry, provenance and actual reviewer observations remain bound.
    derived_reference_fields = {"quality_metrics", "image_size", "product_pixel_size", "edge_signal"}
    for identifier in pending:
        if identifier in references:
            links({key: value for key, value in references[identifier].items() if key not in derived_reference_fields})
        elif identifier in catalog:
            links(catalog[identifier])
    selected_refs = [{key: copy.deepcopy(value) for key, value in ref.items()
                      if key not in derived_reference_fields} for rid, ref in references.items() if rid in seen]
    if base is not None:
        for ref in selected_refs:
            path = p.resolve_path(ref.get("path"), base)
            ref["actual_sha256"] = p.sha256_file(path) if path and path.is_file() else "MISSING"
    selected_details = critical_detail_dependencies(manifest, job, set(details) & seen)
    # The new review contract scopes visibility even for legacy generation data.
    for detail in selected_details:
        detail["visibility"] = {job["id"]: details[detail["id"]].get("visibility", {}).get(job["id"], "optional")}
    return {"version": 2, "references": selected_refs,
            "facts": [copy.deepcopy(fact) for fid, fact in facts.items() if fid in seen],
            "details": selected_details, "missing": sorted(seen - set(catalog)),
            "shared_rules": {key: copy.deepcopy(manifest.get(key)) for key in
                             ("product_truth", "marketplace", "language", "critical_detail_census_completed", "shared_blockers")}}
