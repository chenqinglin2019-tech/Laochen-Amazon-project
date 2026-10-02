#!/usr/bin/env python3
"""Append one 09B reviewed judgment, material invalidation, or signal review."""
import argparse
import json
from pathlib import Path

from common import load_json, print_recorded
from stage_risk_stage_b import record_event, record_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--verbose", action="store_true",
                        help="Print the complete stored record (default: ids, states and short fields only)")
    args = parser.parse_args()
    request = load_json(args.input)
    if isinstance(request, dict) and set(request) == {"events"} and isinstance(request["events"], list):
        # Atomic batch: every event is validated in order against the earlier ones, then one write.
        print_recorded({"events": record_events(args.task_dir, request["events"])}, verbose=args.verbose)
        return
    print_recorded(record_event(args.task_dir, request), verbose=args.verbose)


if __name__ == "__main__":
    main()
