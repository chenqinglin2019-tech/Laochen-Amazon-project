#!/usr/bin/env python3
"""Append a 09C freeze, independent review or chief adjudication to one task."""
import argparse
import json
from pathlib import Path

from common import atomic_write_json, load_json
from stage_review_stage_c import export_batch_input, record_event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--export-batch")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.export_batch:
        if args.input or not args.output:
            parser.error("--export-batch requires --output and excludes --input")
        value = export_batch_input(args.task_dir, args.export_batch)
        atomic_write_json(args.output, value)
        print(json.dumps({"output": str(args.output), "evidence_digest": value["evidence_digest"]}, ensure_ascii=False))
        return
    if not args.input or args.output:
        parser.error("recording requires --input and excludes --output")
    print(json.dumps(record_event(args.task_dir, load_json(args.input)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
