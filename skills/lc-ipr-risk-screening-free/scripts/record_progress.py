#!/usr/bin/env python3
"""Append one 08D work-round, diagnosis, repair, stop, or reopen event."""
import argparse
import json
from pathlib import Path

from common import load_json, print_recorded
from continuous_progress_stage_d import record_event, record_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--verbose", action="store_true",
                        help="Print the complete stored record (default: ids, states and short fields only)")
    args = parser.parse_args()
    request = load_json(args.input)
    if isinstance(request, dict) and set(request) == {"events"} and isinstance(request["events"], list):
        # {"events": [...]}: all begin or all finish -> one atomic batch; other kinds are applied in order,
        # each validated against the state left by the previous one.
        batch = request["events"]
        kinds = {item.get("kind") for item in batch if isinstance(item, dict)}
        recorded = (record_events(args.task_dir, batch) if len(kinds) == 1 and kinds <= {"begin", "finish"}
                    else [record_event(args.task_dir, item) for item in batch])
        print_recorded({"events": recorded}, verbose=args.verbose)
        return
    print_recorded(record_event(args.task_dir, request), verbose=args.verbose)


if __name__ == "__main__":
    main()
