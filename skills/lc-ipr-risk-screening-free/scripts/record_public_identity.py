#!/usr/bin/env python3
"""Record bounded identity investigation of a retained public Lens sales lead."""
import argparse
import json
from pathlib import Path
from common import load_json, print_recorded
from public_identity import record

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir',type=Path,required=True)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument("--verbose", action="store_true",
                        help="Print the complete stored record (default: ids, states and short fields only)")
    args = parser.parse_args()
    print_recorded(record(args.task_dir, load_json(args.input)), verbose=args.verbose)

if __name__ == '__main__':
    main()
