#!/usr/bin/env python3
"""Offline, reproducible five-level report in the user's eight-section template.

The assessment engine owns legal grading. This module never fills a missing
rating, resolves reviewer disagreements, or upgrades a discovery signal.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import json
import mimetypes
import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from copy import deepcopy
from urllib.parse import quote, unquote, urlsplit

from common import atomic_write_bytes, atomic_write_json, recall_integrity_enabled, RECALL_INTEGRITY_REVISION

POLICY = "evidence-estimate-v1"
REPORT_SCHEMA = "IPR-EVIDENCE-ESTIMATE-REPORT/1.0"
LEGACY_VISUAL_POLICY_REVISION = "core-risk-evidence-v1"
VISUAL_POLICY_REVISION = "core-risk-evidence-v2"
COMPACT_REPORT_REVISION = "compact-evidence-v1"
VISUAL_ROLE_LABELS = {"document_identity": "文献身份页", "patent_claims": "适用权利要求页", "patent_drawings": "相关附图页",
                      "registry_record": "准确登记记录图", "copyright_work": "原作品图", "trade_dress_view": "商业外观原图"}
SECTION_ORDER = ["product", "decision", "coverage", "gaps", "modules", "visual", "candidates", "trace"]
SECTION_LABELS = ["产品快照", "筛查结论", "覆盖情况", "人工核查", "七项模块", "视觉证据", "候选追溯", "数据绑定"]
MODULE_LABELS = {"appearance_patent": "外观设计／外观专利", "utility_patent": "实用／发明专利", "pending_application": "已公开申请", "word_mark": "文字商标", "figurative_trade_dress": "图形商标与商业外观", "copyright_ip": "版权与创意资产", "enforcement": "公开维权信号"}
RIGHT_MODULES = {"design": "appearance_patent", "unregistered_design": "appearance_patent", "patent": "utility_patent", "utility_model": "utility_patent", "utility_patent": "utility_patent", "trademark_word": "word_mark", "trademark_figurative": "figurative_trade_dress", "trade_dress": "figurative_trade_dress", "copyright": "copyright_ip", "enforcement": "enforcement"}
RISKS = ["极低", "低", "中", "高", "极高"]
CONFIDENCES = ["低", "中", "高"]
RISK_CLASS = dict(zip(RISKS, ["very_low", "low", "medium", "high", "critical"]))
CSS_PATH = Path(__file__).resolve().parent.parent / "assets" / "evidence-estimate-template.css"
EXPLANATION_FIELDS = [("supporting_evidence", "支持风险的事实"), ("counter_evidence", "降低风险的事实"), ("reasoning", "主审推论"), ("assumptions", "假设与范围"), ("confidence_reasoning", "置信度理由"), ("human_checks", "人工核查"), ("raise_if", "上调条件"), ("lower_if", "下调条件")]
CSV_FIELDS = ["row_type", "jurisdiction", "right_type", "candidate_id", "title", "scope", "risk", "confidence", "aggregation_included", "supporting_evidence", "counter_evidence", "reasoning", "assumptions", "confidence_reasoning", "human_checks", "raise_if", "lower_if", "evidence_refs", "evidence_sources"]
BASIS_LABELS = {"official_verified": "已由官方记录核验", "source_observed": "来源所载，未经官方核验",
                "inferred": "基于所列证据的审阅推论", "unknown": "尚无足够证据", "conflicted": "来源记载存在冲突，未解决"}
FACT_FIELDS = {"title": "文献或标识名称", "publication_number": "公开号", "registration_number": "登记号",
               "legal_status": "法律状态", "owner": "权利人", "assignee": "受让人", "applicant": "申请人",
               "goods_services": "商品与服务", "claims": "权利要求", "claim_text": "权利要求文本"}



def _security_errors(objects: Any, rendered: dict[str, bytes | str] | None = None) -> list[str]:
    """Reuse the legacy secret/session boundaries without revealing matched data."""
    from common import load_skill_config
    from validate_run import configured_secrets, forbidden_browser_paths, FORBIDDEN_BROWSER_FIELDS
    errors = []
    secrets = configured_secrets(load_skill_config())
    texts = [json.dumps(objects, ensure_ascii=False, sort_keys=True)]
    for payload in (rendered or {}).values():
        texts.append(payload.decode('utf-8-sig', errors='replace') if isinstance(payload, bytes) else payload)
    text = '\n'.join(texts)
    decoded = html.unescape(unquote(text))
    if any(secret in text or secret in decoded for secret in secrets):
        errors.append('CONFIGURED_SECRET_IN_REPORT_OR_EVIDENCE')
    forbidden = bool(forbidden_browser_paths(objects))
    # Report prose can contain serialized field names even when its outer JSON
    # keys are innocuous. Apply the same forbidden-key set to those renditions.
    key_pattern = r'(?i)(?:["\']|\b)(?:' + '|'.join(re.escape(key) for key in sorted(FORBIDDEN_BROWSER_FIELDS)) + r')["\']?\s*[:=]'
    if forbidden or re.search(key_pattern, decoded):
        errors.append('FORBIDDEN_BROWSER_SESSION_FIELDS')
    return list(dict.fromkeys(errors))


def _require_safe(objects: Any, rendered: dict[str, bytes | str] | None = None) -> None:
    errors = _security_errors(objects, rendered)
    if errors:
        raise ValueError(';'.join(errors))

def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any) -> str:
    return _sha(_json(value))


def _safe_url(value: Any) -> str:
    value = str(value or "").strip()
    if any(ord(c) < 32 for c in value):
        return ""
    parsed = urlsplit(value)
    return value if parsed.scheme in ("", "https", "http") and not value.startswith("//") else ""


class _Inline(HTMLParser):
    """Keep evidence prose formatting, never executable template instructions."""
    def __init__(self, markdown: bool = False):
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.markdown = markdown
        self.links: list[str] = []
        self.suppress = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "iframe", "object"):
            self.suppress += 1
            return
        if self.suppress:
            return
        if tag == "a":
            url = _safe_url(dict(attrs).get("href"))
            self.links.append(url)
            self.output.append("[" if self.markdown else '<a href="' + html.escape(url, quote=True) + '">')
        elif tag in ("strong", "b", "em", "i", "code", "br", "p", "ul", "ol", "li"):
            self.output.append({"strong": "**", "b": "**", "em": "*", "i": "*", "code": "`", "br": "\n", "p": "\n", "ul": "\n", "ol": "\n", "li": "\n- "}[tag] if self.markdown else "<" + tag + ">")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "iframe", "object") and self.suppress:
            self.suppress -= 1
            return
        if self.suppress:
            return
        if tag == "a":
            url = self.links.pop() if self.links else ""
            self.output.append("](" + url + ")" if self.markdown else "</a>")
        elif tag in ("strong", "b", "em", "i", "code", "p", "ul", "ol", "li"):
            self.output.append({"strong": "**", "b": "**", "em": "*", "i": "*", "code": "`", "p": "\n", "ul": "\n", "ol": "\n", "li": ""}[tag] if self.markdown else "</" + tag + ">")

    def handle_data(self, data):
        if not self.suppress:
            self.output.append(data if self.markdown else html.escape(data))


def _inline(value: Any, markdown=False) -> str:
    parser = _Inline(markdown)
    parser.feed(str(value or ""))
    return "".join(parser.output)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "；".join(_text(item) for item in value)
    if isinstance(value, dict):
        if value.get("question"):
            labels = [("priority", "优先级"), ("owner", "核查人"), ("question", "核查事项"), ("evidence_needed", "所需证据"), ("raise_if", "上调条件"), ("lower_if", "下调条件")]
            return "；".join(label + "：" + _text(value[key]) for key, label in labels if value.get(key))
        main = value.get("reasoning") or value.get("action") or value.get("detail") or value.get("description") or value.get("title")
        if main is not None:
            suffix = "（核查人：" + str(value["reviewer"]) + "）" if value.get("reviewer") else ""
            refs = value.get("evidence_refs", [])
            return str(main) + suffix + (" [" + ", ".join(map(str, refs)) + "]" if refs else "")
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)



def _unique_notes(*groups: Any) -> list[str]:
    result, seen = [], set()
    for group in groups:
        for value in group if isinstance(group, list) else ([group] if group else []):
            text = _text(value).strip()
            key = " ".join(text.split())
            if key and key not in seen:
                seen.add(key)
                result.append(text)
    return result


def _reason_value(row: dict, key: str) -> Any:
    if key == "reasoning" and row.get("risk_basis") in {"evidence_supported", "policy_fallback"} and row.get("risk_reasoning"):
        return row["risk_reasoning"]
    value = row.get(key)
    if not value and key == "counter_evidence" and row.get("screening_revision") == RECALL_INTEGRITY_REVISION:
        return "未取得降低风险的证据。检索缺口不作为排除事实。"
    if not value and key in ("supporting_evidence", "counter_evidence"):
        value = row.get("no_" + key + "_reasoning")
    return value


def _overall_drivers(overall: dict, rows: list[dict]) -> list[dict]:
    def matches(row, driver):
        identity = ("jurisdiction", "right_type", "candidate_id", "title", "scenario_id", "scenario_sha256")
        declared = [key for key in identity if driver.get(key) is not None]
        return bool(declared) and all(row.get(key) == driver.get(key) for key in declared)
    drivers = [row for row in rows if _is_scored(row) and any(matches(row, driver) for driver in overall.get("drivers", []))]
    return drivers or [row for row in rows if _is_scored(row) and row["risk"] == overall["risk"]
                       and (not overall.get("scenario_id") or row.get("scenario_id") == overall["scenario_id"])]

def _module_id(row: dict) -> str:
    return row.get("module_id") or RIGHT_MODULES.get(row.get("right_type"), "utility_patent")


def _is_scored(row: dict) -> bool:
    return not row.get("out_of_scope") and row.get("risk_aggregation_included", row.get("aggregation_included", True)) and _module_id(row) != "enforcement" and row.get("risk") in RISKS


def _partial_report(data: dict) -> bool:
    from assessment_estimate import PARTIAL_EVIDENCE_REVISION
    return data.get("assessment_revision") == PARTIAL_EVIDENCE_REVISION and bool(data.get("query_trace"))


def _risk_basis_note(row: dict) -> str:
    return {"policy_fallback": "规则兜底：已取得信息中未确认中、高或极高风险；低风险不代表已经排除侵权风险。",
            "evidence_supported": "证据支持：基于已列事实及主审判断，未完成工作仍单独保留。"}.get(row.get("risk_basis"), "")


def _partial_warning(data: dict) -> str:
    from report_query_trace import ZERO_WARNING
    summary = data["query_trace"]["summary"]
    warning = "查询未完成；未完成步骤 " + str(summary["unfinished_step_count"]) + " 项；全部评级置信度为低。"
    if summary["zero_effective_search"]:
        warning += ZERO_WARNING if data['overall'].get('risk') == '低' and data['overall'].get('risk_basis') == 'policy_fallback' else "有效检索为零；当前风险由已审阅的具体证据支持，未完成范围不代表已排除侵权。"
    return warning


def _query_dimension_label(dimension: dict) -> str:
    label = " · ".join(str(dimension[key]) for key in ("scenario_id", "jurisdiction", "right_type") if dimension.get(key)) or "未标注查询范围"
    return label + (" [情景版本 " + str(dimension['scenario_sha256'])[:12] + "]" if dimension.get('scenario_sha256') else "")


def _query_notes_html(notes: list[str]) -> str:
    # Query strings and diagnostic IDs can occur after a translated prefix, so
    # the legacy line-start diagnostic detector cannot see them. Only this new
    # ledger uses the existing code wrapping rule; no CSS or old markup changes.
    return '<ul>' + ''.join('<li><code>' + html.escape(note) + '</code></li>' for note in notes) + '</ul>'


def _query_trace_html(data: dict) -> str:
    from report_query_trace import query_notes
    trace = data["query_trace"]
    result = '<h3>逐维查询事实与单项结论</h3><p class="meta">' + html.escape(trace["note"]) + '</p>'
    for dimension in trace["dimensions"]:
        label = _query_dimension_label(dimension)
        result += '<details class="fold"><summary>' + html.escape(label) + '</summary><div class="fold-content">'
        for index in dimension["query_indices"]:
            result += _query_notes_html(query_notes(trace["queries"][index]))
        if not dimension["query_indices"]:
            result += '<p>本维度未见已规划查询或实际执行记录。</p>'
        for row in dimension["conclusions"]:
            grade = (row.get("risk", "") + "风险／低置信度") if row.get("risk") and not row.get("out_of_scope") else "未纳入本次风险评价"
            result += '<p><strong>单项结论：' + html.escape(str(row.get("title") or row.get("candidate_id") or label)) + ' · ' + html.escape(grade) + '</strong></p>'
            result += _list_html([_risk_basis_note(row), _text(_reason_value(row, "reasoning") or row.get("pending_reasoning")),
                "尚需核查：" + _text(row.get("human_checks")), "可能上调：" + _text(row.get("raise_if")), "可能下调：" + _text(row.get("lower_if"))])
        result += '</div></details>'
    return result


def _risk_text(overall: dict) -> str:
    return overall["risk"] + "风险" if overall.get("risk") in RISKS else "阶段性报告 · 尚未定级"


def _scenario_summary_text(summary: dict, ledger_counts: dict | None = None) -> str:
    completion = summary["completion"]
    counts = completion["triage_counts"]
    all_counts = completion.get("all_triage_counts", counts)
    grade = summary["risk"] + "风险／" + summary["confidence"] + "置信度" if summary.get("risk") else "当前风险尚未定级"
    state = lambda key: "完成" if completion[key] == "complete" else "未完成"
    return (summary["title"] + "（" + ("主情景" if summary["primary"] else "条件情景") + "）：" + grade
        + "；检索 " + state("retrieval") + "／分流 " + state("triage") + "／核验 " + state("verification")
        + "／评级工作 " + state("assessment") + "；必要范围分流 " + str(sum(counts.values())) + " 条：已入选 " + str(counts["selected"])
        + "、未入选 " + str(counts["not_selected"]) + "、需补证 " + str(counts["needs_info"]) + "、未审 " + str(counts["unreviewed"])
        + "。本情景全量台账 " + str(sum(all_counts.values())) + " 条；其中不属必要工作范围的记录仍保留，不等于法律排除。"
        + ("全任务分流台账 " + str(sum(ledger_counts.values())) + " 条（按情景及权利范围计，不等于独立候选数）：已入选 "
           + str(ledger_counts["selected"]) + "、未入选 " + str(ledger_counts["not_selected"])
           + "、需补证 " + str(ledger_counts["needs_info"]) + "、未审 " + str(ledger_counts["unreviewed"]) + "。" if ledger_counts else ""))


def _scenario_html(data: dict) -> str:
    summaries = data.get("scenario_summaries", [])
    if not summaries:
        return ""
    result = '<div class="review-note"><strong>销售情景与完成状态</strong>'
    for item in summaries:
        result += '<h3>' + html.escape(item["title"]) + '</h3><p>' + html.escape(_scenario_summary_text(item, data.get("coverage", {}).get("triage", {}).get("counts"))) + '</p>' + _list_html(item["assumptions"])
        if not item.get("risk") and item.get("known_scoped_risk"):
            result += '<p class="scope-line">已评局部最高为' + html.escape(item["known_scoped_risk"]) + '风险；尚不足以外推该情景总风险。</p>'
    return result + '</div>'


def _unscored_text(row: dict) -> str:
    return "未纳入范围" if row.get("out_of_scope") else "待完成 · 尚未定级" if row.get("assessment_status") == "pending" else "补充注意事项"


def _confidence(row: dict) -> str:
    return row.get("evidence_confidence", row.get("confidence", ""))


def _refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        refs.extend(str(ref) for ref in value.get("evidence_refs", []) if isinstance(ref, (str, int)))
        for key, item in value.items():
            if key != "evidence_refs":
                refs.extend(_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_refs(item))
    return list(dict.fromkeys(refs))


def _registry(*objects: Any, registered_only: bool = False) -> dict[str, dict]:
    result: dict[str, dict] = {}
    if registered_only:
        # Reading receipts refer to EVs; they do not redefine those records.
        # Only the two established registration containers may supply media.
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            collections = obj.get("collections", {})
            groups = list(collections.values()) if isinstance(collections, dict) else [collections]
            groups.append(obj.get("evidence", []))
            for group in groups:
                if not isinstance(group, list):
                    continue
                for entry in group:
                    if not isinstance(entry, dict) or not entry.get("evidence_id"):
                        continue
                    identifier = str(entry["evidence_id"])
                    if identifier in result and result[identifier] != entry:
                        raise ValueError("REPORT_DUPLICATE_REGISTERED_EVIDENCE_ID: " + identifier)
                    result[identifier] = dict(entry)
        return result
    def visit(obj):
        if isinstance(obj, dict):
            identifier = obj.get("evidence_id")
            if identifier:
                result[str(identifier)] = dict(obj)
            for child in obj.values():
                visit(child)
        elif isinstance(obj, list):
            for child in obj:
                visit(child)
    for obj in objects:
        visit(obj)
    return result


def build_verification_basis(task: dict, evidence: dict, assessment: dict, candidates: dict, plan: dict) -> dict:
    """Describe observed facts; reuse the assessment engine's official eligibility.

    A source saying Active or carrying an official_verification object is still
    only a source observation without its exact accepted plan/run/record proof.
    None of these derived disclosures changes a risk, confidence or work status.
    """
    from assessment_v24 import official_refs
    registry = _registry(evidence, assessment.get("supplement", {}), registered_only=True)
    runs = {run.get("run_id"): run for run in evidence.get("source_runs", []) if isinstance(run, dict)}
    candidate_index = {row["candidate_id"]: row for group in candidates.values() if isinstance(group, list)
                       for row in group if isinstance(row, dict) and row.get("candidate_id")}
    rows = assessment.get("assessments", [])
    refs = _refs(rows) + _refs(assessment.get("publication", {}).get("limitations", []))
    sources = []
    for ref in dict.fromkeys(refs):
        entry = registry.get(ref, {})
        role = " ".join(_text(entry.get(key)) for key in ("role", "kind", "privacy", "purpose")).casefold()
        if entry.get("private") is True or any(word in role for word in ("private", "login", "account", "debug")):
            continue
        run = runs.get(entry.get("source_run_id"), {})
        payload = entry.get("payload", {})
        metadata = payload if isinstance(payload, dict) else {}
        official_metadata = metadata.get("official_verification", {})
        if not isinstance(official_metadata, dict):
            official_metadata = {}
        raw_url = (entry.get("source_url") or entry.get("url") or entry.get("final_url") or run.get("source_url")
                   or metadata.get("source_url") or metadata.get("url") or official_metadata.get("url"))
        url = _safe_url(raw_url)
        if urlsplit(url).scheme not in {"http", "https"}:
            url = ""
        source_time = entry.get("source_checked_at") or entry.get("collected_at")
        if not source_time and entry.get("checked_at_meaning") != "retained_file_hash_verification":
            source_time = entry.get("checked_at")
        source_time = source_time or metadata.get("source_checked_at") or metadata.get("checked_at") or official_metadata.get("checked_at") or run.get("checked_at") or run.get("finished_at") or ""
        sources.append({"evidence_id": ref, "source_name": entry.get("source_name") or entry.get("provider")
                        or run.get("provider") or urlsplit(url).hostname or "未标明来源名称",
                        "source_url": url, "source_checked_at": source_time,
                        "source_time_note": "原取证时间未登记" if not source_time else "原来源取证时间；不使用报告生成时间替代",
                        "source_run_id": entry.get("source_run_id", ""),
                        "authority_scope": entry.get("authority_scope") or run.get("authority_scope") or "unknown",
                        "retained_sha256": entry.get("sha256", ""), "observed_facts": []})
    source_index = {item["evidence_id"]: item for item in sources}
    items = []
    for row in rows:
        candidate = candidate_index.get(row.get("candidate_id"), {})
        accepted = official_refs(task, evidence, plan, candidate, row.get("jurisdiction", ""),
                                 row.get("right_type", "")) if candidate else set()
        observations = {field: [] for field in FACT_FIELDS}
        for ref in _refs(row):
            if ref not in source_index:
                continue
            entry = registry.get(ref, {})
            run = runs.get(entry.get("source_run_id"), {})
            if entry.get("source_run_id") and (not run or run.get("status") != "success"):
                continue
            payload = entry.get("payload", {})
            records = payload if isinstance(payload, list) else payload.get("candidates", [payload]) if isinstance(payload, dict) else []
            if entry.get("publication_number"):
                records = [*records, entry]
            for record in records:
                if not isinstance(record, dict):
                    continue
                if any((record.get(key) or entry.get(key)) and (record.get(key) or entry.get(key)) != row.get(key)
                       for key in ("jurisdiction", "right_type")):
                    continue
                identity_match = bool(candidate and record.get("candidate_id") == candidate.get("candidate_id"))
                number = candidate.get("publication_number")
                if not identity_match and number and record.get("publication_number") == number:
                    identity_match = (record.get("jurisdiction") or entry.get("jurisdiction")) == row.get("jurisdiction")
                if not identity_match:
                    continue
                # Even an accepted official record only supports fields actually
                # present in that record. Review reasoning is not an official fact.
                official = record.get("official_verification", {})
                for field in FACT_FIELDS:
                    value = official.get(field) if isinstance(official, dict) and official.get(field) is not None else record.get(field)
                    if value in (None, "", [], {}):
                        continue
                    text = _text(value)
                    observation = {"evidence_id": ref, "source_field": "official_verification." + field
                                   if isinstance(official, dict) and official.get(field) is not None else field,
                                   "candidate_id": row.get("candidate_id", ""), "jurisdiction": row.get("jurisdiction", ""),
                                   "right_type": row.get("right_type", ""), "source_record_sha256": _digest(record),
                                   "value": text[:800], "value_sha256": _digest(value), "excerpted": len(text) > 800,
                                   "basis": "official_verified" if ref in accepted and isinstance(official, dict)
                                            and official.get(field) is not None else "source_observed"}
                    if observation not in observations[field]:
                        observations[field].append(observation)
                    fact = {"field": field, "label": FACT_FIELDS[field], **observation}
                    if fact not in source_index[ref]["observed_facts"]:
                        source_index[ref]["observed_facts"].append(fact)
        facts = []
        for field, label in FACT_FIELDS.items():
            observed = observations[field]
            if not observed and field not in {"legal_status", "owner", "claims", "goods_services"}:
                continue
            if field == "claims" and row.get("right_type") not in {"patent", "utility_model", "utility_patent"}:
                continue
            if field == "goods_services" and row.get("right_type") not in {"trademark_word", "trademark_figurative"}:
                continue
            values = {item["value_sha256"] for item in observed}
            basis = ("unknown" if not observed else "conflicted" if len(values) > 1 else
                     "official_verified" if any(item["basis"] == "official_verified" for item in observed) else "source_observed")
            facts.append({"field": field, "label": label, "basis": basis, "basis_label": BASIS_LABELS[basis],
                          "observations": observed, "evidence_refs": list(dict.fromkeys(item["evidence_id"] for item in observed))})
        inference = _text(_reason_value(row, "reasoning") or row.get("pending_reasoning") or row.get("scope_reasoning"))
        facts.append({"field": "review_inference", "label": "审阅推论", "basis": "inferred" if inference else "unknown",
                      "basis_label": BASIS_LABELS["inferred" if inference else "unknown"], "value": inference,
                      "evidence_refs": [ref for ref in _refs(row) if ref in source_index], "observations": []})
        items.append({"assessment_index": len(items), **{key: row.get(key, "") for key in
                      ("scenario_id", "jurisdiction", "right_type", "candidate_id", "title")},
                      "facts": facts, "unverified_facts": [fact["label"] for fact in facts
                          if fact["basis"] in {"source_observed", "unknown", "conflicted"}]})
    counts = {basis: sum(fact["basis"] == basis for item in items for fact in item["facts"]) for basis in BASIS_LABELS}
    return {"schema": "IPR-VERIFICATION-BASIS/1.0", "sources": sources, "assessments": items, "fact_counts": counts,
            "note": "来源记载仅证明取证时该来源展示的内容；未核验事项不等于无权利或无侵权风险。"}


def _delivery_text(data: dict) -> str:
    if not data.get("verification_basis"):
        return ""
    publication = data.get("publication", {})
    mode = publication.get("mode")
    label = "来源取证报告已生成 · 含未经官方核验事项" if mode == "evidence" else "阶段取证报告 · 仍有待处理工作" if mode == "stage" else "报告已生成 · 核验范围见逐项依据"
    labels = {"completed": "完成", "complete": "完成", "partial": "部分交付", "incomplete": "未完成", "unknown": "未知"}
    return label + "。交付状态：" + labels.get(publication.get("delivery_status"), "未知") + "；业务完成度：" + labels.get(data["overall"].get("business_completion"), "未知") + "。"


def _report_risk_text(data: dict) -> str:
    if data.get("verification_basis") and data.get("publication", {}).get("mode") == "evidence" and data["overall"].get("risk") not in RISKS:
        return "来源取证报告 · 尚未定级"
    return _risk_text(data["overall"])


def _basis_item(data: dict, row: dict) -> dict:
    identity = ("scenario_id", "jurisdiction", "right_type", "candidate_id", "title")
    return next((item for item in data.get("verification_basis", {}).get("assessments", [])
                 if all(item.get(key, "") == row.get(key, "") for key in identity)), {})


def _basis_notes(data: dict, row: dict) -> list[str]:
    return [fact["label"] + "：" + fact["basis_label"] + ("；" + fact["value"] if fact.get("value") else "")
            + ("；" + "；".join(item["value"] + " [" + item["evidence_id"] + "]" for item in fact["observations"])
               if fact["observations"] else "") for fact in _basis_item(data, row).get("facts", [])]


def _source_notes(data: dict, row: dict | None = None) -> list[str]:
    refs = set(_refs(row)) if row is not None else None
    if row is not None and isinstance(row.get("evidence_refs"), str):
        refs.update(row["evidence_refs"].split(";"))
    def facts(item):
        return [fact for fact in item["observed_facts"] if row is None or not row.get("candidate_id")
                or all(fact.get(key, "") == row.get(key, "") for key in ("candidate_id", "jurisdiction", "right_type"))]
    return [item["source_name"] + " [" + item["evidence_id"] + "]；来源：" + (item["source_url"] or "未登记来源 URL")
            + "；原取证时间：" + (item["source_checked_at"] or "未登记")
            + "；实际支持：" + ("；".join(fact["candidate_id"] + " · " + fact["label"] + "=" + fact["value"] + "（" + BASIS_LABELS[fact["basis"]] + "）"
                                      for fact in facts(item)) or "仅为已引用来源材料，未提取可单独核实的登记事实")
            for item in data.get("verification_basis", {}).get("sources", []) if refs is None or item["evidence_id"] in refs]


def _source_html(data: dict, row: dict | None = None) -> str:
    notes = _source_notes(data, row)
    if not notes:
        return ""
    refs = set(_refs(row)) if row is not None else None
    links = ['<a href="' + html.escape(item["source_url"], quote=True) + '">' + html.escape(item["source_name"] + " [" + item["evidence_id"] + "]") + '</a>'
             for item in data["verification_basis"]["sources"] if item["source_url"] and (refs is None or item["evidence_id"] in refs)]
    return _list_html(notes) + ('<p class="source-note">原始来源链接：' + " · ".join(links) + '</p>' if links else "")


def _limitation_notes(data: dict) -> list[str]:
    return [str(item.get("reason", "未登记阻碍原因")) + ": "
            + " · ".join(str(item[key]) for key in ("scenario_id", "jurisdiction", "right_type", "candidate_id") if item.get(key))
            + ("；具体缺口：" + str(item["planning_gap"]) if item.get("planning_gap") else "")
            + "；" + _text(item.get("reasoning"))
            + ("；证据 [" + ", ".join(item["evidence_refs"]) + "]" if item.get("evidence_refs") else "")
            for item in data.get("publication", {}).get("limitations", [])]


def _resolve(root: Path, path: str, *, relative_root: Path | None = None) -> Path:
    candidate = Path(path).expanduser()
    resolved = (candidate if candidate.is_absolute() else (relative_root or root) / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise ValueError("REPORT_SOURCE_OUTSIDE_EVIDENCE_ROOT") from None
    return resolved


def _task_file_declarations(value: Any, root: Path, task_root: Path) -> Any:
    """Normalize only media declarations in a report-local copy of task inputs.

    Canonical files are task-relative; supplement files remain evidence-root
    relative. Both keep the same allowed boundary and exact frozen hashes.
    """
    if isinstance(value, list):
        return [_task_file_declarations(item, root, task_root) for item in value]
    if not isinstance(value, dict):
        return value
    role = " ".join(_text(value.get(key, "")) for key in ("role", "kind", "privacy", "purpose", "source_environment")).casefold()
    if value.get("private") is True or any(word in role for word in ("private", "login", "account", "debug")) or re.search(r"(?:^|[ _-])(mock|fixture|test)(?:$|[ _-])", role):
        return deepcopy(value)  # Same exclusions as the registered-file reader.
    result = {key: (deepcopy(item) if key.casefold() in ("private", "login", "account", "debug")
                    else _task_file_declarations(item, root, task_root)) for key, item in value.items()}
    for key, hash_key in (("path", "sha256"), ("local_path", "sha256"),
                          ("file_path", "sha256"), ("screenshot_path", "screenshot_sha256")):
        if isinstance(value.get(key), str) and value.get(hash_key) is not None:
            result[key] = str(_resolve(root, value[key], relative_root=task_root))
    if isinstance(value.get("source_document"), str) and value["source_document"].strip():
        result["source_document"] = str(_resolve(root, value["source_document"], relative_root=task_root))
    if isinstance(value.get("screenshots"), list) and isinstance(value.get("screenshot_hashes"), dict):
        result["screenshots"] = [str(_resolve(root, path, relative_root=task_root))
                                 if isinstance(path, str) else result["screenshots"][index]
                                 for index, path in enumerate(value["screenshots"])]
        result["screenshot_hashes"] = {str(_resolve(root, path, relative_root=task_root)): digest
                                       for path, digest in value["screenshot_hashes"].items()}
    return result


def _registered_files(root: Path, *objects: Any) -> dict[str, dict]:
    """Use frozen file declarations, never presentation-selected files or new hashes."""
    bindings: dict[str, dict] = {}
    referenced_documents: set[str] = set()
    def bind(path, digest, source_urls):
        if not isinstance(path, str) or not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            return
        key = str(_resolve(root, path))
        if key in bindings and bindings[key]["sha256"] != digest.lower():
            raise ValueError("REPORT_CONFLICTING_SOURCE_HASHES")
        record = bindings.setdefault(key, {"sha256": digest.lower(), "source_urls": []})
        for source_url in source_urls:
            if source_url and source_url not in record["source_urls"]:
                record["source_urls"].append(source_url)
    def visit(obj, inherited_urls=()):
        if isinstance(obj, list):
            for child in obj:
                visit(child, inherited_urls)
        elif isinstance(obj, dict):
            role = " ".join(_text(obj.get(key, "")) for key in ("role", "kind", "privacy", "purpose", "source_environment")).casefold()
            if obj.get("private") is True or any(word in role for word in ("private", "login", "account", "debug")) or re.search(r"(?:^|[ _-])(mock|fixture|test)(?:$|[ _-])", role):
                return
            source_urls = list(dict.fromkeys([*inherited_urls, *(_safe_url(obj.get(key)) for key in ("source_url", "url", "final_url", "requested_url"))]))
            for key, hash_key in (("path", "sha256"), ("local_path", "sha256"), ("file_path", "sha256"), ("screenshot_path", "screenshot_sha256")):
                bind(obj.get(key), obj.get(hash_key), source_urls)
            document = obj.get("source_document")
            own_file = any(isinstance(obj.get(key), str) and obj[key].strip()
                           for key in ("path", "local_path", "file_path"))
            document_digest = obj.get("source_document_sha256")
            if isinstance(document, str) and document.strip():
                if own_file:
                    # A derived image's hash belongs to the image, never its
                    # source PDF. Independent document declarations may follow
                    # this record later in the evidence list.
                    referenced_documents.add(str(_resolve(root, document)))
                elif document_digest is None:
                    document_digest = obj.get("sha256")  # Historical source-document-only record.
                if obj.get("source_document_sha256") is not None and (
                        not isinstance(document_digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", document_digest)):
                    raise ValueError("REPORT_SOURCE_DOCUMENT_HASH_INVALID")
                bind(document, document_digest, source_urls)
            if isinstance(obj.get("screenshots"), list) and isinstance(obj.get("screenshot_hashes"), dict):
                for path in obj["screenshots"]:
                    bind(path, obj["screenshot_hashes"].get(path), source_urls)
            for key, child in obj.items():
                if key.casefold() not in ("private", "login", "account", "debug"):
                    visit(child, source_urls)
    for obj in objects:
        visit(obj)
    if referenced_documents - bindings.keys():
        raise ValueError("REPORT_SOURCE_DOCUMENT_NOT_REGISTERED")
    return bindings


def _local_info(root: Path, out: Path, item: dict, *, bindings: dict[str, dict], image=False) -> dict:
    source = item.get("path") or item.get("source_document") or item.get("local_path") or item.get("file_path")
    if not source:
        raise ValueError("REPORT_SOURCE_PATH_MISSING")
    path = _resolve(root, str(source))
    expected = bindings.get(str(path))
    if not expected:
        raise ValueError("REPORT_SOURCE_NOT_REGISTERED: " + str(source))
    if not path.is_file():
        raise ValueError("REPORT_SOURCE_MISSING: " + str(source))
    content = path.read_bytes()
    digest = _sha(content)
    if digest != expected["sha256"] or (item.get("sha256") and str(item["sha256"]).lower() != expected["sha256"]):
        raise ValueError("REPORT_SOURCE_HASH_MISMATCH: " + str(source))
    source_url = _safe_url(item.get("source_url") or item.get("url"))
    if source_url and source_url not in expected["source_urls"]:
        raise ValueError("REPORT_SOURCE_URL_NOT_REGISTERED")
    source_url = source_url or next(iter(expected["source_urls"]), "")
    # Keep original AVIF bytes even on Python/platform MIME registries that
    # predate AVIF. The browser decodes the image; no conversion is performed.
    mime = "image/avif" if path.suffix.lower() == ".avif" else mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if image and mime == "image/avif":
        box_size = int.from_bytes(content[:4], "big")
        brands = [content[8:12], *(content[index:index + 4] for index in range(16, min(box_size, len(content)), 4))]
        if (len(content) < 16 or content[4:8] != b"ftyp" or not 16 <= box_size <= len(content)
                or box_size % 4 or not any(brand in (b"avif", b"avis") for brand in brands)):
            raise ValueError("REPORT_IMAGE_FORMAT: invalid AVIF header")
    if image and mime not in ("image/png", "image/jpeg", "image/webp", "image/gif", "image/avif"):
        raise ValueError("REPORT_IMAGE_FORMAT: " + mime)
    return {**item, "source_path": str(path), "path": "files/" + digest + path.suffix.lower(), "sha256": digest, "bytes": len(content), "mime_type": mime, "source_url": source_url}


def _normalize_blocks(blocks: list[dict], root: Path, out: Path, images: list[dict], linked_files: list[dict], bindings: dict[str, dict]) -> list[dict]:
    result = []
    for original in blocks:
        row = dict(original)
        kind = row.get("type")
        if kind == "figures":
            row["items"] = [_local_info(root, out, item, bindings=bindings, image=True) for item in row.get("items", [])]
            images.extend(row["items"])
        elif kind == "details":
            row["blocks"] = _normalize_blocks(row.get("blocks", []), root, out, images, linked_files, bindings)
        elif kind not in ("p", "list", "note", "cards"):
            raise ValueError("REPORT_BLOCK_TYPE: " + str(kind))
        if kind in ("p", "note"):
            row["html"] = _localize_html(row.get("html", ""), root, out, linked_files, bindings)
        elif kind == "list":
            row["items"] = [_localize_html(item, root, out, linked_files, bindings) for item in row.get("items", [])]
        elif kind == "cards":
            row["items"] = [{**item, "html": _localize_html(item.get("html", ""), root, out, linked_files, bindings)} for item in row.get("items", [])]
        result.append(row)
    return result


def _localize_html(value: str, root: Path, out: Path, linked_files: list[dict], bindings: dict[str, dict]) -> str:
    def replace(match):
        target = html.unescape(match.group(2))
        parsed = urlsplit(target)
        if parsed.scheme or target.startswith(("#", "//")):
            return match.group(0)
        source = _resolve(root, unquote(parsed.path))
        if not source.is_file():
            raise ValueError("REPORT_LOCAL_LINK_MISSING: " + target)
        item = _local_info(root, out, {"path": str(source)}, bindings=bindings)
        linked_files.append(item)
        return 'href="' + item["path"] + ('#' + parsed.fragment if parsed.fragment else '') + '"'
    return re.sub(r"href\s*=\s*([\"'])(.*?)\1", replace, str(value or ""), flags=re.I)



def _declared_images(record: Any, *, source_url: str = "", checked_at: str = "", blocked: bool = False) -> list[dict]:
    """Read only declared image bindings; never discover files from directories."""
    found = []
    if isinstance(record, list):
        for child in record:
            found.extend(_declared_images(child, source_url=source_url, checked_at=checked_at, blocked=blocked))
        return found
    if not isinstance(record, dict):
        return found
    role = " ".join(_text(record.get(key, "")) for key in ("role", "kind", "privacy", "purpose")).casefold()
    blocked = blocked or record.get("private") is True or any(word in role for word in ("private", "login", "account", "debug"))
    if blocked:
        return found
    source_url = _safe_url(record.get("source_url") or record.get("url") or record.get("final_url") or record.get("requested_url") or source_url)
    checked_at = record.get("checked_at") or record.get("collected_at") or checked_at
    for path_key, hash_key in (("path", "sha256"), ("source_document", "sha256"), ("local_path", "sha256"), ("file_path", "sha256"), ("screenshot_path", "screenshot_sha256")):
        path, digest = record.get(path_key), record.get(hash_key)
        if isinstance(path, str) and Path(path).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".avif") and isinstance(digest, str) and re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            found.append({"path": path, "sha256": digest.lower(), "source_url": source_url, "checked_at": checked_at, "label": record.get("label", ""), "role": record.get("role", "")})
            break
    screenshots, hashes = record.get("screenshots"), record.get("screenshot_hashes")
    if isinstance(screenshots, list) and isinstance(hashes, dict):
        for path in screenshots:
            if isinstance(path, str) and path in hashes:
                found.extend(_declared_images({"path": path, "sha256": hashes[path]}, source_url=source_url, checked_at=checked_at))
    for key, child in record.items():
        if isinstance(child, (dict, list)):
            found.extend(_declared_images(child, source_url=source_url, checked_at=checked_at, blocked=key.casefold() in ("private", "login", "account", "debug")))
    return found


def _automatic_visuals(rows: list[dict], registry: dict, root: Path, out: Path, bindings: dict[str, dict]) -> list[dict]:
    figures, seen = [], set()
    for identifier in _refs(rows):
        record = registry.get(identifier)
        if not record:
            continue
        for binding in _declared_images(record):
            figure = _local_info(root, out, binding, bindings=bindings, image=True)
            if figure["sha256"] in seen:
                continue
            seen.add(figure["sha256"])
            figure.update({"label": binding.get("label") or identifier + " · 图证原件", "alt": identifier + " 已引用证据原图", "caption": "本图来自主审已引用证据 " + identifier + "；具体支持和反对理由见逐项推论。自动展示不代表该图本身足以确认侵权。"})
            figures.append(figure)
    return figures


def _visual_row_key(row: dict) -> tuple:
    return tuple(row.get(key, "") for key in ("scenario_id", "jurisdiction", "right_type", "candidate_id"))


def _visual_eligible(row: dict) -> bool:
    return (bool(row.get("candidate_id")) and row.get("risk") in ("中", "高", "极高")
            and row.get("assessment_status", "assessed") == "assessed"
            and row.get("aggregation_included", True) and not row.get("out_of_scope")
            and not row.get("future_signal") and not row.get("signal_only")
            and _module_id(row) not in ("enforcement", "pending_application"))


def _visual_failed(record: Any) -> bool:
    """Execution receipts remain traceable, but are never substantive media."""
    if isinstance(record, list):
        return any(_visual_failed(item) for item in record)
    if not isinstance(record, dict):
        return False
    if record.get("status") in ("no_result", "failed", "access_limited", "needs_user_action"):
        return True
    if record.get("stop_reason") == "zero_results" or record.get("submission_state") in ("not_submitted", "unconfirmed"):
        return True
    return any(_visual_failed(value) for value in record.values() if isinstance(value, (dict, list)))


def _core_visuals(rows: list[dict], registry: dict, root: Path, out: Path,
                  bindings: dict[str, dict], failed_queries: set | None = None,
                  failed_runs: set | None = None, candidate_index: dict | None = None,
                  *, visual_policy_revision=LEGACY_VISUAL_POLICY_REVISION, task=None) -> tuple[list[dict], list[dict]]:
    """Select current-risk rights media, following only exact frozen PDF bindings."""
    sections, gaps, page_cache = [], [], {}
    def failed(record):
        return (_visual_failed(record) or record.get("source_run_id") in (failed_runs or set())
                or (not record.get("source_run_id") and record.get("query_id") in (failed_queries or set())))
    derivatives: dict[tuple, list[tuple[str, dict]]] = {}
    for identifier, record in registry.items():
        document, digest = record.get("source_document"), record.get("source_document_sha256")
        if document and isinstance(digest, str):
            derivatives.setdefault((str(_resolve(root, document)), digest.lower()), []).append((identifier, record))
    for row in rows:
        if not _visual_eligible(row):
            continue
        identity = {key: row.get(key, "") for key in ("candidate_id", "scenario_id", "scenario_sha256", "jurisdiction", "right_type")}
        candidate = (candidate_index or {}).get(row["candidate_id"], row)
        selected, comparisons, seen, roles = [], [], set(), set()
        gap_reasons = []
        comparison_hashes = {item.get("artifact_sha256") for item in row.get("comparison", {}).get("visual_coverage", {}).get("product_views", [])
                             if isinstance(item, dict) and item.get("artifact_sha256")}
        structural_right = row.get("right_type") in ("patent", "utility_model", "utility_patent", "design", "unregistered_design")

        def document_matches(record):
            # A cited prior-art or family document is not the candidate's own
            # right merely because it was used somewhere in the explanation.
            if task and task.get("workflow_correction_revision"):
                from decision_workflow import candidate_document_entries
                return any(item.get("evidence_id") == record.get("evidence_id") for item in
                    candidate_document_entries(candidate, supplement={"evidence": [record]}, task=task))
            actual, expected = record.get("publication_number"), candidate.get("publication_number")
            if not actual or not expected:
                return False
            if row.get("jurisdiction") == "US":
                from record_candidate_lead import publication_number
                try:
                    actual, expected = publication_number(actual), publication_number(expected)
                except ValueError:
                    return False
            return (actual == expected and record.get("jurisdiction") == row.get("jurisdiction")
                    and record.get("right_type") == row.get("right_type"))

        def append_record(identifier, record, *, parent_id="", document=None, comparison=False):
            if failed(record):
                return
            role = record.get("visual_role", "product_comparison" if comparison else "")
            if document:
                page = record.get("page_number")
                if type(page) is not int or page < 1 or role not in ("document_identity", "patent_claims", "patent_drawings"):
                    gap_reasons.append("原文页图未绑定准确页码或用途：" + identifier)
                    return
                if any(record.get(key) and record[key] != row.get(key) for key in ("jurisdiction", "right_type")):
                    gap_reasons.append("原文页图范围与候选不一致：" + identifier)
                    return
                if visual_policy_revision == VISUAL_POLICY_REVISION:
                    from pdf_page_evidence import validate_page_binding
                    try:
                        validate_page_binding(record, document, root, cache=page_cache)
                    except ValueError as exc:
                        gap_reasons.append("原文页图定位校验失败：" + identifier + " · " + str(exc))
                        return
            for binding in _declared_images(record):
                if comparison and (comparison_hashes or not structural_right) and binding["sha256"] not in comparison_hashes:
                    continue
                figure = _local_info(root, out, binding, bindings=bindings, image=True)
                media_key = (figure["sha256"], comparison)
                if media_key in seen:
                    continue
                seen.add(media_key)
                title = row.get("title") or row["candidate_id"]
                page_label = (" · 原文第 " + str(record["page_number"]) + " 页") if document else ""
                figure.update({**identity, "risk": row["risk"], "evidence_id": identifier,
                    "source_evidence_id": parent_id or identifier, "visual_role": role,
                    "page_number": record.get("page_number"), "figure_labels": record.get("figure_labels", []),
                    "label": title + page_label + (" · 产品对照" if comparison else ""),
                    "alt": title + page_label,
                    "caption": record.get("visual_reason") or ("用于已审候选的产品对照；不单独证明权利或侵权。" if comparison else "准确权利记录／原文图证；其支持与限制见该候选的逐项推论。"),
                    "checked_at": record.get("source_checked_at") or figure.get("checked_at", "")})
                if document:
                    figure.update(source_document_sha256=document["sha256"], source_document_path=document["path"],
                                  source_document_source_path=document["source_path"])
                (comparisons if comparison else selected).append(figure)
                if not comparison:
                    roles.add(role)

        for identifier in _refs(row):
            record = registry.get(identifier, {})
            if not record or failed(record):
                continue
            payload = record.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}
            source = record.get("path") or record.get("source_document") or record.get("local_path") or record.get("file_path")
            if source and Path(source).suffix.lower() == ".pdf":
                if not document_matches(record):
                    gap_reasons.append("引用文献未精确绑定当前候选公开号与范围：" + identifier)
                    continue
                document = _local_info(root, out, record, bindings=bindings)
                derived = derivatives.get((document["source_path"], document["sha256"]), [])
                # A newly registered description of the identical original page
                # may add its verified locator without rewriting the old entry.
                described_hashes = {item.get("sha256") for _, item in derived
                    if type(item.get("page_number")) is int and item["page_number"] > 0
                    and item.get("visual_role") in ("document_identity", "patent_claims", "patent_drawings")
                    and (visual_policy_revision != VISUAL_POLICY_REVISION or item.get("page_verification"))}
                for image_id, image_record in derived:
                    if image_record.get("sha256") in described_hashes and (
                            type(image_record.get("page_number")) is not int or image_record["page_number"] < 1
                            or image_record.get("visual_role") not in ("document_identity", "patent_claims", "patent_drawings")
                            or (visual_policy_revision == VISUAL_POLICY_REVISION and not image_record.get("page_verification"))):
                        continue
                    append_record(image_id, image_record, parent_id=identifier, document=document)
            elif (record.get("source_document") and record.get("source_document_sha256")
                  and Path(record["source_document"]).suffix.lower() == ".pdf"):
                parents = [item for item in registry.values() if item.get("path")
                    and str(_resolve(root, item["path"])) == str(_resolve(root, record["source_document"]))
                    and item.get("sha256") == record["source_document_sha256"] and document_matches(item)]
                if not parents:
                    gap_reasons.append("页图源文献未精确绑定当前候选：" + identifier)
                    continue
                document = _local_info(root, out, {**parents[0], "path": record["source_document"], "sha256": record["source_document_sha256"]}, bindings=bindings)
                append_record(identifier, record, parent_id=parents[0].get("evidence_id", ""), document=document)
            elif (payload.get("candidate_id") == row.get("candidate_id")
                  and payload.get("jurisdiction") == row.get("jurisdiction")
                  and payload.get("right_type") == row.get("right_type")
                  and payload.get("official_verification", {}).get("identity_match") is True):
                append_record(identifier, {**record, "visual_role": "registry_record"})
            elif (record.get("visual_role") in ("registry_record", "copyright_work", "trade_dress_view")
                  and record.get("candidate_id") == row.get("candidate_id")
                  and record.get("jurisdiction") == row.get("jurisdiction")
                  and record.get("right_type") == row.get("right_type")):
                append_record(identifier, record)
            elif (record.get("visual_role") == "product_comparison"
                  or any(item.get("role") in ("main", "product_view", "product_comparison")
                         or item["sha256"] in comparison_hashes for item in _declared_images(record))):
                append_record(identifier, record, comparison=True)
        required = ({"document_identity", "patent_claims", "patent_drawings"} if row.get("right_type") in ("patent", "utility_model", "utility_patent")
                    else {"patent_drawings"} if row.get("right_type") in ("design", "unregistered_design")
                    else {"copyright_work"} if row.get("right_type") == "copyright"
                    else {"trade_dress_view"} if row.get("right_type") == "trade_dress" else {"registry_record"})
        missing = sorted(required - roles)
        if missing or gap_reasons:
            gaps.append({**identity, "risk": row["risk"], "missing_roles": missing,
                "reason": "核心图证尚不完整；缺图不改变已有风险预判。", "details": list(dict.fromkeys(gap_reasons))})
        # Product images have a place only beside an actual selected rights image.
        figures = selected + (comparisons if selected else [])
        title = (row.get("scenario_title") or row.get("scenario_id") or "当前评价情景") + " · " + (row.get("title") or row["candidate_id"]) + " · " + row["risk"] + "风险"
        blocks = ([{"type": "figures", "cols": 2, "items": figures}] if figures else [])
        if missing or gap_reasons:
            blocks.append({"type": "note", "html": html.escape("核心图证待补：" + "、".join([VISUAL_ROLE_LABELS[role] for role in missing] + list(dict.fromkeys(gap_reasons))) + "。已知风险及原文引用继续保留。")})
        sections.append({"id": "core-" + _digest(identity)[:16], "title": title, **identity, "risk": row["risk"], "blocks": blocks})
    return sections, gaps


def _section_figures(sections: list[dict]) -> list[dict]:
    def visit(blocks):
        found = []
        for block in blocks:
            if block.get("type") == "figures":
                found.extend(block.get("items", []))
            elif block.get("type") == "details":
                found.extend(visit(block.get("blocks", [])))
        return found
    return [item for section in sections for item in visit(section.get("blocks", []))]


def _row_visuals(data: dict, row: dict) -> list[dict]:
    return [item for item in _section_figures(data.get("sections", []))
            if item.get("evidence_id") and _visual_row_key(item) == _visual_row_key(row)] if data.get("visual_policy_revision") else []

def _canonical(task_dir, task, evidence, assessment, candidates, plan):
    from annotate_materiality import load_materiality_ledger
    from assessment_estimate import compute_assessment
    task_dir = Path(task.get("outputs", {}).get("assessment_input_dir") or task_dir)
    reviews = assessment.get("review", {}).get("input_reviews", {})
    ledger = load_materiality_ledger(task_dir, task["task_id"], task=task)
    root = assessment.get("review", {}).get("evidence_root") or task_dir
    expected = compute_assessment(task, evidence, candidates, plan, ledger, reviews.get("first", {}), reviews.get("second"), reviews.get("adjudication"), supplement=assessment.get("supplement"), evidence_root=root, generated_at=assessment.get("generated_at"), task_dir=task_dir)
    from necessary_completion import restore_publication
    restore_publication(task, evidence, candidates, plan, ledger, expected, assessment, task_dir=task_dir, evidence_root=root)
    if expected != assessment:
        raise ValueError("ASSESSMENT_STALE_OR_TAMPERED")


def build_report_data(task_dir: Path, task: dict, evidence: dict, assessment: dict, candidates: dict, journal: dict, plan: dict, *, output_dir: Path | None = None, report_content: dict | None = None, verify_assessment: bool = True, visual_policy_revision: str | None = VISUAL_POLICY_REVISION) -> dict:
    task_dir = Path(task_dir).resolve()
    out = Path(output_dir or task_dir).resolve()
    if assessment.get("assessment_policy") != POLICY:
        raise ValueError("REPORT_POLICY_MISMATCH")
    _require_safe({"task": task, "evidence": evidence, "assessment": assessment, "candidates": candidates, "journal": journal, "plan": plan, "report_content": report_content})
    if verify_assessment:
        _canonical(task_dir, task, evidence, assessment, candidates, plan)
    content = report_content or {}
    if visual_policy_revision not in (None, LEGACY_VISUAL_POLICY_REVISION, VISUAL_POLICY_REVISION):
        raise ValueError("REPORT_VISUAL_POLICY_UNSUPPORTED")
    root = Path(assessment.get("review", {}).get("evidence_root") or task_dir).resolve()
    if content.get("evidence_root") and Path(content["evidence_root"]).resolve() != root:
        raise ValueError("REPORT_EVIDENCE_ROOT_OVERRIDE")
    media_task, media_evidence = task, evidence
    if task.get("workflow_correction_revision") == "workflow-correction-v1":
        from assessment_estimate import task_artifact_root
        source = task.get("outputs", {}).get("assessment_input_dir") or task_dir
        task_root = task_artifact_root(task, root, source)
        media_task = _task_file_declarations(task, root, task_root)
        media_evidence = _task_file_declarations(evidence, root, task_root)
    bindings = _registered_files(root, {"source_url": task.get("request", {}).get("url", ""), "images": media_task.get("images", []), "main_visual": media_task.get("product", {}).get("main_visual", {})}, media_evidence, assessment.get("supplement", {}))
    rows = assessment.get("assessments", [])
    scenario_mode = task.get("decision_workflow_revision") == "scenario-triage-v1"
    from assessment_estimate import partial_evidence_enabled, PARTIAL_EVIDENCE_REVISION
    partial = partial_evidence_enabled(task) and (assessment.get("status") == "incomplete"
        or assessment.get("overall", {}).get("business_completion") == "incomplete")
    for row in rows:
        if not row.get("out_of_scope") and row.get("risk_aggregation_included", row.get("aggregation_included", True)) and _module_id(row) != "enforcement":
            if row.get("risk") not in RISKS or _confidence(row) not in CONFIDENCES:
                raise ValueError("REPORT_INVALID_FINAL_RATING")
    overall = assessment.get("overall", {})
    stage = (recall_integrity_enabled(task) and assessment.get("status") == "incomplete"
             and overall.get("risk") is None)
    if (overall.get("risk") not in RISKS and not stage) or overall.get("confidence") not in CONFIDENCES:
        raise ValueError("REPORT_INVALID_OVERALL_RATING")
    product = dict(task.get("product", {}))
    if product.get("actual_asin") and product.get("asin") and product["actual_asin"] != product["asin"]:
        raise ValueError("REPORT_PRODUCT_ASIN_CONFLICT")
    product["asin"] = product.get("actual_asin") or product.get("asin") or product.get("requested_asin", "")
    product["source_url"] = _safe_url(product.get("source_url") or task.get("request", {}).get("url"))
    product["jurisdictions"] = task.get("target_jurisdictions", [])
    display_facts = content.get("product_facts", {})
    if not isinstance(display_facts, dict):
        raise ValueError("REPORT_PRODUCT_FACTS_TYPE")
    for key, value in display_facts.items():
        if key != "main_visual" and (key not in product or value != product[key]):
            raise ValueError("REPORT_PRODUCT_FACT_OVERRIDE: " + str(key))
    for field, expected in (("lead", overall.get("report_lead", "")), ("summary", overall.get("report_summary", "")), ("scope", product.get("report_scope") or product.get("intended_use", ""))):
        if field in content and content[field] != expected:
            raise ValueError("REPORT_DECISION_TEXT_OVERRIDE: " + field)
    if "main_visual" in product:
        product["main_visual"] = media_task["product"]["main_visual"]
    images: list[dict] = []
    linked_files: list[dict] = []
    declared_mains = _declared_images(product.get("main_visual", {}), source_url=product["source_url"])
    for item in media_task.get("images", []):
        if isinstance(item, dict) and item.get("role") == "main":
            declared_mains.extend(_declared_images(item, source_url=product["source_url"]))
    main = display_facts.get("main_visual") or product.get("main_visual")
    if isinstance(main, dict):
        selected = _local_info(root, out, main, bindings=bindings, image=True)
        identities = {(str(_resolve(root, item["path"])), item["sha256"]) for item in declared_mains}
        if (selected["source_path"], selected["sha256"]) not in identities:
            raise ValueError("REPORT_MAIN_IMAGE_IDENTITY_MISMATCH")
    if isinstance(main, dict):
        product["main_visual"] = selected
        images.append(product["main_visual"])
    else:
        # Trust the declared main role and hash, never a guessed folder filename.
        if declared_mains:
            if len({item["sha256"] for item in declared_mains}) > 1:
                raise ValueError("REPORT_MULTIPLE_MAIN_IMAGES")
            product["main_visual"] = _local_info(root, out, {**declared_mains[0], "alt": product.get("title", "产品主图"), "label": "产品主图", "caption": "来自 task.images 中已绑定的 main 原图；具体评价范围见产品事实。"}, bindings=bindings, image=True)
            images.append(product["main_visual"])
    explicit_images: list[dict] = []
    sections = [{**section, "blocks": _normalize_blocks(section.get("blocks", []), root, out, explicit_images if visual_policy_revision else images, linked_files, bindings)} for section in content.get("sections", [])]
    signal_rows = []
    for field, module in (("future_applications", "pending_application"), ("enforcement_signals", "enforcement")):
        for signal in assessment.get(field, []):
            signal_rows.append({**signal, "module_id": module, "right_type": signal.get("right_type") or field, "aggregation_included": False, "signal_only": True, "risk": None})
    registry = _registry(media_evidence, assessment.get("supplement", {}),
                         registered_only=visual_policy_revision == VISUAL_POLICY_REVISION)
    visual_gaps = []
    if visual_policy_revision:
        latest_runs = {item.get("query_id"): item for item in evidence.get("source_runs", []) if item.get("query_id")}
        failed_queries = {key for key, item in latest_runs.items() if _visual_failed(item)}
        failed_runs = {item.get("run_id") for item in evidence.get("source_runs", []) if item.get("run_id") and _visual_failed(item)}
        candidate_index = {item["candidate_id"]: item for group in candidates.values() if isinstance(group, list)
                           for item in group if isinstance(item, dict) and item.get("candidate_id")}
        core_sections, visual_gaps = _core_visuals(rows, registry, root, out, bindings, failed_queries, failed_runs, candidate_index,
            visual_policy_revision=visual_policy_revision, task=task)
        core_images = _section_figures(core_sections)
        eligible = {item["sha256"] for item in core_images}
        if any(item["sha256"] not in eligible for item in explicit_images):
            raise ValueError("REPORT_EXPLICIT_VISUAL_NOT_ELIGIBLE")
        # Explicit prose is retained; explicit figures cannot replace the policy's
        # required media or make an empty override hide a high-risk document.
        def without_figures(blocks):
            return [{**block, **({"blocks": without_figures(block.get("blocks", []))} if block.get("type") == "details" else {})}
                    for block in blocks if block.get("type") != "figures"]
        sections = core_sections + [{**section, "blocks": without_figures(section["blocks"])} for section in sections
                                    if without_figures(section["blocks"])]
        images.extend(core_images)
        for item in core_images:
            if item.get("source_document_source_path"):
                linked_files.append(_local_info(root, out, {"path": item["source_document_source_path"],
                    "sha256": item["source_document_sha256"]}, bindings=bindings))
    elif report_content is None:
        selected = _automatic_visuals(rows + signal_rows, registry, root, out, bindings)
        if selected:
            sections = [{"id": "reviewed-evidence", "title": "已引用且校验通过的图证原件", "blocks": [{"type": "figures", "cols": 2, "items": selected}]}]
            images.extend(selected)
    evidence_index = []
    visual_ids = [item["evidence_id"] for item in _section_figures(sections) if item.get("evidence_id")] if visual_policy_revision else []
    from completion_policy import evidence_delivery_enabled
    limitation_refs = _refs(assessment.get("publication", {}).get("limitations", [])) if evidence_delivery_enabled(task) else []
    for identifier in list(dict.fromkeys(_refs(rows + signal_rows) + visual_ids + limitation_refs)):
        record = registry.get(identifier, {"evidence_id": identifier})
        role = " ".join(_text(record.get(key, "")) for key in ("role", "kind", "privacy", "purpose")).casefold()
        if record.get("private") is True or any(word in role for word in ("private", "login", "account", "debug")):
            evidence_index.append({"evidence_id": identifier, "source_note": "私密、登录或调试角色资料未纳入报告图证与附件。"})
            continue
        path = record.get("path") or record.get("source_document") or record.get("local_path") or record.get("file_path")
        if path:
            record = _local_info(root, out, record, bindings=bindings)
        evidence_index.append(record)
    modules = []
    caps = assessment.get("module_confidence_caps", {})
    if "module_confidence_caps" in content and content["module_confidence_caps"] != caps:
        raise ValueError("REPORT_MODULE_CONFIDENCE_OVERRIDE")
    for key, label in MODULE_LABELS.items():
        related = [row for row in rows + signal_rows if _module_id(row) == key
                   and (not scenario_mode or row.get("scenario_id") == task["primary_scenario_id"])]
        eligible = [row for row in related if _is_scored(row)]
        risk = max((row["risk"] for row in eligible), key=RISKS.index, default=None)
        driver = [row for row in eligible if row["risk"] == risk]
        cap = caps.get(key, {})
        confidence = min((_confidence(row) for row in driver), key=CONFIDENCES.index, default=None)
        if confidence and cap.get("confidence") in CONFIDENCES:
            confidence = min((confidence, cap["confidence"]), key=CONFIDENCES.index)
        modules.append({"confidence_reasoning": cap.get("reasoning", "按该模块最高风险候选的证据链评价；不等于全范围检索完成。"), "module_id": key, "label": label, "risk": risk, "confidence": confidence, "assessment_count": len(eligible), "rows": related})
        if recall_integrity_enabled(task):
            modules[-1]["pending_count"] = sum(row.get("assessment_status") == "pending" for row in related)
            if scenario_mode:
                primary = next(item for item in assessment["scenario_summaries"] if item["primary"])
                pending = {("row", row.get("right_type"), row.get("candidate_id", ""))
                           for row in related if row.get("assessment_status") == "pending"}
                for queue in primary["completion"]["queues"].values():
                    pending.update(("row", item["right_type"], item.get("candidate_id", "")) for item in queue
                                   if RIGHT_MODULES.get(item.get("right_type")) == key)
                pending.update(("scope", scope["jurisdiction"], scope["right_type"])
                    for scope in assessment["coverage"]["scopes"] if scope.get("scenario_id") == task["primary_scenario_id"]
                    and RIGHT_MODULES.get(scope["right_type"]) == key and scope.get("gaps"))
                modules[-1]["pending_count"] = len(pending)
            if risk and modules[-1]["pending_count"] and not partial:
                modules[-1]["label"] = label + '（已评局部）'
                modules[-1]["confidence_reasoning"] = ('仅为已评局部风险；仍有 ' + str(modules[-1]["pending_count"])
                    + ' 项待评范围或候选，不是该模块的最终等级。' + modules[-1]["confidence_reasoning"])
        if partial:
            modules[-1]["confidence"] = "低"
            modules[-1]["risk_basis"] = ("evidence_supported" if risk in {"中", "高", "极高"} else "policy_fallback") if risk else None
            modules[-1]["confidence_reasoning"] = "查询未完成，模块置信度统一为低；当前等级不改变原查询、审阅及核验完成状态。" + _risk_basis_note(modules[-1])
    confidence_basis = _unique_notes(
        overall.get("confidence_reasoning"),
        [(row.get("title") or row.get("candidate_id") or row.get("scope", "主导风险事项")) + "：" + row["confidence_reasoning"] for row in _overall_drivers(overall, rows) if row.get("confidence_reasoning")],
        overall.get("coverage_confidence_reasoning"))
    if not confidence_basis:
        confidence_basis = ["总置信度取决定总体风险的证据链及覆盖置信度上限；具体假设见逐项推论。"]
    inputs = {"task": task, "evidence": evidence, "assessment": assessment, "candidates": candidates, "journal": journal, "search_plan": plan}
    result = {"report_schema": REPORT_SCHEMA, "assessment_policy": POLICY, "task_id": task["task_id"], "generated_at": assessment.get("generated_at", ""), "section_order": SECTION_ORDER, "product": product, "overall": overall, "assessments": rows, "supplemental_rows": signal_rows, "modules": modules, "coverage": assessment.get("coverage", {}), "future_applications": assessment.get("future_applications", []), "enforcement_signals": assessment.get("enforcement_signals", []), "lead": _localize_html(overall.get("report_lead", ""), root, out, linked_files, bindings), "summary": _localize_html(overall.get("report_summary", ""), root, out, linked_files, bindings), "scope": product.get("report_scope") or product.get("intended_use", ""), "sections": sections, "coverage_notes": _unique_notes(content.get("coverage_notes", []), assessment.get("coverage", {}).get("notes", [])), "overall_confidence_basis": confidence_basis, "evidence_cutoff": content.get("evidence_cutoff") or "见各引用证据的核查时间", "change_note": content.get("change_note") or "报告生成时间不代表全部证据重新检索；评级按所列来源时点和现行策略生成。", "review_method": content.get("review_method", ""), "review_binding": content.get("review_binding", {}), "footer": content.get("footer", "本报告为指定产品、销售行为、法域及证据时点下的风险预判。风险等级与证据置信度分别表达；范围限制及核查条件随结论列示。"), "visual_evidence": images, "evidence_index": evidence_index, "linked_files": linked_files, "presentation_source": content, "presentation_explicit": report_content is not None, "trace": {"source_task_dir": str(task_dir), "input_digests": {key: _digest(value) for key, value in inputs.items()}, "assessment_digest": assessment.get("review", {}).get("evidence_digest", ""), "report_content_digest": _digest(content), "template_css_sha256": _sha(CSS_PATH.read_bytes())}, "offline_policy": {"images_embedded_as_data_uri": True, "remote_resources": False, "scripts": False, "visual_limit": None}}
    if partial_evidence_enabled(task):
        result["assessment_revision"] = PARTIAL_EVIDENCE_REVISION
    if partial:
        from report_query_trace import build_query_trace
        result["query_trace"] = build_query_trace(task, evidence, assessment, candidates, plan,
            source_task_dir=task.get("outputs", {}).get("assessment_input_dir") or task_dir)
        result["coverage_notes"].append(_partial_warning(result))
        result["overall_confidence_basis"] = _unique_notes(["查询未完成，全部评级置信度统一为低。"], result["overall_confidence_basis"])
    if scenario_mode:
        result["decision_workflow_revision"] = task["decision_workflow_revision"]
        result["scenario_summaries"] = assessment["scenario_summaries"]
        result["legacy_coverage_confidence_disclosure"] = assessment.get("legacy_coverage_confidence_disclosure", [])
    if visual_policy_revision:
        result["visual_policy_revision"] = visual_policy_revision
        result["visual_gaps"] = visual_gaps
    from necessary_completion import enabled as completion_enabled
    if completion_enabled(task):
        publication = assessment.get("publication")
        if not isinstance(publication, dict):
            raise ValueError("PUBLICATION_CONTEXT_REQUIRED")
        result["completion_policy_revision"] = task["completion_policy_revision"]
        result["publication"] = deepcopy(publication)
        if assessment.get("coverage", {}).get("triage", {}).get("counts", {}).get("selected") == 0:
            result["coverage_notes"].append("当前没有入选候选；核验队列为空不表示全部候选已经全面核验，也不构成低风险依据。")
        if publication.get("mode") == "stage":
            result["coverage_notes"].append("阶段报告停止原因：" + publication["stop_reason"])
        # Present provenance metadata in the existing explanation column; keep
        # the source notes verbatim in coverage and the frozen evidence.
        for raw, label in (("kind=provenance_document", "资料类型：来源文件"),
                           ("document_type=published_license_terms", "文档类型：公开许可条款")):
            result["coverage_notes"] = [note.replace(raw, label) for note in result["coverage_notes"]]
        from completion_policy import evidence_delivery_enabled
        if evidence_delivery_enabled(task):
            # This is the prospective artifact view, not the assessment's
            # readiness decision. Public builders validate it in a private
            # staging directory before any completed report is delivered.
            if publication.get("mode") in {"evidence", "final"}:
                result["publication"]["delivery_status"] = "completed"
            result["verification_basis"] = build_verification_basis(task, evidence, assessment, candidates, plan)
            result["coverage_notes"].append(_delivery_text(result))
            result["coverage_notes"].append(result["verification_basis"]["note"])
            if publication.get("mode") == "evidence" and not partial:
                result["coverage_notes"].append("本报告已完成来源取证交付；官方核验、检索覆盖和风险评估仍按原状态逐项披露。")
    if task.get("workflow_correction_revision") == "workflow-correction-v1":
        result["workflow_correction_revision"] = task["workflow_correction_revision"]
        result = _compact_report_data(result)
    return result


def _display_rows(data: dict) -> list[dict]:
    return data["assessments"] + data.get("supplemental_rows", [])


def _compact_report_data(data: dict) -> dict:
    """Intern complete decisions once; preserve every queue membership and fact."""
    data = deepcopy(data)
    records = {}
    def reference(record):
        identifier = "DEC-" + _digest(record)
        if identifier in records and records[identifier] != record:
            raise ValueError("REPORT_DECISION_IDENTITY_COLLISION")
        records[identifier] = record
        return {"decision_ref": identifier}
    triage = data.get("coverage", {}).get("triage", {})
    if isinstance(triage.get("records"), list):
        triage["records"] = [reference(item) for item in triage["records"]]
    for obj in [*data.get("coverage", {}).get("scopes", []),
                *(item["completion"] for item in data.get("scenario_summaries", []))]:
        if isinstance(obj.get("queues"), dict):
            obj["queues"] = {key: [reference(item) for item in value] for key, value in obj["queues"].items()}
    data["decision_records"] = records
    data["report_schema"] = "IPR-EVIDENCE-ESTIMATE-REPORT/2.0"
    data["report_model_revision"] = COMPACT_REPORT_REVISION
    return data


def _queue_record(data: dict, item: dict) -> dict:
    if "decision_ref" not in item:
        return item
    record = data.get("decision_records", {}).get(item["decision_ref"])
    if not isinstance(record, dict):
        raise ValueError("REPORT_DECISION_REFERENCE_MISSING")
    return record


def _scope_display(scope: dict, data: dict) -> dict:
    if data.get("report_model_revision") != COMPACT_REPORT_REVISION:
        return scope
    result = {key: scope[key] for key in ("scenario_id", "jurisdiction", "right_type", "status",
        "retrieval_status", "triage_status", "verification_status", "gaps", "unresolved_facts", "work_reasons")
        if key in scope} | {"queue_counts": {key: len(value) for key, value in scope.get("queues", {}).items()},
                           "完整记录": "report-data.json：coverage.scopes、decision_records"}
    if data.get("verification_basis"):
        result["delivery_status"] = data["publication"].get("delivery_status", "unknown")
        result["unverified_facts"] = list(dict.fromkeys(label for item in data["verification_basis"]["assessments"]
            if all(item.get(key, "") == scope.get(key, "") for key in ("scenario_id", "jurisdiction", "right_type"))
            for label in item["unverified_facts"]))
        result["delivery_limitations"] = [item for item in data["publication"].get("limitations", [])
            if all(item.get(key, "") == scope.get(key, "") for key in ("scenario_id", "jurisdiction", "right_type"))]
    return result


def _scope_queue_notes(scope: dict, data: dict) -> list[str]:
    notes = []
    for name, queue in scope.get("queues", {}).items():
        for item in queue:
            row = _queue_record(data, item)
            annotation = row.get("annotation") or {}
            detail = (annotation.get("missing_information") or row.get("pending_reasoning")
                      or row.get("reopen_reasons") or annotation.get("reason") or row.get("reason") or "待完成相应审阅")
            notes.append(name + " · " + str(row.get("candidate_id") or row.get("right_type") or "范围") + "：" + _text(detail))
    return notes


def _pill(risk: str | None) -> str:
    return '<span class="risk-pill risk-pill-' + RISK_CLASS.get(risk, "neutral") + '">' + html.escape((risk + "风险") if risk else "范围说明") + '</span>'


def _list_html(value: Any, *, diagnostics: bool = False) -> str:
    items = value if isinstance(value, list) else ([value] if value else [])
    def content(item):
        text = _text(item)
        escaped = html.escape(text)
        # Machine-readable diagnostic keys are code, not prose. The existing
        # template's code rule wraps long identifiers without dropping data.
        return '<code>' + escaped + '</code>' if diagnostics and re.match(r'^[A-Z][A-Z0-9_]+(?::|$)', text) else escaped
    return '<ul>' + ''.join('<li>' + content(item) + '</li>' for item in items) + '</ul>' if items else '<p class="meta">未另列；以该项明确范围与推论为准。</p>'


def _refs_html(row: dict, data: dict) -> str:
    index = {item.get("evidence_id"): item for item in data["evidence_index"]}
    links = []
    for identifier in list(dict.fromkeys(_refs(row) + [item["evidence_id"] for item in _row_visuals(data, row)])):
        item = index.get(identifier, {})
        url = quote(item["path"], safe="/:#") if item.get("path") else _safe_url(item.get("source_url") or item.get("url"))
        links.append('<a href="' + html.escape(url, quote=True) + '">' + html.escape(identifier) + '</a>' if url else html.escape(identifier))
    return '<div class="refs">' + '<br>'.join(links) + '</div>'


def _reason_html(row: dict) -> str:
    result = ''.join('<div><span class="reason-label">' + label + '</span>' + _list_html(_reason_value(row, key)) + '</div>' for key, label in EXPLANATION_FIELDS)
    if row.get("decision_workflow_revision") == "scenario-triage-v1" and row.get("comparison", {}).get("claims"):
        result += '<details class="fold"><summary>实施方案 × 权利要求：独立分组比较</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(json.dumps(row["comparison"], ensure_ascii=False, sort_keys=True, indent=2)) + '</pre></details>'
    return result


def _figure(item: dict, out: Path) -> str:
    local_path = _resolve(out, item["path"])
    payload = (local_path if local_path.is_file() else Path(item["source_path"])).read_bytes()
    if _sha(payload) != item["sha256"]:
        raise ValueError("REPORT_IMAGE_CHANGED: " + item["path"])
    local = html.escape(quote(item["path"], safe="/:"), quote=True)
    source = '<a href="' + html.escape(item["source_url"], quote=True) + '">来源页面／档案</a> · ' if item.get("source_url") else ''
    if item.get("source_document_path"):
        source += '<a href="' + html.escape(quote(item["source_document_path"], safe="/:"), quote=True) + '#page=' + str(item["page_number"]) + '">完整原文／本页</a> · '
    return '<figure class="visual-card ' + html.escape(item.get("class", ""), quote=True) + '"><a href="' + local + '"><img alt="' + html.escape(item.get("alt") or item.get("label", "证据原图"), quote=True) + '" data-source-path="' + html.escape(item["path"], quote=True) + '" data-sha256="' + item["sha256"] + '" src="data:' + item["mime_type"] + ';base64,' + base64.b64encode(payload).decode() + '"></a><figcaption class="visual-copy"><h4>' + html.escape(item.get("label", "证据原图")) + '</h4><p>' + html.escape(item.get("caption", "")) + '</p><div class="source-note">' + html.escape(item.get("checked_at", "")) + ' · SHA-256 ' + item["sha256"][:12] + '<br>' + source + '<a href="' + local + '">查看原图</a></div></figcaption></figure>'


def _blocks_html(blocks: list[dict], out: Path) -> str:
    result = []
    for block in blocks:
        kind = block["type"]
        if kind in ("p", "note"):
            text = '<p>' + _inline(block.get("html", "")) + '</p>'
            if kind == "note":
                text = '<div class="review-note ' + html.escape(block.get("tone", ""), quote=True) + '">' + text + '</div>'
        elif kind == "list":
            text = '<ul>' + ''.join('<li>' + _inline(item) + '</li>' for item in block.get("items", [])) + '</ul>'
        elif kind == "figures":
            cols = min(3, max(1, int(block.get("cols", 2))))
            text = '<div class="visual-grid cols-' + str(cols) + '">' + ''.join(_figure(item, out) for item in block["items"]) + '</div>'
        elif kind == "cards":
            text = '<div class="module-grid">' + ''.join('<article class="module"><span class="badge">' + html.escape(item.get("label", "")) + '</span><h3>' + html.escape(item.get("title", "")) + '</h3><p>' + _inline(item.get("html", "")) + '</p></article>' for item in block.get("items", [])) + '</div>'
        else:
            text = '<details class="fold"><summary>' + html.escape(block.get("title", "展开说明")) + '</summary><div class="fold-content">' + _blocks_html(block.get("blocks", []), out) + '</div></details>'
        result.append('<div class="review-block">' + text + '</div>')
    return ''.join(result)



def _human_priority(row: dict) -> int:
    ranks = []
    for check in row.get('human_checks', []):
        if not isinstance(check, dict):
            continue
        match = re.fullmatch(r'P?([123])', str(check.get('priority', '')).strip(), re.I)
        if match:
            ranks.append(int(match.group(1)))
    return min(ranks, default=4)


def _gaps_html(data: dict) -> str:
    e = html.escape
    result = '<h2>人工核查与注意事项</h2><p class="meta">以下事项用于提高置信度及调整等级，不是拒绝输出当前评级的前提。</p>'
    if data["overall"].get("business_completion") == "incomplete":
        result = '<h2>人工核查与注意事项</h2><p class="meta">本报告保留已核实结果及未完成工作；证据不足的项目尚未定级，自动检索工作仍由 Agent 完成。</p>'
    if _partial_report(data):
        from report_query_trace import unfinished_notes
        result = '<h2>人工核查与注意事项</h2><p class="meta">本报告基于已取得信息评级；未确认中高风险的适用项按规则判低，不表示已排除侵权风险，也不改变未完成状态。</p>'
        result += '<h3>未完成的查询及核验步骤</h3>' + _query_notes_html(unfinished_notes(data["query_trace"]))
    checked = sorted((row for row in _display_rows(data) if not row.get('out_of_scope') and row.get('human_checks')), key=_human_priority)
    has_p1 = any(_human_priority(row) == 1 for row in checked)
    primary = [row for row in checked if _human_priority(row) == 1] if has_p1 else checked
    secondary = [row for row in checked if _human_priority(row) != 1] if has_p1 else []
    def item(row, opened=False):
        priority = _human_priority(row)
        title = row.get('title') or row.get('candidate_id') or row.get('right_type', '核查事项')
        label = ('P' + str(priority) + ' · ' if priority < 4 else '') + title
        return '<details class="fold"' + (' open' if opened else '') + '><summary>' + e(label) + '</summary><div class="fold-content">' + ''.join('<strong>' + label + '</strong>' + _list_html(row.get(key)) for key, label in EXPLANATION_FIELDS if key in ('human_checks', 'raise_if', 'lower_if')) + '</div></details>'
    for index, row in enumerate(primary):
        result += item(row, opened=has_p1 or index == 0)
    if secondary:
        result += '<details class="fold"><summary>其他候选的条件性核查 · ' + str(len(secondary)) + ' 项</summary><div class="fold-content">' + ''.join(item(row) for row in secondary) + '</div></details>'
    for row in _display_rows(data):
        if row.get('out_of_scope'):
            result += '<div class="gap"><strong>' + e(row.get('title') or row.get('scope', '未纳入范围')) + '</strong><p>' + e(row.get('scope_reasoning', row.get('reasoning', '未纳入本次评价。'))) + '</p></div>'
    if not checked:
        result += '<p class="meta">未另列人工核查事项；评价前提与范围仍以各项推论为准。</p>'
    return result

def render_html(data: dict, output_dir: Path) -> str:
    e = html.escape
    product, overall = data["product"], data["overall"]
    def facts(items):
        return '<div class="facts">' + ''.join('<div class="fact"><span>' + e(key) + '</span><div>' + val + '</div></div>' for key, val in items) + '</div>'
    product_body = '<div class="product-layout"><div class="gallery single">' + (_figure(product["main_visual"], output_dir) if product.get("main_visual") else '<p class="empty">未附产品主图；按已列文字与证据范围评价。</p>') + '</div><div class="product-copy"><span class="badge">评价对象与使用前提</span><h2>' + e(product.get("title", "产品知识产权风险预判")) + '</h2>' + facts([("ASIN", e(product.get("asin", ""))), ("法域", e(_text(product.get("jurisdictions", [])))), ("品牌", e(_text(product.get("brand", "")))), ("变体", e(_text(product.get("variant", "")))), ("评估前提", e(_text(data.get("scope", "")))), ("商品链接", '<a href="' + e(product["source_url"], quote=True) + '">来源商品页面</a>')]) + '</div></div>'
    if data.get("verification_basis"):
        product_body += '<div class="review-note"><strong>' + e(_delivery_text(data)) + '</strong><p>' + e(data["verification_basis"]["note"]) + '</p></div>'
    if _partial_report(data):
        product_body = '<div class="gap"><strong>' + e(_partial_warning(data)) + '</strong><p>' + e(_risk_basis_note(overall)) + '</p></div>' + product_body
    risk_text = _report_risk_text(data)
    decision = '<div class="decision-head"><div><h2>当前风险预判</h2><p class="meta">基于现有证据的主审判断 · 置信度独立评价</p></div><div class="risk-seal risk-seal-' + RISK_CLASS.get(overall["risk"], "not_assessable") + '"><small>总体风险</small><b>' + (overall["risk"] or '尚未定级') + '</b><small>置信度 ' + overall["confidence"] + '</small></div></div><div class="decision"><strong>' + _inline(data.get("lead") or (risk_text + '／' + overall["confidence"] + '置信度')) + '</strong>' + _list_html(overall.get("reasons", [])) + _inline(data.get("summary", "")) + '</div><div class="grid"><div class="metric"><span>评级策略</span><b>五级风险预判</b><small>' + POLICY + '</small></div><div class="metric"><span>当前总评</span><b>' + risk_text + '</b><small>主审确认的最高适用风险</small></div><div class="metric"><span>判断把握</span><b>' + overall["confidence"] + '置信度</b><small>关键证据链及覆盖边界决定</small></div><div class="metric"><span>纳入评价</span><b>' + str(sum(_is_scored(row) for row in data["assessments"])) + ' 项</b><small>文献数不等于独立有效权利数</small></div></div>'
    if not data.get("scenario_summaries") and overall.get("business_completion") == "incomplete" and overall.get("known_scoped_risk"):
        decision += '<p class="scope-line">已评范围最高风险：' + e(overall["known_scoped_risk"]) + '；仅适用于下列已评对象，不代表整项排查完成。</p>'
    decision += _scenario_html(data)
    decision += '<div class="review-note"><strong>总体置信度依据</strong>' + _list_html(data['overall_confidence_basis']) + '</div><p class="source-note">证据截止：' + e(_text(data['evidence_cutoff'])) + ' · 本版生成：' + e(data['generated_at']) + '</p><p class="scope-line">' + e(_text(data['change_note'])) + '</p>'
    coverage = '<h2>查询与候选覆盖</h2><p class="meta">覆盖缺口单独列示；查询失败不自动提高风险，有限零结果不等于全面排除。</p>' + _list_html(data.get("coverage_notes"), diagnostics="business_completion" in overall)
    if _partial_report(data):
        coverage += _query_trace_html(data)
    if data.get("verification_basis"):
        coverage += '<h3>尚未官方核验的事项及阻碍</h3>' + _list_html(_limitation_notes(data), diagnostics=True)
    for scope in data["coverage"].get("scopes", []):
        coverage += '<details class="fold"><summary>' + e((str(scope["scenario_id"]) + ' · ' if scope.get("scenario_id") else '') + str(scope.get("jurisdiction", "")) + ' · ' + str(scope.get("right_type", "")) + ' · ' + str(scope.get("status", "范围覆盖记录"))) + '</summary><div class="fold-content"><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + e(json.dumps(_scope_display(scope, data), ensure_ascii=False, sort_keys=True, indent=2)) + '</pre>' + (_list_html(_scope_queue_notes(scope, data)) + '<a href="report-data.json">离线完整决定及查询台账</a>' if data.get("report_model_revision") else '') + '</div></details>'
    gaps = _gaps_html(data)
    modules = '<h2>七项知识产权模块</h2><div class="module-grid">'
    for module in data["modules"]:
        modules += '<article class="module"><div class="module-head"><h3>' + e(module["label"]) + '</h3>' + _pill(module["risk"]) + '</div><p class="meta">' + ('置信度 ' + module["confidence"] + ' · ' + str(module["assessment_count"]) + ' 项评价' if module["risk"] else '待完成 · 尚未定级' if module.get("pending_count") else '补充信号，不计法律总风险' if module["module_id"] == 'enforcement' else '未纳入本次评价或没有适用评价对象') + '</p>'
        modules += '<p class="scope-line">' + e(module["confidence_reasoning"]) + '</p>'
        drivers = [row for row in module['rows'] if _is_scored(row) and row['risk'] == module['risk']]
        if drivers:
            driver_names = [row.get('title') or row.get('candidate_id') or row.get('scope', '评价对象') for row in drivers]
            names = '、'.join(driver_names[:3]) + ('等 ' + str(len(driver_names)) + ' 项' if len(driver_names) > 3 else '')
            modules += '<p><strong>主要驱动：</strong>' + e(names) + '</p>'
            if len(drivers) == 1:
                summary = _reason_value(drivers[0], 'reasoning') or ''
                modules += '<p>' + e(summary[:180] + ('…' if len(summary) > 180 else '')) + '</p>'
            else:
                modules += '<p class="meta">以上为该模块最高适用风险；其他候选的排除数量不稀释其等级。</p>'
        elif module['rows']:
            modules += '<p>' + e(_text(module['rows'][0].get('scope_reasoning') or module['rows'][0].get('reasoning', ''))[:160]) + '</p>'
        modules += '<p><a href="#candidates">查看该模块逐项依据与调整条件</a></p>'
        modules += '</article>'
    modules += '</div>'
    board_images = _section_figures(data["sections"]) if data.get("visual_policy_revision") else data["visual_evidence"]
    visual = '<h2>重点视觉证据</h2><p class="meta">' + str(len(board_images)) + ' 处图证展示，' + str(len({item["sha256"] for item in board_images})) + ' 个唯一图源；均嵌入留存图片字节，点击原图可查看完整分辨率。</p>' if data.get("visual_policy_revision") else '<h2>重点视觉证据</h2><p class="meta">' + str(len(board_images)) + ' 处图证展示，' + str(len({item["sha256"] for item in board_images})) + ' 个唯一图源；均嵌入原始字节，点击原图可查看完整分辨率。</p>'
    if data.get("visual_policy_revision"):
        visual += '<p class="meta">仅展示中、高、极高当前候选的实质图证，按评价情景分组；检索过程、零结果和受阻记录仍在候选追溯中保留。</p>'
    for section in data["sections"]:
        visual += '<div class="review-group" id="visual-' + e(str(section.get("id", "evidence")), quote=True) + '"><h3>' + e(section.get("title", "证据说明")) + '</h3>' + _blocks_html(section["blocks"], output_dir) + '</div>'
    if not data["sections"]:
        visual += ('<p class="empty">本轮没有已定级为中、高、极高的当前候选；不在此展示低风险、待评或检索过程图片。完整候选、原文与缺口仍保留在追溯中，不代表没有风险。</p>' if data.get("visual_policy_revision") else '<p class="empty">已引用证据中尚未取得同时具备本地原图路径、SHA-256 绑定及可验证原文件的适用图证；不能用缺图推断没有风险。已有原文引用与缺口保留在候选追溯中。</p>')
    candidate = '<h2>候选追溯与逐项推论</h2><div class="table-wrap" role="region" aria-label="逐项风险判断，可横向滚动" tabindex="0"><table class="candidate-table"><thead><tr><th>候选／评价对象</th><th>风险／置信度</th><th>当前推论与调整条件</th><th>证据引用</th></tr></thead><tbody>'
    for i, row in enumerate(_display_rows(data)):
        label = row.get("title") or row.get("candidate_id") or row.get("scope", "评价对象")
        candidate += '<tr data-assessment-index="' + str(i) + '"><td><strong>' + e(label) + '</strong>' + ('<p class="scope-line">' + e(row.get("scenario_title") or row["scenario_id"]) + '</p>' if row.get("scenario_id") else '') + '<p>' + e(str(row.get("jurisdiction", "")) + ' · ' + str(row.get("right_type", ""))) + '</p><p class="scope-line">' + e(row.get("scope", "")) + '</p></td><td>' + (_pill(row.get("risk")) if _is_scored(row) else '<span class="badge">' + _unscored_text(row) + '</span>') + ('<p>置信度 ' + e(_confidence(row)) + '</p>' if _is_scored(row) else '') + '</td><td>' + _reason_html(row) + ('<h4>事实依据与未核验项</h4>' + _list_html(_basis_notes(data, row)) if data.get("verification_basis") else '') + '</td><td>' + _refs_html(row, data) + (_source_html(data, row) if data.get("verification_basis") else '') + '</td></tr>'
        if _partial_report(data) and _is_scored(row):
            candidate += '<tr><td colspan="4"><p class="scope-line">' + e(_risk_basis_note(row)) + ('审阅／核验工作状态仍为未完成。' if row.get("assessment_status") == "pending" else '') + '</p></td></tr>'
    candidate += '</tbody></table></div>'
    trace = '<h2>可复现数据绑定</h2><p>本版采用 ' + POLICY + '。重新定级基于已列证据与主审论证；策略变化不表示新增事实或新查得权利。</p>' + facts([(key, '<code>' + e(value) + '</code>') for key, value in sorted(data["trace"]["input_digests"].items())]) + '<p>' + e(data.get("review_method", "")) + '</p><p><a href="report-data.json">统一报告数据</a> · <a href="report-manifest.json">图证与产物校验清单</a> · <a href="report-findings.csv">逐项 CSV</a></p>'
    if data.get("verification_basis"):
        trace += '<h3>取证来源与原始时点</h3>' + _source_html(data)
    panels = [product_body, decision, coverage, gaps, modules, visual, candidate, trace]
    nav = ''.join('<a href="#' + key + '">' + label + '</a>' for key, label in zip(SECTION_ORDER, SECTION_LABELS))
    sections = ''.join('<section id="' + key + '" class="panel' + (' trace' if key == 'trace' else '') + '">' + text + '</section>' for key, text in zip(SECTION_ORDER, panels))
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; script-src \'none\'; base-uri \'none\'; form-action \'none\'"><title>知识产权风险预判 · ' + e(product.get("asin", "")) + '</title><style>' + CSS_PATH.read_text() + '</style></head><body><div class="shell"><aside class="side"><div class="brand">LC IPR Screening</div><small>离线证据报告 · ' + e(data["task_id"]) + '<br>' + e(data["generated_at"]) + '</small><nav>' + nav + '</nav></aside><main class="main"><div class="wrap"><header class="header"><div><h1>知识产权风险筛查报告</h1><div class="meta">' + e(product.get("title", "")) + '</div></div><span class="badge">' + risk_text + '<br>' + overall["confidence"] + '置信度</span></header>' + sections + '<footer class="report-footer">' + e(data["footer"]) + '</footer></div></main></div></body></html>'


def _blocks_md(blocks: list[dict]) -> str:
    result = []
    for block in blocks:
        kind = block["type"]
        if kind in ("p", "note"):
            result.append(_inline(block.get("html"), True))
        elif kind == "list":
            result.append('\n'.join('- ' + _inline(item, True) for item in block.get("items", [])))
        elif kind == "figures":
            for item in block["items"]:
                result.append('![' + item.get("alt", item.get("label", "证据")) + '](' + quote(item["path"], safe="/:") + ')\n\n' + item.get("label", "") + '：' + item.get("caption", "") + '\n\nSHA-256：' + item["sha256"] + (' · [来源](' + item["source_url"] + ')' if item.get("source_url") else ''))
        elif kind == "cards":
            result.extend('**' + item.get("label", "") + ' · ' + item.get("title", "") + '**\n\n' + _inline(item.get("html"), True) for item in block.get("items", []))
        else:
            result.append('**' + block.get("title", "详细说明") + '**\n\n' + _blocks_md(block.get("blocks", [])))
    return '\n\n'.join(result)


def render_markdown(data: dict) -> str:
    overall = data["overall"]
    lines = ['# 知识产权风险筛查报告', '**' + _report_risk_text(data) + '／' + overall["confidence"] + '置信度**', '## 产品快照', _text(data["product"].get("title")), 'ASIN：' + data["product"].get("asin", ""), _text(data.get("scope", ""))]
    if _partial_report(data):
        lines[2:2] = [_partial_warning(data), _risk_basis_note(overall)]
    if data.get("verification_basis"):
        lines.extend([_delivery_text(data), data["verification_basis"]["note"]])
    if not data.get("scenario_summaries") and overall.get("business_completion") == "incomplete" and overall.get("known_scoped_risk"):
        lines.append('已评范围最高风险：' + overall["known_scoped_risk"] + '；不代表整项排查完成。')
    for scenario in data.get("scenario_summaries", []):
        lines.extend(['### ' + scenario["title"], _scenario_summary_text(scenario, data.get("coverage", {}).get("triage", {}).get("counts")),
                      '\n'.join('- ' + assumption for assumption in scenario["assumptions"])])
    main = data["product"].get("main_visual")
    if main:
        lines.append(_blocks_md([{"type": "figures", "items": [main]}]))
    scopes = data["coverage"].get("scopes", [])
    scope_text = '```json\n' + json.dumps([_scope_display(scope, data) for scope in scopes], ensure_ascii=False, sort_keys=True, indent=2) + '\n```'
    if data.get("report_model_revision"):
        scope_text += '\n\n' + '\n'.join('- ' + note for scope in scopes for note in _scope_queue_notes(scope, data))
        scope_text += '\n\n[离线完整决定及查询台账](report-data.json)'
    lines.extend(['## 筛查结论', _inline(data.get("lead"), True), '\n'.join('- ' + _text(reason) for reason in overall.get("reasons", [])), _inline(data.get("summary"), True), '评级策略：' + POLICY, '**总体置信度依据**：' + _text(data['overall_confidence_basis']), '证据截止：' + _text(data['evidence_cutoff']) + '；本版生成：' + data['generated_at'], _text(data['change_note']), '## 覆盖情况', _text(data.get("coverage_notes")), scope_text, '## 人工核查与注意事项', '人工核查及升降级条件随逐项推论列示；未纳入范围事项不赋予法律风险等级。'])
    if _partial_report(data):
        from report_query_trace import query_notes, unfinished_notes
        query_lines = ['### 逐维查询事实与单项结论', data['query_trace']['note']]
        for dimension in data['query_trace']['dimensions']:
            query_lines.append('#### ' + html.escape(_query_dimension_label(dimension)))
            for index in dimension['query_indices']:
                query_lines.append('\n'.join('- ' + html.escape(note) for note in query_notes(data['query_trace']['queries'][index])))
            for row in dimension['conclusions']:
                query_lines.append('单项结论：' + html.escape(_text(row.get('title') or row.get('candidate_id')) + ' · ' + (_text(row.get('risk')) + '风险' if row.get('risk') and not row.get('out_of_scope') else '未纳入本次风险评价') + '；' + _risk_basis_note(row) + '；' + _text(_reason_value(row, 'reasoning') or row.get('pending_reasoning'))))
        position = lines.index('## 人工核查与注意事项')
        lines[position:position] = query_lines
        lines.extend(['### 未完成的查询及核验步骤', '\n'.join('- ' + html.escape(note) for note in unfinished_notes(data['query_trace']))])
    if data.get("verification_basis"):
        lines.append('尚未官方核验事项及阻碍：' + _text(_limitation_notes(data)))
    for row in _display_rows(data):
        if row.get("out_of_scope"):
            lines.append('- ' + _text(row.get("title")) + '：' + _text(row.get("scope_reasoning")))
    lines.append('## 七项模块')
    for module in data["modules"]:
        lines.append('- **' + module["label"] + '**：' + (module["risk"] + '风险／' + module["confidence"] + '置信度' if module["risk"] else '待完成 · 尚未定级' if module.get("pending_count") else '补充注意事项，不计法律总风险' if module["module_id"] == 'enforcement' else '未纳入本次评价或无适用对象') + '。' + module['confidence_reasoning'])
    lines.append('## 视觉证据')
    if not data['sections']:
        lines.append('本轮没有已定级为中、高、极高的当前候选；不在此展示低风险、待评或检索过程图片。完整候选、原文与缺口仍保留在追溯中，不代表没有风险。' if data.get('visual_policy_revision') else '已引用证据中尚未取得同时具备本地原图路径、SHA-256 绑定及可验证原文件的适用图证；缺图不能用于推断没有风险，已有原文引用仍在候选追溯中。')
    for section in data["sections"]:
        lines.extend(['### ' + section.get("title", "证据说明"), _blocks_md(section["blocks"])])
    lines.append('## 候选追溯与逐项推论')
    for row in _display_rows(data):
        lines.extend(['### ' + (row.get("title") or row.get("candidate_id") or row.get("right_type", "范围")), ('**' + row["risk"] + '风险／' + _confidence(row) + '置信度**') if _is_scored(row) else _unscored_text(row), '法域／范围：' + str(row.get("jurisdiction", "")) + ' · ' + str(row.get("scope", ""))])
        if _partial_report(data) and _is_scored(row):
            lines.append(_risk_basis_note(row) + ('审阅／核验工作状态仍为未完成。' if row.get('assessment_status') == 'pending' else ''))
        if row.get("scenario_id"):
            lines.append('情景：' + str(row.get("scenario_title") or row["scenario_id"]))
            if row.get("comparison", {}).get("claims"):
                lines.append('实施方案 × 权利要求（不跨组拼接排除理由）：\n\n```json\n' + json.dumps(row["comparison"], ensure_ascii=False, sort_keys=True, indent=2) + '\n```')
        for key, label in EXPLANATION_FIELDS:
            lines.append('**' + label + '**：' + (_text(_reason_value(row, key)) or '未另列；以该项范围与推论为准。'))
        evidence_index = {item.get('evidence_id'): item for item in data['evidence_index']}
        references = []
        for identifier in list(dict.fromkeys(_refs(row) + [item["evidence_id"] for item in _row_visuals(data, row)])):
            item = evidence_index.get(identifier, {})
            target = item.get('path') or item.get('source_url')
            references.append('[' + identifier + '](' + quote(target, safe='/:#?=&') + ')' if target else identifier)
        lines.append('证据引用：' + '；'.join(references))
        if data.get("verification_basis"):
            lines.extend(['事实依据与未核验项：\n\n' + '\n'.join('- ' + note for note in _basis_notes(data, row)),
                          '取证来源：\n\n' + '\n'.join('- ' + note for note in _source_notes(data, row))])
    lines.extend(['## 数据绑定', '本版评级变化来自评价策略和主审推论调整；不代表新增证据。', '```json\n' + json.dumps(data["trace"], ensure_ascii=False, sort_keys=True, indent=2) + '\n```', data["footer"]])
    return '\n\n'.join(line for line in lines if line) + '\n'


def render_findings_csv(data: dict) -> str:
    stream = io.StringIO(newline='')
    fields = [*CSV_FIELDS, *(["scenario_id", "scenario_sha256", "conditional", "business_completion", "retrieval_status", "triage_status", "verification_status", "assessment_status", "assessment_completion", "comparison"] if data.get("scenario_summaries") else [])]
    if data.get("visual_policy_revision"):
        fields.extend(["visual_evidence_refs", "visual_sources", "visual_gaps"])
    if data.get("verification_basis"):
        fields.extend(["delivery_mode", "delivery_status", "delivery_limitations", "verification_basis", "unverified_facts", "source_disclosures"])
    if _partial_report(data):
        fields.extend(["risk_basis", "risk_aggregation_included", "query_id", "run_id", "provider", "operation", "search_dimension", "search_language", "plan_entry_sha256", "scenario_bindings", "planned_query", "actual_query", "actual_query_basis", "query_status", "latest_status", "has_prior_findings", "query_status_label", "submission_state", "source_checked_at", "total_hits", "retrieved_hits", "reported_total", "reviewed_hits", "pages_retrieved", "completeness", "coverage_complete", "count_contradiction", "truncated", "unfinished_step_count", "effective_search_count", "work_id", "work_state", "work_reason", "query_facts", "query_sources"])
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    overall = data["overall"]
    driver_rows = _overall_drivers(overall, data["assessments"])
    total = {"row_type": "overall", "title": "总体风险预判" if overall.get("risk") else "来源取证报告 · 整项尚未定级" if data.get("verification_basis") and data.get("publication", {}).get("mode") == "evidence" else "阶段性报告 · 整项尚未定级", "risk": overall["risk"], "confidence": overall["confidence"], "reasoning": _text(overall.get("reasons")), "aggregation_included": overall.get("risk") in RISKS}
    for key, _ in EXPLANATION_FIELDS:
        if key != 'reasoning':
            total[key] = '\n'.join((row.get('title') or row.get('candidate_id', '决定总评的事项')) + '：' + _text(_reason_value(row, key)) for row in driver_rows)
    total['confidence_reasoning'] = _text(data['overall_confidence_basis'])
    total['evidence_refs'] = ';'.join(_refs(driver_rows))
    values = [total]
    if _partial_report(data):
        from report_query_trace import query_notes
        total.update(risk_basis=overall.get('risk_basis'), **{key: data['query_trace']['summary'][key] for key in ('unfinished_step_count', 'effective_search_count')})
        total['assumptions'] = _unique_notes(total.get('assumptions'), _partial_warning(data), _risk_basis_note(overall))
        for query in data['query_trace']['queries']:
            for attempt in query['attempts'] or [{}]:
                values.append({**query, **attempt, 'row_type': 'query_attempt' if attempt else 'query_plan',
                    'query_status': attempt.get('status', query['status']), 'source_checked_at': attempt.get('checked_at', ''),
                    'query_status_label': query['status_label'],
                    'query_facts': query_notes({**query, 'attempts': [attempt] if attempt else []}),
                    'query_sources': attempt.get('sources', []), 'aggregation_included': False})
        for work in data['query_trace']['unfinished_work']:
            values.append({**work, 'row_type': 'unfinished_work', 'work_state': work['status'],
                'work_reason': work.get('reason') or work.get('reasoning'), 'aggregation_included': False})
    if data.get("scenario_summaries"):
        primary = next(item for item in data["scenario_summaries"] if item["scenario_id"] == overall["scenario_id"])
        total.update(scenario_id=overall["scenario_id"], scenario_sha256=overall["scenario_sha256"],
            business_completion=overall["business_completion"], assessment_status=overall["assessment_status"],
            assessment_completion=primary["completion"]["assessment"], retrieval_status=primary["completion"]["retrieval"],
            triage_status=primary["completion"]["triage"], verification_status=primary["completion"]["verification"])
        for scenario in data["scenario_summaries"]:
            completion = scenario["completion"]
            values.append({"row_type": "scenario", "title": scenario["title"], "scenario_id": scenario["scenario_id"],
                "scenario_sha256": scenario["scenario_sha256"], "conditional": scenario["conditional"], "risk": scenario["risk"],
                "confidence": scenario["confidence"], "aggregation_included": scenario["primary"] and scenario["risk"] in RISKS,
                "risk_basis": scenario.get("risk_basis"),
                "reasoning": _scenario_summary_text(scenario, data.get("coverage", {}).get("triage", {}).get("counts")), "assumptions": scenario["assumptions"],
                "business_completion": completion["status"], "retrieval_status": completion["retrieval"],
                "triage_status": completion["triage"], "verification_status": completion["verification"],
                "assessment_status": scenario["assessment_status"], "assessment_completion": completion["assessment"]})
    if not data.get("scenario_summaries") and overall.get("business_completion") == "incomplete" and overall.get("known_scoped_risk"):
        values.append({"row_type": "known_scoped_risk", "title": "已评范围最高风险（非整项结论）",
                       "risk": overall["known_scoped_risk"], "confidence": overall.get("known_scoped_confidence"),
                       "aggregation_included": False, "evidence_refs": _refs(driver_rows)})
    for module in data['modules']:
        drivers = [row for row in module['rows'] if _is_scored(row) and row['risk'] == module['risk']]
        values.append({'row_type': 'module', 'title': module['label'], 'scope': module['confidence_reasoning'], 'risk': module['risk'] or '', 'confidence': module['confidence'] or '', 'risk_basis': module.get('risk_basis'), 'aggregation_included': False, **{key: '\n'.join((row.get('title') or row.get('candidate_id', '评价对象')) + '：' + _text(_reason_value(row, key)) for row in drivers) for key, _ in EXPLANATION_FIELDS}, 'evidence_refs': _refs(drivers)})
    for row in _display_rows(data):
        values.append({**row, 'row_type': 'out_of_scope' if row.get('out_of_scope') else 'assessment' if _is_scored(row) else 'pending' if row.get('assessment_status') == 'pending' else 'supplemental', 'risk': row.get('risk') if _is_scored(row) else '', 'confidence': _confidence(row) if _is_scored(row) else '', 'evidence_refs': _refs(row)})
    evidence_index = {item.get('evidence_id'): item for item in data['evidence_index']}
    for row in values:
        if data.get("verification_basis"):
            row.update(delivery_mode=data["publication"].get("mode"), delivery_status=data["publication"].get("delivery_status"),
                       delivery_limitations=_limitation_notes(data),
                       verification_basis=_basis_notes(data, row), unverified_facts=_basis_item(data, row).get("unverified_facts", []),
                       source_disclosures=_source_notes(data, row))
        if data.get("visual_policy_revision"):
            media = _row_visuals(data, row)
            row["visual_evidence_refs"] = list(dict.fromkeys(item["evidence_id"] for item in media))
            row["visual_sources"] = list(dict.fromkeys(item["path"] for item in media))
            row["visual_gaps"] = [item for item in data.get("visual_gaps", []) if _visual_row_key(item) == _visual_row_key(row)]
        references = row.get('evidence_refs', [])
        if isinstance(references, str):
            references = references.split(';')
        row['evidence_sources'] = ';'.join(str(evidence_index.get(identifier, {}).get('path') or evidence_index.get(identifier, {}).get('source_url') or identifier) for identifier in references)
        safe = {}
        for key in fields:
            value = _text(_reason_value(row, key))
            safe[key] = "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        writer.writerow(safe)
    return stream.getvalue()


def bundle_bytes(data: dict, output_dir: Path) -> dict[str, bytes]:
    return {'report-data.json': _json(data), 'report.html': render_html(data, Path(output_dir)).encode(), 'report.md': render_markdown(data).encode(), 'report-findings.csv': render_findings_csv(data).encode('utf-8-sig')}


def _manifest(data: dict, payloads: dict[str, bytes]) -> dict:
    manifest = {'report_schema': REPORT_SCHEMA, 'assessment_policy': POLICY, 'task_id': data['task_id'], 'generated_at': data['generated_at'], 'overall': {'risk': data['overall']['risk'], 'confidence': data['overall']['confidence']}, 'section_order': SECTION_ORDER, 'input_digests': data['trace']['input_digests'], 'report_content_digest': data['trace']['report_content_digest'], 'template_css_sha256': data['trace']['template_css_sha256'], 'artifacts': {name: {'path': name, 'bytes': len(payload), 'sha256': _sha(payload)} for name, payload in payloads.items()}, 'images': data['visual_evidence'], 'evidence_index': data['evidence_index'], 'linked_files': data['linked_files'], 'offline_policy': data['offline_policy']}
    if data.get('assessment_revision'):
        manifest['assessment_revision'] = data['assessment_revision']
    if _partial_report(data):
        manifest['overall']['risk_basis'] = data['overall'].get('risk_basis')
        manifest['query_trace'] = {'path': 'report-data.json', 'json_pointer': '/query_trace',
            'sha256': _digest(data['query_trace']), **data['query_trace']['summary']}
    if "business_completion" in data["overall"]:
        manifest["business_completion"] = data["overall"]["business_completion"]
        manifest["overall"]["known_scoped_risk"] = data["overall"].get("known_scoped_risk")
    if data.get("scenario_summaries"):
        manifest["decision_workflow_revision"] = data["decision_workflow_revision"]
        manifest["scenario_summaries"] = data["scenario_summaries"]
    if data.get("visual_policy_revision"):
        manifest["visual_policy_revision"] = data["visual_policy_revision"]
        manifest["visual_gaps"] = data.get("visual_gaps", [])
    if data.get("report_model_revision"):
        manifest["report_schema"] = data["report_schema"]
        manifest["report_model_revision"] = data["report_model_revision"]
        manifest["workflow_correction_revision"] = data["workflow_correction_revision"]
        manifest["scenario_summaries"] = deepcopy(data.get("scenario_summaries", []))
        for scenario in manifest["scenario_summaries"]:
            completion = scenario["completion"]
            completion["queue_counts"] = {key: len(value) for key, value in completion.pop("queues", {}).items()}
        manifest["decision_records"] = {"path": "report-data.json", "json_pointer": "/decision_records",
            "count": len(data["decision_records"]), "sha256": _digest(data["decision_records"])}
    if data.get("completion_policy_revision"):
        manifest["completion_policy_revision"] = data["completion_policy_revision"]
        manifest["publication"] = {"path": "report-data.json", "json_pointer": "/publication",
            "sha256": _digest(data["publication"])}
    if data.get("verification_basis"):
        manifest["delivery_mode"] = data["publication"].get("mode")
        manifest["delivery_status"] = data["publication"].get("delivery_status")
        manifest["delivery_limitations"] = deepcopy(data["publication"].get("limitations", []))
        manifest["verification_basis"] = {"path": "report-data.json", "json_pointer": "/verification_basis",
            "sha256": _digest(data["verification_basis"]), "fact_counts": data["verification_basis"]["fact_counts"],
            "source_evidence_refs": [item["evidence_id"] for item in data["verification_basis"]["sources"]]}
    manifest['content_digest'] = _digest(manifest)
    return manifest


def build_bundle(task_dir: Path, task: dict, evidence: dict, assessment: dict, candidates: dict, journal: dict, plan: dict, *, output_dir: Path | None = None, report_content: dict | None = None) -> tuple[dict, dict]:
    out = Path(output_dir or task_dir).resolve()
    data = build_report_data(Path(task_dir), task, evidence, assessment, candidates, journal, plan, output_dir=out, report_content=report_content)
    return _write_delivery_bundle(data, out, task_dir=task_dir, task=task, assessment=assessment)


def build_bundle_from_verified_context(context, *, task_dir, output_dir, journal=None, report_content=None):
    from assessment_estimate import VerifiedAssessmentContext
    if not isinstance(context, VerifiedAssessmentContext):
        raise ValueError("REPORT_VERIFIED_CONTEXT_REQUIRED")
    context.consume(task_dir=task_dir, output_dir=output_dir)
    inputs = context.inputs
    actual_journal = inputs["journal"]
    if journal is not None and journal != actual_journal:
        raise ValueError("REPORT_VERIFIED_JOURNAL_CHANGED")
    data = build_report_data(Path(task_dir), context.output_task, inputs["evidence"], context.assessment,
        inputs["candidates"], actual_journal, inputs["plan"], output_dir=Path(output_dir),
        report_content=report_content, verify_assessment=False)
    context.validate(task_dir=task_dir, output_dir=output_dir)
    return _write_delivery_bundle(data, Path(output_dir).resolve(), task_dir=task_dir,
        task=context.output_task, assessment=context.assessment)


def _write_delivery_bundle(data: dict, out: Path, *, task_dir: Path, task: dict, assessment: dict) -> tuple[dict, dict]:
    """v2 delivers only bytes which passed the same independent bundle validator.

    No persisted 'validation passed' flag is trusted. Standalone finalize keeps
    readiness only; standalone build and publish use this identical boundary.
    Legacy writes retain their original bytes and execution behavior.
    """
    from completion_policy import evidence_delivery_enabled
    if not evidence_delivery_enabled(task):
        return _write_bundle(data, out)
    assessment_path = out / "assessment.json"
    if assessment_path.is_file() and json.loads(assessment_path.read_text()) != assessment:
        raise ValueError("REPORT_ASSESSMENT_CHANGED_BEFORE_DELIVERY")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ipr-report-validation-", dir=out.parent) as temporary:
        stage = Path(temporary)
        atomic_write_json(stage / "assessment.json", assessment)
        atomic_write_json(stage / "task.json", task)
        result, manifest = _write_bundle(data, stage)
        errors = validate_run(Path(task_dir), task, output_dir=stage)
        if errors:
            raise ValueError("REPORT_DELIVERY_VALIDATION_FAILED: " + "; ".join(errors))
        # Publish the exact staged bytes, never reread source media after QA.
        # HTML is last so a new visible report cannot precede its attachments.
        files = list(_unique_file_records(data["visual_evidence"] + data["evidence_index"] + data["linked_files"]))
        names = ([name for name in ("assessment.json", "task.json") if not (out / name).exists()]
            + [item["path"] for item in files] + ["report-data.json", "report.md",
            "report-findings.csv", "report-manifest.json", "report.html"])
        for name in dict.fromkeys(names):
            path = _resolve(stage, name)
            target = _resolve(out, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target, path.read_bytes())
    return result, manifest


def _unique_file_records(items: list[dict], *, source=False):
    seen = set()
    for item in items:
        path = item.get("source_path" if source else "path")
        if not path:
            continue
        key = (str(Path(path).resolve()) if source else path, item["sha256"])
        if key not in seen:
            seen.add(key)
            yield item


def _write_bundle(data: dict, out: Path) -> tuple[dict, dict]:
    payloads = bundle_bytes(data, out)
    manifest = _manifest(data, payloads)
    _require_safe({'report_data': data, 'manifest': manifest}, payloads)
    out.mkdir(parents=True, exist_ok=True)
    for item in _unique_file_records(data['visual_evidence'] + data['evidence_index'] + data['linked_files'], source=True):
        payload = Path(item['source_path']).read_bytes()
        if _sha(payload) != item['sha256']:
            raise ValueError('REPORT_SOURCE_CHANGED: ' + item['source_path'])
        target = out / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, payload)
    for name, payload in payloads.items():
        atomic_write_bytes(out / name, payload)
    atomic_write_json(out / 'report-manifest.json', manifest)
    return data, manifest


def validate_run(task_dir: Path, task: dict, *, output_dir: Path | None = None) -> list[str]:
    """Recompute every rendition and source hash; engine revalidates frozen reviews."""
    task_dir, out = Path(task_dir).resolve(), Path(output_dir or task_dir).resolve()
    errors = []
    try:
        data = json.loads((out / 'report-data.json').read_text())
        manifest = json.loads((out / 'report-manifest.json').read_text())
        actual_rendered = {name: (out / name).read_bytes() for name in ('report.html', 'report.md', 'report-findings.csv') if (out / name).is_file()}
        security = _security_errors({'task': task, 'report_data': data, 'manifest': manifest}, actual_rendered)
        if security:
            return security
        if data.get('assessment_policy') != POLICY or data.get('task_id') != task.get('task_id'):
            errors.append('REPORT_IDENTITY_MISMATCH')
        if data['trace']['input_digests']['task'] != _digest(task):
            errors.append('REPORT_TASK_STALE')
        if data['trace']['template_css_sha256'] != _sha(CSS_PATH.read_bytes()):
            errors.append('REPORT_TEMPLATE_CHANGED')
        for item in _unique_file_records(data['visual_evidence'] + data['linked_files'] + data['evidence_index']):
            path = _resolve(out, item['path'])
            if not path.is_file() or _sha(path.read_bytes()) != item['sha256']:
                errors.append('REPORT_SOURCE_CHANGED: ' + item['path'])
        payloads = bundle_bytes(data, out)
        for name, expected in payloads.items():
            if not (out / name).is_file() or (out / name).read_bytes() != expected:
                errors.append('REPORT_ARTIFACT_MISMATCH: ' + name)
        if manifest != _manifest(data, payloads):
            errors.append('REPORT_MANIFEST_MISMATCH')
        source = Path(task.get('outputs', {}).get('assessment_input_dir') or data['trace'].get('source_task_dir') or task_dir)
        if source.resolve() != Path(task.get('outputs', {}).get('assessment_input_dir') or task_dir).resolve():
            return list(dict.fromkeys(errors + ['REPORT_CANONICAL_SOURCE_MISMATCH']))
        inputs = {}
        for key, filename in [('evidence', 'evidence.json'), ('assessment', 'assessment.json'), ('candidates', 'normalized-candidates.json'), ('journal', 'browser-candidate-journal.json'), ('search_plan', 'search-plan.json')]:
            # A re-evaluation keeps its new assessment in the output bundle;
            # source/assessment.json may deliberately remain a historical result.
            path = (out if key == 'assessment' else source) / filename
            if not path.exists() and key == 'journal':
                value = {'schema_version': '1.0', 'task_id': task['task_id'], 'entries': []}
            elif not path.exists():
                errors.append('REPORT_INPUT_MISSING: ' + filename)
                continue
            else:
                value = json.loads(path.read_text())
            inputs[key] = value
            if _digest(value) != data['trace']['input_digests'][key]:
                errors.append('REPORT_INPUT_STALE: ' + filename)
        security = _security_errors({'task': task, **inputs})
        if security:
            return security
        if len(inputs) == 5:
            from assessment_estimate import validate_assessment
            assessment_errors = validate_assessment(task_dir, task, inputs['assessment'])
            errors.extend(assessment_errors)
            if not assessment_errors:
                # validate_assessment already performed the full canonical review
                # recomputation. Rebuild the view once from exactly those inputs.
                expected_data = build_report_data(Path(data['trace']['source_task_dir']), task, inputs['evidence'], inputs['assessment'], inputs['candidates'], inputs['journal'], inputs['search_plan'], output_dir=out, report_content=data.get('presentation_source', {}) if data.get('presentation_explicit') else None, verify_assessment=False, visual_policy_revision=data.get('visual_policy_revision'))
                if data != expected_data:
                    errors.append('REPORT_DATA_RECOMPUTE_MISMATCH')
        expected_ids = [re.search(r'<section id="([^"]+)"', part).group(1) for part in re.findall(r'<section id="[^"]+"[^>]*>', payloads['report.html'].decode())]
        if expected_ids != SECTION_ORDER:
            errors.append('REPORT_SECTIONS_MISMATCH')
        if '<script' in payloads['report.html'].decode().lower():
            errors.append('REPORT_SCRIPT_FORBIDDEN')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append('REPORT_VALIDATION_ERROR: ' + str(exc))
    return list(dict.fromkeys(errors))
