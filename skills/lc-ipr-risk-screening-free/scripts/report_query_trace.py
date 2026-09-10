"""Read-only report projection of recorded queries; never executes a source.

The projection does not decide source eligibility, close work, or change grading.
It deliberately keeps attempts and unknown counts instead of synthesizing recall.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from common import sha256_json


STATUS_LABELS = {
    "hit": "查到候选", "no_match": "本次查询无命中", "failed": "查询失败",
    "access_limited": "访问受限", "not_run": "未执行", "submission_unknown": "提交状态未知",
    "truncated": "结果截断／未取全", "not_applicable": "不适用", "unknown": "结果或覆盖未知",
    "awaiting_review": "材料待审阅", "blocked": "工作受阻",
}
COMPLETE = {"hit", "no_match", "not_applicable"}
ZERO_WARNING = "有效检索为零；本结论为规则兜底，未排除侵权风险。"


def _items(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _plain(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else ""


def _url(value):
    """Do not publish userinfo, fragments, or credential-like query parameters."""
    value = str(value or "")
    if any(ord(char) < 32 for char in value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                 if not any(part in key.casefold() for part in ("token", "secret", "password", "credential", "auth", "api_key", "apikey", "session", "signature"))]
        host = parsed.hostname + (":" + str(parsed.port) if parsed.port else "")
        return urlunsplit((parsed.scheme, host, parsed.path, urlencode(query), ""))
    except ValueError:
        return ""


def _time(record):
    value = record.get("source_checked_at") or record.get("collected_at")
    if not value and record.get("checked_at_meaning") != "retained_file_hash_verification":
        value = record.get("checked_at")
    return value or record.get("finished_at") or record.get("started_at") or ""


def _number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _records(evidence):
    collections = evidence.get("collections", {})
    groups = list(collections.values()) if isinstance(collections, dict) else [collections]
    return [entry for group in groups for entry in _items(group)
            if entry.get("evidence_id") and not entry.get("private")
            and not any(word in " ".join(_plain(entry.get(key)).casefold() for key in ("role", "kind", "privacy", "purpose"))
                        for word in ("private", "login", "account", "debug"))]


def _queries(plan):
    groups = plan.get("queries", {})
    if isinstance(groups, list):
        return [{**query, "_plan_entry_sha256": sha256_json(query)} for query in _items(groups)]
    return [{**query, "provider": query.get("provider") or provider, "_plan_entry_sha256": sha256_json(query)}
            for provider, group in groups.items() for query in _items(group)] if isinstance(groups, dict) else []


def _refs(record):
    refs = record.get("evidence_refs", [])
    return [str(ref) for ref in refs if isinstance(ref, (str, int))] if isinstance(refs, list) else []


def _semantics(run, entries):
    objects = [run, run.get("metadata", {})]
    for entry in entries:
        objects.extend([entry, entry.get("payload", {})])
    objects += [obj[key] for obj in list(objects) if isinstance(obj, dict)
                for key in ("search_coverage", "result_coverage") if isinstance(obj.get(key), dict)]
    # A compiled plan is not submission evidence: only executed run/record values.
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        semantics = obj.get("query_semantics", {})
        if isinstance(semantics, dict) and semantics.get("rendered_query"):
            return _plain(semantics["rendered_query"]), "rendered_query"
        if obj.get("rendered_query"):
            return _plain(obj["rendered_query"]), "rendered_query"
    for obj in objects:
        if isinstance(obj, dict):
            for key in ("submitted_query", "actual_query"):
                if isinstance(obj.get(key), str) and obj[key]:
                    return obj[key], "recorded_" + key
    return "", "not_recorded"


def _recorded_retrieval_complete(coverage, state, records, provider):
    """Match existing receipt count/stop checks; never infer review completion.

    Older accepted receipts did not have a completeness field. An explicit
    unknown/incomplete value is still a disclosure, not a missing field default.
    """
    if "completeness" in coverage and coverage["completeness"] not in {"complete", "completed", "exhaustive"}:
        return False
    total, retrieved = _number(coverage.get("total_hits")), _number(coverage.get("retrieved_hits"))
    if (state not in {"hit", "no_match"} or coverage.get("schema_valid") is not True
            or total is None or retrieved is None or coverage.get("truncated") is not False
            or not str(coverage.get("stop_reason") or "").strip()
            or records is None or len(records) != retrieved):
        return False
    if provider == "uspto_patent_browser" and coverage.get("coverage_counting_revision") == "ppubs-result-rows-v1":
        from record_browser_execution import ppubs_counting_complete
        return ppubs_counting_complete(coverage, records)
    return retrieved >= total


def _bounded_discovery_receipt(evidence, query, run, source_task_dir):
    """Reuse retained-response checks without executing or configuring a source.

    These providers intentionally return bounded discovery cards, not an
    official recall total. Their successful response has an independent source
    contract even when the older receipt has no search_coverage metadata.
    """
    providers = {"serper_patents", "serper_web", "serper_images", "serpapi_google_patents", "serpapi_google_lens"}
    if (query.get("action_purpose") != "discovery" or run.get("provider") not in providers
            or run.get("status") not in {"success", "no_result"} or run.get("submission_state") != "submitted"):
        return None
    if source_task_dir is None:
        return {"valid": False, "error": "DISCOVERY_EVIDENCE_ROOT_UNAVAILABLE"}
    from api_first_planning import source_files_error
    from assessment_v24 import _source_records
    error = source_files_error(Path(source_task_dir), evidence, run)
    records = _source_records(evidence, str(run.get("run_id") or "")) if not error else None
    if error or records is None:
        return {"valid": False, "error": error or "API_DISCOVERY_SOURCE_CARDS_INVALID"}
    return {"valid": True, "returned_count": len(records), "basis": "retained_source_contract"}


def _attempt(run, query, entries, candidates, position, *, discovery=None):
    meta = run.get("metadata", {}) if isinstance(run.get("metadata"), dict) else {}
    coverage = meta.get("search_coverage", {}) if isinstance(meta.get("search_coverage"), dict) else {}
    status = str(run.get("status") or "unknown")
    submitted = str(run.get("submission_state") or "")
    actual, basis = _semantics(run, entries)
    refs = list(dict.fromkeys([entry["evidence_id"] for entry in entries] + _refs(run)))
    associated = [item for item in candidates if set(_refs(item) + (item.get("verification_refs") or [])).intersection(refs)
                  or (item.get("source_run_id") and item["source_run_id"] == run.get("run_id"))]
    observed, source_records = [], None
    for entry in entries:
        payload = entry.get("payload", {})
        records = payload.get("candidates") if isinstance(payload, dict) else payload
        if isinstance(records, list):
            source_records = (source_records or []) + records
            observed.extend(_items(records))
    found = [{key: item[key] for key in ("candidate_id", "title", "publication_number", "registration_number") if item.get(key)}
             for item in associated + observed]
    found = list({json.dumps(item, sort_keys=True): item for item in found if item}.values())
    total = _number(coverage.get("total_hits"))
    total = total if total is not None else _number(coverage.get("reported_total"))
    retrieved = _number(coverage.get("retrieved_hits"))
    retrieved = retrieved if retrieved is not None else _number(coverage.get("retrieved_count"))
    bounded = bool(discovery and discovery.get("valid"))
    returned_count = discovery.get("returned_count") if bounded else None
    declared_count_mismatch = bounded and retrieved is not None and retrieved != returned_count
    if bounded and retrieved is None:
        retrieved = returned_count  # Returned cards are counted; the global total remains unknown.
    reason = str(run.get("error_code") or run.get("reason") or coverage.get("stop_reason") or "")
    if submitted in {"unknown", "submission_unknown"} or status == "submission_unknown":
        state = "submission_unknown"
    elif status in {"not_applicable", "not_required"}:
        state = "not_applicable"
    elif status in {"access_limited", "unauthorized", "forbidden", "awaiting_access"}:
        state = "access_limited"
    elif status in {"failed", "error", "timeout", "blocked"}:
        state = "failed"
    elif status in {"not_run", "skipped", "not_executed"} or submitted in {"not_submitted", "not_started"}:
        state = "not_run"
    elif discovery is not None:
        state = "no_match" if bounded and status == "no_result" and returned_count == 0 else "hit" if bounded and status == "success" and returned_count else "unknown"
        if not bounded:
            reason = "; ".join(part for part in (reason, discovery.get("error", "")) if part)
    elif coverage.get("truncated") is True:
        state = "truncated"
    elif coverage.get("schema_valid") is True and status in {"success", "no_result", "complete", "completed"}:
        state = "no_match" if total == 0 and retrieved == 0 else "hit" if found or (retrieved is not None and retrieved > 0) else "unknown"
    else:
        state = "unknown"
    count_contradiction = total == 0 and retrieved == 0 and bool(found)
    if count_contradiction and state in {"hit", "no_match", "truncated", "unknown"}:
        state = "unknown"
        reason = "; ".join(part for part in (reason, "ZERO_RESULT_CONTRADICTION") if part)
    if declared_count_mismatch:
        state = "unknown"
        reason = "; ".join(part for part in (reason, "SOURCE_RECORD_COUNT_MISMATCH") if part)
    if state in {"not_run", "not_applicable"} or submitted in {"not_submitted", "not_started"}:
        actual, basis = "", "not_submitted"
    elif state in {"failed", "access_limited"} and submitted != "submitted":
        actual, basis = "", "submission_not_confirmed"
    # A successful, schema-valid observed result is effective within its reported
    # boundary, including a partial page; it is not proof of exhaustive recall.
    effective = bool((coverage.get("schema_valid") is True or bounded) and refs and state in {"hit", "no_match", "truncated"})
    completeness = coverage.get("completeness", "not_recorded")
    coverage_complete = not bounded and _recorded_retrieval_complete(coverage, state, source_records, run.get("provider") or query.get("provider"))
    response_complete = bool(bounded and state in {"hit", "no_match"}) or coverage_complete
    sources = [{"evidence_id": entry["evidence_id"], "source_url": _url(entry.get("source_url") or entry.get("url") or entry.get("final_url")),
                "source_checked_at": _time(entry), "source_name": entry.get("source_name") or entry.get("provider") or run.get("provider", "")}
               for entry in entries]
    return {"run_id": run.get("run_id", ""), "attempt_index": position, "query_id": run.get("query_id") or query.get("query_id", ""),
            "status": state, "status_label": STATUS_LABELS[state], "recorded_status": status,
            "submission_state": submitted or "not_recorded", "actual_query": actual, "actual_query_basis": basis,
            "checked_at": _time(run), "source_url": _url(run.get("source_url") or run.get("url")),
            "evidence_refs": refs, "sources": sources, "candidates_found": found,
            "total_hits": total, "retrieved_hits": retrieved, "truncated": coverage.get("truncated") if isinstance(coverage.get("truncated"), bool) else None,
            "reported_total": _number(coverage.get("reported_total")), "reviewed_hits": _number(coverage.get("reviewed_hits")),
            "pages_retrieved": _number(coverage.get("pages_retrieved")), "completeness": completeness,
            "coverage_complete": coverage_complete, "coverage_reason": str(coverage.get("reason") or ""),
            "bounded_discovery": bounded, "response_complete": response_complete,
            "source_response_basis": discovery.get("basis", "") if bounded else "search_coverage" if coverage.get("schema_valid") is True else "unvalidated",
            "count_contradiction": count_contradiction,
            "coverage_schema_valid": coverage.get("schema_valid") is True, "effective": effective,
            "reason": reason, "coverage_boundary": "仅为有界发现来源的本次响应；无命中不等于完整官方覆盖或排除侵权。" if bounded else "仅代表本次查询及已记录结果范围；不等于全面排除。"}


def build_query_trace(task, evidence, assessment, candidates, plan, *, source_task_dir=None):
    """Project all attempts plus outstanding/unplanned work without mutating inputs."""
    queries, entries = _queries(plan), _records(evidence)
    source_task_dir = source_task_dir or task.get("outputs", {}).get("assessment_input_dir")
    runs = _items(evidence.get("source_runs", []))
    candidate_rows = [item for group in candidates.values() for item in _items(group)]
    result, seen_runs = [], set()
    for query in queries:
        related = [run for run in runs if run.get("query_id") == query.get("query_id")
                   and run.get("provider") == query.get("provider")
                   and run.get("plan_entry_sha256") == query["_plan_entry_sha256"]]
        attempts = []
        for position, run in enumerate(related, 1):
            seen_runs.add(id(run))
            refs = [entry for entry in entries if entry.get("source_run_id") and entry.get("source_run_id") == run.get("run_id")]
            attempts.append(_attempt(run, query, refs, candidate_rows, position,
                discovery=_bounded_discovery_receipt(evidence, query, run, source_task_dir)))
        state = attempts[-1]["status"] if attempts else "not_applicable" if query.get("not_applicable") is True else "not_run"
        prior_findings = any(attempt["effective"] and (attempt["candidates_found"] or (attempt["retrieved_hits"] or 0) > 0)
                             for attempt in attempts[:-1])
        label = ("已查到候选；后续" + STATUS_LABELS[state]) if prior_findings and state in {"failed", "access_limited", "not_run", "submission_unknown", "unknown"} else STATUS_LABELS[state]
        result.append({"query_id": query.get("query_id", ""), "provider": query.get("provider", ""),
            "jurisdiction": query.get("jurisdiction", ""), "right_type": query.get("right_type", ""),
            "scenario_id": query.get("scenario_id", ""), "scenario_ids": query.get("scenario_ids", []),
            "scenario_sha256": query.get("scenario_sha256", ""), "scenario_bindings": query.get("scenario_bindings", []),
            "plan_entry_sha256": query["_plan_entry_sha256"], "search_dimension": query.get("search_dimension", ""), "search_language": query.get("search_language", ""),
            "operation": query.get("operation", ""), "requirement_ids": query.get("requirement_ids", []),
            "planned_query": _plain(query.get("q") or query.get("query") or query.get("search_term")),
            "status": state, "latest_status": state, "has_prior_findings": bool(prior_findings), "status_label": label, "attempts": attempts,
            "coverage_complete": bool(attempts and attempts[-1]["coverage_complete"]),
            "response_complete": bool(attempts and attempts[-1]["response_complete"]),
            "required": query.get("required", query.get("execute_by_default", True)) is not False})
    # Historical runs not present in the current plan remain visible, not promoted
    # into a new current plan or merged away by the latest receipt.
    for run in runs:
        if id(run) in seen_runs or not run.get("query_id"):
            continue
        refs = [entry for entry in entries if entry.get("source_run_id") and entry.get("source_run_id") == run.get("run_id")]
        attempt = _attempt(run, {}, refs, candidate_rows, 1)
        result.append({"query_id": run["query_id"], "provider": run.get("provider", ""), "jurisdiction": run.get("jurisdiction", ""),
            "right_type": run.get("right_type", ""), "scenario_id": run.get("scenario_id", ""), "scenario_ids": [],
            "scenario_sha256": run.get("scenario_sha256", ""), "scenario_bindings": run.get("scenario_bindings", run.get("metadata", {}).get("scenario_bindings", [])),
            "plan_entry_sha256": run.get("plan_entry_sha256", ""), "search_dimension": run.get("search_dimension", run.get("metadata", {}).get("search_dimension", "")),
            "search_language": run.get("search_language", run.get("metadata", {}).get("search_language", "")),
            "operation": run.get("operation", ""), "requirement_ids": run.get("requirement_ids", []), "planned_query": "",
            "status": attempt["status"], "status_label": attempt["status_label"], "attempts": [attempt], "required": False,
            "latest_status": attempt["status"], "has_prior_findings": False,
            "coverage_complete": False,
            "response_complete": False,
            "historical_unplanned_run": True})
    remaining = []
    for item in _items(assessment.get("publication", {}).get("remaining_work", [])):
        state = item.get("state", "unknown")
        if state in {"complete", "completed", "not_applicable"}:
            continue
        label_state = {"ready": "not_run", "awaiting_access": "access_limited", "awaiting_user": "blocked"}.get(state, state)
        if label_state not in STATUS_LABELS:
            label_state = "unknown"
        kept = {key: item[key] for key in ("work_id", "query_id", "scenario_id", "scenario_sha256", "jurisdiction", "right_type", "provider", "kind", "reason", "reasoning", "action_id", "evidence_refs", "source_run_refs", "requirement_id", "requirement_ids") if key in item}
        remaining.append({**kept, "recorded_state": state, "status": label_state, "status_label": STATUS_LABELS[label_state]})
    represented = {ref for query in result for ref in query["requirement_ids"]}
    represented.update(item.get("requirement_id") for item in remaining)
    represented.update(ref for item in remaining for ref in item.get("requirement_ids", []))
    for requirement in _items(task.get("coverage_requirements", [])):
        if requirement.get("requirement_id") in represented or requirement.get("required") is False or requirement.get("not_applicable") is True:
            continue
        # Candidate verification is conditional on an applicable candidate. Its
        # actual outstanding work is already owned by remaining_work/coverage.
        if requirement.get("phase") == "candidate_verification":
            continue
        remaining.append({"work_id": "unplanned:" + str(requirement.get("requirement_id", "")),
            **{key: requirement.get(key, "") for key in ("requirement_id", "scenario_id", "jurisdiction", "right_type")},
            "kind": "unplanned_requirement", "status": "not_run", "status_label": STATUS_LABELS["not_run"],
            "reason": "必要查询尚未规划；没有执行记录。"})
    for query in result:
        if query["required"] and not query["response_complete"] and query["status"] != "not_applicable" and not any(item.get("query_id") == query["query_id"] and item.get("provider", query["provider"]) == query["provider"] for item in remaining):
            remaining.append({"work_id": "query:" + query["provider"] + ":" + query["query_id"],
                **{key: query[key] for key in ("query_id", "scenario_id", "scenario_sha256", "scenario_bindings", "jurisdiction", "right_type", "provider", "status", "status_label")},
                "kind": "query", "reason": (query["attempts"][-1]["coverage_reason"] or query["attempts"][-1]["reason"] or "召回覆盖未知。") if query["attempts"] else "未见执行记录。"})
    scopes = _items(assessment.get("coverage", {}).get("scopes", []))
    for scope in scopes:
        if not (scope.get("gaps") or any(scope.get(key) == "incomplete" for key in ("retrieval_status", "triage_status", "verification_status"))):
            continue
        if any(all(not item.get(key) or item.get(key) == scope.get(key, "") for key in ("scenario_id", "jurisdiction", "right_type")) for item in remaining):
            continue
        identity = ":".join(str(scope.get(key, "")) for key in ("scenario_id", "jurisdiction", "right_type"))
        remaining.append({"work_id": "scope:" + identity,
            **{key: scope.get(key, "") for key in ("scenario_id", "jurisdiction", "right_type")},
            "kind": "unresolved_scope", "status": "unknown", "status_label": STATUS_LABELS["unknown"],
            "reason": _plain(scope.get("gaps") or scope.get("work_reasons") or "范围完成状态为未完成；未取得更细的停止记录。")})
    dimensions = []
    identities = {(scope.get("scenario_id", ""), scope.get("scenario_sha256", ""), scope.get("jurisdiction", ""), scope.get("right_type", "")) for scope in scopes}
    for item in result + remaining:
        bindings = _items(item.get("scenario_bindings", [])) or [item]
        for binding in bindings:
            identity = (binding.get("scenario_id", ""), binding.get("scenario_sha256", ""), item.get("jurisdiction", ""), item.get("right_type", ""))
            if not identity[0] and not item.get("historical_unplanned_run") and any(key[2:] == identity[2:] for key in identities):
                continue
            identities.add(identity)
    for scenario, scenario_sha256, country, right in sorted(identities):
        def matches(item):
            bindings = _items(item.get("scenario_bindings", []))
            scope_match = any(binding.get("scenario_id") == scenario and binding.get("scenario_sha256", "") == scenario_sha256 for binding in bindings) if bindings else (not item.get("scenario_id") or (item.get("scenario_id") == scenario and item.get("scenario_sha256", "") == scenario_sha256))
            if item.get("historical_unplanned_run") and not bindings and not item.get("scenario_id"):
                scope_match = not scenario and not scenario_sha256
            return item.get("jurisdiction", "") == country and item.get("right_type", "") == right and scope_match and (not item.get("scenario_ids") or scenario in item["scenario_ids"])
        rows = [row for row in _items(assessment.get("assessments", [])) if matches(row)]
        dimensions.append({"scenario_id": scenario, "scenario_sha256": scenario_sha256, "jurisdiction": country, "right_type": right,
            "query_indices": [index for index, item in enumerate(result) if matches(item)],
            "unfinished_indices": [index for index, item in enumerate(remaining) if matches(item)],
            "conclusions": [{key: row[key] for key in ("candidate_id", "title", "risk", "evidence_confidence", "confidence", "risk_basis", "assessment_status", "reasoning", "risk_reasoning", "pending_reasoning", "human_checks", "raise_if", "lower_if", "evidence_refs", "out_of_scope") if key in row} for row in rows]})
    attempts = [attempt for query in result for attempt in query["attempts"]]
    effective = sum(attempt["effective"] for query in result if not query.get("historical_unplanned_run") for attempt in query["attempts"])
    digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    unique_work = {item.get("work_id") or digest(item) for item in remaining}
    return {"revision": "query-trace-v1", "queries": result, "unfinished_work": remaining, "dimensions": dimensions,
        "summary": {"query_count": len(result), "attempt_count": len(attempts), "effective_search_count": effective,
                    "historical_attempt_count": sum(len(query["attempts"]) for query in result if query.get("historical_unplanned_run")),
                    "unfinished_step_count": len(unique_work), "zero_effective_search": effective == 0},
        "note": "统计按实际留存回执，不将计划等同执行；未知数量保留为空。查询完成与权利核验、评级工作完成分别记录。"}


def query_notes(query):
    """Identical plain facts used by HTML, Markdown and CSV renderers."""
    notes = ["查询 " + query["query_id"] + " · " + query["provider"] + " · " + query["status_label"],
             "查询维度／语言：" + (query.get("search_dimension") or "未记录") + "／" + (query.get("search_language") or "未记录"),
             "计划内容（不等于已提交）：" + (query["planned_query"] or "未记录")]
    for attempt in query["attempts"]:
        number = lambda value: str(value) if value is not None else "未知"
        sources = "；".join(item["evidence_id"] + " · " + item["source_name"] + " · " + (item["source_checked_at"] or "原始时点未知") + " · " + item["source_url"] for item in attempt["sources"])
        found = "；".join(" / ".join(str(value) for value in item.values()) for item in attempt["candidates_found"])
        notes.extend(["尝试 " + str(attempt["attempt_index"]) + "（" + attempt["run_id"] + "）：" + attempt["status_label"],
            "实际记录查询：" + (attempt["actual_query"] or "未记录实际提交内容") + "；语义依据：" + attempt["actual_query_basis"],
            "时点：" + (attempt["checked_at"] or "未知") + "；总命中 " + number(attempt["total_hits"]) + "，已获取 " + number(attempt["retrieved_hits"]),
            "召回覆盖：" + ("完整" if attempt["coverage_complete"] else "未完成或未知") + "；原始完整度：" + str(attempt["completeness"]) + "；已审 " + number(attempt["reviewed_hits"]) + "；已取页数 " + number(attempt["pages_retrieved"]),
            "来源响应：" + ("已完成有界发现响应，官方覆盖仍未知" if attempt["bounded_discovery"] and attempt["response_complete"] else "按原始查询及覆盖状态记录"),
            "查到的候选：" + (found or ("本次成功查询无命中" if attempt["status"] == "no_match" else "未记录具体候选，不能据此推断零命中")),
            "原因／停止边界：" + (attempt["reason"] or "未另记录") + "；" + attempt["coverage_boundary"],
            "证据与来源：" + (sources or "；".join(attempt["evidence_refs"]) or "未记录")])
    return notes


def unfinished_notes(trace):
    return [" · ".join(str(item.get(key) or "") for key in ("scenario_id", "jurisdiction", "right_type", "provider", "work_id"))
            + "：" + item["status_label"] + "；" + _plain(item.get("reason") or item.get("reasoning") or "原因未记录")
            for item in trace["unfinished_work"]]
