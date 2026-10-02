"""10A versioned presentation of the already validated 09 stage snapshot."""
from __future__ import annotations

import html
import csv
import hashlib
import io
from copy import deepcopy
from pathlib import Path

from common import sha256_json

REVISION = "report-presentation-stage-a-v1"
SAMPLE_SHA256 = "c48b415e79845913355f6658fb2c2b9580fa1915a9d8de326a837b2d861c6177"
SAMPLE_STYLE_SHA256 = "ed6460f1f4c53dbf1b53f2bc7758886d5123124ba967b7d42ad0246ac4485120"
SAMPLE_STYLE_BYTES = 6116
SCOPE = ("scenario_id", "jurisdiction", "right_type", "product_version")


def enabled(task: dict) -> bool:
    value = task.get("report_presentation_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("REPORT_PRESENTATION_REVISION_INVALID")
    return True


def build(task_dir: Path, task: dict, assessment: dict, candidates: dict) -> dict:
    stylesheet = Path(__file__).resolve().parent.parent / "assets/evidence-estimate-template.css"
    if hashlib.sha256(stylesheet.read_bytes()[:SAMPLE_STYLE_BYTES]).hexdigest() != SAMPLE_STYLE_SHA256:
        raise ValueError("REPORT_PRESENTATION_SAMPLE_STYLE_CHANGED")
    from stage_delivery_stage_d import build_model
    from final_review import enabled as final_enabled, project_stage
    options = {}
    if final_enabled(task) and (Path(task_dir) / 'search-plan.json').is_file():
        from workflow_v24 import work_view_from_dir
        reviews = assessment.get('review', {}).get('input_reviews', {})
        options['view'] = work_view_from_dir(task_dir,
            first_review=reviews.get('first'), second_review=reviews.get('second'))
    stage = build_model(task_dir, generated_at=assessment.get("generated_at") or "未记录", **options)
    if final_enabled(task):
        stage = project_stage(stage, assessment)
    if stage["identity_errors"]:
        raise ValueError("REPORT_PRESENTATION_IDENTITY_INVALID:" + ",".join(stage["identity_errors"]))
    inventory = []
    for provider, group in sorted(candidates.items()):
        if not isinstance(group, list):
            continue
        for row in group:
            if isinstance(row, dict):
                inventory.append({key: deepcopy(row.get(key)) for key in ("candidate_id", "title", "jurisdiction",
                    "right_type", "scope_status", "triage_status", "identity_status", "owner", "rights_holder",
                    "scope_reasoning", "triage_reasoning", "evidence_refs", "family_members", "publication_numbers",
                    "publication_relations", "search_similarity") if row.get(key) is not None}
                    | {"provider": provider})
    # Reuse the already verified 05 projection in this assessment. Candidate
    # metadata cannot replace a current, version-bound triage decision.
    triage = assessment.get("coverage", {}).get("triage", {})
    projected = []
    for item in inventory:
        records = [r for r in triage.get("records", []) if r.get("candidate_id") == item.get("candidate_id")]
        dispositions = [r for r in triage.get("scope_dispositions", []) if r.get("candidate_id") == item.get("candidate_id")]
        for record in records:
            annotation = record.get("annotation") or {}
            projected.append({**item, **{k: record.get(k) for k in ("scenario_id", "jurisdiction", "right_type")},
                "scope_status": "included", "triage_status": record.get("decision") if record.get("current") else
                    "pending_recheck" if annotation or record.get("reopen_reasons") else "unreviewed",
                "triage_reasoning": annotation.get("reason"), "missing_information": annotation.get("missing_information"),
                "reopen_reasons": deepcopy(record.get("reopen_reasons", [])),
                "next_actions": deepcopy(record.get("next_actions", [])),
                "evidence_refs": deepcopy(annotation.get("evidence_refs", item.get("evidence_refs", [])))})
        for record in dispositions:
            projected.append({**item, **deepcopy(record), "scope_reasoning": record.get("reason"),
                "triage_status": "scope_not_assessed"})
        if not records and not dispositions:
            projected.append(item)
    inventory = projected
    result = {"revision": REVISION, "sample_sha256": SAMPLE_SHA256,
        "sample_style_sha256": SAMPLE_STYLE_SHA256,
        "snapshot_sha256": sha256_json({"stage": stage, "assessment": assessment}),
        "stage": stage, "candidate_inventory": inventory}
    from business_status_stage_b import enabled as business_enabled, build as business_build
    if business_enabled(task):
        result["business_status"] = business_build(task_dir, task, stage, assessment)
    return result


def _text(value) -> str:
    if isinstance(value, list):
        return "；".join(_text(item) for item in value) or "未另列"
    if isinstance(value, dict):
        return "；".join(str(key) + "：" + _text(value[key]) for key in sorted(value)) or "未另列"
    return "未知" if value is None or value == "" else str(value)


def _scope(row: dict) -> str:
    return " / ".join(_text(row.get(key)) for key in SCOPE[:3])


def _metric(label: str, value, detail="") -> str:
    e = html.escape
    return '<div class="metric"><span>' + e(label) + '</span><b>' + e(_text(value)) + '</b><small>' + e(_text(detail)) + '</small></div>'


def _candidate_status(value) -> str:
    return {"included": "已纳入", "out_of_scope": "未纳入", "not_included": "未纳入",
            "selected": "入选", "not_selected": "不入选", "needs_info": "待补信息",
            "unreviewed": "未审阅", "pending_recheck": "待复核", "scope_not_assessed": "范围未纳入处置",
            "pending": "待处理", "recheck": "待复核"}.get(value, _text(value))


def _review_status(value) -> str:
    return {"needs_supplement": "已执行双审主审／待补证",
            "final_reviewed": "最终双审已完成", "final_review_pending": "待最终双审",
            "chief_reviewed": "已双审主审", "complete": "已双审主审",
            "single_review_pending_09C": "待双审", "awaiting_reviews": "待双审",
            "awaiting_second_review": "待第二审", "awaiting_chief": "待主审",
            "awaiting_valid_independent_review": "待修复独立双审",
            "invalid_for_delivery": "本次不可用"}.get(value, _text(value))


def _verification_status(value) -> str:
    return {"pending": "核实待评", "verified": "已核实",
            "not_applicable": "不适用"}.get(value, _text(value))


def _business_status(value) -> str:
    return {"business_complete": "整项业务已完成", "limited_round_closed": "本轮受限结束，整项未完成",
        "continue": "继续处理", "awaiting_dependency": "等待资料／访问条件",
        "user_paused": "用户主动暂停", "review_pending": "必要审阅待完成",
        "integrity_unavailable": "当前绑定待核对"}.get(value, _text(value))


def project(data: dict) -> dict:
    """Replace legacy rating fields in the current rendition with the 09 snapshot."""
    stage = data["presentation_stage_a"]["stage"]
    risk = stage["stage_risk"]
    overall = risk.get("overall", {})
    data["overall"] = {
        "risk": overall.get("stage_risk") if overall.get("applicability") == "current" else None,
        "display_grade": overall.get("display_grade") or "尚无已审阶段等级",
        "confidence": overall.get("confidence") if overall.get("verification_status") == "verified" or stage.get("final_review") else None,
        "verification_status": overall.get("verification_status") or "pending",
        "review_status": overall.get("review_status") or "pending",
        "applicability": overall.get("applicability"),
        "drivers": overall.get("drivers") or [],
    }
    # The earlier assessment remains an input digest, not a second published grade.
    data["assessments"] = []
    data["supplemental_rows"] = []
    data["scenario_summaries"] = []
    data["decision_records"] = {}
    data["lead"] = ""
    data["summary"] = ""
    data["overall_confidence_basis"] = ""
    data["sections"] = data["presentation_stage_a"].get("visual_sections", [])
    from report_estimate import _section_figures
    figures = _section_figures(data["sections"])
    current_images = ([data["product"]["main_visual"]] if data["product"].get("main_visual") else []) + figures
    data["visual_evidence"] = list({(row.get("path"), row.get("sha256")): row for row in current_images}.values())
    data["visual_gaps"] = data["presentation_stage_a"].get("visual_gaps", [])
    data["modules"] = []
    return data


def render_markdown(data: dict) -> str:
    stage = data["presentation_stage_a"]["stage"]
    risk = stage["stage_risk"]
    progress = stage["progress"]
    overall = data["overall"]
    lines = ["# 知识产权风险筛查报告", "## 产品快照", _text(data["product"].get("title")),
        "产品版本：" + _text(stage["product"].get("product_version")),
        "## 筛查结论", ("当前风险：" if stage.get('final_review') else "当前阶段风险：") + _text(overall["display_grade"]),
        "核实状态：" + _verification_status(overall["verification_status"]),
        "审阅状态：" + _text(stage["review_label"]),
        "置信度：" + _text(overall["confidence"] if overall["confidence"] else "尚未形成"),
        "## 覆盖情况", "唯一工作项：" + _text(progress.get("completed")) + "/" +
        _text(progress.get("planned")), "计划版本：" + _text(progress.get("plan_version")),
        "## 限制与待办"]
    if data["product"].get("brand_name_query"):
        lines.extend(["参考品牌名称查询：" + data["product"]["brand_name_query"]["display"],
                      data["product"]["brand_name_query"]["limitation"]])
    business = data["presentation_stage_a"].get("business_status")
    if business:
        lines[4:4] = ["业务状态：" + _business_status(business["business_status"]),
            "交付状态：尚未核对实际可访问入口"]
    product = data["product"]
    if product.get("scope_sha256"):
        from product_scope import LABELS
        role = {"reference_product": "竞品参考", "actual_product": "实际产品"}.get(
            product.get("input_role"), _text(product.get("input_role")))
        source = {"default": "系统默认", "user": "用户明确指定"}.get(
            product.get("input_role_source"), _text(product.get("input_role_source")))
        details = ["角色及来源：" + role + " / " + source, _text(product.get("scope_assumption"))]
        for status, label in LABELS.items():
            members = [row for row in product.get("scope_objects", []) if row.get("scope_status") == status]
            details.append(label + "：" + ("；".join(_text(row.get("description")) for row in members)
                if members else "无已登记对象"))
        if product.get("scope_waiting"):
            details.append("局部限制：" + "；".join(_text(row.get("question") or row.get("reason"))
                for row in product["scope_waiting"]))
        for fact in product.get("scope_facts", []):
            nature = {"page_claim": "仅确认存在该声明"}.get(fact.get("nature"), _text(fact.get("nature")))
            details.append("产品事实：" + _text(fact.get("fact_id")) + "；" + nature + "；" + _text(fact.get("value")))
        for obj in product.get("scope_objects", []):
            visual = obj.get("visual_evidence") or {}
            if visual.get("main_visibility") not in (None, "sufficient"):
                details.append("主图呈现限制：" + _text(obj.get("object_id")) + "；" +
                    _text(visual.get("limitation_reason")))
        lines[4:4] = details
    lines.extend("- " + _text(row.get("work_id")) + "：" + _text(row.get("question") or row.get("reason"))
        for row in stage["work"]["entries"])
    if business:
        for row in business.get("limitations", []):
            lines.append("- 限制核对 " + _text(row.get("work_id")) + "：原回执 " +
                _text(row.get("source_run_refs")) + "；材料 " + _text(row.get("material_processing")) +
                "；判断影响 " + _text(row.get("judgment_impact")) + "；恢复 " +
                _text(row.get("recovery_condition")) + "；缺口 " + _text(row.get("gaps")))
    for row in data.get('report_package_stage_c', {}).get('business_material_gaps', []):
        lines.append('- 材料业务缺口 ' + _text(row.get('evidence_id')) + '：' + _text(row.get('reason')))
    lines.append("## 七项模块")
    for row in risk.get("judgments", []):
        lines.append("- " + _scope(row.get("scope", {})) + "：" + _text(row.get("display_grade")) +
            "；核实 " + _verification_status(row.get("verification_status")) +
            "；审阅 " + _review_status(row.get("review_status")) +
            "；依据 " + "、".join(row.get("evidence_refs", [])))
    lines.extend(["## 视觉证据", "详见离线 HTML 与 report-data.json 的当前阶段图证绑定。",
        "## 候选追溯与逐项推论"])
    for row in data["presentation_stage_a"]["candidate_inventory"]:
        lines.append("- " + _text(row.get("candidate_id")) + "：" + _text(row.get("title")) +
            "；" + _candidate_status(row.get("scope_status") or "pending") + "；" +
            _candidate_status(row.get("triage_status") or "unreviewed") + "；情景 " + _text(row.get("scenario_id")) +
            "；理由／缺口 " + _text([row.get("scope_reasoning"), row.get("triage_reasoning"),
                row.get("missing_information"), row.get("reopen_reasons"), row.get("next_actions")]) +
            ("；同族／文献成员 " + _text(row.get("family_members") or row.get("publication_numbers"))
                if row.get("family_members") or row.get("publication_numbers") else ""))
    lines.extend(["## 数据绑定", "来源截止：" + _text(stage["progress_cutoff"].get("source_run_count")),
        "评级截止：" + _text(stage["grade_cutoff"].get("stage_risk_event_count")),
        "审阅截止：" + _text(stage["grade_cutoff"].get("stage_review_event_count")), data["footer"]])
    if data.get("verification_basis", {}).get("acceptance_policy") == "api-first-v3":
        from report_estimate import _source_notes
        lines.extend(["### 来源与事实采信", data["verification_basis"]["note"], *_source_notes(data)])
        for row in data["verification_basis"]["assessments"]:
            lines.append(_scope(row) + "；缺失或未采信字段：" + _text(row["unverified_facts"]))
    return "\n\n".join(lines) + "\n"


def render_csv(data: dict) -> str:
    stage = data["presentation_stage_a"]["stage"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["row_type", "candidate_id", "jurisdiction", "right_type",
        "display_grade", "stage_risk", "verification_status", "review_status", "business_status",
        "delivery_status", "evidence_refs", "scenario_id", "scope_status", "triage_status", "reasoning"])
    writer.writeheader()
    writer.writerow({"row_type": "overall", "display_grade": data["overall"]["display_grade"],
        "stage_risk": data["overall"]["risk"], "verification_status": data["overall"]["verification_status"],
        "review_status": stage["review_label"],
        "business_status": data["presentation_stage_a"].get("business_status", {}).get("business_status"),
        "delivery_status": data["presentation_stage_a"].get("business_status", {}).get("delivery_status")})
    for row in stage["stage_risk"].get("judgments", []):
        scope = row.get("scope", {})
        writer.writerow({"row_type": "judgment", **{key: scope.get(key) for key in
            ("candidate_id", "jurisdiction", "right_type")}, "display_grade": row.get("display_grade"),
            "stage_risk": row.get("stage_risk"), "verification_status": row.get("verification_status"),
            "review_status": row.get("review_status"), "evidence_refs": ";".join(row.get("evidence_refs", []))})
    for row in data["presentation_stage_a"]["candidate_inventory"]:
        values = {key: row.get(key) for key in ("candidate_id", "jurisdiction", "right_type", "scenario_id")}
        values.update(row_type="candidate", scope_status=_candidate_status(row.get("scope_status") or "pending"),
            triage_status=_candidate_status(row.get("triage_status") or "unreviewed"),
            reasoning=_text([row.get("scope_reasoning"), row.get("triage_reasoning"), row.get("reopen_reasons"),
                row.get("missing_information"), row.get("family_members")]),
            evidence_refs=";".join(row.get("evidence_refs", [])))
        writer.writerow({key: "'" + str(value) if str(value).lstrip().startswith(('=', '+', '-', '@')) else value
            for key, value in values.items()})
    return stream.getvalue()


def render(data: dict, output_dir: Path, product_body: str) -> str:
    """Keep the historical eight-section shell; all status text comes from 09."""
    import report_estimate as old
    e = html.escape
    presentation = data["presentation_stage_a"]
    stage = presentation["stage"]
    progress = stage["progress"]
    risk = stage["stage_risk"]
    overall = risk.get("overall", {})
    grade = overall.get("display_grade") or "尚无已审阶段等级"
    paused = overall.get("applicability") == "suspended"
    risk_class = old.RISK_CLASS.get(overall.get("stage_risk"), "not_assessable") if not paused else "not_assessable"
    ratio = _text(progress.get("completed")) + "/" + _text(progress.get("planned"))
    percent = "不可计算" if progress.get("percentage") is None else str(progress["percentage"]) + "%"
    pending = (progress.get("planned") - progress.get("completed") if
        isinstance(progress.get("planned"), int) and isinstance(progress.get("completed"), int) else None)
    review = stage["review_label"]
    verification = _verification_status(overall.get("verification_status") or "pending")
    confidence = overall.get("confidence") if overall.get("verification_status") == "verified" or stage.get('final_review') else None
    driver_ids = overall.get("drivers") or []
    drivers = [row for row in risk.get("judgments", []) if row.get("event_id") in driver_ids]
    driver_label = "、".join(_text(row.get("scope", {}).get("candidate_id") or
        row.get("scope", {}).get("right_type")) for row in drivers[:3]) or "见专项依据"
    reason = "；".join(_text(row.get("comparison") or row.get("reasoning")) for row in drivers[:3]) or "见各项已审依据"
    unknowns = [row.get("question") or row.get("reason") for row in stage["work"]["entries"]]
    next_step = next((row.get("resume_condition") or row.get("completion_condition") or row.get("question")
        for row in stage["work"]["entries"] if row), None)
    decision = ('<div class="decision-head"><div><h2>筛查结论</h2><p class="meta">' +
        ('最终双审结论与具体证据限制' if stage.get('final_review') else '阶段风险、核实和审阅分别记录') + '</p></div>'
        '<div class="risk-seal risk-seal-' + risk_class + '"><small>' +
        ('当前风险' if stage.get('final_review') else '当前阶段风险') + '</small><b>' + e(grade) +
        '</b><small>' + e(review) + '</small></div></div><div class="grid">' +
        _metric("核实状态", verification, "置信度：" + (_text(confidence) if confidence else "尚未形成")) +
        _metric("审阅状态", review, "按最终双审凭据" if stage.get('final_review') else "按当前批次凭据") +
        _metric("工作进度", ratio + "（" + percent + "）", "计划版本 " + _text(progress.get("plan_version"))) +
        _metric("驱动总评", driver_label, "专项／候选") + '</div><div class="decision"><strong>选级依据</strong>' +
        e(reason) + '<p>可能改变判断的未知：' + e("；".join(_text(x) for x in unknowns[:8]) or "未另列") +
        '</p><p>下一步：' + e(_text(next_step)) + '</p></div>')
    business = presentation.get("business_status")
    if business:
        decision += ('<div class="review-note"><strong>业务状态：' + e(_business_status(business["business_status"])) +
            '</strong><p>交付状态：尚未核对实际可访问入口。本地文件生成或校验不代表已送达。</p></div>')
    scopes = progress.get("by_scope_module") or []
    coverage = ('<h2>查询与候选覆盖</h2><div class="grid">' +
        _metric("当前计划总项 N", progress.get("planned"), "唯一工作项") +
        _metric("已完成 C", progress.get("completed"), "已验收项") +
        _metric("未完成 N−C", pending, "不含有据免做／移除") +
        _metric("去重候选", len({r.get("candidate_id") for r in presentation["candidate_inventory"] if r.get("candidate_id")})
            if presentation["candidate_inventory"] else None, "未知时不补零") + '</div>' +
        '<p class="meta">主进度：' + e(ratio) + '（' + e(percent) + '）；计划版本 ' +
        e(_text(progress.get("plan_version"))) + '；免做 ' + e(_text((progress.get("excluded") or {}).get("exempt"))) +
        '。查询次数与覆盖充分性另见原记录，不由本进度推断。</p>' +
        '<div class="progress" role="progressbar" aria-label="唯一工作项进度" aria-valuemin="0" aria-valuemax="100"' +
        (' aria-valuenow="' + e(str(progress["percentage"])) + '"' if progress.get("percentage") is not None else '') +
        '><i style="width:' + e(str(max(0, min(100, progress.get("percentage") or 0)))) + '%"></i></div>')
    if scopes:
        coverage += '<h3>各专项进度</h3><ul>' + ''.join('<li>' + e(_scope(row)) + ' / ' +
            e(_text(row.get("module_id"))) + '：' + e(_text(row.get("completed"))) + '/' +
            e(_text(row.get("planned"))) + '（' + e(_text(row.get("percentage"))) + '%）</li>' for row in scopes) + '</ul>'
    coverage += ('<p class="meta">当前来源截止 ' + e(_text(stage["progress_cutoff"].get("source_run_count"))) +
        '；评级判断截止 ' + e(_text(stage["grade_cutoff"].get("stage_risk_event_count"))) + '。</p>')
    gaps = '<h2>限制与待办</h2>'
    for row in stage["work"]["entries"]:
        state = row.get("state")
        category = ("完整／受限交付待完成" if state in ("ready", "awaiting_review", "submission_unknown") else
                    "等待资料／访问" if state in ("awaiting_user", "awaiting_access") else "真实外部限制" if
                    state == "blocked" else "待确认")
        gaps += ('<div class="gap"><strong>' + e(category) + ' · ' + e(_text(row.get("work_id"))) +
            '</strong><p>' + e(_text(row.get("question") or row.get("reason"))) + '</p><p>影响：' +
            e(" / ".join(_text(row.get(k)) for k in ("scenario_id", "jurisdiction", "right_type") if row.get(k))) +
            '；下一步／恢复：' + e(_text(row.get("completion_condition") or row.get("resume_condition"))) + '</p>')
        limitation = next((item for item in (business or {}).get("limitations", []) if
            item.get("work_id") == row.get("work_id")), None)
        if limitation:
            gaps += ('<p>限制核对：来源回执 ' + e(_text(limitation.get("source_run_refs"))) +
                '；材料处理 ' + e(_text(limitation.get("material_processing"))) +
                '；替代路线 ' + e(_text(limitation.get("alternative_route"))) +
                '；判断影响 ' + e(_text(limitation.get("judgment_impact"))) +
                ('；最终双审摘要 ' + e(_text(limitation.get("final_review_digest"))) if stage.get('final_review') else
                 '；09C 审阅批次 ' + e(_text(limitation.get("review_batch_id")))) +
                '；待核对 ' + e(_text(limitation.get("gaps"))) + '</p>')
        gaps += '</div>'
    if not stage["work"]["entries"]:
        gaps += '<p class="empty">当前无已登记待办；是否业务完成仍按必要义务另行判定。</p>'
    for row in data.get('report_package_stage_c', {}).get('business_material_gaps', []):
        gaps += '<p>材料业务缺口 · ' + e(_text(row.get('evidence_id'))) + '：' + e(_text(row.get('reason'))) + '</p>'
    modules = '<h2>七项知识产权模块</h2><div class="module-grid">'
    for module_id, label in old.MODULE_LABELS.items():
        rows = [row for row in risk.get("judgments", []) if old.RIGHT_MODULES.get(row.get("scope", {}).get("right_type")) == module_id]
        signals = [row for row in risk.get("signals", []) if
            {"future_application": "pending_application", "enforcement": "enforcement"}.get(row.get("signal_type")) == module_id]
        valid = [row for row in rows if row.get("applicability") == "current" and row.get("stage_risk") in old.RISKS]
        grade_value = max((row["stage_risk"] for row in valid), key=old.RISKS.index, default=None)
        scoped = [row for row in scopes if row.get("module_id") == module_id]
        modules += ('<article class="module"><div class="module-head"><h3>' + e(label) + '</h3>' +
            (old._pill(grade_value) if grade_value else '<span class="badge">' +
            ("补充信号" if signals else "未开展／待确认") + '</span>') + '</div>')
        for row in rows:
            modules += ('<p>' + e(_scope(row.get("scope", {}))) + '：' + e(_text(row.get("display_grade") or
                row.get("stage_risk"))) + '；核实：' +
                e(_verification_status(row.get("verification_status"))) + '；审阅：' +
                e(_review_status(row.get("review_status"))) + '</p>')
        for row in signals:
            modules += ('<p>补充信号 · ' + e(_scope(row.get("scope", {}))) + '：' +
                e(_text(row.get("signal_reasoning"))) + '；层级：' + e(_text(row.get("event_layer"))) +
                '；适用性：' + e("当前" if row.get("applicability") == "current" else "已暂停") +
                '；复核条件：' + e(_text(row.get("review_condition"))) + '</p>')
        if module_id == "figurative_trade_dress":
            for right, label in (("trademark_figurative", "图形商标"), ("trade_dress", "商业外观")):
                if not any(row.get("scope", {}).get("right_type") == right for row in rows):
                    modules += '<p>' + label + '：尚未形成当前判断；待补和范围仍按原计划。</p>'
        for row in scoped:
            modules += ('<p class="meta">本专项 ' + e(_text(row.get("completed"))) + '/' +
                e(_text(row.get("planned"))) + '（' + e(_text(row.get("percentage"))) + '%）</p>')
        if not rows and not signals:
            modules += '<p class="empty">未形成当前阶段判断；实际范围见工作计划。</p>'
        modules += '<p><a href="#candidates">查看逐项依据与缺口</a></p></article>'
    modules += '</div>'
    visual = '<h2>重点视觉证据</h2>'
    figures = old._section_figures(presentation.get("visual_sections", data.get("sections", [])))
    visual_rows = [row for row in risk.get("judgments", []) if row.get("applicability") == "current"
                   and row.get("stage_risk") in ("中", "高", "极高")]
    for row in visual_rows:
        scope = row.get("scope", {})
        matching = [item for item in figures if all(item.get(k, "") == scope.get(k, "") for k in
                    ("candidate_id", "scenario_id", "jurisdiction", "right_type"))]
        matching_candidate = next((item for item in presentation["candidate_inventory"] if
            item.get("candidate_id") == scope.get("candidate_id") and
            item.get("jurisdiction") == scope.get("jurisdiction") and item.get("right_type") == scope.get("right_type")), {})
        similarity = matching_candidate.get("search_similarity")
        similarity_text = '；检索相似度：' + e(_text(similarity)) + '（来源检索指标，不代表侵权概率）' if similarity is not None else ''
        product_image = data["product"].get("main_visual")
        visual += ('<div class="review-group"><h3>' + e(_text(scope.get("candidate_id"))) + ' · ' +
            e(_scope(scope)) + ' · 产品版本 ' + e(_text(scope.get("product_version"))) + ' · ' +
            e(_text(row.get("display_grade"))) + '</h3><p>核实：' + e(_verification_status(row.get("verification_status"))) +
            '；审阅：' + e(_review_status(row.get("review_status"))) + '；评估日：' +
            e(_text(row.get("assessment_date"))) + '</p><div class="visual-grid cols-2">')
        visual += old._figure(product_image, output_dir) if product_image else '<div class="gap">缺产品图；须核对原材料待办和比较影响。</div>'
        visual += ''.join(old._figure(item, output_dir) for item in matching) if matching else '<div class="gap">缺对应权利图或必要视角；比较影响及补证见下。</div>'
        visual += ('</div><p>产品联系：' + e(_text(row.get("product_link"))) + '；比较：' +
            e(_text(row.get("comparison"))) + '；未知：' +
            e(_text(row.get("gaps"))) + similarity_text + '；依据：' + e("、".join(row.get("evidence_refs", []))) + '</p></div>')
    if not visual_rows:
        visual += '<p class="empty">当前无符合重点展示条件的有效阶段判断；待复核、信号与缺图仍见专项和候选追溯。</p>'
    if presentation.get("visual_gaps"):
        visual += '<h3>图证缺口</h3>' + old._list_html([_text(row.get("reason")) + '；' +
            _text(row.get("details")) for row in presentation["visual_gaps"]])
    candidate_rows = []
    inventory_by_key = {}
    for row in presentation["candidate_inventory"]:
        key = tuple(row.get(k) for k in ("candidate_id", "jurisdiction", "right_type", "scenario_id"))
        if key not in inventory_by_key or row.get("scope_status") == "included":
            inventory_by_key[key] = row
    known = set()
    for judgment in risk.get("judgments", []):
        scope = judgment.get("scope", {})
        key = (scope.get("candidate_id"), scope.get("jurisdiction"), scope.get("right_type"), scope.get("scenario_id"))
        if not scope.get("candidate_id"):
            continue
        inventory = inventory_by_key.get(key) or inventory_by_key.get((*key[:3], None), {})
        candidate_rows.append({**inventory, **scope, "title": inventory.get("title") or scope["candidate_id"],
            "scope_status": inventory.get("scope_status", "included"), "judgment": judgment})
        known.add((*key, inventory.get("object_id")))
    for row in presentation["candidate_inventory"]:
        key = (row.get("candidate_id"), row.get("jurisdiction"), row.get("right_type"), row.get("scenario_id"), row.get("object_id"))
        if key not in known and not (row.get("scenario_id") is None and any(k[:3] == key[:3] for k in known)):
            candidate_rows.append(row)
            known.add(key)
    candidate = ('<h2>候选追溯与逐项推论</h2><div class="table-wrap" role="region" '
        'aria-label="候选追溯，可横向滚动" tabindex="0"><table class="candidate-table stage-a-five">'
        '<thead><tr><th scope="col">候选</th><th scope="col">模块／法域</th><th scope="col">标题／权利人</th>'
        '<th scope="col">处置</th><th scope="col">证据引用</th></tr></thead><tbody>')
    for row in candidate_rows:
        judgment = row.get("judgment")
        status = (_candidate_status(row.get("scope_status") or "pending") + "；" +
            _candidate_status(row.get("triage_status") or "unreviewed"))
        if judgment:
            status += ("；" + _text(judgment.get("display_grade")) + "；" +
                _text(row.get("scenario_id")) + " / 产品版本 " + _text(row.get("product_version")) + "；审阅 " +
                _review_status(judgment.get("review_status")))
        candidate += ('<tr><td>' + e(_text(row.get("candidate_id"))) + '</td><td>' +
            e(_text(row.get("right_type"))) + ' / ' + e(_text(row.get("jurisdiction"))) + '</td><td>' +
            e(_text(row.get("title"))) + ('<p>' + e(_text(row.get("owner") or row.get("rights_holder"))) + '</p>'
            if row.get("owner") or row.get("rights_holder") else '') + '</td><td>' + e(status) +
            '<details class="fold"><summary>理由与缺口</summary>' +
            e(_text(judgment.get("comparison") if judgment else row.get("scope_reasoning"))) + '；' +
            e(_text(judgment.get("gaps") if judgment else [row.get("triage_reasoning"), row.get("missing_information"),
                row.get("reopen_reasons"), row.get("next_actions")])) +
            ('<p>候选处置依据：' + e(_text([row.get(key) for key in ('triage_reasoning', 'missing_information', 'reopen_reasons', 'next_actions')])) + '</p>' if any(row.get(key) for key in ('triage_reasoning', 'missing_information', 'reopen_reasons', 'next_actions')) else '') +
            ('<p>同族／文献成员：' + e(_text(row.get("family_members") or row.get("publication_numbers"))) + '</p>' if row.get("family_members") or row.get("publication_numbers") else '') +
            '</details></td><td>' + (old._refs_html(judgment, data) if judgment else old._refs_html(row, data) if row.get('evidence_refs') else '未绑定') + '</td></tr>')
    if not candidate_rows:
        candidate += '<tr><td colspan="5">尚无已登记候选；不据此推断无风险。</td></tr>'
    candidate += '</tbody></table></div>'
    trace = '<h2>数据绑定</h2><div class="facts">'
    trace_items = [("呈现版本", presentation["revision"]), ("阶段快照摘要", presentation["snapshot_sha256"][:16]),
        ("产品版本", stage["product"]["product_version"]), ("计划版本", progress.get("plan_version")),
        ("来源截止", stage["progress_cutoff"].get("source_run_count")),
        ("评级截止", stage["grade_cutoff"].get("stage_risk_event_count")),
        ("审阅截止", stage["grade_cutoff"].get("stage_review_event_count")),
        ("审核状态", review), ("评估时点", "；".join(_text(row.get("assessment_date")) for row in risk.get("judgments", [])))]
    if stage.get("limitations"):
        trace_items.append(("截点差异与阶段限制", "；".join(_text(item) for item in stage["limitations"])))
    trace += (''.join('<div class="fact"><span>' + e(label) + '</span><div>' + e(_text(value)) + '</div></div>'
        for label, value in trace_items) + '</div><p>历史样例指纹：<code>' + SAMPLE_SHA256 +
        '</code>；本版已按 M10-D002 衍生，业务值来自当前记录。</p>')
    if data.get('report_package_stage_c'):
        trace += '<p>' + ' · '.join('<a href="' + name + '">' + label + '</a>'
            for name, label in [('report-data.json', '统一报告数据'), ('report-manifest.json', '文件与材料清单'),
                ('report.md', 'Markdown'), ('report-findings.csv', 'CSV')]
            if name in data['report_package_stage_c']['required_artifacts']) + '</p>'
    if data.get("verification_basis", {}).get("acceptance_policy") == "api-first-v3":
        trace += '<h3>来源与事实采信</h3><p>' + e(data["verification_basis"]["note"]) + '</p>' + old._source_html(data)
        trace += old._list_html([_scope(row) + '；缺失或未采信字段：' + _text(row["unverified_facts"])
            for row in data["verification_basis"]["assessments"]])
    panels = [product_body, decision, coverage, gaps, modules, visual, candidate, trace]
    labels = ["产品快照", "筛查结论", "覆盖情况", "限制与待办", "七项模块", "视觉证据", "候选追溯", "数据绑定"]
    nav = ''.join('<a href="#' + key + '">' + label + '</a>' for key, label in zip(old.SECTION_ORDER, labels))
    sections = ''.join('<section id="' + key + '" class="panel' + (' trace' if key == 'trace' else '') +
        '">' + text + '</section>' for key, text in zip(old.SECTION_ORDER, panels))
    header = ('<header class="header"><div><h1>知识产权风险筛查报告</h1><div class="meta">' +
        e(_text(data["product"].get("title"))) + ' · 产品版本 ' + e(_text(stage["product"]["product_version"])) +
        ' · 评估时点见明细</div></div><span class="badge">' +
        ('最终报告 · ' if stage.get('final_review') else '阶段判断 · ') + e(review) + '</span></header>')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" '
        'content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; script-src \'none\'; '
        'base-uri \'none\'; form-action \'none\'"><title>知识产权风险筛查报告</title><style>' +
        old.CSS_PATH.read_text() + '</style></head><body class="stage-a-report"><div class="shell"><aside class="side"><div class="brand">'
        'LC IPR Screening</div><small>离线证据报告 · ' + e(data["task_id"]) + '</small><nav>' + nav +
        '</nav></aside><main class="main"><div class="wrap">' + header + sections +
        '<footer class="report-footer">' + e(data["footer"]) + '</footer></div></main></div></body></html>')
