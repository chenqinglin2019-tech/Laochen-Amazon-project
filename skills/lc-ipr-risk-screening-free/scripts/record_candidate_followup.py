#!/usr/bin/env python3
"""Bind a candidate follow-up to a discovery request or review its result."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from candidate_followup import record_binding, record_review
from common import load_json, print_recorded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=("bind-discovery", "review-result"))
    parser.add_argument("--verbose", action="store_true",
                        help="Print the complete stored record (default: ids, states and short fields only)")
    args = parser.parse_args()
    request = load_json(args.input.expanduser().resolve())
    if not isinstance(request, dict):
        raise ValueError("FOLLOWUP_INPUT_OBJECT_REQUIRED")
    task_dir = args.task_dir.expanduser().resolve()
    result = (record_binding if args.kind == "bind-discovery" else record_review)(task_dir, request)
    print_recorded(result, verbose=args.verbose)


if __name__ == "__main__":
    main()
