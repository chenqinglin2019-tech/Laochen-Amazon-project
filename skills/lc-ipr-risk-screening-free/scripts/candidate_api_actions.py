"""Bounded, field-specific follow-ups for new API-first tasks.

No second request is generated merely to confirm a retained fact. Existing
material wins; an outstanding request is reused; each record operation is tried
once here, with the existing recovery machinery owning any authorized retry.
"""
from __future__ import annotations

from common import load_skill_config, sha256_json
import trusted_api


def _origins(task, evidence, candidate, country, right):
    result = []
    for group in evidence.get("collections", {}).values():
        for entry in group if isinstance(group, list) else []:
            if not isinstance(entry, dict) or not trusted_api.valid_entry(task, entry):
                continue
            if any(trusted_api._matches(row, entry, candidate, country, right)
                   for row in trusted_api.records(entry.get("payload"))):
                result.append(entry["provider"])
    return set(result)


def _lens_wire(row):
    from runtime_v24 import _physical_request_identity
    keys = ("q", "image_url", "type", "hl", "country", "jurisdiction")
    if (row.get("operation") != "image_search" or row.get("q") != row.get("image_url")
            or not all(isinstance(row.get(key), str) and row[key].strip() for key in keys)):
        return None
    return _physical_request_identity("serpapi_google_lens", row)


def _retained_lens_response(evidence, row, task_dir):
    """Same checks as runtime reuse; this read does not create an execution."""
    if task_dir is None or _lens_wire(row) is None:
        return False
    from pathlib import Path
    from runtime_v24 import source_files_complete, source_fresh
    from serpapi_lens_client import retained_source_records
    for run in evidence.get("source_runs", []):
        if (run.get("provider") != "serpapi_google_lens" or run.get("status") not in {"success", "no_result"}
                or run.get("submission_state") != "submitted"
                or run.get("quota", {}).get("network_request_attempted") is not True
                or run.get("metadata", {}).get("physical_response_reuse")):
            continue
        wire = _lens_wire({**(run.get("request_params") or {}),
            "operation": run.get("operation"), "jurisdiction": run.get("jurisdiction")})
        if wire != _lens_wire(row) or not source_fresh(run, 48):
            continue
        try:
            if source_files_complete(Path(task_dir), evidence, run):
                retained_source_records(evidence, run, Path(task_dir))
                return True
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return False


def planned_lens_reuse(task, evidence, queries, row, *, task_dir, plan=None):
    """Bind a logical use before reserving a second identical wire request."""
    if task.get('retrieval_workflow_revision') != 'api-first-v3' or _lens_wire(row) is None:
        return None
    from workflow_v24 import validated_query_cancellation
    wire = _lens_wire(row)
    for source in queries.get('serpapi_google_lens', []):
        if source.get('query_id') == row.get('query_id') or _lens_wire(source) != wire:
            continue
        if plan is not None and validated_query_cancellation(task, plan, source):
            continue
        runs = [run for run in evidence.get('source_runs', [])
            if run.get('provider') == 'serpapi_google_lens'
            and run.get('query_id') == source.get('query_id')]
        if runs and not _retained_lens_response(evidence, row, task_dir):
            continue
        # Pending plans share one execution; retained material must still pass
        # freshness and raw-card integrity. Each logical purpose keeps its own
        # discovery/triage obligation and never counts as a second source.
        return {'provider': 'serpapi_google_lens', 'query_id': source['query_id'],
            'plan_entry_sha256': sha256_json(source), 'request_identity_sha256': sha256_json(wire),
            'independent_source_count': 1}
    return None


def _physical_planned(task, evidence, queries, providers, *, plan=None, task_dir=None):
    from pathlib import Path
    from workflow_v24 import validated_query_cancellation
    from runtime_v24 import physical_response_source
    retained, pending_wires = [], set()
    for provider in providers:
        for row in queries.get(provider, []):
            if not isinstance(row, dict):
                continue
            runs = [run for run in evidence.get("source_runs", []) if isinstance(run, dict)
                and run.get("provider") == provider and run.get("query_id") == row.get("query_id")]
            # Cancellation cannot refund a physical attempt or an unknown submission.
            if not runs and plan is not None and validated_query_cancellation(task, plan, row):
                continue
            if provider == "serpapi_google_lens":
                reuse = row.get('discovery_scope', {}).get('physical_response_plan_reuse')
                if isinstance(reuse, dict):
                    parents = [source for source in queries.get(provider, [])
                        if source.get('query_id') == reuse.get('query_id')]
                    if (len(parents) == 1 and parents[0].get('query_id') != row.get('query_id')
                            and reuse.get('provider') == provider
                            and reuse.get('plan_entry_sha256') == sha256_json(parents[0])
                            and _lens_wire(row) is not None and _lens_wire(parents[0]) == _lens_wire(row)
                            and reuse.get('request_identity_sha256') == sha256_json(_lens_wire(row))
                            and not any(run.get('quota', {}).get('network_request_attempted') is True
                                or run.get('submission_state') == 'unknown' for run in runs)):
                        # Runtime never submits this logical row if the parent
                        # response failed or is pending. A failed parent still
                        # retains its one real/unknown consumption reservation.
                        continue
                if runs and task_dir is not None and all(
                        physical_response_source(Path(task_dir), evidence, run) is not None for run in runs):
                    continue
                if not runs:
                    if _retained_lens_response(evidence, row, task_dir):
                        continue
                    wire = _lens_wire(row)
                    if wire is not None:
                        digest = sha256_json(wire)
                        if digest in pending_wires:
                            continue
                        pending_wires.add(digest)
            retained.append(row)
    return retained


def _budget_issue(task, evidence, queries, provider, *, plan=None, task_dir=None):
    """Keep shared planned slots and actual attempts within existing free caps."""
    if provider == "signa":
        from signa_client import consumed_queries, persisted_stop_reason
        providers, selection = {provider}, "signa_free_enhancement"
        stop = persisted_stop_reason(evidence)
    elif provider in {"serpapi_google_patents", "serpapi_google_lens"}:
        from serpapi_patents_client import consumed_queries, persisted_quota_block_reason
        providers, selection = {"serpapi_google_patents", "serpapi_google_lens"}, "serpapi_free_enhancement"
        stop = persisted_quota_block_reason(evidence)
    else:
        return ""
    maximum = (task.get(selection) or {}).get("max_queries_per_task")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        return "FREE_TASK_BUDGET_UNAVAILABLE"
    if stop:
        return "FREE_PROVIDER_STOP_RECORDED"
    consumed = consumed_queries(evidence)
    if consumed >= maximum:
        return "FREE_TASK_REQUEST_LIMIT_REACHED"
    planned = (_physical_planned(task, evidence, queries, providers, plan=plan, task_dir=task_dir)
        if task.get("retrieval_workflow_revision") == "api-first-v3" else
        [row for name in providers for row in queries.get(name, []) if isinstance(row, dict)])
    if len(planned) >= maximum:
        return "FREE_TASK_PLAN_LIMIT_REACHED"
    attempted = {run.get("query_id") for run in evidence.get("source_runs", []) if isinstance(run, dict)
                 and consumed_queries({"source_runs": [run]})}
    pending = sum(1 for row in planned if row.get("query_id") not in attempted)
    if consumed + pending >= maximum:
        return "FREE_TASK_RESERVED_REQUEST_LIMIT_REACHED"
    return ""


def _options(task, evidence, candidate, country, right, missing, requirements):
    number = str(candidate.get("publication_number") or candidate.get("serial_number")
        or candidate.get("registration_number") or candidate.get("application_number")
        or candidate.get("record_number") or "")
    base = {"q": number, "candidate_id": candidate["candidate_id"], "record_number": number}
    result = []
    if right in {"patent", "utility_model", "design"} and number:
        detail_params = {key: value for key, value in base.items() if key != "record_number"}
        detail_facts = set(missing) - (trusted_api.DYNAMIC if number.upper().startswith("EP") and country != "EP" else set())
        result.append(("serpapi_google_patents", "candidate_detail",
            {**detail_params, "patent_id": "patent/" + trusted_api.identifier(number) + "/en"}, detail_facts, False))
        if number.upper().startswith("EP") and "protection_content" in missing:
            result.append(("epo_publication_server", "document_retrieval",
                {**base, "document": number, "format": "xml"}, {"protection_content"}, False))
    if right.startswith("trademark"):
        record_id = candidate.get("provider_record_id")
        media = []
        for group in evidence.get("collections", {}).values():
            for entry in group if isinstance(group, list) else []:
                if not isinstance(entry, dict) or entry.get("provider") != "signa" or not trusted_api.valid_entry(task, entry):
                    continue
                for row in trusted_api.records(entry.get("payload")):
                    if trusted_api._matches(row, entry, candidate, country, right):
                        record_id = record_id or row.get("provider_record_id") or row.get("id")
                        media.extend(row.get("media") or [])
        if record_id:
            result.append(("signa", "candidate_detail", {**base, "provider_record_id": record_id},
                           set(missing), False))
            if "representative_figures" in missing:
                for item in media:
                    if isinstance(item, dict) and (item.get("media_id") or item.get("id")):
                        result.append(("signa", "trademark_media", {**base, "provider_record_id": record_id,
                            "media_id": item.get("media_id") or item["id"]}, {"representative_figures"}, False))
    # National/region APIs are used only for their actual territory.
    for req in requirements:
        for route in req.get("routes", []) + req.get("gap_only_routes", []) + req.get("fallback_routes", []):
            provider, operation = route.get("provider"), route.get("operation")
            if operation != "candidate_verification" or not number:
                continue
            params = dict(base)
            browser = provider.endswith("browser") or provider == "uspto_tsdr"
            if provider == "inpi_api" and country == "FR":
                params["identifier"] = number
            elif provider in {"euipo_trademark", "euipo_design"} and country == "EU":
                params.pop("record_number", None)
                params.update(identifier=number, detail=True)
            elif provider == "jpo_api" and country == "JP":
                from merge_candidates import _jp_candidate_number
                jp_number, kind = _jp_candidate_number(candidate, right)
                if not jp_number:
                    continue
                params.pop("record_number", None)
                params.update(q=jp_number, number=jp_number, number_kind=kind)
            elif browser:
                params.update(mode="agent", strategy="record_number")
                if provider == "uspto_tsdr":
                    params["serial_number"] = number
            else:
                continue
            supported = set(missing)
            if provider == "uspto_patent_browser":
                supported &= {"identity", "protection_content", "representative_figures"}
            result.append((provider, operation, params, supported, browser))
    return [option for option in result if option[3]]


def append(task, evidence, queries, candidate, decision, requirements, *, capabilities=None, plan=None, task_dir=None):
    """Append at most one next action, or return precise remaining limitations."""
    from generate_search_plan import entry
    from workflow_v24 import bind_scenario_action, _add
    country, right = decision["jurisdiction"], decision["right_type"]
    acceptance = trusted_api.accepted_verification(task, evidence, candidate, country, right,
        scope=decision, task_dir=task_dir)
    if acceptance["complete"]:
        return []
    missing = set(acceptance["missing"])
    if capabilities is None:
        from runtime_v24 import capabilities as get_capabilities
        capabilities = {row["provider"]: row for row in get_capabilities(task, load_skill_config())}
    scope = {key: decision[key] for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type")}
    attempts = {run.get("query_id"): run for run in evidence.get("source_runs", []) if isinstance(run, dict)}
    def current_binding(row):
        if any(row.get(key) != decision.get(key) for key in ("scenario_id", "scenario_sha256")):
            return False
        annotation = decision["annotation"]
        if (row.get("triage_decision_id") != annotation.get("annotation_id")
                or row.get("triage_decision_sha256") != sha256_json(annotation)):
            return False
        return all(key not in row or row.get(key) == value for key, value in (
            ("product_target_sha256", task.get("product_identity", {}).get("sha256")),
            ("product_change_version", task.get("product_change_version"))))
    prior = [(provider, row) for provider, rows in queries.items() for row in rows
        if row.get("candidate_id") == candidate["candidate_id"] and (row.get("triage_jurisdiction") or row.get("jurisdiction")) == country
        and row.get("right_type") == right and row.get("api_gap_revision") == trusted_api.REVISION
        and (row.get("query_id") in attempts or current_binding(row))]
    if plan is not None:
        from workflow_v24 import validated_query_cancellation
        prior = [(provider, row) for provider, row in prior
            if row["query_id"] in attempts or not validated_query_cancellation(task, plan, row)]
    # Pending/unknown submissions remain in the original recovery workflow.
    if any(row["query_id"] not in attempts or attempts[row["query_id"]].get("submission_state") == "unknown"
           for _, row in prior if not trusted_api.action_facts(task, evidence, row)):
        return []
    origins = _origins(task, evidence, candidate, country, right)
    options = _options(task, evidence, candidate, country, right, missing, requirements)
    options.sort(key=lambda option: (option[4], option[0] not in origins))
    budget_limits = {}
    for provider, operation, params, supported, browser in options:
        if not browser and capabilities.get(provider, {}).get("executable") is not True:
            continue
        if any(old_provider == provider and old.get("operation") == operation
               and old.get("media_id") == params.get("media_id") for old_provider, old in prior):
            continue
        budget_issue = _budget_issue(task, evidence, queries, provider, plan=plan, task_dir=task_dir)
        if budget_issue:
            budget_limits[provider] = budget_issue
            continue
        params.update(missing_facts=sorted(supported), api_gap_revision=trusted_api.REVISION,
            gap_reason="Missing retained fields for this exact record: " + ", ".join(sorted(supported)),
            judgment_impact="Required to determine this candidate's identity, applicable protection or product comparison.")
        if browser:
            params["fallback_basis"] = {"candidate_id": candidate["candidate_id"],
                "missing_facts": sorted(supported), "reviewed_evidence_refs": acceptance["evidence_refs"],
                "attempted_query_ids": [row["query_id"] for _, row in prior],
                "api_budget_limits": dict(budget_limits),
                "unavailable_api_providers": sorted({option[0] for option in options if not option[4]
                    and capabilities.get(option[0], {}).get("executable") is not True})}
        request_country = ("EP" if provider in {"epo_publication_server", "serpapi_google_patents"}
                           and str(params.get("q") or "").upper().startswith("EP") else country)
        row = entry(provider, operation, request_country, params, required=False, right_type=right,
            requirement_ids=[req["requirement_id"] for req in requirements if req.get("phase") == "candidate_verification"],
            derived_from=["candidate:" + candidate["candidate_id"]], wave=2)
        row.update(required_for="comparison", execute_by_default=True, execution_phase="verification",
                   search_dimension="identifier", search_language="")
        if provider == "signa":
            from common import SIGNA_FREE_ROLE
            row.update(retrieval_workflow_revision=trusted_api.REVISION,
                       role=SIGNA_FREE_ROLE, authoritative_for_final_rating=False)
        row = bind_scenario_action(task, provider, row, purpose="document_content", decision=decision,
                                   obligation_key="api-gap:" + operation + ":" + sha256_json(params)[:16])
        if provider == "signa":
            from common import signa_record_operation_query_id
            row["query_id"] = signa_record_operation_query_id(row)
        _add(queries, provider, row)
        return []
    gap = {**scope, "code": "API_RECORD_FACT_GAP", "required_facts": sorted(missing),
        "assigned_to": "agent", "reason": "Available bounded record operations did not resolve these facts; retain a scoped report limitation.",
        "evidence_refs": acceptance["evidence_refs"], "attempted_query_ids": [row["query_id"] for _, row in prior],
        "api_budget_limits": budget_limits}
    # Old exhausted operations retain their original audit metadata/signatures.
    # Budget changes elsewhere cannot reopen an operation tried once already.
    if task.get("retrieval_workflow_revision") == "api-first-v3" and plan is not None and not budget_limits:
        old = [value for value in plan.get("candidate_action_gaps", [])
            if isinstance(value, dict) and {k:v for k,v in value.items() if k != "api_budget_limits"}
                == {k:v for k,v in gap.items() if k != "api_budget_limits"}]
        tried = {provider for provider, _ in prior}
        if len(old) == 1 and old[0].get("api_budget_limits") and all(
                provider in tried and code in {"FREE_TASK_PLAN_LIMIT_REACHED", "FREE_TASK_RESERVED_REQUEST_LIMIT_REACHED", "FREE_TASK_REQUEST_LIMIT_REACHED"}
                for provider, code in old[0]["api_budget_limits"].items()):
            return old
    return [gap]
