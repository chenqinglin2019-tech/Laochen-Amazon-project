"""Anchor product quick-check: open sibling generation after the raw anchor is judged.

The full review (layout, text, export) still happens later and is still required
for QA and delivery. This proof only states that the anchor's raw product image
matches the evidence (identity, geometry, material, components, clarity). It is
bound to the generation fingerprint, the raw bytes, the evidence dependencies and
the product review rules, so any change closes the gate again. No model calls.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

CHECKS = ("geometry", "material", "components", "clarity")
READY_STATUSES = {"generated", "review_pending", "layout_repair_needed", "export_repair_needed", "qa_passed"}


def anchor_context(manifest, job, base):
    import lc_image_pipeline as p
    from lc_dependencies import evidence_dependencies
    from lc_review_rules import rule_hashes
    raw = p.resolve_path(job.get("raw_output"), base)
    context = {"generation": p.generation_fingerprint(manifest, job, base),
               "raw": p.sha256_file(raw) if raw and raw.is_file() else None,
               "evidence": evidence_dependencies(manifest, job, base)}
    context.update(rule_hashes("product", manifest, job))
    return context


def _verdicts(verdicts=None, notes=None):
    if verdicts is None:
        if not isinstance(notes, str) or not notes.strip():
            raise ValueError("anchor-approve needs --notes describing what was checked, or --verdicts")
        verdicts = {name: {"verdict": "pass", "notes": notes.strip()} for name in CHECKS}
    if not isinstance(verdicts, dict) or set(verdicts) != set(CHECKS):
        raise ValueError(f"anchor verdicts must contain exactly: {', '.join(CHECKS)}")
    for name, value in verdicts.items():
        if (not isinstance(value, dict) or value.get("verdict") not in {"pass", "fail"}
                or not isinstance(value.get("notes"), str) or not value["notes"].strip()):
            raise ValueError(f"anchor verdict {name} needs verdict pass/fail and specific notes")
    return verdicts


def anchor_approve(manifest, base, job_id, *, verdicts=None, notes=None):
    import lc_image_pipeline as p
    base = Path(base).resolve()
    job = p.find_by_id(manifest["jobs"], job_id)
    if job is None:
        raise p.PipelineError(f"Unknown job: {job_id}")
    if manifest.get("anchor_job_id") != job_id:
        raise p.PipelineError(f"{job_id} is not the current anchor ({manifest.get('anchor_job_id')}); only the anchor opens the gate")
    if job.get("status") not in READY_STATUSES:
        raise p.PipelineError(f"Anchor {job_id} has no ingested raw image yet (status {job.get('status')})")
    raw = p.resolve_path(job.get("raw_output"), base)
    if raw is None or not raw.is_file() or p.sha256_file(raw) != job.get("bound_raw_sha256"):
        raise p.PipelineError("Anchor raw image is missing or differs from the ingested artifact")
    try:
        checked = _verdicts(verdicts, notes)
    except ValueError as exc:
        raise p.PipelineError(str(exc)) from exc
    passed = all(value["verdict"] == "pass" for value in checked.values())
    record = {"schema_version": 1, "kind": "anchor_product_check", "job": job_id,
              "status": "product_passed" if passed else "product_failed", "submitted_at": time.time(),
              "product_context": anchor_context(manifest, job, base), "reviews": checked,
              "submission_hash": p.digest(checked)}
    path = base / "review" / "submissions" / f"{job_id}-anchor-{uuid.uuid4().hex[:12]}.json"
    p.write_json(path, record)
    proof = {"path": p.relpath(path, base), "sha256": p.sha256_file(path)}
    if passed:
        job["anchor_product_proof"] = proof
    else:
        job.pop("anchor_product_proof", None)
    return {"job": job_id, "anchor_passed": passed, "proof": proof["path"],
            "next_action": ("siblings may now generate; the anchor still needs its normal full review" if passed
                            else "use review-prepare/review-submit with the failed checks to enter the repair flow")}


def anchor_quick_proof_valid(manifest, job, base):
    """True when a current, intact product quick-check proof exists for this anchor."""
    import lc_image_pipeline as p
    proof = job.get("anchor_product_proof")
    if not isinstance(proof, dict) or job.get("status") not in READY_STATUSES:
        return False
    try:
        path = p.resolve_project_path(proof.get("path"), Path(base), "anchor product proof")
        if path is None or not path.is_file() or p.sha256_file(path) != proof.get("sha256"):
            return False
        record = p.read_json(path)
        if (record.get("kind") != "anchor_product_check" or record.get("job") != job.get("id")
                or record.get("status") != "product_passed"
                or record.get("submission_hash") != p.digest(record.get("reviews"))):
            return False
        return bool(record.get("product_context", {}).get("raw")) and \
            record.get("product_context") == anchor_context(manifest, job, Path(base))
    except (OSError, ValueError, TypeError, KeyError):
        return False
