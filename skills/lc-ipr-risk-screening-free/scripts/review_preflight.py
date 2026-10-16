"""Read-only dry run of the final review: every check that can fail before a model session is paid for.

Nothing is written (no freeze file, no assessment-instant cache in task.json, no output directory), no native
process starts and the review allowance is not charged. The report lists, per module, the prompt size, the
retained-slot state of a resumed run, an estimate of the time one pass still needs and every problem that a
real run (or its resume) would hit - with the stable error codes the real run would use.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from common import load_json, sha256_file, sha256_json

PROMPT_LIMIT = 1048576
TOKEN_CHARS = 3.5        # rough characters per model token for the review prompt
TOKEN_WARNING = 120000   # per-module estimate above which the preflight warns
SUMMARY_SECONDS = 120          # one chain summary session; both chains run in parallel (measured 45-120 s class)
PREPARATION_SECONDS = 20       # readiness + packets + freeze per review invocation (measured 15-17 s)
BASE_MODULE_SECONDS = 150      # prefill, material observations and the closing statement of one module session
SECONDS_PER_REQUIRED_SCOPE = 20  # about 1,000 output tokens per row at ~38 tokens/second, shared by many rows


# r5d10 (B0GLNPC6K8): the technical module was cut by the network at 655 s and then stopped by the allowance at 507 s
# without an answer, while the estimate (no completed turn) said 190 s and a doomed pass was started. A turn of the same
# prompt that was still running when it was cut or timed out needed at least that long, plus this margin.
UNFINISHED_MARGIN_SECONDS = 120


def _measured_seconds(directory, prompt_sha256):
    """Longest completed native turn of this exact prompt in a slot or its archived attempts, else None.

    A turn of the same prompt that was cut off or timed out counts as its elapsed time plus a margin: the session
    needed longer than that, so a pass is never started in an allowance that already proved too short."""
    best = None
    directory = Path(directory)
    for folder in [directory, *directory.parent.glob(directory.name + '.attempt-*')]:
        path = folder / 'events.execution.json'
        try:
            data = load_json(path)
        except (OSError, ValueError):
            continue
        if (not isinstance(data, dict) or data.get('prompt_sha256') != prompt_sha256
                or not isinstance(data.get('elapsed_seconds'), (int, float))):
            continue
        if data.get('status') == 'process_exited':
            best = max(best or 0, float(data['elapsed_seconds']))
        elif (data.get('stall_kind') == 'answered_turn_not_closed'
              and isinstance(data.get('first_agent_message_seconds'), (int, float))):
            # r5d23: the answer was complete when the connection died; the model needed that long, not the grace after
            best = max(best or 0, float(data['first_agent_message_seconds']))
        elif silent_twin_measure(folder, data) is not None:
            best = max(best or 0, silent_twin_measure(folder, data))
        elif data.get('status') in ('process_failed', 'timed_out', 'stalled'):
            best = max(best or 0, float(data['elapsed_seconds']) + UNFINISHED_MARGIN_SECONDS)
    return best


def silent_twin_measure(folder, data):
    """r5d22: a turn cut off before it said anything (stalled, or timed out without an event of the model) proves
    nothing about the material; when the other chain finished the same module, that session is the measure
    (B0H16FDSD8: chain 2 hung 900 s with no event, chain 1 took 392 s; the resume then asked for 1,160 s)."""
    if data.get('status') not in ('timed_out', 'stalled'):
        return None
    if data.get('first_agent_message_seconds') is not None or data.get('first_reasoning_seconds') is not None:
        return None
    import stall_guard
    return stall_guard.twin_seconds(folder)


def _schedule(durations, workers):
    """Longest-first list scheduling, as the host does: the finishing time of the last session."""
    loads = [0.0] * max(1, workers)
    for duration in sorted(durations, reverse=True):
        loads[loads.index(min(loads))] += duration
    return max(loads) if durations else 0.0


def preflight(task_dir, output_dir=None, *, resume_existing=False, binary=None, isolation='auto', max_parallel=6):
    from execution_budget import snapshot as budget_snapshot
    task_dir = Path(task_dir).resolve()
    output_dir = Path(output_dir).resolve() if output_dir is not None else None
    report = {'schema': 'IPR-REVIEW-PREFLIGHT/1.0', 'task_dir': str(task_dir),
              'output_dir': str(output_dir) if output_dir else None, 'resume_existing': bool(resume_existing),
              'problems': [], 'warnings': [], 'modules': {}}

    def problem(code, **detail):
        report['problems'].append({'code': code, **detail})

    # 1. native runtime (and, for a resume, the runtime the retained sessions were bound to)
    try:
        import review_isolation
        backend = review_isolation.select_backend(isolation)
        report['backend'] = backend
        if resume_existing and output_dir is not None:
            from native_runtime_binding import resume_runtime, retained_runtime
            chosen, backend = resume_runtime(output_dir, binary, isolation)
            recorded = retained_runtime(output_dir)
            if recorded is None:
                problem('FINAL_REVIEW_RETAINED_RUNTIME_UNCONFIRMED', stage='runtime')
            else:
                path = Path(recorded['binary'])
                if not path.is_file():
                    problem('FINAL_REVIEW_RETAINED_RUNTIME_UNAVAILABLE', stage='runtime', binary=str(path))
                elif recorded.get('binary_sha256') is not None and sha256_file(path) != recorded['binary_sha256']:
                    problem('FINAL_REVIEW_RETAINED_RUNTIME_CHANGED', stage='runtime', binary=str(path),
                            hint='The native CLI changed after the retained sessions ran (an app update); '
                                 'do not update it until the retained review has been completed.')
        else:
            review_isolation.resolve_codex_binary(Path(binary) if binary else None, backend)
    except ValueError as exc:
        problem(str(exc).split(':')[0], stage='runtime', detail=str(exc))

    # 2. readiness of the evidence (the same gate the host applies, collected instead of raised)
    from review_readiness import readiness, preview_payload
    try:
        gate = readiness(task_dir)
    except ValueError as exc:
        problem('REVIEW_INPUT_NOT_READY', stage='readiness', detail=str(exc))
        report['ready'] = False
        return report
    report['input_digest'] = gate['input_digest']
    if not gate['ready']:
        reasons = sorted({str(row.get('reason')) for row in gate.get('blockers', [])})
        reasons.extend(str(value) for value in (gate.get('publication_preparation') or {}).get('errors', []))
        problem('REVIEW_INPUT_NOT_READY', stage='readiness', reasons=reasons)

    # 3. the frozen payload: the retained one on a resume, otherwise the one a freeze would export
    frozen = None
    retained_freeze = output_dir / 'frozen-input.json' if output_dir is not None else None
    if resume_existing and retained_freeze is not None and retained_freeze.is_file():
        frozen = load_json(retained_freeze)
        if frozen.get('evidence_digest') != gate['input_digest']:
            problem('REPORT_REVIEW_HOST_RETAINED_FREEZE_CHANGED', stage='freeze')
            frozen = None
    elif resume_existing:
        problem('REPORT_REVIEW_HOST_RETAINED_FREEZE_REQUIRED', stage='freeze')
    if frozen is None and not any(row['code'].startswith('REPORT_REVIEW_HOST_RETAINED_FREEZE') for row in report['problems']):
        try:
            frozen = preview_payload(task_dir)
        except ValueError as exc:
            problem(str(exc).split(':')[0], stage='freeze', detail=str(exc))
    if frozen is None:
        report['ready'] = not report['problems']
        return report

    # 4. module packets, material classification and prompt sizes
    import module_review as mr
    from report_review_host import review_prompt
    task = frozen['task']
    from legacy_task import notice as legacy_notice
    legacy = legacy_notice(task)
    if legacy:
        report['warnings'].append({'code': legacy['code'], 'detail': legacy['message'],
                                   'recommended_command': legacy['recommended_command']})
    if not mr.enabled(task):
        report['warnings'].append({'code': 'REVIEW_PREFLIGHT_LEGACY_WHOLE_INPUT_REVIEW',
                                   'detail': 'only the module review host is rehearsed'})
        report['ready'] = not report['problems']
        return report
    digest, payload_hash = frozen['evidence_digest'], sha256_json(frozen)
    import report_always
    marked = report_always.enabled(task)
    try:
        registry, candidates = mr.validation_context(frozen, task_dir)
    except ValueError as exc:
        problem(str(exc).split(':')[0], stage='validation_context', detail=str(exc))
        report['ready'] = False
        return report
    packets = {}
    for group in mr.GROUPS:
        try:
            packet = mr.module_packet(frozen, group)
            images = mr.attach_originals(packet, task_dir)
            # r5d4: the material inventory the sessions are later held to is checked here, before any session runs
            # (B0FSJBDTF2: an unreadable GIF voided the appearance review only after five minutes of sessions)
            from review_material_policy import enabled as classified_materials, validate_inventory
            if classified_materials(packet.get('task') or {}):
                validate_inventory(packet)
        except (ValueError, OSError) as exc:
            problem(str(exc).split(':')[0], stage='packet', module=group, detail=str(exc))
            continue
        packets[group] = (packet, images)
        scopes = len(packet['module_scope']['required_scopes'])
        entry = report['modules'][group] = {'required_scopes': scopes, 'images': len(images),
            'materials': len(packet['retained_originals']['materials']),
            'shared_public_originals': len(packet.get('shared_public_originals', []))}
        for chain in (1, 2):
            prompt = review_prompt(packet, chain)
            entry['prompt_chars_chain_%d' % chain] = len(prompt)
            tokens = round(len(prompt) / TOKEN_CHARS)
            entry['estimated_prompt_tokens'] = max(entry.get('estimated_prompt_tokens', 0), tokens)
            if chain == 1 and tokens > TOKEN_WARNING:
                report['warnings'].append({'code': 'REVIEW_PROMPT_TOKENS_HIGH', 'module': group,
                    'estimated_prompt_tokens': tokens, 'threshold': TOKEN_WARNING,
                    'images': len(images), 'hint': 'Estimate = prompt characters / %s, images excluded; '
                    'a long module turn is the main final-review latency.' % TOKEN_CHARS})
            if len(prompt) > PROMPT_LIMIT:
                problem('REPORT_REVIEW_HOST_INPUT_TOO_LARGE_AFTER_LOSSLESS_ENCODING', stage='prompt', module=group,
                        chain=chain, chars=len(prompt), limit=PROMPT_LIMIT,
                        hint='Reduce the task scope (fewer jurisdictions per task) and freeze again.')
            elif len(prompt) > 0.85 * PROMPT_LIMIT:
                report['warnings'].append({'code': 'REVIEW_PROMPT_NEAR_LIMIT', 'module': group, 'chain': chain,
                                           'chars': len(prompt), 'limit': PROMPT_LIMIT})

    # 5. retained slots of a resumed run and the time a pass still needs
    fresh_seconds = []
    summary_needed = True
    if packets and len(packets) == len(mr.GROUPS):
        states = {}
        for chain in (1, 2):
            for group, (packet, images) in packets.items():
                prompt = review_prompt(packet, chain)
                directory = output_dir / str(chain) / group if (output_dir is not None and resume_existing) else None
                if directory is None:
                    state, detail = 'fresh', None
                else:
                    def validate(record, packet=packet):
                        # the run's own module check (r6: the settled answer; older tasks: with the binding list the run
                        # applies - r6 found this dry run calling a refused slot "retained" without it)
                        mr.judge_module(record, packet, task, registry, candidates, None,
                            reusable_unit_ids=packet.get('review_reuse', {}).get('reusable_unit_ids', []))
                    state, detail = mr.preview_slot(directory, packet, prompt, validate, digest, payload_hash)
                    if state == 'archive' and _retry_limit(task) is not None and mr.failed_complete_turns(
                            directory, packet, prompt) > _retry_limit(task):
                        # the run refuses another session for this slot: r6 keeps it as pending rows, older tasks stop
                        state, detail = ('fallback', 'FINAL_REVIEW_SLOT_RETRY_LIMIT_REACHED') if marked else (
                            'blocked', 'FINAL_REVIEW_SLOT_RETRY_LIMIT_REACHED')
                states['%d/%s' % (chain, group)] = {'state': state, **({'detail': detail} if detail else {})}
                if state == 'blocked':
                    problem(detail, stage='slot', slot='%d/%s' % (chain, group))
                elif state in {'fresh', 'archive'}:
                    prompt_sha = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
                    measured = _measured_seconds(directory, prompt_sha) if directory else None
                    estimate = measured if measured is not None else (
                        BASE_MODULE_SECONDS + SECONDS_PER_REQUIRED_SCOPE * report['modules'][group]['required_scopes'])
                    states['%d/%s' % (chain, group)]['estimate_seconds'] = round(estimate)
                    states['%d/%s' % (chain, group)]['estimate_basis'] = 'measured' if measured is not None else 'model'
                    fresh_seconds.append(estimate)
        report['slots'] = states
        if resume_existing and output_dir is not None:
            summaries = [output_dir / str(chain) / 'summary' for chain in (1, 2)]
            summary_needed = not all((path / 'events.jsonl').is_file() and (path / 'audit.json').is_file()
                                     for path in summaries) or bool(fresh_seconds)
    modules_seconds = _schedule(fresh_seconds, max_parallel)
    if marked:
        summary_needed = False          # r6: the chain summary is written by the program
    needed = (PREPARATION_SECONDS + modules_seconds + (SUMMARY_SECONDS if summary_needed else 0))
    report['estimate'] = {'fresh_module_sessions': len(fresh_seconds), 'modules_seconds': round(modules_seconds),
        'summary_seconds': SUMMARY_SECONDS if summary_needed else 0, 'preparation_seconds': PREPARATION_SECONDS,
        'needed_seconds': round(needed),
        'basis': 'host-observed seconds of the same prompt where a retained turn exists, otherwise a '
                 'model of %d s + %d s per required scope (estimate, not a guarantee)' % (
                     BASE_MODULE_SECONDS, SECONDS_PER_REQUIRED_SCOPE)}

    # 6. the review allowance
    snapshot = None
    try:
        snapshot = budget_snapshot(task_dir)
    except ValueError as exc:
        problem(str(exc).split(':')[0], stage='budget', detail=str(exc))
    if snapshot is not None:
        report['budget'] = {key: snapshot[key] for key in ('revision', 'review_remaining_seconds', 'remaining_seconds',
                                                            'stop_reason') if key in snapshot}
        if snapshot['review_remaining_seconds'] < needed and marked:
            # r6: a module the allowance cannot hold becomes pending rows of its chain; the report is still written
            report['warnings'].append({'code': 'EXECUTION_REVIEW_BUDGET_SHORT', 'needed_seconds': round(needed),
                                       'review_remaining_seconds': round(snapshot['review_remaining_seconds'])})
        elif snapshot['review_remaining_seconds'] < needed:
            problem('EXECUTION_REVIEW_BUDGET_INSUFFICIENT', stage='budget', needed_seconds=round(needed),
                    review_remaining_seconds=round(snapshot['review_remaining_seconds']),
                    hint='The owner can add a bounded allowance in a terminal: python scripts/extend_review_budget.py '
                         '--task-dir "%s" --add-seconds %d --reason "<why>"' % (
                             task_dir, max(60, min(1800, int(needed - snapshot['review_remaining_seconds'] + 120)))))
    report['ready'] = not report['problems']
    return report


def _retry_limit(task):
    from execution_budget import policy as budget_policy
    return (budget_policy(task) or {}).get('max_slot_retries')


def render(report):
    return json.dumps(report, ensure_ascii=False, indent=2)
