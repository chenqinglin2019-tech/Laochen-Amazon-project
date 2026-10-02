#!/usr/bin/env python3
"""Append an 08B recovery or unknown-submission audit; never call a source."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_json
from recovery_stage_b import record_review, record_failure_closeout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True,
        help="Audit JSON; operator failure_closeout binds receipt_disposition and failure_review atomically; v3 failures may use explicit no-retry")
    args = parser.parse_args()
    request = load_json(args.input)
    if not isinstance(request, dict):
        raise ValueError("RECOVERY_REVIEW_INPUT_INVALID")
    if request.get('kind') == 'failure_closeout':
        if set(request) - {'kind', 'source_run_id', 'source_run_sha256', 'receipt_disposition', 'failure_review'}:
            raise ValueError('RECOVERY_FAILURE_CLOSEOUT_INPUT_INVALID')
        result = record_failure_closeout(args.task_dir.resolve(), source_run_id=request.get('source_run_id'),
            source_run_sha256=request.get('source_run_sha256'), receipt_disposition=request.get('receipt_disposition'),
            failure_review=request.get('failure_review'))
    else:
        result = record_review(args.task_dir.resolve(), request)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
