#!/usr/bin/env python3
"""Create or independently validate a preliminary stage result for a 09D task."""
import argparse
import json
from pathlib import Path

from stage_delivery_stage_d import create_output, validate_output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--correction-id")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        errors = validate_output(args.task_dir, args.output_dir)
        print(json.dumps({"status": "passed" if not errors else "failed", "errors": errors}, ensure_ascii=False))
        if errors:
            raise SystemExit(1)
    else:
        print(json.dumps(create_output(args.task_dir, args.output_dir, correction_id=args.correction_id), ensure_ascii=False))


if __name__ == "__main__":
    main()
