"""Versioned operator projection; assessment owns grades, receipts own work states.

The readable report is deliberately separate from the complete audit payload.
No source calls, business mutations, or guessed completion occur here.
"""
from __future__ import annotations

import html
import csv
import io
import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

REVISION = "operator-report-v1"
SECTION_ORDER = ["product", "decision", "modules", "candidates", "gaps", "coverage", "trace"]
APPENDIX_FILES = ["operator-appendix.html", "technical-audit.html", "query-progress.html", "query-progress.json"]
RIGHTS = [("copyright", "版权"), ("design", "外观专利"), ("patent", "发明专利"),
          ("trade_dress", "商业外观"), ("trademark_figurative", "图形商标"),
          ("trademark_word", "文字商标"), ("utility_model", "实用新型"),
          ("unregistered_design", "未注册外观"), ("enforcement", "维权信号")]
SOURCE_NAMES = {"epo_ops": "欧洲专利局 OPS", "serpapi_google_patents": "SerpApi 专利",
    "serpapi_google_lens": "SerpApi 图片相似检索", "serper_web": "Serper 网页检索",
    "serper_patents": "Serper 专利", "signa": "Signa 商标",
    "public_source": "已留存公开原文", "google_patents": "Google Patents 公开记录",
    "local_agent_review": "公开材料阅读与比较", "asset_provenance": "设计来源与授权资料调查",
    "uspto_patent_browser": "美国专利商标局专利核验", "uspto_trademark_browser": "美国专利商标局商标核验"}
COUNTRIES = {"US": "美国", "GB": "英国", "FR": "法国", "DE": "德国", "IT": "意大利", "ES": "西班牙", "JP": "日本", "EU": "欧盟"}
RISKS = ["极低", "低", "中", "高", "极高"]
AUTO_PENDING_NOTE = "未取得对应国家和权利类型的合格检索比较或具体权利证据；保留阶段性记录，不输出最终风险结论。"
INTERNAL = re.compile(r"\b(?:EV|ATT|QRY|WORK|CAND|FDB|FINAL|INT|ITEM|REVIEW|BATCH)(?:-[A-Za-z0-9]+)+\b|\b[a-f0-9]{32,64}\b")
ERROR_LABELS = {"API_DISCOVERY_BUDGET_EXHAUSTED": "本轮已授权的该检索路线调用次数已用完",
    "PROVIDER_CAPABILITY_UNAVAILABLE": "对应检索接口不可用", "OFFICIAL_COVERAGE_UNVERIFIED": "未取得完整检索覆盖",
    "US_MEMBER_NOT_LOCATED": "尚未定位准确的美国记录", "SOURCE_ACCESS_LIMITED": "来源访问受限"}


def enabled(task):
    revision = task.get("presentation_policy_revision")
    if revision not in (None, REVISION):
        raise ValueError("OPERATOR_PRESENTATION_REVISION_INVALID")
    return revision == REVISION


def human(value, limit=None):
    """Only business prose is allowed in operator text; raw objects stay in audit."""
    if isinstance(value, dict):
        value = value.get("reasoning") or value.get("reason") or value.get("question") or value.get("description") or ""
    if isinstance(value, list):
        value = "；".join(filter(None, (human(item, limit) for item in value)))
    value = str(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    for code, meaning in ERROR_LABELS.items():
        value = value.replace(code, meaning)
    value = INTERNAL.sub("", value)
    value = re.sub(r"(?<![\w])(?:/[\w\u4e00-\u9fff .-]+){2,}", "相关留存文件", value)
    value = re.sub(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", "待补充的信息", value)
    value = re.sub(r"(?:evidence_refs|candidate_id|query_id|source_run_id|sha256|scenario_id|plan_entry_sha256)\s*[:=]?", "", value)
    value = re.sub(r"[；，、 ]{2,}", "；", value).strip("；，、 ：")
    return value if limit is None else value[:limit] + ("…" if len(value) > limit else "")


def unique(values, limit=None):
    result = list(dict.fromkeys(text for text in (human(v) for v in values) if text))
    return result if limit is None else result[:limit]


def _scope(row):
    scope = row.get("scope")
    return scope if isinstance(scope, dict) else row


def _primary(row, scenario):
    actual = _scope(row).get("scenario_id") or row.get("scenario_id")
    return not actual or actual == scenario


def _step(query):
    operation = query.get("operation") or query.get("search_dimension")
    return {"candidate_detail": "准确候选详情读取", "search": "公开来源检索", "image": "产品图片相似检索",
            "text": "关键词与技术术语检索", "claims": "权利要求读取", "drawings": "设计图样读取",
            "provenance": "创作来源与授权调查", "source_investigation": "公开来源与原作调查",
            "asset_provenance": "设计来源与授权调查", "document_reading": "完整材料阅读",
            "record_lookup": "准确记录读取", "record_reading": "准确记录阅读",
            "enforcement_signal_search": "公开维权信号检索", "patent_search": "专利关键词检索"}.get(operation, "来源调查" if operation and "_" in str(operation) else human(operation) or "来源调查")


def _candidate_key(row):
    # Application IDs are exact only within the same jurisdiction. A family
    # relationship alone does not merge different territories or rights.
    return (row.get("jurisdiction"), row.get("right_type"),
            row.get("application_number") or row.get("registration_number")
            or row.get("publication_number") or row.get("candidate_id"))



def _pending_key(origin, kind, scenario, right):
    """A shared fact can span modules; different objects never merge by prose."""
    scope = _scope(origin)
    objects = [origin.get('product_object_id'), origin.get('assessment_object'),
               scope.get('candidate_id'), origin.get('candidate_id')]
    objects += list(origin.get('product_object_ids') or origin.get('affected_object_ids') or [])
    events = [origin.get('fact_event_id'), origin.get('pending_fact_event_id')]
    events += list(origin.get('fact_event_ids') or [])
    event_ids = tuple(sorted(str(item) for item in events if item))
    object_ids = tuple(sorted(set(str(item) for item in objects if item)))
    # Without an identified shared object/event, retain the module scope.
    return (scope.get('scenario_id') or scenario, scope.get('jurisdiction') or '',
            object_ids, event_ids, origin.get('fact_kind') or kind,
            '' if object_ids or event_ids else right,
            origin.get('query_id') or '', origin.get('source_run_id') or '')


def _comparison_performed(rows):
    for row in rows:
        comparison = row.get('comparison')
        if not isinstance(comparison, dict):
            continue
        criteria = comparison.get('criteria') or []
        claims = comparison.get('claims') or []
        views = comparison.get('visual_coverage') or {}
        if (any(isinstance(item, dict) and item.get('criterion') and
                (item.get('reasoning') or item.get('evidence_refs')) for item in criteria)
                or any(isinstance(item, dict) and item.get('elements') for item in claims)
                or isinstance(views, dict) and views.get('product_views') and views.get('right_views')):
            return True
    return False

def _display_progress(data, fallback):
    """Use the evidence-validated query projection; legacy reports retain their snapshot."""
    execution = data.get("actual_query_execution_progress")
    if not isinstance(execution, dict):
        return deepcopy(fallback)
    progress = deepcopy(execution)
    planned = progress.get("planned_total", progress.get("planned", 0))
    completed = progress.get("completed_total", progress.get("completed", 0))
    if planned is None and progress.get("status") == "plan_required":
        progress.update(planned=None, completed=None, percentage=None)
        progress["by_scope"] = []
        return progress
    if (isinstance(planned, bool) or isinstance(completed, bool) or
            not isinstance(planned, int) or not isinstance(completed, int) or
            not 0 <= completed <= planned):
        raise ValueError("OPERATOR_QUERY_PROGRESS_COUNTS_INVALID")
    progress.update(planned=planned, completed=completed,
                    percentage=(completed / planned * 100 if planned else None))
    scopes = []
    for row in progress.get("by_scope", []):
        scope = {**_scope(row), **row}
        scope["planned"] = row.get("planned_total", row.get("planned", 0))
        scope["completed"] = row.get("completed_total", row.get("completed", 0))
        scopes.append(scope)
    progress["by_scope"] = scopes
    return progress


def build(task, evidence, assessment, candidates, data):
    if not enabled(task):
        return None
    if task.get("assessment_revision") != "known-findings-risk-v1":
        raise ValueError("OPERATOR_REPORT_KNOWN_FINDINGS_POLICY_REQUIRED")
    from report_query_trace import build_query_trace
    from report_estimate import _sha
    stage = data.get("presentation_stage_a", {}).get("stage", {})
    progress = _display_progress(data, stage.get("progress") or assessment.get("review_progress", {}))
    trace = data.get("query_trace") or build_query_trace(task, evidence, assessment, candidates,
        data.pop("_operator_plan"), source_task_dir=data["trace"]["source_task_dir"])
    data["query_trace"] = trace
    scenario = task.get("primary_scenario_id")
    judgments = stage.get("stage_risk", {}).get("judgments") or assessment.get("assessments", [])
    known = assessment.get("known_findings", {}).get("by_scope", [])
    if isinstance(known, dict):
        known = list(known.values())
    inventory = data.get("presentation_stage_a", {}).get("candidate_inventory", [])
    actual = {item.get("candidate_id"): item for group in candidates.values() if isinstance(group, list)
              for item in group if isinstance(item, dict) and item.get("candidate_id")}
    pending = []
    modules = []
    for right, label in RIGHTS:
        rows = [row for row in judgments if _scope(row).get("right_type") == right and _primary(row, scenario)]
        entries = [q for q in trace.get("queries", []) if q.get("right_type") == right and _primary(q, scenario)
                   and not q.get("historical_unplanned_run")]
        counts = [p for p in (progress.get("by_scope") or []) if p.get("right_type") == right and _primary(p, scenario)]
        planned = sum(p.get("planned", 0) for p in counts)
        completed = sum(p.get("completed", 0) for p in counts)
        local = [a for q in entries for a in q.get("attempts", []) if a.get("local_investigation_performed")]
        effective = {a.get("physical_source_run_id") or a.get("run_id"): a for q in entries
                     for a in q.get("attempts", []) if a.get("effective")}
        performed = [q for q in entries if any(a.get("source_query_performed") or a.get("physical_response_reused")
                     or a.get("local_investigation_performed") for a in q.get("attempts", []))]
        scope_results = [k for k in known if isinstance(k, dict) and _scope(k).get("right_type") == right and _primary(k, scenario)]
        not_applicable = (bool(scope_results) and all(k.get("applicability") == "not_applicable" or
            k.get("query_status") == "not_applicable" for k in scope_results)) or (bool(rows) and all(r.get("assessment_status") == "not_applicable" or
            r.get("verification_status") == "not_applicable" or r.get("applicability") == "not_applicable" for r in rows)
            )
        generic = right == "trademark_word" and bool(data["product"].get("brand_name_query"))
        if not_applicable:
            status = "不适用"
        elif planned and completed == planned:
            status = "本轮计划步骤完成"
        elif completed or performed or local:
            status = "已完成部分查询"
        elif generic:
            status = "无需查询（Generic 名称项）"
        else:
            status = "未查询"
        grades = [k.get("risk") or k.get("known_risk") or k.get("screening_risk") for k in scope_results]
        grades = [g for g in grades if g in RISKS]
        # Read the policy result; do not manufacture a low score in a renderer.
        risk = max(grades, key=RISKS.index) if grades else None
        if risk is None:
            actual_grades = [r.get("risk") or r.get("stage_risk") for r in rows if
                (r.get("risk") or r.get("stage_risk")) in RISKS and r.get("aggregation_included", True)]
            risk = max(actual_grades, key=RISKS.index) if actual_grades else None
        if not_applicable:
            risk = None
        positive = risk in {"中", "高", "极高"}
        unresolved = [] if not_applicable else [r for r in rows if r.get("assessment_status") == "pending" or r.get("pending_reasoning")]
        finding = "已查明具体风险" if positive else "存在待判断线索" if unresolved else "本轮已查结果未发现已证实的具体风险" if performed or completed or not_applicable else "尚无本模块查询结果"
        done = []
        if planned:
            done.append("已完成 %s/%s 个去重查询或资料核查项；该比例表示查询工作完成度。" % (completed, planned))
        if effective:
            names = unique(SOURCE_NAMES.get(q.get("provider"), q.get("provider")) for q in entries
                           if any(a.get("effective") for a in q.get("attempts", [])))
            done.append("实际使用：" + "、".join(names) + "。有效响应按原记录及其范围使用。")
            retrieved = sum(a.get("retrieved_hits") or 0 for a in effective.values())
            if retrieved:
                done.append("有效响应共载有 %s 条结果；重复响应按一次计算，结果条数不等于权利件数，处理范围以查询完成记录为准。" % retrieved)
        if local:
            done.append("完成留存公开材料的本地阅读、来源调查或比较；此动作无需向远程接口提交。")
        completed_steps = unique(_step(q) for q in entries if any(a.get("effective") or a.get("local_investigation_performed") for a in q.get("attempts", [])))
        if completed_steps:
            done.append("已执行步骤：" + "、".join(completed_steps) + "。")
        related_candidates = {item.get("candidate_id"): item for item in inventory if
            item.get("right_type") == right and _primary(item, scenario) and item.get("candidate_id")}
        if related_candidates:
            reviewed = sum(item.get("triage_status") in {"selected", "not_selected", "needs_info"}
                           for item in related_candidates.values())
            done.append("本范围候选清单有 %s 个去重对象，其中 %s 个已完成相关性分流；入选与待补信息分别继续比较。" % (len(related_candidates), reviewed))
        if not_applicable:
            done.extend(unique(k.get("query_not_required_reason") or k.get("reasoning") for k in scope_results))
            if not done:
                done.extend(unique(r.get("reasoning") or r.get("product_link") for r in rows))
        if generic:
            done.append(data["product"]["brand_name_query"]["display"] + "；该参考名称无需查询。")
        if not done:
            done.append("未登记有效查询或已完成调查步骤。")
        facts = unique(k.get("query_not_required_reason") or k.get("reasoning") for k in scope_results) if not_applicable else unique(
            r.get("reviewed_reasoning") or r.get("pending_reasoning") or r.get("product_link") or r.get("reasoning") for r in rows)
        missing = []
        pending_records = []
        def add_missing(text, origin, kind):
            text = human(text)
            if text:
                missing.append(text)
                pending_records.append({'module': label, 'text': text,
                    'identity': _pending_key(origin, kind, scenario, right),
                    'subject': human(origin.get('title') or actual.get(origin.get('candidate_id') or _scope(origin).get('candidate_id'), {}).get('title'))})
        if planned > completed:
            add_missing("另有 %s 个查询项未完成；已尝试但失败、受限或状态未知的项保留为未完成。" % (planned-completed),
                        {}, 'plan_acceptance')
        for q in entries:
            last = q.get("attempts", [])[-1] if q.get("attempts") else {}
            if q.get("status") == "not_run" and planned and completed == planned:
                continue  # Optional directions do not reopen an accepted unique-work plan.
            if q.get("status") in {"failed", "access_limited", "submission_unknown", "not_run", "unknown"}:
                add_missing(SOURCE_NAMES.get(q.get("provider"), human(q.get("provider"))) + "：" +
                    q.get("status_label", "状态未知") + ("；" + human(last.get("reason")) if last.get("reason") else ""),
                    q, 'source_response')
        for row in unresolved:
            if row.get('pending_reasoning'):
                add_missing("已查材料仍不足以确定全部权利或授权事实；具体补充资料见运营关注。"
                    if row['pending_reasoning'] == AUTO_PENDING_NOTE and row.get('reviewed_reasoning')
                    else row['pending_reasoning'], row, 'pending_judgment')
        if right in {"trademark_word", "trademark_figurative"}:
            for issue in candidates.get('official_export_issues', []):
                if (isinstance(issue, dict) and right in issue.get('affected_right_types', [])
                        and issue.get('jurisdiction') in task.get('target_jurisdictions', [])):
                    add_missing('已留存的官方商标导出文件格式损坏，结果无法读取；本项仍待重新取得并复核。',
                        {'evidence_id': issue.get('evidence_id'), 'fact_kind': 'official_export_unreadable'},
                        'official_export_unreadable')
            own = [o for o in data["product"].get("scope_objects", []) if
                   o.get("kind") in {"own_brand", "own_logo"} or o.get("object_role") == "own_brand"]
            if not performed and not own:
                add_missing("自有品牌名称或 Logo 未提供，尚未对具体自有标识进行查询。",
                            {'assessment_object': 'own_mark'}, 'own_mark_identity')
        if risk is None and not not_applicable and not missing:
            add_missing("本模块尚无完成复核的适用风险判断；" +
                ("尚未登记有效查询或调查步骤。" if status == "未查询" else "已查材料仍不足以给出风险等级。"),
                {}, 'module_risk_pending')
        missing = unique(missing)
        actions = [] if not_applicable else unique(action for r in rows for action in r.get("human_checks", []))
        modules.append({"right_type": right, "label": label, "query_status": status, "risk": risk,
            "risk_label": "不适用" if not_applicable else risk or "待定",
            "finding": finding, "completed": completed, "planned": planned, "done": done,
            "facts": facts, "unfinished": missing, "actions": actions,
            "jurisdictions": sorted(set(_scope(r).get("jurisdiction") for r in rows if _scope(r).get("jurisdiction")))})
        pending.extend(pending_records)
    merged = {}
    for item in pending:
        shared = merged.setdefault(item['identity'], {'texts': [], 'modules': set(), 'subjects': []})
        shared['texts'].append(item['text'])
        shared['modules'].add(item['module'])
        shared['subjects'].append(item.get('subject'))
    pending = [{'identity': [list(part) if isinstance(part, tuple) else part for part in identity], 'text': '；'.join(unique(value['texts'])),
                'modules': sorted(value['modules']), 'subjects': unique(value['subjects'])} for identity, value in merged.items()]
    focus, seen = [], set()
    for projected in sorted(inventory, key=lambda item: item.get("triage_status") != "selected"):
        if not _primary(projected, scenario) or projected.get("triage_status") not in {"selected", "needs_info", "pending_recheck"}:
            continue
        candidate = {**actual.get(projected.get("candidate_id"), {}), **projected}
        if candidate.get("right_type") == "unknown":
            continue  # Public sales links are explained in copyright/trade-dress cards.
        key = _candidate_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        related = [r for r in judgments if _scope(r).get("candidate_id") == candidate.get("candidate_id") and _primary(r, scenario)]
        refs = {ref for r in related for ref in r.get("evidence_refs", [])}
        images = [img for img in data.get("visual_evidence", []) if img.get("candidate_id") == candidate.get("candidate_id")]
        figures = [img for img in images if img.get("visual_role") in {"patent_drawings", "registry_record", "copyright_work", "trade_dress_view"}]
        images = (figures or images)[:2]
        scope_notes = unique([candidate.get("missing_information"), candidate.get("triage_reasoning"),
            *[r.get("pending_reasoning") or r.get("product_link") or r.get("reasoning") for r in related]])
        focus.append({"candidate_id": candidate.get("candidate_id"), "title": human(next((r.get("title") for r in related if r.get("title")), None) or candidate.get("title"), 220),
            "number": candidate.get("publication_number") or candidate.get("registration_number") or "",
            "jurisdiction": candidate.get("jurisdiction"), "right_type": candidate.get("right_type"),
            "status": ("待重新判断" if candidate.get("triage_status") == "pending_recheck" else
                "待补信息" if candidate.get("triage_status") == "needs_info" else
                "已入选并比较" if _comparison_performed(related) else "已入选待比较"),
            "risk": next((r.get("risk") for r in related if r.get("risk") in RISKS), None),
            "notes": scope_notes, "images": images, "evidence_refs": sorted(refs)})
    expression_rows = [r for r in judgments if _scope(r).get("right_type") == "copyright" and _primary(r, scenario)]
    for jurisdiction in sorted({_scope(row).get('jurisdiction') for row in expression_rows
                                if _scope(row).get('jurisdiction')}):
        scoped = [row for row in expression_rows if _scope(row).get('jurisdiction') == jurisdiction]
        refs = {ref for row in scoped for ref in row.get('evidence_refs', [])}
        main_hash = data["product"].get("main_visual", {}).get("sha256")
        expression_images = [img for img in data.get("visual_evidence", []) if img.get("evidence_id") in refs
            and img.get("sha256") != main_hash and not img.get("source_document_path")]
        focus.append({"candidate_id": None, "title": "所列产品的版权表达与公开来源", "number": "",
            "jurisdiction": jurisdiction, "right_type": "copyright",
            "status": "来源或授权待判断" if any(row.get('assessment_status') == 'pending' for row in scoped) else "已评估的版权表达",
            "risk": None, "notes": unique(row.get("pending_reasoning") or row.get("reasoning") for row in scoped),
            "images": expression_images[:2], "evidence_refs": sorted(refs)})
    # One international publication can have separate US/unknown applicability
    # units. Present the publication once and retain both scope notes in audit.
    deduped, international = [], {}
    for item in focus:
        number = item.get("number", "")
        if str(number).startswith("WO"):
            if number in international:
                prior = international[number]
                prior["notes"] = unique(prior["notes"] + item["notes"])
                prior["evaluation_scopes"] = list(dict.fromkeys(prior["evaluation_scopes"] + [item["jurisdiction"]]))
                continue
            item["evaluation_scopes"] = [item["jurisdiction"]]
            item["jurisdiction"] = "国际公开；美国对应成员待定位"
            international[number] = item
        deduped.append(item)
    focus = deduped
    sources = []
    unique_runs = {}
    for q in trace.get("queries", []):
        if not _primary(q, scenario):
            continue
        for attempt in q.get("attempts", []):
            identifier = attempt.get("physical_source_run_id") or attempt.get("run_id")
            if identifier:
                unique_runs.setdefault((q.get("provider"), identifier), (q, attempt))
    grouped = {}
    for (provider, _), (q, attempt) in unique_runs.items():
        group = grouped.setdefault(provider, {"source": SOURCE_NAMES.get(provider, human(provider)), "date": [],
            "operations": [], "valid_responses": 0, "unsuccessful": 0, "boundaries": []})
        group["date"].append(str(attempt.get("checked_at") or "")[:10])
        group["operations"].append(_step(q))
        group["valid_responses"] += int(bool(attempt.get("effective") or attempt.get("local_investigation_performed")))
        group["unsuccessful"] += int(not (attempt.get("effective") or attempt.get("local_investigation_performed")))
        if attempt.get("total_hits") is not None and attempt.get("retrieved_hits") is not None and attempt["total_hits"] > attempt["retrieved_hits"]:
            group["boundaries"].append("一份响应取得 %s/%s 条，剩余结果未读取" % (attempt["retrieved_hits"], attempt["total_hits"]))
    for group in grouped.values():
        group["date"] = unique(group["date"])
        group["operations"] = unique(group["operations"])
        group["boundaries"] = unique(group["boundaries"])
        sources.append(group)
    overall = deepcopy(assessment.get("overall", {}))
    if overall.get("risk") not in RISKS and not (overall.get("risk") is None
            and overall.get("risk_basis") == "insufficient_evidence"):
        raise ValueError("OPERATOR_REPORT_POLICY_RESULT_MISSING")
    css = Path(__file__).resolve().parent.parent / "assets/operator-report.css"
    round_closed = bool(assessment.get("publication", {}).get("mode") in {"evidence", "final"}
                        and stage.get("final_review"))
    return {"revision": REVISION, "risk_policy": "known-findings-risk-v1", "overall": overall,
        "primary_scenario_id": scenario, "progress": progress, "modules": modules,
        "focus_candidates": focus, "pending_items": pending, "sources": sources,
        "delivery": {"round": "本轮报告完成" if round_closed else "当前阶段结果",
                     "meaning": "查询进度与事实缺口见各模块；实际入口由交付记录核对。"},
        "reassessment_note": ("本版按已确认的评级与运营展示规则重新评估，复用既有查询和比较；进度按真实查询与资料核查完成记录修正，本次未新增 API 查询。"
            if (task.get("reassessment_provenance") or {}).get("kind") == "explicit_user_requested_policy_and_presentation_reassessment" else ""),
        "appendices": APPENDIX_FILES, "stylesheet_sha256": _sha(css.read_bytes())}


def project(data, model):
    data["presentation_policy_revision"] = REVISION
    data["operator_view"] = model
    data["overall"] = deepcopy(model["overall"])
    data["section_order"] = SECTION_ORDER
    return data


def _e(value):
    return html.escape(str(value or ""))


def _paragraphs(values, maximum=None):
    return "".join("<p>" + _e(text) + "</p>" for text in unique(values, maximum)) or "<p>无新增事项。</p>"


def _page(title, body):
    css = (Path(__file__).resolve().parent.parent / "assets/operator-report.css").read_text()
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; script-src \'none\'; base-uri \'none\'; form-action \'none\'"><title>' + _e(title) + '</title><style>' + css + '</style></head><body><main>' + body + '</main></body></html>'


def _figure(item, output_dir):
    from report_estimate import _figure as verified_figure
    visible = {**item, "label": human(item.get("label")), "alt": human(item.get("alt")),
               "caption": human(item.get("caption"))}
    result = verified_figure(visible, Path(output_dir))
    return re.sub(r" · SHA-256 [a-f0-9]+", "", result)


def _progress_label(progress):
    percentage = progress.get("percentage")
    if isinstance(percentage, (int, float)) and not isinstance(percentage, bool):
        return "%.1f%%" % percentage
    if progress.get("planned") is None or progress.get("status") == "plan_required":
        return "查询计划未登记"
    return "不适用（无查询计划）" if progress.get("planned") == 0 else "未登记百分比"


def _progress_summary(progress):
    if progress.get("planned") is None or progress.get("status") == "plan_required":
        return "查询计划尚未登记；无法计算完成百分比。"
    return "%s/%s 个去重查询或资料核查项已完成" % (progress.get("completed", 0), progress.get("planned", 0))


def _query_basis(value):
    labels = {
        "NO_BOUND_RUN": "未找到绑定本查询的执行回执。",
        "QUERY_NOT_REGISTERED_BEFORE_EXECUTION": "查询尚未正式登记到当前计划，不能计为完成。",
        "PRODUCT_SCOPE_REVIEW_REQUIRED": "产品或评估范围变化，需要复核查询是否仍适用。",
        "QUERY_REOPENED_REVALIDATION_REQUIRED": "查询已重新开启，既有回执需要重新核验。",
        "SOURCE_ROOT_UNAVAILABLE": "留存原始资料所在目录不可用，无法核验。",
        "LOCAL_INVESTIGATION_REVALIDATED": "本地资料核查及其原始证据已重新核验，符合完成条件。",
        "LOCAL_INVESTIGATION_INCOMPLETE": "本地资料核查或其证据验证尚未完成。",
        "SOURCE_SUBMISSION_NOT_CONFIRMED": "尚未确认查询已提交，且没有可复用的合格原始响应。",
        "SOURCE_ORIGINAL_INVALID": "原始响应文件缺失或未通过完整性核验。",
        "ZERO_RESULT_UNVERIFIED": "零结果尚未取得合格原始证明。",
        "RETAINED_RESPONSE_FULLY_READ": "原始响应完整留存，已完成取得范围内的结果阅读与处理。",
        "RESULT_READING_INCOMPLETE": "响应已取得，结果阅读或处理尚未完成。",
        "SOURCE_CARDS_REVIEWED": "原始响应和对应结果卡已完成阅读、处理与复核。",
        "VERIFIED_ZERO_RESPONSE": "合格原始响应证明为零结果，查询已完成。",
        "RESULT_READING_PROOF_MISSING": "缺少结果已完成阅读和处理的证明。",
    }
    value = str(value or "")
    if value in labels:
        return labels[value]
    if value.startswith("SOURCE_RESULT_"):
        status = value.removeprefix("SOURCE_RESULT_").lower()
        return "查询响应状态为%s，尚不符合完成条件。" % {
            "failed": "失败", "access_limited": "访问受限", "unknown": "未知",
            "pending": "等待响应", "not_submitted": "未提交"}.get(status, "尚未有效确认")
    if value.startswith("RECEIPT_VALIDATION_FAILED:"):
        return "执行回执未通过证据校验，具体原因保留在完整查询记录中。"
    if re.fullmatch(r"[A-Z][A-Z0-9_]+(?::.*)?", value):
        return "证据或结果处理尚未通过完成核验，具体原因保留在完整查询记录中。"
    return human(value)


def render(data, output_dir):
    view, product = data["operator_view"], data["product"]
    overall, progress = view["overall"], view["progress"]
    grade = overall["risk"]
    grade_label = grade + "风险" if grade in RISKS else "风险待定"
    completed, planned = progress.get("completed", 0), progress.get("planned", 0)
    progress_text = _progress_label(progress)
    body_name = next((obj.get("description") for obj in product.get("scope_objects", []) if
        obj.get("kind") == "product" and obj.get("scope_status") == "included" and obj.get("description")), "")
    name = human(product.get("chinese_title") or str(body_name).split("；")[0] or product.get("title"), 140)
    image = _figure(product["main_visual"], Path(output_dir)) if product.get("main_visual") else '<p class="empty">未取得可用主图。</p>'
    countries = "、".join(COUNTRIES.get(j, j) for j in product.get("jurisdictions", []))
    body = '<header><span class="eyebrow">运营知识产权筛查</span><h1>' + _e(name or "产品风险筛查") + '</h1></header>'
    scenario_text = human(product.get("scope_assumption") or "拟售情景未明确；按已登记的产品资料和市场范围判断。", 280)
    body += '<section id="product" class="hero"><div class="product-image">' + image + '</div><div><h2>本次销售情景</h2><p>' + _e(scenario_text) + '</p><dl><dt>商品</dt><dd>' + _e(product.get("asin") or product.get("requested_asin")) + '</dd><dt>市场</dt><dd>' + _e(countries) + '</dd><dt>评估日期</dt><dd>' + _e(str(data.get("generated_at", ""))[:10]) + '</dd></dl><p>未取得的产品视图、实际销售版本和授权资料以各模块缺口为准。</p></div></section>'
    body += '<section id="decision"><h2>当前结果</h2><div class="metrics"><div class="metric"><span>已知结果风险</span><strong class="risk">' + _e(grade_label) + '</strong><small>基于本轮已查明项目</small></div><div class="metric"><span>查询完成率</span><strong>' + _e(progress_text) + '</strong><small>' + _e(_progress_summary(progress)) + '</small></div><div class="metric"><span>报告状态</span><strong>' + _e(view["delivery"]["round"]) + '</strong><small>仍可按新资料补充判断</small></div></div>'
    explanation = human(overall.get("screening_statement") or overall.get("reasoning") or overall.get("known_findings_reasoning"))
    body += '<p class="decision-note">评级置信度：' + _e(human(overall.get("confidence")) or "未形成") + '。侵权风险未排除。</p><p class="grade-reason">' + _e(explanation or ("尚无完成复核的适用风险判断。" if grade is None else "具体风险依据见相关模块和候选。")) + '</p><p><b>上架建议：' + _e(overall.get('listing_recommendation') or '暂缓上架') + '。</b>' + _e(overall.get('listing_reason') or '仍需核对实际销售情景与未完成事项。') + '</p><p>风险由已查明的具体项目决定；未完成事项单独列明。查询完成率表示查询和资料核查进度，不能解读为已排除侵权的比例。</p></section>'
    body += '<section id="modules"><h2>九类查询结果</h2><div class="module-grid">'
    for module in view["modules"]:
        body += '<article class="module"><div class="card-heading"><h3>' + _e(module["label"]) + '</h3><span class="badge">' + _e(module["query_status"]) + '</span></div><p class="finding">' + _e(module["finding"]) + '</p>'
        body += '<p>本项风险：<b>' + _e(module["risk_label"]) + '</b></p>'
        body += '<h4>查了什么</h4>' + _paragraphs(module["done"], 6)
        body += '<h4>发现什么</h4>' + _paragraphs(module["facts"] or [module["finding"]], 2)
        body += '<h4>尚未完成</h4>' + _paragraphs(module["unfinished"], 3)
        body += '<h4>运营关注</h4>' + _paragraphs(module["actions"] or ["后续取得对应资料时可补充判断。" if module["unfinished"] else "无新增必要动作。"], 2) + '</article>'
    body += '</div><p>同一图片响应可支持不同权利的调查，各模块按其实际用途分别说明；它不代表多个独立来源。</p></section>'
    body += '<section id="candidates"><h2>值得关注的候选</h2><p>入选表示需要比较，待判断线索尚未成为查明的侵权风险。下列候选按具体产品关系展示，完整清单见附录。</p>'
    for item in view["focus_candidates"]:
        body += '<article class="candidate"><h3>' + _e(item["number"] or item["title"]) + '</h3><p>' + _e(item["title"]) + ' · ' + _e(COUNTRIES.get(item["jurisdiction"], item["jurisdiction"])) + ' · ' + _e(item["status"]) + '</p>'
        body += _paragraphs(item["notes"], 2)
        if item["images"]:
            body += '<div class="compare"><div><h4>目标产品</h4>' + image + '</div><div><h4>候选相关图证</h4>' + _figure(item["images"][0], Path(output_dir)) + '</div></div>'
            body += '<p class="small">图样用于说明比较对象；相似图片本身不单独证明权利、状态或侵权。</p>'
        else:
            body += '<p class="empty">当前报告未取得或未精确绑定可展示的候选图样；已读文字、比较与缺口继续保留。</p>'
        body += '</article>'
    if not view["focus_candidates"]:
        body += '<p>未形成可单独展示的准确权利候选；公开相似来源及其未知信息已列在模块中。</p>'
    body += '</section><section id="gaps"><h2>未完成事项</h2><p>这些事项说明本轮边界，不作为已知结果评级的加分或扣分。各模块已经列出具体缺口；完整合并清单及恢复条件见候选附录。</p>'
    important = [item for item in view["pending_items"] if not item["text"].startswith("另有 ")]
    body += (''.join('<p>' + _e(('、'.join(item.get('subjects') or []) + '：') if item.get('subjects') else '') +
                     _e(item['text']) + '</p>' for item in important[:5]) or '<p>无新增事项。</p>')
    body += '</section><section id="coverage"><h2>实际来源与查询范围</h2>'
    for source in view["sources"]:
        body += '<article class="source"><h3>' + _e(source["source"]) + '</h3><p>查询或阅读日期：' + _e("、".join(source["date"]) or "未记录") + '。已读取有效响应或完成本地调查 ' + str(source["valid_responses"]) + ' 次；失败、受限或尚未有效确认的记录 ' + str(source["unsuccessful"]) + ' 次。</p><p>用途：' + _e("、".join(source["operations"])) + '。</p>' + _paragraphs(source["boundaries"], 2) + '</article>'
    body += '<p>API 的有效字段按准确记录、地域和时间采信；摘要、历史事件和同族状态仅按原意使用。未取得的信息保留未知，来源查询没有穷尽承诺。</p></section>'
    body += '<section id="trace"><h2>按需查看详细资料</h2>' + ('<p>' + _e(view.get('reassessment_note')) + '</p>' if view.get('reassessment_note') else '') + '<p><a href="operator-appendix.html">完整候选、逐要素比较与未完成清单</a></p><p><a href="technical-audit.html">技术审计与数据追溯</a></p><p><a href="query-progress.html">逐项查询完成记录与统计口径</a></p><p>本报告适用于所列产品、销售情景、市场与评估时点；新产品资料、授权或权利状态可能改变已知结果。</p></section>'
    return _page("运营知识产权筛查报告", body)


def render_appendix(data, output_dir):
    view = data["operator_view"]
    stage = data.get("presentation_stage_a", {}).get("stage", {})
    judgments = stage.get("stage_risk", {}).get("judgments", [])
    body = '<header><h1>候选与分析附录</h1><p><a href="report.html">返回运营报告</a></p></header><h2>未完成事项与恢复条件</h2>'
    for item in view["pending_items"]:
        body += '<p><b>' + _e("、".join(item["modules"])) + '</b>：' + _e(item["text"]) + '</p>'
    body += '<h2>全部候选清单</h2>'
    inventory = data.get("presentation_stage_a", {}).get("candidate_inventory", [])
    for item in inventory:
        body += '<article><h3>' + _e(human(item.get("title"))) + '</h3><p>' + _e(COUNTRIES.get(item.get("jurisdiction"), item.get("jurisdiction"))) + ' · ' + _e(item.get("right_type")) + ' · ' + _e({"selected": "入选", "not_selected": "不入选", "needs_info": "待补信息", "scope_not_assessed": "未纳入本次销售情景"}.get(item.get("triage_status"), "待处理")) + '</p>' + _paragraphs([item.get("triage_reasoning"), item.get("scope_reasoning"), item.get("missing_information")]) + '</article>'
    body += '<h2>逐项比较与专业判断</h2>'
    for row in judgments:
        body += '<article><h3>' + _e(human(row.get("title"))) + '</h3><p>情景：' + _e(row.get("scenario_title")) + '；原始风险：' + _e(row.get("risk") or "待判断") + '；证据置信度：' + _e(row.get("confidence") or "未形成") + '</p>'
        for key, label in [("supporting_evidence", "支持风险的事实"), ("counter_evidence", "降低风险的事实"), ("reasoning", "判断依据"), ("pending_reasoning", "待判断原因"), ("human_checks", "补充材料与恢复条件")]:
            if row.get(key):
                body += '<h4>' + label + '</h4>' + _paragraphs(row[key] if isinstance(row[key], list) else [row[key]])
        comparison = row.get("comparison") or {}
        for claim in comparison.get("claims", []) + comparison.get("independent_claims", []):
            if not isinstance(claim, dict):
                continue
            body += '<h4>权利要求 ' + _e(claim.get("claim_number") or claim.get("number") or claim.get("claim_id")) + '</h4>'
            for element in claim.get("elements", []):
                body += '<p>' + _e(human(element.get("claim_element") or element.get("claim_text") or element.get("element_text") or element.get("description"))) + '；产品对应：' + _e(human(element.get("product_feature") or element.get("reasoning") or element.get("product_correspondence"))) + '；比较结果：' + _e({"unknown": "资料不足", "match": "对应", "no_match": "不对应"}.get(element.get("result"), human(element.get("result")))) + '</p>'
        body += '</article>'
    return _page("候选与分析附录", body)


def render_query_progress(data, output_dir):
    """Readable task receipts; exact IDs and validation proofs remain in JSON/audit."""
    view = data["operator_view"]
    progress = view["progress"]
    planned, completed = progress.get("planned", 0), progress.get("completed", 0)
    label = _progress_label(progress)
    body = '<header><h1>查询完成记录</h1><p><a href="report.html">返回运营报告</a> · <a href="query-progress.json">完整查询记录</a></p></header>'
    body += '<section><h2>查询完成率：' + _e(label) + '</h2><p>' + _e(_progress_summary(progress)) + '</p><p>按当前查询任务及真实回执统计；重试与历史重复项不重复计数。失败、未提交、状态未知以及结果尚未完成处理的查询仍为未完成。查询完成率与侵权判断、事实是否查清和最终审阅分别记录。</p></section>'
    items = progress.get("items", [])
    for index, item in enumerate(items, 1):
        scope = _scope(item)
        right = item.get("right_type") or scope.get("right_type")
        provider = item.get("provider") or scope.get("provider")
        done = item.get("completed") is True if "completed" in item else item.get("state") == "completed" or item.get("status") == "completed"
        body += '<article><h3>' + str(index) + '. ' + _e(dict(RIGHTS).get(right, "查询任务")) + ' · ' + _e(SOURCE_NAMES.get(provider, human(provider))) + '</h3><p>状态：' + ('已完成' if done else '未完成') + '</p>'
        operation = item.get("operation") or item.get("dimension") or item.get("search_dimension") or scope.get("search_dimension")
        body += _paragraphs([item.get("title") or item.get("label") or ("步骤：" + human(operation) if operation else ""),
            _query_basis(item.get("reason") or item.get("completion_basis") or item.get("basis"))])
        for key, label in [("query_id", "查询编号"), ("source_run_id", "执行回执编号"),
                           ("search_dimension", "检索维度"), ("query", "查询表达式")]:
            if item.get(key) is not None and item.get(key) != "":
                body += '<p>' + label + '：<code>' + _e(item[key]) + '</code></p>'
        body += '</article>'
    if not items:
        body += '<p>该历史快照未保存逐项查询明细；可在技术审计中查看原进度来源。</p>'
    return _page("查询完成记录", body)


def render_audit(data, output_dir):
    # Complete technical data is delivered once in its own artifact. The JSON is
    # escaped and cannot execute; configured secret guards cover this payload.
    body = '<header><h1>技术审计与数据追溯</h1><p><a href="report.html">返回运营报告</a> · <a href="report-data.json">完整结构化报告数据</a></p></header><p>供专业复核与维护使用。包含原始候选状态、完整来源和判断引用，不把待判断事实视为已排除。</p><pre>'
    body += _e(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)) + '</pre>'
    return _page("技术审计与数据追溯", body)


def render_markdown(data):
    view = data["operator_view"]
    lines = ["# 运营知识产权筛查报告", "已知结果风险：" + (view["overall"]["risk"] or "待定"),
        "评级置信度：" + (human(view["overall"].get("confidence")) or "未形成"),
        "上架建议：" + (view["overall"].get("listing_recommendation") or "暂缓上架"),
        "查询完成：" + ("%s/%s" % (view["progress"].get("completed", 0), view["progress"].get("planned", 0))
                         if view["progress"].get("planned") is not None else "查询计划未登记")]
    for module in view["modules"]:
        lines.extend(["## " + module["label"], "查询状态：" + module["query_status"],
            "本项风险：" + module["risk_label"], module["finding"],
            "查了什么：" + "；".join(module["done"]), "尚未完成：" + ("；".join(module["unfinished"]) or "无新增事项")])
    return "\n\n".join(lines) + "\n"


def render_csv(data):
    stream = io.StringIO(newline="")
    fields = ["row_type", "right_type", "risk", "listing_recommendation", "query_status", "finding", "completed", "planned", "unfinished"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    view = data["operator_view"]
    writer.writerow({"row_type": "overall", "risk": view["overall"]["risk"] or "待定",
                     "listing_recommendation": view["overall"].get("listing_recommendation") or "暂缓上架",
                     "completed": view["progress"].get("completed"), "planned": view["progress"].get("planned")})
    for module in view["modules"]:
        row = {key: module.get(key) for key in fields if key in module}
        row.update(row_type="module", risk=module["risk_label"], unfinished="；".join(module["unfinished"]))
        writer.writerow({key: "'" + str(value) if str(value).lstrip().startswith(('=', '+', '-', '@')) else value
                         for key, value in row.items()})
    return stream.getvalue()
