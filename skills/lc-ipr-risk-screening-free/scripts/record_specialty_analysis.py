#!/usr/bin/env python3
"""Record one specialty event or one atomic events[]/comparison_close request.

Known-findings/operator tasks can share scope/reviewer/reason, refer only to
earlier batch aliases with {"$event":"alias"}, and commit once after validation.
Legacy single-event inputs preserve their original validation and response.
"""
import argparse
import json
from pathlib import Path

from common import load_json, print_recorded
from specialty_analysis import record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True,
        help='JSON: legacy kind event, atomic events[] (optional transaction_id), or kind=comparison_close with actual comparison/gap/followup disposition')
    parser.add_argument("--verbose", action="store_true",
                        help="Print the complete stored record (default: ids, states and short fields only)")
    args = parser.parse_args()
    request = load_json(args.input.expanduser().resolve())
    if not isinstance(request, dict):
        raise ValueError("SPECIALTY_INPUT_OBJECT_REQUIRED")
    print_recorded(record(args.task_dir.expanduser().resolve(), request), verbose=args.verbose)


if __name__ == "__main__":
    main()
