"""Opt-in completion checks over existing evidence and work projections.

This module owns no queue or mutable authority ledger. Publication retains the
non-secret status inputs used for its decision so validation never reads the
validating machine's credentials.
"""
from copy import deepcopy

from common import load_json, sha256_json

REVISION = "necessary-work-v1"
_ACCESS_REASONS = frozenset({"optional_credentials_missing", "OPTIONAL_CREDENTIALS_MISSING",
    "CREDENTIAL_MISSING", "AUTH_REQUIRED", "LOGIN_REQUIRED", "CAPTCHA_REQUIRED", "MFA_REQUIRED",
    "CONSENT_REQUIRED", "QR_REQUIRED", "ACCESS_INTERACTION_REQUIRED", "QUOTA_EXHAUSTED",
    "FREE_QUOTA_EXHAUSTED", "RATE_LIMITED", "SOURCE_RETRY_CONDITION_REQUIRED",
    "BROWSER_RATE_LIMITED", "BROWSER_RATE_LIMIT_COOLDOWN", "BROWSER_RATE_LIMIT_RECOVERY_EXHAUSTED",
    "BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED"})
_BLOCKED_REASONS = frozenset({"NO_SUPPORTED_ROUTE", "automation_policy_incompatible",
    "free_entitlement_unvalidated", "AUTOMATION_PROHIBITED", "CURRENT_STATUS_ROUTE_UNAVAILABLE", "CURRENT_OWNER_ROUTE_UNAVAILABLE",
    "CURRENT_TERRITORY_ROUTE_UNAVAILABLE",
    "BROWSER_SUBMITTED_FAILURE_RECOVERY_EXHAUSTED", "BROWSER_PARTIAL_RESUME_LIMIT"})


def api_record_gap_entry(task, evidence, candidates, ledger, plan, capabilities, scope, *, supplement=None, require_review=True, task_dir=None):
    """Bind exhausted field retrieval to actual M06/M07 reading and limitation review."""
    from trusted_api import enabled as trusted_enabled
    if not trusted_enabled(task):
        return None
    from annotate_materiality import iter_candidates
    keys = ("candidate_id", "scenario_id", "jurisdiction", "right_type")
    if not all(scope.get(key) for key in keys):
        return None
    matches = [row for row in plan.get("candidate_action_gaps", []) if row.get("code") == "API_RECORD_FACT_GAP"
        and all(row.get(key) == scope.get(key) for key in keys)]
    if len(matches) != 1 or not matches[0].get("required_facts"):
        return None
    candidate = next((row for _, row in iter_candidates(candidates) if row.get("candidate_id") == scope["candidate_id"]), None)
    if candidate is None:
        return None
    import specialty_analysis as specialty
    import distinctive_rights as distinctive
    module = specialty if scope["right_type"] in specialty.RIGHTS else distinctive
    try:
        current = module._current(task, evidence, candidates, ledger, supplement, module._scope(scope))
        intake = module._intake(task, module._scope(scope))
        history = [row for row in module.events(task) if module._scope(row) == module._scope(scope)
            and intake and row.get("intake_event_id") == intake["event_id"]]
    except (ValueError, KeyError, TypeError):
        return None
    if not intake or intake.get("annotation_id") != current.get("annotation", {}).get("annotation_id"):
        return None
    from candidate_triage_stage import events as triage_events
    handoff = next((row for row in reversed(triage_events(task)) if row.get("kind") == "selected_handoff"
        and module._scope(row) == module._scope(scope)
        and row.get("annotation_id") == intake.get("annotation_id")), {})
    if handoff.get("event_id") != intake.get("selected_handoff_event_id"):
        return None
    # Recompute the existing planner. A recovered capability/new record route
    # must reopen work; a saved label cannot prove that retrieval is exhausted.
    from candidate_api_actions import append
    requirements = [row for row in task.get("coverage_requirements", [])
        if row.get("jurisdiction") == scope["jurisdiction"] and row.get("right_type") == scope["right_type"]]
    regenerated = append(task, evidence, deepcopy(plan.get("queries", {})), candidate,
        {**current, **{key: scope[key] for key in keys}}, requirements, capabilities=capabilities, plan=plan, task_dir=task_dir)
    if regenerated != matches:
        return None
    aliases = {"current_status": "status", "protection_content": "protection", "representative_figures": "protection"}
    facts = []
    for needed in matches[0]["required_facts"]:
        fact = next((row for row in reversed(history) if row.get("kind") == "fact" and
            (row.get("fact_kind") == aliases.get(needed, needed) if module is specialty else row.get("api_fact") == needed)), None)
        if fact is None or fact.get("outcome") != "unknown":
            return None
        facts.append(fact)
    fact_ids = {row["event_id"] for row in facts}
    materials = {row["event_id"]: row for row in history if row.get("kind") == "material"}
    material_ids = {ref for row in facts for ref in row.get("material_event_ids", [])}
    batches = [row for row in history if row.get("kind") == "batch"]
    processed = {ref for row in batches for ref in row.get("processed_material_event_ids", [])}
    accounted = {ref for row in batches for ref in row.get("received_evidence_refs", [])}
    refs = set(candidate.get("evidence_refs", [])) | set(matches[0].get("evidence_refs", []))
    if (not material_ids or not material_ids <= set(materials) or not set(materials) <= processed or
        not refs <= accounted or any(not materials[mid].get("reading_locations") or
            materials[mid].get("status") == "acquired" for mid in material_ids)):
        return None
    for change in (row for row in history if row.get("kind") in {"change", "impact"}):
        field = "change_event_id" if change["kind"] == "change" else "impact_event_id"
        review = next((row for row in reversed(history) if row.get(field) == change["event_id"]
            and row.get("kind") in {"change_review", "impact_review"}), {})
        if review.get("outcome") != "continues":
            return None
    covered, follows = set(), []
    for gap in (row for row in history if row.get("kind") == "gap"):
        affected = set(gap.get("affected_event_ids", [])) | set(gap.get("fact_event_ids", [])) | {
            row.get("basis_event_id") for row in gap.get("obligation_bindings", [])}
        if not affected & fact_ids:
            continue
        follow = next((row for row in reversed(history) if row.get("kind") == "followup"
            and row.get("gap_event_id") == gap["event_id"]), {})
        if follow.get("outcome") != "limited" or not follow.get("result_review") or not follow.get("remaining_impact"):
            continue
        covered.update(affected & fact_ids)
        follows.append(follow)
    if require_review and covered != fact_ids:
        return None
    close = next((row for row in reversed(history) if row.get("kind") == "scope_close"), {})
    conditions = [str(row.get("restore_condition") or row.get("next_action_or_dependency") or "") for row in follows]
    if close.get("status") == "limited" and close.get("restore_condition"):
        conditions.append(close["restore_condition"])
    if require_review and (not conditions or not all(value.strip() for value in conditions)):
        return None
    dependencies = [intake, handoff, *facts, *materials.values(), *batches]
    proof = {"kind": "api_record_fact_gap", **{key: scope[key] for key in keys},
        "planning_gap_sha256": sha256_json(matches[0]), "candidate_sha256": sha256_json(candidate),
        "annotation_sha256": sha256_json(current["annotation"]), "capabilities_sha256": sha256_json(capabilities),
        "required_facts": matches[0]["required_facts"],
        "basis_event_ids": sorted(fact_ids),
        "event_sha256": {row["event_id"]: sha256_json(row) for row in dependencies},
        "followup_sha256": {row["event_id"]: sha256_json(row) for row in follows} if require_review else {},
        "recovery_condition": "；".join(dict.fromkeys(conditions)) if require_review else "待记录具体字段补证恢复条件"}
    entry = {**{key: scope[key] for key in keys}, "kind": "source_lookup", "state": "blocked" if require_review else "awaiting_review",
        "reason": "API_RECORD_FACT_GAP", "coverage_status": "unknown", "official_verification": "not_verified",
        "required_facts": matches[0]["required_facts"], "evidence_refs": sorted(refs),
        "limitation_kind": "bounded_api_record_fields_unresolved", "delivery_limit": proof,
        "resume_condition": proof["recovery_condition"],
        "reasoning": "已读API及补证材料仍缺所列准确记录字段；按专项补查审阅保留未知与判断影响。"}
    entry["work_id"] = "WORK-" + sha256_json({"kind": "api_record_fact_gap", **{key: scope[key] for key in keys}})[:24]
    return entry


def _reviewed_api_gap_queries(task,evidence,plan,gap,scope,task_dir):
    """Only an exhausted, read exact record may stop its duplicate API request."""
    if task.get('retrieval_workflow_revision') != 'api-first-v3' or task_dir is None:
        return set()
    from pathlib import Path
    from assessment_v24 import bound_runs
    from trusted_api import api_run_accepted
    from source_result_processing import progress,WHOLE_RECORD
    attempted = gap.get('attempted_query_ids',[])
    if not isinstance(attempted,list):
        return set()
    accepted = set()
    for provider,rows in plan.get('queries',{}).items():
        for row in rows if isinstance(rows,list) else []:
            if (not isinstance(row,dict) or row.get('query_id') not in attempted
                    or row.get('api_gap_revision') != 'api-first-v3' or row.get('operation') != 'candidate_detail'
                    or row.get('candidate_id') != scope['candidate_id']
                    or any(row.get(k) != scope[k] for k in ('scenario_id','jurisdiction','right_type'))
                    or not isinstance(row.get('missing_facts'),list)
                    or not set(gap.get('required_facts',[])) <= set(row['missing_facts'])):
                continue
            for run in bound_runs(evidence,plan,provider,row):
                if run.get('status') != 'success' or run.get('submission_state') != 'submitted' or not api_run_accepted(task,evidence,run):
                    continue
                try:
                    state = progress(Path(task_dir),run,evidence)
                    proof = (state.get('record_content_review') or {}).get('binding',{})
                    if (state.get('result_form') == WHOLE_RECORD and state.get('material_processing_complete') is True
                            and proof.get('candidate_id') == scope['candidate_id'] and proof.get('jurisdiction') == scope['jurisdiction']):
                        accepted.add(row['query_id'])
                except (OSError,ValueError,KeyError,TypeError):
                    continue
    return accepted


def _failed_api_gap_limits(task,evidence,plan,gap,scope,task_dir):
    from recovery_stage_b import task_limit_no_retry_proof
    proofs = {}
    for provider,rows in plan.get('queries',{}).items():
        for row in rows:
            if (row.get('query_id') not in gap.get('attempted_query_ids', [])
                    or row.get('operation') != 'candidate_detail'
                    or any(row.get(k) != scope.get(k) for k in ('candidate_id','scenario_id','jurisdiction','right_type'))
                    or not set(gap.get('required_facts', [])) <= set(row.get('missing_facts', []))):
                continue
            proof = task_limit_no_retry_proof(task,evidence,provider,row,task_dir)
            if proof:
                proofs[row['query_id']] = proof
    return proofs


def _duplicate_reviewed_api_gap_work(row,scope,finished_queries):
    if (not all(row.get(key) == scope.get(key) for key in ('candidate_id','scenario_id','jurisdiction','right_type'))
            or row.get('query_id') not in finished_queries):
        return False
    return (row.get('kind') == 'source_lookup' and (
        row.get('state') == 'ready' and row.get('reason') == 'NECESSARY_ACTION_PENDING'
        or row.get('state') == 'awaiting_review' and row.get('reason') == 'REVIEW_PROGRESS_QUERY_NOT_PLANNED') or
        row.get('kind') == 'agent_investigation' and row.get('state') == 'awaiting_review'
        and row.get('reason') == 'SPECIALTY_SOURCE_PENDING')


def status_route_gap_entry(task, evidence, candidates, ledger, plan, capabilities, scope, *, supplement=None, fact_kind="status"):
    """Bind one of two explicit missing US patent Skill routes, never a failed official query.

    This is a technical limitation for incomplete evidence delivery. It does
    not establish current status, search completion or absence of public routes.
    """
    from specialty_analysis import _current, _intake, _scope, events
    from annotate_materiality import iter_candidates
    right = scope.get("right_type")
    if right not in {"patent", "design"} or (fact_kind == "territory" and right != "design"):
        return None
    subject = "PATENT" if right == "patent" else "DESIGN"
    specs = {
        "status": (f"US_{subject}_STATUS_ROUTE_UNIMPLEMENTED", ["current_status"], {"status", "current_status"},
                   {"current_status", "patent_status", "maintenance_status", "design_status"}, "status_plan_gap",
                   "CURRENT_STATUS_ROUTE_UNAVAILABLE", "internal_status_route_not_implemented", "现行状态"),
        "rights_holder": (f"US_{subject}_OWNER_ROUTE_UNIMPLEMENTED", ["rights_holder"], {"rights_holder", "owner", "assignment"},
                         {"current_owner", "rights_holder", "owner", "assignment", "patent_assignment"}, "ownership_plan_gap",
                         "CURRENT_OWNER_ROUTE_UNAVAILABLE", "internal_owner_route_not_implemented", "现行权利人/转让记录"),
        # The current-status implementation gap is also the bounded source
        # basis for the distinct territorial-effect fact. Do not infer that
        # a patent/design right is active in a territory from its publication.
        "territory": (f"US_{subject}_STATUS_ROUTE_UNIMPLEMENTED", ["current_status"], {"status", "current_status"},
                      {"current_status", "patent_status", "maintenance_status", "design_status"},
                      "territory_current_effect_plan_gap", "CURRENT_TERRITORY_ROUTE_UNAVAILABLE",
                      "internal_territory_effect_route_not_implemented", "美国现行地域效力"),
    }
    if fact_kind not in specs:
        return None
    code, required, status_names, operation_names, proof_kind, reason, limitation_kind, label = specs[fact_kind]
    keys = ("candidate_id", "scenario_id", "jurisdiction", "right_type")
    if scope.get("jurisdiction") != "US":
        return None
    matches = [gap for gap in (plan or {}).get("candidate_action_gaps", [])
               if gap.get("code") == code
               and all(gap.get(key) == scope.get(key) for key in keys)
               and gap.get("assigned_to") == "implementation"
               and gap.get("required_facts") == required]
    if len(matches) != 1 or not capabilities:
        return None
    requirement = next((row for row in task.get("coverage_requirements", [])
                        if row.get("requirement_id") == matches[0].get("requirement_id")), {})
    if (requirement.get("jurisdiction"), requirement.get("right_type"), requirement.get("phase")) != (
            "US", right, "candidate_verification"):
        return None
    try:
        current = _current(task, evidence, candidates, ledger, supplement, _scope(scope))
        intake = _intake(task, _scope(scope))
    except ValueError:
        return None
    if not intake or intake.get("annotation_id") != current.get("annotation", {}).get("annotation_id"):
        return None
    from candidate_triage_stage import events as triage_events
    handoff = next((row for row in reversed(triage_events(task)) if row.get("kind") == "selected_handoff"
                    and _scope(row) == _scope(scope)
                    and row.get("annotation_id") == current["annotation"]["annotation_id"]), {})
    if handoff.get("event_id") != intake.get("selected_handoff_event_id"):
        return None
    history = [row for row in events(task) if _scope(row) == _scope(scope)
               and row.get("intake_event_id") == intake["event_id"]]
    fact = next((row for row in reversed(history) if row.get("kind") == "fact"
                 and row.get("fact_kind") == fact_kind), {})
    if fact.get("outcome") != "unknown":
        return None  # Unread facts and conflicting/supported facts keep their own obligations.
    if any(row.get("kind") == "change" and row.get("substantive") and
           fact.get("event_id") in row.get("affected_event_ids", []) and
           not any(review.get("kind") == "change_review" and review.get("change_event_id") == row["event_id"]
                   and review.get("outcome") == "continues" for review in history) for row in history):
        return None
    for rows in (plan or {}).get("queries", {}).values():
        for row in rows:
            if (all(row.get(key) == scope.get(key) for key in keys)
                    and status_names.intersection(row.get("required_facts", []))):
                return None  # A real planned route must be executed/reviewed instead.
    canonical_caps = capability_map(task, sanitize_snapshots(task, {
        "source-capabilities.json": {"task_id": task["task_id"], "sources": list(capabilities.values())}
    })["source-capabilities.json"])
    for cap in canonical_caps.values():
        for operation in cap.get("operations", []):
            if (operation.get("jurisdiction") == "US" and operation.get("right_type") == right
                    and (operation.get("search_dimension") in status_names or
                         operation.get("operation") in operation_names)):
                return None
    candidate = next((row for _, row in iter_candidates(candidates)
                      if row.get("candidate_id") == scope["candidate_id"]), None)
    if candidate is None:
        return None
    proof = {"kind": proof_kind, "official_verification": "not_verified",
             "fact_kind": fact_kind, "planning_gap_sha256": sha256_json(matches[0]),
             "plan_sha256": sha256_json(plan), "capabilities_sha256": sha256_json(canonical_caps),
             "candidate_sha256": sha256_json(candidate), "annotation_sha256": sha256_json(current["annotation"]),
             "intake_event_id": intake["event_id"], "intake_sha256": sha256_json(intake),
             "basis_event_id": fact["event_id"], "basis_sha256": sha256_json(fact),
             **{key: scope[key] for key in keys}}
    entry = {**{key: scope[key] for key in keys}, "kind": "source_lookup", "state": "blocked",
             "reason": reason, "fact_kind": fact_kind,
             "limitation_kind": limitation_kind, "official_verification": "not_verified",
             "delivery_limit": proof, "planning_gap_sha256": proof["planning_gap_sha256"],
             "reasoning": f"当前技能尚未实现本候选的美国{'专利' if right == 'patent' else '注册外观设计'}{label}路由；未执行{label}查询，"
                          f"不代表官方来源不可访问或无可查信息。已读材料仍不能确认{label}，报告须保留未知。"}
    entry["work_id"] = "WORK-" + sha256_json(entry)[:24]
    return entry


def enabled(task):
    revision = task.get("completion_policy_revision")
    if revision is None:
        return False
    from completion_policy import supported
    if (not supported(task) or task.get("schema_version") != "2.4-free"
            or task.get("assessment_policy") != "evidence-estimate-v1"
            or task.get("workflow_correction_revision") != "workflow-correction-v1"):
        raise ValueError("COMPLETION_POLICY_INVALID")
    return True


def capability_map(task, snapshot):
    if snapshot is None:
        return {}
    if not isinstance(snapshot, dict) or snapshot.get("task_id") != task["task_id"]:
        raise ValueError("COMPLETION_CAPABILITY_SNAPSHOT_INVALID")
    sources = snapshot.get("sources")
    if not isinstance(sources, list):
        raise ValueError("COMPLETION_CAPABILITY_SNAPSHOT_INVALID")
    result = {}
    for row in sources:
        if (not isinstance(row, dict) or not isinstance(row.get("provider"), str)
                or row["provider"] in result or type(row.get("executable")) is not bool):
            raise ValueError("COMPLETION_CAPABILITY_SNAPSHOT_INVALID")
        result[row["provider"]] = row
    return result


def sanitize_snapshots(task, snapshots):
    """Retain only fields consumed by work projection; never serialize opaque results."""
    from completion_policy import evidence_delivery_enabled
    if not isinstance(snapshots, dict) or set(snapshots) - {"source-capabilities.json", "browser-execution-status.json"}:
        raise ValueError("PUBLICATION_SNAPSHOT_INVALID")
    result = {}
    def fields(value, names):
        if not isinstance(value, dict):
            raise ValueError("PUBLICATION_SNAPSHOT_INVALID")
        kept = {key: value[key] for key in names if key in value}
        if any(item is not None and not isinstance(item, (str, bool, int, float)) for item in kept.values()):
            raise ValueError("PUBLICATION_SNAPSHOT_FIELD_INVALID")
        return kept
    for name, snapshot in snapshots.items():
        if not isinstance(snapshot, dict) or snapshot.get("task_id") != task["task_id"]:
            raise ValueError("PUBLICATION_SNAPSHOT_IDENTITY_INVALID")
        saved = fields(snapshot, ("schema_version", "task_id"))
        if name == "source-capabilities.json":
            capability_map(task, snapshot)
            saved["sources"] = [fields(row, ("provider", "state", "reason", "executable",
                "credentials_present", "checked_at", "cost_ceiling_usd")) for row in snapshot["sources"]]
            if evidence_delivery_enabled(task):
                for source, retained in zip(snapshot["sources"], saved["sources"]):
                    operations = source.get("operations", [])
                    if not isinstance(operations, list):
                        raise ValueError("PUBLICATION_OPERATION_SNAPSHOT_INVALID")
                    retained["operations"] = [fields(operation, ("jurisdiction", "right_type", "operation",
                        "query_compiler_revision", "search_dimension", "query_id", "plan_entry_sha256", "source_run_id",
                        "source_run_sha256", "review_sha256", "registry_entry_sha256", "state",
                        "input_mode", "limitations", "reviewer", "acceptance_reason", "checked_at", "adapter_version",
                        "acceptance_review_sha256")) for operation in operations]
                    states = source.get("operation_states", [])
                    if not isinstance(states, list):
                        raise ValueError("PUBLICATION_OPERATION_SNAPSHOT_INVALID")
                    retained["operation_states"] = [fields(operation, ("jurisdiction", "right_type", "operation",
                        "query_compiler_revision", "search_dimension", "registry_entry_sha256", "state",
                        "input_mode", "limitations", "reviewer", "acceptance_reason", "checked_at", "adapter_version",
                        "acceptance_review_sha256")) for operation in states]
        else:
            if not isinstance(snapshot.get("queries", []), list):
                raise ValueError("PUBLICATION_BROWSER_SNAPSHOT_INVALID")
            saved["queries"] = [fields(row, ("query_id", "plan_entry_sha256", "provider", "dispatch",
                "status", "error_code", "source_error_code", "phase", "submission_state",
                "partial_resume_attempts", "partial_resume_limit", *(('capture_path', 'capture_sha256', 'capture_status')
                    if evidence_delivery_enabled(task) else ())))
                for row in snapshot.get("queries", [])]
            pauses = snapshot.get("provider_pauses", {})
            if not isinstance(pauses, dict):
                raise ValueError("PUBLICATION_BROWSER_SNAPSHOT_INVALID")
            saved["provider_pauses"] = {provider: fields(pause, ("error_code", "reason", "resume_after_epoch",
                "recovery_attempts", "paused_at", "query_id")) for provider, pause in pauses.items()}
        result[name] = saved
    return result


def _scope(value):
    return tuple(value.get(key) for key in ("scenario_id", "jurisdiction", "right_type"))


def _route_options(task, requirement, axis):
    """Ask the existing parameter compiler; do not invent an adapter per axis."""
    from workflow_v24 import _api_params, LANGUAGES
    right, country = requirement["right_type"], requirement["jurisdiction"]
    kinds = {"text": [("brand", "mark")] if right.startswith("trademark") else [("product", "toy")], "description": [("mark_description", "circle")],
        "phonetic": [("phonetic", "mark")], "owner": [("owner", "Example")],
        "classification": ([("ipc", "A63H33/00"), ("cpc", "A63H33/00"), ("uspc", "446/1")]
            if right in {"patent", "utility_model"} else [("locarno", "21-01"), ("uspc", "D21/398")]
            if right == "design" else [("design_code", "260101"), ("nice", "28")])}.get(axis, [])
    options = []
    for route in requirement.get("routes", []):
        provider = route.get("provider")
        if route.get("operation") in {"candidate_detail", "candidate_verification", "document_retrieval"}:
            continue
        if task.get("retrieval_workflow_revision") in {"api-first-v2", "api-first-v3"} and not provider.endswith("browser") and provider != "asset_provenance":
            from provider_routing import priority
            allowed = {name for name, _ in priority(country, right, "discovery",
                revision=task["retrieval_workflow_revision"])}
            if provider not in allowed:
                continue
        if provider == "asset_provenance":
            from record_asset_provenance import INVESTIGATION_STEPS
            if axis in INVESTIGATION_STEPS.get(right, ()):
                options.append(route)
            continue
        for kind, value in kinds:
            term = {"kind": kind, "value": value, "language": LANGUAGES.get(country, ""),
                "strategy": "phrase" if axis == "owner" or (right.startswith("trademark") and axis == "text") else "boolean"}
            try:
                params = _api_params(provider, term, country, right)
                if params is not None and provider.endswith("browser"):
                    from record_browser_execution import planned_browser_query
                    row = {**params, "operation": route.get("operation"), "right_type": right}
                    if provider == "uspto_tmsearch_browser":
                        row["query_compiler_revision"] = "tm-figurative-fields-v1" if right == "trademark_figurative" else "tm-field-tags-v1"
                    planned_browser_query(provider, row, task)
            except (ValueError, TypeError):
                params = None
            if params is not None:
                options.append(route)
                break
    return options


def _route_state(options, capabilities):
    if not options:
        return "blocked", "NO_SUPPORTED_ROUTE"
    states = []
    for route in options:
        provider = route["provider"]
        cap = capabilities.get(provider, {})
        reason = cap.get("reason", "SOURCE_CAPABILITY_CHECK_REQUIRED")
        if provider == "asset_provenance" or cap.get("executable") is True:
            return "ready", "SUPPORTED_ROUTE_AVAILABLE"
        if reason in _ACCESS_REASONS:
            states.append(("awaiting_access", reason))
        elif reason in _BLOCKED_REASONS:
            states.append(("blocked", reason))
        else:
            # A missing preflight or local acceptance check is Agent work.
            return "ready", reason
    return next((s for s in states if s[0] == "awaiting_access"), states[0])


def _empty_word_mark_wait_clues(task, plan, evidence, entry):
    """Return current waiting brand clues when an empty own-mark inventory makes a word query impossible."""
    if (entry.get("right_type") != "trademark_word" or not entry.get("scenario_id")
            or not entry.get("jurisdiction")):
        return set()
    from completion_policy import evidence_delivery_enabled
    if not evidence_delivery_enabled(task):
        return set()
    import product_scope as ps
    if not ps.enabled(task):
        return set()
    if any(isinstance(term, dict) and term.get("kind") in {"brand", "mark"}
           and ps.term_allowed(task, term, "trademark_word") for term in plan.get("terms", [])):
        return set()
    sid, country = entry["scenario_id"], entry["jurisdiction"]
    directions = [direction for direction in ps.directions(task, sid, "trademark_word")
        if any(obj.get("object_id") in direction.get("object_ids", []) and obj.get("kind") == "brand"
               and obj.get("scope_status") == "included" for obj in ps.scope(task).get("objects", []))]
    if len(directions) != 1:
        return set()
    # Require a current, independently reviewed empty mark inventory. This is
    # an applicability fact for the user's present mark, not a trademark waiver.
    from record_asset_provenance import asset_scope
    inventory = asset_scope(task, sid, "trademark_figurative")
    if not inventory.get("inventory_reviewed") or inventory.get("asset_ids"):
        return set()
    from discovery_semantics import current
    review = current(task, plan, evidence, stage="direction", scenario_id=sid,
        jurisdiction=country, right_type="trademark_word")
    if not review:
        return set()
    direction = directions[0]
    reviewed_direction = next((item for item in review.get("directions", [])
        if item.get("direction_id") == direction["direction_id"]), None)
    if not reviewed_direction:
        return set()
    clue_ids = set(reviewed_direction.get("clue_ids", []))
    dispositions = {item.get("clue_id"): item.get("disposition") for item in review.get("clues", [])}
    waiting = {clue_id for clue_id in clue_ids if dispositions.get(clue_id) == "awaiting_information"}
    if not waiting or not any(clue_id.endswith(":own-brand") or clue_id.endswith(":own-brand-use") for clue_id in waiting):
        return set()
    # If a current, direction-bound discovery row exists, keep its own execution
    # work visible. Only suppress planning gaps caused by the missing mark term.
    from workflow_v24 import necessary_scenario_row_bindings
    from discovery_semantics import row_jurisdictions
    for provider, rows in plan.get("queries", {}).items():
        for row in rows:
            if (row.get("action_purpose") == "discovery" and row.get("right_type") == "trademark_word"
                    and country in row_jurisdictions(provider, row)
                    and any(binding.get("scenario_id") == sid
                            and any(ref.get("direction_id") == direction["direction_id"]
                                    for ref in row.get("product_dependencies", []))
                            for binding in necessary_scenario_row_bindings(task, row))):
                return set()
    return waiting


def _official_coverage_gap(entry):
    reason = str(entry.get("planning_gap") or entry.get("reason") or "")
    return ":AXIS_MISSING:" in reason or reason.endswith(":LOCAL_LANGUAGE_MISSING")


def _bounded_discovery_proofs(task, plan, evidence, candidates, ledger, *, supplement=None, task_dir=None):
    """Reuse exact, current source reviews; a free-form stop note proves nothing."""
    from api_first_planning import review_validation, source_files_error, reviewed_unknown_submission
    from workflow_v24 import necessary_scenario_row_bindings, validated_query_cancellation
    if task_dir is None:
        return {}
    result = {}
    for provider, rows in plan.get("queries", {}).items():
        for row in rows:
            if validated_query_cancellation(task, plan, row):
                continue
            runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
                and run.get("query_id") == row.get("query_id") and run.get("plan_entry_sha256") == sha256_json(row)]
            if not runs:
                continue
            run = runs[-1]
            if source_files_error(task_dir, evidence, run):
                continue
            reviews = [review for review in task.get("discovery_followups", []) if review.get("role") == "review"
                and review.get("parent_query_id") == row.get("query_id") and review.get("source_run_id") == run.get("run_id")]
            # The latest decision is authoritative for this input, not an older
            # bounded stop that was subsequently reopened.
            review = reviews[-1] if reviews else None
            unknown = reviewed_unknown_submission(task, plan, evidence, candidates, ledger, row, supplement, task_dir=task_dir)
            if row.get("action_purpose") != "discovery" and not unknown:
                continue
            expected_outcome = "stop_bounded_discovery" if run.get("status") in {"success", "no_result"} else "blocked"
            if (not review or review.get("outcome") != expected_outcome
                    or (run.get("submission_state") not in {"submitted", "not_submitted"} and not unknown)
                    or review_validation(task, plan, evidence, candidates, ledger, row, review, supplement)):
                continue
            proof = {"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                "review_sha256": sha256_json(review), "reasoning": review["reason"],
                "evidence_refs": list(review["evidence_ids"]),
                "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)}],
                **({"submission_review_refs": unknown} if unknown else {})}
            for scope in necessary_scenario_row_bindings(task, row):
                key = (scope["scenario_id"], row["jurisdiction"], row["right_type"])
                result.setdefault(key, []).append(proof)
    return result


def _figurative_na_proofs(task, plan, evidence, *, supplement=None, task_dir=None):
    """An empty, actually reviewed mark inventory can close a search-term todo."""
    from assessment_v24 import evidence_index, _entry_matches_run, _retained_artifacts_complete
    from record_asset_provenance import asset_scope, investigation_complete, INVESTIGATION_STEPS
    from runtime_v24 import source_files_complete
    from workflow_v24 import scenario_row_bindings
    from pathlib import Path
    if task_dir is None or task.get("specialty_workflow_revision") != "asset-scope-v1":
        return {}
    registry = evidence_index(evidence)
    registry.update({item["evidence_id"]: item for item in (supplement or {}).get("evidence", [])
        if isinstance(item, dict) and item.get("evidence_id")})
    result = {}
    runs = {run["run_id"]: run for run in evidence.get("source_runs", [])}
    for query in plan.get("queries", {}).get("asset_provenance", []):
        if query.get("right_type") != "trademark_figurative" or query.get("candidate_id"):
            continue
        bindings = scenario_row_bindings(task, query)
        if len(bindings) != 1:
            continue
        sid = bindings[0]["scenario_id"]
        inventory = asset_scope(task, sid, "trademark_figurative")
        if not inventory["inventory_reviewed"] or inventory["asset_ids"]:
            continue
        matches = [entry for entry in registry.values() if entry.get("query_id") == query.get("query_id")
            and entry.get("provider") == "asset_provenance" and entry.get("plan_entry_sha256") == sha256_json(query)]
        for entry in matches[-1:]:
            run = runs.get(entry.get("source_run_id"), {})
            payload = entry.get("payload", {})
            if (run.get("status") != "success" or not _entry_matches_run(entry, run)
                    or not source_files_complete(Path(task_dir), evidence, run)
                    or not _retained_artifacts_complete(payload)
                    or not investigation_complete(task, payload, query, sid, registry)):
                continue
            key = (sid, query["jurisdiction"], query["right_type"])
            result.setdefault(key, {})[query["search_dimension"]] = {
                "evidence_refs": [entry["evidence_id"], *inventory["review"]["evidence_refs"]],
                "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)}],
                "reasoning": inventory["review"]["reasoning"]}
    return {scope: list(steps.values()) for scope, steps in result.items()
        if set(INVESTIGATION_STEPS["trademark_figurative"]) <= set(steps)}


def _resolve_evidence_limits(task, view, plan, capabilities, evidence, candidates, ledger,
                             *, supplement=None, task_dir=None, coverage=None):
    """Resolve delivery only; never change official coverage or evidence authority."""
    bounded = _bounded_discovery_proofs(task, plan, evidence, candidates, ledger,
        supplement=supplement, task_dir=task_dir)
    absent_marks = _figurative_na_proofs(task, plan, evidence, supplement=supplement, task_dir=task_dir)
    from api_first_planning import reviewed_unknown_submission
    rows = {row["query_id"]: row for values in plan.get("queries", {}).values() for row in values}
    # Resolve the base workflow's duplicate unknown obligation using the same
    # exact review as the API projection. The underlying submission stays unknown.
    for entry in view["entries"]:
        if entry.get("state") != "submission_unknown" or entry.get("query_id") not in rows:
            continue
        audited = reviewed_unknown_submission(task, plan, evidence, candidates, ledger,
            rows[entry["query_id"]], supplement, task_dir=task_dir)
        if audited:
            reason = "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW"
            entry.update(state="blocked", kind="source_lookup", reason=reason, submission_state="unknown",
                delivery_limit={"kind": "source_constraint", "reason": reason, "official_verification": "not_verified",
                    "source_run_refs": [{"run_id": item["run_id"], "sha256": item["source_run_sha256"]} for item in audited],
                    "capability_refs": [], "submission_review_refs": audited})
    original = deepcopy(view["entries"])
    for entry in view["entries"]:
        proof = _route_absence_proof(task, entry, plan, capabilities, evidence, candidates, ledger, supplement=supplement)
        if proof:
            entry["delivery_limit"]["route_absence"] = proof
        # A reservation is unused capacity, not an exhausted source. It must be
        # allocated, legitimately cancelled, or replaced by a precise blocker.
        if entry.get("reason") == "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP":
            entry.update(state="ready", kind="plan_repair")
            continue
        if entry.get("reason") == "LANGUAGE_TERM_REPAIR_REQUIRED" and _scope(entry) not in absent_marks:
            continue
        scope = _scope(entry)
        no_mark = scope in absent_marks and (_official_coverage_gap(entry)
            or entry.get("reason") == "API_DISCOVERY_TERMS_MISSING")
        if not no_mark and not _official_coverage_gap(entry):
            continue
        proofs = absent_marks.get(scope) if no_mark else bounded.get(scope)
        if not proofs:
            continue
        # A reviewed web result is not permission to skip an authorized official
        # route. Resolve every compiled route for this exact axis against the
        # frozen capabilities or an actual retained attempt before stopping.
        routes_closed, route_proofs = _axis_route_limits(task, entry, plan, evidence, capabilities,
            original, task_dir=task_dir, candidates=candidates, ledger=ledger, supplement=supplement) if not no_mark else (True, [])
        if not routes_closed:
            entry.update(state="ready", kind="plan_repair", reason="AUTHORIZED_ALTERNATIVE_REQUIRES_PLANNING")
            continue
        # Ready investigations, missing terms, unreviewed cards, retained reads,
        # unknown submissions and reserved budgets cannot disappear behind an
        # official-coverage limitation. Their own exact obligations stay open.
        # A bounded limitation belongs to this exact official axis. Other
        # executable work in the same scenario remains visible as its own
        # entry and still blocks publication; it must not prevent this axis
        # from being accurately labeled unknown. The no-mark disposition is
        # different: it needs the whole mark inventory workflow to be clear.
        exact_axis_stop = any(item.get('direction_id') and item.get('coverage_status') == 'unknown'
            and item.get('reason') == 'BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED'
            for item in route_proofs)
        gap_code = str(entry.get('planning_gap') or entry.get('reason') or '')
        requirement = next((row for row in task.get('coverage_requirements', [])
            if row.get('requirement_id') == gap_code.split(':', 1)[0]), None)
        axis = gap_code.split(':AXIS_MISSING:', 1)[-1]
        exact_axis_stop |= bool(requirement and ':AXIS_MISSING:' in gap_code
                                and not _route_options(task, requirement, axis))
        unfinished = ([other for other in original if _scope(other) in {scope, (None, None, None)}
            and not _official_coverage_gap(other)
            and other.get("reason") != "API_DISCOVERY_TERMS_MISSING"
            and (other.get("state") in {"ready", "awaiting_review", "submission_unknown"}
                 or other.get("reason") == "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP")]
            if no_mark or not exact_axis_stop else [])
        if unfinished:
            continue
        entry.setdefault("planning_gap", entry.get("reason"))
        entry.update(state="blocked", kind="scope_disposition" if no_mark else "retained_limitation",
            reason="REVIEWED_NO_APPLICABLE_FIGURATIVE_MARK" if no_mark else "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED",
            official_verification="not_applicable" if no_mark else "not_verified",
            reasoning=("已完成当前标识盘点及图像审阅；该范围没有已确认且适用的图形标。" if no_mark else
                "已审阅本范围留存的来源回执及已取得材料；所列官方检索维度仍未核验，失败或未知提交不代表无命中，保留为本轮证据报告的限制。"),
            evidence_refs=list(dict.fromkeys(ref for proof in proofs for ref in proof["evidence_refs"])),
            source_run_refs=list({proof["run_id"]: proof for item in proofs for proof in item["source_run_refs"]}.values()),
            resolution_refs=deepcopy(proofs), route_limit_refs=route_proofs)
    return view


def _project_selected_expansion_limits(task, view, original, plan, capabilities, evidence,
                                       candidates, ledger, *, supplement=None, task_dir=None):
    """Replace only legacy selected-expansion presence gaps with exact current proof.

    This is a delivery projection: coverage, candidate decisions, and assessment
    completeness remain untouched. Any current actionable Module 06 work or
    changed source/query evidence leaves the legacy obligation ready.
    """
    if not task.get("specialty_analysis_revision") or task_dir is None:
        return
    from decision_workflow import triage_summary
    from specialty_analysis import project as specialty_project, work_entries as specialty_work_entries
    triage = triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement)
    selected = {(row.get("candidate_id"), row.get("scenario_id"), row.get("jurisdiction"), row.get("right_type")):
        row for row in triage.get("records", []) if row.get("current") and row.get("decision") == "selected"}
    stage_work = []
    if task.get("triage_stage_revision"):
        from candidate_triage_stage import project as triage_stage_project, work_entries as triage_stage_work
        triage_stage = triage_stage_project(task, evidence, candidates, ledger, plan=plan,
            source_work=original, task_dir=task_dir, supplement=supplement)
        stage_work = triage_stage_work(triage_stage)
    specialty = specialty_project(task, evidence, candidates, ledger, supplement=supplement,
        source_work=[*original, *stage_work], plan=plan, capabilities=capabilities, task_dir=task_dir)
    module_work = specialty_work_entries(specialty)
    for entry in view.get("entries", []):
        reason = str(entry.get("reason") or "")
        if not reason.startswith(("SELECTED_EXPANSION_UNPLANNED:", "SELECTED_VERIFICATION_UNPLANNED:")):
            continue
        candidate_id = reason.split(":", 1)[1]
        entry["candidate_id"] = candidate_id
        key = (candidate_id, entry.get("scenario_id"), entry.get("jurisdiction"), entry.get("right_type"))
        selected_record = selected.get(key)
        if not selected_record:
            continue
        current_module = [row for row in module_work if all(row.get(field) == value for field, value in zip(
            ("candidate_id", "scenario_id", "jurisdiction", "right_type"), key))]
        if not current_module or any(row.get("state") in {"ready", "awaiting_review", "submission_unknown"}
                                     for row in current_module):
            continue
        if reason.startswith("SELECTED_VERIFICATION_UNPLANNED:"):
            proof = _selected_verification_disposition(entry, selected_record, specialty, module_work)
            if proof:
                entry.update(state="blocked", kind="retained_limitation",
                    reason="SELECTED_VERIFICATION_CURRENT_DISPOSITION_UNVERIFIED",
                    limitation_kind="candidate_verification_pending", official_verification="not_verified",
                    coverage_status="unknown", delivery_limit=proof,
                    reasoning="当前候选已读原件及逐项专项比较已登记；各未核实事实仍按当前精确限制或等待保留。旧核验行的存在性要求不产生重复查询，也不证明核验完成。")
            continue
        if entry.get("right_type") == "patent":
            delegated = next((row for row in current_module
                if row.get("delivery_limit", {}).get("kind") == "specialty_discovery_delegation"
                and _delivery_limit_valid(row, task, evidence, plan, capabilities, candidates=candidates,
                    ledger=ledger, supplement=supplement, task_dir=task_dir)), None)
            if not delegated:
                continue
            proof = {"kind": "selected_expansion_delegated", "candidate_id": candidate_id,
                "scenario_id": entry.get("scenario_id"), "jurisdiction": entry.get("jurisdiction"),
                "right_type": entry.get("right_type"), "delegation": deepcopy(delegated["delivery_limit"])}
            entry.update(state="blocked", kind="retained_limitation", reason="SELECTED_EXPANSION_WITH_CURRENT_DELEGATION",
                limitation_kind="residual_discovery_pending", official_verification="not_verified",
                delivery_limit=proof, reasoning="该候选的当前精确家族/残余发现委派仍有效；保留残余范围未知，不把委派视为检索完成。")
        elif entry.get("right_type") == "design":
            proof = _selected_design_expansion_proof(task, entry, selected_record, plan, evidence,
                candidates, ledger, supplement=supplement, task_dir=task_dir, current_entries=view.get("entries", []))
            if not proof:
                continue
            entry.update(state="blocked", kind="retained_limitation", reason="BOUNDED_SELECTED_DESIGN_EXPANSION_UNVERIFIED",
                limitation_kind="bounded_discovery_pending", official_verification="not_verified",
                coverage_status="unknown", delivery_limit=proof,
                reasoning="当前官方设计检索仅覆盖已取得并逐条分流的页面；未取得结果仍未知，不代表无命中或检索完成。")


def _selected_verification_disposition(entry, selected_record, specialty, module_work):
    """Bind a legacy row-presence gap to current, independently validated M06 work.

    This retains an incomplete verification scope; it never proves current
    enforceability, ownership, or a product comparison that is still unknown.
    """
    fields = ("candidate_id", "scenario_id", "jurisdiction", "right_type")
    scope = next((row for row in specialty.get("scopes", [])
                  if all(row.get(key) == entry.get(key) for key in fields)), None)
    work = [row for row in module_work if all(row.get(key) == entry.get(key) for key in fields)]
    if (not scope or not scope.get("intake_event_id") or not work
            or any(row.get("state") in {"ready", "awaiting_review", "submission_unknown"} for row in work)):
        return None
    current = [row for row in scope.get("results", []) if row.get("currently_usable") is True]
    if (not all(any(row.get("kind") == "fact" and row.get("fact_kind") == fact
                    and row.get("outcome") == "supported" for row in current)
                for fact in ("identity", "protection"))
            or not any(row.get("kind") == "comparison" for row in current)):
        return None
    return {"kind": "selected_verification_disposition",
        **{key: entry.get(key) for key in fields},
        "annotation_sha256": sha256_json(selected_record.get("annotation") or {}),
        "intake_event_id": scope["intake_event_id"], "specialty_scope_sha256": sha256_json(scope),
        "specialty_work_sha256": sha256_json(work),
        "official_verification": "not_verified", "coverage_status": "unknown"}


def _selected_design_expansion_proof(task, entry, selected_record, plan, evidence, candidates, ledger,
                                    *, supplement=None, task_dir=None, current_entries=None):
    """Bind a legacy design expansion gap to its candidate's exact bounded official retrieval."""
    if task_dir is None:
        return None
    from pathlib import Path
    from workflow_v24 import necessary_scenario_row_bindings, validated_query_cancellation
    requirements = [req for req in task.get("coverage_requirements", [])
        if (req.get("jurisdiction"), req.get("right_type")) == (entry.get("jurisdiction"), entry.get("right_type"))]
    needed_axes = sorted({axis for req in requirements for axis in req.get("required_axes", [])})
    if not requirements or not needed_axes:
        return None
    req_by_axis = {axis: next((req for req in requirements if axis in req.get("required_axes", [])), None)
        for axis in needed_axes}
    annotation = selected_record.get("annotation") or {}
    candidate = next((row for collection in ("patents", "trademarks", "copyright_assets", "enforcement")
        for row in candidates.get(collection, []) if row.get("candidate_id") == entry.get("candidate_id")), {})
    if not candidate or annotation.get("candidate_id") != entry.get("candidate_id"):
        return None
    source_run_ids = {source.get("source_run_id") for source in candidate.get("sources", [])
        if isinstance(source, dict) and source.get("source_run_id")}
    matches = []
    for provider, rows in plan.get("queries", {}).items():
        for row in rows:
            if (validated_query_cancellation(task, plan, row) or row.get("action_purpose") != "discovery"
                    or row.get("right_type") != entry.get("right_type")
                    or row.get("jurisdiction") != entry.get("jurisdiction")
                    or not any(binding.get("scenario_id") == entry.get("scenario_id")
                               for binding in necessary_scenario_row_bindings(task, row))):
                continue
            runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
                and run.get("query_id") == row.get("query_id") and run.get("plan_entry_sha256") == sha256_json(row)
                and run.get("run_id") in source_run_ids]
            for run in runs:
                matches.append((provider, row, run))
    if len(matches) != 1:
        return None
    provider, row, run = matches[0]
    if not str(provider).startswith("uspto_"):
        return None
    from runtime_v24 import source_files_complete
    if run.get("status") not in {"success", "no_result"} or not source_files_complete(Path(task_dir), evidence, run):
        return None
    axes = {}
    for axis in needed_axes:
        requirement = req_by_axis[axis]
        if not requirement:
            return None
        # Image retrieval uses its own typed route/scope proof; USPTO text and
        # classification retrievals are independently bound to their own runs.
        if axis == "image":
            matching_limit = next((other for other in (current_entries or []) if other.get("planning_gap") ==
                requirement["requirement_id"] + ":AXIS_MISSING:" + axis
                and _scope(other) == _scope(entry) and other.get("state") == "blocked"), None)
            if current_entries is not None and not matching_limit:
                return None
            proofs = _bounded_discovery_proofs(task, plan, evidence, candidates, ledger,
                supplement=supplement, task_dir=task_dir).get(_scope(entry), [])
            refs = matching_limit.get("resolution_refs", []) if matching_limit else proofs
            current_refs = [proof for proof in proofs if proof.get("query_id") in {
                ref.get("query_id") for ref in refs if isinstance(ref, dict)}]
            if not current_refs or any(proof not in refs for proof in current_refs):
                return None
            axes[axis] = {"proof_kind": "current_official_bounded_axis", "resolution_refs": deepcopy(current_refs),
                "coverage_status": "unknown", "official_verification": "not_verified"}
            continue
        proxy = {**{field: entry.get(field) for field in ("scenario_id", "jurisdiction", "right_type")},
            "planning_gap": requirement["requirement_id"] + ":AXIS_MISSING:" + axis}
        proofs = _current_axis_bounded_stop(task, proxy, requirement, axis, plan, evidence,
            candidates, ledger, supplement=supplement, task_dir=task_dir)
        matching = [proof for proof in proofs if (axis != "text" or proof.get("query_id") == row.get("query_id")
            and any(ref.get("run_id") == run.get("run_id") for ref in proof.get("source_run_refs", [])))]
        if len(matching) != 1:
            return None
        axes[axis] = matching[0]
    # Every retrieved card must remain triaged for this exact source run.
    from candidate_triage_stage import project as triage_project
    triage = triage_project(task, evidence, candidates, ledger, plan=plan,
        source_work=[], task_dir=task_dir, supplement=supplement)
    batch = next((item for item in triage.get("batches", []) if item.get("batch_id") == run.get("run_id")), None)
    if not batch or candidate.get("candidate_id") not in batch.get("candidate_ids", []) \
            or candidate.get("candidate_id") in batch.get("triage_pending_candidate_ids", []):
        return None
    return {"kind": "selected_expansion_bounded", "candidate_id": entry.get("candidate_id"),
        "scenario_id": entry.get("scenario_id"), "jurisdiction": entry.get("jurisdiction"),
        "right_type": entry.get("right_type"), "annotation_sha256": sha256_json(annotation),
        "candidate_sha256": sha256_json(candidate), "source_run_id": run.get("run_id"),
        "source_run_sha256": sha256_json(run), "query_id": row.get("query_id"),
        "plan_entry_sha256": sha256_json(row), "axis_proofs": axes,
        "unknown_unretrieved_result_row_count": run.get("unretrieved_result_row_count"),
        "official_verification": "not_verified", "coverage_status": "unknown"}


def _axis_route_limits(task, entry, plan, evidence, capabilities, entries, *, task_dir=None,
                       candidates=None, ledger=None, supplement=None):
    """Bound alternatives by compiler, exact attempt and capability, never prose."""
    from pathlib import Path
    from runtime_v24 import source_files_complete
    from workflow_v24 import necessary_scenario_row_bindings
    gap = str(entry.get("planning_gap") or entry.get("reason") or "")
    requirement = next((row for row in task.get("coverage_requirements", [])
        if row.get("requirement_id") == gap.split(":", 1)[0]), None)
    if not requirement:
        return False, []
    axis = gap.split(":AXIS_MISSING:", 1)[1] if ":AXIS_MISSING:" in gap else "text"
    # A classification axis with a current, fully reviewed bounded retrieval
    # is a valid *limited-evidence* endpoint for this report. Do not keep
    # asking for a second route merely because a static route compiler can
    # describe one; the result and every retrieved card remain reviewed, while
    # the unvisited official coverage stays explicitly unknown.
    bounded = _current_axis_bounded_stop(task, entry, requirement, axis, plan, evidence,
        candidates, ledger, supplement=supplement, task_dir=task_dir)
    if bounded:
        return True, bounded
    options = _route_options(task, requirement, axis)
    proofs = []
    scope_bound = _reviewed_browser_scope_limit(task, entry, plan, evidence, candidates, ledger,
        supplement=supplement, task_dir=task_dir)
    fields = ("provider", "state", "reason", "executable", "credentials_present", "checked_at", "cost_ceiling_usd")
    for option in options:
        provider = option["provider"]
        cap = capabilities.get(provider, {})
        attempts = []
        for row in plan.get("queries", {}).get(provider, []):
            if (row.get("search_dimension") != axis or requirement["requirement_id"] not in row.get("requirement_ids", [])
                    or (row.get("jurisdiction"), row.get("right_type")) != (entry.get("jurisdiction"), entry.get("right_type"))
                    or not any(binding["scenario_id"] == entry.get("scenario_id") for binding in necessary_scenario_row_bindings(task, row))):
                continue
            runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
                and run.get("query_id") == row["query_id"] and run.get("plan_entry_sha256") == sha256_json(row)]
            run = runs[-1] if runs else {}
            if (task_dir is not None and run.get("status") in {"success", "no_result"}
                    and source_files_complete(Path(task_dir), evidence, run)):
                attempts.append({"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                    "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)}]})
            elif any(other.get("query_id") == row["query_id"] and other.get("provider") == provider
                    and other.get("state") in {"awaiting_access", "blocked"}
                    and (other.get("reason") in _ACCESS_REASONS | _BLOCKED_REASONS
                         or _delivery_limit_valid(other, task, evidence, plan, capabilities,
                             candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir)) for other in entries):
                attempts.append({"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                    "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)}] if run else []})
        if attempts:
            proofs.append({"provider": provider, "operation": option["operation"], "attempts": attempts})
        elif provider.endswith("browser") and scope_bound:
            proofs.append({"provider": provider, "operation": option["operation"], **deepcopy(scope_bound)})
        elif provider.endswith("browser") and task.get("retrieval_workflow_revision") == "api-first-v2":
            # V2 fallback requires a known-submission parent. If every exact
            # API parent for this axis has an audited unknown receipt, that
            # browser fallback cannot be materialized. Keep the uncertainty;
            # do not ask for a plan the recorder must reject.
            from api_first_planning import reviewed_unknown_submission, API_PROVIDERS
            parents = [row for name, values in plan.get("queries", {}).items() if name in API_PROVIDERS
                for row in values if row.get("action_purpose") == "discovery"
                and row.get("search_dimension") == axis
                and requirement["requirement_id"] in row.get("requirement_ids", [])
                and (row.get("jurisdiction"), row.get("right_type")) ==
                    (entry.get("jurisdiction"), entry.get("right_type"))
                and any(binding["scenario_id"] == entry.get("scenario_id")
                    for binding in necessary_scenario_row_bindings(task, row))]
            audits = [reviewed_unknown_submission(task, plan, evidence, candidates, ledger, row,
                supplement, task_dir=task_dir) for row in parents]
            if not parents or not all(audits):
                if _route_state([option], capabilities)[0] == "ready":
                    return False, []
                proofs.append({"provider": provider, "operation": option["operation"], "reason": cap.get("reason"),
                    "capability_sha256": sha256_json({key: cap[key] for key in fields if key in cap})})
            else:
                proofs.append({"provider": provider, "operation": option["operation"],
                    "reason": "V2_FALLBACK_PARENT_SUBMISSION_UNKNOWN", "submission_review_refs": audits,
                    "completed_search": False, "official_verification": "not_verified"})
        elif _route_state([option], capabilities)[0] != "ready":
            proofs.append({"provider": provider, "operation": option["operation"], "reason": cap.get("reason"),
                "capability_sha256": sha256_json({key: cap[key] for key in fields if key in cap})})
        else:
            return False, []
    return True, proofs


def _current_axis_bounded_stop(task, entry, requirement, axis, plan, evidence, candidates, ledger,
                               *, supplement=None, task_dir=None):
    """Return exact classification-axis stop proofs, without awarding coverage."""
    if (axis not in {"classification", "text"} or task_dir is None or candidates is None or ledger is None
            or entry.get("scenario_id") is None):
        return []
    from workflow_v24 import necessary_scenario_row_bindings
    official_routes = {(route.get("provider"), route.get("operation"))
        for route in requirement.get("routes", [])
        if isinstance(route, dict) and route.get("operation") not in {
            "candidate_detail", "candidate_verification", "document_retrieval"}}
    if not official_routes:
        return []
    proofs = []
    for provider, rows in plan.get("queries", {}).items():
        for row in rows:
            if (row.get("action_purpose") != "discovery"
                    or row.get("search_dimension") != axis
                    or (provider, row.get("operation")) not in official_routes
                    or requirement.get("requirement_id") not in row.get("requirement_ids", [])
                    or (row.get("jurisdiction"), row.get("right_type")) !=
                       (entry.get("jurisdiction"), entry.get("right_type"))
                    or not any(binding.get("scenario_id") == entry.get("scenario_id")
                               for binding in necessary_scenario_row_bindings(task, row))):
                continue
            runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
                    and run.get("query_id") == row.get("query_id")
                    and run.get("plan_entry_sha256") == sha256_json(row)
                    and run.get("status") in {"success", "no_result"}]
            if not runs:
                continue
            run = runs[-1]
            directions = {item.get("direction_id") for item in row.get("product_dependencies", [])
                if isinstance(item, dict) and item.get("scenario_id") == entry.get("scenario_id")
                and item.get("right_type") == entry.get("right_type") and item.get("direction_id")}
            if row.get("direction_id"):
                directions.add(row["direction_id"])
            # Historical API-first tasks have no product-direction contract.
            # Require their native exact-row bounded review instead; absence
            # of a newer field must not discard a retained, fully triaged stop.
            from product_scope import enabled as product_scope_enabled
            if not directions and not product_scope_enabled(task):
                matching = [proof for proof in _bounded_discovery_proofs(task, plan, evidence,
                    candidates, ledger, supplement=supplement, task_dir=task_dir).get(_scope(entry), [])
                    if proof.get("query_id") == row["query_id"]
                    and proof.get("plan_entry_sha256") == sha256_json(row)]
                if matching:
                    proofs.append({"provider": provider, **deepcopy(matching[-1]),
                        "coverage_status": "unknown", "official_verification": "not_verified",
                        "reason": "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED"})
                    continue
            valid_direction = None
            for direction_id in sorted(directions):
                wait_entry = {"scenario_id": entry.get("scenario_id"),
                    "jurisdiction": entry.get("jurisdiction"), "right_type": entry.get("right_type"),
                    "direction_id": direction_id, "provider": provider,
                    "query_id": row.get("query_id"), "plan_entry_sha256": sha256_json(row),
                    "source_run_id": run.get("run_id")}
                if _current_semantic_wait(task, plan, evidence, candidates, ledger, supplement,
                        task_dir, wait_entry, row, fault=False):
                    valid_direction = direction_id
                    break
            if not valid_direction:
                continue
            proofs.append({"provider": provider, "query_id": row["query_id"],
                "plan_entry_sha256": sha256_json(row),
                "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)}],
                "direction_id": valid_direction,
                "coverage_status": "unknown", "official_verification": "not_verified",
                "reason": "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED"})
    return proofs


def _reviewed_browser_scope_limit(task, entry, plan, evidence, candidates, ledger, *, supplement=None, task_dir=None):
    """A scope budget is a delivery limit only after its real attempts are read.

    Use the planner's existing capacity and per-country/right policy. Planned
    reservations and duplicate/renamed rows do not prove performed work. An
    audited unknown submission may retain a slot, but is never a completed
    search or exhausted recovery; its reservation is disclosed separately.
    """
    from api_first_planning import _capacity_rows, policy_limit, dispatch_block, reviewed_unknown_submission
    from discovery_budget import enabled as purpose_budget_enabled
    if purpose_budget_enabled(task):
        return None  # The legacy scope-wide limit cannot close a purpose-level obligation.
    from workflow_v24 import necessary_scenario_row_bindings, action_attempt_state, browser_submitted_failure_state
    from runtime_v24 import source_files_complete
    from pathlib import Path
    if task_dir is None or candidates is None or ledger is None:
        return None
    bound = policy_limit(task, "browser_fallback_queries_per_scope", 2)
    rows = [(provider, row) for provider, row in _capacity_rows(task, plan, evidence)
        if provider.endswith("browser") and row.get("discovery_role") == "browser_fallback"
        and (row.get("jurisdiction"), row.get("right_type")) == (entry.get("jurisdiction"), entry.get("right_type"))]
    if len(rows) != bound or len({row["query_id"] for _, row in rows}) != bound:
        return None
    reviewed = _bounded_discovery_proofs(task, plan, evidence, candidates, ledger,
        supplement=supplement, task_dir=task_dir).get(_scope(entry), [])
    attempts, unknown_slots = [], 0
    for provider, row in rows:
        if not any(scope["scenario_id"] == entry.get("scenario_id") for scope in necessary_scenario_row_bindings(task, row)):
            return None
        runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
            and run.get("query_id") == row["query_id"] and run.get("plan_entry_sha256") == sha256_json(row)]
        if not runs:
            return None
        proof = next((item for item in reviewed if item["query_id"] == row["query_id"]
            and item["plan_entry_sha256"] == sha256_json(row)), None)
        if not proof:
            return None
        block = dispatch_block(task, plan, evidence, candidates, ledger, provider, row,
                               supplement, task_dir=task_dir)
        attempt = {"provider": provider, "discovery_intent_id": row.get("discovery_intent_id"), **deepcopy(proof)}
        if any(run.get("submission_state") not in {"submitted", "not_submitted"} for run in runs):
            audits = reviewed_unknown_submission(task, plan, evidence, candidates, ledger, row, supplement, task_dir=task_dir)
            if not audits or block not in {None, "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY"}:
                return None
            attempt["submission_reservation"] = {"reason": "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW",
                "submission_review_refs": audits, "completed_search": False,
                "reasoning": "原回执已核对但提交仍未知；原名额必须保留且禁止重发，不代表检索完成或实际调用耗尽。"}
            unknown_slots += 1
        else:
            if block or runs[-1].get("submission_state") != "submitted":
                return None
            if runs[-1].get("status") not in {"success", "no_result"}:
                recovery = browser_submitted_failure_state(task, evidence, provider, row)
                if (action_attempt_state(evidence, provider, row)["state"] != "submitted" or not recovery
                        or recovery.get("state") != "blocked" or recovery.get("reason") != "BROWSER_SUBMITTED_FAILURE_RECOVERY_EXHAUSTED"
                        or recovery.get("remaining_attempts") != 0):
                    return None
                recovered_ids = {ref["run_id"] for ref in recovery["source_run_refs"]}
                if any(not source_files_complete(Path(task_dir), evidence, run) for run in runs if run["run_id"] in recovered_ids):
                    return None
                attempt["recovery_limit"] = deepcopy(recovery)
        attempts.append(attempt)
    return {"reason": "API_DISCOVERY_BROWSER_SCOPE_RESERVED_FOR_UNKNOWN_SUBMISSION" if unknown_slots else "API_DISCOVERY_BROWSER_SCOPE_LIMIT", "limit": bound,
        **({"unknown_reserved_slots": unknown_slots, "known_attempt_slots": len(attempts) - unknown_slots} if unknown_slots else {}),
        "policy_sha256": sha256_json(task.get("retrieval_policy")), "attempts": attempts,
        "official_verification": "not_verified"}


def _cancelled_discovery_execution_closed(task, entry, plan, evidence, candidates, ledger,
                                         supplement=None, *, task_dir=None):
    """A cancelled execution is archived only after its real retained work ends."""
    if (task.get('retrieval_workflow_revision') != 'api-first-v3' or task_dir is None
            or entry.get('kind') != 'source_lookup' or entry.get('reason') != 'SCENARIO_ACTION_CANCELLED'):
        return False
    from workflow_v24 import validated_query_cancellation
    from recovery_stage_b import effective_submission
    from api_first_planning import retained_discovery_work
    from source_result_processing import progress
    from pathlib import Path
    provider = entry.get('provider')
    rows = [row for row in plan.get('queries', {}).get(provider, []) if row.get('query_id') == entry.get('query_id')]
    if (len(rows) != 1 or rows[0].get('action_purpose') != 'discovery'
            or not validated_query_cancellation(task, plan, rows[0])
            or any(rows[0].get(k) != entry.get(k) for k in ('jurisdiction','right_type'))):
        return False
    row = rows[0]
    runs = [run for run in evidence.get('source_runs', []) if run.get('provider') == provider
        and run.get('query_id') == row['query_id'] and run.get('plan_entry_sha256') == sha256_json(row)]
    try:
        for run in runs:
            if effective_submission(evidence, run) not in {'submitted','not_submitted'}:
                return False
            from recovery_stage_b import _latest
            review = _latest(evidence,run,'failure_review')
            if run.get('status') in {'failed','access_limited'} and (not review
                    or not all(review.get(k) for k in ('receipt_review','material_review','failure_cause',
                        'remaining_work','repair_basis','reviewer','reasoning','source_rule_ref'))
                    or review.get('review_id') != 'REC-REV-' + sha256_json({k:v for k,v in review.items()
                        if k != 'review_id'})[:24]):
                return False
            if isinstance(run.get('result_processing'),dict):
                if not progress(Path(task_dir),run,evidence)['material_processing_complete']:
                    return False
            else:
                # Some historical adapter failures kept only the error/run.
                # Reuse the actual 08B missing-body audit, never invent a read.
                from assessment_v24 import _source_records
                if (run.get('status') not in {'failed','access_limited'} or run.get('raw_paths')
                        or _source_records(evidence,run.get('run_id')) or not review
                        or not all(review.get(k) for k in ('receipt_absence_reason','receipt_review',
                            'material_review','failure_cause','remaining_work','reviewer','reasoning','source_rule_ref'))
                        or review.get('review_id') != 'REC-REV-' + sha256_json({k:v for k,v in review.items()
                            if k != 'review_id'})[:24]):
                    return False
        return retained_discovery_work(task,evidence,candidates,ledger,provider,row,supplement,
            task_dir=task_dir) is None
    except (ValueError,OSError,KeyError,TypeError):
        return False


def _cancelled_discovery_limit_entry(task, entry, plan, evidence, candidates, ledger,
                                    supplement=None, *, task_dir=None):
    if not _cancelled_discovery_execution_closed(task,entry,plan,evidence,candidates,ledger,
            supplement,task_dir=task_dir):
        return None
    from workflow_v24 import validated_query_cancellation
    from recovery_stage_b import _latest
    row = next(r for r in plan['queries'][entry['provider']] if r['query_id'] == entry['query_id'])
    failures = [r for r in evidence.get('source_runs',[]) if r.get('provider') == entry['provider']
        and r.get('query_id') == row['query_id'] and r.get('plan_entry_sha256') == sha256_json(row)
        and r.get('status') in {'failed','access_limited'}]
    if not failures:
        return None
    audits = [_latest(evidence,run,'failure_review') for run in failures]
    proof = {'kind':'cancelled_discovery_failure', 'plan_entry_sha256':sha256_json(row),
        'cancellation_sha256':sha256_json(validated_query_cancellation(task,plan,row)),
        'failure_run_refs':[{'run_id':run['run_id'],'sha256':sha256_json(run)} for run in failures],
        'failure_review_refs':[{'review_id':review['review_id'],'sha256':sha256_json(review)}
            for review in audits if review], 'official_verification':'not_verified'}
    missing = [review['receipt_absence_reason'] for review in audits if review and review.get('receipt_absence_reason')]
    return {**entry,'kind':'coverage_information','state':'blocked',
        'reason':'CANCELLED_DISCOVERY_FAILURE_UNVERIFIED','coverage_status':'unknown',
        'official_verification':'not_verified','delivery_limit':proof,
        'limitation_kind':'cancelled_failed_discovery',
        'reasoning':'该原发现请求已失败且执行已合法取消；不是成功、有效零结果或充分检索。'
            + ('原正文缺失：'+'；'.join(dict.fromkeys(missing)) if missing else '已取得材料按原记录处理，原失败仍保留。'),
        'resume_condition':'取得针对所列原发现范围的有效新材料及相应实际审阅。'}


def refine_work_view(task, view, plan, capabilities, *, evidence=None, candidates=None,
                     ledger=None, supplement=None, task_dir=None, coverage=None,
                     _skip_selected_disposition=False):
    """Only marked tasks refine unsupported routes; investigation status stays separate."""
    if not enabled(task):
        return view
    view = deepcopy(view)
    if all(value is not None for value in (evidence,candidates,ledger)):
        kept = []
        for entry in view['entries']:
            if _cancelled_discovery_execution_closed(task,entry,plan,evidence,candidates,ledger,
                    supplement,task_dir=task_dir):
                view.setdefault('information',[]).append({**entry,'state':'information',
                    'execution_disposition':'cancelled_retained_work_processed'})
                limit = _cancelled_discovery_limit_entry(task,entry,plan,evidence,candidates,ledger,
                    supplement,task_dir=task_dir)
                if limit:
                    kept.append(limit)
            else:
                kept.append(entry)
        view['entries'] = kept
    from workflow_v24 import product_analysis_readiness
    for gap in product_analysis_readiness(task).get("gaps", []):
        entry = {"scenario_id": task.get("primary_scenario_id"), "kind": "product_analysis",
            "state": "ready", "reason": gap["code"]}
        entry["work_id"] = "WORK-" + sha256_json(entry)[:24]
        view["entries"].append(entry)
    reviewed_public_limits = set()
    requirements = {r["requirement_id"]: r for r in task.get("coverage_requirements", [])}
    rows = {r["query_id"]: r for values in plan.get("queries", {}).values()
        if isinstance(values, list) for r in values if isinstance(r, dict) and r.get("query_id")}
    # The semantic direction already emits a user_information/awaiting_user
    # obligation when the actual brand name is not supplied. Do not duplicate
    # that dependency as a ready/blocked route-planning task for an empty mark.
    # This is tightly scoped to the current own word-mark direction and only
    # applies when no corresponding discovery row exists.
    retained_entries = []
    for candidate in view["entries"]:
        gap = str(candidate.get("planning_gap") or "")
        projection_gap = (":AXIS_MISSING:" in gap or ":AXIS_MISSING:" in str(candidate.get("reason", ""))
            or ":LOCAL_LANGUAGE_MISSING" in gap or ":LOCAL_LANGUAGE_MISSING" in str(candidate.get("reason", ""))
            or candidate.get("code") == "API_DISCOVERY_TERMS_MISSING"
            or candidate.get("reason") == "API_DISCOVERY_TERMS_MISSING")
        route_gap = (candidate.get("kind") == "plan_repair"
            and candidate.get("right_type") == "trademark_word" and projection_gap)
        if route_gap:
            waiting_clues = _empty_word_mark_wait_clues(task, plan, evidence or {}, candidate)
            matching_wait = any(item.get("kind") == "user_information" and item.get("state") == "awaiting_user"
                and _scope(item) == _scope(candidate) and item.get("clue_id") in waiting_clues
                for item in view["entries"])
            if waiting_clues and matching_wait:
                continue
        retained_entries.append(candidate)
    view["entries"] = retained_entries
    original_entries = deepcopy(view["entries"])
    for entry in view["entries"]:
        reason = entry.get("reason", "")
        from completion_policy import evidence_delivery_enabled
        if evidence_delivery_enabled(task) and reason == "DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED" and entry.get("historical_expression_review_missing"):
            from recovery_stage_b import recovery_state
            row = rows.get(entry.get("query_id"))
            recovery = recovery_state(task, evidence or {}, entry.get("provider"), row) if row else None
            if (recovery and recovery.get("reason") in {"SUBMISSION_UNKNOWN_EVIDENCED_LIMIT", "SUBMISSION_UNKNOWN_DEPENDENCY"}
                    and any(ref.get("run_id") == entry.get("source_run_id") for ref in recovery.get("source_run_refs", []))):
                entry.update(kind="plan_repair", state=recovery["state"], reason=recovery["reason"],
                    recovery=deepcopy(recovery),
                    reasoning="原发现请求已尝试或提交未知，事前表达审阅不能补写；该计划缺口与同一原运行的有据限制一起披露，未来须建立新计划及事前审阅。")
                continue
        if evidence_delivery_enabled(task) and reason == "DISCOVERY_DIRECTION_QUERY_MISSING":
            related = [r for r in task.get("coverage_requirements", [])
                if (r.get("jurisdiction"), r.get("right_type")) == (entry.get("jurisdiction"), entry.get("right_type"))
                and r.get("phase") == "official_recall"]
            options = [option for requirement in related for option in _route_options(task, requirement, "text")]
            if related and not options:
                entry.update(kind="plan_repair", state="blocked", reason="NO_SUPPORTED_ROUTE",
                    route_options=[], planning_gap="DISCOVERY_DIRECTION_QUERY_MISSING",
                    reasoning="当前计划没有该方向的发现查询，且冻结覆盖合同无可编译的合格检索路线；官方覆盖未核验，待来源能力或计划变更后恢复。")
                continue
        if (evidence_delivery_enabled(task) and reason == "API_DISCOVERY_ROUTE_UNAVAILABLE"
                and not (entry.get("delivery_limit") or {}).get("source_run_refs")
                and not (entry.get("delivery_limit") or {}).get("capability_refs")):
            related = [r for r in task.get("coverage_requirements", [])
                if r.get("requirement_id") in entry.get("requirement_ids", [])]
            options = [option for requirement in related for option in _route_options(task, requirement,
                entry.get("search_dimension", "text"))]
            if related and not options:
                # Keep the original gap identity: its frozen route-absence proof
                # and publication validator bind to this exact reason.
                entry.update(state="blocked", kind="plan_repair", reason=reason,
                    route_options=[], planning_gap=reason,
                    reasoning="原计划记录 API 发现路线不可用；当前覆盖合同也没有可编译的合格替代路线。该来源范围仍未核验，待来源能力或计划变更后恢复。")
                continue
        if evidence_delivery_enabled(task) and reason.endswith(":LOCAL_LANGUAGE_MISSING"):
            from workflow_v24 import LANGUAGES
            language = LANGUAGES.get(entry.get("jurisdiction"), "")
            linked = _planned_language_queries(task, entry, plan, evidence or {}, candidates or {}, ledger or {},
                                               supplement=supplement, task_dir=task_dir)
            entry.update(planning_gap=reason, required_language=language)
            if linked:
                entry.update(state="blocked", kind="coverage_information", reason="LOCAL_LANGUAGE_BOUND_TO_PLANNED_QUERY",
                    query_refs=linked, official_verification="not_verified",
                    reasoning="目标语言已绑定所列实际编译查询；查询执行与审阅由对应工作项跟踪，官方覆盖尚未核验。")
            else:
                terms = [{key: term.get(key) for key in ("kind", "value", "language", "derived_from")}
                    for term in plan.get("terms", []) if term.get("kind") not in {"nice", "cpc", "ipc", "locarno", "owner"}]
                related = [r for r in task.get("coverage_requirements", [])
                    if (r.get("jurisdiction"), r.get("right_type")) == (entry.get("jurisdiction"), entry.get("right_type"))
                    and r.get("phase") == "official_recall"]
                options = [option for requirement in related for option in _route_options(task, requirement, "text")]
                if related and not options:
                    entry.update(state="blocked", kind="plan_repair", reason="NO_SUPPORTED_ROUTE",
                        source_terms=terms, route_options=[],
                        reasoning="已有目标语言词，但当前覆盖合同没有可编译的文本来源路线；不把来源缺口误报为翻译工作，官方覆盖仍未核验。")
                else:
                    entry.update(state="ready", kind="plan_repair", reason="LANGUAGE_TERM_REPAIR_REQUIRED",
                        source_terms=terms,
                        reasoning="缺少该范围的目标语言文本查询；使用现有目标语言词或补有来源的翻译/描述词重新编译，不能填写覆盖完成。")
            continue
        if reason in {"UNSUPPORTED_QUERY_SEMANTICS", "USPTO_QUERY_REJECTED"}:
            entry.update(state="ready", kind="plan_repair")
            row = rows.get(entry.get("query_id"), {})
            entry.update(query=row.get("q") or row.get("query"), derived_from=row.get("derived_from"),
                plan_entry_sha256=sha256_json(row) if row else None)
            continue
        axis = reason.split(":AXIS_MISSING:", 1)[1] if ":AXIS_MISSING:" in reason else None
        requirement = requirements.get(reason.split(":", 1)[0]) if axis else None
        if axis and requirement:
            options = _route_options(task, requirement, axis)
            entry["state"], entry["reason"] = _route_state(options, capabilities)
            entry["planning_gap"] = reason
            entry["route_options"] = [{k: route[k] for k in ("provider", "operation") if k in route} for route in options]
        elif entry.get("state") in {"awaiting_access", "blocked"} and entry.get("query_id"):
            row = rows.get(entry["query_id"], {})
            # A validated semantic wait already records why this exact query
            # cannot advance now. Static alternative availability must not
            # recreate planning work for the same stopped purpose. Recheck the
            # append-only API/source receipts here; never trust a reason string.
            if reason in {"BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED", "SOURCE_FAULT_UNVERIFIED", "BOUNDED_PUBLIC_DISCOVERY_SCOPE_LIMITED"} \
                    and _current_semantic_wait(task, plan, evidence or {}, candidates, ledger,
                        supplement, task_dir, entry, row, fault=(reason == "SOURCE_FAULT_UNVERIFIED")):
                if reason == 'BOUNDED_PUBLIC_DISCOVERY_SCOPE_LIMITED':
                    reviewed_public_limits.add((*_scope(entry), entry.get('provider'), entry.get('query_id')))
                continue
            # A receipt audit preserves uncertainty and forbids another
            # request. Its exact proof was validated by the API projection;
            # do not turn this terminal source constraint back into a ready
            # fallback which append_followup deliberately cannot authorize.
            if reason == "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW":
                from api_first_planning import reviewed_unknown_submission
                if reviewed_unknown_submission(task, plan, evidence or {}, candidates, ledger,
                        row, supplement, task_dir=task_dir):
                    continue
            reqs = [requirements[r] for r in row.get("requirement_ids", []) if r in requirements]
            alternatives = [option for req in reqs for option in _route_options(task, req, row.get("search_dimension", "text"))
                if option.get("provider") != entry.get("provider")]
            from workflow_v24 import necessary_scenario_row_bindings
            # An already-planned alternative is represented by its own receipt
            # and work entry (including a provider cooldown). Never keep asking
            # for a duplicate plan merely because its static adapter is enabled.
            def unplanned(option):
                provider = option["provider"]
                for alternative in plan.get("queries", {}).get(provider, []):
                    if (alternative.get("search_dimension") == row.get("search_dimension")
                            and set(alternative.get("requirement_ids", [])) & set(row.get("requirement_ids", []))
                            and (alternative.get("triage_jurisdiction") or alternative.get("jurisdiction")) == entry.get("jurisdiction")
                            and alternative.get("right_type") == entry.get("right_type")
                            and any(binding["scenario_id"] == entry.get("scenario_id")
                                for binding in necessary_scenario_row_bindings(task, alternative))):
                        return False
                return not any(other.get("provider") == provider and other.get("state") == "awaiting_access"
                    and str(other.get("reason", "")).startswith("BROWSER_RATE_LIMIT") for other in original_entries)
            alternatives = [option for option in alternatives if unplanned(option)]
            if alternatives and _route_state(alternatives, capabilities)[0] == "ready":
                entry.update(state="ready", reason="AUTHORIZED_ALTERNATIVE_REQUIRES_PLANNING", kind="plan_repair")
    scope_keys = {_scope(entry) for entry in view.get("unresolved_scopes", [])}
    for gap in plan.get("planning_gaps", []):
        if gap.get("code") != "UNSUPPORTED_QUERY_SEMANTICS":
            continue
        for sid, country, right in scope_keys:
            if (country, right) != (gap.get("jurisdiction"), gap.get("right_type")):
                continue
            entry = {"scenario_id": sid, "jurisdiction": country, "right_type": right,
                "kind": "plan_repair", "state": "ready", "reason": gap["code"],
                "term_id": gap.get("term_id"), "provider": gap.get("provider"),
                "query": gap.get("query"), "derived_from": gap.get("derived_from"),
                "detail": gap.get("reason")}
            entry["work_id"] = "WORK-" + sha256_json(entry)[:24]
            view["entries"].append(entry)
    if reviewed_public_limits:
        view['entries'] = [entry for entry in view['entries'] if not (
            entry.get('kind') == 'source_lookup' and entry.get('state') == 'awaiting_review'
            and entry.get('reason') == 'API_RETURNED_SCOPE_TRUNCATED'
            and (*_scope(entry), entry.get('provider'), entry.get('query_id')) in reviewed_public_limits)]
    from completion_policy import evidence_delivery_enabled
    if evidence_delivery_enabled(task) and all(value is not None for value in (evidence, candidates, ledger)):
        view = _resolve_evidence_limits(task, view, plan, capabilities, evidence, candidates, ledger,
            supplement=supplement, task_dir=task_dir, coverage=coverage)
        gaps = plan.get("candidate_action_gaps", [])
        from trusted_api import enabled as trusted_enabled
        if trusted_enabled(task):
            keys = ("candidate_id", "scenario_id", "jurisdiction", "right_type")
            for gap in gaps:
                if gap.get("code") != "API_RECORD_FACT_GAP":
                    continue
                scope = {key: gap.get(key) for key in keys}
                limited = api_record_gap_entry(task, evidence, candidates, ledger, plan, capabilities, scope,
                    supplement=supplement, task_dir=task_dir)
                if limited:
                    finished_queries = _reviewed_api_gap_queries(task,evidence,plan,gap,scope,task_dir)
                    failures = _failed_api_gap_limits(task,evidence,plan,gap,scope,task_dir)
                    for pending in view['entries']:
                        if (pending.get('kind') == 'source_lookup' and pending.get('query_id') in failures
                                and all(pending.get(k) == scope.get(k) for k in keys)
                                and pending.get('reason') == 'SOURCE_RETRY_NOT_REQUESTED'):
                            pending.update(state='blocked', coverage_status='unknown', official_verification='not_verified',
                                resume_condition=limited['resume_condition'],
                                delivery_limit={'kind':'source_failure_no_retry', 'audit':failures[pending['query_id']],
                                    'field_gap':limited['delivery_limit']})
                    view["entries"] = [row for row in view["entries"] if not (
                        row.get("reason") in {"API_RECORD_FACT_GAP", "API_RECORD_FACT_GAP_REVIEW_REQUIRED"}
                        and all(row.get(key) == scope.get(key) for key in keys)) and not _duplicate_reviewed_api_gap_work(row,scope,finished_queries)]
                    view["entries"].append(limited)
                else:
                    for row in view["entries"]:
                        if row.get("reason") == "API_RECORD_FACT_GAP" and all(row.get(key) == scope.get(key) for key in keys):
                            row.update(kind="agent_investigation", state="awaiting_review",
                                reason="API_RECORD_FACT_GAP_REVIEW_REQUIRED",
                                completion_condition="在原M06/M07记录缺字段unknown事实、实际材料阅读与批次去向、对应limited补查判断及恢复条件。")
        fact_scopes = []
        for gap in gaps:
            code = gap.get("code")
            fact_kind = ("status" if code in {"US_PATENT_STATUS_ROUTE_UNIMPLEMENTED", "US_DESIGN_STATUS_ROUTE_UNIMPLEMENTED"}
                         else "rights_holder" if code in {"US_PATENT_OWNER_ROUTE_UNIMPLEMENTED", "US_DESIGN_OWNER_ROUTE_UNIMPLEMENTED"}
                         else None)
            if fact_kind:
                scope = {key: gap.get(key) for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type")}
                fact_scopes.append((scope, fact_kind))
                if code == "US_DESIGN_STATUS_ROUTE_UNIMPLEMENTED":
                    fact_scopes.append((scope, "territory"))
        for scope, fact_kind in fact_scopes:
            status_gap = status_route_gap_entry(task, evidence, candidates, ledger, plan, capabilities, scope,
                                                supplement=supplement, fact_kind=fact_kind)
            if status_gap and not any(row.get("work_id") == status_gap["work_id"] for row in view["entries"]):
                view["entries"].append(status_gap)
        if not _skip_selected_disposition:
            _project_selected_expansion_limits(task, view, deepcopy(view["entries"]), plan, capabilities,
                evidence, candidates, ledger, supplement=supplement, task_dir=task_dir)
    view["counts"] = {state: sum(item["state"] == state for item in view["entries"])
        for state in ("ready", "awaiting_review", "awaiting_access", "awaiting_user", "submission_unknown", "blocked")}
    view["status"] = "incomplete" if view["entries"] or view.get("unresolved_scopes") else "complete"
    return view


def _current_semantic_wait(task, plan, evidence, candidates, ledger, supplement,
                           task_dir, entry, row, *, fault):
    """Revalidate an exact discovery wait before suppressing alternative replanning."""
    if (task_dir is None or not isinstance(row, dict) or not row
            or row.get("query_id") != entry.get("query_id")
            or entry.get("plan_entry_sha256") != sha256_json(row)
            or candidates is None or ledger is None):
        return False
    try:
        from discovery_semantics import (current, _current_source_fault_wait,
            _current_bounded_capability_wait, _current_public_ranked_scope_wait)
        after = current(task, plan, evidence, stage="after", scenario_id=entry.get("scenario_id"),
            jurisdiction=entry.get("jurisdiction"), right_type=entry.get("right_type"),
            direction_id=entry.get("direction_id"), provider=entry.get("provider"), row=row, task_dir=task_dir)
        if not after or after.get("problem_covered") is not False:
            return False
        runs = [run for run in evidence.get("source_runs", []) if run.get("run_id") == entry.get("source_run_id")
            and run.get("query_id") == row.get("query_id") and run.get("provider") == entry.get("provider")
            and run.get("plan_entry_sha256") == sha256_json(row)]
        if len(runs) != 1:
            return False
        checker = (_current_public_ranked_scope_wait if entry.get('reason') == 'BOUNDED_PUBLIC_DISCOVERY_SCOPE_LIMITED'
            else _current_source_fault_wait if fault else _current_bounded_capability_wait)
        return bool(checker(task, plan, evidence, candidates, ledger, supplement, task_dir,
            entry.get("provider"), row, after, runs[0]))
    except (ValueError, OSError, KeyError, TypeError):
        return False


def _planned_language_queries(task, entry, plan, evidence, candidates, ledger, *, supplement=None, task_dir=None):
    """Language belongs to executable text/description rows, not coverage credit."""
    from workflow_v24 import LANGUAGES, necessary_scenario_row_bindings, validated_query_cancellation
    from api_first_planning import dispatch_block
    required = LANGUAGES.get(entry.get("jurisdiction"), "")
    requirement_id = str(entry.get("planning_gap") or entry.get("reason") or "").split(":", 1)[0]
    result = []
    for provider, rows in plan.get("queries", {}).items():
        for row in rows:
            if (validated_query_cancellation(task, plan, row) or row.get("search_dimension") not in {"text", "description", "phonetic"}
                    or not required or str(row.get("search_language") or "").casefold() != required
                    or (row.get("jurisdiction"), row.get("right_type")) != (entry.get("jurisdiction"), entry.get("right_type"))
                    or requirement_id not in row.get("requirement_ids", [])
                    or not any(scope["scenario_id"] == entry.get("scenario_id") for scope in necessary_scenario_row_bindings(task, row))):
                continue
            if dispatch_block(task, plan, evidence, candidates, ledger, provider, row,
                              supplement, task_dir=task_dir) not in {
                    None, "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY", "API_DISCOVERY_BUDGET_EXHAUSTED",
                    "API_DISCOVERY_MERGE_REQUIRED", "API_DISCOVERY_TRIAGE_REQUIRED", "API_DISCOVERY_CARD_IDENTITY_REVIEW_REQUIRED"}:
                continue
            if provider.endswith("browser"):
                from record_browser_execution import planned_browser_query
                try:
                    planned_browser_query(provider, row, task)
                except (ValueError, TypeError, KeyError):
                    continue
            result.append({"provider": provider, "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                "search_language": required, "search_dimension": row["search_dimension"]})
    return result


def review_work(task, evidence, candidates, plan, ledger, scopes, first=None, second=None,
                *, supplement=None, evidence_root=None):
    from assessment_estimate import (review_digest, _validate_review, missing_scope_reviews,
        evidence_index, candidate_index, validate_supplement, product_image_index, missing_product_scopes, complete_product_review_required)
    digest = review_digest(evidence, candidates, ledger, plan, task, supplement)
    registry = {**evidence_index(evidence), **validate_supplement(supplement, evidence_root, task=task, evidence=evidence)}
    images = product_image_index(task, evidence_root)
    if set(registry) & set(images):
        raise ValueError("PRODUCT_IMAGE_EVIDENCE_ID_COLLISION")
    registry.update(images)
    index, errors = candidate_index(candidates)
    if errors:
        raise ValueError("; ".join(errors))
    for review in (first, second):
        if review is not None:
            # Progress must retain valid partial work and expose its missing
            # scopes. Registration and final aggregation keep the strict default.
            _validate_review(review, digest, set(registry), index, set(task.get("target_jurisdictions", [])),
                             task, registry, check_product_scopes=False)
    if first and second and (first["reviewer"] == second["reviewer"]
            or first["review_context"]["session_id"] == second["review_context"]["session_id"]):
        raise ValueError("SECOND_REVIEW_NOT_INDEPENDENT")
    missing = missing_scope_reviews(task, scopes, first, second, registry, index)
    by_scope = {(row['scenario_id'], row['jurisdiction'], row['right_type']): row for row in missing}
    for role, review in (('first', first), ('second', second)):
        execution = (review or {}).get('review_context', {}).get('execution', {})
        if not (complete_product_review_required(task) or isinstance(execution.get('host_audit'), dict)
                or isinstance(execution.get('module_execution'), dict)):
            continue  # Only the digest-bound legacy stage contract keeps narrow scopes.
        for scope in missing_product_scopes((review or {}).get('assessments', []), task):
            key = (scope['scenario_id'], scope['jurisdiction'], scope['right_type'])
            if key not in by_scope:
                row = {**scope, 'candidate_id': '', 'assessment_status': 'pending',
                    'pending_reasoning': '产品整体范围缺少独立审阅；候选、自有品牌和信号不能替代。', 'missing_reviewers': []}
                missing.append(row); by_scope[key] = row
            reviewer = (review or {}).get('reviewer') or role
            if reviewer not in by_scope[key]['missing_reviewers']:
                by_scope[key]['missing_reviewers'].append(reviewer)
    entries = []
    for item in missing:
        for reviewer in item["missing_reviewers"]:
            role = "first" if reviewer == (first or {}).get("reviewer", "first") else "second"
            row = {key: item[key] for key in ("scenario_id", "jurisdiction", "right_type")}
            row.update(kind="scope_review", state="awaiting_review", action_id="review:" + role,
                reviewer=reviewer, reason="NECESSARY_SCOPE_REVIEW_REQUIRED")
            row["work_id"] = "WORK-" + sha256_json(row)[:24]
            entries.append(row)
    return {"status": "incomplete" if entries else "complete", "entries": entries, "evidence_digest": digest}


def _delivery_limit_valid(entry, task, evidence, plan, capabilities, *, candidates=None, ledger=None,
                          supplement=None, task_dir=None):
    """Validate source constraints emitted by the shared planner, not stop prose."""
    proof = entry.get("delivery_limit")
    if isinstance(proof, dict) and proof.get('kind') == 'bounded_public_ranked_scope':
        rows = [row for row in plan.get('queries', {}).get(entry.get('provider'), [])
            if row.get('query_id') == entry.get('query_id')]
        if (len(rows) != 1 or task_dir is None or candidates is None or ledger is None
                or entry.get('plan_entry_sha256') != sha256_json(rows[0])):
            return False
        from discovery_semantics import current, _current_public_ranked_scope_wait, public_ranked_scope_entry
        try:
            after = current(task, plan, evidence, stage='after', scenario_id=entry.get('scenario_id'),
                jurisdiction=entry.get('jurisdiction'), right_type=entry.get('right_type'),
                direction_id=entry.get('direction_id'), provider=entry.get('provider'), row=rows[0], task_dir=task_dir)
            runs = [item for item in evidence.get('source_runs', []) if item.get('run_id') == entry.get('source_run_id')]
            if not after or len(runs) != 1:
                return False
            bound = _current_public_ranked_scope_wait(task, plan, evidence, candidates, ledger,
                supplement, task_dir, entry.get('provider'), rows[0], after, runs[0])
            if not bound:
                return False
            expected = public_ranked_scope_entry({}, rows[0], after, runs[0], bound)
        except (ValueError, OSError, KeyError, TypeError):
            return False
        return all(entry.get(key) == expected.get(key) for key in
            ('kind', 'state', 'reason', 'coverage_status', 'delivery_limit', 'resume_condition',
             'uncovered_clues', 'unretrieved_result_row_count', 'reasoning'))
    if isinstance(proof,dict) and proof.get('kind') == 'public_identity_bounded':
        from public_identity import current, limitation
        event = current(task,evidence,candidates or {},ledger or {},entry,supplement,task_dir)
        expected = limitation(event,entry) if event else None
        return bool(expected and entry.get('state') == 'blocked'
            and entry.get('reason') == 'PUBLIC_IDENTITY_BOUNDED_UNKNOWN'
            and proof == expected['delivery_limit'] and entry.get('coverage_status') == 'unknown'
            and entry.get('resume_condition') == expected['resume_condition'])
    if isinstance(proof,dict) and proof.get('kind') == 'cancelled_discovery_failure':
        source = {**entry,'kind':'source_lookup','reason':'SCENARIO_ACTION_CANCELLED'}
        expected = _cancelled_discovery_limit_entry(task,source,plan,evidence,candidates or {},ledger or {},
            supplement,task_dir=task_dir)
        return bool(expected and all(entry.get(k) == expected.get(k) for k in
            ('kind','state','reason','coverage_status','official_verification','delivery_limit',
             'limitation_kind','reasoning','resume_condition')))
    if isinstance(proof, dict) and proof.get('kind') == 'source_failure_no_retry':
        expected = api_record_gap_entry(task,evidence,candidates or {},ledger or {},plan,capabilities,
            entry,supplement=supplement,task_dir=task_dir)
        row = next((r for r in plan.get('queries',{}).get(entry.get('provider'), [])
            if r.get('query_id') == entry.get('query_id')), None)
        from recovery_stage_b import task_limit_no_retry_proof
        audit = task_limit_no_retry_proof(task,evidence,entry.get('provider'),row,task_dir) if row else None
        return bool(expected and audit and proof == {'kind':'source_failure_no_retry',
            'audit':audit,'field_gap':expected['delivery_limit']}
            and entry.get('kind') == 'source_lookup' and entry.get('state') == 'blocked'
            and entry.get('reason') == 'SOURCE_RETRY_NOT_REQUESTED'
            and entry.get('coverage_status') == 'unknown' and entry.get('official_verification') == 'not_verified'
            and entry.get('resume_condition') == expected['resume_condition'])
    if isinstance(proof, dict) and proof.get("kind") == "api_record_fact_gap":
        expected = api_record_gap_entry(task, evidence, candidates or {}, ledger or {}, plan, capabilities,
            entry, supplement=supplement, task_dir=task_dir)
        return bool(expected and entry.get("state") == "blocked" and entry.get("reason") == "API_RECORD_FACT_GAP"
            and entry.get("coverage_status") == "unknown" and entry.get("official_verification") == "not_verified"
            and not entry.get("query_id") and proof == expected["delivery_limit"]
            and entry.get("resume_condition") == expected["resume_condition"])
    if isinstance(proof, dict) and proof.get("kind") == "candidate_followup_professional_wait":
        from candidate_followup import professional_wait_proof
        from decision_workflow import triage_summary
        try:
            records = triage_summary(task, candidates or {}, ledger or {}, evidence=evidence,
                                    supplement=supplement).get("records", [])
            record = next((row for row in records if all(row.get(key) == entry.get(key)
                for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type"))), None)
            action = next((row for row in (record or {}).get("next_actions", [])
                           if row.get("action_id") == entry.get("action_id")), None)
            expected = professional_wait_proof(task, evidence, record, action, supplement=supplement) if action else None
        except (ValueError, KeyError, TypeError):
            return False
        return bool(expected and expected == proof and entry.get("kind") == "agent_investigation"
            and entry.get("action_kind") == "professional_review" and entry.get("state") == "awaiting_access"
            and entry.get("reason") == "FOLLOWUP_WAITING"
            and entry.get("dependency") == proof["dependency"]
            and entry.get("resume_condition") == proof["resume_condition"])
    if isinstance(proof, dict) and proof.get("kind") == "professional_wait":
        return _professional_wait_valid(entry, task, evidence, candidates, ledger, supplement=supplement)
    if isinstance(proof, dict) and proof.get("kind") == "specialty_discovery_delegation":
        from specialty_analysis import discovery_delegation_entry
        expected = discovery_delegation_entry(task, evidence, candidates or {}, ledger or {}, plan,
            entry, entry.get("handoff_gap"), supplement=supplement)
        return bool(expected and entry.get("state") == "blocked"
                    and entry.get("reason") == expected["reason"]
                    and entry.get("limitation_kind") == "residual_discovery_pending"
                    and entry.get("official_verification") == "not_verified"
                    and not entry.get("query_id") and not entry.get("source_run_refs")
                    and proof == expected["delivery_limit"])
    if isinstance(proof, dict) and proof.get("kind") == "selected_verification_disposition":
        if task_dir is None:
            return False
        from pathlib import Path
        from decision_workflow import triage_summary
        from workflow_v24 import resolved_work_view
        from specialty_analysis import work_entries as specialty_work_entries
        triage = triage_summary(task, candidates or {}, ledger or {}, evidence=evidence, supplement=supplement)
        selected = next((row for row in triage.get("records", []) if row.get("current")
            and row.get("decision") == "selected" and all(row.get(key) == proof.get(key)
                for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type"))), None)
        if not selected:
            return False
        browser_path = Path(task_dir) / "browser-execution-status.json"
        base = resolved_work_view(task, evidence, candidates or {}, plan, ledger or {},
            supplement=supplement, evidence_root=task_dir, task_dir=task_dir,
            browser_status=load_json(browser_path) if browser_path.is_file() else None,
            source_capabilities=capabilities, _skip_selected_disposition=True)
        specialty = base.get("specialty_analysis", {})
        expected = _selected_verification_disposition(entry, selected, specialty, specialty_work_entries(specialty))
        return bool(expected and expected == proof and entry.get("state") == "blocked"
            and entry.get("reason") == "SELECTED_VERIFICATION_CURRENT_DISPOSITION_UNVERIFIED"
            and entry.get("official_verification") == "not_verified" and entry.get("coverage_status") == "unknown"
            and entry.get("limitation_kind") == "candidate_verification_pending")
    if isinstance(proof, dict) and proof.get("kind") == "selected_expansion_delegated":
        from specialty_analysis import project as specialty_project, work_entries as specialty_work_entries
        from decision_workflow import triage_summary
        triage = triage_summary(task, candidates or {}, ledger or {}, evidence=evidence, supplement=supplement)
        selected = next((row for row in triage.get("records", []) if row.get("current")
            and row.get("decision") == "selected" and all(row.get(key) == proof.get(key)
                for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type"))), None)
        if not selected:
            return False
        projected = specialty_project(task, evidence, candidates or {}, ledger or {}, supplement=supplement,
            source_work=[], plan=plan, capabilities=capabilities, task_dir=task_dir)
        delegated = next((row for row in specialty_work_entries(projected)
            if all(row.get(key) == proof.get(key) for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type"))
            and row.get("delivery_limit", {}).get("kind") == "specialty_discovery_delegation"), None)
        return bool(entry.get("state") == "blocked" and entry.get("reason") == "SELECTED_EXPANSION_WITH_CURRENT_DELEGATION"
            and entry.get("limitation_kind") == "residual_discovery_pending" and delegated
            and _delivery_limit_valid(delegated, task, evidence, plan, capabilities, candidates=candidates,
                ledger=ledger, supplement=supplement, task_dir=task_dir)
            and delegated.get("delivery_limit") == proof.get("delegation"))
    if isinstance(proof, dict) and proof.get("kind") == "selected_expansion_bounded":
        from decision_workflow import triage_summary
        triage = triage_summary(task, candidates or {}, ledger or {}, evidence=evidence, supplement=supplement)
        selected = next((row for row in triage.get("records", []) if row.get("current")
            and row.get("decision") == "selected" and all(row.get(key) == proof.get(key)
                for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type"))), None)
        if not selected:
            return False
        current = _selected_design_expansion_proof(task, entry, selected, plan, evidence,
            candidates or {}, ledger or {}, supplement=supplement, task_dir=task_dir,
            current_entries=None)
        if current is None:
            return False
        return bool(entry.get("state") == "blocked" and entry.get("reason") == "BOUNDED_SELECTED_DESIGN_EXPANSION_UNVERIFIED"
            and entry.get("coverage_status") == "unknown" and entry.get("official_verification") == "not_verified"
            and current == proof)
    if isinstance(proof, dict) and proof.get("kind") in {
            "status_plan_gap", "ownership_plan_gap", "territory_current_effect_plan_gap"}:
        expected = status_route_gap_entry(task, evidence, candidates or {}, ledger or {}, plan, capabilities,
                                          entry, supplement=supplement, fact_kind=proof.get("fact_kind"))
        return bool(expected and entry.get("reason") == expected["reason"]
                    and entry.get("fact_kind") == expected["fact_kind"] and entry.get("state") == "blocked"
                    and entry.get("limitation_kind") == expected["limitation_kind"]
                    and entry.get("official_verification") == "not_verified"
                    and not entry.get("query_id") and not entry.get("source_run_refs")
                    and proof == expected["delivery_limit"])
    if (not isinstance(proof, dict) or proof.get("kind") != "source_constraint"
            or proof.get("reason") != entry.get("reason")
            or proof.get("official_verification") != "not_verified"):
        return False
    reason = str(entry.get("reason") or "")
    if (reason == "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP"
            or any(marker in reason for marker in ("INVALID", "MISMATCH", "STALE", "TAMPER", "SYNTAX",
                "UNSUPPORTED_QUERY", "CLOUD_AUTH", "AUTH_GATE", "GUARD", "TERMS_MISSING"))):
        return False
    run_refs, cap_refs = proof.get("source_run_refs", []), proof.get("capability_refs", [])
    if not isinstance(run_refs, list) or not isinstance(cap_refs, list):
        return False
    route_absence = _route_absence_proof(task, entry, plan, capabilities, evidence, candidates or {}, ledger or {}, supplement=supplement)
    if not (run_refs or cap_refs) and (not route_absence or proof.get("route_absence") != route_absence):
        return False
    runs = {run["run_id"]: run for run in evidence.get("source_runs", [])}
    unknown = None
    if reason == "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW":
        from api_first_planning import reviewed_unknown_submission
        rows = [row for values in plan.get("queries", {}).values() for row in values if row.get("query_id") == entry.get("query_id")]
        if task_dir is None or candidates is None or ledger is None or len(rows) != 1:
            return False
        unknown = reviewed_unknown_submission(task, plan, evidence, candidates, ledger, rows[0], supplement, task_dir=task_dir)
        if not unknown or proof.get("submission_review_refs") != unknown:
            return False
        if run_refs != [{"run_id": item["run_id"], "sha256": item["source_run_sha256"]} for item in unknown]:
            return False
    from api_first_planning import account_stop_reason, _account
    stopped_providers = ({entry.get("provider")} | {ref.get("provider") for ref in cap_refs if isinstance(ref, dict)}
        | {ref.get("provider") for ref in entry.get("source_constraints", []) if isinstance(ref, dict)})
    stopped_accounts = {_account(provider) for provider in stopped_providers if provider
        and reason == "API_DISCOVERY_ACCOUNT_STOPPED" and account_stop_reason(provider, evidence)}
    from recovery_stage_b import effective_submission
    for ref in run_refs:
        run = runs.get(ref.get("run_id"), {}) if isinstance(ref, dict) else {}
        if (not run or ref.get("sha256") != sha256_json(run)
                or ((run.get("jurisdiction"), run.get("right_type")) != (entry.get("jurisdiction"), entry.get("right_type"))
                    and _account(run.get("provider", "")) not in stopped_accounts)
                or ((effective_submission(evidence, run) if task.get('retrieval_workflow_revision') == 'api-first-v3'
                     else run.get("submission_state")) not in {"submitted", "not_submitted"} and not unknown)):
            return False
    fields = ("provider", "state", "reason", "executable", "credentials_present", "checked_at", "cost_ceiling_usd")
    for ref in cap_refs:
        cap = capabilities.get(ref.get("provider"), {}) if isinstance(ref, dict) else {}
        if not cap or ref.get("sha256") != sha256_json({key: cap[key] for key in fields if key in cap}):
            return False
    gap_digest = proof.get("planning_gap_sha256")
    if gap_digest:
        from api_first_planning import gap_limit_still_current
        gaps = [gap for gap in plan.get("planning_gaps", []) if sha256_json(gap) == gap_digest
            and (gap.get("jurisdiction"), gap.get("right_type")) == (entry.get("jurisdiction"), entry.get("right_type"))]
        if len(gaps) != 1 or not gap_limit_still_current(task, plan, evidence, candidates or {}, ledger or {},
                gaps[0], capabilities, supplement):
            return False
    return bool(gap_digest or run_refs)


def _professional_wait_valid(entry, task, evidence, candidates, ledger, *, supplement=None):
    """Recompute the exact selected-design expert packet and waiting receipt."""
    proof = entry.get("delivery_limit")
    if (not isinstance(proof, dict) or proof.get("kind") != "professional_wait"
            or entry.get("kind") != "professional_review"
            or entry.get("state") != "awaiting_access"
            or entry.get("reason") != "SPECIALTY_PROFESSIONAL_SCOPE_WAIT"
            or proof.get("official_verification") != "not_verified"
            or not entry.get("candidate_id") or not entry.get("unit_id")):
        return False
    try:
        from specialty_analysis import professional_wait_entry
        expected = professional_wait_entry(task, evidence, candidates or {}, ledger or {},
            {key: entry.get(key) for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type")},
            entry.get("unit_id"), supplement=supplement, gap_event_id=proof.get("gap_event_id"))
    except (ValueError, OSError, KeyError, TypeError):
        return False
    return bool(expected and expected.get("delivery_limit") == proof
        and expected.get("state") == entry.get("state")
        and expected.get("reason") == entry.get("reason")
        and expected.get("unit_id") == entry.get("unit_id"))


def _route_absence_proof(task, entry, plan, capabilities, evidence, candidates, ledger, *, supplement=None):
    """Prove an empty qualified route set from the frozen plan and real snapshot."""
    from api_first_planning import (_planning_gap_term, _gap_providers, gap_limit_still_current,
        intent_id, dimension)
    proof = entry.get("delivery_limit", {})
    if (entry.get("reason") != "API_DISCOVERY_ROUTE_UNAVAILABLE" or not capabilities
            or not isinstance(proof, dict) or proof.get("source_run_refs") or proof.get("capability_refs")):
        return None
    gaps = [gap for gap in plan.get("planning_gaps", []) if sha256_json(gap) == proof.get("planning_gap_sha256")]
    if len(gaps) != 1:
        return None
    gap = gaps[0]
    country, right = entry.get("jurisdiction"), entry.get("right_type")
    term = _planning_gap_term(task, plan, gap)
    requirements = [row for row in task.get("coverage_requirements", []) if
        (row.get("jurisdiction"), row.get("right_type")) == (country, right) and row.get("phase") in {"official_recall", "provenance"}]
    if (not term or not requirements or (gap.get("jurisdiction"), gap.get("right_type")) != (country, right)
            or gap.get("code") != entry["reason"]
            or set(gap.get("requirement_ids", [])) != {row["requirement_id"] for row in requirements}
            or gap.get("discovery_intent_id") != intent_id(country, right, dimension(term), term)
            or _gap_providers(task, gap, term, capabilities)
            or not gap_limit_still_current(task, plan, evidence, candidates, ledger, gap, capabilities, supplement)):
        return None
    policy = {key: task.get(key) for key in ("retrieval_policy", "serper_free_enhancement", "serpapi_free_enhancement", "signa_free_enhancement")}
    if any(plan.get(key) != value for key, value in policy.items()):
        return None
    return {"kind": "no_qualified_route", "planning_gap_sha256": sha256_json(gap), "term_sha256": sha256_json(term),
        "requirements_sha256": sha256_json(requirements), "policy_sha256": sha256_json(policy),
        "source_capabilities_sha256": sha256_json(capabilities), "qualified_providers": [], "official_verification": "not_verified"}


def _reviewed_fact_limitations(assessment, evidence, *, evidence_root=None, task=None):
    """Completed investigation may leave a reviewed fact unknown, without a retry."""
    from assessment_estimate import evidence_index, validate_supplement, _substantive_refs, product_image_index
    supplement_index = validate_supplement(assessment.get("supplement"),
        evidence_root, task=task, evidence=evidence)
    registry = {**evidence_index(evidence), **supplement_index}
    images = product_image_index(task or {}, evidence_root)
    if set(registry) & set(images):
        raise ValueError("PRODUCT_IMAGE_EVIDENCE_ID_COLLISION")
    registry.update(images)
    runs = {run["run_id"]: run for run in evidence.get("source_runs", [])}
    result = []
    for row in assessment.get("assessments", []):
        if row.get("assessment_status") != "pending" or not row.get("pending_reasoning"):
            continue
        refs = _substantive_refs(row.get("evidence_refs", []), registry, runs, row=row)
        scope_gap = False
        if not refs:
            # A reviewed pending candidate may cite an exact, validated local
            # original whose legacy entry omitted right_type. It establishes
            # the documented limitation, not a completed rights comparison.
            refs = {ref for ref in row.get("evidence_refs", []) if ref in supplement_index
                and supplement_index[ref].get("candidate_id") == row.get("candidate_id")
                and row.get("candidate_id") and supplement_index[ref].get("jurisdiction") == row.get("jurisdiction")
                and supplement_index[ref].get("kind") in {"patent_document", "design_drawings", "rights_record"}
                and (supplement_index[ref].get("right_type") in (None, row.get("right_type")))}
        if not refs:
            # The substantive filter proves rights/comparisons, not missing evidence.
            # A jointly reviewed, non-candidate unknown may be disclosed in a
            # partial report without pretending its contextual inputs prove a right.
            from assessment_estimate import partial_evidence_enabled, known_findings_enabled
            cited = row.get("evidence_refs", [])
            scope_gap = bool(task and (partial_evidence_enabled(task) or known_findings_enabled(task))
                and not row.get("candidate_id")
                and row.get("risk") is None and row.get("right_state") == "unknown"
                and row.get("review_resolution", {}).get("method") in {"independent_agreement", "chief_adjudication"}
                and isinstance(cited, list) and cited and all(ref in registry for ref in cited)
                and row.get("scenario_id") and row.get("jurisdiction") and row.get("right_type"))
            if not scope_gap:
                continue
            refs = set(cited)
        identity = {key: row.get(key) for key in ("scenario_id", "jurisdiction", "right_type", "candidate_id")}
        result.append({**identity, "work_id": "LIMIT-" + sha256_json(identity)[:24],
            "kind": "reviewed_scope_gap" if scope_gap else "reviewed_fact_limit",
            "reason": "REVIEWED_SCOPE_EVIDENCE_INSUFFICIENT" if scope_gap else "REVIEWED_FACT_REMAINS_UNCONFIRMED",
            "coverage_status": "unknown", "state": "blocked",
            "official_verification": "not_verified", "reasoning": row["pending_reasoning"],
            "evidence_refs": sorted(refs),
            "context_evidence_sha256": {ref: sha256_json(registry[ref]) for ref in sorted(refs)} if scope_gap else {},
            "source_run_refs": [{"run_id": rid, "sha256": sha256_json(runs[rid])}
                for rid in sorted({registry[ref].get("source_run_id") for ref in refs} - {None}) if rid in runs]})
    return result


_FAILURE_LIMIT_KINDS = {
    "TECHNICAL_EXECUTION_STOPPED": "internal_technical_failure",
    "SOURCE_AUTOMATIC_RETRY_EXHAUSTED": "source_retry_exhausted",
    "SOURCE_RETRY_DEPENDENCY_REQUIRED": "source_access_dependency",
    "SUBMISSION_UNKNOWN_EVIDENCED_LIMIT": "submission_unknown_reviewed",
    "SUBMISSION_UNKNOWN_DEPENDENCY": "submission_unknown_reviewed",
}


def _failure_limit(entry, evidence):
    """failure-limits-v1: a failed/stopped action with a recorded stop or original run is a disclosed limit.

    Read-only, never dispatch permission. It only accepts what is already bound to
    exact records: the 08D technical_stop event (with its recovery condition), or
    every original source run of the 08B state by run id and hash. Unread material,
    unknown submissions without a reviewed disposition and anything else stay blockers.
    """
    kind = _FAILURE_LIMIT_KINDS.get(entry.get("reason"))
    if (not kind or entry.get("state") not in {"blocked", "awaiting_access"}
            or entry.get("integrity_failure") or not isinstance(entry.get("work_id"), str)):
        return None
    facts = []
    if entry["reason"] == "TECHNICAL_EXECUTION_STOPPED":
        stop = next((row for row in evidence.get("progress_events", []) if isinstance(row, dict)
                     and row.get("kind") == "technical_stop" and row.get("event_id") == entry.get("technical_stop_id")), None)
        if (not stop or not str(stop.get("recovery_condition") or "").strip()
                or not str(entry.get("recovery_condition") or "").strip()):
            return None
        facts.append({"kind": "technical_stop", "event_id": stop["event_id"], "sha256": sha256_json(stop)})
    else:
        refs = (entry.get("recovery") or {}).get("source_run_refs") or []
        runs = {run.get("run_id"): run for run in evidence.get("source_runs", []) if isinstance(run, dict)}
        if not refs:
            return None
        for ref in refs:
            run = runs.get(ref.get("run_id")) if isinstance(ref, dict) else None
            if run is None or sha256_json(run) != ref.get("sha256"):
                return None
            facts.append({"kind": "source_run", "run_id": ref["run_id"], "sha256": ref["sha256"]})
    return {**deepcopy(entry), "limitation_kind": kind, "official_verification": "not_verified",
        "failure_records": facts,
        "reasoning": "本项已有绑定原运行或停止记录的执行故障／依赖限制；原待办、恢复条件与提交状态保持不变，"
                     "仅允许交付带限制的不完整报告，不代表权利、来源或事实已核查。"}


def _partial_technical_limit(entry, evidence, plan, snapshots, *, task_dir=None, task=None):
    """Read-only report exception for a recorded query failure, never dispatch permission.

    Bare unexecuted plans, credential checks, unreviewed material and corrupt
    inputs cannot establish a technical limitation. Original work state and
    source submission facts are retained verbatim.
    """
    codes = {"INTERNAL_ROUTE_CONTRACT_ERROR", "NODE_UNAVAILABLE",
        "UNSUPPORTED_QUERY_SEMANTICS", "USPTO_QUERY_REJECTED",
        "API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED", "BROWSER_QUERY_CONTRACT_ERROR"}
    if isinstance(task, dict) and task.get("execution_policy_revision") in {"continuous-work-v1", "continuous-work-v2"}:
        # A locally repairable query/route defect must produce and clear a
        # repair action before evidence delivery.  Historical runs retain the
        # previous narrowly scoped technical exception.
        codes -= {"INTERNAL_ROUTE_CONTRACT_ERROR", "UNSUPPORTED_QUERY_SEMANTICS",
                  "USPTO_QUERY_REJECTED", "API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED",
                  "BROWSER_QUERY_CONTRACT_ERROR"}
    from assessment_v24 import NON_PRODUCTION
    def nonproduction(value):
        if isinstance(value, dict):
            return (any(str(value.get(key) or "").casefold() in
                        NON_PRODUCTION | {"offline", "unit_test_only"}
                        for key in ("source_environment", "environment", "kind"))
                    or any(value.get(key) for key in ("fixture", "fixture_only", "test_only", "mock"))
                    or any(nonproduction(item) for item in value.values()))
        return isinstance(value, list) and any(nonproduction(item) for item in value)
    def unread_material(value):
        if isinstance(value, dict):
            material = {"candidates", "records", "results", "documents", "artifacts", "attachments",
                "claims", "full_text", "text", "html", "body", "pages", "images", "items", "protected_views"}
            return (any(value.get(key) for key in material)
                    or any(unread_material(item) for item in value.values()))
        return isinstance(value, list) and any(unread_material(item) for item in value)
    if (entry.get("kind") not in {"source_lookup", "plan_repair"}
            or entry.get("state") not in {"ready", "blocked", "awaiting_access"}
            or entry.get("reason") not in codes or entry.get("integrity_failure")):
        return None
    provider, query_id = entry.get("provider"), entry.get("query_id")
    matches = [row for row in plan.get("queries", {}).get(provider, [])
        if query_id and row.get("query_id") == query_id]
    if len(matches) != 1:
        return None
    row = matches[0]
    digest = sha256_json(row)
    if any(entry.get(key) != row.get(key) for key in ("jurisdiction", "right_type")):
        return None
    runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
        and run.get("query_id") == query_id and run.get("plan_entry_sha256") == digest]
    from assessment_v24 import evidence_index
    linked = [item for item in evidence_index(evidence).values()
              if item.get("source_run_id") in {run.get("run_id") for run in runs}]
    # Failed returns may still carry usable material. Do not let an error-only
    # exception skip its existing merge/read/review path, even after a later failure.
    if any(nonproduction(value) for value in [*runs, *linked]):
        return None
    if any(unread_material(value) for value in [*runs, *linked]):
        return None
    facts = []
    if runs:
        latest = runs[-1]
        if (latest.get("status") in {"failed", "access_limited"}
                and latest.get("error_code") == entry["reason"]
                and latest.get("submission_state") in {"submitted", "not_submitted"}):
            facts.append({"kind": "source_run", "run_id": latest["run_id"], "sha256": sha256_json(latest)})
        else:
            return None
    current = [record for record in snapshots.get("browser-execution-status.json", {}).get("queries", [])
        if record.get("provider") == provider and record.get("query_id") == query_id
        and record.get("plan_entry_sha256") == digest]
    if current:
        latest = current[-1]
        if nonproduction(latest) or unread_material(latest):
            return None
        if (latest.get("status") in {"failed", "access_limited"}
                and latest.get("error_code") == entry["reason"]
                and latest.get("submission_state") == "not_submitted"
                and latest.get("capture_status") not in {"success", "no_result"}):
            # A scalar scheduler snapshot alone is not a retained failure receipt.
            # Read only the already captured local artifact; never create a capture.
            from pathlib import Path
            from common import load_json, path_within, sha256_file
            if not task_dir or not latest.get("capture_path") or not latest.get("capture_sha256"):
                return None
            root = Path(task_dir).resolve()
            capture_path = Path(latest["capture_path"])
            capture_path = (root / capture_path).resolve() if not capture_path.is_absolute() else capture_path.resolve()
            try:
                if (not path_within(capture_path, root) or not capture_path.is_file()
                        or sha256_file(capture_path) != latest["capture_sha256"]):
                    return None
                capture = load_json(capture_path)
            except (OSError, ValueError):
                return None
            if (not isinstance(capture, dict) or nonproduction(capture) or unread_material(capture)
                    or any(capture.get(key) != latest.get(key)
                           for key in ("status", "error_code", "submission_state"))
                    or any(key in capture and capture[key] != expected
                           for key, expected in (("query_id", query_id), ("provider", provider),
                                                 ("plan_entry_sha256", digest)))):
                return None
            facts.append({"kind": "browser_execution_record", "sha256": sha256_json(latest),
                          "capture_sha256": latest["capture_sha256"]})
        else:
            return None
    if not facts:
        return None
    return {**deepcopy(entry), "limitation_kind": "internal_technical_failure",
        "official_verification": "not_verified", "plan_entry_sha256": digest,
        "failure_records": facts,
        "reasoning": "本项已有绑定该查询的内部技术错误记录，查询未完成；仅允许交付不完整报告，"
                     "不改变原待办、恢复规则、提交状态或来源调用权限。"}


def publication_context(task, evidence, candidates, plan, ledger, assessment, *,
                        mode=None, stop_reason=None, snapshots=None, task_dir=None, evidence_root=None):
    """One immutable v3 publication evaluation; no cache survives this call."""
    options = dict(mode=mode,stop_reason=stop_reason,snapshots=snapshots,
        task_dir=task_dir,evidence_root=evidence_root)
    if task.get('retrieval_workflow_revision') != 'api-first-v3':
        return _publication_context(task,evidence,candidates,plan,ledger,assessment,**options)
    from decision_workflow import decision_snapshot
    with decision_snapshot(task,evidence,candidates,plan,ledger,assessment.get('supplement')):
        return _publication_context(task,evidence,candidates,plan,ledger,assessment,**options)


def collect_publication_issues(task, evidence, candidates, plan, ledger, assessment, *,
                               mode=None, stop_reason=None, snapshots=None, task_dir=None,
                               evidence_root=None, preparation=False, prepared_view=None):
    """Collect independent gates once; a failed/preparation result grants no authority.

    preparation is for the moment before final reviews exist. It checks live
    execution, receipt integrity and limitation proofs only; the normal publish
    path must call this with preparation=False and recheck both real reviewers.
    prepared_view is a call-local readiness projection, never a persisted cache.
    """
    issues = []
    if task_dir is not None and task.get('schema_version') == '2.4-free':
        from official_tmsearch_export import publication_issues
        export_mode = (mode if mode not in (None, 'auto') else
            ('final' if assessment.get('status') == 'completed' else 'evidence'))
        issues.extend(publication_issues(task_dir, evidence, candidates, mode=export_mode, plan=plan))
    options = dict(mode=mode, stop_reason=stop_reason, snapshots=snapshots, task_dir=task_dir,
        evidence_root=evidence_root, _issues=issues, _preparation=preparation,
        _prepared_view=prepared_view if preparation else None)
    try:
        if task.get('retrieval_workflow_revision') == 'api-first-v3':
            from decision_workflow import decision_snapshot
            with decision_snapshot(task, evidence, candidates, plan, ledger, assessment.get('supplement')):
                context = _publication_context(task, evidence, candidates, plan, ledger, assessment, **options)
        else:
            context = _publication_context(task, evidence, candidates, plan, ledger, assessment, **options)
    except (ValueError, KeyError, TypeError) as exc:
        # Structural failures make dependent checks unavailable. Preserve the
        # real error; do not invent successful proof for the unreachable gates.
        message = str(exc)
        if message not in issues:
            issues.append(message)
        context = None
    return {'ready': not issues, 'errors': issues,
        'issues': [{'code': message.split(':', 1)[0], 'message': message,
                    'owner_layer': 'necessary_completion'} for message in issues],
        'preparation_only': preparation,
        'context': context if not issues and not preparation else None}


def _publication_context(task, evidence, candidates, plan, ledger, assessment, *,
                         mode=None, stop_reason=None, snapshots=None, task_dir=None, evidence_root=None,
                         _issues=None, _preparation=False, _prepared_view=None):
    """Recompute a publication decision using only frozen, non-secret inputs."""
    def reject(message):
        if _issues is None:
            raise ValueError(message)
        if message not in _issues:
            _issues.append(message)
    if not enabled(task):
        if mode is not None or stop_reason is not None:
            reject("COMPLETION_POLICY_REQUIRED_FOR_PUBLICATION_MODE")
        return None
    from workflow_v24 import derive_work_view
    from completion_policy import evidence_delivery_enabled
    delivery = evidence_delivery_enabled(task)
    mode = mode or ("auto" if delivery else "final")
    if mode not in ({"auto", "final", "evidence", "stage"} if delivery else {"final", "stage"}):
        reject("PUBLICATION_MODE_INVALID")
        return None
    raw_snapshots = snapshots if snapshots is not None else {}
    snapshots = sanitize_snapshots(task, raw_snapshots)
    source_digests = {name: sha256_json(value) for name, value in raw_snapshots.items()}
    caps = capability_map(task, snapshots.get("source-capabilities.json"))
    if delivery:
        from runtime_v24 import resolved_capabilities
        caps = resolved_capabilities(task, evidence, plan, caps, task_dir,
            browser_status=snapshots.get("browser-execution-status.json"))
        snapshots["source-capabilities.json"] = {"schema_version": task["schema_version"],
            "task_id": task["task_id"], "sources": list(caps.values())}
        snapshots = sanitize_snapshots(task, snapshots)
    scopes = assessment["coverage"]["scopes"]
    supplement = assessment.get("supplement")
    reviews = assessment["review"]["input_reviews"]
    if _prepared_view is not None:
        view = deepcopy(_prepared_view)
    elif delivery:
        from workflow_v24 import resolved_work_view
        view = resolved_work_view(task, evidence, candidates, plan, ledger, supplement=supplement,
            evidence_root=evidence_root, task_dir=task_dir, coverage=scopes,
            browser_status=snapshots.get("browser-execution-status.json"), source_capabilities=caps)
    else:
        view = derive_work_view(task, evidence, candidates, plan, ledger, supplement=supplement,
            evidence_root=evidence_root, task_dir=task_dir, coverage=scopes,
            browser_status=snapshots.get("browser-execution-status.json"), source_capabilities=caps)
        view = refine_work_view(task, view, plan, caps)
    from workflow_v24 import plan_row_index
    plan_index = plan_row_index(plan)
    for entry in ([] if delivery else view["entries"]):
        matches = plan_index.get(entry.get("query_id"), [])
        if len(matches) == 1:
            provider, row = matches[0]
            linked = [{"run_id": run["run_id"], "sha256": sha256_json(run)}
                for run in evidence.get("source_runs", []) if run.get("query_id") == row["query_id"]
                and run.get("provider") == provider and run.get("plan_entry_sha256") == sha256_json(row)]
            entry["source_run_refs"] = list({item["run_id"]: item for item in
                [*entry.get("source_run_refs", []), *linked]}.values()) if delivery else linked
        if entry.get("provider") in caps:
            entry["capability_sha256"] = sha256_json(caps[entry["provider"]])
    if _preparation:
        review = {'entries': [], 'status': 'not_started', 'evidence_digest': ''}
    else:
        try:
            review = review_work(task, evidence, candidates, plan, ledger, scopes, reviews["first"], reviews.get("second"),
                supplement=supplement, evidence_root=evidence_root)
        except ValueError as exc:
            if _issues is None:
                raise
            reject(str(exc))
            review = {'entries': [], 'status': 'invalid', 'evidence_digest': ''}
    if review["entries"]:
        reject("PUBLICATION_SCOPE_REVIEW_REQUIRED: " + ",".join(r["work_id"] for r in review["entries"]))
    if mode == "auto":
        mode = "final" if (assessment["status"] == "completed" and view["status"] == "complete"
            and not view["entries"]) else "evidence"
    limitations = []
    if mode == "final":
        if assessment["status"] != "completed" or view["status"] != "complete" or view["entries"]:
            reject("PUBLICATION_NECESSARY_WORK_INCOMPLETE")
        if stop_reason:
            reject("FINAL_PUBLICATION_CANNOT_HAVE_STOP_REASON")
    elif mode == "evidence":
        if assessment["status"] == "completed":
            reject("COMPLETED_ASSESSMENT_REQUIRES_FINAL_PUBLICATION")
        from assessment_estimate import partial_evidence_enabled
        from execution_budget import delivery_limit as budget_limit
        technical = {entry['work_id']: limitation for entry in view['entries']
            if (limitation := budget_limit(task, evidence, plan, entry, task_dir)) is not None}
        if partial_evidence_enabled(task):
            for entry in view["entries"]:
                if entry.get("integrity_failure"):
                    reject("EVIDENCE_INPUT_INTEGRITY_FAILURE: " + entry["work_id"])
                    continue
                limitation = _partial_technical_limit(entry, evidence, plan, snapshots, task_dir=task_dir, task=task)
                if limitation:
                    technical[entry["work_id"]] = limitation
        from completion_policy import failure_limits_enabled
        failure = ({entry["work_id"]: item for entry in view["entries"]
                    if (item := _failure_limit(entry, evidence)) is not None}
                   if failure_limits_enabled(task) else {})
        actionable = [r for r in view["entries"] if r["state"] in {"ready", "awaiting_review", "submission_unknown"}
                      and r["work_id"] not in technical]
        if actionable:
            reject("EVIDENCE_AGENT_WORK_REMAINS: " + ",".join(r["work_id"] for r in actionable))
        permitted = _ACCESS_REASONS | _BLOCKED_REASONS | {
            "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED", "SOURCE_FAULT_UNVERIFIED",
            "REVIEWED_NO_APPLICABLE_FIGURATIVE_MARK", "LOCAL_LANGUAGE_BOUND_TO_PLANNED_QUERY"}
        for entry in view["entries"]:
            if entry["work_id"] in technical:
                limitations.append(technical[entry["work_id"]])
                continue
            if entry["work_id"] in failure:
                limitations.append(failure[entry["work_id"]])
                continue
            external = entry["state"] == "awaiting_user" and entry.get("kind") in {"user_evidence", "user_information"}
            constrained = entry["state"] in {"awaiting_access", "blocked"} and entry.get("reason") in permitted
            if entry.get("reason") in {"CURRENT_STATUS_ROUTE_UNAVAILABLE", "CURRENT_OWNER_ROUTE_UNAVAILABLE",
                                         "CURRENT_TERRITORY_ROUTE_UNAVAILABLE"}:
                constrained = False  # This reason alone is not evidence of an actual source constraint.
            structured = entry["state"] in {"awaiting_access", "blocked"} and _delivery_limit_valid(entry, task, evidence, plan, caps,
                candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir)
            if not external and not constrained and not structured:
                reject("EVIDENCE_LIMITATION_NOT_ESTABLISHED: " + entry["work_id"])
                continue
            limitations.append({**deepcopy(entry), "official_verification": entry.get("official_verification", "not_verified"),
                "reasoning": entry.get("reasoning") or "本项受所列来源或资料条件限制，未经过官方核验；具体来源和剩余事实随本报告保留。"})
        for source_issue in candidates.get('official_export_issues', []):
            for scope in scopes:
                if (scope.get('jurisdiction') == source_issue.get('jurisdiction')
                        and scope.get('right_type') in source_issue.get('affected_right_types', [])):
                    limitations.append({'scenario_id': scope['scenario_id'],
                        'jurisdiction': scope['jurisdiction'], 'right_type': scope['right_type'],
                        'state': 'blocked', 'reason': 'OFFICIAL_EXPORT_UNREADABLE',
                        'evidence_refs': [source_issue['evidence_id']],
                        'official_verification': 'not_verified',
                        'reasoning': '已留存的官方商标导出文件格式损坏，无法读取其中结果；该范围尚待重新取得并复核。'})
        if _preparation:
            return None
        # These are disclosed assessment facts, not a second execution queue.
        # All executable/review work has already been rejected above.
        limitations.extend(_reviewed_fact_limitations(assessment, evidence, evidence_root=evidence_root, task=task))
        limited_scopes = {_scope(entry) for entry in limitations}
        if any(_scope(scope) not in limited_scopes for scope in view.get("unresolved_scopes", [])):
            reject("EVIDENCE_UNRESOLVED_SCOPE_WITHOUT_LIMITATION")
        for scenario in assessment.get("scenario_summaries", []):
            queues = scenario["completion"].get("queues", {})
            pending = {(*_scope(row), row.get("candidate_id")) for row in queues.get("pending_assessments", [])}
            if queues.get("scope_unassessed") or any((*_scope(row), row.get("candidate_id")) not in pending
                    for row in queues.get("selected_unassessed", [])):
                reject("EVIDENCE_REVIEW_WORK_REMAINS")
            if any(_scope(row) not in limited_scopes for row in queues.get("pending_assessments", [])):
                reject("EVIDENCE_PENDING_ASSESSMENT_WITHOUT_LIMITATION")
    else:
        if not isinstance(stop_reason, str) or not stop_reason.strip():
            reject("STAGE_STOP_REASON_REQUIRED")
        if assessment["status"] == "completed":
            reject("COMPLETED_ASSESSMENT_REQUIRES_FINAL_PUBLICATION")
        actionable = [r for r in view["entries"] if r["state"] in {"ready", "awaiting_review", "submission_unknown"}]
        if actionable:
            reject("STAGE_AGENT_WORK_REMAINS: " + ",".join(r["work_id"] for r in actionable))
        blockers = [r for r in view["entries"] if
            (r["state"] == "awaiting_access" and r["reason"] in _ACCESS_REASONS | {
                "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED", "SOURCE_FAULT_UNVERIFIED"})
            or (r.get("reason") == "SPECIALTY_PROFESSIONAL_SCOPE_WAIT"
                and _professional_wait_valid(r, task, evidence, candidates, ledger, supplement=supplement))
            or (r["state"] == "blocked" and r["reason"] in _BLOCKED_REASONS
                and (r["reason"] not in {"CURRENT_STATUS_ROUTE_UNAVAILABLE", "CURRENT_OWNER_ROUTE_UNAVAILABLE",
                                         "CURRENT_TERRITORY_ROUTE_UNAVAILABLE"}
                     or _delivery_limit_valid(r, task, evidence, plan, caps, candidates=candidates,
                         ledger=ledger, supplement=supplement, task_dir=task_dir)))
            or (r["state"] == "awaiting_user" and r.get("kind") in {"user_evidence", "user_information"})]
        if not blockers or len(blockers) != len(view["entries"]):
            reject("STAGE_EXTERNAL_BLOCKER_NOT_ESTABLISHED")
        blocked_scopes = {_scope(r) for r in blockers}
        if any(_scope(scope) not in blocked_scopes for scope in view.get("unresolved_scopes", [])):
            reject("STAGE_UNRESOLVED_SCOPE_WITHOUT_BLOCKER")
        for scenario in assessment.get("scenario_summaries", []):
            queues = scenario["completion"].get("queues", {})
            pending = {(*_scope(row), row.get("candidate_id")) for row in queues.get("pending_assessments", [])}
            if queues.get("scope_unassessed") or any((*_scope(row), row.get("candidate_id")) not in pending
                    for row in queues.get("selected_unassessed", [])):
                reject("STAGE_REVIEW_WORK_REMAINS")
            if any(_scope(row) not in blocked_scopes for row in queues.get("pending_assessments", [])):
                reject("STAGE_PENDING_ASSESSMENT_WITHOUT_BLOCKER")
    return {"revision": task["completion_policy_revision"], "mode": mode, "stop_reason": stop_reason.strip() if stop_reason else None,
        "evidence_digest": review["evidence_digest"], "work_view_sha256": sha256_json(view),
        "remaining_work": view["entries"], "review_work_sha256": sha256_json(review),
        "snapshots": snapshots, "snapshot_digests": {name: sha256_json(value) for name, value in snapshots.items()},
        "snapshot_source_digests": source_digests,
        **({"delivery_status": "partial" if mode == "stage" else "ready",
            "delivery_basis": "source_evidence" if mode == "evidence" else "interim" if mode == "stage" else "necessary_work_completed",
            "limitations": limitations} if delivery else {})}


def restore_publication(task, evidence, candidates, plan, ledger, expected, saved, *, task_dir, evidence_root=None):
    """Independent validation and standalone builds share the same frozen proof check."""
    if not enabled(task):
        return expected
    from pathlib import Path
    from common import load_json
    publication = saved.get("publication")
    if (not isinstance(publication, dict) or not isinstance(publication.get("snapshots"), dict)
            or not isinstance(publication.get("snapshot_source_digests"), dict)):
        raise ValueError("PUBLICATION_CONTEXT_REQUIRED")
    snapshots = {}
    for name in ("source-capabilities.json", "browser-execution-status.json"):
        path = Path(task_dir) / name
        if path.is_file():
            snapshots[name] = load_json(path)
        actual_digest = sha256_json(snapshots[name]) if name in snapshots else None
        if actual_digest != publication.get("snapshot_source_digests", {}).get(name):
            raise ValueError("PUBLICATION_SNAPSHOT_CHANGED: " + name)
    expected["publication"] = publication_context(task, evidence, candidates, plan, ledger, expected,
        mode=publication.get("mode"), stop_reason=publication.get("stop_reason"), snapshots=snapshots,
        task_dir=task_dir, evidence_root=evidence_root)
    expected["completion_policy_revision"] = task["completion_policy_revision"]
    return expected
