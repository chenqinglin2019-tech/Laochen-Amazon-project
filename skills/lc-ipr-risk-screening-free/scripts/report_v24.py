#!/usr/bin/env python3
"""Scoped 2.4 report using the audited offline dossier renderer and hash format."""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from common import atomic_write_bytes, atomic_write_json, load_json, now_iso, path_within, sha256_bytes, sha256_file, sha256_json
from annotate_materiality import load_materiality_ledger
from assessment_v24 import SCHEMA, compute_assessment
import report_v2 as base

RIGHT_LABELS = {"patent": "发明／功能专利", "utility_model": "实用新型", "design": "注册外观",
                "trademark_word": "文字商标", "trademark_figurative": "图形商标", "copyright": "版权",
                "trade_dress": "商业外观", "unregistered_design": "未注册外观"}
BOUNDARIES = ["结论仅适用于指定商品、使用方式、目标国家和证据核查时点。",
              "检索覆盖表示满足已定义的公开检索要求，不代表排除未公开权利或全部诉讼。",
              "版权、商业外观和未注册外观依赖来源、授权和适用要件证据，登记零结果不能排除其风险。",
              "EP、UP、EU 与国家权利分别核验；局部发现不等于其他国家已完成排查。"]
CSV_FIELDS = ["report_mode", "jurisdiction", "right_type", "candidate_id", "risk", "evidence_confidence",
              "coverage", "publication", "finding_id", "title", "recommended_action", "evidence_refs"]


def canonical_assessment(task_dir: Path, task: dict[str, Any], evidence: dict[str, Any], assessment: dict[str, Any], candidates: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    reviews = assessment.get("review", {}).get("input_reviews", {})
    expected = compute_assessment(task, evidence, candidates, plan,
        load_materiality_ledger(task_dir, task["task_id"]), reviews.get("first", {}), reviews.get("second"),
        generated_at=assessment.get("generated_at"))
    if expected != assessment:
        raise ValueError("ASSESSMENT_STALE_OR_TAMPERED: recomputation from frozen reviews/evidence differs")
    return expected


def build_report_data(task_dir: Path, task: dict[str, Any], evidence: dict[str, Any], assessment: dict[str, Any], candidates: dict[str, Any], journal: dict[str, Any], search_plan: dict[str, Any], *, generated_at: str | None = None) -> dict[str, Any]:
    canonical_assessment(task_dir, task, evidence, assessment, candidates, search_plan)
    ledger = load_materiality_ledger(task_dir, task["task_id"])
    rows = base.candidate_rows(candidates)
    candidate_types = {item.get("candidate_id"): item.get("right_type") for values in candidates.values() if isinstance(values, list) for item in values if isinstance(item, dict)}
    for row in rows:
        # Publication kind A is a document identifier, not today's legal state.
        right_type = candidate_types.get(row["candidate_id"])
        if right_type in RIGHT_LABELS:
            row["module_id"] = right_type
            row["module_name"] = RIGHT_LABELS[right_type]
    scopes = assessment["coverage"]["scopes"]
    confirmed = [row for row in assessment["assessments"] if row["publication"] == "confirmed_scoped"]
    formal = assessment["status"] == "completed" and bool(assessment["overall"].get("risk"))
    mode = "Formal" if formal else "Partial" if confirmed else "Draft"
    overall = assessment["overall"]
    main = base.main_visual_evidence(task_dir, task)
    queries = {row["query_id"]: row for scope in scopes for row in scope["queries"]}
    completed = sum(row["complete"] for row in queries.values())
    product = task.get("product", {})
    runs = base._source_runs(evidence)
    blockers = [{"code": "SCOPED_COVERAGE_INCOMPLETE", "scope": scope["jurisdiction"] + "/" + scope["right_type"],
                 "detail": "该范围尚未完成；不影响其他范围已确认发现。", "items": scope["gaps"]}
                for scope in scopes if scope["gaps"]]
    modules = []
    for row in assessment["assessments"]:
        published = row["publication"] == "confirmed_scoped"
        related = [item for item in rows if item["candidate_id"] == row.get("candidate_id")]
        modules.append({"module_id": "/".join((row["jurisdiction"], row["right_type"], row.get("candidate_id") or "scope")),
            "module_name": row["jurisdiction"] + " · " + RIGHT_LABELS.get(row["right_type"], row["right_type"]) + (" · " + row["candidate_id"] if row.get("candidate_id") else " · 检索范围"),
            "risk": row["risk"], "confidence": row["evidence_confidence"],
            "risk_basis": "formal_assessment" if published else "discovery_only",
            "reasoning": ("已确认分项" if published else "待核实线索") + "；检索覆盖：" + row["coverage"]["status"] + "。" + row["reasoning"]
                         + (" 尚缺：" + "；".join(row["publication_gaps"]) if row["publication_gaps"] else ""),
            "findings": row.get("findings", []), "candidate_count": len(related),
            "material_candidate_count": sum(item["material"] for item in related)})
    for field, label in (("future_applications", "未来申请信号（不计当前风险）"), ("enforcement_signals", "维权与紧急事项（不计当前风险）")):
        signals = assessment.get(field, [])
        if signals:
            modules.append({"module_id": field, "module_name": label, "risk": "单独观察", "confidence": "见证据",
                "risk_basis": "supplemental", "reasoning": "；".join(row["reasoning"] for row in signals),
                "findings": [{"finding_id": field + str(i), "title": row.get("title") or label,
                              "recommended_action": row.get("recommended_action") or row["reasoning"], "evidence_refs": row["evidence_refs"]} for i, row in enumerate(signals)],
                "candidate_count": len(signals), "material_candidate_count": 0})
    gaps = [gap for scope in scopes for gap in scope["gaps"]]
    display_risk = overall["risk"] if formal else overall["known_scoped_risk"] if confirmed else overall["discovery_signal"]
    data = {"schema_version": base.REPORT_SCHEMA_VERSION, "report_schema": base.REPORT_SCHEMA_NAME,
        "task_schema_version": SCHEMA, "task_id": task["task_id"], "generated_at": generated_at or now_iso(),
        "report_mode": mode, "formal_allowed": formal, "section_order": base.SECTION_ORDER,
        "product": {"title": product.get("title", ""), "brand": product.get("brand", ""), "manufacturer": product.get("manufacturer", ""),
                    "category": product.get("category", ""), "asin": product.get("actual_asin") or product.get("requested_asin", ""),
                    "marketplace": task.get("request", {}).get("marketplace", ""), "jurisdictions": task.get("target_jurisdictions", []),
                    "variant": product.get("variant", {}), "bullets": product.get("bullets", []), "specifications": product.get("specifications", {}),
                    "structure": product.get("structure", []), "main_visual_id": main["evidence_id"] if main else "", "main_visual": main},
        "decision": {"report_mode": mode, "formal_allowed": formal, "final_risk": overall["risk"] if formal else None,
                     "display_risk": display_risk, "confidence": overall["confidence"] if confirmed else "低",
                     "risk_basis": "formal_assessment" if formal else "confirmed_scoped" if confirmed else "discovery_only",
                     "assessment_status": assessment["status"], "reasons": overall["reasons"],
                     "known_scoped_risk": overall["known_scoped_risk"], "discovery_signal": overall["discovery_signal"]},
        "coverage": {"requirement_count": len(scopes), "completed_requirement_count": sum(not scope["gaps"] for scope in scopes),
                     "required_query_count": len(queries), "completed_required_query_count": completed,
                     "completion_percent": round(completed * 100 / len(queries)) if queries else 0,
                     "candidate_count": len(rows), "material_candidate_count": sum(row["material"] for row in rows),
                     "missing_coverage_requirements": gaps, "missing_required_queries": [key for key, value in queries.items() if not value["complete"]],
                     "unverified_material_candidates": sorted({row["candidate_id"] for row in assessment["assessments"] if row.get("candidate_id") and row["publication"] != "confirmed_scoped"}),
                     "source_summary": base._source_summary(runs), "scopes": scopes},
        "blockers": blockers, "discovery_degradations": base.default_discovery_degradations(task, evidence, search_plan),
        "modules": modules, "assessments": assessment["assessments"],
        "future_applications": assessment.get("future_applications", []), "enforcement_signals": assessment.get("enforcement_signals", []),
        "visual_evidence": base.visual_evidence(task_dir, task, evidence, candidates, assessment), "candidates": rows,
        "source_runs": runs, "recommended_actions": assessment.get("recommended_actions", []), "paid_recommendations": [],
        "disclaimer": base.DISCLAIMER, "coverage_boundaries": BOUNDARIES,
        "trace": {"input_digests": base.input_digests(task, evidence, assessment, candidates, journal, search_plan, ledger),
                  "materiality_ledger": {"path": "materiality-annotations.json", "annotation_count": len(ledger.get("annotations", []))}},
        "offline_policy": {"images_embedded_as_data_uri": True, "remote_resources": False, "scripts": False, "visual_limit": base.VISUAL_LIMIT}}
    return data


def render_html(data: dict[str, Any], digest: str, size: int) -> str:
    rendered = base.render_html(data, digest, size)
    if data["report_mode"] == "Partial":
        rendered = rendered.replace("发现层风险（非正式）", "已确认分项最高风险（全范围未完成）")
    rendered = rendered.replace("正式结论门禁", "全范围结论门禁").replace("正式评级", "已确认分项评级")
    rendered = rendered.replace("必需查询完成度", "已定义查询完成度（不等于检索穷尽）")
    return rendered


def render_markdown(data: dict[str, Any], digest: str, size: int) -> str:
    rendered = base.render_markdown(data, digest, size)
    if data["report_mode"] == "Partial":
        rendered = rendered.replace("发现层风险（非正式）", "已确认分项最高风险（全范围未完成）")
    return rendered.replace("正式结论门禁", "全范围结论门禁")


def render_findings_csv(data: dict[str, Any]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in data["assessments"]:
        for finding in row.get("findings") or [{}]:
            values = {"report_mode": data["report_mode"], **{key: row.get(key, "") for key in ("jurisdiction", "right_type", "candidate_id", "risk", "evidence_confidence", "publication")},
                      "coverage": row["coverage"]["status"], **{key: finding.get(key, "") for key in ("finding_id", "title", "recommended_action")},
                      "evidence_refs": ";".join(finding.get("evidence_refs") or row.get("evidence_refs", []))}
            writer.writerow({key: base._csv_safe(value) for key, value in values.items()})
    for field in ("future_applications", "enforcement_signals"):
        for index, row in enumerate(data.get(field, [])):
            writer.writerow({key: base._csv_safe(value) for key, value in {
                "report_mode": data["report_mode"], "jurisdiction": row.get("jurisdiction", ""),
                "right_type": field, "candidate_id": row.get("candidate_id", ""), "risk": "单独观察",
                "evidence_confidence": "见证据", "coverage": "不计当前风险", "publication": "supplemental",
                "finding_id": field + str(index), "title": row.get("title", ""),
                "recommended_action": row.get("recommended_action") or row["reasoning"],
                "evidence_refs": ";".join(row["evidence_refs"])}.items()})
    return stream.getvalue()


def bundle_bytes(data: dict[str, Any]) -> dict[str, bytes]:
    content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    digest = sha256_bytes(content)
    return {"report-data.json": content, "report.html": render_html(data, digest, len(content)).encode(),
            "report.md": render_markdown(data, digest, len(content)).encode(),
            "report-findings.csv": render_findings_csv(data).encode("utf-8-sig")}


def build_v24_bundle(task_dir: Path, task: dict[str, Any], evidence: dict[str, Any], assessment: dict[str, Any], candidates: dict[str, Any], journal: dict[str, Any], search_plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    data = build_report_data(task_dir, task, evidence, assessment, candidates, journal, search_plan)
    payloads = bundle_bytes(data)
    for name, value in payloads.items():
        atomic_write_bytes(task_dir / name, value)
    manifest = {"report_schema_version": base.REPORT_SCHEMA_VERSION, "report_schema": base.REPORT_SCHEMA_NAME,
        "task_schema_version": SCHEMA, "task_id": task["task_id"], "generated_at": data["generated_at"],
        "report_mode": data["report_mode"], "formal_allowed": data["formal_allowed"],
        "formal_status": {"task_state": task.get("state"), "assessment_status": assessment["status"],
                          "assessment_risk": assessment["overall"]["risk"], "assessment_provisional": assessment["overall"]["provisional"], "formal_allowed": data["formal_allowed"]},
        "section_order": base.SECTION_ORDER, "input_digests": data["trace"]["input_digests"],
        "artifacts": {name: {"path": name, "sha256": sha256_bytes(value), "bytes": len(value)} for name, value in payloads.items()},
        "offline_policy": data["offline_policy"]}
    manifest["content_digest"] = base.compute_manifest_content_digest(manifest)
    atomic_write_json(task_dir / "report-manifest.json", manifest)
    return data, manifest


def validate_run(task_dir: Path, task: dict[str, Any]) -> list[str]:
    """Recompute assessment, renderers, every digest and offline boundaries."""
    errors = []
    required = ["evidence.json", "assessment.json", "normalized-candidates.json", "search-plan.json", "report-data.json", "report.html", "report.md", "report-findings.csv", "report-manifest.json"]
    if any(not (task_dir / name).is_file() for name in required):
        return ["Missing " + name for name in required if not (task_dir / name).is_file()]
    evidence, assessment, candidates, plan = [load_json(task_dir / name) for name in required[:4]]
    manifest, data = load_json(task_dir / "report-manifest.json"), load_json(task_dir / "report-data.json")
    journal_path = task_dir / "browser-candidate-journal.json"
    journal = load_json(journal_path) if journal_path.exists() else {"schema_version": "1.0", "task_id": task["task_id"], "entries": []}
    from common import canonical_coverage_requirements_match, SOURCE_STATUSES
    if not canonical_coverage_requirements_match(task):
        errors.append("COVERAGE_REQUIREMENTS_INVALID")
    for label, value in (("evidence", evidence), ("assessment", assessment), ("candidates", candidates), ("plan", plan)):
        if value.get("task_id") != task["task_id"] or value.get("schema_version") != SCHEMA:
            errors.append(label + " identity/schema mismatch")
    try:
        expected = build_report_data(task_dir, task, evidence, assessment, candidates, journal, plan, generated_at=data.get("generated_at"))
        if data != expected:
            errors.append("Report data is stale or not canonical")
        for name, value in bundle_bytes(expected).items():
            if (task_dir / name).read_bytes() != value:
                errors.append("Canonical renderer mismatch: " + name)
            if manifest.get("artifacts", {}).get(name) != {"path": name, "sha256": sha256_bytes(value), "bytes": len(value)}:
                errors.append("Artifact manifest mismatch: " + name)
        if manifest.get("input_digests") != expected["trace"]["input_digests"]:
            errors.append("Manifest input digest mismatch")
        if manifest.get("report_mode") != expected["report_mode"] or manifest.get("formal_allowed") != expected["formal_allowed"]:
            errors.append("Manifest publication scope mismatch")
    except (ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    if manifest.get("content_digest") != base.compute_manifest_content_digest(manifest):
        errors.append("Manifest self digest mismatch")
    if (manifest.get("task_id") != task["task_id"] or manifest.get("task_schema_version") != SCHEMA
            or manifest.get("report_schema") != base.REPORT_SCHEMA_NAME or manifest.get("report_schema_version") != base.REPORT_SCHEMA_VERSION
            or manifest.get("section_order") != base.SECTION_ORDER or manifest.get("offline_policy") != data.get("offline_policy")):
        errors.append("Manifest identity/schema/offline policy mismatch")
    if manifest.get("formal_status") != {"task_state": task.get("state"), "assessment_status": assessment["status"],
            "assessment_risk": assessment["overall"]["risk"], "assessment_provisional": assessment["overall"]["provisional"], "formal_allowed": data["formal_allowed"]}:
        errors.append("Manifest formal status mismatch")
    if task.get("outputs", {}).get("report_manifest_sha256") != sha256_file(task_dir / "report-manifest.json"):
        errors.append("Manifest file digest mismatch")
    html = (task_dir / "report.html").read_text()
    if re.findall(r'<section\b[^>]*\bid="([^"]+)"', html) != base.SECTION_ORDER:
        errors.append("HTML must contain exactly eight ordered sections")
    if re.search(r"<script\b|<iframe\b|<link\b|\son\w+\s*=|url\(\s*['\"]?https?", html, re.I):
        errors.append("Active/remote resource in offline report")
    for src in re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', html, re.I):
        if not src.startswith("data:image/"):
            errors.append("Non-embedded report image")
    for href in re.findall(r'\bhref="([^"]+)"', html):
        if not href.startswith(("#", "data:image/")) and href not in {"report-data.json", "report-findings.csv", "report.md", "report-manifest.json"} and not base.is_official_record_url(href):
            errors.append("Report link not allowlisted")
    run_ids = set()
    for run in evidence.get("source_runs", []):
        if not run.get("run_id") or run["run_id"] in run_ids or run.get("status") not in SOURCE_STATUSES:
            errors.append("Invalid/duplicate source run")
        run_ids.add(run.get("run_id"))
        if run.get("status") == "no_result" and run.get("error_code"):
            errors.append("no_result carries an error")
        for raw in run.get("raw_paths", []):
            path = Path(str(raw)).resolve()
            if not path.is_file() or not path_within(path, task_dir / "raw") or sha256_file(path) != run.get("payload_digest"):
                errors.append("Raw source evidence path/hash mismatch")
    # Every declared artifact is checked, including items omitted from the
    # display gallery. Only task-local retained evidence can support provenance.
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("path") and value.get("sha256"):
                path = Path(str(value["path"])).resolve()
                if not path.is_file() or not path_within(path, task_dir) or sha256_file(path) != value["sha256"]:
                    errors.append("Evidence artifact path/hash mismatch")
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(evidence)
    for browser in evidence.get("collections", {}).get("browser", []):
        for role, raw in browser.get("screenshots", {}).items():
            path = Path(str(raw)).resolve()
            if not path.is_file() or not path_within(path, task_dir / "screenshots") or sha256_file(path) != browser.get("screenshot_hashes", {}).get(role):
                errors.append("Browser screenshot hash mismatch: " + role)
    from validate_run import configured_secrets, forbidden_browser_paths
    from common import load_skill_config
    payloads = {"task": task, "evidence": evidence, "assessment": assessment, "plan": plan, "candidates": candidates, "manifest": manifest, "report_data": data, "journal": journal}
    if forbidden_browser_paths(payloads):
        errors.append("Forbidden browser session fields in artifacts")
    combined = json.dumps(payloads, ensure_ascii=False) + html + (task_dir / "report.md").read_text() + (task_dir / "report-findings.csv").read_text(encoding="utf-8-sig")
    if any(secret in combined for secret in configured_secrets(load_skill_config())):
        errors.append("Configured secret in artifacts")
    return sorted(set(errors))
