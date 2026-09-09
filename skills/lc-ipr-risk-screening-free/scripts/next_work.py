#!/usr/bin/env python3
"""Print the current necessary-work view without changing the task or its evidence."""
import argparse
import json
from pathlib import Path
from workflow_v24 import work_view_from_dir
from common import load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--first-review", type=Path)
    parser.add_argument("--second-review", type=Path)
    args = parser.parse_args()
    print(json.dumps(work_view_from_dir(args.task_dir.resolve(),
        first_review=load_json(args.first_review) if args.first_review else None,
        second_review=load_json(args.second_review) if args.second_review else None), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
