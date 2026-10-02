#!/usr/bin/env python3
"""Review retained result positions or complete patent records; resume parsing without a request."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_json
from source_result_processing import (append_dispositions,
    append_parsed_rows, append_receipt_disposition, append_xml_derivation, append_record_content_review,
    append_processing_batch)
from runtime_timing import timed_cli


@timed_cli('source_material_processing')
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--source-run-id", help="Exact retained run; omit only for events[] batch input")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    payload = load_json(args.input)
    if not isinstance(payload, dict):
        raise ValueError("RESULT_PROCESSING_INPUT_INVALID")
    task_dir = args.task_dir.resolve()
    if 'events' in payload:
        if set(payload) != {'events'} or args.source_run_id:
            raise ValueError('RESULT_PROCESSING_BATCH_INPUT_INVALID')
        print(json.dumps(append_processing_batch(task_dir, payload['events']), ensure_ascii=False))
        return
    if not args.source_run_id:
        parser.error('--source-run-id is required for a single retained response')
    if 'record_content_review' in payload:
        if set(payload) != {'record_content_review'}:
            raise ValueError('RESULT_PROCESSING_RECORD_REVIEW_MUST_BE_SEPARATE')
        result = append_record_content_review(task_dir, args.source_run_id, payload['record_content_review'])
        print(json.dumps(result, ensure_ascii=False))
        return
    if "xml_derivation" in payload:
        if set(payload) != {"xml_derivation"}:
            raise ValueError("RESULT_PROCESSING_XML_DERIVATION_MUST_BE_SEPARATE")
        result = append_xml_derivation(task_dir, args.source_run_id, payload["xml_derivation"])
        print(json.dumps(result, ensure_ascii=False))
        return
    if "parsed_rows" in payload and "decisions" in payload:
        if set(payload) != {'parsed_rows', 'decisions'}:
            raise ValueError('RESULT_PROCESSING_BATCH_INPUT_INVALID')
        result = append_processing_batch(task_dir, [{'source_run_id': args.source_run_id, **payload}])
        print(json.dumps(result, ensure_ascii=False))
        return
    if any(key in payload for key in ("receipt_disposition", "receipt_review")):
        if set(payload) != {"receipt_disposition"}:
            raise ValueError("RESULT_PROCESSING_RECEIPT_REVIEW_MUST_BE_SEPARATE")
        result = append_receipt_disposition(task_dir, args.source_run_id,
                                            payload["receipt_disposition"])
        print(json.dumps(result, ensure_ascii=False))
        return
    task_dir = args.task_dir.resolve()
    if "parsed_rows" in payload:
        append_parsed_rows(task_dir, args.source_run_id, payload["parsed_rows"])
    if "decisions" in payload:
        result = append_dispositions(task_dir, args.source_run_id, payload["decisions"])
    elif "parsed_rows" in payload:
        from source_result_processing import progress
        evidence = load_json(task_dir / "evidence.json")
        run = next(r for r in evidence["source_runs"] if r.get("run_id") == args.source_run_id)
        result = progress(task_dir, run, evidence)
    else:
        raise ValueError("RESULT_PROCESSING_INPUT_EMPTY")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
