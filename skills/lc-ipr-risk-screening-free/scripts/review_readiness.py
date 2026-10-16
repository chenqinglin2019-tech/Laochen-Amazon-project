#!/usr/bin/env python3
"""Check final-review readiness; --freeze fixes one semantic input and assessment time.

New final-double-review-v1 tasks reuse unchanged units from each reviewer's own
prior receipt. Legacy tasks preserve their original whole-input contract.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from common import load_json

_PREPARED_SEAL = object()


def _preparation_integrity(task_dir):
    """Bind declared original bytes, including exact relocated copies."""
    from common import sha256_file, resolve_retained_path
    from delivery_versions_stage_e import _retained_files, INPUTS
    root = Path(task_dir).resolve()
    values = {name: load_json(root / name) if (root / name).is_file() else None for name in INPUTS}
    fingerprints = _retained_files(root, values)
    manifest_path = root / 'recovery-manifest.json'
    if manifest_path.is_file():
        manifest = load_json(manifest_path)
        fingerprints[str(manifest_path)] = sha256_file(manifest_path)
        mappings = {row.get('source_path'): row for row in manifest.get('file_mappings', [])}
        # The relocation inventory includes mutable task journals as well as
        # originals. Only declared original-file dependencies bind here;
        # semantic task/journal facts are bound separately by current_digest.
        for source_path in list(fingerprints):
            row = mappings.get(source_path)
            if row is None:
                continue
            target = resolve_retained_path(root, source_path, expected_sha256=row['sha256'],
                                           expected_bytes=row.get('bytes'))
            del fingerprints[source_path]
            fingerprints[str(target)] = sha256_file(target)
    return fingerprints


class PreparedReviewContext:
    """In-process readiness result bound to current facts and original bytes.

    No serialized passed flag may create this context. It can be consumed by
    freezing and row registration only while the actual input still matches.
    """
    def __init__(self, task_dir, gate, fingerprints, seal):
        if seal is not _PREPARED_SEAL or gate.get('ready') is not True:
            raise ValueError('REVIEW_PREPARED_CONTEXT_NOT_ISSUED')
        from copy import deepcopy
        self.task_dir = Path(task_dir).resolve()
        self.gate = deepcopy(gate)
        self.fingerprints = dict(fingerprints)
        self.frozen_path = None
        self.frozen_sha256 = None

    def validate(self, task_dir, *, frozen=False):
        from common import sha256_file
        if (Path(task_dir).resolve() != self.task_dir or current_digest(self.task_dir) != self.gate['input_digest']
                or _preparation_integrity(self.task_dir) != self.fingerprints):
            raise ValueError('REVIEW_PREPARED_INPUT_CHANGED')
        if frozen and (self.frozen_path is None or not self.frozen_path.is_file()
                or sha256_file(self.frozen_path) != self.frozen_sha256):
            raise ValueError('REVIEW_PREPARED_FREEZE_CHANGED')
        return self.gate

    def bind_freeze(self, path):
        from common import sha256_file
        if self.frozen_path is not None:
            raise ValueError('REVIEW_PREPARED_FREEZE_ALREADY_BOUND')
        self.frozen_path = Path(path).resolve()
        self.frozen_sha256 = sha256_file(self.frozen_path)


def prepare_review_context(task_dir):
    root = Path(task_dir).resolve()
    before = _preparation_integrity(root)
    gate = readiness(root)
    if not gate['ready']:
        reasons = sorted({str(row.get('reason')) for row in gate.get('blockers', [])})
        reasons.extend(str(value) for value in (gate.get('publication_preparation') or {}).get('errors', []))
        raise ValueError('REVIEW_INPUT_NOT_READY: ' + ','.join(reasons))
    if current_digest(root) != gate['input_digest'] or _preparation_integrity(root) != before:
        raise ValueError('REVIEW_PREPARATION_INPUT_CHANGED')
    return PreparedReviewContext(root, gate, before, _PREPARED_SEAL)


def current_digest(task_dir: Path) -> str:
    from work_view_memo import cached
    return cached(task_dir, 'review_digest', {}, lambda: _current_digest(task_dir))


def _current_digest(task_dir: Path) -> str:
    from workflow_v24 import _scenario_context, scenario_supplement
    from assessment_estimate import review_digest
    task = load_json(task_dir / 'task.json')
    candidates, ledger, evidence = _scenario_context(task_dir, task)
    plan = load_json(task_dir / 'search-plan.json')
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    return review_digest(evidence, candidates, ledger, plan, task, supplement)


def dispatch_view(task_dir: Path, *, first_review=None, second_review=None):
    from workflow_v24 import work_view_from_dir
    reviews = [first_review, second_review]
    invalidated = []
    if any(review is not None for review in reviews):
        digest = current_digest(task_dir)
        for position, review in enumerate(reviews):
            if review is None:
                continue
            context = review.get('review_context') if isinstance(review, dict) else None
            if not isinstance(context, dict) or not isinstance(context.get('evidence_digest'), str):
                raise ValueError('REVIEW_CONTEXT_INVALID')
            if context['evidence_digest'] != digest:
                invalidated.append({'review': ('first', 'second')[position],
                    'reason': 'REVIEW_INPUT_CHANGED', 'review_digest': context['evidence_digest'],
                    'current_digest': digest})
                reviews[position] = None
    view = work_view_from_dir(task_dir, first_review=reviews[0], second_review=reviews[1])
    if invalidated:
        from final_review import enabled as final_enabled, inputs as final_inputs, reuse_options
        prior_final = any((review or {}).get('review_context', {}).get('final_review')
            for review in (first_review, second_review))
        task = load_json(task_dir / 'task.json') if prior_final else {}
        if final_enabled(task):
            from workflow_v24 import _scenario_context, scenario_supplement
            candidates, ledger, evidence = _scenario_context(task_dir, task)
            material = final_inputs(evidence, candidates, ledger, load_json(task_dir / 'search-plan.json'),
                task, scenario_supplement(task_dir, task=task, evidence=evidence))
            for item in invalidated:
                previous = first_review if item['review'] == 'first' else second_review
                item['unit_reuse'] = reuse_options(previous, material)
        view['invalidated_reviews'] = invalidated
    return view


def readiness(task_dir: Path) -> dict:
    # No old report review is imported: its rejection must not hide repair work.
    view = dispatch_view(task_dir)
    task = load_json(task_dir / 'task.json')
    blockers = [row for row in view.get('entries', [])
                if row.get('state') in {'ready', 'awaiting_review', 'submission_unknown'}]
    from review_progress_stage_a import _version
    stale_items = [{'item_id': row['item_id'], 'product_version': row['scope']['product_version'],
                    'current_product_version': _version(task)}
                   for row in view.get('review_progress', {}).get('items', [])
                   if row.get('state') not in {'removed', 'exempt'}
                   and row.get('scope', {}).get('product_version') != _version(task)]
    plan_required = bool(task.get('review_progress_revision')) and view.get('review_progress', {}).get('status') == 'plan_required'
    blockers.extend(publication_gate_blockers(task))
    digest = current_digest(task_dir)
    from assessment_estimate import known_findings_enabled
    publication_gate = preparation_issues_from_dir(task_dir, task=task, prepared_view=view) if known_findings_enabled(task) else None
    return {'schema': 'IPR-REVIEW-READINESS/1.0', 'ready': not blockers and not stale_items and not plan_required
                and not (publication_gate or {}).get('errors'),
            'progress_plan_required': plan_required,
            'input_digest': digest, 'blockers': blockers, 'stale_progress_items': stale_items,
            'external_dependencies': [row for row in view.get('entries', [])
                                      if row.get('state') in {'awaiting_access', 'awaiting_user', 'blocked'}],
            **({'publication_preparation': publication_gate} if publication_gate is not None else {}),
            'meaning': 'input preparation only; current execution and limitation proof issues are collected together; final independent reviews remain required for publication'}


def publication_gate_blockers(task: dict) -> list[dict]:
    """best-estimate-risk-v2: the assessment gates publication applies, checked before any final-review expense.

    A product change whose affected candidates have no applicability review, or a candidate still waiting for a
    user answer, makes publication fail after both reviews have run (round-7 run: three review passes). They are
    reported here as ordinary readiness blockers with the recorder that resolves them.
    """
    from assessment_estimate import best_estimate_v2
    if not best_estimate_v2(task):
        return []
    from product_change import unresolved_candidates
    from product_feedback import pending
    rows = [{'kind': 'product_change_applicability', 'state': 'ready',
             'reason': 'PRODUCT_CHANGE_APPLICABILITY_REVIEW_REQUIRED',
             'candidate_id': item['candidate_id'], 'change_id': item['change_id'],
             'next_action': 'record_product_applicability.py --task-dir RUN --input <product-applicability-v1> '
                            '(an additive scope change records this automatically)'}
            for item in unresolved_candidates(task)]
    rows.extend({'kind': 'product_feedback_answer', 'state': 'ready', 'reason': 'PRODUCT_FEEDBACK_ANSWER_PENDING',
                 'candidate_id': row.get('candidate_id'), 'request_id': row.get('request_id'),
                 'next_action': 'record_product_feedback.py: record the answer or the unavailability of this request'}
                for row in pending(task) if row.get('candidate_id'))
    return rows


def preparation_issues_from_dir(task_dir: Path, *, task=None, prepared_view=None) -> dict:
    """Check the same publication proof predicates before final-review expense."""
    from workflow_v24 import _scenario_context, scenario_supplement
    from necessary_completion import collect_publication_issues
    task_dir = Path(task_dir)
    task = task if task is not None else load_json(task_dir / 'task.json')
    candidates, ledger, evidence = _scenario_context(task_dir, task)
    plan = load_json(task_dir / 'search-plan.json')
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    snapshots = {name: load_json(task_dir / name) for name in
        ('source-capabilities.json', 'browser-execution-status.json') if (task_dir / name).is_file()}
    assessment = {'status': 'incomplete', 'coverage': {'scopes': []},
        'review': {'input_reviews': {'first': None, 'second': None}},
        'supplement': supplement, 'scenario_summaries': [], 'assessments': []}
    return collect_publication_issues(task, evidence, candidates, plan, ledger, assessment,
        mode='evidence', snapshots=snapshots, task_dir=task_dir, evidence_root=task_dir,
        preparation=True, prepared_view=prepared_view)


def preview_payload(task_dir: Path) -> dict:
    """The payload freeze_input would export, assembled in memory only.

    Nothing is written: no task.json assessment-instant cache, no export file. The sizes, packets and prompts
    built from it are what a real freeze at this moment would produce (the assessment instant aside).
    """
    from copy import deepcopy
    from workflow_v24 import _scenario_context, scenario_supplement
    from assessment_estimate import review_digest
    task_dir = Path(task_dir).resolve()
    task = deepcopy(load_json(task_dir / 'task.json'))
    candidates, ledger, evidence = _scenario_context(task_dir, task)
    plan = load_json(task_dir / 'search-plan.json')
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    digest = review_digest(evidence, candidates, ledger, plan, task, supplement)
    from final_review import enabled as final_enabled, freeze_time_binding, evaluation_at
    if final_enabled(task):
        task['final_review_freeze'] = freeze_time_binding(task, evidence, evaluation_at(task, evidence))
    payload = {'schema': 'IPR-REPORT-REVIEW-FREEZE/1.0', 'task_id': task['task_id'],
        'evidence_digest': digest, 'task': task, 'evidence': evidence,
        'candidates': candidates, 'materiality_ledger': ledger, 'search_plan': plan,
        'supplement': supplement,
        'review_protocol': {'first_review_visible': False, 'second_review_visible': False, 'instruction': (
            'Review current overall, scope and limitations independently; unchanged units may reference each slot own immutable prior receipt.'
            if final_enabled(task) else 'Run both independent reviews against this exact payload; any live input change invalidates both.')}}
    if final_enabled(task):
        payload['assessment_at'] = task['final_review_freeze']['assessment_at']
    return payload


def freeze_input(task_dir: Path, output_path: Path, *, prepared_context=None) -> dict:
    """Export one immutable review payload, but only after the read-only gate passes.

    All plan expansion, source processing, triage, and scope repairs must precede
    this call. The payload is written outside the task directory and bound to the
    exact live digest; a post-read digest check detects concurrent writes.
    """
    from common import atomic_write_json, sha256_json
    from workflow_v24 import _scenario_context, scenario_supplement
    from assessment_estimate import review_digest

    task_dir = Path(task_dir).resolve()
    output_path = Path(output_path).expanduser().resolve()
    if output_path.exists():
        raise ValueError('REVIEW_FREEZE_OUTPUT_EXISTS')
    if prepared_context is not None and type(prepared_context) is not PreparedReviewContext:
        raise ValueError('REVIEW_PREPARED_CONTEXT_NOT_ISSUED')
    gate = prepared_context.validate(task_dir) if prepared_context is not None else readiness(task_dir)
    if not gate['ready']:
        raise ValueError('REVIEW_INPUT_NOT_READY: resolve current blockers before freezing')
    task = load_json(task_dir / 'task.json')
    candidates, ledger, evidence = _scenario_context(task_dir, task)
    plan = load_json(task_dir / 'search-plan.json')
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    digest = review_digest(evidence, candidates, ledger, plan, task, supplement)
    if digest != gate['input_digest']:
        raise ValueError('REVIEW_FREEZE_INPUT_CHANGED_DURING_EXPORT')
    from final_review import enabled as final_enabled, freeze_time_binding
    if final_enabled(task):
        # This cache is deliberately excluded from the semantic review digest.
        # Existing matching freezes keep their original assessment instant.
        from final_review import evaluation_at
        if load_json(task_dir / 'task.json') != task or current_digest(task_dir) != digest:
            raise ValueError('REVIEW_FREEZE_INPUT_CHANGED_DURING_EXPORT')
        task['final_review_freeze'] = freeze_time_binding(task, evidence, evaluation_at(task, evidence))
        atomic_write_json(task_dir / 'task.json', task)
    payload = {'schema': 'IPR-REPORT-REVIEW-FREEZE/1.0', 'task_id': task['task_id'],
        'evidence_digest': digest, 'task': task, 'evidence': evidence,
        'candidates': candidates, 'materiality_ledger': ledger, 'search_plan': plan,
        'supplement': supplement,
        'review_protocol': {'first_review_visible': False,
            'second_review_visible': False,
            'instruction': ('Review current overall, scope and limitations independently; unchanged units may reference each slot own immutable prior receipt.'
                if final_enabled(task) else 'Run both independent reviews against this exact payload; any live input change invalidates both.')}}
    if final_enabled(task):
        payload['assessment_at'] = task['final_review_freeze']['assessment_at']
    # Refuse if any reviewed input changes while the payload is being assembled.
    if current_digest(task_dir) != digest:
        raise ValueError('REVIEW_FREEZE_INPUT_CHANGED_DURING_EXPORT')
    if prepared_context is not None:
        prepared_context.validate(task_dir)
    atomic_write_json(output_path, payload)
    if current_digest(task_dir) != digest:
        output_path.unlink(missing_ok=True)
        raise ValueError('REVIEW_FREEZE_INPUT_CHANGED_DURING_EXPORT')
    if prepared_context is not None:
        prepared_context.validate(task_dir)
        prepared_context.bind_freeze(output_path)
    return {'ready': True, 'input_digest': digest, 'frozen_input': str(output_path),
            'payload_sha256': sha256_json(payload)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--freeze-output', type=Path,
                        help='Export a new review payload only when readiness is true; never overwrite.')
    args = parser.parse_args()
    import json
    result = (freeze_input(args.task_dir.resolve(), args.freeze_output.resolve())
              if args.freeze_output else readiness(args.task_dir.resolve()))
    if args.output:
        from common import atomic_write_json
        atomic_write_json(args.output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['ready'] else 1)


if __name__ == '__main__':
    main()
