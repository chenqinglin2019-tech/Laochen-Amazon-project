"""The run's time box (new tasks with ``time_box_revision='time-box-v1'``, r5d21, owner decision 2026-10-15).

The owner can wait at most 40 minutes for a task and wants about 30. Two real runs of 2026-10-14 took 86 and 90
minutes of machine time and both then stopped at checkpoint 2 for hand work. Here the pipeline counts its own active
seconds (stage time, never the wait for the owner at checkpoint 1) and:

* stops starting discovery rounds after ``sources_seconds`` and core rounds after ``core_seconds``;
* if work is still open when the readiness check is reached, closes it: every work entry that is still actionable is
  recorded in ``time-box.json`` and the work view shows it as a disclosed limitation (state ``blocked``, reason
  ``TIME_BOX_REACHED``, bound to that record by hash) instead of stopping at checkpoint 2. The final review and the
  report then treat these scopes as unfinished ("已完成部分查询"), never as cleared.

The closure is bound to the exact entries listed when it was written; work that appears later is not covered.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_file, sha256_json

REVISION = 'time-box-v1'
DEFAULTS = {'sources_seconds': 720, 'core_seconds': 1320, 'review_session_seconds': 900}
RECORD = 'time-box.json'
REASON = 'TIME_BOX_REACHED'
ACTIONABLE = ('ready', 'awaiting_review', 'submission_unknown')
LIMITATION_KIND = 'time_box'
REASONING = ('本轮时间预算已用完，本项未完成，风险待定；这是本轮的执行限制，不代表来源没有结果或已排除风险，'
             '需要时可在新一轮继续。')


def enabled(task) -> bool:
    return isinstance(task, dict) and task.get('time_box_revision') == REVISION


def policy(task) -> dict | None:
    if not enabled(task):
        return None
    configured = task.get('time_box') if isinstance(task.get('time_box'), dict) else {}
    return {key: int(configured.get(key) or value) for key, value in DEFAULTS.items()}


def record(task_dir) -> dict | None:
    path = Path(task_dir) / RECORD
    if not path.is_file():
        return None
    try:
        data = load_json(path)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get('revision') == REVISION else None


UNESTABLISHED = ('blocked', 'awaiting_access')


def close(task_dir, task, entries, *, active_seconds, why, unestablished=(), keep=()) -> dict:
    """Write the closure for the still-actionable entries of the current work view, plus the blocked entries the
    publication gate named as limitations that are not established (``unestablished`` work ids). ``keep`` (r6) carries
    the work ids of an earlier closure of the same task into this one."""
    unestablished = set(unestablished)
    work = sorted({entry['work_id'] for entry in entries if isinstance(entry, dict) and entry.get('work_id')
                   and (entry.get('underlying_state', entry.get('state')) in ACTIONABLE
                        or (entry['work_id'] in unestablished and entry.get('state') in UNESTABLISHED))}
                  | {work_id for work_id in keep if isinstance(work_id, str)})
    data = {'schema': 'IPR-TIME-BOX/1.0', 'revision': REVISION, 'task_id': task.get('task_id'), 'closed_at': now_iso(),
            'active_seconds': round(float(active_seconds or 0), 1), 'policy': policy(task), 'why': why,
            'work_ids': work}
    atomic_write_json(Path(task_dir) / RECORD, data)
    return data


def limitation(task, entry, task_dir) -> dict | None:
    """The disclosed limitation a closed time box gives one still-actionable work entry, or None."""
    if task_dir is None or not enabled(task) or not isinstance(entry, dict) or entry.get('integrity_failure'):
        return None
    if entry.get('underlying_state', entry.get('state')) not in ACTIONABLE + UNESTABLISHED:
        return None
    data = record(task_dir)
    if data is None or data.get('task_id') != task.get('task_id') or entry.get('work_id') not in data.get('work_ids', []):
        return None
    import portable
    plan_path = Path(task_dir) / 'search-plan.json'
    try:
        plan = load_json(plan_path) if portable.enabled(task) and plan_path.is_file() else None
    except (OSError, ValueError):
        plan = None
    language_gap = portable.language_limitation(task, entry, plan)
    return {**deepcopy(entry), 'state': 'blocked', 'reason': REASON, 'limitation_kind': LIMITATION_KIND,
            **({'limitation_detail': portable.LIMITATION_CODE} if language_gap else {}),
            'source_query_performed': entry.get('kind') != 'source_lookup',
            'official_verification': 'not_verified',
            'budget_proof': {'revision': REVISION, 'task_id': task['task_id'],
                             'record_sha256': sha256_file(Path(task_dir) / RECORD),
                             'work_id': entry['work_id'], 'underlying_state': entry.get('underlying_state', entry.get('state')),
                             'entry_sha256': sha256_json({key: value for key, value in entry.items()
                                                          if key not in ('state', 'underlying_state', 'reason',
                                                                         'underlying_reason', 'budget_proof',
                                                                         'limitation_kind', 'source_query_performed',
                                                                         'official_verification', 'reasoning')})},
            # r9 (portable-v1): an EU/JP national scope without local-language terms was never searchable; say so
            'reasoning': language_gap or REASONING}
