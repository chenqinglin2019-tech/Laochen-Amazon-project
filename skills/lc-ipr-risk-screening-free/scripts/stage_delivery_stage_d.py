"""09D: independently verifiable preliminary result, separate from full reports."""
from __future__ import annotations

import json
import csv
import io
from copy import deepcopy
from html import escape
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_file, sha256_json
from review_progress_stage_a import ledger as progress_ledger
from stage_risk_stage_b import _registry, _summary, _version

REVISION = "stage-delivery-stage-d-v1"
SCHEMA = "IPR-PRELIMINARY-STAGE/1.0"
SCOPE = ("scenario_id", "jurisdiction", "right_type", "product_version")


def enabled(task: dict) -> bool:
    value = task.get("stage_delivery_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("STAGE_DELIVERY_REVISION_INVALID")
    return True


def _source_hashes(task_dir: Path) -> dict:
    return {name: sha256_file(task_dir / name) if (task_dir / name).is_file() else None
            for name in ("task.json", "evidence.json", "search-plan.json", "normalized-candidates.json",
                         "materiality-annotations.json", "supplemental-evidence.json",
                         "source-capabilities.json", "browser-execution-status.json")}


def _product_errors(task: dict, evidence: dict, task_dir: Path) -> list[str]:
    from product_entry import enabled as entry_enabled, evidence_errors
    errors = []
    if not isinstance(task.get("product"), dict) or not task["product"] or not task.get("task_id"):
        errors.append("PRODUCT_IDENTITY_MISSING")
    if entry_enabled(task):
        errors.extend(evidence_errors(task, evidence, task_dir))
    if evidence.get("task_id") != task.get("task_id"):
        errors.append("TASK_EVIDENCE_IDENTITY_MISMATCH")
    return sorted(set(errors))


def _candidate_ids(task_dir: Path) -> set[str]:
    path = task_dir / "normalized-candidates.json"
    if not path.is_file():
        return set()
    from annotate_materiality import iter_candidates
    return {row.get("candidate_id") for _, row in iter_candidates(load_json(path)) if row.get("candidate_id")}


def _review_receipt_valid(task: dict, evidence: dict, judgment: dict) -> bool:
    if judgment.get("review_status") != "chief_reviewed":
        return False
    from stage_review_stage_c import _batch, _events, _receipt, _reviews
    try:
        rows = _events(evidence)
        batch = _batch(rows, judgment["review_batch_id"])
        origin_batch_id = batch.get("reuse", {}).get(judgment["event_id"], batch["event_id"])
        batch = _batch(rows, origin_batch_id)
        reviews = _reviews(rows, batch["event_id"])
        if len(reviews) != 2:
            return False
        for index, review in enumerate(reviews):
            _receipt({"isolation_receipt": review["isolation_receipt"]}, batch, reviews[:index])
        chief = next(row for row in rows if row["kind"] == "adjudicate" and
                     row.get("batch_id") == batch["event_id"] and row.get("status") == "complete")
        return chief["review_refs"] == [{"event_id": row["event_id"], "sha256": row["review_sha256"]}
                                         for row in reviews] and judgment["event_id"] in chief.get("decisions", {}) and \
               chief["event_id"] == judgment.get("chief_event_id")
    except (ValueError, KeyError, StopIteration, OSError, TypeError):
        return False


def _judgment_problem(task: dict, evidence: dict, judgment: dict, registry: dict,
                      candidate_ids: set[str], task_dir: Path) -> str | None:
    if judgment.get("scope", {}).get("product_version") != _version(task):
        return "PRODUCT_VERSION_CHANGED"
    event = next((row for row in evidence.get("stage_risk_events", []) if
                  row.get("event_id") == judgment.get("event_id") and row.get("kind") == "review"), None)
    if event is None:
        return "JUDGMENT_ORIGIN_MISSING"
    if judgment.get("scope") != event.get("scope"):
        return "JUDGMENT_SCOPE_FORK"
    candidate_id = judgment.get("scope", {}).get("candidate_id")
    if candidate_id and candidate_id not in candidate_ids:
        return "CANDIDATE_IDENTITY_MISSING"
    from delivery_inspection_stage_d import enabled as inspection_enabled, dependency_refs
    if inspection_enabled(task):
        for key in ("evidence_refs", "outcome_refs"):
            if judgment.get(key) != event.get(key):
                return "JUDGMENT_REFERENCE_SET_FORK"
        try:
            closure = dependency_refs(registry, event.get("evidence_refs", []) + event.get("outcome_refs", []))
            if not set(closure) <= set(event.get("ref_fingerprints", {})):
                return "STAGE_DEPENDENCY_BOUNDARY_UNPROVEN"
        except (ValueError, TypeError):
            return "STAGE_DEPENDENCY_BOUNDARY_UNPROVEN"
    from assessment_estimate import _verify_declared_artifacts
    from common import resolve_retained_path
    for ref, digest in event.get("ref_fingerprints", {}).items():
        if ref not in registry or sha256_json(registry[ref]) != digest:
            return "SOURCE_REFERENCE_CHANGED_OR_MISSING"
        row = registry[ref]["row"]
        if _path_without_fingerprint(row):
            return "SOURCE_ARTIFACT_FINGERPRINT_MISSING"
        try:
            _verify_declared_artifacts(row, task_dir, set())
            if registry[ref]["origin"] == "run" and row.get("raw_paths") and row.get("payload_digest"):
                paths = row["raw_paths"]
                if not isinstance(paths, list) or len(paths) != 1:
                    return "SOURCE_ARTIFACT_FINGERPRINT_MISSING"
                resolve_retained_path(task_dir, paths[0], expected_sha256=row["payload_digest"])
        except (ValueError, OSError, TypeError):
            return "SOURCE_ARTIFACT_UNREADABLE_OR_CHANGED"
    return None


def _path_without_fingerprint(value) -> bool:
    if isinstance(value, list):
        return any(_path_without_fingerprint(item) for item in value)
    if not isinstance(value, dict):
        return False
    for name, path in value.items():
        if isinstance(path, str) and (name == "path" or name.endswith("_path")):
            stem = name[:-5] if name.endswith("_path") else ""
            if not any(value.get(key) for key in (stem + "_sha256", stem + "_hash", "sha256")):
                return True
    return any(_path_without_fingerprint(item) for item in value.values())


def _sanitize_risk(task: dict, evidence: dict, risk: dict, task_dir: Path) -> tuple[dict, list[dict], list[dict]]:
    result = deepcopy(risk)
    quarantine = []
    review_issues = []
    changed = False
    registry = _registry(task, evidence, task_dir)
    candidate_ids = _candidate_ids(task_dir)
    for row in result.get("judgments", []):
        origin = next((event for event in evidence.get("stage_risk_events", []) if
                       event.get("event_id") == row.get("event_id")), {})
        row["grade_evidence_version"] = origin.get("version")
        problem = _judgment_problem(task, evidence, row, registry, candidate_ids, task_dir)
        if problem:
            changed = True
            quarantine.append({"event_id": row.get("event_id"), "scope": row.get("scope"), "reason": problem,
                               "previous_grade": row.get("stage_risk")})
            row["applicability"] = "suspended"
            row["suspension_reason"] = problem
            row["review_status"] = "invalid_for_delivery"
            row["display_grade"] = f"上次等级：{row.get('stage_risk')}（已暂停适用）"
        elif row.get("review_status") == "chief_reviewed" and not _review_receipt_valid(task, evidence, row):
            changed = True
            review_issues.append({"event_id": row.get("event_id"), "reason": "REVIEW_ISOLATION_PROOF_UNAVAILABLE"})
            row["review_status"] = "awaiting_valid_independent_review"
            row["stage_risk"] = row.get("single_review_stage_risk", row["stage_risk"])
            row["display_grade"] = "初步" + str(row["stage_risk"]) + "（待双审）"
            row["chief_event_id"] = None
    for row in result.get("signals", []):
        if row.get("review_status") == "chief_reviewed" and not _review_receipt_valid(task, evidence, row):
            review_issues.append({"event_id": row.get("event_id"), "reason": "SIGNAL_REVIEW_PROOF_UNAVAILABLE"})
            row["review_status"] = "awaiting_valid_independent_review"
            row.pop("chief_signal_conclusion", None)
            row["chief_event_id"] = None
    if changed:
        for summary in result.get("by_country", []):
            related = [row for row in result.get("judgments", []) if all(row["scope"].get(k) == summary.get(k)
                       for k in ("scenario_id", "jurisdiction", "product_version"))]
            revised = _summary(related, scope={k: summary[k] for k in
                                ("scenario_id", "jurisdiction", "product_version")})
            summary.update({key: revised[key] for key in ("stage_risk", "display_grade", "applicability",
                "previous_risk", "valid_partial_highest", "drivers", "suspended_judgments")})
            summary.update(review_status="pending", verification_status="pending", confidence=None)
        for summary in result.get("by_scenario", []):
            related = [row for row in result.get("judgments", []) if row["scope"].get("scenario_id") ==
                       summary["scenario_id"]]
            revised = _summary(related, scope={k: summary[k] for k in ("scenario_id", "product_version")})
            summary.update({key: revised[key] for key in ("stage_risk", "display_grade", "applicability",
                "previous_risk", "valid_partial_highest", "drivers", "suspended_judgments")})
            summary.update(review_status="pending", verification_status="pending", confidence=None)
        primary = task.get("primary_scenario_id") or "product_entry"
        current = next((row for row in result.get("by_scenario", []) if row["scenario_id"] == primary), None)
        if current:
            result["overall"].update({key: current.get(key) for key in ("stage_risk", "display_grade",
                "applicability", "previous_risk", "valid_partial_highest", "drivers", "suspended_judgments")})
            result["overall"].update(review_status="pending", verification_status="pending", confidence=None)
    return result, quarantine, review_issues


def _review_cutoffs(evidence: dict, risk: dict, progress: dict) -> list[dict]:
    from stage_review_stage_c import _events as review_events
    events = review_events(evidence)
    batches = {row["event_id"]: row for row in events if row["kind"] == "freeze"}
    current_scopes = {tuple(row.get(key) for key in SCOPE): row for row in progress.get("by_scope", [])}
    cutoffs = []
    for batch in risk.get("stage_review", {}).get("batches", []):
        frozen = batches.get(batch["batch_id"])
        if not frozen:
            continue
        key = tuple(batch["scope"].get(field) for field in SCOPE)
        current = current_scopes.get(key, {})
        old = next((row for row in frozen["coverage"]["scope"] if
                    tuple(row.get(field) for field in SCOPE) == key), {})
        cutoffs.append({"batch_id": batch["batch_id"], "scope": batch["scope"],
            "review_status": batch["status"], "evidence_digest": batch["evidence_digest"],
            "grade_evidence_cutoff": frozen["stage_risk_cutoff"],
            "grade_source_run_cutoff": frozen["evidence_cutoff"],
            "grade_plan_version": frozen["coverage"].get("plan_version"),
            "grade_completed_at_freeze": old.get("completed"),
            "current_completed": current.get("completed"),
            "later_completed_not_in_batch": max(0, current["completed"] - old["completed"])
                if isinstance(current.get("completed"), int) and isinstance(old.get("completed"), int) else None})
    return cutoffs


def build_model(task_dir: Path, *, generated_at: str | None = None, view: dict | None = None) -> dict:
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / "task.json")
    evidence = load_json(task_dir / "evidence.json")
    if not enabled(task):
        raise ValueError("STAGE_DELIVERY_NEW_TASK_MARKER_REQUIRED")
    from workflow_v24 import work_view_from_dir
    progress = progress_ledger(task, evidence)
    view_error = None
    if view is None:
        try:
            view = work_view_from_dir(task_dir)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            view_error = type(exc).__name__ + ":" + str(exc).split(":")[0]
            view = {"entries": [], "review_progress": progress, "stage_risk": {}}
    identity_errors = _product_errors(task, evidence, task_dir)
    if view_error:
        identity_errors.append("WORK_VIEW_INTEGRITY_UNAVAILABLE")
    try:
        risk, quarantine, review_issues = ({}, [], []) if identity_errors else _sanitize_risk(
            task, evidence, view.get("stage_risk", {}), task_dir)
    except (ValueError, OSError, KeyError, TypeError):
        identity_errors.append("STAGE_REFERENCE_INTEGRITY_UNAVAILABLE")
        risk, quarantine, review_issues = {}, [], []
    progress = deepcopy(view.get("review_progress") or progress)
    entries = [{key: deepcopy(row.get(key)) for key in ("work_id", "issue_id", "state", "kind", "reason",
        "question", "completion_condition", "resume_condition", "scenario_id", "jurisdiction",
        "right_type", "candidate_id") if row.get(key) is not None} for row in view.get("entries", [])]
    try:
        cutoffs = _review_cutoffs(evidence, risk, progress) if risk else []
    except (ValueError, KeyError, TypeError):
        identity_errors.append("STAGE_REVIEW_CHAIN_UNAVAILABLE")
        risk, quarantine, review_issues, cutoffs = {}, [], [], []
    judgments = risk.get("judgments", [])
    preliminary = (any(row.get("review_status") != "chief_reviewed" for row in judgments) or
                   any(row.get("review_status") != "chief_reviewed" for row in risk.get("signals", [])) or
                   not judgments)
    reviewed_items = [*judgments, *risk.get("signals", [])]
    awaiting_supplement = (bool(reviewed_items) and
        any(row.get("review_status") == "needs_supplement" for row in reviewed_items) and
        all(row.get("review_status") in {"needs_supplement", "chief_reviewed"} for row in reviewed_items))
    review_label = ("所列批次已执行双审主审／待补证" if awaiting_supplement else
                    "初步判断／待双审" if preliminary else "所列批次已双审主审")
    model = {"schema": SCHEMA, "revision": REVISION, "task_id": task.get("task_id"),
        "generated_at": generated_at or now_iso(), "delivery_type": "preliminary_stage_result",
        "delivery_status": "local_validated_result_only", "business_completion": "not_claimed",
        "product": {"product_id": task.get("product", {}).get("product_id"),
                    "title": task.get("product", {}).get("title"),
                    "binding": deepcopy(task.get("product_identity", {}).get("binding")),
                    "product_version": _version(task), "product_sha256": sha256_json(task.get("product", {}))},
        "identity_errors": sorted(set(identity_errors)), "view_error": view_error,
        "progress": {key: deepcopy(progress.get(key)) for key in ("status", "plan_version", "completed",
            "planned", "percentage", "excluded", "by_scope", "by_scope_module", "items")},
        "progress_cutoff": {"plan_version": progress.get("plan_version"),
            "review_progress_event_count": len(evidence.get("review_progress_events", [])),
            "source_run_count": len(evidence.get("source_runs", []))},
        "grade_cutoff": {"stage_risk_event_count": len(evidence.get("stage_risk_events", [])),
            "stage_review_event_count": len(evidence.get("stage_review_events", [])),
            "batches": cutoffs},
        "stage_risk": risk, "quarantined_judgments": quarantine, "review_issues": review_issues,
        "work": {"status": view.get("status", "integrity_unavailable"), "entries": entries,
                 "unresolved_scopes": deepcopy(view.get("unresolved_scopes", []))},
        "review_label": review_label,
        "limitations": ["产品／输入绑定未通过：仅交接已知状态，不交付风险等级"] if identity_errors else
            ["所列未查范围、待办与补证义务仍在原任务中；阶段结果不等于业务完成或完整报告"] +
            (["双审隔离凭据当前不可核，相关判断仅作初步展示"] if review_issues else []) +
            (["较新已完成工作尚未纳入所列审定批次"] if any(
                (row.get("later_completed_not_in_batch") or 0) > 0 for row in cutoffs) else []),
        "source_hashes": _source_hashes(task_dir)}
    from report_package_stage_c import enabled as package_enabled, stage_carriers, REVISION as package_revision
    if package_enabled(task):
        model['stage_package_stage_c'] = {'revision': package_revision, 'carriers': stage_carriers(task),
            'actual_delivery': 'not_verified'}
    return model


def render_markdown(model: dict) -> str:
    progress = model["progress"]
    def safe(value):
        return str(value) if value is not None else "未知"
    def scope_label(row, *, module=False):
        label = " / ".join(safe(row.get(key)) for key in SCOPE[:3])
        label += " / 产品版本 " + safe(row.get("product_version"))
        if module:
            label += " / " + safe(row.get("module_id"))
        return label
    ratio = f"{safe(progress.get('completed'))}/{safe(progress.get('planned'))}"
    percentage = "不可计算" if progress.get("percentage") is None else f"{progress['percentage']}%"
    lines = ["# 初步阶段结果", "", f"产品：{safe(model['product'].get('title'))}",
        f"任务：{safe(model['task_id'])}", f"审核状态：{model['review_label']}",
        f"工作进度：{ratio}（{percentage}）；计划版本：{safe(progress.get('plan_version'))}",
        f"成果截止：{model['progress_cutoff']['source_run_count']} 条来源运行记录；"
        f"等级依据截止：{model['grade_cutoff']['stage_risk_event_count']} 条阶段判断事件", ""]
    if progress.get("by_scope_module"):
        lines.append("## 专项工作进度")
        for row in progress["by_scope_module"]:
            value = "不可计算" if row.get("percentage") is None else f"{row['percentage']}%"
            lines.append("- " + scope_label(row, module=True) +
                f"：{safe(row.get('completed'))}/{safe(row.get('planned'))}（{value}）")
        lines.append("")
    if model["identity_errors"]:
        lines.extend(["## 身份／输入问题", *["- " + item for item in model["identity_errors"]], ""])
    else:
        overall = model["stage_risk"].get("overall", {})
        lines.extend(["## 当前阶段风险", safe(overall.get("display_grade") or "尚无已审阶段等级"),
            f"核实状态：{safe(overall.get('verification_status'))}；审核状态：{safe(overall.get('review_status'))}", ""])
        for row in model["stage_risk"].get("judgments", []):
            scope = row.get("scope", {})
            lines.append("- " + scope_label(scope) +
                f"：{safe(row.get('display_grade'))}；审核：{safe(row.get('review_status'))}；"
                f"评估日：{safe(row.get('assessment_date'))}；依据：{', '.join(row.get('evidence_refs', []))}；"
                f"{'原单审比较' if row.get('chief_fact_basis') and row.get('review_status') == 'chief_reviewed' else '比较'}：{safe(row.get('comparison'))}；{'原单审缺口' if row.get('chief_fact_basis') and row.get('review_status') == 'chief_reviewed' else '缺口'}：{safe(row.get('gaps'))}")
            if row.get('chief_fact_basis') and row.get('review_status') == 'chief_reviewed':
                lines.append("  主审事实：" + safe(row['chief_fact_basis']) +
                             "；主审理由：" + safe(row.get('chief_reasoning')))
        lines.append("")
        if model["stage_risk"].get("scopes_without_any_judgment"):
            lines.append("## 尚无阶段判断的范围")
            for row in model["stage_risk"]["scopes_without_any_judgment"]:
                lines.append("- " + scope_label(row, module=True) +
                             f"：{safe(row.get('investigation_status'))}")
            lines.append("")
        if model["stage_risk"].get("signals"):
            lines.append("## 未来申请与维权信号（不计入当前等级）")
            for row in model["stage_risk"]["signals"]:
                lines.append("- " + safe(row.get("signal_type")) + "：" +
                    safe(row.get("chief_signal_conclusion") or row.get("signal_reasoning")) +
                    "；审核：" + safe(row.get("review_status")))
            lines.append("")
    if model["quarantined_judgments"]:
        lines.extend(["## 已隔离判断", *["- " + safe(row["event_id"]) + "：" + row["reason"]
                       for row in model["quarantined_judgments"]], ""])
    if model["review_issues"]:
        lines.extend(["## 待修复审阅依据", *["- " + safe(row["event_id"]) + "：" + row["reason"]
                       for row in model["review_issues"]], ""])
    if model["grade_cutoff"]["batches"]:
        lines.append("## 审阅批次与未纳入成果")
        for row in model["grade_cutoff"]["batches"]:
            lines.append(f"- {row['batch_id']}：{row['review_status']}；冻结时完成 {safe(row['grade_completed_at_freeze'])}，"
                         f"当前 {safe(row['current_completed'])}，较新未纳入 {safe(row['later_completed_not_in_batch'])}")
        lines.append("")
    lines.extend(["## 未完成工作与限制"])
    for row in model["work"]["entries"]:
        lines.append("- " + safe(row.get("work_id")) + "：" + safe(row.get("state")) + "；" +
                     safe(row.get("reason")) + ("；恢复：" + safe(row.get("resume_condition"))
                                                if row.get("resume_condition") else ""))
    for row in model["limitations"]:
        lines.append("- " + row)
    lines.extend(["", "本结果不是完整报告，也不表示业务完成或实际交付成功。", ""])
    return "\n".join(lines)


def render_html(model: dict) -> str:
    body = escape(render_markdown(model))
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
        '<title>初步阶段结果</title><style>body{font-family:system-ui,sans-serif;max-width:72rem;margin:2rem auto;'
        'padding:0 1rem;line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head>'
        '<body><main><pre>' + body + '</pre></main></body></html>')


def _payloads(model: dict) -> dict[str, bytes]:
    from report_package_stage_c import choices, STAGE_CARRIERS
    package = model.get('stage_package_stage_c')
    carriers = choices(package.get('carriers'), STAGE_CARRIERS, 'STAGE_CARRIERS_INVALID') if package else ['html', 'markdown']
    payloads = {'stage-result.json': (json.dumps(model, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()}
    if 'reply' in carriers:
        payloads['stage-result.txt'] = render_markdown(model).encode()
    if 'html' in carriers:
        payloads['stage-result.html'] = render_html(model).encode()
    if 'markdown' in carriers:
        payloads['stage-result.md'] = render_markdown(model).encode()
    if 'csv' in carriers:
        stream = io.StringIO(newline='')
        fields = ('type', 'task_id', 'product_version', 'model_sha256', 'record')
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        rows = [('summary', {key: model[key] for key in ('progress', 'review_label', 'limitations', 'identity_errors')})]
        rows += [('judgment', row) for row in model.get('stage_risk', {}).get('judgments', [])]
        rows += [('signal', row) for row in model.get('stage_risk', {}).get('signals', [])]
        rows += [('work', row) for row in model['work']['entries']]
        for kind, row in rows:
            values = {'type': kind, 'task_id': model['task_id'], 'product_version': model['product']['product_version'],
                'model_sha256': sha256_json(model), 'record': json.dumps(row, ensure_ascii=False, sort_keys=True)}
            writer.writerow({key: "'" + str(value) if str(value).lstrip().startswith(('=', '+', '-', '@')) else value
                for key, value in values.items()})
        payloads['stage-result.csv'] = stream.getvalue().encode('utf-8-sig')
    return payloads


def validate_output(task_dir: Path, output_dir: Path) -> list[str]:
    source, out = Path(task_dir).resolve(), Path(output_dir).resolve()
    try:
        saved = load_json(out / "stage-result.json")
        expected = build_model(source, generated_at=saved["generated_at"])
        if sha256_json(saved) != sha256_json(expected):
            return ["STAGE_RESULT_SOURCE_OR_MODEL_CHANGED"]
        payloads = _payloads(expected)
        manifest = load_json(out / "stage-manifest.json")
        if manifest.get("task_id") != expected["task_id"] or manifest.get("model_sha256") != sha256_json(expected):
            return ["STAGE_MANIFEST_MODEL_MISMATCH"]
        if set(manifest.get('artifacts', {})) != set(payloads):
            return ['STAGE_ARTIFACT_SET_MISMATCH']
        for name in ('stage-result.txt', 'stage-result.html', 'stage-result.md', 'stage-result.csv'):
            if name not in payloads and (out / name).exists():
                return ['STAGE_UNDECLARED_CARRIER:' + name]
        for name, payload in payloads.items():
            if not (out / name).is_file() or (out / name).read_bytes() != payload or \
                    manifest.get("artifacts", {}).get(name) != {"bytes": len(payload), "sha256": sha256_file(out / name)}:
                return ["STAGE_ARTIFACT_MISMATCH:" + name]
        receipt_path = out / "stage-validation.json"
        if receipt_path.is_file():
            receipt = load_json(receipt_path)
            if receipt.get("status") != "locally_validated" or receipt.get("task_id") != expected["task_id"] or \
                    receipt.get("manifest_sha256") != sha256_file(out / "stage-manifest.json") or \
                    receipt.get("business_completion") != "not_claimed" or receipt.get("actual_delivery") != "not_claimed":
                return ["STAGE_VALIDATION_RECEIPT_MISMATCH"]
        return []
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return ["STAGE_VALIDATION_ERROR:" + type(exc).__name__]


def _create_local_output(task_dir: Path, output_dir: Path) -> dict:
    source, out = Path(task_dir).resolve(), Path(output_dir).resolve()
    if out == source or out.exists():
        raise ValueError("STAGE_NEW_OUTPUT_DIRECTORY_REQUIRED")
    model = build_model(source)
    payloads = _payloads(model)
    out.mkdir(parents=True)
    for name, payload in payloads.items():
        (out / name).write_bytes(payload)
    manifest = {"schema": "IPR-PRELIMINARY-STAGE-MANIFEST/1.0", "task_id": model["task_id"],
        "model_sha256": sha256_json(model), "source_hashes": model["source_hashes"],
        "artifacts": {name: {"bytes": len(payload), "sha256": sha256_file(out / name)}
                      for name, payload in payloads.items()}}
    atomic_write_json(out / "stage-manifest.json", manifest)
    errors = validate_output(source, out)
    if errors:
        raise ValueError("STAGE_RESULT_VALIDATION_FAILED:" + ",".join(errors))
    atomic_write_json(out / "stage-validation.json", {"schema": "IPR-PRELIMINARY-STAGE-VALIDATION/1.0",
        "validated_at": now_iso(), "task_id": model["task_id"], "manifest_sha256": sha256_file(out / "stage-manifest.json"),
        "status": "locally_validated", "business_completion": "not_claimed", "actual_delivery": "not_claimed"})
    from delivery_inspection_stage_d import enabled as inspection_enabled, inspect as independent_inspect
    if inspection_enabled(load_json(source / "task.json")):
        inspection = independent_inspect(source, out, kind="stage")
        atomic_write_json(out / "delivery-inspection.json", inspection)
        if inspection["errors"]:
            raise ValueError("STAGE_INDEPENDENT_INSPECTION_FAILED:" + ";".join(inspection["errors"]))
    result_file = next(name for name in ('stage-result.html', 'stage-result.txt', 'stage-result.md', 'stage-result.csv') if name in payloads)
    return {"status": "locally_validated", "result": str(out / result_file),
            **({'reply': render_markdown(model)} if 'stage-result.txt' in payloads else {}),
            "manifest": str(out / "stage-manifest.json")}


def create_output(task_dir: Path, output_dir: Path, *, correction_id=None) -> dict:
    from delivery_versions_stage_e import enabled, begin_build, finish_build, fail_build
    source = Path(task_dir).resolve()
    if not enabled(load_json(source / "task.json")):
        return _create_local_output(task_dir, output_dir)
    version_id = begin_build(source, output_dir, kind="stage", correction_id=correction_id)
    try:
        result = _create_local_output(task_dir, output_dir)
        return {**result, **finish_build(source, version_id), "build_only": True}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        fail_build(source, version_id, exc)
        raise
