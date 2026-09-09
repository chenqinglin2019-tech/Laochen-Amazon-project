"""Append-only, bounded API discovery and evidence-bound follow-up authorization.

These are discovery actions, never official coverage or risk assessments. The
only durable records are existing task follow-ups, plan rows and source runs.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from common import atomic_write_json, load_json, sha256_json, now_iso

REVISION = "api-first-v1"
META_FIELDS = frozenset({"retrieval_workflow_revision", "discovery_intent_id", "discovery_role",
    "refinement_round", "parent_query_id", "parent_plan_entry_sha256", "source_index", "discovery_scope"})
INDEX = {"serper_patents": "google_patents", "serpapi_google_patents": "google_patents",
    "serper_web": "google_search", "serper_images": "google_images", "serpapi_google_lens": "google_lens",
    "signa": "signa", "epo_ops": "epo_ops", "euipo_trademark": "euipo", "euipo_design": "euipo",
    "inpi_api": "inpi", "uspto_patent_browser": "uspto_pps", "uspto_tmsearch_browser": "uspto_tmsearch"}
API_PROVIDERS = frozenset(p for p in INDEX if not p.endswith("browser"))
FOLLOWUP_ROLES = frozenset({"refinement", "fallback", "browser_fallback"})
REASONS = frozenset({"source_unavailable", "zero_results", "insufficient_relevant_candidates", "refine_scope"})


def enabled(task):
    return task.get("retrieval_workflow_revision") == REVISION


def intent_id(country, right, dimension, term):
    # A revised expression belongs to its original intent, not a new quota.
    return "INT-" + sha256_json({"country": country, "right": right, "dimension": dimension,
        "term": {k: term.get(k) for k in ("kind", "value", "language", "derived_from")}})[:20]


def dimension(term):
    from workflow_v24 import _dimension
    return "image" if term.get("discovery_channel") == "image" else _dimension(term)


def google_query(term):
    """Compile the implemented Google syntax; never send PPS field suffixes."""
    value = str(term.get("value") or "").strip()
    if not value or re.search(r"\.(?:PN|CPC|CCLS|KD|IN|AS)\.", value, re.I):
        raise ValueError("API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED")
    if term.get("kind") == "cpc":
        if not re.fullmatch(r"[A-HY]\d{2}[A-Z]\d+(?:/\d+)?", value, re.I):
            raise ValueError("API_DISCOVERY_CLASSIFICATION_UNSUPPORTED")
        return "cpc:" + value.upper()
    if dimension({"kind": term.get("kind", "product")}) == "classification":
        raise ValueError("API_DISCOVERY_CLASSIFICATION_UNSUPPORTED")
    if term.get("strategy") != "boolean":
        return '"' + value.replace('"', ' ') + '"' if term.get("strategy") == "phrase" else value
    # Google supports Unicode search words. Reusing the ASCII PPS compiler here
    # would silently lose non-English discovery intents.
    matches = list(re.finditer(r'"[^"\r\n]+"|\(|\)|[^\W_]+(?:[-\x27][^\W_]+)*', value))
    cursor, depth, expect_operand, negative = 0, 0, True, False
    result = []
    for match in matches:
        if value[cursor:match.start()].strip():
            raise ValueError("API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED")
        cursor = match.end()
        token = match.group()
        if token in {"WITH", "SAME", "ADJ", "NEAR"}:
            raise ValueError("API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED")
        if token in {"AND", "OR"}:
            if expect_operand or negative:
                raise ValueError("API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED")
            expect_operand = True
            if token == "OR":
                result.append(token)
        elif token == "NOT":
            negative = not negative
            expect_operand = True
        elif token == "(":
            if negative:
                raise ValueError("API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED")
            depth += 1
            expect_operand = True
            result.append(token)
        elif token == ")":
            if not depth or expect_operand or negative:
                raise ValueError("API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED")
            depth -= 1
            result.append(token)
        else:
            result.append(("-" if negative else "") + token)
            expect_operand, negative = False, False
    if value[cursor:].strip() or not matches or depth or expect_operand or negative:
        raise ValueError("API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED")
    return " ".join(result)


def provider_params(provider, term, country, right, *, page=1):
    from workflow_v24 import _api_params, LANGUAGES
    if provider == "serpapi_google_lens":
        image_url = str(term.get("image_url") or "")
        if not image_url.startswith("https://") or page != 1:
            raise ValueError("API_DISCOVERY_PUBLIC_IMAGE_REQUIRED")
        return {"q": image_url, "image_url": image_url, "type": "all", "hl": LANGUAGES[country],
            "country": country.lower()}
    if provider.startswith("serper_"):
        query = google_query(term)
        if provider == "serper_patents":
            query = f"({query}) country:{'EP' if country == 'EU' else country}"
        return {"q": query, "num": 10, "gl": "fr" if country == "EU" else country.lower(),
            "hl": LANGUAGES[country], **({"page": page} if page > 1 else {})}
    if provider == "serpapi_google_patents":
        if page != 1:
            raise ValueError("API_DISCOVERY_PAGINATION_UNSUPPORTED")
        return {"q": google_query(term), "num": 10, "country": "EP" if country == "EU" else country}
    if provider == "signa":
        from generate_search_plan import signa_discovery_entry
        from common import load_skill_config
        office = load_skill_config().get("providers", {}).get("signa", {}).get("office_map", {}).get(country)
        if not office:
            raise ValueError("API_DISCOVERY_ROUTE_UNSUPPORTED")
        # Keep the established Signa wire contract, but one country intent.
        row = signa_discovery_entry(country, term["value"], [term["derived_from"]], [office])
        from provider_utils import PLAN_META_KEYS
        return {k: v for k, v in row.items() if k not in PLAN_META_KEYS}
    params = _api_params(provider, term, country, right,
        query_compiler_revision="ppubs-boolean-v2" if provider == "uspto_patent_browser" and term.get("strategy") == "boolean" else None)
    if params is None:
        raise ValueError("API_DISCOVERY_ROUTE_UNSUPPORTED")
    return params


def policy_limit(task, key, maximum, *, minimum=1):
    value = (task.get("retrieval_policy") or {}).get(key, maximum)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("API_FIRST_RETRIEVAL_POLICY_INVALID")
    return value


def make_row(task, provider, term, country, right, requirements, *, parent=None, role="primary"):
    from workflow_v24 import bind_scenario_action
    from generate_search_plan import entry
    operation = {"serper_patents": "patents", "serper_web": "search", "serper_images": "images",
        "serpapi_google_patents": "search", "serpapi_google_lens": "image_search", "signa": "trademark_search",
        "uspto_patent_browser": "design_recall" if right == "design" else "patent_recall",
        "uspto_tmsearch_browser": "trademark_recall"}.get(provider, "search")
    params = provider_params(provider, term, country, right)
    if "num" in params:
        params["num"] = policy_limit(task, "discovery_results_per_query", 10)
    axis = parent.get("search_dimension") if parent else dimension(term)
    iid = parent["discovery_intent_id"] if parent else intent_id(country, right, axis, term)
    row = entry(provider, operation, country, params, right_type=right, required=False,
        requirement_ids=requirements, required_for="discovery_only", derived_from=[term["derived_from"]],
        wave=1 if role == "primary" else 2)
    row.update(role="discovery_only", authoritative_for_final_rating=False, execute_by_default=True,
        search_dimension=axis, search_language=term.get("language", ""),
        execution_phase="discovery_fallback" if role == "browser_fallback" else "discovery" if role == "primary" else "expansion",
        retrieval_workflow_revision=REVISION, discovery_intent_id=iid, discovery_role=role,
        refinement_round=(parent.get("refinement_round", 0) + 1 if role == "refinement" else parent.get("refinement_round", 0)) if parent else 0,
        source_index=INDEX[provider], discovery_scope={"mode": "bounded", "max_pages": policy_limit(task, "max_pages_per_query", 8) if role == "browser_fallback" else 1,
            "max_candidates": policy_limit(task, "browser_fallback_max_candidates", 50) if role == "browser_fallback" else 25 if provider in {"epo_ops", "euipo_trademark", "euipo_design", "inpi_api", "signa"} else params.get("num", 10),
            "review_all_returned": True})
    if provider == "serpapi_google_lens":
        row["discovery_scope"].update(requested_candidates=policy_limit(task, "discovery_results_per_query", 10),
            response_limit_enforceable=False)
    if parent:
        row.update(parent_query_id=parent["query_id"], parent_plan_entry_sha256=sha256_json(parent))
    if provider == "uspto_tmsearch_browser":
        row["query_compiler_revision"] = "tm-figurative-fields-v1" if right == "trademark_figurative" else "tm-field-tags-v1"
    return bind_scenario_action(task, provider, row, purpose="discovery", obligation_key=iid)


def _account(provider):
    return "serper" if provider.startswith("serper_") else "serpapi" if provider.startswith("serpapi_") else provider


def _limits(task):
    return {p: min(int((task.get(p + "_free_enhancement") or {}).get("max_queries_per_task", 0)),
        policy_limit(task, p + "_max_requests", maximum)) for p, maximum in (("serper", 30), ("serpapi", 10), ("signa", 3))}


def _preferred_providers(task, right, term, capabilities):
    from common import serper_free_enabled, serpapi_free_enabled, signa_free_enabled
    # Current accepted APIs are preferred when their credential/capability proof
    # exists; browser access is never created here as a startup side effect.
    if term.get("discovery_channel") == "image":
        if right == "copyright" and term.get("image_url") and serpapi_free_enabled(task):
            yield "serpapi_google_lens"
        if serper_free_enabled(task):
            yield "serper_images"
        return
    if right in {"patent", "utility_model"} and capabilities.get("epo_ops", {}).get("executable"):
        yield "epo_ops"
    if right == "trademark_word" and signa_free_enabled(task):
        yield "signa"
    if serper_free_enabled(task):
        yield "serper_patents" if right in {"patent", "utility_model", "design"} else "serper_web"
    if right in {"patent", "design"} and serpapi_free_enabled(task) and not serper_free_enabled(task):
        yield "serpapi_google_patents"


def append_initial(task_dir, task, terms, queries, gaps, expansion_queue):
    """Round-robin countries and rights without dropping unplanned clues."""
    from workflow_v24 import _applicable, _target_language_compatible, _add
    from decision_workflow import scenario_index, necessary_scenario_right_types
    cap_path = Path(task_dir) / "source-capabilities.json"
    raw_caps = load_json(cap_path) if cap_path.is_file() else {}
    values = raw_caps.get("providers", raw_caps.get("sources", []))
    capabilities = values if isinstance(values, dict) else {v.get("provider"): v for v in values if isinstance(v, dict)}
    applicable_rights = set().union(*(necessary_scenario_right_types(task, s) for s in scenario_index(task).values()))
    requirements = [r for r in task.get("coverage_requirements", []) if r.get("phase") in {"official_recall", "provenance"}
        and r.get("right_type") in applicable_rights]
    buckets = {}
    for country in task["target_jurisdictions"]:
        for right in sorted({r["right_type"] for r in requirements if r["jurisdiction"] == country}):
            refs = [r["requirement_id"] for r in requirements if (r["jurisdiction"], r["right_type"]) == (country, right)]
            eligible = [t for t in terms if _target_language_compatible(t, country) and
                (_applicable(t, right, task=task) if right not in {"copyright", "trade_dress", "unregistered_design"}
                 else t["kind"] in {"product", "ocr", "manufacturer"} and "mark_inventory" not in str(t.get("derived_from", "")))]
            if right == "trademark_figurative":
                eligible = [t for t in eligible if t["kind"] not in {"brand", "ocr"}]

            # Interleave dimensions within a country/right instead of consuming
            # all shared credit on the first language or one category of terms.
            public_image = next((i for i in task.get("images", []) if str(i.get("source_url", "")).startswith("https://")), None)
            if eligible and public_image and right in {"design", "copyright", "trademark_figurative"}:
                eligible = [*eligible, {**eligible[0], "discovery_channel": "image", "image_url": public_image["source_url"]}]
            dimensions = {}
            for term in eligible:
                dimensions.setdefault(dimension(term), []).append(term)
            ordered = [values[i] for i in range(max(map(len, dimensions.values()), default=0))
                for values in dimensions.values() if i < len(values)]
            buckets[(country, right)] = [(t, refs) for t in ordered]
            if not ordered:
                gaps.append({"code": "API_DISCOVERY_TERMS_MISSING", "jurisdiction": country, "right_type": right,
                    "requirement_ids": refs, "assigned_to": "agent", "blocking_planning": False})
    limits = _limits(task)
    # Leave shared credit for evidence-driven follow-ups, with no endpoint split.
    initial_limits = {p: n - (max(2, n // 4) if n >= 8 else 0) for p, n in limits.items()}
    used = {p: sum(len(v) for provider, v in queries.items() if _account(provider) == p) for p in limits}
    existing = {r.get("discovery_intent_id") for values in queries.values() for r in values if r.get("discovery_role") == "primary"}
    countries = {country: i for i, country in enumerate(task["target_jurisdictions"])}
    rights = {r: i for i, r in enumerate(("patent", "design", "utility_model", "trademark_word", "trademark_figurative", "copyright", "trade_dress", "unregistered_design"))}
    bucket_order = sorted(buckets, key=lambda key: (rights.get(key[1], 99), countries[key[0]]))
    order = [(key, buckets[key][i]) for i in range(max(map(len, buckets.values()), default=0))
        for key in bucket_order if i < len(buckets[key])]
    # Structural clues drive discovery precision. Preserve their country round
    # robin ahead of secondary identity/provenance expressions.
    def core(item):
        return item[0][1] in {"patent", "utility_model"} and item[1][0]["kind"] in {"structural_feature", "function", "cpc", "ipc"}
    order = [item for item in order if core(item)] + [item for item in order if not core(item)]
    for (country, right), (term, refs) in order:
        iid = intent_id(country, right, dimension(term), term)
        if iid in existing:
            continue
        reason, selected = "API_DISCOVERY_ROUTE_UNAVAILABLE", None
        for provider in _preferred_providers(task, right, term, capabilities):
            account = _account(provider)
            if account in limits and used[account] >= initial_limits[account]:
                reason = "API_DISCOVERY_BUDGET_EXHAUSTED" if used[account] >= limits[account] else "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP"
                continue
            try:
                selected = provider, make_row(task, provider, term, country, right, refs)
            except ValueError as exc:
                reason = str(exc)
                continue
            break
        if selected:
            provider, row = selected
            _add(queries, provider, row)
            if _account(provider) in used:
                used[_account(provider)] += 1
            expansion_queue.append({"query_id": row["query_id"], "discovery_intent_id": iid, "provider": provider,
                "jurisdiction": country, "right_type": right, "state": "scheduled", "reason": "api_first_discovery"})
        else:
            gaps.append({"code": reason, "discovery_intent_id": iid, "jurisdiction": country, "right_type": right,
                "search_dimension": dimension(term), "requirement_ids": refs, "derived_from": [term["derived_from"]],
                "term_id": sha256_json(term), "assigned_to": "agent", "blocking_planning": False})


def triage_digest(task, evidence, candidates, ledger, supplement=None, *, query_id=None):
    from decision_workflow import triage_summary
    result = triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement)
    if query_id:
        from assessment_v24 import _query_candidates
        ids = {r.get("candidate_id") for r in _query_candidates(candidates, evidence, query_id)}
        result = [r for r in result.get("records", []) if r.get("candidate_id") in ids]
    return sha256_json(result)


def source_card_state(task, evidence, candidates, ledger, row, run, supplement=None):
    """Every returned card must survive merge and have current scope triage."""
    from assessment_v24 import _source_records, _query_candidates, _records_accounted_for
    from decision_workflow import triage_summary
    from provider_utils import ProviderError
    try:
        if run.get("provider") in {"serpapi_google_lens", "serper_images"}:
            if run.get("provider") == "serper_images":
                from serper_client import retained_source_records
            else:
                from serpapi_lens_client import retained_source_records
            records = retained_source_records(evidence, run)
        else:
            records = _source_records(evidence, run.get("run_id"))
    except (ValueError, OSError, TypeError, KeyError, ProviderError):
        return "API_DISCOVERY_SOURCE_CARDS_INVALID", []
    if records is None or (run.get("status") == "no_result" and records):
        return "API_DISCOVERY_SOURCE_CARDS_INVALID", []
    merged = _query_candidates(candidates, evidence, row["query_id"])
    matched = []
    for card in records:
        if card.get("source_record_sha256"):
            found = [c for c in merged if any(isinstance(src, dict)
                and src.get("source_record_sha256") == card["source_record_sha256"]
                and src.get("source_run_id") == run["run_id"]
                and src.get("plan_entry_sha256") == sha256_json(row) for src in c.get("sources", []))]
        else:
            found = [c for c in merged if any(isinstance(src, dict) and src.get("source_run_id") == run["run_id"]
                for src in c.get("sources", [])) and _records_accounted_for([card], [c], review_check=lambda item: True)]
        if not found:
            return "API_DISCOVERY_MERGE_REQUIRED", []
        matched.extend(found)
    ids = {c.get("candidate_id") for c in matched}
    summary = triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement)
    from decision_workflow import scenario_index, necessary_scenario_right_types
    decisions = [r for r in summary.get("records", []) if r.get("candidate_id") in ids
        and r.get("jurisdiction") == row["jurisdiction"]]
    for candidate in matched:
        actual_right = candidate.get("right_type")
        if not actual_right or actual_right == "unknown" or candidate.get("right_type_status") == "unresolved":
            return "API_DISCOVERY_CARD_IDENTITY_REVIEW_REQUIRED", decisions
        for sid, scenario in scenario_index(task).items():
            if actual_right not in necessary_scenario_right_types(task, scenario):
                continue
            current = [d for d in decisions if d.get("candidate_id") == candidate.get("candidate_id")
                and d.get("scenario_id") == sid and d.get("right_type") == actual_right]
            if not current or any(not d.get("current") or d.get("decision") not in {"selected", "not_selected"} for d in current):
                return "API_DISCOVERY_TRIAGE_REQUIRED", decisions
    return None, decisions


def review_validation(task, plan, evidence, candidates, ledger, row, review, supplement=None):
    """A bounded discovery stop is a recorded decision, not a coverage claim."""
    if (review.get("role") != "review" or review.get("parent_query_id") != row["query_id"]
            or review.get("parent_plan_entry_sha256") != sha256_json(row)
            or review.get("discovery_scope") != row.get("discovery_scope")
            or review.get("outcome") not in {"proceed_to_verification", "stop_bounded_discovery", "blocked"}
            or any(not str(review.get(k) or "").strip() for k in ("reason", "reviewer"))):
        return "API_DISCOVERY_REVIEW_INVALID"
    runs = [r for r in evidence.get("source_runs", []) if r.get("run_id") == review.get("source_run_id")]
    if len(runs) != 1:
        return "API_DISCOVERY_SOURCE_RUN_REQUIRED"
    run = runs[0]
    if (run.get("query_id") != row["query_id"] or run.get("plan_entry_sha256") != sha256_json(row)
            or review.get("source_run_sha256") != sha256_json(run)
            or run.get("submission_state") not in {"submitted", "not_submitted"}
            or run.get("fixture") or run.get("test_only")
            or run.get("source_environment") in {"test_fixture", "sandbox", "non_production"}):
        return "API_DISCOVERY_SOURCE_BINDING_MISMATCH"
    linked = {entry.get("evidence_id") for values in evidence.get("collections", {}).values() if isinstance(values, list)
        for entry in values if isinstance(entry, dict) and entry.get("source_run_id") == run["run_id"]}
    refs = review.get("evidence_ids")
    if not isinstance(refs, list) or any(ref not in linked for ref in refs):
        return "API_DISCOVERY_EVIDENCE_REQUIRED"
    if run.get("status") in {"success", "no_result"}:
        if not refs or review.get("triage_digest") != triage_digest(task, evidence, candidates, ledger, supplement, query_id=row["query_id"]):
            return "API_DISCOVERY_TRIAGE_CHANGED"
        error, decisions = source_card_state(task, evidence, candidates, ledger, row, run, supplement)
        if error:
            return error
        if review["outcome"] == "proceed_to_verification" and not any(d.get("decision") == "selected" for d in decisions):
            return "API_DISCOVERY_RELEVANT_CANDIDATES_REQUIRED"
    elif (run.get("status") not in {"failed", "access_limited", "needs_user_action"}
            or not run.get("error_code") or review.get("outcome") != "blocked"):
        return "API_DISCOVERY_STOP_REASON_UNSUPPORTED"
    if review.get("outcome") == "blocked" and not str(review.get("blocker") or "").strip():
        return "API_DISCOVERY_BLOCKER_REQUIRED"
    return None


def append_review(task_dir, task, plan, evidence, parent, request):
    from workflow_v24 import scenario_supplement
    candidates = load_json(task_dir / "normalized-candidates.json")
    ledger = load_json(task_dir / "materiality-annotations.json")
    runs = [r for r in evidence.get("source_runs", []) if r.get("run_id") == request.get("source_run_id")]
    if len(runs) != 1:
        raise ValueError("API_DISCOVERY_SOURCE_RUN_REQUIRED")
    record = {k: deepcopy(request.get(k)) for k in ("source_run_id", "reason", "reviewer", "evidence_ids", "triage_digest", "outcome", "blocker")}
    record.update(role="review", parent_query_id=parent["query_id"], parent_plan_entry_sha256=sha256_json(parent),
        source_run_sha256=sha256_json(runs[0]), discovery_scope=deepcopy(parent["discovery_scope"]), reviewed_at=now_iso())
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    error = review_validation(task, plan, evidence, candidates, ledger, parent, record, supplement)
    if not error:
        error = source_files_error(task_dir, evidence, runs[0])
    if error:
        raise ValueError(error)
    task.setdefault("discovery_followups", []).append(record)
    atomic_write_json(task_dir / "task.json", task)
    return record


def followup_validation(task, plan, evidence, candidates, ledger, row, supplement=None):
    """Validate a follow-up using existing immutable rows/runs and triage."""
    if row.get("discovery_role") == "primary":
        return None
    records = task.get("discovery_followups", [])
    records = [d for d in records if isinstance(d, dict) and d.get("query_id") == row.get("query_id")] if isinstance(records, list) else []
    if len(records) != 1:
        return "API_DISCOVERY_FOLLOWUP_DECISION_REQUIRED"
    d = records[0]
    from workflow_v24 import plan_row_index
    parents = plan_row_index(plan).get(row.get("parent_query_id"), [])
    if len(parents) != 1:
        return "API_DISCOVERY_PARENT_INVALID"
    parent_provider, parent = parents[0]
    if (d.get("plan_entry_sha256") != sha256_json(row) or d.get("parent_plan_entry_sha256") != sha256_json(parent)
            or row.get("parent_plan_entry_sha256") != sha256_json(parent)
            or d.get("parent_query_id") != parent["query_id"]
            or any(row.get(k) != parent.get(k) for k in ("discovery_intent_id", "jurisdiction", "right_type", "requirement_ids", "search_dimension"))):
        return "API_DISCOVERY_PARENT_BINDING_MISMATCH"
    providers = [p for p, values in plan.get("queries", {}).items() if any(r is row or r == row for r in values)]
    term = d.get("term")
    try:
        if (len(providers) != 1 or not isinstance(term, dict)
                or provider_params(providers[0], term, row["jurisdiction"], row["right_type"])["q"] != row["q"]):
            return "API_DISCOVERY_FOLLOWUP_TERM_MISMATCH"
        if row.get("discovery_role") == "fallback" and provider_params(parent_provider, term, row["jurisdiction"], row["right_type"])["q"] != parent["q"]:
            return "API_DISCOVERY_FALLBACK_CHANGED_QUERY"
    except (KeyError, ValueError, TypeError):
        return "API_DISCOVERY_FOLLOWUP_TERM_MISMATCH"
    runs = [r for r in evidence.get("source_runs", []) if r.get("run_id") == d.get("source_run_id")]
    if len(runs) != 1:
        return "API_DISCOVERY_SOURCE_RUN_REQUIRED"
    run = runs[0]
    if (d.get("source_run_sha256") != sha256_json(run) or run.get("query_id") != parent["query_id"]
            or run.get("provider") != parent_provider or run.get("plan_entry_sha256") != sha256_json(parent)
            or run.get("fixture") or run.get("test_only") or run.get("source_environment") in {"test_fixture", "sandbox", "non_production"}
            or run.get("submission_state") not in {"submitted", "not_submitted"}):
        return "API_DISCOVERY_SOURCE_BINDING_MISMATCH"
    if (d.get("reason_code") not in REASONS or any(not isinstance(d.get(k), str) or not d[k].strip() for k in ("reviewer", "reason"))):
        return "API_DISCOVERY_REASON_REQUIRED"
    refs = d.get("evidence_ids")
    linked = {item.get("evidence_id") for values in evidence.get("collections", {}).values() if isinstance(values, list)
        for item in values if isinstance(item, dict) and item.get("source_run_id") == run["run_id"]}
    if not isinstance(refs, list) or any(ref not in linked for ref in refs) or (run.get("status") in {"success", "no_result"} and not refs):
        return "API_DISCOVERY_EVIDENCE_REQUIRED"
    if d["reason_code"] == "source_unavailable":
        if run.get("status") not in {"failed", "access_limited", "needs_user_action"} or not run.get("error_code"):
            return "API_DISCOVERY_SOURCE_NOT_FAILED"
    else:
        if run.get("status") not in {"success", "no_result"}:
            return "API_DISCOVERY_SUCCESSFUL_PARENT_REQUIRED"
        if d["reason_code"] == "zero_results" and run.get("status") != "no_result":
            return "API_DISCOVERY_PARENT_NOT_ZERO"
        if d.get("triage_digest") != triage_digest(task, evidence, candidates, ledger, supplement, query_id=parent["query_id"]):
            return "API_DISCOVERY_TRIAGE_CHANGED"
        error, relevant = source_card_state(task, evidence, candidates, ledger, parent, run, supplement)
        if error:
            return error
        if d["reason_code"] == "insufficient_relevant_candidates" and any(r.get("decision") == "selected" for r in relevant):
            return "API_DISCOVERY_RELEVANT_CANDIDATES_EXIST"
    if row.get("discovery_role") == "browser_fallback" and (parent_provider not in API_PROVIDERS
            or d["reason_code"] not in {"source_unavailable", "zero_results", "insufficient_relevant_candidates"}):
        return "API_DISCOVERY_BROWSER_FALLBACK_NOT_AUTHORIZED"
    return None


def dispatch_block(task, plan, evidence, candidates, ledger, provider, row, supplement=None):
    if not enabled(task):
        return None
    if plan.get("retrieval_workflow_revision") != REVISION:
        return "API_FIRST_PLAN_REVISION_MISMATCH"
    if (plan.get("retrieval_policy") != task.get("retrieval_policy")
            or plan.get("retrieval_policy_sha256") != sha256_json(task.get("retrieval_policy"))
            or any(plan.get(p + "_free_enhancement") != task.get(p + "_free_enhancement") for p in ("serper", "serpapi", "signa"))):
        return "API_FIRST_RETRIEVAL_POLICY_CHANGED"
    if row.get("action_purpose") != "discovery":
        # Current selected / needs_info checks remain the authority for exact
        # candidate reads. No broad browser recall can be smuggled in here.
        if provider.endswith("browser") and row.get("action_purpose") == "recall" and not row.get("triage_candidate_id"):
            return "API_FIRST_BROAD_BROWSER_RECALL_DISABLED"
        return None
    if (row.get("retrieval_workflow_revision") != REVISION or not row.get("discovery_intent_id")
            or row.get("role") != "discovery_only" or row.get("required_for") != "discovery_only"
            or row.get("authoritative_for_final_rating") is not False or row.get("source_index") != INDEX.get(provider)):
        return "API_DISCOVERY_CONTRACT_INVALID"
    scope = row.get("discovery_scope")
    browser = provider.endswith("browser")
    try:
        max_pages = policy_limit(task, "max_pages_per_query", 8)
        max_candidates = policy_limit(task, "browser_fallback_max_candidates", 50) if browser else 25
        max_rounds = policy_limit(task, "max_refinement_rounds", 2, minimum=0)
        max_browser_queries = policy_limit(task, "browser_fallback_queries_per_scope", 2)
    except ValueError as exc:
        return str(exc)
    if (not isinstance(scope, dict) or scope.get("mode") != "bounded" or scope.get("review_all_returned") is not True
            or type(scope.get("max_pages")) is not int or not 1 <= scope["max_pages"] <= max_pages
            or type(scope.get("max_candidates")) is not int or not 1 <= scope["max_candidates"] <= max_candidates):
        return "API_DISCOVERY_BOUNDS_INVALID"
    role = row.get("discovery_role")
    if role not in {"primary", *FOLLOWUP_ROLES} or type(row.get("refinement_round")) is not int or not 0 <= row["refinement_round"] <= max_rounds:
        return "API_DISCOVERY_ROUND_LIMIT"
    if browser != (role == "browser_fallback"):
        return "API_DISCOVERY_BROWSER_FALLBACK_NOT_AUTHORIZED"
    if role == "primary":
        from common import serper_free_enabled
        if provider == "serpapi_google_patents" and serper_free_enabled(task):
            return "API_DISCOVERY_FALLBACK_DECISION_REQUIRED"
        if provider not in API_PROVIDERS or row.get("refinement_round") != 0 or row.get("parent_query_id"):
            return "API_DISCOVERY_PRIMARY_INVALID"
        return None
    all_rows = [(p, r) for p, values in plan.get("queries", {}).items() for r in values]
    if browser:
        same = [r for p, r in all_rows if p.endswith("browser") and r.get("discovery_role") == "browser_fallback"
            and (r.get("jurisdiction"), r.get("right_type")) == (row.get("jurisdiction"), row.get("right_type"))]
        if len(same) > max_browser_queries:
            return "API_DISCOVERY_BROWSER_SCOPE_LIMIT"
    parents = [r for _, r in all_rows if r.get("query_id") == row.get("parent_query_id")]
    if len(parents) != 1:
        return "API_DISCOVERY_PARENT_INVALID"
    parent = parents[0]
    parent_provider = next(p for p, r in all_rows if r is parent)
    if role == "fallback" and provider == parent_provider:
        return "API_DISCOVERY_FALLBACK_REQUIRES_SAME_QUERY_ALTERNATIVE"
    if role == "refinement" and row.get("q") == parent.get("q"):
        return "API_DISCOVERY_REFINEMENT_UNCHANGED"
    expected = parent.get("refinement_round", 0) + (role == "refinement")
    if row["refinement_round"] != expected:
        return "API_DISCOVERY_ROUND_INVALID"
    # A node may not grow sibling rewrites to evade the two-round lineage.
    siblings = [r for _, r in all_rows if r.get("parent_query_id") == parent["query_id"] and r.get("discovery_role") == role]
    if len(siblings) != 1:
        return "API_DISCOVERY_FOLLOWUP_AMBIGUOUS"
    return followup_validation(task, plan, evidence, candidates, ledger, row, supplement)


def followup_source_files_error(task_dir, task, evidence, row):
    if not enabled(task) or row.get("discovery_role") not in FOLLOWUP_ROLES:
        return None
    decisions = [d for d in task.get("discovery_followups", []) if d.get("query_id") == row.get("query_id")]
    if len(decisions) != 1:
        return "API_DISCOVERY_FOLLOWUP_DECISION_REQUIRED"
    run = next((r for r in evidence.get("source_runs", []) if r.get("run_id") == decisions[0].get("source_run_id")), {})
    return source_files_error(task_dir, evidence, run)


def source_files_error(task_dir, evidence, run):
    if run.get("status") in {"success", "no_result"} or run.get("raw_paths"):
        from runtime_v24 import source_files_complete
        if not source_files_complete(Path(task_dir), evidence, run):
            return "API_DISCOVERY_SOURCE_FILES_INVALID"
        if run.get("status") in {"success", "no_result"} and run.get("provider") in {
                "serper_patents", "serper_web", "serper_images", "serpapi_google_patents", "serpapi_google_lens"}:
            from collections import Counter
            from assessment_v24 import _source_records
            from provider_utils import ProviderError
            try:
                raw = load_json(Path(task_dir) / run["raw_paths"][0])
                keys = {"serper_patents": ["organic"], "serper_web": ["organic"], "serper_images": ["images"],
                    "serpapi_google_patents": ["organic_results"], "serpapi_google_lens": ["visual_matches", "exact_matches"]}[run["provider"]]
                lists = [raw[k] for k in keys if k in raw]
                if not lists or any(not isinstance(items, list) for items in lists):
                    return "API_DISCOVERY_SOURCE_CARDS_INVALID"
                cards = [card for items in lists for card in items]
                if run.get("provider") in {"serpapi_google_lens", "serper_images"}:
                    if run.get("provider") == "serper_images":
                        from serper_client import retained_source_records
                    else:
                        from serpapi_lens_client import retained_source_records
                    records = retained_source_records(evidence, run, task_dir=task_dir)
                else:
                    records = _source_records(evidence, run["run_id"])
                if (records is None or any(not isinstance(card, dict) for card in cards)
                        or len(cards) != len(records) or (run.get("status") == "no_result") != (len(cards) == 0)
                        or any(not re.fullmatch(r"[0-9a-f]{64}", str(r.get("source_record_sha256") or "")) for r in records)
                        or Counter(sha256_json(card) for card in cards) != Counter(r["source_record_sha256"] for r in records)):
                    return "API_DISCOVERY_SOURCE_CARDS_INVALID"
            except (OSError, ValueError, KeyError, TypeError, ProviderError):
                return "API_DISCOVERY_SOURCE_CARDS_INVALID"
    return None


def append_plan_repair(task_dir, task, plan, evidence, old_provider, parent, request):
    """Repair only an unsubmitted wrong-provider primary, retaining its bytes."""
    from workflow_v24 import _add
    from common import serper_free_enabled
    if (parent.get("discovery_role") != "primary" or old_provider != "serpapi_google_patents"
            or not serper_free_enabled(task) or request.get("provider") != "serper_patents"):
        raise ValueError("API_DISCOVERY_PLAN_REPAIR_NOT_APPLICABLE")
    if any(r.get("query_id") == parent["query_id"] and r.get("plan_entry_sha256") == sha256_json(parent)
            and r.get("submission_state") != "not_submitted" for r in evidence.get("source_runs", [])):
        raise ValueError("API_DISCOVERY_PLAN_REPAIR_ALREADY_SUBMITTED")
    term = request.get("term")
    if (not isinstance(term, dict) or provider_params(old_provider, term, parent["jurisdiction"], parent["right_type"])["q"] != parent["q"]
            or any(not str(request.get(k) or "").strip() for k in ("reason", "reviewer"))):
        raise ValueError("API_DISCOVERY_PLAN_REPAIR_REASON_OR_TERM_INVALID")
    row = make_row(task, "serper_patents", term, parent["jurisdiction"], parent["right_type"], parent["requirement_ids"])
    if row["discovery_intent_id"] != parent["discovery_intent_id"]:
        raise ValueError("API_DISCOVERY_PARENT_BINDING_MISMATCH")
    if any(r.get("query_id") == row["query_id"] for values in plan["queries"].values() for r in values):
        raise ValueError("API_DISCOVERY_FOLLOWUP_ALREADY_PLANNED")
    if sum(len(v) for provider, v in plan["queries"].items() if _account(provider) == "serper") >= _limits(task)["serper"]:
        raise ValueError("API_DISCOVERY_BUDGET_EXHAUSTED")
    _add(plan["queries"], "serper_patents", row)
    plan.setdefault("execution_dispositions", []).append({"query_id": parent["query_id"],
        "plan_entry_sha256": sha256_json(parent), "status": "cancelled", "reason": request["reason"],
        "reason_code": "API_DISCOVERY_PRIMARY_PROVIDER_REPAIRED", "reviewer": request["reviewer"], "created_at": now_iso()})
    task.setdefault("discovery_followups", []).append({"role": "plan_repair", "parent_query_id": parent["query_id"],
        "parent_plan_entry_sha256": sha256_json(parent), "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
        "term": deepcopy(term), "reason": request["reason"], "reviewer": request["reviewer"], "reviewed_at": now_iso()})
    atomic_write_json(task_dir / "task.json", task)
    atomic_write_json(task_dir / "search-plan.json", plan)
    return row


def append_followup(task_dir, request):
    """Materialize one reviewed follow-up, retaining old rows and failures."""
    from workflow_v24 import assert_recall_planning_contract, plan_row_index, _add, scenario_supplement
    task_dir = Path(task_dir)
    task, plan, evidence = (load_json(task_dir / n) for n in ("task.json", "search-plan.json", "evidence.json"))
    assert_recall_planning_contract(task, plan)
    if not enabled(task) or not isinstance(request, dict):
        raise ValueError("API_FIRST_TASK_REQUIRED")
    parents = plan_row_index(plan).get(request.get("parent_query_id"), [])
    if len(parents) != 1:
        raise ValueError("API_DISCOVERY_PARENT_INVALID")
    old_provider, parent = parents[0]
    role = request.get("role")
    if role == "plan_repair":
        return append_plan_repair(task_dir, task, plan, evidence, old_provider, parent, request)
    if role == "review":
        return append_review(task_dir, task, plan, evidence, parent, request)
    if role not in FOLLOWUP_ROLES:
        raise ValueError("API_DISCOVERY_FOLLOWUP_ROLE_INVALID")
    provider = request.get("provider", old_provider)
    if provider not in INDEX:
        raise ValueError("API_DISCOVERY_ROUTE_UNSUPPORTED")
    term = request.get("term")
    if not isinstance(term, dict) or any(not str(term.get(k) or "").strip() for k in ("kind", "value", "derived_from")):
        raise ValueError("API_DISCOVERY_TERM_REQUIRED")
    from workflow_v24 import _target_language_compatible
    if not _target_language_compatible(term, parent["jurisdiction"]):
        raise ValueError("API_DISCOVERY_LANGUAGE_MISMATCH")
    row = make_row(task, provider, term, parent["jurisdiction"], parent["right_type"], parent["requirement_ids"], parent=parent, role=role)
    if any(r.get("query_id") == row["query_id"] for rows in plan["queries"].values() for r in rows):
        raise ValueError("API_DISCOVERY_FOLLOWUP_ALREADY_PLANNED")
    runs = [r for r in evidence.get("source_runs", []) if r.get("run_id") == request.get("source_run_id")]
    if len(runs) != 1:
        raise ValueError("API_DISCOVERY_SOURCE_RUN_REQUIRED")
    candidates = load_json(task_dir / "normalized-candidates.json")
    ledger = load_json(task_dir / "materiality-annotations.json")
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    decision = {k: deepcopy(request.get(k)) for k in ("source_run_id", "reason_code", "reason", "reviewer", "evidence_ids", "triage_digest")}
    decision["term"] = deepcopy(term)
    decision.update(query_id=row["query_id"], plan_entry_sha256=sha256_json(row), parent_query_id=parent["query_id"],
        parent_plan_entry_sha256=sha256_json(parent), source_run_sha256=sha256_json(runs[0]), reviewed_at=now_iso())
    trial_task, trial_plan = deepcopy(task), deepcopy(plan)
    trial_task.setdefault("discovery_followups", []).append(decision)
    _add(trial_plan["queries"], provider, row)
    block = dispatch_block(trial_task, trial_plan, evidence, candidates, ledger, provider, row, supplement)
    block = block or followup_source_files_error(task_dir, trial_task, evidence, row)
    if block:
        raise ValueError(block)
    account = _account(provider)
    if account in _limits(task) and sum(len(v) for p, v in trial_plan["queries"].items() if _account(p) == account) > _limits(task)[account]:
        raise ValueError("API_DISCOVERY_BUDGET_EXHAUSTED")
    # A partially written task cannot authorize execution without the exact
    # second plan write; validation rejects missing/mismatched rows.
    atomic_write_json(task_dir / "task.json", trial_task)
    atomic_write_json(task_dir / "search-plan.json", trial_plan)
    return row


def next_work_entries(task, plan, evidence, candidates, ledger, supplement=None, *, task_dir=None):
    """Discovery work only; preserve existing official coverage gaps verbatim."""
    from workflow_v24 import necessary_scenario_row_bindings
    rows = [(p, r) for p, values in plan.get("queries", {}).items() for r in values if r.get("action_purpose") == "discovery"]
    output = []
    for provider, row in rows:
        from workflow_v24 import validated_query_cancellation
        if validated_query_cancellation(task, plan, row):
            continue
        block = dispatch_block(task, plan, evidence, candidates, ledger, provider, row, supplement)
        runs = [r for r in evidence.get("source_runs", []) if r.get("provider") == provider and r.get("query_id") == row["query_id"] and r.get("plan_entry_sha256") == sha256_json(row)]
        run = runs[-1] if runs else None
        for scope in necessary_scenario_row_bindings(task, row):
            base = {"scenario_id": scope["scenario_id"], "jurisdiction": row["jurisdiction"], "right_type": row["right_type"],
                "query_id": row["query_id"], "provider": provider, "discovery_intent_id": row["discovery_intent_id"]}
            if run:
                error = source_files_error(task_dir, evidence, run) if task_dir is not None else None
                if not error and run.get("status") in {"success", "no_result"}:
                    error, _ = source_card_state(task, evidence, candidates, ledger, row, run, supplement)
                if error:
                    output.append({**base, "kind": "plan_repair", "state": "ready" if error in {
                        "API_DISCOVERY_MERGE_REQUIRED", "API_DISCOVERY_TRIAGE_REQUIRED", "API_DISCOVERY_CARD_IDENTITY_REVIEW_REQUIRED"} else "blocked", "reason": error})
                    continue
                decisions = [d for d in task.get("discovery_followups", []) if d.get("parent_query_id") == row["query_id"]
                    and d.get("source_run_id") == run["run_id"]]
                reviewed = any(d.get("role") == "review" and review_validation(task, plan, evidence, candidates, ledger, row, d, supplement) is None
                    for d in decisions)
                children = [child for _, child in rows if child.get("parent_query_id") == row["query_id"]]
                reviewed = reviewed or any(followup_validation(task, plan, evidence, candidates, ledger, child, supplement) is None for child in children)
                if reviewed:
                    continue
                output.append({**base, "kind": "plan_repair", "state": "ready", "reason": "API_DISCOVERY_REVIEW_REQUIRED",
                    "source_run_id": run["run_id"], "source_status": run.get("status"),
                    "error_code": run.get("error_code"), "discovery_scope": deepcopy(row["discovery_scope"])})
                continue
            if block:
                output.append({**base, "kind": "plan_repair", "state": "blocked", "reason": block})
            elif not run:
                output.append({**base, "kind": "source_lookup", "state": "ready", "reason": "API_DISCOVERY_PENDING"})
            elif run.get("status") not in {"success", "no_result"}:
                output.append({**base, "kind": "plan_repair", "state": "blocked", "reason": run.get("error_code") or "API_DISCOVERY_SOURCE_UNAVAILABLE"})
    for gap in plan.get("planning_gaps", []):
        if not str(gap.get("code", "")).startswith("API_DISCOVERY_"):
            continue
        country, right = gap.get("jurisdiction"), gap.get("right_type")
        if not country or not right:
            continue
        from decision_workflow import scenario_index, necessary_scenario_right_types
        for sid, scenario in scenario_index(task).items():
            if right in necessary_scenario_right_types(task, scenario):
                output.append({**gap, "scenario_id": sid, "kind": "plan_repair", "reason": gap["code"],
                    "state": "ready" if gap["code"] in {"API_DISCOVERY_TERMS_MISSING", "API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED"} else "blocked"})
    return output
