"""Full-report host rejects tool traces and probes both workspace boundaries."""
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from report_review_host import (_probe, parse_agent_trace, review_payload_view, review_prompt,
                               review_transport_view, restore_review_transport, native_review_command,
                               run_native_logged, run_native_pair_logged, seal_review_job, validate_review_job)


class SentMaterialContractTests(unittest.TestCase):
    def setUp(self):
        from common import atomic_write_json, sha256_bytes
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        host_dir, workspace = self.root / 'host', self.root / 'workspace'
        host_dir.mkdir(); workspace.mkdir()
        self.packet = {'retained_originals': {'revision': 'public-originals-v2', 'materials': []}, 'exact_fact': '原文'}
        self.images = {'M1.png': b'actual registered image bytes'}
        self.job = {'packet_path': host_dir / 'packet.json', 'prompt_path': host_dir / 'prompt.txt',
            'profile': host_dir / 'sandbox.sb', 'workspace': workspace, 'prompt': 'exact prompt',
            'command': ['fake'], 'trace_path': host_dir / 'events.jsonl', 'stderr_path': host_dir / 'stderr.log',
            'image_manifest': [{'name': 'M1.png', 'path': str(host_dir / 'M1.png'), 'sha256': sha256_bytes(self.images['M1.png'])}]}
        atomic_write_json(self.job['packet_path'], self.packet)
        atomic_write_json(workspace / 'frozen-input.json', review_transport_view(self.packet))
        self.job['prompt_path'].write_text(self.job['prompt'], encoding='utf-8')
        self.job['profile'].write_text('exact profile')
        for path in [host_dir / 'M1.png', workspace / 'M1.png']:
            path.write_bytes(self.images['M1.png'])

    def test_every_sent_artifact_changed_or_removed_is_rejected_before_dispatch(self):
        import module_review
        seal_review_job(self.job, self.packet, self.images)
        for path, digest in self.job['material_contract']:
            data = path.read_bytes()
            for replacement in (b'changed', None):
                with self.subTest(path=path.name, replacement=replacement):
                    if replacement is None: path.unlink()
                    else: path.write_bytes(replacement)
                    with patch('report_review_host.run_native_logged') as native:
                        with self.assertRaisesRegex(ValueError, 'SENT_MATERIAL_CHANGED'):
                            module_review.run_jobs([self.job], 30, 1)
                        native.assert_not_called()
                    path.write_bytes(data)
        self.assertEqual(validate_review_job(self.job), self.packet)

    def test_preparation_cannot_redefine_the_in_memory_packet_contract(self):
        from common import atomic_write_json
        changed = dict(self.packet, exact_fact='substituted')
        atomic_write_json(self.job['packet_path'], changed)
        with self.assertRaisesRegex(ValueError, 'SENT_MATERIAL_CHANGED'):
            seal_review_job(self.job, self.packet, self.images)

    def test_packet_parser_uses_checked_bytes_even_if_disk_changes_after_read(self):
        from common import atomic_write_json
        seal_review_job(self.job, self.packet, self.images)
        read = Path.read_bytes
        hits = []
        def captured(path):
            data = read(path)
            if path == self.job['packet_path']:
                hits.append(str(path))
                atomic_write_json(path, dict(self.packet, exact_fact='later disk value'))
            return data
        with patch.object(Path, 'read_bytes', captured):
            self.assertEqual(validate_review_job(self.job), self.packet)
        self.assertEqual(len(hits), 1)
        with self.assertRaisesRegex(ValueError, 'SENT_MATERIAL_CHANGED'):
            validate_review_job(self.job)


class AssessmentStatusContractTests(unittest.TestCase):
    @staticmethod
    def contract(payload, number):
        prompt = review_prompt(payload, number)
        contract = json.loads(prompt.split('\n输出契约：\n', 1)[1].split('\n材料包（审阅位 ', 1)[0])
        return prompt, contract

    def setUp(self):
        import test_module_review as fixtures
        from common import CURRENT_SCHEMA_VERSION, RECALL_INTEGRITY_REVISION
        self.fixture = fixtures.ModuleReviewTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.task = dict(self.fixture.task, schema_version=CURRENT_SCHEMA_VERSION,
                         screening_revision=RECALL_INTEGRITY_REVISION)
        self.row = self.fixture.legal_record()['judgment']['assessments'][0]

    def validate(self, row):
        from assessment_estimate import _validate_row
        _validate_row(row, {'E'}, {}, {'US'}, self.task)

    def test_status_values_are_explicit_in_both_routes_and_review_slots(self):
        for module in (None, {'right_types': ['patent', 'utility_model'], 'required_scopes': []}):
            for number in (1, 2):
                payload = {'task': self.task}
                if module: payload['module_scope'] = module
                with self.subTest(module=module, number=number):
                    prompt, contract = self.contract(payload, number)
                    self.assertEqual(contract['assessment_status_values'], ['pending', 'assessed'])
                    self.assertIn('不能使用completed', prompt)
                    self.assertIn('必须显式填写', prompt)

    def test_contract_distinguishes_null_risk_exceptions_and_applicability(self):
        _, contract = self.contract({'task': self.task}, 1)
        self.assertEqual(contract['assessment_status_rules']['pending']['risk'], None)
        self.assertIn('pending_reasoning', contract['assessment_status_rules']['pending'])
        assessed = contract['assessment_status_rules']['assessed']
        self.assertEqual(assessed['current_risk_values'], ['极低', '低', '中', '高', '极高'])
        self.assertIn('decision_workflow_revision=scenario-triage-v1', assessed['reviewed_signal'])
        self.assertIn('and (future_signal:true or signal_only:true)', assessed['reviewed_signal'])
        self.assertIn('task', assessed['out_of_scope'])
        self.assertEqual(contract['scope_applicability_status_values'],
                         ['applicable', 'not_applicable', 'unassessed'])

    def test_assessed_grade_and_pending_null_still_pass_strict_validator(self):
        self.validate(self.row)
        pending = dict(self.row, assessment_status='pending', risk=None,
                       pending_reasoning='Necessary original has not been obtained', evidence_refs=[])
        self.validate(pending)
        for bad in (dict(pending, risk='低'), dict(pending, pending_reasoning=''),
                    dict(self.row, risk=None)):
            with self.subTest(row=bad), self.assertRaises(ValueError): self.validate(bad)

    def test_invented_status_rejected_without_rewriting_row(self):
        from copy import deepcopy
        for status in ('completed', 'success', 'not_applicable', '', True):
            bad = dict(self.row, assessment_status=status); original = deepcopy(bad)
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'ASSESSMENT_STATUS_INVALID'):
                self.validate(bad)
            self.assertEqual(bad, original)
        # Historical compatibility remains unchanged; new prompts require an explicit enum.
        self.validate(dict(self.row, assessment_status=None))

    def test_institutional_applicability_requires_evidence_and_is_not_a_status(self):
        row = dict(self.row, scope_applicability={'status': 'not_applicable',
                    'reasoning': 'Synthetic institutional source', 'evidence_refs': ['E']})
        self.validate(row)
        for status, refs in (('not_applicable', []), ('completed', ['E'])):
            bad = dict(row, scope_applicability={'status': status, 'reasoning': 'Synthetic', 'evidence_refs': refs})
            with self.subTest(status=status, refs=refs), self.assertRaisesRegex(ValueError, 'ASSESSMENT_SCOPE_APPLICABILITY_INVALID'):
                self.validate(bad)


class ReportReviewHostTests(unittest.TestCase):
    def test_pair_starts_both_isolated_jobs_once_and_retains_order(self):
        barrier = threading.Barrier(2)
        calls = []
        jobs = [{'command': [str(i)], 'prompt': 'same frozen input',
            'workspace': Path('/workspace-' + str(i)), 'trace_path': Path('/trace-' + str(i)),
            'stderr_path': Path('/stderr-' + str(i))} for i in (1, 2)]
        def execute(command, prompt, workspace, trace, errors, timeout):
            calls.append((command, prompt, workspace))
            barrier.wait(timeout=2)
            return command[0], str(trace), str(errors)
        with patch('report_review_host.run_native_logged', side_effect=execute):
            result = run_native_pair_logged(jobs, 30)
        self.assertEqual([row[0] for row in result], ['1', '2'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len({row[2] for row in calls}), 2)
        self.assertEqual({row[1] for row in calls}, {'same frozen input'})
        with self.assertRaisesRegex(ValueError, 'TWO_JOBS_REQUIRED'):
            run_native_pair_logged(jobs[:1], 30)

    def test_failed_and_timed_out_execution_preserves_live_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace, errors = root / 'events', root / 'errors'
            command = [sys.executable, '-c',
                'import sys; print("partial", flush=True); print("failure", file=sys.stderr, flush=True); sys.exit(1)']
            proc, stdout, stderr = run_native_logged(command, '', root, trace, errors, 5)
            self.assertEqual((proc.returncode, stdout.strip(), stderr.strip()), (1, 'partial', 'failure'))
            command = [sys.executable, '-c',
                'import time; print("partial", flush=True); time.sleep(20)']
            with self.assertRaisesRegex(ValueError, 'TIMEOUT_NO_AUTOMATIC_RETRY'):
                run_native_logged(command, '', root, trace, errors, 0.2)
            self.assertEqual(trace.read_text().strip(), 'partial')

    def test_https_connection_keeps_auth_and_disables_tools_and_retries(self):
        command = native_review_command(Path('/native'), Path('/profile'), Path('/workspace'))
        self.assertIn('model_providers.ipr_chatgpt_https.supports_websockets=false', command)
        self.assertIn('model_providers.ipr_chatgpt_https.requires_openai_auth=true', command)
        self.assertIn('model_context_window=872000', command)
        self.assertIn('model_auto_compact_token_limit=800000', command)
        self.assertIn('model_providers.ipr_chatgpt_https.stream_max_retries=0', command)
        self.assertIn('model_providers.ipr_chatgpt_https.request_max_retries=0', command)
        self.assertIn('--ignore-user-config', command)
        self.assertIn('shell_tool', command)
        self.assertNotIn('OPENAI_API_KEY', ' '.join(command))

    def test_only_exact_disabled_tool_notice_before_turn_is_accepted(self):
        payload = {'assessments': []}
        notice = {'type': 'item.completed', 'item': {'type': 'error', 'message':
            'Code Mode is unavailable because code-mode host is disabled. '
            'Code mode will fail closed; enable `features.code_mode_host` '
            'and install `codex-code-mode-host`.'}}
        start = {'type': 'thread.started', 'thread_id': 'S1'}
        turn = {'type': 'turn.started'}
        end = [{'type': 'item.completed', 'item': {'type': 'agent_message',
                'text': json.dumps(payload)}}, {'type': 'turn.completed'}]
        encode = lambda rows: '\n'.join(json.dumps(row) for row in rows)
        self.assertEqual(parse_agent_trace(encode([start, notice, turn] + end)), ('S1', payload))
        with self.assertRaisesRegex(ValueError, 'AGENT_ERROR'):
            parse_agent_trace(encode([start, turn, notice] + end))
        notice['item']['message'] = 'request timed out'
        with self.assertRaisesRegex(ValueError, 'AGENT_ERROR'):
            parse_agent_trace(encode([start, notice, turn] + end))

    def test_shared_transport_roundtrip_preserves_every_value_and_reference(self):
        repeated = {'evidence_id': 'EV-ACTUAL', 'reasoning': 'current original source ' * 20,
                    'nested': ['retained history ' * 20]}
        payload = {'task': {'assessment_scenarios': []}, 'evidence_digest': 'EXACT',
                   'evidence': [repeated, repeated, {'unknown': True, 'count': 0, 'missing': None}]}
        encoded = review_transport_view(payload)
        self.assertEqual(restore_review_transport(encoded), review_payload_view(payload))
        self.assertTrue(encoded['shared_values'])
        self.assertLess(len(json.dumps(encoded)), len(json.dumps(payload)))
        with self.assertRaisesRegex(ValueError, 'REFERENCE_INVALID'):
            restore_review_transport({'encoding': 'IPR-SHARED-VALUES/1.0',
                'materials': {'$v': 'V1'}, 'shared_values': {'V1': {'$v': 'V1'}}})
        with self.assertRaisesRegex(ValueError, 'RESERVED_KEY'):
            review_transport_view({'source': {'$v': 'literal'}})

    def test_v2_shape_sharing_fits_large_material_without_fact_loss(self):
        fields = ['actual_full_field_name_' + str(index) + '_original_source_reference'
                  for index in range(30)]
        records = [{key: 'actual-source-' + str(row) + '-' + str(index)
                    for index, key in enumerate(fields)} for row in range(600)]
        payload = {'evidence_digest': 'UNCHANGED', 'history': records}
        original = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        encoded = review_transport_view(payload)
        wire = json.dumps(encoded, ensure_ascii=False, separators=(',', ':'))
        self.assertGreater(len(original), 1048576)
        self.assertLess(len(wire), 1048576)
        self.assertEqual(encoded['encoding'], 'IPR-SHARED-VALUES/2.0')
        self.assertEqual(restore_review_transport(encoded), payload)
        self.assertTrue(any(shape == sorted(fields) for shape in encoded['shared_shapes']))
        self.assertEqual(review_transport_view(payload), encoded)

    def test_v2_literal_markers_nested_arrays_and_primitive_types_roundtrip(self):
        payload = {'evidence_digest': 'ORIGINAL', 'literal': '$12345678901234567',
                   'again': '$12345678901234567', 'unicode': '$²',
                   'arrays': [['@', 4, {'original': True}], ['!', '$7'],
                              ['!', ['@', None]], [], [False, 0, None, '']],
                   'ordinary': {'@': 'real field', '!': 'real field'}}
        self.assertEqual(restore_review_transport(review_transport_view(payload)), payload)

    def test_v2_rejects_cycle_missing_reference_and_invalid_shapes(self):
        def wire(materials, values=None, shapes=None):
            return {'encoding': 'IPR-SHARED-VALUES/2.0', 'materials': materials,
                    'shared_values': values or [], 'shared_shapes': shapes or []}
        for value in (wire('$0'), wire('$0', ['$1', '$0'])):
            with self.assertRaisesRegex(ValueError, 'REFERENCE_INVALID'):
                restore_review_transport(value)
        for value in (wire(['@', 0]), wire(['@', True], shapes=[[]]),
                      wire(['@', 0, 1], shapes=[['a', 'b']]),
                      wire(['@', 0, 1, 2], shapes=[['a', 'a']])):
            with self.assertRaisesRegex(ValueError, 'SHAPE_INVALID'):
                restore_review_transport(value)
        with self.assertRaisesRegex(ValueError, 'ESCAPE_INVALID'):
            restore_review_transport(wire(['!', {'not': 'a literal escape'}]))

    def test_legacy_shared_value_decode_keeps_original_contract(self):
        value = {'evidence_digest': 'LEGACY', 'original': {'$v': 'V1'}}
        transport = {'encoding': 'IPR-SHARED-VALUES/1.0', 'materials': value,
                     'shared_values': {'V1': {'evidence_id': 'EV-ACTUAL', 'unknown': True}}}
        self.assertEqual(restore_review_transport(transport),
                         {'evidence_digest': 'LEGACY',
                          'original': {'evidence_id': 'EV-ACTUAL', 'unknown': True}})

    def test_partial_unit_source_cannot_be_used_as_a_complete_review(self):
        from assessment_estimate import _validate_review
        with self.assertRaisesRegex(ValueError, 'FINAL_REVIEW_PARTIAL_NOT_PUBLISHABLE'):
            _validate_review({'registration_scope': 'validated_unit_subset'},
                             'D', set(), {}, {'US'}, {})

    def test_prompt_exposes_actual_contract_without_embedded_duplicate_bytes(self):
        from decision_workflow import scenario_sha256
        scenario = {'scenario_id': 'product_entry', 'type': 'product_entry',
                    'title': 'Product', 'assumptions': [], 'conditional': False,
                    'fact_sources': []}
        payload = {'task': {'assessment_scenarios': [scenario]},
                   'evidence': {'image_bytes': 'OMIT-THIS-BINARY', 'text': 'actual evidence'}}
        prompt = review_prompt(payload, 1)
        self.assertIn(scenario_sha256(scenario), prompt)
        self.assertIn('utility_patent', prompt)
        self.assertIn('confidence_basis_keys', prompt)
        self.assertIn('actual evidence', prompt)
        self.assertIn('候选评级只对当前selected范围输出', prompt)
        for field in ('allowed_right_types', 'unique_assessment_scope', 'decisive_exclusion',
                      'future_application_additional_fields', 'supplemental_signal_fields'):
            self.assertIn(field, prompt)
        self.assertNotIn('OMIT-THIS-BINARY', prompt)

    def test_known_findings_prompt_does_not_default_empty_evidence_to_low(self):
        payload = {'task': {'assessment_revision': 'known-findings-risk-v1',
            'assessment_scenarios': []},
            'module_scope': {'right_types': ['trademark_word'], 'required_scopes': []}}
        prompt = review_prompt(payload, 1)
        self.assertIn('没有完成复核的适用风险判断时总体risk:null、风险待定', prompt)
        self.assertIn('证据不足则risk:null/pending', prompt)
        self.assertNotIn('没有具体中/高/极高时运营总体为低风险', prompt)

    def test_review_view_omits_embedded_bytes_but_keeps_digest_and_evidence(self):
        frozen = {'evidence_digest': 'D1', 'evidence': {'collections': {'x': [
            {'evidence_id': 'EV1', 'text': 'retained content', 'result_task': {'old': True},
             'image_bytes': 'secret', 'screenshot_bytes': 'secret', 'base64': 'secret'}]}}}
        view = review_payload_view(frozen)
        row = view['evidence']['collections']['x'][0]
        self.assertEqual(view['evidence_digest'], 'D1')
        self.assertEqual((row['evidence_id'], row['text']), ('EV1', 'retained content'))
        self.assertNotIn('result_task', row)
        self.assertNotIn('image_bytes', row)
        self.assertNotIn('screenshot_bytes', row)
        self.assertNotIn('base64', row)

    def test_trace_accepts_one_finished_agent_message(self):
        payload = {'reviewer': 'independent', 'coverage_confidence_cap': '低',
                   'coverage_confidence_reasoning': 'Coverage limits.', 'assessments': [],
                   'future_applications': [], 'enforcement_signals': []}
        events = [
            {'type': 'thread.started', 'thread_id': 'S1'},
            {'type': 'turn.started'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(payload)}},
            {'type': 'turn.completed'},
        ]
        self.assertEqual(parse_agent_trace('\n'.join(json.dumps(row) for row in events)), ('S1', payload))

    def test_trace_rejects_tools_and_incomplete_turns(self):
        tool = [{'type': 'thread.started', 'thread_id': 'S1'},
                {'type': 'item.started', 'item': {'type': 'shell_tool'}}]
        with self.assertRaisesRegex(ValueError, 'TOOL_ACTIVITY'):
            parse_agent_trace('\n'.join(json.dumps(row) for row in tool))
        incomplete = [{'type': 'thread.started', 'thread_id': 'S1'}]
        with self.assertRaisesRegex(ValueError, 'INCOMPLETE_TRACE'):
            parse_agent_trace(json.dumps(incomplete[0]))

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS sandbox-exec required')
    def test_kernel_denies_peer_task_and_host_output_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, output = root / 'task', root / 'host-output'
            first, second = root / 'workspace-1', root / 'workspace-2'
            for directory in (task, output, first, second, output / '1'):
                directory.mkdir(parents=True, exist_ok=True)
            (task / 'task.json').write_text('{}')
            (first / 'frozen-input.json').write_text('{"frozen":true}')
            (second / 'frozen-input.json').write_text('{"frozen":true}')
            for own, peer, number in ((first, second, '1'), (second, first, '2')):
                controls = _probe(Path('/bin/cat'), own, peer,
                                  task, output)
                self.assertTrue(all(row['readable'] == row['expected_readable']
                                    for row in controls if 'readable' in row))
                self.assertTrue(all(row['writable'] is False for row in controls if 'writable' in row))



class HostObservationTests(unittest.TestCase):
    def execute(self, program, timeout=3):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        trace, errors = root / 'events.jsonl', root / 'stderr.log'
        result = run_native_logged([sys.executable, '-u', '-c', program], '原件', root, trace, errors, timeout)
        return result, json.loads(trace.with_suffix('.execution.json').read_text()), trace

    def test_measured_events_usage_and_exit_are_not_review_success(self):
        events = [{'type':'thread.started','thread_id':'X'}, {'type':'turn.started'},
            {'type':'item.completed','item':{'type':'reasoning','text':'actual'}},
            {'type':'item.completed','item':{'type':'agent_message','text':'{"assessments":[]}'}},
            {'type':'turn.completed','usage':{'input_tokens':123,'output_tokens':10,'reasoning_output_tokens':4}}]
        program = 'import json,time,sys\nsys.stdin.read()\n'
        program += 'events='+repr(events)+'\nfor event in events:\n print(json.dumps(event),flush=True)\n time.sleep(.12)\n'
        (proc, stdout, _), obs, trace = self.execute(program)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(obs['status'], 'process_exited')
        self.assertEqual(obs['review_validation'], 'not_performed')
        self.assertEqual(obs['usage'], events[-1]['usage'])
        self.assertEqual(obs['prompt_utf8_bytes'], 6)
        fields = ['first_event_seconds','turn_started_seconds','first_reasoning_seconds',
                  'first_agent_message_seconds','turn_completed_seconds']
        times = [obs[key] for key in fields]
        self.assertTrue(all(value is not None for value in times))
        self.assertEqual(times, sorted(times))
        self.assertFalse(obs['observer_errors'])
        self.assertEqual(parse_agent_trace(stdout)[0], 'X')

    def test_zero_exit_without_completed_turn_keeps_unknown_usage(self):
        (proc, stdout, _), obs, _ = self.execute('print(\'{"type":"thread.started","thread_id":"X"}\',flush=True)')
        self.assertEqual(obs['status'], 'process_exited')
        self.assertIsNone(obs['usage'])
        self.assertIsNone(obs['first_agent_message_seconds'])
        with self.assertRaisesRegex(ValueError, 'INCOMPLETE_TRACE'):
            parse_agent_trace(stdout)

    def test_split_json_and_malformed_line_are_observed_without_fabricated_usage(self):
        program = 'import sys,time\nprint("bad",flush=True)\nsys.stdout.write(\'{"type":"turn.\');sys.stdout.flush()\ntime.sleep(.15)\nsys.stdout.write(\'completed","usage":{"input_tokens":true,"output_tokens":-1}}\');sys.stdout.flush()'
        (_, stdout, _), obs, _ = self.execute(program)
        self.assertEqual(obs['malformed_lines'], 1)
        self.assertEqual(obs['event_counts'], {'turn.completed': 1})
        self.assertIsNone(obs['usage'])
        self.assertEqual(obs['review_validation'], 'not_performed')

    def test_timeout_preserves_observed_event_and_partial_delivery(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); trace = root/'events.jsonl'; errors = root/'stderr.log'
        program = 'import time\nprint(\'{"type":"thread.started","thread_id":"X"}\',flush=True)\ntime.sleep(20)'
        with self.assertRaisesRegex(ValueError, 'TIMEOUT_NO_AUTOMATIC_RETRY'):
            run_native_logged([sys.executable,'-u','-c',program], '', root, trace, errors, .3)
        obs = json.loads(trace.with_suffix('.execution.json').read_text())
        self.assertEqual(obs['status'], 'timed_out')
        self.assertIsNotNone(obs['first_event_seconds'])
        self.assertIsNotNone(obs['exit_code'])
        self.assertIsNone(obs['usage'])
        self.assertIn('thread.started', trace.read_text())
        self.assertEqual(obs['review_validation'], 'not_performed')

    def test_spawn_failure_and_nonzero_exit_are_distinct(self):
        (_, _, _), obs, _ = self.execute('import sys;sys.exit(7)')
        self.assertEqual((obs['status'],obs['exit_code']), ('process_failed',7))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); trace=root/'events.jsonl'
            # bounded_popen uses a process-group launcher: exec failure is a
            # real nonzero launcher exit, not necessarily a Popen exception.
            proc, _, _ = run_native_logged(['/nonexistent-review-binary'], '', root, trace, root/'errors', 2)
            self.assertNotEqual(proc.returncode, 0)
            with patch('execution_budget.bounded_popen', side_effect=FileNotFoundError), self.assertRaises(FileNotFoundError):
                run_native_logged(['/nonexistent-review-binary'], '', root, trace, root/'errors', 2)
            obs=json.loads(trace.with_suffix('.execution.json').read_text())
            self.assertEqual(obs['status'],'start_failed')
            self.assertIsNone(obs['process_id'])

    def test_running_observation_is_available_before_process_exit(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); trace=root/'events.jsonl'; failures=[]
            program='import time;print(\'{"type":"thread.started","thread_id":"X"}\',flush=True);time.sleep(.7)'
            def run():
                try:run_native_logged([sys.executable,'-u','-c',program],'',root,trace,root/'errors',3)
                except Exception as exc:failures.append(exc)
            thread=threading.Thread(target=run);thread.start()
            try:
                end=time.monotonic()+2; observed=False
                while time.monotonic()<end and thread.is_alive():
                    path=trace.with_suffix('.execution.json')
                    if path.exists():
                        obs=json.loads(path.read_text())
                        if obs['status']=='running' and obs['first_event_seconds'] is not None:
                            observed=True;break
                    time.sleep(.02)
                self.assertTrue(observed)
            finally:thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures,[])

    @unittest.skipIf(sys.platform == 'win32', 'POSIX ignored-SIGTERM grandchild challenge')
    def test_observed_timeout_kills_ignored_sigterm_grandchild(self):
        import os,time,signal,subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pid_path=root/'grandchild.pid';trace=root/'events.jsonl'
            child='import os,signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path("grandchild.pid").write_text(str(os.getpid()));time.sleep(20)'
            program='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(child)+']);print(\'{"type":"turn.started"}\',flush=True);time.sleep(20)'
            pid=None
            try:
                with self.assertRaisesRegex(ValueError,'TIMEOUT_NO_AUTOMATIC_RETRY'):
                    run_native_logged([sys.executable,'-u','-c',program],'',root,trace,root/'errors',.6)
                self.assertTrue(pid_path.is_file())
                pid=int(pid_path.read_text())
                end=time.monotonic()+2;alive=True
                while time.monotonic()<end:
                    result=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
                    alive=bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')
                    if not alive:break
                    time.sleep(.05)
                self.assertFalse(alive,'ignored-SIGTERM grandchild must not keep running')
                obs=json.loads(trace.with_suffix('.execution.json').read_text())
                self.assertEqual(obs['status'],'timed_out')
                self.assertEqual(obs['event_counts'],{'turn.started':1})
                self.assertEqual(obs['review_validation'],'not_performed')
            finally:
                if pid_path.exists():
                    try:os.kill(int(pid_path.read_text()),signal.SIGKILL)
                    except ProcessLookupError:pass


class LegacyOriginalSendingTests(unittest.TestCase):
    def run_fixture(self, root, *, missing_observation=False):
        from contextlib import nullcontext, ExitStack
        from types import SimpleNamespace
        from common import atomic_write_json, sha256_file
        import report_review_host as host
        task=root/'task';task.mkdir(); source=task/'original.json'
        atomic_write_json(source, 'Exact original claim, not metadata')
        image=task/'actual.png';image.write_bytes(b'\x89PNG\r\n\x1a\nactual image fixture')
        sources=[{'evidence_id':'E1','path':str(source),'sha256':sha256_file(source),'bytes':source.stat().st_size,'source_url':'https://official.example/claim'},
                 {'image_id':'IMG1','path':str(image),'sha256':sha256_file(image),'source_url':'https://product.example/image'}]
        frozen={'task':{'assessment_scenarios':[]},'evidence_digest':'D','evidence':{},'supplement':{'evidence':sources},'candidates':{},'materiality_ledger':{},'search_plan':{}}
        def freeze(task,path,**kwargs): atomic_write_json(path,frozen); return {'ready':True}
        captured=[]
        def native(jobs,timeout):
            outcomes=[]
            for i,job in enumerate(jobs):
                captured.append(job)
                packet=json.loads(job['packet_path'].read_text())
                observations={row['material_id']:{'source_refs':row['source_refs'],'observation':'Fixture specific observed content','limitations':'Fixture only'} for row in packet['retained_originals']['materials']}
                raw={'assessments':[], 'material_observations': observations}
                if missing_observation: raw.pop('material_observations')
                events=[{'type':'thread.started','thread_id':str(i)}, {'type':'turn.started'},
                    {'type':'item.completed','item':{'type':'agent_message','text':json.dumps(raw)}}, {'type':'turn.completed'}]
                stdout='\n'.join(json.dumps(row) for row in events)
                job['trace_path'].write_text(stdout)
                outcomes.append((SimpleNamespace(returncode=0,pid=i+100),stdout,''))
            return outcomes
        def build(*args,**kwargs): return {'review_context':{'evidence_digest':'D'}}
        with ExitStack() as stack:
            patches=[patch('review_isolation.select_backend',return_value='macos-sandbox'),
                patch.object(host,'prepare_review_context'),patch.object(host,'freeze_input',freeze),
                patch.object(host,'_probe',return_value=[]),patch.object(host,'require_chatgpt_auth'),
                patch.object(host,'run_native_pair_logged',native),patch.object(host,'build_review',build),
                patch.object(host,'current_digest',return_value='D'),patch('runtime_timing.timed_step',lambda *a:nullcontext())]
            for p in patches:stack.enter_context(p)
            try:
                paths=host._run_pair(task,root/'out',Path(sys.executable),timeout=30)
                return paths,captured
            finally:
                import shutil
                for job in captured: shutil.rmtree(job['workspace'])

    def test_legacy_pair_sends_exact_original_and_images_without_policy_migration(self):
        from common import sha256_file
        with tempfile.TemporaryDirectory() as tmp:
            paths,jobs=self.run_fixture(Path(tmp))
            self.assertEqual(len(paths),2)
            self.assertEqual(len(jobs),2)
            self.assertEqual(len({job['workspace'] for job in jobs}),2)
            for job in jobs:
                packet=json.loads(job['packet_path'].read_text())
                self.assertNotIn('final_review_execution_revision',packet['task'])
                self.assertEqual(packet['evidence_digest'],'D')
                self.assertIn('Exact original claim, not metadata',job['prompt'])
                self.assertIn('material_observations',job['prompt'])
                self.assertIn('--image',job['command'])
                self.assertEqual(len(job['image_manifest']),1)
                row=job['image_manifest'][0]
                self.assertEqual(row['sha256'],sha256_file(Path(row['path'])))
                self.assertEqual(restore_review_transport(review_transport_view(packet)),review_payload_view(packet))

    def test_finished_native_pair_without_original_observations_cannot_publish_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaisesRegex(ValueError,'ORIGINAL_OBSERVATIONS_REQUIRED'):
                self.run_fixture(root,missing_observation=True)
            self.assertTrue((root/'out/1/agent-judgment.json').is_file())
            self.assertFalse((root/'out/1/review.json').exists())
            self.assertFalse((root/'out/freeze-receipt.json').exists())


if __name__ == '__main__':
    unittest.main()
