#!/usr/bin/env python3
"""Publish from one verified calculation, then independently validate the bundle."""
from __future__ import annotations

import argparse
from pathlib import Path

from common import atomic_write_json, ensure_object, load_json, now_iso, sha256_file, sha256_json
from assessment_estimate import POLICY, finalize
from runtime_timing import timed_cli, timed_step
from completion_check import delivery_inputs, optional_inputs, validate_delivery_transaction


def _assert_review_pair_current(task_dir, first_review, second_review, *, assessment_revision=None):
    """Fail before creating build records if either review predates live inputs."""
    from workflow_v24 import _scenario_context, scenario_supplement
    from assessment_estimate import review_digest
    task = load_json(Path(task_dir) / "task.json")
    digest_task = dict(task)
    if assessment_revision is not None:
        if task.get("assessment_revision") not in (None, assessment_revision):
            raise ValueError("ASSESSMENT_REVISION_CONFLICT")
        digest_task["assessment_revision"] = assessment_revision
    candidates, ledger, evidence = _scenario_context(Path(task_dir), task)
    plan = load_json(Path(task_dir) / "search-plan.json")
    supplement = scenario_supplement(Path(task_dir), task=digest_task, evidence=evidence)
    current = review_digest(evidence, candidates, ledger, plan, digest_task, supplement)
    for label, path in (("first", first_review), ("second", second_review)):
        review = ensure_object(load_json(Path(path)), label + " review")
        context = review.get("review_context")
        if not isinstance(context, dict) or context.get("evidence_digest") != current:
            raise ValueError("REPORT_REVIEW_INPUT_CHANGED: " + label)
    return current


def _publish_local(task_dir, first_review, second_review, *, output_dir=None,
            adjudication=None, supplement=None, evidence_root=None, report_content=None,
            assessment_policy=None, assessment_revision=None, mode=None, stop_reason=None,
            validation_context=None):
    source = Path(task_dir).resolve()
    destination = Path(output_dir).resolve() if output_dir else source
    task = ensure_object(load_json(source / "task.json"), "task.json")
    delivery_input_sha256 = delivery_inputs(source, first_review, second_review, adjudication)
    optional_input_hashes = optional_inputs(source)
    if task.get("assessment_policy") not in (None, POLICY):
        raise ValueError("REPORT_TASK_POLICY_CONFLICT")
    if (assessment_policy or task.get("assessment_policy")) != POLICY:
        raise ValueError("PUBLISH_EVIDENCE_ESTIMATE_POLICY_REQUIRED")
    if task.get("assessment_policy") is None and destination == source:
        raise ValueError("HISTORICAL_REASSESSMENT_REQUIRES_NEW_OUTPUT_DIRECTORY")
    material_outputs = ("assessment.json", "report.html", "report.md", "report-data.json",
                        "report-findings.csv", "report-manifest.json")
    if any((destination / name).exists() for name in material_outputs) or (
            destination != source and (destination / "task.json").exists()):
        raise ValueError("PUBLISH_OUTPUT_ALREADY_EXISTS: choose a new output directory")
    task = {**task, "assessment_policy": POLICY}
    content = ensure_object(load_json(Path(report_content)), "report content") if report_content is not None else None
    with timed_step(source if task.get('presentation_policy_revision') == 'operator-report-v1' else None,
                    'assessment_and_publication_preflight'):
        context = finalize(source, task, first_review, second_review,
            adjudication_path=adjudication, supplement_path=supplement, evidence_root=evidence_root,
            output_dir=destination, return_context=True, publication_mode=mode, stop_reason=stop_reason,
            assessment_revision=assessment_revision)
    from report_estimate import build_bundle_from_verified_context
    with timed_step(destination, 'report_render_and_bundle'):
        data, manifest = build_bundle_from_verified_context(context, task_dir=source,
            output_dir=destination, report_content=content,
            **({'validation_context': validation_context} if validation_context is not None else {}))
    errors = validate_delivery_transaction(source, destination, first_review=first_review,
        second_review=second_review, adjudication=adjudication,
        expected_delivery_input_sha256=delivery_input_sha256,
        expected_optional_inputs=optional_input_hashes)
    if errors:
        raise ValueError("PUBLISHED_REPORT_VALIDATION_FAILED: " + "; ".join(errors))
    from report_package_stage_c import report_files
    atomic_write_json(destination / "delivery-validation.json", {
        "schema": "IPR-DELIVERY-VALIDATION/1.1", "validated_at": now_iso(),
        "optional_input_hashes": optional_input_hashes,
        "source_task_sha256": sha256_json(task), "manifest_sha256": sha256_file(destination / "report-manifest.json"),
        "delivery_input_sha256": delivery_input_sha256,
        "review_bundle_sha256": sha256_json({"first": load_json(first_review), "second": load_json(second_review),
                                             "adjudication": load_json(adjudication) if adjudication else None}),
        "errors": [], "required_artifacts": report_files(data),
    })
    from delivery_inspection_stage_d import enabled as inspection_enabled, inspect as independent_inspect
    if inspection_enabled(task):
        inspection = independent_inspect(source, destination, first_review=first_review,
            second_review=second_review, adjudication=adjudication,
            **({'validation_context': validation_context} if validation_context is not None else {}))
        atomic_write_json(destination / "delivery-inspection.json", inspection)
        if inspection["errors"]:
            raise ValueError("DELIVERY_INDEPENDENT_INSPECTION_FAILED:" + ";".join(inspection["errors"]))
    from codex_guard import update_bound_paths
    update_bound_paths(source, output_dir=destination, first_review=first_review,
                       second_review=second_review, adjudication=adjudication)
    return {"file_integrity": "valid", "business_completion": data["overall"].get("business_completion"),
        **({"delivery_status": "partial" if data["publication"]["mode"] == "stage" else "completed", "publication_mode": data["publication"]["mode"]}
           if data.get("publication", {}).get("delivery_status") else {}),
        "status": context.assessment["status"], "report": str(destination / "report.html"),
        "manifest": str(destination / "report-manifest.json"), "manifest_digest": manifest["content_digest"]}


def publish(task_dir, first_review, second_review, **options):
    from delivery_versions_stage_e import enabled, begin_build, finish_build, fail_build
    source = Path(task_dir).resolve()
    deliver_to = options.pop('deliver_to', None)
    require_complete = options.pop('require_complete', False)
    if require_complete and deliver_to is None:
        raise ValueError('DELIVERY_TRANSACTION_DESTINATION_REQUIRED')
    # The review pair is the only input that may authorize a report. Validate it
    # before begin_build writes any delivery journal entry; publication itself
    # then reads the frozen task inputs and writes only to a new output directory.
    _assert_review_pair_current(source, first_review, second_review,
                                assessment_revision=options.get("assessment_revision"))
    if not enabled(load_json(source / "task.json")):
        if deliver_to is not None or require_complete:
            raise ValueError('DELIVERY_TRANSACTION_VERSIONED_TASK_REQUIRED')
        if options.pop("correction_id", None):
            raise ValueError("DELIVERY_CORRECTION_NEW_TASK_REQUIRED")
        return _publish_local(task_dir, first_review, second_review, **options)
    correction_id = options.pop("correction_id", None)
    destination = options.get("output_dir")
    if destination is None:
        raise ValueError("DELIVERY_BUILD_NEW_DIRECTORY_REQUIRED")
    validation_context = None
    from delivery_validation import enabled as transaction_enabled, begin as begin_validation
    if transaction_enabled(load_json(source / 'task.json')):
        validation_context = begin_validation(source, first_review=first_review,
            second_review=second_review, adjudication=options.get('adjudication'))
        options['validation_context'] = validation_context
    version_id = begin_build(source, destination, first_review=first_review,
        second_review=second_review, adjudication=options.get("adjudication"), correction_id=correction_id)
    try:
        result = _publish_local(task_dir, first_review, second_review, **options)
        validation_options = {'validation_context': validation_context} if validation_context is not None else {}
        receipt = finish_build(source, version_id, **validation_options)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        fail_build(source, version_id, exc)
        raise
    result = {**result, **receipt, 'build_only': True}
    if validation_context is not None:
        result['validation_transaction'] = validation_context.audit()
    if deliver_to is not None:
        from delivery_versions_stage_e import deliver
        delivery = deliver(source, version_id, deliver_to, **validation_options)
        result.update(delivery, build_only=False)
        if delivery.get('delivery_status') != 'entry_verified':
            raise ValueError('DELIVERY_TRANSACTION_ENTRY_FAILED:' + str(delivery.get('failed_step')))
        result['report'] = delivery['entry']
        # The Stop hook must verify the delivered entry, not the build directory
        # (a build directory has no delivered journal row and can never complete).
        from codex_guard import update_bound_paths
        update_bound_paths(source, output_dir=deliver_to)
        from completion_check import check_completion
        completion = check_completion(source, first_review=first_review, second_review=second_review,
            adjudication=options.get('adjudication'), output_dir=deliver_to, **validation_options)
        atomic_write_json(Path(deliver_to).parent / (Path(deliver_to).name + '-completion.json'), completion)
        result['completion'] = {key: completion.get(key) for key in
                                ('status', 'stage', 'validation_errors', 'business_completion')}
        result['business_completion'] = completion['business_completion']
        if require_complete and completion['status'] not in {'complete', 'limited_round_closed'}:
            raise ValueError('DELIVERY_TRANSACTION_COMPLETION_FAILED:' + completion['status'])
    elif require_complete:
        raise ValueError('DELIVERY_TRANSACTION_DESTINATION_REQUIRED')
    return result


@timed_cli("report_publish")
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--first-review", type=Path, required=True)
    parser.add_argument("--second-review", type=Path, required=True)
    parser.add_argument("--assessment-policy", choices=(POLICY,))
    parser.add_argument("--assessment-revision", choices=("partial-evidence-v1", "partial-evidence-v2", "known-findings-risk-v1"))
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--supplement", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--report-content", type=Path)
    parser.add_argument("--mode", choices=("auto", "final", "evidence", "stage"))
    parser.add_argument("--stop-reason")
    parser.add_argument("--correction-id")
    parser.add_argument('--deliver-to', type=Path,
                        help='Publish, freeze, deliver and check completion in one transaction into a NEW directory.')
    parser.add_argument('--require-complete', action='store_true',
                        help='Require complete or limited_round_closed at the actual delivered entry.')
    args = parser.parse_args()
    result = publish(args.task_dir, args.first_review, args.second_review,
        assessment_policy=args.assessment_policy, assessment_revision=args.assessment_revision, adjudication=args.adjudication,
        supplement=args.supplement, evidence_root=args.evidence_root,
        output_dir=args.output_dir, report_content=args.report_content,
        mode=args.mode, stop_reason=args.stop_reason, correction_id=args.correction_id,
        deliver_to=args.deliver_to, require_complete=args.require_complete)
    print("file_integrity: valid; business_completion: " + str(result["business_completion"]))
    if result.get("delivery_status"):
        print("delivery_status: " + result["delivery_status"] + "; publication_mode: " + result["publication_mode"])
    print(result["report"])
    if result.get('validation_transaction'):
        print('independent_semantic_checks: ' + str(result['validation_transaction']['semantic_checks']))
    if result.get('completion'):
        print('completion_status: ' + result['completion']['status'])


if __name__ == "__main__":
    main()
