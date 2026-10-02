"""08D: evidence-bound progress rounds and bounded technical stop per stable action."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_file, sha256_json

REVISION = "continuous-progress-stage-d-v1"
KEYS = ("query_id", "source_run_id", "candidate_id", "action_id", "issue_id",
        "gap_id", "fact_id", "request_id")
CONTROL = {"progress_events", "continuation_events", "access_requests"}
DIAGNOSIS = ("command", "receipt", "retained_files", "adapter", "submission")


def enabled(task: dict) -> bool:
    value = task.get("continuous_progress_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("CONTINUOUS_PROGRESS_REVISION_INVALID")
    return True


def events(evidence: dict) -> list[dict]:
    return [row for row in evidence.get("progress_events", []) if isinstance(row, dict)]


def recover_interrupted_rounds(task_dir: Path, actor: str) -> list[dict]:
    """Close rounds this dispatcher left open when a previous run was interrupted.

    An open begin makes every later begin fail with PROGRESS_ACTIONABLE_ROUND_REQUIRED.
    The recovery finish is an ordinary 08D finish, so effective progress is still
    derived from the original facts and never asserted here.
    """
    prior = events(load_json(Path(task_dir) / "evidence.json"))
    finished = {row.get("begin_id") for row in prior if row.get("kind") == "finish"}
    return [record_event(task_dir, {"kind": "finish", "begin_id": row["event_id"], "actor": actor,
                "reasoning": "Recovered a dispatch round left open by an interrupted run",
                "action_taken": "interrupted_dispatch_recovered"})
            for row in prior if row.get("kind") == "begin" and row.get("actor") == actor
            and row.get("event_id") not in finished]


def _target(view: dict, work_id: str) -> dict:
    rows = [*view.get("entries", []), *view.get("review_work", {}).get("entries", [])]
    matches = [row for row in rows if row.get("work_id") == work_id]
    if len(matches) != 1 or not matches[0].get("linked_action_id"):
        raise ValueError("PROGRESS_STABLE_WORK_REQUIRED")
    return matches[0]


def _matches(value, identifiers: dict) -> bool:
    if isinstance(value, dict):
        return any(value.get(key) == expected for key, expected in identifiers.items()) or any(
            _matches(child, identifiers) for child in value.values() if isinstance(child, (dict, list)))
    if isinstance(value, list):
        return any(_matches(child, identifiers) for child in value)
    return False


def _facts(entry: dict, evidence: dict, *, meaningful=False, task_dir=None) -> dict:
    identifiers = {key: entry[key] for key in KEYS if entry.get(key) not in (None, "", [])}
    for ref in entry.get("source_run_refs", []):
        if isinstance(ref, dict) and ref.get("run_id"):
            identifiers.setdefault("run_id", ref["run_id"])
    if not meaningful:
        return {key: [sha256_json(row) for row in rows if isinstance(row, dict) and _matches(row, identifiers)]
                for key, rows in evidence.items() if key not in CONTROL and isinstance(rows, list)}
    # Control prose, a new failure id or a recaptured identical response is not
    # usable evidence. Actual collection content and accepted state changes are.
    volatile = {'run_id', 'source_run_id', 'event_id', 'evidence_id', 'recorded_at', 'started_at',
        'finished_at', 'generated_at', 'updated_at', 'checked_at', 'reviewed_at', 'elapsed_ms',
        'reasoning', 'reason', 'progress_text', 'raw_paths', 'path', 'raw_path', 'capture_path', 'attempt_id',
        'captured_at', 'retrieved_at', 'timestamp', 'elapsed_seconds', 'request_id', 'retry_count'}
    def content(value):
        if isinstance(value, dict):
            return {key: content(child) for key, child in value.items() if key not in volatile}
        if isinstance(value, list):
            return sorted({sha256_json(content(row)): content(row) for row in value}.values(), key=sha256_json)
        return value
    from runtime_v24 import source_files_complete
    related_sources = {row.get('source_run_id') for rows in evidence.get('collections', {}).values()
        if isinstance(rows, list) for row in rows if isinstance(row, dict) and _matches(row, identifiers)}
    responses = {}
    def usable_run(row):
        if task_dir is None or not source_files_complete(Path(task_dir), evidence, row):
            return False
        from common import resolve_retained_path
        try:
            path = resolve_retained_path(Path(task_dir), row['raw_paths'][0], expected_sha256=row['payload_digest'])
            raw = load_json(path) if path.suffix.lower() == '.json' else {'sha256': row['payload_digest']}
            if path.suffix.lower() == '.json':
                if isinstance(raw, dict) and (raw.get('error_code') or raw.get('error')
                        or raw.get('status') in {'failed', 'access_limited', 'error'}):
                    return False
            responses[row.get('run_id')] = raw
            return True
        except (OSError, ValueError, TypeError):
            return False
    valid_runs = {row.get('run_id'): row for row in evidence.get('source_runs', [])
        if isinstance(row, dict) and row.get('status') in {'success', 'no_result'}
        and (_matches(row, identifiers) or row.get('run_id') in related_sources) and usable_run(row)}
    result = {}
    groups = {key: rows for key, rows in evidence.items() if key not in CONTROL and isinstance(rows, list)}
    groups.update({'collections.' + key: rows for key, rows in evidence.get('collections', {}).items()
                   if isinstance(rows, list)})
    for key, rows in groups.items():
        values = set()
        for row in rows:
            if not isinstance(row, dict) or not _matches(row, identifiers):
                continue
            if key == 'source_runs':
                if row.get('run_id') not in valid_runs:
                    continue
                response = responses[row.get('run_id')]
                row = {field: row[field] for field in ('provider', 'query_id', 'operation', 'status',
                    'jurisdiction', 'right_type') if field in row}
                row['retained_response'] = response
            if key.startswith('collections.'):
                source_id = row.get('source_run_id')
                if source_id and source_id not in valid_runs:
                    continue
                # Unbound collections must contain an intact, hashed local artifact.
                if not source_id:
                    from common import resolve_retained_path
                    def artifact(value):
                        if isinstance(value, dict):
                            if value.get('path') and value.get('sha256'):
                                try:
                                    return sha256_file(resolve_retained_path(Path(task_dir), value['path'],
                                        expected_sha256=value['sha256'])) == value['sha256']
                                except (OSError, ValueError, TypeError):
                                    return False
                            return any(artifact(v) for v in value.values())
                        return any(artifact(v) for v in value) if isinstance(value, list) else False
                    if task_dir is None or not artifact(row):
                        continue
            payload = row.get('payload') or {}
            if isinstance(payload, dict) and payload.get('error_code') and not any(
                    payload.get(field) for field in ('candidates', 'records', 'artifacts')):
                continue
            values.add(sha256_json(content(row)))
        if values:
            result[key] = sorted(values)
    return result


def _verified_ref(task_dir: Path, value: dict) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str) or not isinstance(value.get("sha256"), str):
        raise ValueError("PROGRESS_VERIFIABLE_EVIDENCE_REF_REQUIRED")
    path = Path(value["path"])
    if not path.is_absolute():
        path = task_dir / path
    path = path.resolve()
    if not path.is_file() or sha256_file(path) != value["sha256"]:
        raise ValueError("PROGRESS_EVIDENCE_REF_MISMATCH")
    return {"path": str(path), "sha256": value["sha256"]}


def status(evidence: dict, action_id: str) -> dict:
    rounds = [row for row in events(evidence) if row.get("action_id") == action_id]
    finished = [row for row in rounds if row.get("kind") == "finish"]
    reopen = next((row for row in reversed(rounds) if row.get("kind") == "reopen"), None)
    cycle = rounds[rounds.index(reopen) + 1:] if reopen else rounds
    current_finished = [row for row in cycle if row.get("kind") == "finish"]
    streak = 0
    for row in reversed(current_finished):
        if row.get("effective_progress"):
            break
        streak += 1
    diagnosis = next((row for row in reversed(cycle) if row.get("kind") == "diagnosis"), None)
    repair = next((row for row in reversed(cycle) if row.get("kind") == "repair"), None)
    active_stop = next((row for row in reversed(cycle) if row.get("kind") == "technical_stop"), None)
    failed_repair = bool(repair and len(finished) > repair.get("after_rounds", len(finished)) and streak)
    return {"rounds": len(finished), "consecutive_no_progress": streak,
            "diagnosis_required": streak >= 2 and not diagnosis,
            "repair_required": streak >= 2 and not repair,
            "stop_required": failed_repair and not active_stop,
            "diagnosis": diagnosis, "repair": repair, "technical_stop": active_stop}


def project(task: dict, view: dict, evidence: dict | None) -> dict:
    if not enabled(task) or evidence is None:
        return view
    result = deepcopy(view)
    from execution_budget import round_block
    cumulative_block = round_block(task, evidence)
    states = {}
    for entry in [*result.get("entries", []), *result.get("review_work", {}).get("entries", [])]:
        action_id = entry.get("linked_action_id")
        if not action_id:
            continue
        progress = states.setdefault(action_id, status(evidence, action_id))
        if progress["technical_stop"]:
            entry["underlying_state"] = entry.get("underlying_state", entry.get("state"))
            entry["underlying_reason"] = entry.get("underlying_reason", entry.get("reason"))
            entry["state"], entry["reason"] = "blocked", "TECHNICAL_EXECUTION_STOPPED"
            entry["technical_stop_id"] = progress["technical_stop"]["event_id"]
            entry["recovery_condition"] = progress["technical_stop"]["recovery_condition"]
        elif progress["stop_required"]:
            entry["underlying_state"] = entry.get("underlying_state", entry.get("state"))
            entry["state"], entry["reason"] = "awaiting_review", "PROGRESS_TECHNICAL_STOP_REQUIRED"
        elif progress["repair_required"]:
            entry["underlying_state"] = entry.get("underlying_state", entry.get("state"))
            entry["state"], entry["reason"] = "awaiting_review", "PROGRESS_DIAGNOSIS_OR_REPAIR_REQUIRED"
        elif cumulative_block and entry.get('state') == 'ready' and entry.get('kind') != 'scope_review':
            entry['underlying_state'], entry['underlying_reason'] = entry['state'], entry.get('reason')
            entry['state'], entry['reason'] = 'blocked', cumulative_block
    if cumulative_block:
        result['execution_budget_stop'] = {'reason': cumulative_block, 'incomplete': True}
        result['status'] = 'incomplete'
    result["per_work_progress"] = [{"action_id": key, **{name: value for name, value in state.items()
        if name in {"rounds", "consecutive_no_progress", "diagnosis_required", "repair_required", "stop_required"}}}
        for key, state in sorted(states.items())]
    result["technical_stops"] = [{"action_id": key, "event_id": state["technical_stop"]["event_id"],
        "recovery_condition": state["technical_stop"]["recovery_condition"]}
        for key, state in sorted(states.items()) if state["technical_stop"]]
    result["counts"] = {state: sum(row.get("state") == state for row in result.get("entries", []))
        for state in ("ready", "awaiting_review", "awaiting_access", "awaiting_user", "submission_unknown", "blocked")}
    if result["technical_stops"]:
        result["status"] = "incomplete"
    if "work_view_sha256" in result:
        result["work_view_sha256"] = sha256_json({key: value for key, value in result.items()
            if key not in {"work_view_sha256", "review_work"}})
    return result


def dispatch_block(task: dict, evidence: dict, provider: str, row: dict) -> str | None:
    if not enabled(task):
        return None
    from execution_budget import round_block
    if (reason := round_block(task, evidence)):
        return reason
    for event in reversed(events(evidence)):
        if event.get("provider") == provider and event.get("query_id") == row.get("query_id"):
            state = status(evidence, event["action_id"])
            if state["technical_stop"]:
                return "TECHNICAL_EXECUTION_STOPPED"
            if state["stop_required"]:
                return "PROGRESS_TECHNICAL_STOP_REQUIRED"
            if state["repair_required"]:
                return "PROGRESS_DIAGNOSIS_OR_REPAIR_REQUIRED"
            return None
    return None


def _append_event(task_dir: Path, task: dict, evidence: dict, request: dict, view) -> dict:
    """Validate one control event against in-memory state and append it (caller persists)."""
    kind = request.get("kind")
    if kind not in {"begin", "finish", "diagnosis", "repair", "technical_stop", "reopen"}:
        raise ValueError("PROGRESS_KIND_INVALID")
    if not all(isinstance(request.get(key), str) and request[key].strip()
               for key in ("actor", "reasoning")):
        raise ValueError("PROGRESS_ACTOR_AND_BASIS_REQUIRED")
    prior = events(evidence)
    active = next((row for row in reversed(prior) if row.get("kind") == "begin" and
        (kind != "finish" or row.get("event_id") == request.get("begin_id")) and
        not any(other.get("kind") == "finish" and other.get("begin_id") == row.get("event_id")
                for other in prior)), None)
    entry = None
    if kind in {"begin", "finish"}:
        if kind == "begin":
            entry = _target(view(), request.get("work_id"))
            if entry.get("state") != "ready" or any(row.get("kind") == "begin" and
                    row.get("action_id") == entry["linked_action_id"] and not any(
                    other.get("kind") == "finish" and other.get("begin_id") == row.get("event_id")
                    for other in prior) for row in prior):
                raise ValueError("PROGRESS_ACTIONABLE_ROUND_REQUIRED")
        elif not active or active.get("event_id") != request.get("begin_id"):
            raise ValueError("PROGRESS_OPEN_ROUND_REQUIRED")
    action_id = (entry or active or {}).get("linked_action_id") or request.get("action_id")
    if not isinstance(action_id, str) or not action_id.startswith("ACTION-"):
        raise ValueError("PROGRESS_ACTION_ID_REQUIRED")
    state = status(evidence, action_id)
    from execution_budget import policy as budget_policy, round_block
    bounded = budget_policy(task) is not None
    if kind == 'begin' and bounded:
        block = round_block(task, evidence)
        if block and entry.get('kind') != 'scope_review':
            raise ValueError(block)
    if kind == "begin" and state["technical_stop"]:
        raise ValueError("PROGRESS_TECHNICAL_STOP_ACTIVE")
    if kind == "begin" and state["consecutive_no_progress"] >= 2 and (
            not state["repair"] or state["repair"]["after_rounds"] != state["rounds"]):
        raise ValueError("PROGRESS_DIAGNOSIS_AND_REPAIR_BEFORE_REPEAT_REQUIRED")
    event = {"kind": kind, "actor": request["actor"], "reasoning": request["reasoning"],
             "action_id": action_id, "recorded_at": now_iso()}
    if kind == "begin":
        event.update(work_id=entry["work_id"], issue_id=entry.get("issue_id"),
            linked_action_id=action_id, provider=entry.get("provider"), query_id=entry.get("query_id"),
            entry=entry, fact_snapshot=_facts(entry, evidence, meaningful=bounded, task_dir=task_dir))
    elif kind == "finish":
        if request.get("action_taken") in (None, "", "wait", "notification"):
            raise ValueError("PROGRESS_ACTUAL_ACTION_REQUIRED")
        original = active["entry"]
        projected = view()
        candidates = [*projected.get('entries', []), *projected.get('review_work', {}).get('entries', [])]
        current = [row for row in candidates if row.get("linked_action_id") == action_id
            and (bounded or row.get("issue_id") == original.get("issue_id"))]
        facts = _facts(original, evidence, meaningful=bounded, task_dir=task_dir)
        changed = (any(set(rows) - set(active['fact_snapshot'].get(key, [])) for key, rows in facts.items())
                   if bounded else facts != active['fact_snapshot'])
        complete = not current
        event.update(begin_id=active["event_id"], work_id=active["work_id"],
            issue_id=active.get("issue_id"), provider=active.get("provider"), query_id=active.get("query_id"),
            action_taken=request["action_taken"], effective_progress=bool(changed or complete),
            outcome="obligation_closed" if complete else "linked_evidence_changed" if changed else "no_effective_progress")
    elif kind == "diagnosis":
        checks = request.get("checks")
        if state["consecutive_no_progress"] < 2 or not isinstance(checks, dict) or any(
                not isinstance(checks.get(key), str) or not checks[key].strip() for key in DIAGNOSIS):
            raise ValueError("PROGRESS_TWO_ROUNDS_AND_FIVE_CHECKS_REQUIRED")
        event["checks"] = {key: checks[key] for key in DIAGNOSIS}
    elif kind == "repair":
        if not state["diagnosis"] or not request.get("evidence_ref"):
            raise ValueError("PROGRESS_DIAGNOSIS_AND_NEW_REPAIR_EVIDENCE_REQUIRED")
        if state["stop_required"]:
            # The repaired round again made no progress: record technical_stop
            # (08D contract) instead of another repair that reopens the same loop.
            raise ValueError("PROGRESS_TECHNICAL_STOP_REQUIRED_AFTER_FAILED_REPAIR")
        reference = _verified_ref(task_dir, request["evidence_ref"])
        if any(row.get("kind") == "repair" and (row.get("evidence_ref") == reference or
                    bounded and row.get('evidence_ref', {}).get('sha256') == reference['sha256'])
               for row in prior if row.get("action_id") == action_id):
            raise ValueError("PROGRESS_REPAIR_EVIDENCE_ALREADY_USED")
        event["evidence_ref"] = reference
        event["after_rounds"] = state["rounds"]
    elif kind == "technical_stop":
        repair = state["repair"]
        if not state["diagnosis"] or not repair or state["rounds"] <= repair["after_rounds"] or not state["consecutive_no_progress"]:
            raise ValueError("PROGRESS_FAILED_REPAIR_ROUND_REQUIRED")
        if state["technical_stop"] or not request.get("recovery_condition"):
            raise ValueError("PROGRESS_STOP_OR_RECOVERY_INVALID")
        rounds = [row for row in prior if row.get("action_id") == action_id and row.get("kind") == "begin"]
        origin = rounds[-1]
        event.update(recovery_condition=request["recovery_condition"], provider=origin.get("provider"),
                     query_id=origin.get("query_id"), incomplete=True)
    elif kind == "reopen":
        if not state["technical_stop"] or not request.get("new_evidence_ref") or not request.get("reconciliation_id"):
            raise ValueError("PROGRESS_NEW_EVIDENCE_AND_RECONCILIATION_REQUIRED")
        reference = _verified_ref(task_dir, request["new_evidence_ref"])
        if (reference == state["repair"].get("evidence_ref") or bounded and any(
                reference['sha256'] == (row.get('evidence_ref') or row.get('new_evidence_ref') or {}).get('sha256')
                for row in prior if row.get('action_id') == action_id)):
            raise ValueError("PROGRESS_NEW_EVIDENCE_REQUIRED")
        reconciliations = [row for row in evidence.get("continuation_events", [])
            if isinstance(row, dict) and row.get("kind") == "reconcile"]
        if not any(row.get("event_id") == request["reconciliation_id"] for row in reconciliations):
            raise ValueError("PROGRESS_RECONCILIATION_NOT_FOUND")
        event.update(new_evidence_ref=reference, reconciliation_id=request["reconciliation_id"],
            provider=state["technical_stop"].get("provider"), query_id=state["technical_stop"].get("query_id"))
    event["event_id"] = "PROGRESS-" + sha256_json({"task_id": task["task_id"], "sequence": len(prior), "event": event})[:24]
    evidence.setdefault("progress_events", []).append(event)
    return event


def record_event(task_dir: Path, request: dict) -> dict:
    """Record control facts only; successful progress comes from original evidence records."""
    from provider_utils import evidence_lock
    from workflow_v24 import work_view_from_dir
    task_dir = Path(task_dir)
    with evidence_lock(task_dir):
        task = load_json(task_dir / "task.json")
        evidence = load_json(task_dir / "evidence.json")
        if not enabled(task) or evidence.get("task_id") != task.get("task_id"):
            raise ValueError("PROGRESS_TASK_MISMATCH")
        event = _append_event(task_dir, task, evidence, request, lambda: work_view_from_dir(task_dir))
        atomic_write_json(task_dir / "evidence.json", evidence)
        return event


def record_events(task_dir: Path, requests: list[dict]) -> list[dict]:
    """Record several begin events, or several finish events, with one load, one work view and one write.

    Equivalent to calling record_event once per request: begin never changes what
    another begin or finish reads from the work view (08D status ignores begin
    events, and finish only asks whether the original entry still exists), so the
    view is derived once. Events accepted before a failing request are kept, as
    with sequential calls, and the failure is re-raised.
    """
    from provider_utils import evidence_lock
    from workflow_v24 import work_view_from_dir
    task_dir = Path(task_dir)
    kinds = {request.get("kind") for request in requests if isinstance(request, dict)}
    if not requests or len(kinds) != 1 or not kinds <= {"begin", "finish"}:
        raise ValueError("PROGRESS_BATCH_KIND_INVALID")
    with evidence_lock(task_dir):
        task = load_json(task_dir / "task.json")
        evidence = load_json(task_dir / "evidence.json")
        if not enabled(task) or evidence.get("task_id") != task.get("task_id"):
            raise ValueError("PROGRESS_TASK_MISMATCH")
        cache = []
        def view():
            if not cache:
                cache.append(work_view_from_dir(task_dir))
            return cache[0]
        recorded = []
        try:
            for request in requests:
                recorded.append(_append_event(task_dir, task, evidence, request, view))
        finally:
            if recorded:
                atomic_write_json(task_dir / "evidence.json", evidence)
        return recorded
