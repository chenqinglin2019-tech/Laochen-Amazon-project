#!/usr/bin/env python3
"""Record 05C selected handoff, change reopen/review, or duplicate reference."""
import argparse
import json
from pathlib import Path

from common import load_json, print_recorded
from candidate_triage_stage import (record_duplicate_reference, record_reopen,
    record_reopen_review, record_selected_handoff, record_batch_review)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--kind", choices=("batch-review", "selected-handoff", "reopen", "reopen-review", "duplicate-reference"),
                        required=True)
    parser.add_argument("--verbose", action="store_true",
                        help="Print the complete stored record (default: ids, states and short fields only)")
    args = parser.parse_args()
    request = load_json(args.input.expanduser().resolve())
    if not isinstance(request, dict):
        raise ValueError("TRIAGE_STAGE_INPUT_OBJECT_REQUIRED")
    handlers = {"batch-review": record_batch_review, "selected-handoff": record_selected_handoff,
                "reopen": record_reopen,
                "reopen-review": record_reopen_review, "duplicate-reference": record_duplicate_reference}
    result = handlers[args.kind](args.task_dir.expanduser().resolve(), request)
    print_recorded(result, verbose=args.verbose)


if __name__ == "__main__":
    main()
