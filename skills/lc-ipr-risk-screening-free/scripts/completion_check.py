#!/usr/bin/env python3
"""Read-only completion gate shared by dispatch, publication and Codex hooks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import ensure_object, load_json, sha256_file, sha256_json

ARTIFACTS = ("report-data.json", "report.html", "report.md", "report-findings.csv",
             "report-manifest.json", "delivery-validation.json")
OPTIONAL_INPUTS = ("supplemental-evidence.json", "source-capabilities.json",
                   "browser-execution-status.json", "browser-candidate-journal.json")


def review_paths(task_dir, first_review=None, second_review=None, adjudication=None):
    return tuple(Path(p).resolve() if p else Path(task_dir).resolve() / name for p, name in
        ((first_review, "first-review.json"), (second_review, "second-review.json"), (adjudication, "adjudication.json")))


def delivery_inputs(task_dir, first_review, second_review, adjudication):
    root = Path(task_dir)
    inputs = {name: load_json(root / name) for name in
        ("task.json", "evidence.json", "search-plan.json", "materiality-annotations.json")}
    candidate_path = root / "normalized-candidates.json"
    inputs["normalized-candidates.json"] = load_json(candidate_path) if candidate_path.is_file() else {}
    return sha256_json(inputs
        | {"first_review": load_json(first_review), "second_review": load_json(second_review),
           "adjudication": load_json(adjudication) if adjudication else None})


def optional_inputs(task_dir):
    # Include absence: adding a supplement/capability snapshot invalidates delivery.
    return {name: sha256_file(Path(task_dir) / name) if (Path(task_dir) / name).exists() else None
            for name in OPTIONAL_INPUTS}


def validate_delivery_transaction(task_dir, output_dir, *, first_review, second_review, adjudication,
                                  expected_delivery_input_sha256, expected_optional_inputs):
    """Verify copied bytes and frozen inputs inside an already validated publish transaction.

    The staging directory has just passed the independent semantic validator.
    This check deliberately does not run that validator again; standalone
    completion checks still call :func:`validate_delivery` and fully recompute.
    """
    source, out = Path(task_dir).resolve(), Path(output_dir).resolve()
    errors = []
    try:
        if delivery_inputs(source, first_review, second_review, adjudication) != expected_delivery_input_sha256:
            errors.append("DELIVERY_INPUTS_CHANGED_DURING_PUBLICATION")
        if optional_inputs(source) != expected_optional_inputs:
            errors.append("DELIVERY_OPTIONAL_INPUTS_CHANGED_DURING_PUBLICATION")
        output_task = ensure_object(load_json(out / "task.json"), "output task")
        current_task = ensure_object(load_json(source / "task.json"), "source task")
        if output_task.get("task_id") != current_task.get("task_id"):
            errors.append("DELIVERY_TASK_ID_MISMATCH")
        if Path(output_task.get("outputs", {}).get("assessment_input_dir", "")).resolve() != source:
            errors.append("DELIVERY_SOURCE_MISMATCH")
        reviews = {"first": load_json(first_review), "second": load_json(second_review),
                   "adjudication": load_json(adjudication) if adjudication else None}
        if load_json(out / "assessment.json").get("review", {}).get("input_reviews") != reviews:
            errors.append("DELIVERY_REVIEW_INPUTS_CHANGED")
        manifest = ensure_object(load_json(out / "report-manifest.json"), "report manifest")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            errors.append("DELIVERY_MANIFEST_ARTIFACTS_INVALID")
        else:
            from report_package_stage_c import report_files
            report_data = load_json(out / "report-data.json")
            required = report_files(report_data)
            for name in required:
                if name == "report-manifest.json":
                    continue
                path, record = out / name, artifacts.get(name)
                if not path.is_file() or not isinstance(record, dict) or record.get("sha256") != sha256_file(path):
                    errors.append("DELIVERY_COPIED_BYTES_INVALID:" + name)
            if report_data.get('report_package_stage_c'):
                for name in ('report.md', 'report-findings.csv'):
                    if name not in required and (out / name).exists():
                        errors.append('DELIVERY_UNDECLARED_EXPORT:' + name)
                for record in manifest.get('material_files', []):
                    from report_estimate import _resolve
                    path = _resolve(out, record['path'])
                    if not path.is_file() or sha256_file(path) != record['sha256']:
                        errors.append('DELIVERY_MATERIAL_MISSING_OR_CHANGED:' + record['path'])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append("DELIVERY_TRANSACTION_CHECK_ERROR:" + type(exc).__name__)
    return errors


def validate_delivery(task_dir, output_dir, *, first_review, second_review, adjudication,
                      require_receipt=True, validation_context=None):
    """Recompute the canonical report and bind it to current source/review bytes.

    No auth, network, writes, or saved-complete shortcuts. Standalone completion
    consumers call this and verify the publication receipt. Publication itself
    runs the same semantic validation on staging, then uses the transaction check
    above after copying the already validated bytes.
    """
    from report_estimate import validate_run
    source, out = Path(task_dir).resolve(), Path(output_dir).resolve()
    try:
        output_task = ensure_object(load_json(out / "task.json"), "output task")
        current_task = ensure_object(load_json(source / "task.json"), "source task")
        if output_task.get("task_id") != current_task.get("task_id"):
            return ["DELIVERY_TASK_ID_MISMATCH"]
        if Path(output_task.get("outputs", {}).get("assessment_input_dir", "")).resolve() != source:
            return ["DELIVERY_SOURCE_MISMATCH"]
        reviews = {"first": load_json(first_review), "second": load_json(second_review),
                   "adjudication": load_json(adjudication) if adjudication else None}
        assessment = load_json(out / "assessment.json")
        if assessment.get("review", {}).get("input_reviews") != reviews:
            return ["DELIVERY_REVIEW_INPUTS_CHANGED"]
        if validation_context is None:
            errors = validate_run(source, output_task, output_dir=out)
        else:
            from delivery_validation import require
            errors = require(validation_context).verify(out, source=source, reviews={
                'first_review': first_review, 'second_review': second_review, 'adjudication': adjudication})
        if require_receipt:
            receipt = ensure_object(load_json(out / "delivery-validation.json"), "delivery receipt")
            if receipt.get("schema") not in {"IPR-DELIVERY-VALIDATION/1.0", "IPR-DELIVERY-VALIDATION/1.1"}:
                errors.append("DELIVERY_RECEIPT_SCHEMA_INVALID")
            if receipt.get("errors") != [] or receipt.get("manifest_sha256") != sha256_file(out / "report-manifest.json"):
                errors.append("DELIVERY_RECEIPT_INVALID")
            if receipt.get("delivery_input_sha256") != delivery_inputs(source, first_review, second_review, adjudication):
                errors.append("DELIVERY_INPUTS_CHANGED")
            if receipt.get("review_bundle_sha256") != sha256_json(reviews):
                errors.append("DELIVERY_REVIEWS_CHANGED")
            if receipt.get("schema") == "IPR-DELIVERY-VALIDATION/1.1" and receipt.get("optional_input_hashes") != optional_inputs(source):
                errors.append("DELIVERY_OPTIONAL_INPUTS_CHANGED")
            data = load_json(out / 'report-data.json')
            if data.get('report_package_stage_c'):
                from report_package_stage_c import report_files
                if receipt.get('required_artifacts') != report_files(data):
                    errors.append('DELIVERY_REQUIRED_ARTIFACTS_CHANGED')
        return errors
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Never reflect source contents or configuration values into hook logs.
        return ["DELIVERY_CHECK_ERROR:" + type(exc).__name__]


def workflow_stage(view, packet, *, first_review, second_review, adjudication,
                   output_dir, task_dir=None, validation_errors=None, validation_context=None):
    # External access/user-information limitations may be delivered as
    # evidence-report limitations after both reviews.  The authoritative
    # publication gate in necessary_completion validates their evidence and
    # scope.  Unknown submissions remain executable-integrity blockers.
    unresolved_submission = [e for e in packet["waiting"] if e.get("state") == "submission_unknown"]
    failure_limits = False
    if task_dir is not None:
        from completion_policy import failure_limits_enabled
        failure_limits = failure_limits_enabled(load_json(Path(task_dir) / "task.json"))
    if view.get("active_pauses") or (view.get("technical_stops") and not failure_limits):
        # failure-limits-v1: a technical stop is a disclosed limitation candidate, so review and
        # publication continue; the publication gate decides whether the stop is a valid limit.
        return "investigation"
    if packet["source"] or packet["agent"] or packet["repair"] or unresolved_submission:
        return "investigation"
    if packet["review"]:
        return "independent_review"

    def recorded(path):
        if path is None or not Path(path).is_file():
            return False
        try:
            context = ensure_object(load_json(path), "review").get("review_context", {})
            return bool(context.get("evidence_digest") and context.get("session_id"))
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    if not recorded(first_review) or not recorded(second_review):
        return "independent_review"
    if not recorded(adjudication):
        return "adjudication"
    artifacts = ARTIFACTS
    if output_dir is not None and (Path(output_dir) / "report-data.json").is_file():
        try:
            from report_package_stage_c import report_files
            artifacts = (*report_files(load_json(Path(output_dir) / "report-data.json")), "delivery-validation.json")
        except (ValueError, OSError, TypeError, KeyError):
            return "validation"
    if output_dir is None or not all((Path(output_dir) / name).is_file() for name in artifacts):
        return "publication"
    validation_options = {'validation_context': validation_context} if validation_context is not None else {}
    errors = ["TASK_DIRECTORY_REQUIRED"] if task_dir is None else validate_delivery(task_dir, output_dir,
        first_review=first_review, second_review=second_review, adjudication=adjudication, **validation_options)
    if errors:
        if validation_errors is not None:
            validation_errors.extend(errors)
        return "validation"
    data = load_json(Path(output_dir) / "report-data.json")
    if data.get("publication", {}).get("delivery_status") != "completed":
        return "validation"
    from delivery_versions_stage_e import enabled as versions_enabled, entry_errors
    if versions_enabled(load_json(Path(task_dir) / "task.json")):
        errors = entry_errors(task_dir, output_dir)
        if errors:
            if validation_errors is not None: validation_errors.extend(errors)
            return "delivery"
        business = data.get("business_status_stage_b", {}).get("business_status")
        if business == "limited_round_closed":
            return "limited_round_closed"
        if (business == "awaiting_dependency" and data.get("publication", {}).get("mode") == "evidence"):
            # Canonical publication and the actual entry were verified above.
            # Closing this evidence delivery does not close its business obligations.
            return "limited_round_closed"
        if business != "business_complete":
            if validation_errors is not None: validation_errors.append("CURRENT_BUSINESS_OBLIGATIONS_NOT_COMPLETE")
            return "validation"
    return "complete"


def check_completion(task_dir, *, first_review=None, second_review=None, adjudication=None, output_dir=None,
                     validation_context=None):
    from advance_work import actionable_packet, action_card, progress_digest
    from workflow_v24 import work_view_from_dir
    source = Path(task_dir).resolve()
    task = ensure_object(load_json(source / "task.json"), "task")
    if task.get("execution_policy_revision") not in {"continuous-work-v1", "continuous-work-v2"}:
        raise ValueError("EXPLICIT_HISTORICAL_RESUME_REQUIRED")
    paths = review_paths(source, first_review, second_review, adjudication)
    first, second, chief = paths
    base = {"schema": "IPR-COMPLETION-CHECK/1.0", "task_id": task["task_id"], "task_dir": str(source)}
    if not (source / "search-plan.json").is_file() and (task.get('product_scope_revision') or task.get('product_scope_required')):
        view=work_view_from_dir(source); packet=actionable_packet(view)
        waiting=packet['waiting']; active=any(packet[k] for k in ('source','agent','repair','review'))
        return base|{'status':'user_paused' if view.get('active_pauses') and not active else
            'execution_stopped' if view.get('technical_stops') and not active else
            'awaiting_user' if waiting and not active else 'continue','stage':'setup',
            'reasons':['PRODUCT_SCOPE_PENDING'],'work_view':view,
            'next_actions':[action_card(source,e) for k in ('agent','repair') for e in packet[k]],
            'progress_digest':progress_digest(source,*paths)}
    if not (source / "search-plan.json").is_file():
        return base | {"status": "continue", "stage": "setup", "reasons": ["SEARCH_PLAN_NOT_CREATED"],
            "progress_digest": progress_digest(source, *paths), "next_actions": [
                {"action": "Complete credentials preflight, product capture/analysis and generate_search_plan.py; preserve auth-first order."}]}
    view = work_view_from_dir(source, first_review=load_json(first) if first.is_file() else None,
                             second_review=load_json(second) if second.is_file() else None)
    packet = actionable_packet(view)
    errors = []
    stage = workflow_stage(view, packet, first_review=first, second_review=second,
                           adjudication=chief, output_dir=output_dir, task_dir=source, validation_errors=errors,
                           validation_context=validation_context)
    executable = any(packet[key] for key in ("source", "agent", "repair", "review"))
    waiting = [e for e in packet["waiting"] if e.get("state") in {"awaiting_access", "awaiting_user"}]
    unknown = any(e.get("state") == "submission_unknown" for e in packet["waiting"])
    paused = view.get("active_pauses", [])
    stopped = view.get("technical_stops", [])
    from completion_policy import failure_limits_enabled
    limits_on = failure_limits_enabled(task)
    # With failure-limits-v1 a stop or access wait only ends the round while investigation itself
    # is what remains; once reviews/adjudication/publication are the next steps they must run.
    later_stage = limits_on and stage in {"adjudication", "publication", "delivery", "validation"}
    status = ("limited_round_closed" if stage == "limited_round_closed" else "complete" if stage == "complete" else "user_paused" if paused and not executable
              else "execution_stopped" if stopped and not executable and not later_stage else
              "awaiting_user" if waiting and not executable and not unknown and not later_stage else "continue")
    from execution_budget import snapshot as budget_snapshot
    runtime_budget = budget_snapshot(source)
    if runtime_budget:
        base['execution_budget'] = runtime_budget
        exhausted_source = runtime_budget['stop_reason'] and (bool(packet['source']) or
            (not any(packet[key] for key in ('agent', 'repair', 'review')) and stage == 'investigation'))
        exhausted_review = runtime_budget['review_remaining_seconds'] <= 0 and stage == 'independent_review'
        if status == 'continue' and (exhausted_source or exhausted_review):
            status = 'execution_stopped'
            base['budget_stop_reason'] = runtime_budget['stop_reason'] or 'EXECUTION_TIME_BUDGET_EXHAUSTED'
    actions = [{"action": "execute_ready_source", "query_id": e.get("query_id"), "provider": e.get("provider")}
               for e in packet["source"]]
    actions += [action_card(source, e) for key in ("agent", "repair", "review") for e in packet[key]]
    if not actions and stage not in {"complete", "limited_round_closed"}:
        actions = [{"action": {"independent_review": "Write both independent reviews against the current frozen digest.",
            "adjudication": "Write evidence-bound adjudication.json.",
            "delivery": "Use delivery_versions_stage_e.py --action deliver with the frozen version and a NEW explicit local destination; recheck actual entry before completion.",
            "publication": "Publish with publish_report.py --mode auto --output-dir NEW_BUILD --deliver-to NEW_ENTRY --require-complete (new directories), then run completion_check.py --output-dir NEW_ENTRY.",
            "validation": "Diagnose independent validation failure; do not edit receipts to bypass it.",
            "investigation": "Resolve the recorded user/access/unknown-submission obligations; do not blindly retry submissions."}[stage]}]
    if paused:
        actions.append({"action": "reconcile_and_explicitly_resume_paused_scope", "pauses": paused})
    if stopped:
        actions.append({"action": "retain_incomplete_and_reopen_only_with_new_repair_evidence", "stops": stopped})
    if base.get('budget_stop_reason'):
        actions = [{'action': 'retain_incomplete_results_and_budget_reason; do not automatically restart',
                    'reason': base['budget_stop_reason']}]
    return base | {"status": status, "stage": stage, "progress_digest": progress_digest(source, *paths),
        "reasons": [] if stage == "complete" else ["WORKFLOW_" + stage.upper()],
        "validation_errors": errors,
        "counts": view.get("counts", {}), "next_actions": actions, "waiting": waiting,
        "active_pauses": paused, "technical_stops": stopped,
        "per_work_progress": view.get("per_work_progress", []),
        "business_completion": "incomplete" if stage == "limited_round_closed" else "complete" if stage == "complete" else "not_claimed",
        "report": str(Path(output_dir).resolve() / "report.html") if stage in {"complete", "limited_round_closed"} else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    for name in ("first-review", "second-review", "adjudication", "output-dir"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    try:
        result = check_completion(**vars(args))
    except Exception as exc:
        result = {"status": "error", "reasons": ["COMPLETION_CHECK_ERROR:" + type(exc).__name__]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] in {"complete", "limited_round_closed"} else 3 if result["status"] == "error" else 2)


if __name__ == "__main__":
    main()
