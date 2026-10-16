"""Real offline review-to-publication checks; only the native model is synthetic."""
from copy import copy, deepcopy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
from offline_test_support import isolated_test_environment


def native_publication(directory, *, before_publish=None, reuse_previous=False):
    """Attach actual host-audited turns to the existing complete delivery fixture."""
    import publish_report
    from module_review import run_module_pair
    from record_independent_review import expand_pending
    from review_readiness import prepare_review_context, freeze_input
    from test_evidence_delivery_integration import build_evidence_delivery_fixture
    publish = publish_report.publish
    def with_host(source, first, second, **options):
        source = Path(source)
        task = load_json(source / 'task.json')
        task['final_review_execution_revision'] = 'module-double-review-v1'
        atomic_write_json(source / 'task.json', task)
        payloads = [load_json(Path(path)) for path in (first, second)]
        from review_progress_stage_a import record_event
        record_event(source, {'kind': 'initialize', 'items': [], 'actor': 'offline-test',
                              'reasoning': 'Initialize offline native review fixture.'})
        out = source / 'native-review'; out.mkdir()
        binary = source / 'offline-native'; binary.write_bytes(b'not executed')
        context = prepare_review_context(source)
        meta = freeze_input(source, out / 'frozen-input.json', prepared_context=context)
        frozen = load_json(out / 'frozen-input.json')
        lock, calls = threading.Lock(), []
        def native(command, prompt, workspace, trace_path, stderr_path, timeout):
            chain, group = trace_path.parent.parent.name, trace_path.parent.name
            with lock:
                calls.append((chain, group)); number = len(calls)
            packet = load_json(trace_path.parent / 'packet.json')
            base = payloads[int(chain) - 1]
            raw = {key: deepcopy(base[key]) for key in
                   ('reviewer', 'coverage_confidence_cap', 'coverage_confidence_reasoning')}
            raw.update(assessments=[], future_applications=[], enforcement_signals=[],
                final_review_statement=deepcopy(base['review_context']['final_review']['statement']))
            if group == 'summary':
                raw['module_review_digests'] = [sha256_json(row) for row in packet['modules']]
            else:
                raw['assessments'] = [expand_pending(row, task) for row in base['assessments']
                    if row['right_type'] in packet['module_scope']['right_types']]
                from module_review import required_scopes
                identities = {tuple(row.get(key) for key in ('scenario_id', 'jurisdiction', 'right_type'))
                              for row in raw['assessments']}
                for scope in required_scopes(task, set(packet['module_scope']['right_types'])):
                    if tuple(scope[key] for key in ('scenario_id', 'jurisdiction', 'right_type')) not in identities:
                        raw['assessments'].append(expand_pending({**scope, 'assessment_status': 'pending',
                            'risk': None, 'pending_reasoning': 'Retain the unassessed offline scope.',
                            'evidence_refs': ['EV-PUBLIC']}, task))
                raw['material_observations'] = {row['material_id']: {
                    'source_refs': row['source_refs'], 'observation': 'Read the retained synthetic original.',
                    'limitations': 'Offline fixture; no real legal finding.'}
                    for row in packet['retained_originals']['materials']}
                if packet.get('review_reuse'):
                    raw['reused_unit_ids'] = packet['review_reuse']['reusable_unit_ids']
                    raw['assessments'] = []
            events = [{'type': 'thread.started', 'thread_id': 'offline-publication-' + str(number)},
                {'type': 'turn.started'}, {'type': 'item.completed', 'item': {
                    'type': 'agent_message', 'text': json.dumps(raw)}}, {'type': 'turn.completed'}]
            text = '\n'.join(json.dumps(event) for event in events) + '\n'
            trace_path.write_text(text, encoding='utf-8'); stderr_path.write_bytes(b'')
            atomic_write_json(trace_path.with_suffix('.execution.json'), {
                'schema': 'OFFLINE-OBSERVATION-FIXTURE', 'process_id': 50000 + number})
            return SimpleNamespace(returncode=0, pid=50000 + number), text, ''
        with patch('report_review_host.run_native_logged', side_effect=native), \
                patch('native_review_jobs._probe', return_value=[]), \
                patch('macos_review_host.require_chatgpt_auth'):
            paths = run_module_pair(source, out, binary, frozen, meta, context, timeout=10,
                max_parallel=2, isolation='macos-sandbox')
            if reuse_previous:
                previous = paths
                out = source / 'reused-native-review'; out.mkdir()
                paths = run_module_pair(source, out, binary, frozen, meta, context, timeout=10,
                    max_parallel=2, isolation='macos-sandbox', previous_first=previous[0], previous_second=previous[1])
        chief = load_json(options['adjudication'])
        chief['review_context']['evidence_digest'] = frozen['evidence_digest']
        chief['review_refs'] = dict(zip(('first', 'second'), [sha256_json(load_json(path)) for path in paths]))
        atomic_write_json(options['adjudication'], chief)
        if before_publish:
            before_publish(source, out, paths)
        return publish(source, *paths, **options)
    with isolated_test_environment(), patch.object(publish_report, 'publish', side_effect=with_host):
        return build_evidence_delivery_fixture(directory, operator_policy=True, transaction=True)


class ReviewPublicationTests(unittest.TestCase):
    def test_native_reviews_publish_with_one_semantic_check(self):
        import report_estimate
        with tempfile.TemporaryDirectory(prefix='ipr-native-publication-') as tmp:
            with patch.object(report_estimate, 'validate_run', wraps=report_estimate.validate_run) as check:
                result = native_publication(Path(tmp) / 'task')
            self.assertEqual(check.call_count, 1)
            self.assertEqual(result['transaction']['completion']['status'], 'limited_round_closed')
            self.assertEqual(result['transaction']['validation_transaction']['semantic_checks'], 1)

    def test_changed_native_trace_after_copy_rejects_delivery(self):
        import delivery_versions_stage_e as versions
        with tempfile.TemporaryDirectory(prefix='ipr-native-publish-change-') as tmp:
            directory = Path(tmp) / 'task'
            original_copy = versions._copy_files
            def changed_copy(build, destination, files):
                original_copy(build, destination, files)
                (directory / 'native-review/1/technical/events.jsonl').write_bytes(b'changed trace')
            with patch.object(versions, '_copy_files', side_effect=changed_copy):
                with self.assertRaisesRegex(ValueError, 'DELIVERY_TRANSACTION_ENTRY_FAILED'):
                    native_publication(directory)
            journal = load_json(directory / versions.JOURNAL)
            self.assertEqual(journal['versions'][-1]['state'], 'delivery_failed')
            self.assertFalse((Path(tmp) / 'task-delivered-completion.json').exists())

    def test_every_checked_dependency_is_bound_without_changing_old_snapshot(self):
        import delivery_validation as validation
        from delivery_versions_stage_e import _snapshot
        from completion_check import check_completion
        contexts = []
        original = validation.begin
        def begin(*args, **kwargs):
            context = original(*args, **kwargs); contexts.append(context); return context
        with tempfile.TemporaryDirectory(prefix='ipr-native-dependencies-') as tmp:
            directory = Path(tmp).resolve() / '中文 task'
            with patch.object(validation, 'begin', side_effect=begin):
                result = native_publication(directory)
            context = contexts[0]
            self.assertEqual(context._snapshot, _snapshot(directory, context._reviews))
            audit = load_json(directory / 'native-review/1/technical/audit.json')
            paths = [directory / 'native-review/1/technical/audit.json']
            paths += [Path(audit[key + '_path']) for key in
                      ('trace', 'packet', 'prompt', 'judgment', 'profile', 'execution_observation')]
            paths += [Path(row['path']) for row in audit['image_manifest']]
            self.assertGreater(len(paths), 7)
            for path in paths:
                self.assertIn(str(path.absolute()), context._review_dependencies)
                body = path.read_bytes()
                for change in ('modify', 'delete'):
                    with self.subTest(file=path.name, change=change):
                        # Independent fault branches of the same verified inputs;
                        # a rejected branch cannot revive after restoring bytes.
                        branch = copy(context)
                        try:
                            if change == 'modify': path.write_bytes(body + b'changed')
                            else: path.unlink()
                            self.assertIn('DELIVERY_REVIEW_DEPENDENCY_CHANGED', branch.verify(result['delivered']))
                        finally:
                            path.write_bytes(body)
                        self.assertIn('DELIVERY_REVIEW_DEPENDENCY_CHANGED', branch.verify(result['delivered']))
                self.assertEqual(context.verify(result['delivered']), [])
            # Uncached completion remains an independent real validation path.
            trace = Path(audit['trace_path']); trace.write_bytes(b'changed trace')
            args = dict(first_review=directory/'native-review/1/review.json',
                        second_review=directory/'native-review/2/review.json',
                        adjudication=directory/'adjudication.json', output_dir=result['delivered'])
            for options in ({}, {'validation_context': context}):
                with self.assertRaisesRegex(ValueError, 'TRACE_CHANGED|DEPENDENCY_CHANGED'):
                    check_completion(directory, **args, **options)

    def test_change_at_end_of_semantic_check_cannot_bind_context(self):
        import report_estimate
        actual = report_estimate.validate_run
        with tempfile.TemporaryDirectory(prefix='ipr-native-during-validation-') as tmp:
            directory = Path(tmp) / 'task'
            def changed(*args, **kwargs):
                errors = actual(*args, **kwargs)
                self.assertEqual(errors, [])
                (directory / 'native-review/1/technical/prompt.txt').write_bytes(b'changed')
                return errors
            with patch.object(report_estimate, 'validate_run', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'DEPENDENCY_CHANGED'):
                    native_publication(directory)
            self.assertFalse((Path(tmp) / 'task-delivered-completion.json').exists())

    def test_change_before_completion_invalidates_cached_work_view(self):
        import completion_check
        actual = completion_check.check_completion
        with tempfile.TemporaryDirectory(prefix='ipr-native-before-completion-') as tmp:
            directory = Path(tmp) / 'task'
            def changed(*args, **kwargs):
                (directory / 'native-review/2/expression/events.jsonl').write_bytes(b'changed')
                return actual(*args, **kwargs)
            with patch.object(completion_check, 'check_completion', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'DEPENDENCY_CHANGED'):
                    native_publication(directory)
            self.assertFalse((Path(tmp) / 'task-delivered-completion.json').exists())

    def test_reused_previous_review_dependencies_are_collected_recursively(self):
        import delivery_validation as validation
        contexts = []
        original = validation.begin
        def begin(*args, **kwargs):
            context = original(*args, **kwargs); contexts.append(context); return context
        with tempfile.TemporaryDirectory(prefix='ipr-previous-review-dependency-') as tmp:
            directory = Path(tmp) / 'task'
            with patch.object(validation, 'begin', side_effect=begin):
                result = native_publication(directory, reuse_previous=True)
            context = contexts[0]
            old = directory.resolve() / 'native-review/1/technical/events.jsonl'
            self.assertIn(str(old.absolute()), context._review_dependencies)
            review = load_json(directory / 'reused-native-review/1/review.json')
            self.assertTrue(review['review_context']['final_review']['reused_unit_ids'])
            old.unlink()
            self.assertIn('DELIVERY_REVIEW_DEPENDENCY_CHANGED', context.verify(result['delivered']))


if __name__ == '__main__':
    unittest.main()
