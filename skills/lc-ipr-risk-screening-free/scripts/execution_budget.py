"""Persistent bounds for automatic execution; never grant completion authority."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import math
import os
import signal
import subprocess
import sys
import time
import uuid

from common import atomic_write_json, load_json, sha256_json, sha256_file
from execution_lock import execution_lock

REVISION = 'bounded-execution-v1'
JOURNAL = 'execution-budget.json'
DEFAULTS = {'active_seconds': 1800, 'review_seconds': 900, 'review_reserve_seconds': 600,
            'max_action_rounds': 96, 'max_no_progress_rounds': 12}
ENV_DEADLINE = 'LC_IPR_EXECUTION_DEADLINE_EPOCH'
ENV_LEASE = 'LC_IPR_EXECUTION_LEASE'
ENV_TASK = 'LC_IPR_EXECUTION_TASK_DIR'
ENV_GROUP = 'LC_IPR_OWNED_PROCESS_GROUP'


def policy(task):
    revision = task.get('execution_budget_revision')
    if revision is None:
        return None
    if revision != REVISION:
        raise ValueError('EXECUTION_BUDGET_REVISION_INVALID')
    if not isinstance(task.get('execution_budget', {}), dict):
        raise ValueError('EXECUTION_BUDGET_POLICY_INVALID')
    values = {**DEFAULTS, **task.get('execution_budget', {})}
    if set(values) != set(DEFAULTS) or any(type(v) is not int or v <= 0 for v in values.values()):
        raise ValueError('EXECUTION_BUDGET_POLICY_INVALID')
    if (values['review_seconds'] > values['active_seconds']
            or values['review_reserve_seconds'] >= values['active_seconds']):
        raise ValueError('EXECUTION_BUDGET_REVIEW_EXCEEDS_TOTAL')
    return values


def round_block(task, evidence, *, admitted_ids=()):
    limits = policy(task)
    if limits is None:
        return None
    events = evidence.get('progress_events', [])
    if not admitted_ids:
        root = os.environ.get(ENV_TASK)
        if root and os.environ.get(ENV_LEASE):
            try:
                active = _read(root, task, limits).get('active') or {}
                if active.get('lease') == os.environ[ENV_LEASE] and active.get('phase') == 'sources':
                    admitted_ids = active.get('admitted_ids', [])
            except (OSError, ValueError, KeyError):
                pass
    admitted = {row.get('event_id') for row in events if row.get('kind') == 'begin'
        and row.get('event_id') in admitted_ids and not any(
            other.get('kind') == 'finish' and other.get('begin_id') == row.get('event_id') for other in events)}
    if sum(row.get('kind') == 'begin' for row in events) - len(admitted) >= limits['max_action_rounds']:
        return 'EXECUTION_ACTION_ROUNDS_EXHAUSTED'
    if sum(row.get('kind') == 'finish' and row.get('effective_progress') is False
           for row in events) >= limits['max_no_progress_rounds']:
        return 'EXECUTION_NO_PROGRESS_BUDGET_EXHAUSTED'
    return None


def _read(task_dir, task, limits):
    path = Path(task_dir) / JOURNAL
    data = load_json(path) if path.is_file() else {
        'revision': REVISION, 'task_id': task['task_id'], 'policy_sha256': sha256_json(limits),
        'used_seconds': 0.0, 'review_used_seconds': 0.0, 'invocations': 0, 'active': None}
    if (data.get('revision') != REVISION or data.get('task_id') != task['task_id']
            or data.get('policy_sha256') != sha256_json(limits)):
        raise ValueError('EXECUTION_BUDGET_BINDING_CHANGED')
    data.setdefault('review_used_seconds', 0.0)
    for key in ('used_seconds', 'review_used_seconds', 'invocations'):
        if type(data.get(key)) not in (int, float) or not math.isfinite(data[key]) or data[key] < 0:
            raise ValueError('EXECUTION_BUDGET_JOURNAL_INVALID')
    active = data.get('active')
    if active is not None and (not isinstance(active, dict)
            or any(type(active.get(k)) not in (int, float) or not math.isfinite(active[k])
                   for k in ('started', 'deadline')) or active['deadline'] < active['started']
            or not active.get('lease')):
        raise ValueError('EXECUTION_BUDGET_JOURNAL_INVALID')
    return data


def snapshot(task_dir):
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / 'task.json')
    limits = policy(task)
    if limits is None:
        return None
    data = _read(task_dir, task, limits)
    active = data.get('active')
    used = data['used_seconds'] + (max(0, min(time.time(), active['deadline']) - active['started']) if active else 0)
    remaining = max(0, limits['active_seconds'] - used)
    evidence = load_json(task_dir / 'evidence.json')
    reason = round_block(task, evidence) or ('EXECUTION_SOURCE_TIME_BUDGET_EXHAUSTED'
        if remaining <= limits['review_reserve_seconds'] else None)
    review_used = data['review_used_seconds'] + (max(0, min(time.time(), active['deadline']) - active['started'])
        if active and active.get('phase') == 'review' else 0)
    return {'revision': REVISION, 'limits': limits, 'used_seconds': round(used, 3),
            'review_remaining_seconds': max(0, min(remaining, limits['review_seconds'] - review_used)),
            'remaining_seconds': remaining, 'stop_reason': reason, 'incomplete': bool(reason)}


def remaining(deadline, timeout):
    if deadline is None:
        return timeout
    if not math.isfinite(deadline):
        raise ValueError('EXECUTION_DEADLINE_INVALID')
    available = deadline - time.time()
    if available <= 0:
        raise ValueError('EXECUTION_TIME_BUDGET_EXHAUSTED')
    return min(timeout, available)


@contextmanager
def execution_budget(task_dir, phase, *, inherit=False, admitted_ids=()):
    """Charge one outer invocation, including children, even after interruption.

    An inherited lease is accepted only when it matches the live task journal.
    Waiting between completed invocations is not charged. Interrupted leases
    are conservatively charged until their persisted deadline, never refunded.
    """
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / 'task.json')
    limits = policy(task)
    if limits is None:
        yield None
        return
    if inherit and os.environ.get(ENV_TASK) == str(task_dir):
        data = _read(task_dir, task, limits)
        active = data.get('active') or {}
        if active.get('lease') != os.environ.get(ENV_LEASE):
            raise ValueError('EXECUTION_BUDGET_INHERITED_LEASE_INVALID')
        deadline = float(os.environ.get(ENV_DEADLINE, 'nan'))
        if deadline != active.get('deadline'):
            raise ValueError('EXECUTION_BUDGET_INHERITED_LEASE_INVALID')
        remaining(deadline, limits['active_seconds'])
        yield deadline
        return
    with execution_lock(task_dir, 'budget'):
        data = _read(task_dir, task, limits)
        # The previous owner lost its process lock: retain the whole reservation
        # rather than letting a crash or a later restart buy another attempt.
        if data.get('active'):
            reserved = data['active']['deadline'] - data['active']['started']
            data['used_seconds'] += reserved
            if data['active'].get('phase') == 'review':
                data['review_used_seconds'] += reserved
            data['active'] = None
            atomic_write_json(task_dir / JOURNAL, data)
        available = limits['active_seconds'] - data['used_seconds']
        if phase == 'review':
            available = min(available, limits['review_seconds'] - data['review_used_seconds'])
        else:
            available -= limits['review_reserve_seconds']
        reason = round_block(task, load_json(task_dir / 'evidence.json'), admitted_ids=admitted_ids) if phase != 'review' else None
        if reason or available <= 0:
            raise ValueError(reason or 'EXECUTION_TIME_BUDGET_EXHAUSTED')
        now = time.time()
        deadline = now + min(available, limits['review_seconds'] if phase == 'review' else available)
        data['active'] = {'lease': uuid.uuid4().hex, 'started': now, 'deadline': deadline, 'phase': phase, 'admitted_ids': list(admitted_ids)}
        data['invocations'] += 1
        atomic_write_json(task_dir / JOURNAL, data)
        try:
            yield deadline
        finally:
            elapsed = max(0, min(time.time(), deadline) - now)
            data['used_seconds'] += elapsed
            if phase == 'review':
                data['review_used_seconds'] += elapsed
            data['active'] = None
            atomic_write_json(task_dir / JOURNAL, data)


def child_environment(task_dir, deadline):
    if deadline is None:
        return dict(os.environ)
    data = load_json(Path(task_dir) / JOURNAL)
    return {**os.environ, ENV_TASK: str(Path(task_dir).resolve()),
            ENV_LEASE: data['active']['lease'], ENV_DEADLINE: str(deadline)}


def delivery_limit(task, evidence, plan, entry, task_dir):
    """A frozen internal stop may defer only a genuinely unexecuted lookup.

    Existing originals, candidate reading and unknown submissions retain all
    their original obligations. This proof never grants a final clearance.
    """
    if task_dir is None or policy(task) is None or entry.get('integrity_failure'):
        return None
    if (entry.get('kind') not in {'source_lookup', 'agent_investigation'}
            or entry.get('candidate_id') or entry.get('source_run_refs')
            or entry.get('underlying_state', entry.get('state')) != 'ready'):
        return None
    root = Path(task_dir)
    journal = root / JOURNAL
    if not journal.is_file():
        return None
    current_task = load_json(root / 'task.json')
    if current_task.get('task_id') != task.get('task_id') or policy(current_task) != policy(task):
        return None
    data = _read(root, task, policy(task))
    stopped = snapshot(root)
    if (data.get('active') or {}).get('phase') not in (None, 'review') or not stopped['stop_reason']:
        return None
    query = entry.get('query_id')
    matches = [(provider, row) for provider, rows in plan.get('queries', {}).items()
               for row in rows if isinstance(row, dict) and row.get('query_id') == query]
    if not query or len(matches) != 1:
        return None
    provider, row = matches[0]
    if any(run.get('query_id') == query for run in evidence.get('source_runs', [])):
        return None
    if any(material.get('query_id') == query for rows in evidence.get('collections', {}).values()
           if isinstance(rows, list) for material in rows if isinstance(material, dict)):
        return None
    for filename, key in (('browser-execution-status.json', 'queries'), ('execution-status.json', 'results')):
        path = root / filename
        if not path.is_file():
            continue
        receipt = load_json(path)
        if query in receipt.get('pending_submissions', {}):
            return None
        for item in receipt.get(key, []):
            if item.get('query_id') == query and (item.get('submission_state') != 'not_submitted'
                    or item.get('plan_entry_sha256') != sha256_json(row)):
                return None
    # A begin without a retained submission outcome is not proof of no submission.
    if any(event.get('kind') == 'begin' and event.get('query_id') == query
           for event in evidence.get('progress_events', [])):
        return None
    return {**deepcopy(entry), 'state': 'blocked', 'reason': stopped['stop_reason'],
        'limitation_kind': 'internal_execution_budget', 'source_query_performed': False,
        'official_verification': 'not_verified', 'budget_proof': {
            'revision': REVISION, 'task_id': task['task_id'], 'policy_sha256': sha256_json(policy(task)),
            'journal_sha256': sha256_file(journal), 'progress_sha256': sha256_json(evidence.get('progress_events', [])),
            'provider': provider, 'query_id': query, 'plan_entry_sha256': sha256_json(row)},
        'reasoning': '自动执行的累计预算已用尽，本项尚未实际查询，风险待定；内部执行停止不代表来源没有结果，不能据此放行。'}


def project(task, evidence, plan, view, task_dir):
    if policy(task) is None or task_dir is None:
        return view
    result = deepcopy(view)
    changed = False
    for entry in result.get('entries', []):
        limit = delivery_limit(task, evidence, plan, entry, task_dir)
        if limit:
            entry.setdefault('underlying_state', entry['state'])
            entry.setdefault('underlying_reason', entry.get('reason'))
            entry.update({key: limit[key] for key in ('state', 'reason', 'budget_proof', 'limitation_kind',
                          'source_query_performed', 'official_verification', 'reasoning')})
            changed = True
    if changed:
        result['status'] = 'incomplete'
        result['counts'] = {state: sum(row.get('state') == state for row in result.get('entries', []))
                           for state in ('ready', 'awaiting_review', 'awaiting_access', 'awaiting_user', 'submission_unknown', 'blocked')}
    return result


def owned_group():
    if os.name == 'nt':
        return None
    try:
        group = int(os.environ.get(ENV_GROUP, '0'))
        return group if group > 0 and group == os.getpgrp() == os.getsid(0) else None
    except (ValueError, OSError):
        return None


def bounded_popen(command, *, env=None, **kwargs):
    # A nested runner stays inside its outer owner's group. A standalone runner
    # starts its own session, with a bootstrap stamping the real group id.
    inherited = owned_group()
    child_env = dict(os.environ if env is None else env)
    argv = command
    if os.name != 'nt' and inherited is None:
        child_env.pop(ENV_GROUP, None)
        argv = [sys.executable, str(Path(__file__).with_name('process_group_exec.py')), *command]
    elif inherited is not None:
        child_env[ENV_GROUP] = str(inherited)
    proc = subprocess.Popen(argv, start_new_session=os.name != 'nt' and inherited is None,
                            env=child_env, **kwargs)
    proc._ipr_group_owner = inherited is None
    return proc


def kill_tree(proc):
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           capture_output=True, timeout=5, check=False)
            proc.kill()
        elif getattr(proc, '_ipr_group_owner', True):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            # An operation timeout must not kill sibling jobs or its parent.
            # The outer deadline still owns a single group and catches races.
            captured = subprocess.run(['ps', '-axo', 'pid=,ppid='], capture_output=True,
                                      text=True, timeout=1, check=False)
            parents = {}
            for line in captured.stdout.splitlines():
                fields = line.split()
                if len(fields) == 2:
                    parents.setdefault(int(fields[1]), []).append(int(fields[0]))
            def descendants(pid):
                result = []
                for child in parents.get(pid, []):
                    result.extend(descendants(child)); result.append(child)
                return result
            for pid in [*descendants(proc.pid), proc.pid]:
                try: os.kill(pid, signal.SIGKILL)
                except ProcessLookupError: pass
    except ProcessLookupError:
        pass


def run_bounded(command, *, deadline, timeout, env=None, **kwargs):
    duration = remaining(deadline, timeout)
    with bounded_popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, **kwargs) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=duration)
        except subprocess.TimeoutExpired as exc:
            kill_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise subprocess.TimeoutExpired(command, duration, output=exc.output, stderr=exc.stderr) from exc
            raise subprocess.TimeoutExpired(command, duration, output=stdout, stderr=stderr) from exc
        return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
