#!/usr/bin/env python3
"""Record an 08C pause, reconciliation, resume, or access event without source calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_json, print_recorded
from continuation_stage_c import record_event


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--verbose", action="store_true",
                        help="Print the complete stored record (default: ids, states and short fields only)")
    args = parser.parse_args()
    print_recorded(record_event(args.task_dir, load_json(args.input)), verbose=args.verbose)


if __name__ == "__main__":
    main()
