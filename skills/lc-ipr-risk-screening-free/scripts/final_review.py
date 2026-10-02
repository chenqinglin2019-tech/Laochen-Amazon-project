"""Final-only review policy, semantic bindings and explicit prior-review reuse.

Old attestations are immutable. A new review can reference unchanged units from
its own prior review, but must review the current overall, scope and limitations.
"""
from __future__ import annotations

from copy import deepcopy
from common import now_iso, sha256_json

REVISION = "final-double-review-v1"
ADMIN_COLLECTIONS = {"history", "logs", "progress_events", "review_progress_events",
    "stage_review_events", "delivery_events", "delivery_version_events",
    "execution_progress_events", "execution_attempts", "review_events"}
ADMIN_FIELDS = {"generated_at", "updated_at", "last_updated", "progress_text",
    "display_order", "priority", "progress_percentage", "work_view_sha256"}
PATH_FIELDS = {"path", "local_path", "file_path", "raw_paths", "artifact_path",
    "source_path", "evidence_root", "historical_evidence_root"}
TASK_FIELDS = {"task_id", "assessment_policy", "assessment_revision", "product", "images",
    "product_identity", "product_scope", "product_change_version", "product_applicability_reviews",
    "product_feedback_history", "target_jurisdictions", "coverage_requirements",
    "assessment_scenarios", "primary_scenario_id", "assessment_scope_exclusions",
    "screening_revision", "recall_planning_revision", "query_terms", "discovery_followups",
    "decision_workflow_revision", "specialty_workflow_revision", "workflow_correction_revision",
    "completion_policy_revision", "review_policy_revision", "retrieval_workflow_revision"}
TASK_FIELDS |= {"specialty_analysis_revision", "specialty_analysis_events", "distinctive_rights_revision",
    "distinctive_rights_events", "candidate_triage_stage_events", "candidate_followup_events"}
TASK_FIELDS.add("presentation_policy_revision")
TASK_FIELDS.add("product_structure_policy")
TASK_FIELDS.add("final_review_execution_revision")
TASK_FIELDS |= {"limited_delivery_revision", "review_conflict_revision"}


def enabled(task):
    if task.get('final_review_execution_revision') is not None:
        from module_review import enabled as modules_enabled
        modules_enabled(task)
    revision = task.get("review_policy_revision")
    if revision is None:
        return False
    if revision != REVISION:
        raise ValueError("REVIEW_POLICY_REVISION_INVALID")
    return True


def semantic(value):
    """Discard administrative metadata, retaining all unknown substantive data.

Paths are omitted only when the same record carries a content fingerprint;
unfingerprinted paths remain dependencies. Source/retrieval dates stay bound.
"""
    if isinstance(value, dict):
        fingerprinted = any(value.get(key) for key in
            ("sha256", "payload_digest", "payload_sha256", "raw_sha256", "content_sha256", "file_sha256", "artifact_sha256"))
        return {key: semantic(item) for key, item in value.items()
            if key not in ADMIN_FIELDS and key not in ADMIN_COLLECTIONS
            and not (fingerprinted and key in PATH_FIELDS)}
    if isinstance(value, list):
        return [semantic(item) for item in value]
    return value


def inputs(evidence, candidates, ledger, plan, task, supplement=None):
    material = semantic({"revision": REVISION, "task": {key: task[key] for key in TASK_FIELDS if key in task},
        "evidence": evidence, "candidates": candidates, "ledger": ledger,
        "plan": plan, "supplement": supplement})
    # Queue order is presentation metadata. Normalize only request lists, never
    # claims, views or other source content whose sequence can carry meaning.
    for provider, rows in material.get("plan", {}).get("queries", {}).items():
        if isinstance(rows, list):
            material["plan"]["queries"][provider] = sorted(rows,
                key=lambda row: (str(row.get("query_id") or "") if isinstance(row, dict) else "", sha256_json(row)))
    return material


def digest(evidence, candidates, ledger, plan, task, supplement=None):
    return sha256_json(inputs(evidence, candidates, ledger, plan, task, supplement))


def freeze_time_binding(task, evidence, at=None):
    return {"assessment_at": at or now_iso(),
        "evidence_semantic_sha256": sha256_json(semantic(evidence)),
        "task_semantic_sha256": sha256_json(semantic({key: task[key] for key in TASK_FIELDS if key in task}))}


def evaluation_at(task, evidence=None):
    """Retain the final assessment instant only while its source facts match."""
    frozen = task.get("final_review_freeze") or {}
    if enabled(task) and evidence is not None and frozen.get("assessment_at"):
        current = freeze_time_binding(task, evidence, frozen["assessment_at"])
        if current == frozen:
            return frozen["assessment_at"]
    return now_iso()


def unit_id(row):
    return "FINAL-UNIT-" + sha256_json({key: row.get(key) or ("product" if key == "assessment_object" else "")
        for key in ("scenario_id", "jurisdiction", "right_type", "candidate_id", "assessment_object")})[:24]


def _scope_matches(item, row):
    scope = item.get("scope") if isinstance(item.get("scope"), dict) else item
    return all(not scope.get(key) or not row.get(key) or scope[key] == row[key]
        for key in ("scenario_id", "jurisdiction", "right_type"))


def _select(value, row, dependencies=None):
    """Keep unscoped facts and the judgment's actual candidate/scope dependencies."""
    if isinstance(value, list):
        return [_select(item, row, dependencies) for item in value
            if not isinstance(item, dict) or (_scope_matches(item, row) and
                (not row.get("candidate_id") or not item.get("candidate_id") or
                 item.get("candidate_id") == row["candidate_id"]) and
                _dependency_matches(item, row, dependencies))]
    if isinstance(value, dict):
        return {key: _select(item, row, dependencies) for key, item in value.items()}
    return value


def _references(value, fields):
    result = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in fields:
                result.update(str(ref) for ref in (item if isinstance(item, list) else [item]) if isinstance(ref, (str, int)))
            result.update(_references(item, fields))
    elif isinstance(value, list):
        for item in value:
            result.update(_references(item, fields))
    return result


def _dependency_index(material, row):
    """Resolve whole retained envelopes through candidate, query and run identity.

    Raw hashes belong to their source record. Filtering only its nested payload
    leaves the unrelated envelope behind and spuriously reopens another unit.
    """
    refs, queries, runs = {}, {}, {}
    def add(index, key, owners):
        if key and owners:
            index.setdefault(key, set()).update(owners)
    if row.get("candidate_id"):
        for ref in _references(row, {"evidence_refs", "verification_refs", "evidence_id"}):
            add(refs, ref, {row["candidate_id"]})
    for group in material.get("candidates", {}).values():
        for candidate in group if isinstance(group, list) else []:
            if isinstance(candidate, dict) and candidate.get("candidate_id"):
                for ref in _references(candidate, {"evidence_refs", "verification_refs", "evidence_id"}):
                    add(refs, ref, {candidate["candidate_id"]})
    for group in material.get("plan", {}).get("queries", {}).values():
        for query in group if isinstance(group, list) else []:
            if isinstance(query, dict):
                add(queries, query.get("query_id"), _references(query, {"candidate_id"}))
    evidence = material.get("evidence") or {}
    entries = [entry for group in evidence.get("collections", {}).values() if isinstance(group, list)
        for entry in group if isinstance(entry, dict)]
    for entry in entries:
        owners = refs.get(entry.get("evidence_id"), set()) | queries.get(entry.get("query_id"), set()) | _references(entry, {"candidate_id"})
        add(refs, entry.get("evidence_id"), owners)
        add(runs, entry.get("source_run_id"), owners)
    for run in evidence.get("source_runs", []):
        if isinstance(run, dict):
            add(runs, run.get("run_id"), queries.get(run.get("query_id"), set()) | _references(run, {"candidate_id"}))
    return {"evidence_id": refs, "source_run_id": runs, "run_id": runs, "query_id": queries}


def _dependency_matches(item, row, dependencies):
    candidate = row.get("candidate_id")
    if not candidate or dependencies is None:
        return True
    direct_refs = _references(row, {"evidence_refs", "verification_refs", "evidence_id"})
    if item.get("evidence_id") in direct_refs:
        return True
    owners = set().union(*(index.get(item.get(field), set()) for field, index in dependencies.items()))
    return not owners or candidate in owners


def unit_binding(row, material):
    """Use direct referenced facts plus scoped inventory/obligations.

Scope rows bind the complete scope inventory. Candidate rows bind the selected
candidate and all unscoped source facts, so newly discovered facts cannot be
silently ignored while an unrelated explicitly scoped candidate can be reused.
"""
    return sha256_json(_select(material, row, _dependency_index(material, row)))


def reuse_options(previous, material):
    if not previous:
        return {"previous_review_sha256": None, "reusable_unit_ids": [], "changed_unit_ids": []}
    validate_envelope(previous)
    bindings = previous["review_context"]["final_review"]["unit_bindings"]
    reusable, changed = [], []
    for row in previous["assessments"]:
        key = unit_id(row)
        (reusable if bindings.get(key) == unit_binding(row, material) else changed).append(key)
    return {"previous_review_sha256": sha256_json(previous),
        "reusable_unit_ids": sorted(reusable), "changed_unit_ids": sorted(changed)}


def prepare_rows(payload, assessments, material, previous=None):
    requested = payload.get("reused_unit_ids", [])
    if not isinstance(requested, list) or len(set(requested)) != len(requested):
        raise ValueError("FINAL_REVIEW_REUSE_INVALID")
    if requested and previous is None:
        raise ValueError("FINAL_REVIEW_PREVIOUS_RECEIPT_REQUIRED")
    options = reuse_options(previous, material)
    if not set(requested).issubset(options["reusable_unit_ids"]):
        raise ValueError("FINAL_REVIEW_REUSED_UNIT_CHANGED")
    current = {unit_id(row) for row in assessments}
    if current.intersection(requested):
        raise ValueError("FINAL_REVIEW_UNIT_REVIEWED_AND_REUSED")
    rows = deepcopy(assessments)
    rows.extend(deepcopy(row) for row in (previous or {}).get("assessments", []) if unit_id(row) in requested)
    statement = payload.get("final_review_statement")
    if not isinstance(statement, dict) or any(not isinstance(statement.get(key), str) or not statement[key].strip()
        for key in ("overall", "scope", "limitations")):
        raise ValueError("FINAL_REVIEW_CURRENT_OVERALL_SCOPE_LIMITATIONS_REQUIRED")
    receipt = {"revision": REVISION, "statement": deepcopy(statement),
        "unit_bindings": {unit_id(row): unit_binding(row, material) for row in rows},
        "reused_unit_ids": list(requested),
        "previous_review_sha256": sha256_json(previous) if requested else None,
        "previous_review": deepcopy(previous) if requested else None}
    return rows, receipt


def validate_envelope(review, material=None):
    context = review.get("review_context", {})
    receipt = context.get("final_review")
    if not isinstance(receipt, dict) or receipt.get("revision") != REVISION:
        raise ValueError("FINAL_REVIEW_RECEIPT_REQUIRED")
    execution = context.get("execution") or {}
    if (not context.get("session_id") or context.get("first_review_visible") is not False or
        not execution.get("agent_id") or not execution.get("run_id") or
        execution.get("input_digest") != context.get("evidence_digest") or
        execution.get("assessment_digest") != sha256_json(review.get("assessments")) or
        execution.get("final_review_digest") != sha256_json(receipt)):
        raise ValueError("FINAL_REVIEW_EXECUTION_ATTESTATION_INVALID")
    statement = receipt.get("statement", {})
    if any(not isinstance(statement.get(key), str) or not statement[key].strip()
        for key in ("overall", "scope", "limitations")):
        raise ValueError("FINAL_REVIEW_CURRENT_OVERALL_SCOPE_LIMITATIONS_REQUIRED")
    rows = review.get("assessments", [])
    by_id = {unit_id(row): row for row in rows}
    bindings = receipt.get("unit_bindings", {})
    if len(by_id) != len(rows) or set(by_id) != set(bindings):
        raise ValueError("FINAL_REVIEW_UNIT_BINDINGS_INVALID")
    if material is not None and any(bindings[key] != unit_binding(row, material) for key, row in by_id.items()):
        raise ValueError("FINAL_REVIEW_UNIT_INPUT_CHANGED")
    reused = receipt.get("reused_unit_ids", [])
    if not isinstance(reused, list) or len(set(reused)) != len(reused) or not set(reused).issubset(by_id):
        raise ValueError("FINAL_REVIEW_REUSE_INVALID")
    previous = receipt.get("previous_review")
    if reused:
        if not isinstance(previous, dict) or sha256_json(previous) != receipt.get("previous_review_sha256"):
            raise ValueError("FINAL_REVIEW_PREVIOUS_RECEIPT_CHANGED")
        validate_envelope(previous)
        old_context = previous.get("review_context", {})
        old_execution = old_context.get("execution", {})
        if (old_context.get("first_review_visible") is not False or
            old_execution.get("input_digest") != old_context.get("evidence_digest") or
            old_execution.get("assessment_digest") != sha256_json(previous.get("assessments"))):
            raise ValueError("FINAL_REVIEW_PREVIOUS_ATTESTATION_INVALID")
        old = {unit_id(row): row for row in previous["assessments"]}
        old_bindings = old_context["final_review"]["unit_bindings"]
        if any(key not in old or old[key] != by_id[key] or old_bindings.get(key) != bindings[key] for key in reused):
            raise ValueError("FINAL_REVIEW_REUSE_NOT_IDENTICAL")
    elif previous is not None or receipt.get("previous_review_sha256") is not None:
        raise ValueError("FINAL_REVIEW_UNREFERENCED_PREVIOUS_RECEIPT")
    from module_review import validate_execution
    validate_execution(review, required=bool(material and
        material.get('task', {}).get('final_review_execution_revision') == 'module-double-review-v1'))


def pair_summary(first, second, digest_value):
    # Called only after the existing full pair/row/adjudication validation.
    def origin(review, key):
        receipt = review["review_context"]["final_review"]
        if key in receipt["reused_unit_ids"]:
            return origin(receipt["previous_review"], key)
        from module_review import unit_origins
        return unit_origins(review, key)
    first_modules = first['review_context'].get('execution', {}).get('module_execution')
    second_modules = second['review_context'].get('execution', {}).get('module_execution')
    if first_modules and second_modules:
        left = {row['session_id'] for row in first_modules['modules'] + [first_modules['summary']]}
        right = {row['session_id'] for row in second_modules['modules'] + [second_modules['summary']]}
        if left & right:
            raise ValueError('FINAL_REVIEW_MODULE_PAIR_NOT_INDEPENDENT')
    shared = set(first["review_context"]["final_review"]["unit_bindings"]) & set(
        second["review_context"]["final_review"]["unit_bindings"])
    if any((origin(first, key) - {None}) & (origin(second, key) - {None}) for key in shared):
        raise ValueError("FINAL_REVIEW_REUSED_ORIGIN_NOT_INDEPENDENT")
    return {"revision": REVISION, "status": "complete", "evidence_digest": digest_value,
        "review_sha256s": [sha256_json(first), sha256_json(second)],
        "reviewer_sessions": [row["review_context"]["session_id"] for row in (first, second)],
        "reused_unit_counts": [len(row["review_context"]["final_review"]["reused_unit_ids"])
            for row in (first, second)],
        "statements": [deepcopy(row["review_context"]["final_review"]["statement"]) for row in (first, second)],
        **({'execution_revision': 'module-double-review-v1',
            'module_sessions': [[module['session_id'] for module in metadata['modules']]
                for metadata in (first_modules, second_modules)]} if first_modules and second_modules else {})}


def completed(assessment):
    final = (assessment or {}).get("final_review", {})
    return final.get("revision") == REVISION and final.get("status") == "complete"


def project_stage(stage, assessment):
    """Present the validated final assessments; never manufacture 09C receipts."""
    result = deepcopy(stage)
    if not completed(assessment):
        result["review_label"] = "待最终双审"
        return result
    final = assessment["final_review"]
    judgments = []
    for row in assessment.get("assessments", []):
        risk = row.get("risk") if row.get("aggregation_included", True) else None
        judgments.append({**deepcopy(row), "event_id": unit_id(row),
            "scope": {**{key: row.get(key) for key in ("scenario_id", "jurisdiction", "right_type", "candidate_id")},
                "product_version": stage.get("product", {}).get("product_version")},
            "applicability": "out_of_scope" if row.get("out_of_scope") else "current",
            "stage_risk": risk, "display_grade": risk or "暂不定级", "review_status": "final_reviewed",
            "verification_status": "pending" if row.get("assessment_status") == "pending" else "verified",
            "confidence": row.get("evidence_confidence"), "comparison": deepcopy(row.get("comparison", {})),
            "confirmed_facts": deepcopy(row.get("supporting_evidence", [])),
            "assessment_date": assessment.get("generated_at"),
            "product_link": row.get("reasoning"),
            "gaps": deepcopy(row.get("confidence_gaps", [])), "weak_leads": []})
    overall = deepcopy(assessment.get("overall", {}))
    overall["drivers"] = [unit_id(row) if isinstance(row, dict) else row for row in overall.get("drivers", [])]
    overall.update(stage_risk=overall.get("risk"), display_grade=overall.get("risk") or "暂不定级",
        review_status="complete", applicability="current",
        verification_status="verified" if assessment.get("status") == "completed" else "pending")
    signals = []
    for field, kind in (("future_applications", "future_application"), ("enforcement_signals", "enforcement")):
        for row in assessment.get(field, []):
            signals.append({**deepcopy(row), "signal_type": kind, "signal_reasoning": row.get("reasoning"),
                "review_status": "final_reviewed", "applicability": "current",
                "scope": {key: row.get(key) for key in ("scenario_id", "jurisdiction", "right_type", "candidate_id")}})
    by_scope = []
    ranks = ("极低", "低", "中", "高", "极高")
    scopes = sorted({tuple(row['scope'].get(key) or '' for key in ('scenario_id', 'jurisdiction', 'right_type'))
        for row in judgments})
    for scope in scopes:
        rows = [row for row in judgments if tuple(row['scope'].get(key) or '' for key in
            ('scenario_id', 'jurisdiction', 'right_type')) == scope]
        included = [row for row in rows if row.get('applicability') == 'current' and row.get('stage_risk') in ranks]
        grade = max((row['stage_risk'] for row in included), key=ranks.index, default=None)
        by_scope.append({**dict(zip(('scenario_id', 'jurisdiction', 'right_type'), scope)),
            'product_version': stage.get('product', {}).get('product_version'),
            'stage_risk': grade, 'display_grade': grade or '暂不定级', 'review_status': 'complete',
            'verification_status': 'pending' if any(row['verification_status'] == 'pending' for row in rows) else 'verified',
            'applicability': 'current', 'drivers': [row['event_id'] for row in included if row['stage_risk'] == grade]})
    # The operating scope grade and the unaltered candidate findings have
    # distinct meanings. Consume the same deterministic aggregate used by the
    # report instead of deriving a pending module from a pending candidate.
    if assessment.get('known_findings', {}).get('revision') == 'known-findings-risk-v1':
        by_scope = [{**deepcopy(row), 'product_version': stage.get('product', {}).get('product_version'),
            'stage_risk': row['risk'], 'display_grade': row['risk'], 'review_status': 'complete',
            'applicability': row.get('applicability', 'current'), 'verification_status': 'pending' if row.get('pending_count') else 'verified',
            'drivers': [unit_id(driver) for driver in row.get('drivers', [])]}
            for row in assessment['known_findings']['by_scope']]
    result["stage_risk"] = {"revision": REVISION, "status": "final_reviewed", "judgments": judgments,
        "overall": overall, "signals": signals, "by_scope": by_scope,
        "by_scenario": [deepcopy(row) | {'stage_risk': row.get('risk'), 'display_grade': row.get('risk') or '暂不定级',
            'review_status': 'complete'} for row in assessment.get('scenario_summaries', [])],
        "final_review": deepcopy(final)}
    result.update(review_label="最终双审已完成", review_issues=[], quarantined_judgments=[],
        delivery_type="final_report", final_review=deepcopy(final))
    result["grade_cutoff"] = {"review_policy_revision": REVISION,
        "evidence_digest": final["evidence_digest"], "review_sha256s": final["review_sha256s"], "batches": []}
    return result
