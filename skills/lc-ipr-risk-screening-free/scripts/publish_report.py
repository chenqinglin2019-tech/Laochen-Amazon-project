#!/usr/bin/env python3
"""Publish from one verified calculation, then independently validate the bundle."""
from __future__ import annotations

import argparse
from pathlib import Path

from common import ensure_object, load_json
from assessment_estimate import POLICY, finalize
from runtime_timing import timed_cli


def publish(task_dir, first_review, second_review, *, output_dir=None,
            adjudication=None, supplement=None, evidence_root=None, report_content=None,
            assessment_policy=None, mode=None, stop_reason=None):
    source = Path(task_dir).resolve()
    destination = Path(output_dir).resolve() if output_dir else source
    task = ensure_object(load_json(source / "task.json"), "task.json")
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
    context = finalize(source, task, first_review, second_review,
        adjudication_path=adjudication, supplement_path=supplement, evidence_root=evidence_root,
        output_dir=destination, return_context=True, publication_mode=mode, stop_reason=stop_reason)
    from report_estimate import build_bundle_from_verified_context, validate_run
    data, manifest = build_bundle_from_verified_context(context, task_dir=source,
        output_dir=destination, report_content=content)
    errors = validate_run(source, context.output_task, output_dir=destination)
    if errors:
        raise ValueError("PUBLISHED_REPORT_VALIDATION_FAILED: " + "; ".join(errors))
    return {"file_integrity": "valid", "business_completion": data["overall"].get("business_completion"),
        "status": context.assessment["status"], "report": str(destination / "report.html"),
        "manifest": str(destination / "report-manifest.json"), "manifest_digest": manifest["content_digest"]}


@timed_cli("report_publish")
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--first-review", type=Path, required=True)
    parser.add_argument("--second-review", type=Path, required=True)
    parser.add_argument("--assessment-policy", choices=(POLICY,))
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--supplement", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--report-content", type=Path)
    parser.add_argument("--mode", choices=("final", "stage"))
    parser.add_argument("--stop-reason")
    args = parser.parse_args()
    result = publish(args.task_dir, args.first_review, args.second_review,
        assessment_policy=args.assessment_policy, adjudication=args.adjudication,
        supplement=args.supplement, evidence_root=args.evidence_root,
        output_dir=args.output_dir, report_content=args.report_content,
        mode=args.mode, stop_reason=args.stop_reason)
    print("file_integrity: valid; business_completion: " + str(result["business_completion"]))
    print(result["report"])


if __name__ == "__main__":
    main()
