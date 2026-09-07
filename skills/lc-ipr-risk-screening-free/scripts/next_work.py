#!/usr/bin/env python3
"""Print the current necessary-work view without changing the task or its evidence."""
import argparse
import json
from pathlib import Path
from workflow_v24 import work_view_from_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(work_view_from_dir(args.task_dir.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
