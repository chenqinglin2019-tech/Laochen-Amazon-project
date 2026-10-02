#!/usr/bin/env python3
"""Append a reviewed module-07 factual event to the current task."""
import argparse
import json
from pathlib import Path

from common import load_json, print_recorded
from distinctive_rights import record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--verbose", action="store_true",
                        help="Print the complete stored record (default: ids, states and short fields only)")
    args = parser.parse_args()
    request = load_json(args.input.expanduser().resolve())
    if not isinstance(request, dict):
        raise ValueError("M07_INPUT_OBJECT_REQUIRED")
    print_recorded(record(args.task_dir.expanduser().resolve(), request), verbose=args.verbose)


if __name__ == "__main__":
    main()
