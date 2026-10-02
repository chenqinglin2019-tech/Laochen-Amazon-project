#!/usr/bin/env python3
"""Append one reviewed, incremental candidate handoff batch."""
import argparse
import json
from pathlib import Path

from common import load_json
from candidate_handoff import record_batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    event = record_batch(args.task_dir, load_json(args.input))
    print(json.dumps({"batch_id": event["batch_id"],
                      "candidate_ids": [row["candidate_id"] for row in event["candidates"]]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
