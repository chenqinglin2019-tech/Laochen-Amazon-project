"""Append-only, bounded API discovery and evidence-bound follow-up authorization.

These are discovery actions, never official coverage or risk assessments. The
only durable records are existing task follow-ups, plan rows and source runs.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from common import atomic_write_json, load_json, sha256_json, sha256_file, now_iso
from completion_policy import evidence_delivery_enabled

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


def make_row(task, provider, term, country, right, requirements, *, parent=None, role="primary", capability_basis=None,
             reserve_release=None):
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
    if evidence_delivery_enabled(task) and axis == "image" and provider not in {"serpapi_google_lens", "serper_images"}:
        raise ValueError("API_DISCOVERY_IMAGE_ROUTE_UNSUPPORTED")
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
    if capability_basis is not None:
        row["discovery_scope"]["capability_basis"] = deepcopy(capability_basis)
    if reserve_release is not None:
        row["discovery_scope"]["reserve_release"] = deepcopy(reserve_release)
    if parent:
        row.update(parent_query_id=parent["query_id"], parent_plan_entry_sha256=sha256_json(parent))
    if provider == "uspto_tmsearch_browser":
        row["query_compiler_revision"] = "tm-figurative-fields-v1" if right == "trademark_figurative" else "tm-field-tags-v1"
    if evidence_delivery_enabled(task) and provider.endswith("browser"):
        from record_browser_execution import planned_browser_query
        try:
            planned_browser_query(provider, row, task)
        except ValueError as exc:
            unsupported_field = (provider == "uspto_tmsearch_browser" and term.get("kind") not in
                {"brand", "ocr", "translation", "design_code", "mark_description"})
            raise ValueError("API_DISCOVERY_ROUTE_UNSUPPORTED" if unsupported_field else "API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED") from exc
    return bind_scenario_action(task, provider, row, purpose="discovery", obligation_key=iid)


def _account(provider):
    return "serper" if provider.startswith("serper_") else "serpapi" if provider.startswith("serpapi_") else provider


def _limits(task):
    return {p: min(int((task.get(p + "_free_enhancement") or {}).get("max_queries_per_task", 0)),
        policy_limit(task, p + "_max_requests", maximum)) for p, maximum in (("serper", 30), ("serpapi", 10), ("signa", 3))}


def _preferred_providers(task, right, term, capabilities, country=None):
    from common import serper_free_enabled, serpapi_free_enabled, signa_free_enabled
    # Current accepted APIs are preferred when their credential/capability proof
    # exists; browser access is never created here as a startup side effect.
    if term.get("discovery_channel") == "image":
        if (right == "copyright" or evidence_delivery_enabled(task) and right in {"design", "trademark_figurative"}) and term.get("image_url") and serpapi_free_enabled(task):
            yield "serpapi_google_lens"
        if serper_free_enabled(task):
            yield "serper_images"
        return
    if evidence_delivery_enabled(task) and country:
        for requirement in task.get("coverage_requirements", []):
            if (requirement.get("jurisdiction"), requirement.get("right_type"), requirement.get("phase")) != (country, right, "official_recall"):
                continue
            for route in requirement.get("routes", []):
                provider = route.get("provider")
                if provider in {"euipo_trademark", "euipo_design", "inpi_api"} and capabilities.get(provider, {}).get("executable"):
                    yield provider
    if right in {"patent", "utility_model"} and capabilities.get("epo_ops", {}).get("executable"):
        yield "epo_ops"
    if right == "trademark_word" and signa_free_enabled(task):
        yield "signa"
    if serper_free_enabled(task):
        yield "serper_patents" if right in {"patent", "utility_model", "design"} else "serper_web"
    if right in {"patent", "design"} and serpapi_free_enabled(task) and not serper_free_enabled(task):
        yield "serpapi_google_patents"


def _capacity_rows(task, plan, evidence):
    """Planning reservations only; never alter the provider consumption ledger."""
    from workflow_v24 import validated_query_cancellation
    rows = [(provider, row) for provider, values in plan.get("queries", {}).items() for row in values]
    if not evidence_delivery_enabled(task):
        return rows
    kept = []
    for provider, row in rows:
        cancelled = validated_query_cancellation(task, plan, row)
        runs = [r for r in evidence.get("source_runs", []) if r.get("provider") == provider
            and r.get("query_id") == row.get("query_id") and r.get("plan_entry_sha256") == sha256_json(row)]
        # Unknown submissions keep their reservation, including after cancellation.
        if cancelled and all(run.get("submission_state") == "not_submitted" for run in runs):
            continue
        kept.append((provider, row))
    return kept


def account_stop_reason(provider, evidence):
    """Project the existing clients' stop rules; do not redefine free entitlement."""
    if provider.startswith("serper_"):
        from serper_client import persisted_provider_block
        stopped = persisted_provider_block(evidence, entitlement_recheck=True)
        return stopped[0] if stopped else ""
    if provider.startswith("serpapi_"):
        from serpapi_patents_client import persisted_quota_block_reason
        return persisted_quota_block_reason(evidence)
    if provider == "signa":
        from signa_client import persisted_stop_reason
        return persisted_stop_reason(evidence)
    return ""


def _planning_gap_term(task, plan, gap):
    terms = list(plan.get("terms", []))
    if gap.get("search_dimension") == "image":
        image = next((i for i in task.get("images", []) if str(i.get("source_url", "")).startswith("https://")), None)
        if image:
            terms.extend({**term, "discovery_channel": "image", "image_url": image["source_url"]} for term in plan.get("terms", []))
    matches = [term for term in terms if sha256_json(term) == gap.get("term_id")]
    return matches[0] if matches else None


def _gap_providers(task, gap, term, capabilities):
    country, right = gap.get("jurisdiction"), gap.get("right_type")
    providers = list(_preferred_providers(task, right, term, capabilities, country))
    providers.extend(route["provider"] for requirement in task.get("coverage_requirements", [])
        if (requirement.get("jurisdiction"), requirement.get("right_type"), requirement.get("phase")) == (country, right, "official_recall")
        for route in requirement.get("routes", []) if route.get("provider") in INDEX
        and route.get("operation") not in {"candidate_detail", "candidate_verification", "document_retrieval"})
    return list(dict.fromkeys(providers))


def gap_limit_still_current(task, plan, evidence, candidates, ledger, gap, capabilities, supplement=None):
    """Use current routing and native account stops, not a stale gap's label."""
    if not evidence_delivery_enabled(task) or gap.get("code") in {
            "API_DISCOVERY_TERMS_MISSING", "API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED", "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP"}:
        return False
    term = _planning_gap_term(task, plan, gap)
    if term is None:
        return False
    country, right = gap.get("jurisdiction"), gap.get("right_type")
    rows = _capacity_rows(task, plan, evidence)
    limits = _limits(task)
    from necessary_completion import _route_state
    for provider in _gap_providers(task, gap, term, capabilities):
        if account_stop_reason(provider, evidence):
            continue
        try:
            make_row(task, provider, term, country, right, gap.get("requirement_ids", []),
                role="browser_fallback" if provider.endswith("browser") else "primary")
        except (ValueError, KeyError, TypeError):
            continue  # A missing native compiler is a concrete route limitation.
        cap = capabilities.get(provider)
        if cap is None or cap.get("executable") is not True and _route_state([{"provider": provider}], capabilities)[0] == "ready":
            return False  # Missing/unvalidated capability is still Agent work.
    for provider in _preferred_providers(task, right, term, capabilities, country):
        cap = capabilities.get(provider, {})
        if cap.get("executable") is not True or account_stop_reason(provider, evidence):
            continue
        account = _account(provider)
        if account in limits and sum(_account(p) == account for p, _ in rows) >= limits[account]:
            continue
        try:
            make_row(task, provider, term, country, right, gap.get("requirement_ids", []))
        except (ValueError, KeyError, TypeError):
            continue
        return False
    snapshot = {"task_id": task.get("task_id"), "sources": list(capabilities.values())}
    for provider in ("uspto_patent_browser", "uspto_tmsearch_browser"):
        basis = _capability_basis(task, snapshot, provider, country, right, term)
        if basis is None:
            continue
        count = sum(p.endswith("browser") and r.get("discovery_role") == "browser_fallback"
            and (r.get("jurisdiction"), r.get("right_type")) == (country, right) for p, r in rows)
        if count >= policy_limit(task, "browser_fallback_queries_per_scope", 2):
            continue
        try:
            make_row(task, provider, term, country, right, gap.get("requirement_ids", []),
                role="browser_fallback", capability_basis=basis)
        except (ValueError, KeyError, TypeError):
            continue
        return False
    return True


def _load_planning_context(task_dir, queries):
    task_dir = Path(task_dir)
    values = [load_json(task_dir / name) if (task_dir / name).is_file() else {}
        for name in ("search-plan.json", "evidence.json", "normalized-candidates.json", "materiality-annotations.json")]
    values[0] = {**values[0], "queries": queries}
    return values


def _reserve_release_basis(task, plan, evidence, candidates, ledger, account, supplement=None):
    """Release reserved planning capacity only after the prior wave was reviewed."""
    rows = [(p, r) for p, r in _capacity_rows(task, plan, evidence)
        if _account(p) == account and r.get("discovery_role") == "primary"]
    if not rows:
        return None
    basis = []
    for provider, row in rows:
        if retained_discovery_work(task, evidence, candidates, ledger, provider, row, supplement):
            return None
        runs = [r for r in evidence.get("source_runs", []) if r.get("provider") == provider
            and r.get("query_id") == row["query_id"] and r.get("plan_entry_sha256") == sha256_json(row)]
        if not runs:
            return None
        run = runs[-1]
        review = next((d for d in task.get("discovery_followups", [])
            if d.get("role") == "review" and d.get("parent_query_id") == row["query_id"]
            and d.get("source_run_id") == run["run_id"]
            and review_validation(task, plan, evidence, candidates, ledger, row, d, supplement) is None), None)
        if review is None:
            return None
        basis.append({"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
            "source_run_id": run["run_id"], "source_run_sha256": sha256_json(run), "review_sha256": sha256_json(review)})
    return basis


def _release_basis_valid(task, plan, evidence, candidates, ledger, basis, account, supplement=None):
    if not isinstance(basis, list) or not basis or len({b.get("query_id") for b in basis if isinstance(b, dict)}) != len(basis):
        return False
    from workflow_v24 import plan_row_index
    for item in basis:
        matches = plan_row_index(plan).get(item.get("query_id"), [])
        if len(matches) != 1:
            return False
        provider, row = matches[0]
        if _account(provider) != account or row.get("discovery_role") != "primary" or sha256_json(row) != item.get("plan_entry_sha256"):
            return False
        if retained_discovery_work(task, evidence, candidates, ledger, provider, row, supplement):
            return False
        runs = [r for r in evidence.get("source_runs", []) if r.get("provider") == provider
            and r.get("query_id") == row["query_id"] and r.get("plan_entry_sha256") == sha256_json(row)]
        if not runs or runs[-1].get("run_id") != item.get("source_run_id") or sha256_json(runs[-1]) != item.get("source_run_sha256"):
            return False
        if not any(sha256_json(d) == item.get("review_sha256") and review_validation(
            task, plan, evidence, candidates, ledger, row, d, supplement) is None for d in task.get("discovery_followups", [])):
            return False
    return True


def _capability_basis(task, snapshot, provider, country, right, term):
    """A preflight absence is real evidence; no failing paid request is required."""
    if (dimension(term) == "image" or not isinstance(snapshot, dict) or snapshot.get("task_id") != task.get("task_id")
            or not isinstance(snapshot.get("sources"), list)):
        return None
    capabilities = {row.get("provider"): row for row in snapshot["sources"] if isinstance(row, dict)}
    browser_cap = capabilities.get(provider, {})
    if not (browser_cap.get("executable") is True or browser_cap.get("reason") == "browser_adapter_requires_real_route_acceptance"):
        return None
    reasons = []
    for api in dict.fromkeys(_preferred_providers(task, right, term, capabilities, country)):
        cap = capabilities.get(api)
        if cap is None:
            return None  # Unknown capability is not a proven source absence.
        if cap.get("executable") is not True:
            reasons.append({"provider": api, "reason": cap.get("reason") or "SOURCE_CAPABILITY_UNAVAILABLE"})
            continue
        try:
            provider_params(api, term, country, right)
        except ValueError as exc:
            reasons.append({"provider": api, "reason": str(exc)})
            continue
        return None
    routes = [route for requirement in task.get("coverage_requirements", [])
        if (requirement.get("jurisdiction"), requirement.get("right_type"), requirement.get("phase")) == (country, right, "official_recall")
        for route in requirement.get("routes", []) if route.get("provider") == provider
        and route.get("operation") in {"patent_recall", "design_recall", "trademark_recall"}]
    if len(routes) != 1:
        return None
    return {"task_id": task["task_id"], "jurisdiction": country, "right_type": right,
        "provider": provider, "operation": routes[0]["operation"], "term": deepcopy(term),
        "snapshot_sha256": sha256_json(snapshot), "unavailable_api_routes": reasons,
        "policy_sha256": sha256_json({k: task.get(k) for k in ("retrieval_policy", "serper_free_enhancement", "serpapi_free_enhancement", "signa_free_enhancement")}),
        "reason": "no_usable_authorized_api"}


def _capability_basis_error(task, provider, row, snapshot=None):
    basis = row.get("discovery_scope", {}).get("capability_basis")
    if not evidence_delivery_enabled(task) or not isinstance(basis, dict):
        return "API_DISCOVERY_CAPABILITY_BASIS_REQUIRED"
    if (row.get("discovery_role") != "browser_fallback" or row.get("parent_query_id")
            or row.get("refinement_round") != 0 or provider not in {"uspto_patent_browser", "uspto_tmsearch_browser"}
            or any(basis.get(k) != expected for k, expected in (("task_id", task.get("task_id")),
                ("jurisdiction", row.get("jurisdiction")), ("right_type", row.get("right_type")), ("provider", provider), ("operation", row.get("operation"))))):
        return "API_DISCOVERY_CAPABILITY_BINDING_MISMATCH"
    policy = {k: task.get(k) for k in ("retrieval_policy", "serper_free_enhancement", "serpapi_free_enhancement", "signa_free_enhancement")}
    if basis.get("policy_sha256") != sha256_json(policy) or not re.fullmatch(r"[0-9a-f]{64}", str(basis.get("snapshot_sha256") or "")):
        return "API_DISCOVERY_CAPABILITY_BINDING_MISMATCH"
    try:
        expected = make_row(task, provider, basis["term"], row["jurisdiction"], row["right_type"],
            row["requirement_ids"], role="browser_fallback", capability_basis=basis)
        if expected != row:
            return "API_DISCOVERY_CAPABILITY_BINDING_MISMATCH"
    except (ValueError, KeyError, TypeError):
        return "API_DISCOVERY_CAPABILITY_BINDING_MISMATCH"
    if snapshot is not None and _capability_basis(task, snapshot, provider, row["jurisdiction"], row["right_type"], basis["term"]) != basis:
        return "API_DISCOVERY_CAPABILITY_SNAPSHOT_CHANGED"
    return None


def _figurative_not_applicable(task, plan, evidence, candidates, ledger, sid, country, supplement=None):
    if not evidence_delivery_enabled(task) or task.get("specialty_workflow_revision") != "asset-scope-v1":
        return False
    from record_asset_provenance import asset_scope, INVESTIGATION_STEPS
    from workflow_v24 import necessary_scenario_row_bindings
    from assessment_v24 import query_coverage
    inventory = asset_scope(task, sid, "trademark_figurative")
    if not inventory["inventory_reviewed"] or inventory["asset_ids"]:
        return False
    completed = set()
    for row in plan.get("queries", {}).get("asset_provenance", []):
        if (row.get("jurisdiction"), row.get("right_type")) != (country, "trademark_figurative") or not any(
                binding["scenario_id"] == sid for binding in necessary_scenario_row_bindings(task, row)):
            continue
        result = query_coverage(evidence, candidates, plan, "asset_provenance", row, task,
            strict_lineage=True, ledger=ledger, supplement=supplement, scenario_id=sid)
        if result.get("complete") and result.get("investigation_status") == "completed":
            completed.add(row.get("search_dimension"))
    return set(INVESTIGATION_STEPS["trademark_figurative"]) <= completed


def append_initial(task_dir, task, terms, queries, gaps, expansion_queue):
    """Round-robin countries and rights without dropping unplanned clues."""
    from workflow_v24 import _applicable, _target_language_compatible, _add
    from decision_workflow import scenario_index, necessary_scenario_right_types
    cap_path = Path(task_dir) / "source-capabilities.json"
    raw_caps = load_json(cap_path) if cap_path.is_file() else {}
    values = raw_caps.get("providers", raw_caps.get("sources", []))
    capabilities = values if isinstance(values, dict) else {v.get("provider"): v for v in values if isinstance(v, dict)}
    v2 = evidence_delivery_enabled(task)
    context_plan, evidence, candidates, ledger = _load_planning_context(task_dir, queries) if v2 else ({}, {}, {}, {})
    supplement = None
    if v2:
        from workflow_v24 import scenario_supplement
        supplement = scenario_supplement(Path(task_dir), task=task, evidence=evidence)
    applicable_rights = set().union(*(necessary_scenario_right_types(task, s) for s in scenario_index(task).values()))
    requirements = [r for r in task.get("coverage_requirements", []) if r.get("phase") in {"official_recall", "provenance"}
        and r.get("right_type") in applicable_rights]
    buckets = {}
    for country in task["target_jurisdictions"]:
        for right in sorted({r["right_type"] for r in requirements if r["jurisdiction"] == country}):
            if right == "trademark_figurative" and v2:
                relevant_scenarios = [sid for sid, scenario in scenario_index(task).items()
                    if right in necessary_scenario_right_types(task, scenario)]
                if relevant_scenarios and all(_figurative_not_applicable(task, context_plan, evidence, candidates, ledger,
                        sid, country, supplement) for sid in relevant_scenarios):
                    continue
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
    capacity_rows = _capacity_rows(task, context_plan, evidence) if v2 else [(p, r) for p, rows in queries.items() for r in rows]
    used = {p: sum(_account(provider) == p for provider, row in capacity_rows) for p in limits}
    release = {account: _reserve_release_basis(task, context_plan, evidence, candidates, ledger, account, supplement)
        for account in limits} if v2 else {}
    for account, basis in list(release.items()):
        if basis and _release_basis_files_error(task_dir, evidence, basis):
            release[account] = None
    existing = {r.get("discovery_intent_id") for values in queries.values() for r in values
        if r.get("discovery_role") == "primary" or v2 and r.get("discovery_scope", {}).get("capability_basis")}
    countries = {country: i for i, country in enumerate(task["target_jurisdictions"])}
    rights = {r: i for i, r in enumerate(("patent", "design", "utility_model", "trademark_word", "trademark_figurative", "copyright", "trade_dress", "unregistered_design"))}
    bucket_order = sorted(buckets, key=lambda key: (rights.get(key[1], 99), countries[key[0]]))
    if v2:
        # A diagonal round-robin spreads a small shared budget over both rights
        # and countries. Every available scope gets its first turn before a
        # second expression from that scope; dimensions are interleaved above.
        right_order = sorted({key[1] for key in buckets}, key=lambda right: rights.get(right, 99))
        bucket_order = [(country, right_order[(index + offset) % len(right_order)])
            for offset in range(len(right_order)) for index, country in enumerate(task["target_jurisdictions"])
            if (country, right_order[(index + offset) % len(right_order)]) in buckets] if right_order else []
    order = [(key, buckets[key][i]) for i in range(max(map(len, buckets.values()), default=0))
        for key in bucket_order if i < len(buckets[key])]
    # Structural clues drive discovery precision. Preserve their country round
    # robin ahead of secondary identity/provenance expressions.
    def core(item):
        return item[0][1] in {"patent", "utility_model"} and item[1][0]["kind"] in {"structural_feature", "function", "cpc", "ipc"}
    if not v2:
        order = [item for item in order if core(item)] + [item for item in order if not core(item)]
    else:
        covered = {(row.get("jurisdiction"), row.get("right_type"), row.get("search_dimension")) for _, row in capacity_rows
            if row.get("action_purpose") == "discovery"}
        order.sort(key=lambda item: (*item[0], dimension(item[1][0])) in covered)
    for (country, right), (term, refs) in order:
        iid = intent_id(country, right, dimension(term), term)
        if iid in existing:
            continue
        reason, selected = "API_DISCOVERY_ROUTE_UNAVAILABLE", None
        stopped_sources = []
        for provider in _preferred_providers(task, right, term, capabilities, country):
            account = _account(provider)
            stopped = account_stop_reason(provider, evidence) if v2 else ""
            if stopped:
                reason = "API_DISCOVERY_ACCOUNT_STOPPED"
                stopped_sources.append({"provider": provider, "reason": stopped})
                continue
            if v2 and provider in capabilities and capabilities[provider].get("executable") is not True:
                reason = "API_DISCOVERY_ROUTE_UNAVAILABLE"
                continue
            ceiling = limits.get(account) if release.get(account) else initial_limits.get(account)
            if account in limits and used[account] >= ceiling:
                reason = "API_DISCOVERY_BUDGET_EXHAUSTED" if used[account] >= limits[account] else "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP"
                continue
            try:
                selected = provider, make_row(task, provider, term, country, right, refs,
                    reserve_release=release[account] if v2 and account in limits and used[account] >= initial_limits[account] else None)
            except ValueError as exc:
                reason = str(exc)
                continue
            break
        if v2 and selected is None and reason not in {"API_DISCOVERY_BUDGET_EXHAUSTED", "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP"}:
            for provider in ("uspto_patent_browser", "uspto_tmsearch_browser"):
                basis = _capability_basis(task, raw_caps, provider, country, right, term)
                if basis is None:
                    continue
                count = sum(p.endswith("browser") and (r.get("jurisdiction"), r.get("right_type")) == (country, right)
                    and r.get("discovery_role") == "browser_fallback" for p, r in capacity_rows)
                if count >= policy_limit(task, "browser_fallback_queries_per_scope", 2):
                    reason = "API_DISCOVERY_BROWSER_SCOPE_LIMIT"
                    break
                try:
                    selected = provider, make_row(task, provider, term, country, right, refs,
                        role="browser_fallback", capability_basis=basis)
                except ValueError as exc:
                    reason = str(exc)
                    continue
                break
        if selected:
            provider, row = selected
            _add(queries, provider, row)
            if _account(provider) in used:
                used[_account(provider)] += 1
            capacity_rows.append((provider, row))
            expansion_queue.append({"query_id": row["query_id"], "discovery_intent_id": iid, "provider": provider,
                "jurisdiction": country, "right_type": right, "state": "scheduled", "reason": "api_first_discovery"})
        else:
            gaps.append({"code": reason, "discovery_intent_id": iid, "jurisdiction": country, "right_type": right,
                "search_dimension": dimension(term), "requirement_ids": refs, "derived_from": [term["derived_from"]],
                "term_id": sha256_json(term), "assigned_to": "agent", "blocking_planning": False,
                **({"source_constraints": stopped_sources} if stopped_sources else {})})


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


def retained_discovery_work(task, evidence, candidates, ledger, provider, row, supplement=None, *, task_dir=None):
    """A later attempt never erases cards already obtained for this exact row."""
    if not evidence_delivery_enabled(task) or row.get("action_purpose") != "discovery":
        return None
    from assessment_v24 import _source_records
    pending = []
    review_codes = {"API_DISCOVERY_MERGE_REQUIRED", "API_DISCOVERY_TRIAGE_REQUIRED", "API_DISCOVERY_CARD_IDENTITY_REVIEW_REQUIRED"}
    for run in evidence.get("source_runs", []):
        if (run.get("provider") != provider or run.get("query_id") != row.get("query_id")
                or run.get("plan_entry_sha256") != sha256_json(row)):
            continue
        records = _source_records(evidence, run.get("run_id"))
        if run.get("status") not in {"success", "no_result"} and not records:
            continue  # A failed receipt with no cards remains submission/access work.
        # Partial failures can still contain real cards; validate them using the
        # successful-card contract without changing the original run or status.
        card_run = {**run, "status": "success"} if records and run.get("status") not in {"success", "no_result"} else run
        error = source_files_error(task_dir, evidence, card_run) if task_dir is not None else None
        if not error:
            error, _ = source_card_state(task, evidence, candidates, ledger, row, run, supplement)
        if error:
            pending.append((error, run))
    if not pending:
        return None
    # One resumable card-work item, separate from any unresolved submission.
    error = next((error for error, _ in pending if error not in review_codes), pending[0][0])
    return {"kind": "triage" if error in review_codes else "plan_repair",
        "state": "awaiting_review" if error in review_codes else "blocked", "reason": error,
        "retained_source_run_ids": [run["run_id"] for _, run in pending],
        "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)} for _, run in pending],
        **({} if error in review_codes else {"integrity_failure": True})}


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
            or (run.get("submission_state") not in {"submitted", "not_submitted"}
                and not _unknown_review_valid(task, evidence, candidates, ledger, row, review, run, supplement))
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
    if not review.get("submission_review"):
        pending = retained_discovery_work(task, evidence, candidates, ledger, run.get("provider"), row, supplement)
        if pending:
            return pending["reason"]
    return None


def _unknown_review_valid(task, evidence, candidates, ledger, row, review, run, supplement=None):
    """An audit records remaining uncertainty; it never authorizes another request."""
    audit = review.get("submission_review")
    if (not evidence_delivery_enabled(task) or not isinstance(audit, dict)
            or audit.get("state") != "unknown_after_receipt_review" or review.get("outcome") != "blocked"
            or not str(audit.get("reasoning") or "").strip() or audit.get("source_run_sha256") != sha256_json(run)
            or run.get("submission_state") in {"submitted", "not_submitted"}
            or review.get("triage_digest") != triage_digest(task, evidence, candidates, ledger, supplement, query_id=row["query_id"])):
        return False
    paths = run.get("raw_paths", [])
    receipts = audit.get("raw_receipts")
    if not isinstance(paths, list) or not isinstance(receipts, list) or len(paths) != len(receipts):
        return False
    if not paths:
        return bool(str(audit.get("raw_receipt_absence_reason") or "").strip())
    if len(paths) != 1 or not run.get("payload_digest"):
        return False
    return all(isinstance(receipt, dict) and receipt.get("path") == path
        and receipt.get("sha256") == run["payload_digest"] and type(receipt.get("bytes")) is int
        and receipt["bytes"] >= 0 for path, receipt in zip(paths, receipts))


def reviewed_unknown_submission(task, plan, evidence, candidates, ledger, row, supplement=None, *, task_dir=None):
    """Return hash-bound audits for every still-unknown exact source run."""
    if not evidence_delivery_enabled(task):
        return None
    from workflow_v24 import action_attempt_state
    providers = [p for p, values in plan.get("queries", {}).items() if row in values]
    if len(providers) != 1:
        return None
    provider = providers[0]
    state = action_attempt_state(evidence, provider, row)
    known = {r.get("source_run_id") for r in state.get("submission_reviews", [])}
    unknown = [r for r in evidence.get("source_runs", []) if r.get("provider") == provider
        and r.get("query_id") == row["query_id"] and r.get("plan_entry_sha256") == sha256_json(row)
        and r.get("submission_state") not in {"submitted", "not_submitted"} and r.get("run_id") not in known]
    if not unknown:
        return None
    result = []
    for run in unknown:
        review = next((d for d in reversed(task.get("discovery_followups", []))
            if d.get("parent_query_id") == row["query_id"] and d.get("source_run_id") == run["run_id"]
            and _unknown_review_valid(task, evidence, candidates, ledger, row, d, run, supplement)
            and review_validation(task, plan, evidence, candidates, ledger, row, d, supplement) is None), None)
        if review is None:
            return None
        if task_dir is not None:
            if source_files_error(task_dir, evidence, run):
                return None
            for receipt in review["submission_review"]["raw_receipts"]:
                path = (Path(task_dir) / receipt["path"]).resolve()
                if not path.is_relative_to(Path(task_dir).resolve()) or not path.is_file() or path.stat().st_size != receipt["bytes"]:
                    return None
        result.append({"run_id": run["run_id"], "source_run_sha256": sha256_json(run),
            "review_sha256": sha256_json(review), "submission_state": run.get("submission_state", "unknown")})
    return result


def append_review(task_dir, task, plan, evidence, parent, request):
    from workflow_v24 import scenario_supplement
    candidates = load_json(task_dir / "normalized-candidates.json")
    ledger = load_json(task_dir / "materiality-annotations.json")
    runs = [r for r in evidence.get("source_runs", []) if r.get("run_id") == request.get("source_run_id")]
    if len(runs) != 1:
        raise ValueError("API_DISCOVERY_SOURCE_RUN_REQUIRED")
    record = {k: deepcopy(request.get(k)) for k in ("source_run_id", "reason", "reviewer", "evidence_ids", "triage_digest", "outcome", "blocker")}
    record.update(role="review", parent_query_id=parent["query_id"], parent_plan_entry_sha256=sha256_json(parent),
        source_run_sha256=sha256_json(runs[0]), discovery_scope=deepcopy(parent.get("discovery_scope")), reviewed_at=now_iso())
    if request.get("submission_review") is not None:
        requested = request["submission_review"]
        if not evidence_delivery_enabled(task) or not isinstance(requested, dict):
            raise ValueError("API_DISCOVERY_SUBMISSION_REVIEW_INVALID")
        receipts = []
        for relative in runs[0].get("raw_paths", []):
            path = (Path(task_dir) / relative).resolve()
            if not path.is_relative_to(Path(task_dir).resolve()) or not path.is_file():
                raise ValueError("API_DISCOVERY_SOURCE_FILES_INVALID")
            receipts.append({"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size})
        record["submission_review"] = {"state": requested.get("state"), "reasoning": requested.get("reasoning"),
            "source_run_sha256": sha256_json(runs[0]), "raw_receipts": receipts,
            **({"raw_receipt_absence_reason": requested.get("raw_receipt_absence_reason")} if not receipts else {})}
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
    if evidence_delivery_enabled(task) and row.get("discovery_scope", {}).get("capability_basis"):
        providers = [p for p, values in plan.get("queries", {}).items() if row in values]
        return _capability_basis_error(task, providers[0], row) if len(providers) == 1 else "API_DISCOVERY_CAPABILITY_BINDING_MISMATCH"
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
    pending = retained_discovery_work(task, evidence, candidates, ledger, parent_provider, parent, supplement)
    if pending:
        return pending["reason"]
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
    if evidence_delivery_enabled(task):
        account = _account(provider)
        limits = _limits(task)
        capacity_rows = _capacity_rows(task, plan, evidence)
        from workflow_v24 import action_attempt_state
        attempts = action_attempt_state(evidence, provider, row)
        audited_not_submitted = {r.get("source_run_id") for r in attempts.get("submission_reviews", [])}
        if any(r.get("provider") == provider and r.get("query_id") == row["query_id"]
                and r.get("plan_entry_sha256") == sha256_json(row)
                and r.get("submission_state") not in {"submitted", "not_submitted"}
                and r.get("run_id") not in audited_not_submitted for r in evidence.get("source_runs", [])):
            return "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY"
        pending = retained_discovery_work(task, evidence, candidates, ledger, provider, row, supplement)
        if pending:
            return pending["reason"]
        if account in limits:
            account_rows = [r for p, r in capacity_rows if _account(p) == account]
            if len(account_rows) > limits[account]:
                return "API_DISCOVERY_BUDGET_EXHAUSTED"
            reserve = row.get("discovery_scope", {}).get("reserve_release")
            if reserve is not None and not _release_basis_valid(task, plan, evidence, candidates, ledger, reserve, account, supplement):
                return "API_DISCOVERY_RESERVE_RELEASE_INVALID"
            initial_limit = limits[account] - (max(2, limits[account] // 4) if limits[account] >= 8 else 0)
            if sum(r.get("discovery_role") == "primary" and not r.get("discovery_scope", {}).get("reserve_release") for r in account_rows) > initial_limit:
                return "API_DISCOVERY_RESERVE_RELEASE_REQUIRED"
    if role == "primary":
        from common import serper_free_enabled
        if provider == "serpapi_google_patents" and serper_free_enabled(task):
            return "API_DISCOVERY_FALLBACK_DECISION_REQUIRED"
        if provider not in API_PROVIDERS or row.get("refinement_round") != 0 or row.get("parent_query_id"):
            return "API_DISCOVERY_PRIMARY_INVALID"
        return None
    all_rows = [(p, r) for p, values in plan.get("queries", {}).items() for r in values]
    if browser:
        bounded_rows = _capacity_rows(task, plan, evidence) if evidence_delivery_enabled(task) else all_rows
        same = [r for p, r in bounded_rows if p.endswith("browser") and r.get("discovery_role") == "browser_fallback"
            and (r.get("jurisdiction"), r.get("right_type")) == (row.get("jurisdiction"), row.get("right_type"))]
        if len(same) > max_browser_queries:
            return "API_DISCOVERY_BROWSER_SCOPE_LIMIT"
        if evidence_delivery_enabled(task) and row.get("discovery_scope", {}).get("capability_basis"):
            return _capability_basis_error(task, provider, row)
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
    if evidence_delivery_enabled(task) and row.get("discovery_scope", {}).get("reserve_release"):
        error = _release_basis_files_error(task_dir, evidence, row["discovery_scope"]["reserve_release"])
        if error:
            return error
    if evidence_delivery_enabled(task) and row.get("discovery_scope", {}).get("capability_basis"):
        path = Path(task_dir) / "source-capabilities.json"
        if not path.is_file():
            return "API_DISCOVERY_CAPABILITY_SNAPSHOT_REQUIRED"
        try:
            return _capability_basis_error(task, row["discovery_scope"]["capability_basis"]["provider"], row, load_json(path))
        except (OSError, ValueError, KeyError, TypeError):
            return "API_DISCOVERY_CAPABILITY_SNAPSHOT_INVALID"
    if not enabled(task) or row.get("discovery_role") not in FOLLOWUP_ROLES:
        return None
    decisions = [d for d in task.get("discovery_followups", []) if d.get("query_id") == row.get("query_id")]
    if len(decisions) != 1:
        return "API_DISCOVERY_FOLLOWUP_DECISION_REQUIRED"
    run = next((r for r in evidence.get("source_runs", []) if r.get("run_id") == decisions[0].get("source_run_id")), {})
    return source_files_error(task_dir, evidence, run)


def _release_basis_files_error(task_dir, evidence, basis):
    for item in basis:
        runs = [r for r in evidence.get("source_runs", []) if r.get("run_id") == item.get("source_run_id")]
        if len(runs) != 1:
            return "API_DISCOVERY_SOURCE_RUN_REQUIRED"
        error = source_files_error(task_dir, evidence, runs[0])
        if error:
            return error
    return None


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
    if evidence_delivery_enabled(task) and parent.get("discovery_scope", {}).get("capability_basis"):
        if (request.get("provider", old_provider) != old_provider
                or any(not str(request.get(k) or "").strip() for k in ("reason", "reviewer"))):
            raise ValueError("API_DISCOVERY_PLAN_REPAIR_NOT_APPLICABLE")
        if any(r.get("query_id") == parent["query_id"] and r.get("plan_entry_sha256") == sha256_json(parent)
                and r.get("submission_state") != "not_submitted" for r in evidence.get("source_runs", [])):
            raise ValueError("API_DISCOVERY_PLAN_REPAIR_ALREADY_SUBMITTED")
        path = Path(task_dir) / "source-capabilities.json"
        if not path.is_file():
            raise ValueError("API_DISCOVERY_CAPABILITY_SNAPSHOT_REQUIRED")
        term = parent["discovery_scope"]["capability_basis"]["term"]
        if request.get("term", term) != term:
            raise ValueError("API_DISCOVERY_PLAN_REPAIR_CHANGED_QUERY")
        basis = _capability_basis(task, load_json(path), old_provider, parent["jurisdiction"], parent["right_type"], term)
        if basis is None:
            raise ValueError("API_DISCOVERY_CAPABILITY_BASIS_REQUIRED")
        if basis == parent["discovery_scope"]["capability_basis"]:
            raise ValueError("API_DISCOVERY_PLAN_REPAIR_UNCHANGED")
        row = make_row(task, old_provider, term, parent["jurisdiction"], parent["right_type"], parent["requirement_ids"],
            role="browser_fallback", capability_basis=basis)
        trial_plan = deepcopy(plan)
        trial_plan.setdefault("execution_dispositions", []).append({"query_id": parent["query_id"],
            "plan_entry_sha256": sha256_json(parent), "status": "cancelled", "reason": request["reason"],
            "reason_code": "API_DISCOVERY_CAPABILITY_SNAPSHOT_REBOUND", "reviewer": request["reviewer"], "created_at": now_iso()})
        _add(trial_plan["queries"], old_provider, row)
        candidates, ledger = (load_json(Path(task_dir) / name) for name in ("normalized-candidates.json", "materiality-annotations.json"))
        error = dispatch_block(task, trial_plan, evidence, candidates, ledger, old_provider, row)
        if error:
            raise ValueError(error)
        task.setdefault("discovery_followups", []).append({"role": "plan_repair", "parent_query_id": parent["query_id"],
            "parent_plan_entry_sha256": sha256_json(parent), "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
            "reason": request["reason"], "reviewer": request["reviewer"], "reviewed_at": now_iso()})
        atomic_write_json(Path(task_dir) / "task.json", task)
        atomic_write_json(Path(task_dir) / "search-plan.json", trial_plan)
        return row
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
    if sum(_account(provider) == "serper" for provider, _ in _capacity_rows(task, plan, evidence)) >= _limits(task)["serper"]:
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
    if account in _limits(task) and sum(_account(p) == account for p, _ in _capacity_rows(task, trial_plan, evidence)) > _limits(task)[account]:
        raise ValueError("API_DISCOVERY_BUDGET_EXHAUSTED")
    # A partially written task cannot authorize execution without the exact
    # second plan write; validation rejects missing/mismatched rows.
    atomic_write_json(task_dir / "task.json", trial_task)
    atomic_write_json(task_dir / "search-plan.json", trial_plan)
    return row


def _next_work_v2(task, plan, evidence, candidates, ledger, supplement=None, *, task_dir=None,
                  source_capabilities=None, browser_status=None):
    from workflow_v24 import (necessary_scenario_row_bindings, validated_query_cancellation,
        action_attempt_state, browser_submitted_failure_state, browser_partial_recovery_state)
    from decision_workflow import scenario_index, necessary_scenario_right_types
    if source_capabilities is None:
        path = Path(task_dir) / "source-capabilities.json" if task_dir is not None else None
        snapshot = load_json(path) if path is not None and path.is_file() else {}
        source_capabilities = {r.get("provider"): r for r in snapshot.get("sources", []) if isinstance(r, dict)}
    if browser_status is None and task_dir is not None:
        path = Path(task_dir) / "browser-execution-status.json"
        browser_status = load_json(path) if path.is_file() else {}
    browser_rows = {r.get("query_id"): r for r in (browser_status or {}).get("queries", []) if isinstance(r, dict)}
    capabilities = source_capabilities or {}
    rows = [(p, r) for p, values in plan.get("queries", {}).items() for r in values if r.get("action_purpose") == "discovery"]
    output, na = [], {}
    access_reasons = {"optional_credentials_missing", "OPTIONAL_CREDENTIALS_MISSING", "CREDENTIAL_MISSING",
        "AUTH_REQUIRED", "LOGIN_REQUIRED", "CAPTCHA_REQUIRED", "MFA_REQUIRED", "CONSENT_REQUIRED", "QR_REQUIRED",
        "ACCESS_INTERACTION_REQUIRED", "QUOTA_EXHAUSTED", "FREE_QUOTA_EXHAUSTED", "RATE_LIMITED"}

    def not_applicable(sid, country, right):
        if right != "trademark_figurative":
            return False
        key = sid, country
        if key not in na:
            na[key] = _figurative_not_applicable(task, plan, evidence, candidates, ledger, sid, country, supplement)
        return na[key]

    def limit_proof(reason, runs=(), providers=(), gap=None):
        cap_fields = ("provider", "state", "reason", "executable", "credentials_present", "checked_at", "cost_ceiling_usd")
        return {"kind": "source_constraint", "reason": reason, "official_verification": "not_verified",
            "source_run_refs": [{"run_id": r.get("run_id"), "sha256": sha256_json(r)} for r in runs],
            "capability_refs": [{"provider": provider, "sha256": sha256_json({k: capabilities[provider][k]
                for k in cap_fields if k in capabilities[provider]})}
                for provider in dict.fromkeys(providers) if provider in capabilities],
            **({"planning_gap_sha256": sha256_json(gap)} if gap is not None else {})}

    for provider, row in rows:
        runs = [r for r in evidence.get("source_runs", []) if r.get("provider") == provider
            and r.get("query_id") == row["query_id"] and r.get("plan_entry_sha256") == sha256_json(row)]
        run = runs[-1] if runs else None
        attempt = action_attempt_state(evidence, provider, row)
        audited = {r.get("source_run_id") for r in attempt.get("submission_reviews", [])}
        unknown = [r for r in runs if r.get("submission_state") not in {"submitted", "not_submitted"}
            and r.get("run_id") not in audited]
        retained_work = retained_discovery_work(task, evidence, candidates, ledger, provider, row, supplement, task_dir=task_dir)
        if validated_query_cancellation(task, plan, row) and not unknown and not retained_work:
            continue
        block = dispatch_block(task, plan, evidence, candidates, ledger, provider, row, supplement)
        current = browser_rows.get(row["query_id"], {})
        if current.get("plan_entry_sha256") != sha256_json(row):
            current = {}
        for scope in necessary_scenario_row_bindings(task, row):
            if not retained_work and not_applicable(scope["scenario_id"], row["jurisdiction"], row["right_type"]):
                continue
            base = {"scenario_id": scope["scenario_id"], "jurisdiction": row["jurisdiction"], "right_type": row["right_type"],
                "query_id": row["query_id"], "provider": provider, "discovery_intent_id": row["discovery_intent_id"],
                "plan_entry_sha256": sha256_json(row)}
            if retained_work:
                output.append({**base, **retained_work})
            if unknown:
                reviewed = reviewed_unknown_submission(task, plan, evidence, candidates, ledger, row, supplement, task_dir=task_dir)
                if reviewed:
                    reason = "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW"
                    output.append({**base, "kind": "source_lookup", "state": "blocked", "reason": reason, "submission_state": "unknown",
                        "delivery_limit": {**limit_proof(reason, unknown, [provider]), "submission_review_refs": reviewed}})
                else:
                    output.append({**base, "kind": "source_lookup", "state": "submission_unknown",
                        "reason": "VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY", "delivery_limit": limit_proof("submission_unknown", unknown, [provider])})
                continue
            if retained_work:
                continue
            if not run and task_dir is not None:
                pending_error = followup_source_files_error(task_dir, task, evidence, row)
                if pending_error:
                    repair = pending_error in {"API_DISCOVERY_CAPABILITY_SNAPSHOT_CHANGED", "API_DISCOVERY_CAPABILITY_SNAPSHOT_REQUIRED"}
                    output.append({**base, "kind": "plan_repair", "state": "ready" if repair else "blocked",
                        "reason": pending_error, **({"parent_query_id": row["query_id"]} if repair else {"integrity_failure": True})})
                    continue
            error = source_files_error(task_dir, evidence, run) if task_dir is not None and run else None
            if error:
                output.append({**base, "kind": "plan_repair", "state": "blocked", "reason": error,
                    "integrity_failure": True})
                continue
            decisions = [d for d in task.get("discovery_followups", []) if run
                and d.get("parent_query_id") == row["query_id"] and d.get("source_run_id") == run["run_id"]]
            reviews = [d for d in decisions if d.get("role") == "review"
                and review_validation(task, plan, evidence, candidates, ledger, row, d, supplement) is None]
            children = [child for _, child in rows if child.get("parent_query_id") == row["query_id"]
                and not validated_query_cancellation(task, plan, child)]
            if any(followup_validation(task, plan, evidence, candidates, ledger, child, supplement) is None for child in children):
                continue
            recovery = None
            if run:
                if run.get("error_code") in {"UNSUPPORTED_QUERY_SEMANTICS", "USPTO_QUERY_REJECTED", "API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED"}:
                    output.append({**base, "kind": "plan_repair", "state": "ready", "reason": run["error_code"],
                        "source_run_id": run["run_id"]})
                    continue
                recovery = (browser_submitted_failure_state(task, evidence, provider, row)
                    or browser_partial_recovery_state(task, evidence, provider, row, current))
                if recovery and recovery.get("state") in {"ready", "submission_unknown"}:
                    output.append({**base, "kind": "source_lookup", **recovery})
                    continue
            if reviews:
                if run.get("status") not in {"success", "no_result"}:
                    reason = run.get("error_code") or "API_DISCOVERY_SOURCE_UNAVAILABLE"
                    output.append({**base, "kind": "source_lookup", "state": "awaiting_access" if reason in access_reasons else "blocked",
                        "reason": reason, "delivery_limit": limit_proof(reason, runs, [provider]),
                        "discovery_review_sha256": sha256_json(reviews[-1])})
                continue
            if run:
                output.append({**base, "kind": "plan_repair", "state": "ready", "reason": "API_DISCOVERY_REVIEW_REQUIRED",
                    "source_run_id": run["run_id"], "source_status": run.get("status"), "error_code": run.get("error_code"),
                    "discovery_scope": deepcopy(row["discovery_scope"]),
                    **({"delivery_limit": limit_proof(recovery["reason"], runs, [provider])} if recovery else {})})
                continue
            if block:
                output.append({**base, "kind": "plan_repair", "state": "blocked", "reason": block})
                continue
            stopped = account_stop_reason(provider, evidence)
            if stopped:
                account_runs = [r for r in evidence.get("source_runs", []) if _account(str(r.get("provider") or "")) == _account(provider)]
                output.append({**base, "kind": "source_lookup", "state": "blocked", "reason": "API_DISCOVERY_ACCOUNT_STOPPED",
                    "source_stop_reason": stopped, "delivery_limit": limit_proof("API_DISCOVERY_ACCOUNT_STOPPED", account_runs, [provider])})
                continue
            cap = capabilities.get(provider, {})
            from runtime_v24 import operation_accepted
            if cap and not cap.get("executable") and not operation_accepted(cap, row) and cap.get("reason") != "browser_adapter_requires_real_route_acceptance":
                from necessary_completion import _route_state
                reason = cap.get("reason") or "SOURCE_CAPABILITY_UNAVAILABLE"
                state, _ = _route_state([{"provider": provider}], capabilities)
                output.append({**base, "kind": "source_lookup", "state": state, "reason": reason,
                    **({"delivery_limit": limit_proof(reason, providers=[provider])} if state != "ready" else {})})
            else:
                output.append({**base, "kind": "source_lookup", "state": "ready", "reason": "API_DISCOVERY_PENDING"})

    active_intents = {row["discovery_intent_id"] for _, row in _capacity_rows(task, plan, evidence) if row.get("discovery_intent_id")}
    for gap in plan.get("planning_gaps", []):
        code, country, right = gap.get("code", ""), gap.get("jurisdiction"), gap.get("right_type")
        if not code.startswith("API_DISCOVERY_") or not country or not right or gap.get("discovery_intent_id") in active_intents:
            continue
        for sid, scenario in scenario_index(task).items():
            if right not in necessary_scenario_right_types(task, scenario) or not_applicable(sid, country, right):
                continue
            ready = code in {"API_DISCOVERY_TERMS_MISSING", "API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED", "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP"}
            base = {**gap, "scenario_id": sid, "kind": "plan_repair", "reason": code, "state": "ready" if ready else "blocked"}
            if code == "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP":
                base["reserve_release_available"] = any(_reserve_release_basis(task, plan, evidence, candidates, ledger,
                    account, supplement) for account in _limits(task))
            if not ready:
                if not gap_limit_still_current(task, plan, evidence, candidates, ledger, gap, capabilities, supplement):
                    base.update(state="ready", reason="API_DISCOVERY_REPLAN_REQUIRED", planning_gap=code)
                    output.append(base)
                    continue
                runs = [r for r in evidence.get("source_runs", []) if (r.get("jurisdiction"), r.get("right_type")) == (country, right)]
                if gap.get("source_constraints"):
                    accounts = {_account(item["provider"]) for item in gap["source_constraints"]}
                    runs = [r for r in evidence.get("source_runs", []) if _account(str(r.get("provider") or "")) in accounts]
                term = _planning_gap_term(task, plan, gap)
                relevant_providers = _gap_providers(task, gap, term, capabilities) if term else []
                base["delivery_limit"] = limit_proof(code, runs, relevant_providers, gap)
            output.append(base)
    return output


def next_work_entries(task, plan, evidence, candidates, ledger, supplement=None, *, task_dir=None,
                      source_capabilities=None, browser_status=None):
    """Discovery work only; preserve existing official coverage gaps verbatim."""
    if evidence_delivery_enabled(task):
        return _next_work_v2(task, plan, evidence, candidates, ledger, supplement, task_dir=task_dir,
            source_capabilities=source_capabilities, browser_status=browser_status)
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
