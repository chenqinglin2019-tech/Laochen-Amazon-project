#!/usr/bin/env python3
"""Append one 09A event or an atomic complete_query_batch with per-query proofs."""
import argparse
import json
from pathlib import Path

from common import load_json, print_recorded
from review_progress_stage_a import record_event, record_query_completions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True,
        help="Single append-only event JSON or complete_query_batch with original query proofs. New operating tasks accept hash-bound effective submission audits and verified exact zero receipts; failures remain incomplete.")
    parser.add_argument("--verbose", action="store_true",
                        help="Print the complete stored record (default: ids, states and short fields only)")
    args = parser.parse_args()
    request = load_json(args.input)
    if isinstance(request,dict) and request.get('kind') == 'complete_query_batch':
        if set(request) != {'kind','completions'}:
            raise ValueError('REVIEW_PROGRESS_BATCH_INPUT_INVALID')
        result = record_query_completions(args.task_dir,request['completions'])
    else:
        result = record_event(args.task_dir,request)
    print_recorded(result, verbose=args.verbose)


if __name__ == "__main__":
    main()
