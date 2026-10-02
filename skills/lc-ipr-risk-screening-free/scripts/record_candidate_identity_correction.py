#!/usr/bin/env python3
"""Append a source-backed candidate identity correction; rerun merge afterward."""
import argparse
import json
from pathlib import Path

from common import load_json
from candidate_identity_corrections import record_correction


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    event = record_correction(args.task_dir, load_json(args.input))
    print(json.dumps({"event_id": event["event_id"], "kind": event["kind"],
                      "rerun": "merge_candidates.py"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
