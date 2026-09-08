#!/usr/bin/env python3
"""Strictly validate evidence coverage, report freshness and secret boundaries."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html as html_module
import io
import json
import re
from pathlib import Path
from typing import Any

from common import (
    configured_credential_values, MODULE_IDS, SOURCE_STATUSES, SUPPORTED_SCHEMA_VERSIONS,
    SERPAPI_PROVIDER, SERPER_PROVIDERS, SIGNA_PROVIDER,
    canonical_coverage_requirements_match, default_discovery_plan_error,
    ensure_object, load_json,
    load_skill_config, path_within, plan_free_policy_matches_task, sha256_file,
    sha256_json, task_free_policy_valid,
)
from annotate_materiality import (
    CANDIDATE_COLLECTIONS, load_materiality_ledger, materiality_ledger_errors,
)
from runtime_timing import timed_cli


FORBIDDEN_BROWSER_FIELDS = {
    "cdp_endpoint", "endpoint", "websocket", "websocket_url",
    "remote_debugging_port", "profile_dir", "user_data_dir",
    "cookies", "local_storage", "localstorage",
}
AUTHORITY_BOUND_API_PROVIDERS = {
    "epo_ops", "euipo_trademark", "euipo_design", "jpo_api",
    "inpi_api", "prv_open_data",
}


def forbidden_browser_paths(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).casefold() in FORBIDDEN_BROWSER_FIELDS:
                found.append(path)
            found.extend(forbidden_browser_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(forbidden_browser_paths(item, f"{prefix}[{index}]"))
    return found
from finalize_assessment import (
    coverage_requirement_gaps, formal_rating_evidence_by_module,
    low_risk_gate_gaps, material_unverified, required_query_gaps, source_gaps,
    verification_plan_binding_errors,
)


def configured_secrets(config: dict[str, Any]) -> list[str]:
    del config
    # Keep the existing substring-detection threshold: short account names can
    # also be ordinary evidence words. Structured credential fields are checked
    # separately by the evidence sanitizers.
    return [value for value in configured_credential_values() if len(value) >= 8]


def validate_v2_bundle(
    task_dir: Path, task: dict[str, Any], evidence: dict[str, Any], assessment: dict[str, Any],
    plan: dict[str, Any], candidates: dict[str, Any], journal: dict[str, Any],
    manifest: dict[str, Any],
) -> list[str]:
    """Validate the standalone schema-2.0 report bundle independently of rendering."""
    from report_v2 import (
        COVERAGE_BOUNDARIES, CSV_FIELDS, REPORT_SCHEMA_NAME, REPORT_SCHEMA_VERSION,
        SECTION_ORDER, VISUAL_LIMIT,
        assessment_module_errors, build_report_data, candidate_rows,
        compute_manifest_content_digest, input_digests, is_official_record_url,
        main_visual_evidence, paid_recommendation_rows,
        release_gate, render_findings_csv, render_html, render_markdown, visual_evidence,
        wipo_traces,
    )

    errors: list[str] = []
    report_data_path = task_dir / "report-data.json"
    report_data = ensure_object(load_json(report_data_path), "report-data.json")
    html_text = (task_dir / "report.html").read_text(encoding="utf-8")
    markdown_text = (task_dir / "report.md").read_text(encoding="utf-8")

    traces = wipo_traces(task_dir, task, evidence, candidates, journal, plan)
    if traces:
        errors.append("2.3 task contains forbidden WIPO source/query/recorder traces: " + ", ".join(traces[:8]))

    if manifest.get("report_schema_version") != REPORT_SCHEMA_VERSION or manifest.get("report_schema") != REPORT_SCHEMA_NAME:
        errors.append("V2 report manifest schema mismatch")
    if manifest.get("content_digest") != compute_manifest_content_digest(manifest):
        errors.append("V2 manifest canonical content digest mismatch")
    if task.get("outputs", {}).get("report_manifest_sha256") != sha256_file(task_dir / "report-manifest.json"):
        errors.append("V2 manifest file digest mismatch")
    if report_data.get("schema_version") != REPORT_SCHEMA_VERSION or report_data.get("report_schema") != REPORT_SCHEMA_NAME:
        errors.append("report-data.json schema mismatch")
    if report_data.get("coverage_boundaries") != COVERAGE_BOUNDARIES:
        errors.append("report-data.json coverage boundaries are missing or stale")
    for boundary in COVERAGE_BOUNDARIES:
        if boundary not in html_text or boundary not in markdown_text:
            errors.append(f"Rendered reports are missing a coverage boundary: {boundary}")
    evidence_collections = (
        evidence.get("collections", {})
        if isinstance(evidence.get("collections"), dict) else {}
    )
    known_evidence = {
        str(entry.get("evidence_id") or "").strip()
        for values in evidence_collections.values()
        if isinstance(values, list)
        for entry in values
        if isinstance(entry, dict) and str(entry.get("evidence_id") or "").strip()
    }
    module_contract_errors = assessment_module_errors(
        assessment, known_evidence=known_evidence,
        formal_risk_evidence=formal_rating_evidence_by_module(
            task, evidence, candidates, plan,
        ),
    )
    errors.extend(
        f"INVALID_ASSESSMENT_MODULES: {detail}"
        for detail in module_contract_errors
    )
    for label, payload in (("manifest", manifest), ("report-data", report_data)):
        if payload.get("task_id") != task.get("task_id") or payload.get("task_schema_version") != task.get("schema_version"):
            errors.append(f"V2 {label} task identity/schema mismatch")
        if payload.get("section_order") != SECTION_ORDER:
            errors.append(f"V2 {label} section order mismatch")

    materiality_ledger = load_materiality_ledger(
        task_dir, str(task.get("task_id") or ""),
    )
    errors.extend(materiality_ledger_errors(
        materiality_ledger, str(task.get("task_id") or ""), candidates,
    ))
    expected_digests = input_digests(
        task, evidence, assessment, candidates, journal, plan,
        materiality_ledger,
    )
    if manifest.get("input_digests") != expected_digests:
        errors.append("V2 manifest is stale relative to task inputs")
    if report_data.get("trace", {}).get("input_digests") != expected_digests:
        errors.append("report-data.json is stale relative to task inputs")
    if report_data.get("trace", {}).get("materiality_ledger") != {
        "path": "materiality-annotations.json",
        "annotation_count": len(materiality_ledger.get("annotations", [])),
    }:
        errors.append("report-data materiality ledger summary is stale")

    expected_report_data: dict[str, Any] | None = None
    try:
        expected_report_data = build_report_data(
            task_dir, task, evidence, assessment, candidates, journal, plan,
            generated_at=str(report_data.get("generated_at") or ""),
        )
    except ValueError as exc:
        errors.append(f"Unable to reconstruct canonical report-data: {exc}")
    if expected_report_data is not None and report_data != expected_report_data:
        errors.append("report-data.json is not the canonical task view model")

    if expected_report_data is not None:
        canonical_report_data_bytes = (
            json.dumps(expected_report_data, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        canonical_report_data_digest = hashlib.sha256(canonical_report_data_bytes).hexdigest()
        expected_rendered = {
            "report.html": render_html(
                expected_report_data, canonical_report_data_digest,
                len(canonical_report_data_bytes),
            ).encode("utf-8"),
            "report.md": render_markdown(
                expected_report_data, canonical_report_data_digest,
                len(canonical_report_data_bytes),
            ).encode("utf-8"),
            "report-findings.csv": render_findings_csv(expected_report_data).encode("utf-8-sig"),
        }
        for artifact_name, expected_bytes in expected_rendered.items():
            artifact_path = task_dir / artifact_name
            if artifact_path.is_file() and artifact_path.read_bytes() != expected_bytes:
                errors.append(
                    f"{artifact_name} is not the deterministic rendering of report-data.json"
                )

    expected_artifacts = {"report-data.json", "report.html", "report.md", "report-findings.csv"}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != expected_artifacts:
        errors.append("V2 manifest must bind exactly the four non-manifest report artifacts")
        artifacts = artifacts if isinstance(artifacts, dict) else {}
    for name in expected_artifacts:
        metadata = artifacts.get(name, {}) if isinstance(artifacts.get(name), dict) else {}
        declared_path = Path(str(metadata.get("path") or ""))
        path = (task_dir / declared_path).resolve()
        if declared_path.is_absolute() or path != (task_dir / name).resolve() or not path_within(path, task_dir):
            errors.append(f"V2 artifact path binding mismatch: {name}")
            path = task_dir / name
        if not path.is_file():
            errors.append(f"Missing V2 artifact: {name}")
            continue
        if metadata.get("sha256") != sha256_file(path) or metadata.get("bytes") != path.stat().st_size:
            errors.append(f"V2 artifact digest/byte mismatch: {name}")
    duplicates = list(task_dir.rglob("report-data.json"))
    if len(duplicates) != 1 or duplicates[0].resolve() != report_data_path.resolve():
        errors.append("Task must contain exactly one canonical report-data.json")

    output_fields = {
        "report_data": "report-data.json", "report_html": "report.html", "report_md": "report.md",
        "report_findings_csv": "report-findings.csv", "report_manifest": "report-manifest.json",
    }
    outputs = task.get("outputs", {}) if isinstance(task.get("outputs"), dict) else {}
    for field, name in output_fields.items():
        if Path(str(outputs.get(field) or "")).resolve() != (task_dir / name).resolve():
            errors.append(f"Task output path mismatch: {field}")
    if outputs.get("report_schema_version") != REPORT_SCHEMA_VERSION:
        errors.append("Task output report schema version mismatch")
    if outputs.get("report_mode") != report_data.get("report_mode"):
        errors.append("Task output report mode mismatch")
    expected_artifact_digests = {
        name: metadata.get("sha256") for name, metadata in artifacts.items() if isinstance(metadata, dict)
    }
    if outputs.get("artifact_digests") != expected_artifact_digests:
        errors.append("Task output artifact digests are stale")

    gate = release_gate(task, evidence, assessment, candidates, journal, plan)
    if report_data.get("report_mode") != gate["report_mode"] or report_data.get("formal_allowed") != gate["formal_allowed"]:
        errors.append("V2 Draft/Formal gate is stale")
    decision = report_data.get("decision", {}) if isinstance(report_data.get("decision"), dict) else {}
    if (
        decision.get("final_risk") != gate["final_risk"]
        or decision.get("display_risk") != gate["display_risk"]
        or decision.get("confidence") != gate["confidence"]
        or decision.get("risk_basis") != gate["risk_basis"]
    ):
        errors.append("V2 decision does not match the recomputed release gate")
    if report_data.get("blockers") != gate["blockers"]:
        errors.append("V2 report blockers do not match the recomputed release gate")
    if gate["report_mode"] == "Draft" and decision.get("final_risk") is not None:
        errors.append("Draft report must not expose a final risk")
    if gate["report_mode"] == "Formal" and decision.get("final_risk") not in {"极低", "低", "中", "高", "极高"}:
        errors.append("Formal report has no valid final risk")
    report_modules = report_data.get("modules")
    if not isinstance(report_modules, list):
        errors.append("report-data modules must be an array")
        report_modules = []
    if [item.get("module_id") for item in report_modules if isinstance(item, dict)] != MODULE_IDS:
        errors.append("V2 report must contain the seven required modules in canonical order")
    if gate["report_mode"] == "Draft":
        for item in report_modules:
            if not isinstance(item, dict):
                continue
            if (
                item.get("risk") != "无法判断"
                or item.get("confidence") != "无法判断"
                or item.get("risk_basis") != "discovery_only"
            ):
                errors.append("Draft report modules must not expose assessment risk/confidence")
                break
        if html_text.count("发现层风险（非正式）") != 1:
            errors.append("Draft HTML must contain the exact discovery-only decision label once")
        if "- 发现层风险（非正式）：**" not in markdown_text:
            errors.append("Draft Markdown is missing the exact discovery-only decision label")
    if manifest.get("report_mode") != gate["report_mode"] or manifest.get("formal_allowed") != gate["formal_allowed"]:
        errors.append("V2 manifest release gate is stale")
    overall = assessment.get("overall", {}) if isinstance(assessment.get("overall"), dict) else {}
    expected_formal_status = {
        "task_state": str(task.get("state") or ""),
        "assessment_status": str(assessment.get("status") or ""),
        "assessment_risk": str(overall.get("risk") or ""),
        "assessment_provisional": overall.get("provisional"),
        "formal_allowed": gate["formal_allowed"],
    }
    if manifest.get("formal_status") != expected_formal_status:
        errors.append("V2 manifest task/assessment formal status is stale")

    expected_candidates = candidate_rows(candidates)
    report_candidates = report_data.get("candidates")
    if not isinstance(report_candidates, list):
        errors.append("report-data candidates must be an array")
        report_candidates = []
    expected_ids = [row["candidate_id"] for row in expected_candidates]
    actual_ids = [item.get("candidate_id") for item in report_candidates if isinstance(item, dict)]
    if report_candidates != expected_candidates or actual_ids != expected_ids:
        errors.append("V2 report does not contain the complete normalized candidate set")
    for item in report_candidates:
        if not isinstance(item, dict):
            continue
        urls = [item.get("url")]
        verification = item.get("official_verification")
        if isinstance(verification, dict):
            urls.append(verification.get("url"))
        for url in (str(value) for value in urls if value):
            if not is_official_record_url(url):
                errors.append(f"Candidate link is outside the official record allowlist: {url[:100]}")
    report_coverage = report_data.get("coverage", {}) if isinstance(report_data.get("coverage"), dict) else {}
    for key, value in gate["computed"].items():
        if report_coverage.get(key) != value:
            errors.append(f"V2 report coverage is stale for {key}")
    if report_coverage.get("candidate_count") != len(expected_candidates):
        errors.append("V2 report candidate count is stale")
    if report_coverage.get("material_candidate_count") != sum(1 for row in expected_candidates if row["material"]):
        errors.append("V2 report material candidate count is stale")
    requirement_count = len(task.get("coverage_requirements", [])) if isinstance(task.get("coverage_requirements"), list) else 0
    if report_coverage.get("requirement_count") != requirement_count:
        errors.append("V2 report coverage requirement count is stale")
    for candidate_id in expected_ids:
        markdown_id = str(candidate_id).replace("\\", "\\\\").replace("|", "\\|")
        if html_module.escape(str(candidate_id), quote=True) not in html_text or markdown_id not in markdown_text:
            errors.append(f"Candidate is missing from rendered reports: {candidate_id}")
    if report_data.get("paid_recommendations") != paid_recommendation_rows(assessment):
        errors.append("V2 paid upgrade recommendations are stale")

    def validate_embedded_visual(
        item: dict[str, Any], label: str, manifest_binding: dict[str, Any],
    ) -> None:
        data_uri = str(item.get("data_uri") or "")
        match = re.fullmatch(r"data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/=]+)", data_uri)
        if not match or match.group(1) != item.get("mime_type"):
            errors.append(f"Invalid {label} Data URI: {item.get('evidence_id')}")
            return
        try:
            payload = base64.b64decode(match.group(2), validate=True)
        except ValueError:
            errors.append(f"Invalid {label} base64: {item.get('evidence_id')}")
            return
        if len(payload) != item.get("bytes") or sha256_file_bytes(payload) != item.get("sha256"):
            errors.append(f"Embedded {label} hash/byte mismatch: {item.get('evidence_id')}")
        relative_path = Path(str(item.get("relative_path") or ""))
        local_path = (task_dir / relative_path).resolve()
        if not local_path.is_file() or not path_within(local_path, task_dir):
            errors.append(f"{label.title()} source file is missing/outside task: {relative_path}")
        elif sha256_file(local_path) != item.get("sha256") or local_path.stat().st_size != item.get("bytes"):
            errors.append(f"{label.title()} source file hash/byte mismatch: {relative_path}")
        for key in ("relative_path", "mime_type", "sha256", "bytes"):
            if manifest_binding.get(key) != item.get(key):
                errors.append(f"Manifest {label} binding mismatch for {item.get('evidence_id')}: {key}")
                break

    product_data = report_data.get("product") if isinstance(report_data.get("product"), dict) else {}
    report_main = product_data.get("main_visual") if isinstance(product_data.get("main_visual"), dict) else None
    try:
        expected_main = main_visual_evidence(task_dir, task)
    except ValueError as exc:
        errors.append(f"Declared main visual integrity failure: {exc}")
        expected_main = None
    if report_main != expected_main:
        errors.append("V2 product main visual binding is stale")
    manifest_main = manifest.get("main_visual") if isinstance(manifest.get("main_visual"), dict) else {}
    if report_main:
        validate_embedded_visual(report_main, "main visual", manifest_main)
    elif manifest_main:
        errors.append("Manifest declares a main visual that report-data does not contain")

    visuals = report_data.get("visual_evidence")
    if not isinstance(visuals, list):
        errors.append("report-data visual_evidence must be an array")
        visuals = []
    if len(visuals) > VISUAL_LIMIT:
        errors.append(f"V2 visual evidence exceeds the {VISUAL_LIMIT}-item limit")
    try:
        # This validates every declared candidate/evidence image before applying
        # the 12-card display limit, so an omitted 13th image cannot be tampered.
        expected_visuals = visual_evidence(task_dir, task, evidence, candidates, assessment)
    except ValueError as exc:
        errors.append(f"Declared visual integrity failure: {exc}")
        expected_visuals = []
    if visuals != expected_visuals:
        errors.append("V2 visual evidence selection, source binding or stable order is stale")
    manifest_visuals = manifest.get("visual_evidence") if isinstance(manifest.get("visual_evidence"), list) else []
    manifest_visual_by_id = {
        item.get("evidence_id"): item for item in manifest_visuals if isinstance(item, dict)
    }
    for item in visuals:
        if not isinstance(item, dict):
            errors.append("Visual evidence entry must be an object")
            continue
        bound = manifest_visual_by_id.get(item.get("evidence_id"), {})
        validate_embedded_visual(item, "visual", bound)
    if len(manifest_visuals) != len(visuals):
        errors.append("Manifest visual evidence count mismatch")

    section_positions: list[int] = []
    for section_id in SECTION_ORDER:
        marker = f'<section id="{section_id}"'
        if html_text.count(marker) != 1:
            errors.append(f"HTML must contain exactly one #{section_id} section")
        section_positions.append(html_text.find(marker))
    if any(position < 0 for position in section_positions) or section_positions != sorted(section_positions):
        errors.append("HTML eight-section DOM order mismatch")
    if len(re.findall(r"<section\b", html_text, re.I)) != len(SECTION_ORDER):
        errors.append("HTML must contain exactly the eight prescribed sections")
    html_count_bindings = {
        ("coverage", "query-count"): report_coverage.get("required_query_count"),
        ("coverage", "candidate-count"): report_coverage.get("candidate_count"),
        ("gaps", "gap-count"): (
            len(report_data.get("blockers", []))
            + len(report_data.get("discovery_degradations", []))
        ),
        ("modules", "module-count"): len(report_data.get("modules", [])),
        ("visual", "visual-count"): len(visuals),
        ("candidates", "candidate-count"): len(report_candidates),
    }
    for (section_id, field), expected in html_count_bindings.items():
        match = re.search(
            rf'<section\s+id="{re.escape(section_id)}"[^>]*\bdata-{re.escape(field)}="(\d+)"',
            html_text, re.I,
        )
        if not match or int(match.group(1)) != expected:
            errors.append(f"HTML #{section_id} {field} does not match report-data")
    excluded_count = sum(
        1 for item in report_candidates
        if isinstance(item, dict) and str(item.get("disposition") or "").casefold() == "excluded"
    )
    candidate_start = html_text.find('<section id="candidates"')
    candidate_end = html_text.find('<section id="trace"')
    candidate_markup = html_text[candidate_start:candidate_end]
    details_marker = '<details class="fold print-hidden">'
    print_marker = (
        '<div class="print-only excluded-print" '
        f'data-print-excluded-count="{excluded_count}">'
    )
    if excluded_count:
        if candidate_markup.count(details_marker) != 1 or candidate_markup.count(print_marker) != 1:
            errors.append("HTML excluded candidates need one screen details block and one print-only copy")
        elif not (
            candidate_markup.find("待处置或重大候选")
            < candidate_markup.find(details_marker)
            < candidate_markup.find(print_marker)
        ):
            errors.append("HTML candidate details/print-only block order mismatch")
    elif details_marker in candidate_markup or "data-print-excluded-count=" in candidate_markup:
        errors.append("HTML contains excluded-candidate containers without excluded candidates")
    if f'name="report-schema" content="{REPORT_SCHEMA_NAME}"' not in html_text:
        errors.append("HTML report schema meta is missing")
    if f'name="report-mode" content="{gate["report_mode"]}"' not in html_text:
        errors.append("HTML report mode meta is missing or stale")
    forbidden_markup = re.search(r"<(?:script|link|iframe|object|embed)\b|@import\b|url\(\s*['\"]?https?://", html_text, re.I)
    if forbidden_markup:
        errors.append("HTML contains script or remote/active resource markup")
    for source in re.findall(r"<(?:img|source)\b[^>]*\bsrc=[\"']([^\"']+)", html_text, re.I):
        if not source.startswith("data:image/"):
            errors.append(f"HTML image is not embedded as a Data URI: {source[:80]}")
    for href in re.findall(r"<a\b[^>]*\bhref=[\"']([^\"']+)", html_text, re.I):
        value = html_module.unescape(href)
        if value.startswith("#"):
            if value[1:] not in SECTION_ORDER:
                errors.append(f"HTML contains an unknown internal link: {value}")
        elif not is_official_record_url(value):
            errors.append(f"HTML link is outside the official record allowlist: {value[:100]}")
    if "@media (max-width:" not in html_text or "@media print" not in html_text:
        errors.append("HTML responsive or print stylesheet is missing")
    report_data_digest = sha256_file(report_data_path)
    if report_data_digest not in html_text or report_data_digest not in markdown_text:
        errors.append("Rendered reports do not bind the canonical report-data digest")

    csv_text = (task_dir / "report-findings.csv").read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    if reader.fieldnames != CSV_FIELDS:
        errors.append("report-findings.csv header mismatch")
    expected_findings = [
        (module.get("module_id"), finding.get("finding_id"))
        for module in report_data.get("modules", []) if isinstance(module, dict)
        for finding in module.get("findings", []) if isinstance(finding, dict)
    ]
    actual_findings = [(row.get("module_id"), row.get("finding_id")) for row in rows]
    if actual_findings != expected_findings:
        errors.append("report-findings.csv does not contain the complete ordered finding set")
    return errors


def sha256_file_bytes(payload: bytes) -> str:
    import hashlib
    return hashlib.sha256(payload).hexdigest()


@timed_cli("report_validation")
def main() -> None:
    parser = argparse.ArgumentParser(description="Validate one IPR task directory.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    errors: list[str] = []
    task_path = task_dir / "task.json"
    if not task_path.is_file():
        raise SystemExit("validation failed:\n- Missing task.json")
    task = ensure_object(load_json(task_path), "task.json")
    output_dir = args.output_dir.resolve() if args.output_dir else task_dir
    assessment_path = output_dir / "assessment.json"
    estimate_assessment = ensure_object(load_json(assessment_path), "assessment.json") if assessment_path.is_file() else {}
    policy = estimate_assessment.get("assessment_policy") or task.get("assessment_policy")
    if policy:
        if policy != "evidence-estimate-v1":
            raise SystemExit("Unsupported assessment_policy: " + str(policy))
        from assessment_estimate import report_input_context
        task_dir, task = report_input_context(task_dir, task, output_dir)
        from report_estimate import validate_run as validate_estimate_run
        estimate_errors = validate_estimate_run(task_dir, task, output_dir=output_dir)
        if estimate_errors:
            raise SystemExit("validation failed:\n- " + "\n- ".join(estimate_errors))
        from common import recall_integrity_enabled
        if recall_integrity_enabled(task):
            print("file_integrity: valid; business_completion: " + str(estimate_assessment.get("status", "incomplete")) + " (evidence-estimate-v1)")
            if task.get("decision_workflow_revision") == "scenario-triage-v1":
                overall = estimate_assessment["overall"]
                print("primary_scenario: " + overall["scenario_id"] + "; current_risk: " + str(overall.get("risk") or "pending")
                      + "; confidence: " + overall["confidence"] + "; primary_completion: " + overall["primary_completion"])
        else:
            print("run valid (evidence-estimate-v1)")
        return
    if args.output_dir:
        parser.error("Output option requires evidence-estimate-v1")
    task_schema = str(task.get("schema_version") or "")
    if task_schema == "2.4-free":
        from report_v24 import validate_run as validate_scoped_run
        scoped_errors = validate_scoped_run(task_dir, task)
        if scoped_errors:
            raise SystemExit("validation failed:\n- " + "\n- ".join(scoped_errors))
        print("run valid")
        return
    is_v2 = task_schema == "2.3-free"
    if is_v2 and not task_free_policy_valid(task):
        errors.append("FREE_POLICY_INVALID: task must use its immutable recognized free policy")
    if is_v2 and not canonical_coverage_requirements_match(task):
        errors.append(
            "COVERAGE_REQUIREMENTS_INVALID: task coverage must match the canonical jurisdiction routes"
        )
    required_files = [
        "task.json", "evidence.json", "assessment.json", "search-plan.json",
        "normalized-candidates.json", "report.md", "report.html", "report-manifest.json",
    ]
    if is_v2:
        required_files += ["report-data.json", "report-findings.csv"]
    for name in required_files:
        if not (task_dir / name).is_file():
            errors.append(f"Missing {name}")
    if errors:
        raise SystemExit("validation failed:\n- " + "\n- ".join(errors))

    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    assessment = ensure_object(load_json(task_dir / "assessment.json"), "assessment.json")
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
    candidates = ensure_object(load_json(task_dir / "normalized-candidates.json"), "normalized-candidates.json")
    manifest = ensure_object(load_json(task_dir / "report-manifest.json"), "report-manifest.json")
    journal_path = task_dir / "browser-candidate-journal.json"
    journal = ensure_object(load_json(journal_path), "browser-candidate-journal.json") if journal_path.exists() else {
        "schema_version": "1.0", "task_id": task.get("task_id"), "entries": [],
    }

    if task_schema not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(f"Unsupported task schema version: {task_schema}")
    for label, payload in (("task", task), ("evidence", evidence), ("assessment", assessment), ("plan", plan), ("candidates", candidates)):
        if payload.get("schema_version") != task_schema:
            errors.append(f"{label} schema version mismatch")
        if payload.get("task_id") != task.get("task_id"):
            errors.append(f"{label} task_id mismatch")
    if is_v2:
        if not plan_free_policy_matches_task(task, plan):
            errors.append("FREE_POLICY_INVALID: search plan policy/revision does not match task")
        default_discovery_error = default_discovery_plan_error(task, plan)
        if default_discovery_error:
            errors.append(default_discovery_error)
        errors.extend(
            "OFFICIAL_VERIFICATION_PLAN_BINDING_INVALID: " + detail
            for detail in verification_plan_binding_errors(
                task, evidence, candidates, plan,
            )
        )

    expected_state = {"completed": "completed", "incomplete": "incomplete", "needs_review": "needs_review"}.get(str(assessment.get("status")))
    if expected_state and task.get("state") != expected_state:
        errors.append(f"Task state {task.get('state')} does not match assessment status {assessment.get('status')}")

    if len(task.get("images", [])) != 1:
        errors.append("Exactly one main image is required")
    else:
        image = task["images"][0]
        path = Path(str(image.get("path", ""))).resolve()
        if not path.is_file() or not path_within(path, task_dir / "images") or sha256_file(path) != image.get("sha256"):
            errors.append("Main image path/hash validation failed")

    if journal.get("schema_version") != "1.0" or journal.get("task_id") != task.get("task_id"):
        errors.append("Browser candidate journal identity/schema mismatch")
    journal_entries = journal.get("entries", [])
    if not isinstance(journal_entries, list):
        errors.append("Browser candidate journal entries must be an array")
        journal_entries = []
    unresolved_journal: list[str] = []
    verified_candidate_ids = {
        (
            str(item.get("right_type") or {
                "patents": "patent", "trademarks": "trademark_word",
                "copyright_assets": "copyright", "enforcement": "enforcement",
            }.get(collection, "")),
            re.sub(r"[^A-Za-z0-9]", "", str(item.get(key) or "")).upper(),
        )
        for collection in CANDIDATE_COLLECTIONS
        for item in candidates.get(collection, [])
        if isinstance(item, dict) and item.get("official_verification", {}).get("status") == "verified"
        for key in (
            "publication_number", "grant_number", "application_number", "record_number",
            "serial_number", "registration_number", "case_number", "docket_number",
        )
        if item.get(key)
    }
    verified_any_ids = {record for _, record in verified_candidate_ids}
    for entry in journal_entries:
        if not isinstance(entry, dict):
            errors.append("Browser candidate journal entry must be an object")
            continue
        record = re.sub(r"[^A-Za-z0-9]", "", str(entry.get("record_number") or "")).upper()
        right_type = str(entry.get("right_type") or "")
        status = str(entry.get("status") or "")
        if not record or not entry.get("provider"):
            errors.append("Browser candidate journal entry is missing provider/record_number")
        if status not in {"pending", "success", "no_result", "needs_user_action", "access_limited", "failed"}:
            errors.append(f"Invalid browser candidate journal status: {status}")
        if status == "success" and not (
            (right_type and (right_type, record) in verified_candidate_ids)
            or (not right_type and record in verified_any_ids)
        ):
            errors.append(f"Successful viewed candidate was not ingested as officially verified: {record}")
        if status in {"pending", "needs_user_action", "access_limited", "failed"}:
            unresolved_journal.append(record or "unknown")
        for key in ("screenshot_path", "capture_path"):
            raw_path = entry.get(key)
            if not raw_path:
                continue
            path = Path(str(raw_path)).resolve()
            expected_root = task_dir / ("screenshots" if key == "screenshot_path" else "")
            if not path.is_file() or not path_within(path, expected_root):
                errors.append(f"Browser candidate journal {key} is missing or outside task: {raw_path}")

    run_ids: set[str] = set()
    for run in evidence.get("source_runs", []):
        run_id = str(run.get("run_id") or "")
        if not run_id or run_id in run_ids:
            errors.append(f"Missing or duplicate run_id: {run_id}")
        run_ids.add(run_id)
        if not run.get("query_id"):
            errors.append(f"Source run has no query_id: {run_id}")
        if run.get("status") not in SOURCE_STATUSES:
            errors.append(f"Invalid source status: {run.get('status')}")
        if run.get("status") == "no_result" and run.get("error_code"):
            errors.append(f"no_result run has error code: {run_id}")
        if is_v2:
            provider = str(run.get("provider") or "")
            operation = str(run.get("operation") or "")
            if (
                provider in {*SERPER_PROVIDERS, SERPAPI_PROVIDER, SIGNA_PROVIDER}
                and run.get("authoritative_for_final_rating") is not False
            ):
                errors.append(f"Discovery-only provider claims or omits non-authority binding: {run_id}")
            if provider in AUTHORITY_BOUND_API_PROVIDERS and run.get("status") in {
                "success", "no_result",
            }:
                environment = str(run.get("source_environment") or "")
                authoritative = run.get("authoritative_for_final_rating")
                if not environment or not isinstance(authoritative, bool):
                    errors.append(f"Authority-bound API run has no environment/authority binding: {run_id}")
                elif authoritative and environment != "production":
                    errors.append(f"Non-production API run claims formal authority: {run_id}")
            routed = [
                requirement for requirement in task.get("coverage_requirements", [])
                if isinstance(requirement, dict)
                and any(
                    isinstance(route, dict)
                    and str(route.get("provider") or "") == provider
                    and str(route.get("operation") or "") == operation
                    for route in requirement.get("routes", [])
                )
            ]
            if routed:
                right_type = str(run.get("right_type") or "")
                requirement_ids = {
                    str(value) for value in run.get("requirement_ids", [])
                    if str(value).strip()
                }
                matching_ids = {
                    str(requirement.get("requirement_id") or "")
                    for requirement in routed
                    if str(requirement.get("jurisdiction") or "").upper()
                    == str(run.get("jurisdiction") or "").upper()
                    and str(requirement.get("right_type") or "") == right_type
                }
                if not right_type:
                    errors.append(f"Routed 2.3 source run has no right_type: {run_id}")
                if not requirement_ids:
                    errors.append(f"Routed 2.3 source run has no requirement_ids: {run_id}")
                elif not requirement_ids <= matching_ids:
                    errors.append(f"Routed 2.3 source run has invalid requirement binding: {run_id}")
        for raw in run.get("raw_paths", []):
            path = Path(str(raw)).resolve()
            if not path.is_file() or not path_within(path, task_dir / "raw"):
                errors.append(f"Raw evidence is missing or outside task raw/: {raw}")
            elif run.get("payload_digest") and sha256_file(path) != run.get("payload_digest"):
                errors.append(f"Raw evidence digest mismatch: {raw}")

    recomputed_queries = required_query_gaps(task, evidence, plan)
    recomputed_unverified = material_unverified(
        candidates, strict=is_v2, evidence=evidence if is_v2 else None,
        task=task if is_v2 else None, search_plan=plan if is_v2 else None,
    )
    coverage = assessment.get("coverage", {})
    if is_v2:
        from report_v2 import coverage_gap_groups
        recomputed_requirements = coverage_requirement_gaps(task, evidence, candidates, plan)
        grouped_requirements = coverage_gap_groups(task, recomputed_requirements)
        recomputed_formal = grouped_requirements["formal"]
        recomputed_low_risk = [*grouped_requirements["low_risk"], *grouped_requirements["unsupported"]]
        recomputed_unsupported = grouped_requirements["unsupported"]
        recomputed_sources: list[str] = []
        recomputed_gates: list[str] = []
        comparisons = (
            ("missing_coverage_requirements", recomputed_requirements),
            ("missing_formal_requirements", recomputed_formal),
            ("missing_low_risk_requirements", recomputed_low_risk),
            ("missing_required_queries", recomputed_queries),
            ("unverified_material_candidates", recomputed_unverified),
        )
        if coverage.get("missing_low_risk_gate_sources", []) != []:
            errors.append("2.3 assessment must not retain legacy low-risk gate gaps")
    else:
        recomputed_requirements = []
        recomputed_formal = []
        recomputed_low_risk = []
        recomputed_unsupported = []
        recomputed_sources = source_gaps(task, evidence, candidates, plan)
        recomputed_gates = low_risk_gate_gaps(task, evidence, plan)
        comparisons = (
            ("missing_required_sources", recomputed_sources),
            ("missing_required_queries", recomputed_queries),
            ("missing_low_risk_gate_sources", recomputed_gates),
            ("unverified_material_candidates", recomputed_unverified),
        )
    for key, recomputed in comparisons:
        if sorted(coverage.get(key, [])) != sorted(recomputed):
            errors.append(f"Assessment coverage is stale for {key}")

    if assessment.get("status") == "completed":
        if assessment.get("overall", {}).get("risk") not in {"极低", "低", "中", "高", "极高"}:
            errors.append("Completed assessment has no valid final risk")
        blocking_requirements = bool(
            recomputed_formal
            or recomputed_unsupported
            or (recomputed_low_risk and assessment.get("overall", {}).get("risk") in {"极低", "低"})
        ) if is_v2 else bool(recomputed_requirements)
        if recomputed_sources or blocking_requirements or recomputed_queries or recomputed_unverified:
            errors.append("Completed assessment has unresolved mandatory evidence")
        if not is_v2 and recomputed_gates and assessment.get("overall", {}).get("risk") in {"极低", "低"}:
            errors.append("Completed low-risk assessment has unfinished patent-browser gates")
        if unresolved_journal:
            errors.append("Completed assessment has unresolved viewed patent candidates")
    elif assessment.get("status") == "incomplete" and assessment.get("overall", {}).get("risk"):
        errors.append("Incomplete assessment must not expose a final risk")

    browser = evidence.get("collections", {}).get("browser", [])
    if not browser:
        errors.append("Browser evidence is missing")
    else:
        screenshots = browser[0].get("screenshots", {})
        hashes = browser[0].get("screenshot_hashes", {})
        for role, raw_path in screenshots.items():
            path = Path(str(raw_path)).resolve()
            if not path.is_file() or not path_within(path, task_dir / "screenshots"):
                errors.append(f"Browser screenshot is missing or outside task: {role}")
            elif hashes.get(role) != sha256_file(path):
                errors.append(f"Browser screenshot digest mismatch: {role}")

    if is_v2:
        errors.extend(validate_v2_bundle(
            task_dir, task, evidence, assessment, plan, candidates, journal, manifest,
        ))
    else:
        if manifest.get("report_schema_version") != "1.0" or manifest.get("task_id") != task.get("task_id"):
            errors.append("Report manifest identity/schema mismatch")
        task_for_digest = {**task, "outputs": {}}
        expected_digests = {
            "task": sha256_json(task_for_digest), "evidence": sha256_json(evidence),
            "assessment": sha256_json(assessment), "candidates": sha256_json(candidates),
            "candidate_journal": sha256_json(journal),
        }
        if manifest.get("input_digests") != expected_digests:
            errors.append("Report is stale relative to task evidence or assessment")
        for item in manifest.get("key_evidence", []):
            path = Path(str(item.get("path", ""))).resolve()
            if not path.is_file() or not path_within(path, task_dir) or sha256_file(path) != item.get("sha256"):
                errors.append(f"Key evidence path/hash mismatch: {path}")

    report_md = (task_dir / "report.md").read_text(encoding="utf-8")
    report_html = (task_dir / "report.html").read_text(encoding="utf-8")
    for entry in journal_entries:
        record = str(entry.get("record_number") or "") if isinstance(entry, dict) else ""
        if record and record not in report_md and record not in report_html:
            errors.append(f"Viewed patent candidate is missing from report: {record}")
    if not is_v2 and 'name="report-schema" content="IPR-EVIDENCE-DOSSIER/1.0"' not in report_html:
        errors.append("HTML report does not use the fixed dossier format")
    secrets = configured_secrets(load_skill_config())
    public_text = report_md + report_html + (task_dir / "evidence.json").read_text(encoding="utf-8")
    if is_v2:
        public_text += (task_dir / "report-data.json").read_text(encoding="utf-8")
        public_text += (task_dir / "report-findings.csv").read_text(encoding="utf-8-sig")
    if journal_path.exists():
        public_text += journal_path.read_text(encoding="utf-8")
    if any(secret in public_text for secret in secrets):
        errors.append("A configured secret appears in report or evidence JSON")
    browser_leaks = forbidden_browser_paths({
        "task": task, "evidence": evidence, "assessment": assessment,
        "plan": plan, "candidates": candidates, "journal": journal, "manifest": manifest,
        "report_data": load_json(task_dir / "report-data.json") if is_v2 else {},
    })
    if browser_leaks:
        errors.append("Forbidden browser session fields appear in artifacts: " + ", ".join(browser_leaks[:5]))

    if errors:
        raise SystemExit("validation failed:\n- " + "\n- ".join(errors))
    print("run valid")


if __name__ == "__main__":
    main()
