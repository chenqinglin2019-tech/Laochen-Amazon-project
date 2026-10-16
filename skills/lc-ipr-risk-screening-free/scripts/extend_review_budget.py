#!/usr/bin/env python3
"""Owner-only: add final-review allowance to a task whose review budget is spent.

The execution budget is a loop guard for the agent, and an interrupted or failed review is charged in full and
never refunded. When the owner decides that a task which already holds most of its work (for example five of
six module judgments and their audits) deserves one more bounded pass, this tool APPENDS an allowance record
to the budget journal. It never clears or lowers a counter, never changes the policy hash, and is capped:
at most 1800 s in total and three records per task.

It refuses to run outside an interactive terminal and asks for a typed confirmation, so an automated agent
cannot grant itself time; run it yourself, for example from a terminal (or with "!" in the Codex prompt).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_file
from execution_lock import execution_lock
import execution_budget as budget


def extend(task_dir, seconds, reason):
    """Append one allowance record; returns the new snapshot. Raises ValueError with a stable code."""
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / 'task.json')
    limits = budget.policy(task)
    if limits is None:
        raise ValueError('EXTEND_BUDGET_TASK_HAS_NO_BUDGET')
    if type(seconds) is not int or not 60 <= seconds <= budget.MAX_EXTENSION_SECONDS:
        raise ValueError('EXTEND_BUDGET_SECONDS_OUT_OF_RANGE')
    if not isinstance(reason, str) or len(reason.strip()) < 8:
        raise ValueError('EXTEND_BUDGET_REASON_REQUIRED')
    with execution_lock(task_dir, 'budget'):
        data = budget._read(task_dir, task, limits)
        if data.get('active'):
            raise ValueError('EXTEND_BUDGET_LEASE_ACTIVE')
        rows = list(data.get('review_extensions', []))
        if len(rows) >= budget.MAX_EXTENSIONS:
            raise ValueError('EXTEND_BUDGET_RECORD_LIMIT_REACHED')
        if budget.extension_seconds(data) + seconds > budget.MAX_EXTENSION_SECONDS:
            raise ValueError('EXTEND_BUDGET_TOTAL_LIMIT_REACHED')
        journal = task_dir / budget.JOURNAL
        rows.append({'seconds': seconds, 'reason': reason.strip(), 'at': now_iso(), 'actor': 'owner-terminal',
            'review_used_seconds_before': round(float(data['review_used_seconds']), 3),
            'used_seconds_before': round(float(data['used_seconds']), 3),
            'review_invocations_before': int(data.get('review_invocations', 0)),
            'journal_sha256_before': sha256_file(journal) if journal.is_file() else None})
        data['review_extensions'] = rows
        atomic_write_json(journal, data)
    return budget.snapshot(task_dir)


def main(argv=None, *, interactive=None, ask=input):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--add-seconds', type=int, required=True,
        help='Allowance to add, 60..1800 seconds (all records of one task together never exceed 1800)')
    parser.add_argument('--reason', required=True, help='Why one more bounded review pass is justified (recorded)')
    args = parser.parse_args(argv)
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    command = 'python scripts/extend_review_budget.py --task-dir "%s" --add-seconds %d --reason "%s"' % (
        args.task_dir, args.add_seconds, args.reason)
    if not interactive:
        print('REFUSED: this tool only runs in an interactive terminal operated by the task owner.\n'
              'Run the same command yourself in a terminal (in the Codex prompt: "! " followed by the command):\n  '
              + command, file=sys.stderr)
        return 2
    task = load_json(args.task_dir.resolve() / 'task.json')
    try:
        before = budget.snapshot(args.task_dir)
    except ValueError as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        return 1
    if before is None:
        print('REFUSED: EXTEND_BUDGET_TASK_HAS_NO_BUDGET', file=sys.stderr)
        return 1
    phrase = 'EXTEND %s %d' % (task['task_id'], args.add_seconds)
    print('Task %s: review allowance left %.0f s, source time left %.0f s, extension so far %s s.' % (
        task['task_id'], before['review_remaining_seconds'], before['remaining_seconds'],
        before.get('review_extension_seconds', 0)))
    print('This adds %d s of final-review allowance. No counter is reset and no review is rewritten.' % args.add_seconds)
    typed = ask('Type exactly "%s" to confirm: ' % phrase).strip()
    if typed != phrase:
        print('REFUSED: confirmation text did not match.', file=sys.stderr)
        return 1
    try:
        after = extend(args.task_dir, args.add_seconds, args.reason)
    except ValueError as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        return 1
    print('Review allowance left now: %.0f s (extension total %s s).' % (
        after['review_remaining_seconds'], after.get('review_extension_seconds', 0)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
