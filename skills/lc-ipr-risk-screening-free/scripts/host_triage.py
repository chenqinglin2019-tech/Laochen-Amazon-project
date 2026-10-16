"""Shared policy, budget and card helpers for batch judgment hosts (new tasks only).

A host asks an independent native session for compact judgments and writes the
ordinary ledger records through the existing recorders. Nothing here grants
completion, changes a risk level or relaxes any validator.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import time

from common import atomic_write_json, load_json

REVISION = 'host-triage-v1'
JOURNAL = 'host-triage-budget.json'
# vision_* override the execution_efficiency visual batch limits for tasks that froze this marker.
# Added after the first host-triage-v1 tasks existed: a frozen task without these keys gets the value
# below, so no task has to be recreated. vision_product_images bounds the product views attached to one
# visual session; an object bound to more views than the limit could never be judged by the host at all.
OPTIONAL = {'vision_product_images': 6, 'vision_timeout_seconds': 240}
DEFAULTS = {'text_batch_units': 24, 'text_parallel': 3, 'text_timeout_seconds': 240,
            'analysis_seconds': 3600, 'vision_batch_candidates': 10, 'vision_parallel': 3, **OPTIONAL}
CARD_TEXT_LIMIT = 1200
CARD_LIST_LIMIT = 12
# Bulky or purely mechanical fields never help a relevance judgment.
CARD_SKIP_KEYS = {'figures', 'browser_evidence', 'normalization_key', 'material', 'payload', 'raw', 'raw_paths',
                  'record_fields', 'source_record', 'original_identifiers', 'field_claims', 'official_verification',
                  'evidence_refs', 'candidate_id', 'identity_status'}


def enabled(task):
    revision = task.get('host_triage_revision')
    if revision is None:
        return False
    if revision != REVISION:
        raise ValueError('HOST_TRIAGE_REVISION_INVALID')
    return True


def policy(task):
    """Return the frozen limits of a new task, or None for a task without the marker."""
    if not enabled(task):
        return None
    values = task.get('host_triage')
    if (not isinstance(values, dict) or not set(DEFAULTS) - set(OPTIONAL) <= set(values) <= set(DEFAULTS)
            or any(type(v) is not int or v <= 0 for v in values.values())):
        raise ValueError('HOST_TRIAGE_POLICY_INVALID')
    return {**OPTIONAL, **values}


def _journal(task_dir, task):
    path = task_dir / JOURNAL
    if path.is_file():
        data = load_json(path)
        if (not isinstance(data, dict) or data.get('revision') != REVISION
                or data.get('task_id') != task.get('task_id')
                or type(data.get('used_seconds')) not in (int, float) or data['used_seconds'] < 0):
            raise ValueError('HOST_TRIAGE_BUDGET_JOURNAL_INVALID')
        return data
    return {'revision': REVISION, 'task_id': task.get('task_id'), 'used_seconds': 0.0, 'invocations': 0}


# r5d9 (B0GLNPC6K8 new task): the Mac slept 34 minutes inside three host calls of the first run; the wall clock
# charged that sleep to this allowance, so the resume found 72 seconds left and cut the design comparison session
# off. A call is now charged its awake time (the process clock stops while the computer sleeps), and sleep that an
# earlier version charged is credited back from the host steps' own two clocks in runtime-timings.jsonl.
SLEEP_CREDIT_SECONDS = 60
HOST_STEPS = frozenset({'discovery_review', 'provenance_host', 'text_triage', 'visual_triage', 'comparison_host', 'recall_screen',
                        'prereview_screen', 'design_screen', 'claims_triage'})


def _instant(value):
    from datetime import datetime
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment.timestamp() if moment.tzinfo else None


def sleep_credit(task_dir, before):
    """Seconds of sleep that wall-clock charging put on host steps started before ``before`` (a timestamp).

    A step whose wall time exceeds its process time by a minute or more slept. Steps of one name that overlap ran
    in one invocation (parallel slots), which was charged once, so each overlapping group counts its largest gap.
    """
    import json
    from runtime_timing import FILENAME
    steps = {}
    try:
        lines = (Path(task_dir) / FILENAME).read_text(encoding='utf-8').splitlines()
    except OSError:
        return 0.0
    for line in lines:
        try:
            row = json.loads(line)
            stage, process = row.get('stage'), float(row['elapsed_ms']) / 1000
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        start, end = _instant(row.get('started_at')), _instant(row.get('finished_at'))
        if stage in HOST_STEPS and start is not None and end is not None and start < before and end >= start:
            steps.setdefault(stage, []).append((start, end, max(0.0, end - start - process)))
    credit = 0.0
    for rows in steps.values():
        group_end, largest = None, 0.0
        for start, end, slept in sorted(rows):
            if group_end is None or start > group_end:
                credit += largest if largest >= SLEEP_CREDIT_SECONDS else 0.0
                group_end, largest = end, 0.0
            group_end, largest = max(group_end, end), max(largest, slept)
        credit += largest if largest >= SLEEP_CREDIT_SECONDS else 0.0
    return round(credit, 3)


def _charged(task_dir, data):
    """Charged seconds less the sleep an earlier wall-clock charge counted (never below zero)."""
    before = _instant(data.get('awake_since')) if data.get('awake_since') else time.time()
    return max(0.0, data['used_seconds'] - sleep_credit(task_dir, before if before is not None else time.time()))


def remaining_seconds(task_dir, task):
    limits = policy(task)
    if limits is None:
        raise ValueError('HOST_TRIAGE_NEW_TASK_REQUIRED')
    return max(0.0, limits['analysis_seconds'] - _charged(task_dir, _journal(task_dir, task)))


@contextmanager
def analysis_budget(task_dir, task):
    """Charge the awake time of one host invocation to its own analysis allowance.

    The allowance is separate from source retrieval and final review, so
    replacing hand-written ledgers never starves either of them. A crashed
    invocation is charged the time it actually ran; time the computer slept is not analysis.
    """
    task_dir = Path(task_dir)
    left = remaining_seconds(task_dir, task)
    if left <= 0:
        raise ValueError('HOST_TRIAGE_ANALYSIS_BUDGET_EXHAUSTED')
    started = time.time()
    clock = time.perf_counter()
    try:
        yield started + left
    finally:
        from execution_lock import execution_lock
        awake = max(0.0, time.perf_counter() - clock)
        ended = time.time()
        for _ in range(50):
            try:
                with execution_lock(task_dir, 'budget'):
                    _charge(task_dir, task, started, ended, awake)
                break
            except ValueError:
                time.sleep(0.1)     # another host is writing its own charge
        else:
            _charge(task_dir, task, started, ended, awake)


def _overlap(start, end, intervals):
    """Seconds of [start, end] already covered by the recorded intervals (their union)."""
    covered, cursor = 0.0, start
    for low, high in sorted((max(start, a), min(end, b)) for a, b in intervals if b > start and a < end):
        if high <= cursor:
            continue
        covered += high - max(low, cursor)
        cursor = high
    return covered


def _charge(task_dir, task, started, ended, awake):
    """r5d21: hosts the pipeline runs side by side were each charged in full (three hosts for six minutes cost
    eighteen); a call is now charged only the awake time that no earlier recorded call already covered."""
    from datetime import datetime, timezone
    data = _journal(task_dir, task)
    intervals = [tuple(row) for row in data.get('intervals', []) if isinstance(row, list) and len(row) == 2]
    charge = max(0.0, awake - _overlap(started, ended, intervals))
    data['used_seconds'] = round(data['used_seconds'] + charge, 3)
    data['intervals'] = [list(row) for row in (intervals + [(started, ended)])[-400:]]
    data['invocations'] = int(data.get('invocations', 0)) + 1
    # steps started before the first awake charge were charged by the wall clock
    since = datetime.fromtimestamp(started, timezone.utc).isoformat()
    known = _instant(data.get('awake_since')) if data.get('awake_since') else None
    if known is None or started < known:
        data['awake_since'] = since
    data['sleep_credit_seconds'] = sleep_credit(task_dir, _instant(data['awake_since']))
    atomic_write_json(task_dir / JOURNAL, data)


def _clip(value):
    text = ' '.join(value.split())
    return text if len(text) <= CARD_TEXT_LIMIT else text[:CARD_TEXT_LIMIT] + '…'


def _scalar(value):
    return isinstance(value, (str, int, float, bool)) or value is None


def candidate_card(candidate):
    """Compact, factual view of one normalized candidate for a relevance judgment."""
    card = {}
    for key, value in candidate.items():
        if key in CARD_SKIP_KEYS or key.endswith(('_sha256', '_digest', '_hash')):
            continue
        if key == 'sources':
            rows = []
            for source in value if isinstance(value, list) else []:
                if isinstance(source, dict):
                    rows.append({k: _clip(v) if isinstance(v, str) else v for k, v in source.items()
                                 if k in {'provider', 'source', 'operation', 'source_url', 'url', 'source_position',
                                          'result_position', 'index'} and _scalar(v)})
            card['sources'] = rows[:4]
        elif isinstance(value, str):
            if value.strip():
                card[key] = _clip(value)
        elif _scalar(value):
            if value is not None:
                card[key] = value
        elif isinstance(value, list):
            items = [_clip(v) if isinstance(v, str) else v for v in value if _scalar(v) and v not in (None, '')]
            if items:
                card[key] = items[:CARD_LIST_LIMIT]
        elif isinstance(value, dict):
            flat = {k: _clip(v) if isinstance(v, str) else v for k, v in value.items() if _scalar(v) and v not in (None, '')}
            if flat:
                card[key] = dict(list(flat.items())[:CARD_LIST_LIMIT])
    return card


def _text_len(candidate, *names):
    best = 0
    for name in names:
        value = candidate.get(name)
        if isinstance(value, str):
            best = max(best, len(value.strip()))
        elif isinstance(value, list):
            best = max(best, sum(len(v.strip()) for v in value if isinstance(v, str)))
    return best


def text_only_lead(candidate):
    """A public web result with no image of its own: only its card text can be read by a model.

    Such a lead has no right type, no country and nothing to look at. Judging it as a picture only produces a
    blank "nothing to compare" session; its card (title, snippet, address) is the whole judgeable content.
    """
    return (isinstance(candidate, dict) and candidate.get('right_type') == 'unknown'
            and candidate.get('candidate_nature') == 'web_result'
            and not str(candidate.get('image_url') or '').strip()
            and not str(candidate.get('thumbnail_url') or '').strip())


def text_only_candidate_ids(root):
    """Candidate IDs of a task's text-only public leads (empty when there are no retained candidates)."""
    from pathlib import Path
    from annotate_materiality import iter_candidates
    path = Path(root) / 'normalized-candidates.json'
    if not path.is_file():
        return set()
    return {str(item.get('candidate_id')) for _, item in iter_candidates(load_json(path))
            if text_only_lead(item) and item.get('candidate_id')}


def reading_profile(candidate):
    """(reading_level, exclusion_allowed) from the content actually present on the card.

    A bare number or title can never support an exclusion; it can only be
    selected or kept as needs_info.
    """
    right = candidate.get('right_type')
    if right in {'patent', 'utility_model', 'design', 'unregistered_design'}:
        if _text_len(candidate, 'abstract', 'snippet', 'description') >= 40:
            return 'abstract', True
        return 'result_record', False
    if right in {'trademark_word', 'trademark_figurative'}:
        has_mark = _text_len(candidate, 'mark_text', 'mark', 'name') > 0
        has_goods = _text_len(candidate, 'goods_services', 'nice_classes', 'classes', 'goods') > 0
        registered = bool(candidate.get('registration_number') or candidate.get('serial_number')
                          or candidate.get('application_number'))
        if has_mark and has_goods:
            return ('registry_record' if registered else 'result_record'), True
        return 'result_record', False
    return 'result_record', _text_len(candidate, 'snippet', 'abstract', 'description') >= 40
