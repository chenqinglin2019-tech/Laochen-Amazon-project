"""Opt-in review-rule hashes with conservative, explicit infrastructure exclusions.

Legacy results preserve the historical payload keys and full-file byte hashes.
The scoped profile includes all remaining top-level code, including new helpers;
it does not infer a fragile transitive call graph or silently ignore new code.
"""
from __future__ import annotations

import ast
import hashlib
from functools import lru_cache
from pathlib import Path

from lc_assets import file_hash

SCRIPT_DIR = Path(__file__).resolve().parent
PROFILE = "scoped_v1"

# These functions orchestrate already-bound visual operations or create disposable
# reports; the actual pixel, validation and review workers remain included.
_EXCLUDED = {
    "lc_image_pipeline.py": frozenset({
        "write_json", "active_model_count", "record_timing", "reported_timings",
        "execution_plan", "transition_job", "prepare", "prepare_prompt_edits", "_prepare_impl",
        "create_micro_detail_sheet", "create_final_contact_sheet", "contact_inputs", "bind_artifact",
        "init_project", "migrate_project", "parser", "run_command", "main", "_run_main_args", "delivery_check",
    }),
    "lc_workflow.py": frozenset({
        "manifest_lock", "_attempt", "attempt_event", "_atomic_bytes", "ingest",
        "_job_artifact_guard", "review_prepare", "review_prepare_many", "_prepare_reviews",
        "review_submit", "review_packet_map", "review_submit_many",
    }),
    "lc_delivery.py": frozenset({
        "_write_json", "retained_input_paths", "_job_input_paths", "_retired_path", "_snapshot_files",
        "persist_review_evidence", "compact_project", "_approved_delivery_images", "_directory_matches",
        "_assert_delivery_directory", "_delivery_directory", "prepare_delivery_directory",
        "_purge_compaction_files", "_rollback_compaction", "recover_compaction", "_directory_result",
        "preserve_owned_overview",
    }),
    "lc_dependencies.py": frozenset({"migrate_dependencies"}),
}


def _read_source(name):
    return (SCRIPT_DIR / name).read_text(encoding="utf-8")


@lru_cache(maxsize=64)
def _slice_source(name, source):
    """Hash definitions/constants/imports, not line positions or omitted workers.

    Unknown functions and top-level statements are deliberately retained. Mixed
    logging changes inside a visual worker still invalidate conservatively.
    """
    tree = ast.parse(source, filename=name)
    nodes = []
    excluded = _EXCLUDED.get(name, frozenset())
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in excluded:
            continue
        # The executable CLI guard does not define a visual rule.
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"
                and any(isinstance(value, ast.Constant) and value.value == "__main__" for value in node.test.comparators)):
            continue
        nodes.append(ast.dump(node, include_attributes=False))
    return hashlib.sha256("\n".join(nodes).encode("utf-8")).hexdigest()


def _legacy(scope, manifest, job):
    from lc_dependencies import scoped_review_dependencies
    from lc_design import has_panel_sources, resolve_text_mode

    def hashes(*names):
        return {name: file_hash(SCRIPT_DIR / name) for name in names}

    if scope == "product":
        return {"rules": hashes("lc_workflow.py", "lc_dependencies.py", "lc_image_pipeline.py", "lc_quality.py", "lc_assets.py")}
    if scope == "review":
        result = {"rules": hashes("lc_image_pipeline.py", "lc_workflow.py", "lc_assets.py", "lc_quality.py")}
        if resolve_text_mode(job) == "model_native" or has_panel_sources(job):
            result["design_rules"] = file_hash(SCRIPT_DIR / "lc_design.py")
        if scoped_review_dependencies(manifest, job):
            result["dependency_rules"] = file_hash(SCRIPT_DIR / "lc_dependencies.py")
        return result
    result = {"rule_hashes": hashes("lc_image_pipeline.py", "lc_quality.py", "lc_assets.py")}
    if scoped_review_dependencies(manifest, job):
        result["dependency_rule_hashes"] = hashes("lc_dependencies.py", "lc_workflow.py")
    if manifest.get("style_contract") or manifest.get("copy_budget"):
        result["contract_rule_hashes"] = hashes("lc_project_contracts.py", "lc_dependencies.py", "lc_workflow.py", "lc_delivery.py")
    return result


def rule_hashes(scope, manifest, job):
    """Return payload fields for ``payload.update(rule_hashes(...))``.

    Scopes are ``qa``, ``review`` (review packet), and ``product`` (reusable
    product observations). Missing/explicit legacy profile never migrates data.
    """
    if scope not in {"qa", "review", "product"}:
        raise ValueError("Unknown review-rule scope")
    profile = job.get("review_rule_profile", manifest.get("review_rule_profile"))
    if profile is None or profile == "legacy":
        return _legacy(scope, manifest, job)
    if profile != PROFILE:
        raise ValueError("review_rule_profile must be legacy or scoped_v1")
    modules = {"lc_assets.py", "lc_quality.py", "lc_design.py", "lc_project_contracts.py", "lc_review_rules.py"}
    if job.get("kind") != "main" and job.get("text_mode") != "model_native" and job.get("layout"):
        modules.update({"lc_layout.py", "lc_layout_v3.py", "lc_typography.py", "render_layout.mjs"})
    if job.get("title_effect_state") or any(group.get("decorative_effect") for group in job.get("layout", {}).get("text_groups", [])):
        modules.add("lc_title_effects.py")
    if job.get("background_normalization") is not None:
        modules.add("lc_background.py")
    codes = {name: hashlib.sha256(_read_source(name).encode("utf-8")).hexdigest() for name in sorted(modules)}
    codes.update({name: _slice_source(name, _read_source(name)) for name in _EXCLUDED})
    # Keep the former field names: callers can replace each legacy rule field
    # without leaving a hidden full-source hash in their payload.
    result = _legacy(scope, manifest, job)
    for key in result:
        result[key] = {"profile": PROFILE, "scope": scope, "code": codes}
    result["review_rule_profile"] = PROFILE
    return result
