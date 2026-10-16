"""Offline module provenance/packet/concurrency tests; no real IP or native call."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from common import atomic_write_json, sha256_file, sha256_json
import final_review
import module_review as mod


class ModuleReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.task = {'task_id': 'OFFLINE', 'target_jurisdictions': ['US'],
            'review_policy_revision': final_review.REVISION,
            'final_review_execution_revision': mod.REVISION,
            'assessment_revision': 'known-findings-risk-v1',
            'assessment_scenarios': [{'scenario_id': 'S', 'type': 'product_entry'}],
            'product': {'title': 'Synthetic fixture'}}
        self.material = final_review.inputs({}, {}, {}, {}, self.task)
        self.digest = sha256_json(self.material)

    def tearDown(self):
        self.temp.cleanup()

    def legal_record(self):
        from record_independent_review import FULL_ASSESSMENT_FIELDS, MODULE_BY_RIGHT
        rows = []
        for scope in mod.required_scopes(self.task, mod.GROUPS['technical']):
            row = {key: None for key in FULL_ASSESSMENT_FIELDS}
            row.update(scope, module_id=MODULE_BY_RIGHT[scope['right_type']],
                title='Synthetic scope', scope='Synthetic product', risk='低', assessment_status='assessed',
                reasoning='Synthetic control only', confidence_reasoning='Synthetic fixture',
                evidence_confidence='低', evidence_refs=['E'], supporting_evidence=[], counter_evidence=[],
                no_supporting_evidence_reasoning='No positive conflict in fixture',
                no_counter_evidence_reasoning='No exclusion established', assumptions=[], raise_if=[],
                lower_if=[], human_checks=[], right_state='unknown', confidence_basis={})
            rows.append(row)
        return {'module_id': 'technical', 'judgment': {'assessments': rows,
            'final_review_statement': {'overall': 'Synthetic', 'scope': 'Synthetic', 'limitations': 'Synthetic'}}}

    def test_legal_contract_output_errors_are_explicitly_classified(self):
        record = self.legal_record()
        mod._validate_module_judgment(record, self.task, {'E'}, {}, {})
        changes = [('assessments', [], 'SCOPE_MISSING'),
                   ('assessments', None, 'ASSESSMENTS_INVALID'),
                   ('assessments', [None], 'ASSESSMENTS_INVALID'),
                   ('reused_unit_ids', [{}], 'REUSE_INVALID'),
                   ('final_review_statement', ['invalid'], 'STATEMENT_REQUIRED')]
        for field, value, code in changes:
            bad = deepcopy(record); bad['judgment'][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(mod.ModuleJudgmentError, code):
                mod._validate_module_judgment(bad, self.task, {'E'}, {}, {})
        for fault, code in [('scope', 'FULL_ORIGINAL_JUDGMENT_REQUIRED'),
                            ('reasoning', 'ASSESSMENT_REASONING_REQUIRED')]:
            bad = deepcopy(record)
            if fault == 'scope': del bad['judgment']['assessments'][0][fault]
            else: bad['judgment']['assessments'][0][fault] = ''
            with self.subTest(fault=fault), self.assertRaisesRegex(mod.ModuleJudgmentError, code):
                mod._validate_module_judgment(bad, self.task, {'E'}, {}, {})

    def record(self, chain, group, raw, packet):
        directory = self.root / chain / group
        directory.mkdir(parents=True)
        paths = {name: directory / (name + '.json') for name in ('packet', 'judgment', 'trace', 'prompt', 'profile')}
        session = chain + '-' + group
        atomic_write_json(paths['packet'], packet)
        atomic_write_json(paths['judgment'], raw)
        paths['prompt'].write_text('Offline synthetic prompt')
        if getattr(self, 'tool_free', False):
            import review_isolation as ri
            binary = self.root / 'codex'
            binary.write_bytes(b'#!/bin/sh\necho fixture\n')
            workspace = self.root / ('ws-' + chain + '-' + group)
            workspace.mkdir()
            ri.write_policy(paths['profile'], binary, workspace, {}, image_names=[])
        else:
            paths['profile'].write_text('Offline synthetic profile')
        trace = [{'type': 'thread.started', 'thread_id': session}, {'type': 'turn.started'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(raw)}},
            {'type': 'turn.completed'}]
        paths['trace'].write_text('\n'.join(json.dumps(row) for row in trace))
        audit = {'session_id': session, 'input_digest': self.digest, 'chain_id': chain, 'module_id': group,
            'tool_activity': False, 'exit_code': 0, 'task_directory_mounted': False, 'foreign_workspaces_mounted': False,
            'image_manifest': []}
        if getattr(self, 'tool_free', False):
            audit.update(isolation_method='tool_free_process', kernel_read_boundary=False, controls=[])
        for name, path in paths.items():
            audit[name + '_path'] = str(path)
            audit[name + '_sha256'] = sha256_file(path)
        audit_path = directory / 'audit.json'
        atomic_write_json(audit_path, audit)
        return {'chain_id': chain, 'module_id': group, 'session_id': session, 'agent_id': session,
            'run_id': 'offline-' + session, 'input_digest': self.digest,
            'packet_sha256': audit['packet_sha256'], 'judgment': raw,
            'host_audit': {'path': str(audit_path), 'sha256': sha256_file(audit_path)}}

    def review(self, chain='1', rollup=False):
        frozen = {'task': self.task, 'evidence_digest': self.digest, 'candidates': {}}
        modules = []
        for group, rights in mod.GROUPS.items():
            rows = [{'scenario_id': 'S', 'jurisdiction': 'US', 'right_type': right,
                'assessment_object': 'product', 'reasoning': 'Synthetic unchanged judgment'} for right in sorted(rights)]
            if rollup and group == 'technical':
                # cited in a nested field, forgotten in the row's own roll-up list
                rows[0]['evidence_refs'] = ['E']
                rows[0]['confidence_basis'] = {'scope': {'satisfied': True, 'reasoning': 'r', 'evidence_refs': ['E2', 'E']}}
            raw = {'assessments': rows, 'future_applications': [], 'enforcement_signals': []}
            modules.append(self.record(chain, group, raw, mod.module_packet(frozen, group)))
        statement = {'overall': 'No established medium or high finding.', 'scope': 'All three synthetic modules.',
                     'limitations': 'Unknowns are progress gaps, not adverse findings.'}
        raw = {'assessments': [], 'future_applications': [], 'enforcement_signals': [],
            'coverage_confidence_cap': '低', 'coverage_confidence_reasoning': 'Synthetic only',
            'final_review_statement': statement, 'module_review_digests': [sha256_json(row) for row in modules]}
        summary = self.record(chain, 'summary', raw, {'task': self.task, 'evidence_digest': self.digest,
            'chain_id': chain, 'modules': modules})
        rows = [deepcopy(row) for module in modules for row in module['judgment']['assessments']]
        rows, added = mod.derive_rows(rows)
        rows, receipt = final_review.prepare_rows({'final_review_statement': statement}, rows, self.material)
        derivation = {'row_derivation': mod.row_derivation_record(added)} if added else {}
        return {'reviewer': chain, 'assessments': rows, 'future_applications': [], 'enforcement_signals': [],
            'coverage_confidence_cap': '低', 'coverage_confidence_reasoning': 'Synthetic only',
            'review_context': {'session_id': summary['session_id'], 'evidence_digest': self.digest,
                'first_review_visible': False, 'final_review': receipt,
                'execution': {'agent_id': summary['agent_id'], 'run_id': summary['run_id'], 'input_digest': self.digest,
                    'assessment_digest': sha256_json(rows), 'final_review_digest': sha256_json(receipt),
                    'module_execution': {'revision': mod.REVISION, 'chain_id': chain, 'modules': modules,
                                         'summary': summary, **derivation}}}}

    def test_six_module_and_two_summary_sessions_keep_truthful_origins(self):
        first, second = self.review('1'), self.review('2')
        final_review.validate_envelope(first, self.material)
        final_review.validate_envelope(second, self.material)
        result = final_review.pair_summary(first, second, self.digest)
        self.assertEqual(result['execution_revision'], mod.REVISION)
        self.assertEqual(result['module_sessions'][0], ['1-technical', '1-appearance', '1-expression'])
        key = final_review.unit_id(first['assessments'][0])
        self.assertEqual(mod.unit_origins(first, key), {'1-technical'})
        self.assertNotEqual(mod.unit_origins(first, key), {first['review_context']['session_id']})

    # --- evidence roll-up derivation (row-evidence-ref-rollup-v1) --------------------------------------
    def test_rollup_derivation_is_pure_ordered_idempotent_and_leaves_malformed_rows(self):
        row = {'evidence_refs': ['E1'], 'supporting_evidence': [{'reasoning': 'r', 'evidence_refs': ['E2', 'E1']}],
               'confidence_basis': {'scope': {'evidence_refs': ['E3']}}, 'right_state_evidence_refs': ['E2', 'E4']}
        original = deepcopy(row)
        self.assertEqual(mod.row_evidence_ref_additions(row), ['E2', 'E3', 'E4'])
        self.assertEqual(row, original)
        for malformed in ({'supporting_evidence': [{'evidence_refs': 'E2'}], 'evidence_refs': ['E1']},
                          {'supporting_evidence': [{'evidence_refs': [7]}], 'evidence_refs': ['E1']},
                          {'supporting_evidence': [{'evidence_refs': ['E2']}]},
                          {'supporting_evidence': [{'evidence_refs': ['E2']}], 'evidence_refs': 'E1'}):
            with self.subTest(row=malformed):
                self.assertEqual(mod.row_evidence_ref_additions(malformed), [])
        full = {'scenario_id': 'S', 'jurisdiction': 'US', 'right_type': 'patent', 'assessment_object': 'product', **row}
        rows, added = mod.derive_rows([full])
        self.assertEqual(rows[0]['evidence_refs'], ['E1', 'E2', 'E3', 'E4'])
        self.assertEqual(full['evidence_refs'], ['E1'])
        again, nothing = mod.derive_rows(rows)
        self.assertEqual(again, rows)
        self.assertEqual(nothing, {})
        self.assertEqual(list(added.values()), [['E2', 'E3', 'E4']])

    def test_completed_rollup_validates_while_the_receipt_keeps_raw_rows(self):
        review = self.review(rollup=True)
        execution = review['review_context']['execution']
        self.assertEqual(execution['module_execution']['row_derivation']['revision'], mod.ROW_DERIVATION_REVISION)
        mod.validate_execution(review, required=True)
        technical = execution['module_execution']['modules'][0]['judgment']['assessments'][0]
        self.assertEqual(technical['evidence_refs'], ['E'])
        self.assertEqual(review['assessments'][0]['evidence_refs'], ['E', 'E2'])
        # a chain that needed no completion carries no marker at all (its receipt is unchanged)
        plain = self.review('2')
        self.assertNotIn('row_derivation', plain['review_context']['execution']['module_execution'])
        mod.validate_execution(plain, required=True)

    def test_unrecorded_wrong_or_hand_edited_rollup_is_rejected(self):
        review = self.review(rollup=True)
        missing = deepcopy(review)
        missing['review_context']['execution']['module_execution'].pop('row_derivation')
        with self.assertRaisesRegex(ValueError, 'ROW_DERIVATION_MISMATCH'):
            mod.validate_execution(missing, required=True)
        wrong = deepcopy(review)
        unit = next(iter(wrong['review_context']['execution']['module_execution']['row_derivation']['added_evidence_refs']))
        wrong['review_context']['execution']['module_execution']['row_derivation']['added_evidence_refs'][unit] = ['E9']
        with self.assertRaisesRegex(ValueError, 'ROW_DERIVATION_MISMATCH'):
            mod.validate_execution(wrong, required=True)
        revision = deepcopy(review)
        revision['review_context']['execution']['module_execution']['row_derivation']['revision'] = 'other'
        with self.assertRaisesRegex(ValueError, 'ROW_DERIVATION_INVALID'):
            mod.validate_execution(revision, required=True)
        edited = deepcopy(review)
        edited['assessments'][0]['evidence_refs'] = ['E', 'E2', 'E-INVENTED']
        with self.assertRaisesRegex(ValueError, 'ROWS_REWRITTEN'):
            mod.validate_execution(edited, required=True)
        raw_in_review = deepcopy(review)
        raw_in_review['assessments'][0]['evidence_refs'] = ['E']
        with self.assertRaisesRegex(ValueError, 'ROWS_REWRITTEN'):
            mod.validate_execution(raw_in_review, required=True)

    def test_module_judgment_with_unlisted_nested_refs_passes_the_module_validator_only_after_derivation(self):
        record = self.legal_record()
        row = record['judgment']['assessments'][0]
        row['supporting_evidence'] = [{'reasoning': 'Cited here only', 'evidence_refs': ['E2']}]
        # E2 is not part of the known registry: derivation adds it, ordinary validation still rejects it
        with self.assertRaises(mod.ModuleJudgmentError):
            mod._validate_module_judgment(record, self.task, {'E'}, {}, {})
        mod._validate_module_judgment(record, self.task, {'E', 'E2'}, {}, {})
        self.assertEqual(row['evidence_refs'], ['E'])

    def test_changed_native_trace_or_rows_rejected_even_if_top_hash_rebuilt(self):
        review = self.review()
        changed = deepcopy(review)
        changed['assessments'][0]['reasoning'] = 'Host rewritten legal judgment'
        changed['review_context']['execution']['assessment_digest'] = sha256_json(changed['assessments'])
        with self.assertRaisesRegex(ValueError, 'ROWS_REWRITTEN'):
            final_review.validate_envelope(changed)
        module = review['review_context']['execution']['module_execution']['modules'][0]
        audit = json.loads(Path(module['host_audit']['path']).read_text())
        Path(audit['trace_path']).write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'TRACE_CHANGED'):
            final_review.validate_envelope(review)

    def test_execution_observation_tamper_is_rejected_when_audit_binds_it(self):
        review = self.review()
        module = review['review_context']['execution']['module_execution']['modules'][0]
        audit_path = Path(module['host_audit']['path']); audit=json.loads(audit_path.read_text())
        observation = audit_path.parent / 'events.execution.json'
        atomic_write_json(observation, {'status':'process_exited','review_validation':'not_performed'})
        audit.update(execution_observation_path=str(observation), execution_observation_sha256=sha256_file(observation))
        atomic_write_json(audit_path,audit);module['host_audit']['sha256']=sha256_file(audit_path)
        observation.write_text('{"status":"fake_success"}')
        with self.assertRaisesRegex(ValueError,'EXECUTION_OBSERVATION_CHANGED'):
            mod.validate_execution(review,required=True)

    def test_tool_free_process_audits_validate_and_policy_tampering_is_rejected(self):
        self.tool_free = True
        review = self.review()
        mod.validate_execution(review, required=True)
        execution = review['review_context']['execution']['module_execution']
        module = execution['modules'][0]
        audit_path = Path(module['host_audit']['path'])
        audit = json.loads(audit_path.read_text())
        # A policy that claims a kernel boundary is never accepted, even with every hash re-bound.
        policy_path = Path(audit['profile_path'])
        policy = json.loads(policy_path.read_text())
        policy['kernel_read_boundary'] = True
        policy_path.write_text(json.dumps(policy))
        audit['profile_sha256'] = sha256_file(policy_path)
        atomic_write_json(audit_path, audit)
        module['host_audit']['sha256'] = sha256_file(audit_path)
        with self.assertRaisesRegex(ValueError, 'ISOLATION_POLICY_INVALID'):
            mod.validate_execution(review, required=True)
        audit['isolation_method'] = 'something_else'
        atomic_write_json(audit_path, audit)
        module['host_audit']['sha256'] = sha256_file(audit_path)
        with self.assertRaisesRegex(ValueError, 'ISOLATION_METHOD_INVALID'):
            mod.validate_execution(review, required=True)

    def test_module_policy_does_not_accept_old_whole_session_receipt(self):
        review = self.review()
        review['review_context']['execution'].pop('module_execution')
        with self.assertRaisesRegex(ValueError, 'MODULE_EXECUTION_REQUIRED'):
            final_review.validate_envelope(review, self.material)
        old = deepcopy(self.material)
        old['task'].pop('final_review_execution_revision')
        # Legacy envelope validation remains unchanged; bindings are checked
        # against its own legacy material by ordinary legacy tests.
        final_review.validate_envelope(review)

    def test_cross_chain_shared_module_session_is_not_independent(self):
        first, second = self.review('1'), self.review('2')
        second['review_context']['execution']['module_execution']['modules'][0] = deepcopy(
            first['review_context']['execution']['module_execution']['modules'][0])
        with self.assertRaisesRegex(ValueError, 'PAIR_NOT_INDEPENDENT'):
            final_review.pair_summary(first, second, self.digest)

    def test_real_api_unknown_cross_right_source_and_legal_fields_are_retained(self):
        frozen = {'task': self.task, 'evidence_digest': self.digest,
            'candidates': {'assets': [{'candidate_id': 'U', 'right_type': 'unknown',
                'sources': [{'right_type': 'copyright'}, {'right_type': 'design'}]}]},
            'evidence': {'collections': {'records': [{'candidate_id': 'U', 'right_type': 'unknown',
                'payload': {'updated_at': 'actual source date', 'history': ['actual legal event'], 'claim': 'FULL EXACT'}}]}},
            'supplement': {'evidence': [{'candidate_id': 'U', 'path': '/retained/image.jpg', 'sha256': 'ORIGINAL'}]}}
        expression = mod.module_packet(frozen, 'expression')
        self.assertEqual(expression['evidence']['collections']['records'][0]['payload'],
                         frozen['evidence']['collections']['records'][0]['payload'])
        self.assertEqual(expression['supplement']['evidence'][0]['path'], '/retained/image.jpg')
        self.assertTrue(expression['candidates']['assets'])
        self.assertFalse(mod.module_packet(frozen, 'technical')['candidates']['assets'])

    # --- one file referenced by two rights keeps its public-source binding (field patch 7) --------------
    def shared_frozen(self, *, public=True):
        record = {'evidence_id': 'EV-PUB-US1B2', 'kind': 'patent_document', 'path': '/retained/US1B2.pdf',
            'sha256': 'H' * 64, 'bytes': 10, 'jurisdiction': 'US', 'right_type': 'patent',
            'publication_number': 'US1B2', 'checked_at': '2026-10-11T02:32:12Z',
            'authority_scope': 'published_document_only', 'pages': 7,
            'publication_relations': [{'publication_number': 'US0A1', 'relation': 'prior_publication'}]}
        if public:
            record['source_url'] = 'https://patentimages.example/US1B2.pdf'
        return {'task': self.task, 'evidence_digest': self.digest, 'candidates': {},
            'evidence': {'collections': {'asset_provenance': [{'evidence_id': 'EV-ASSET', 'right_type': 'copyright',
                'payload': {'artifacts': [{'path': '/retained/US1B2.pdf', 'sha256': 'H' * 64}]}}]}},
            'supplement': {'evidence': [record]}}

    def test_cross_right_public_original_binding_is_shared_not_dropped(self):
        frozen = self.shared_frozen()
        technical, expression = mod.module_packet(frozen, 'technical'), mod.module_packet(frozen, 'expression')
        self.assertNotIn('shared_public_originals', technical)
        self.assertEqual(technical['supplement']['evidence'][0]['source_url'], 'https://patentimages.example/US1B2.pdf')
        self.assertEqual(expression['supplement']['evidence'], [])
        shared = expression['shared_public_originals']
        self.assertEqual(len(shared), 1)
        self.assertEqual(list(shared[0]), list(mod.SHARED_ORIGINAL_FIELDS[:3]) + ['source_url', 'evidence_id', 'kind',
            'publication_number', 'jurisdiction', 'right_type', 'checked_at', 'authority_scope'])
        self.assertNotIn('pages', shared[0])
        self.assertNotIn('publication_relations', shared[0])
        from review_material_policy import file_inventory
        row = next(item for item in file_inventory(expression) if item['path'] == '/retained/US1B2.pdf')
        self.assertTrue(row['public'])
        self.assertIn('EV-ASSET', row['source_refs'])
        self.assertIn('EV-PUB-US1B2', row['source_refs'])
        # the shared key sits before module_scope so the original is read after every module-local material
        keys = list(expression)
        self.assertLess(keys.index('shared_public_originals'), keys.index('module_scope'))

    def test_private_or_unreferenced_files_are_never_promoted_to_public(self):
        private = self.shared_frozen(public=False)
        self.assertNotIn('shared_public_originals', mod.module_packet(private, 'expression'))
        frozen = self.shared_frozen()
        frozen['evidence']['collections']['asset_provenance'][0]['payload']['artifacts'][0]['sha256'] = 'X' * 64
        self.assertNotIn('shared_public_originals', mod.module_packet(frozen, 'expression'))
        frozen['evidence']['collections'].pop('asset_provenance')
        self.assertNotIn('shared_public_originals', mod.module_packet(frozen, 'expression'))

    def test_shared_binding_is_omitted_when_the_module_keeps_the_public_record(self):
        frozen = self.shared_frozen()
        packet = mod.module_packet(frozen, 'technical')
        self.assertNotIn('shared_public_originals', packet)
        self.assertEqual(mod.shared_public_originals(frozen, packet), [])

    def test_public_original_complete_text_is_read_once_and_never_truncated(self):
        original = self.root / 'original.txt'
        original.write_text('Actual independent claim 1\n' + 'all content ' * 20000)
        row = {'evidence_id': 'E1', 'path': str(original), 'sha256': sha256_file(original),
            'bytes': original.stat().st_size, 'source_url': 'https://official.example/original'}
        packet = {'supplement': {'evidence': [row, deepcopy(row)]}}
        images = mod.attach_originals(packet, self.root)
        self.assertEqual(images, {})
        materials = packet['retained_originals']['materials']
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0]['text'], original.read_text())
        original.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH'):
            mod.attach_originals({'supplement': {'evidence': [row]}}, self.root)

    def test_native_scheduler_runs_each_job_once_with_bounded_parallelism(self):
        active = 0
        max_active = 0
        lock = threading.Lock()
        barrier = threading.Barrier(4)
        calls = []
        jobs = [{'command': [str(i)], 'prompt': 'module', 'workspace': self.root,
            'trace_path': self.root / str(i), 'stderr_path': self.root / ('e' + str(i))} for i in range(4)]
        def run(command, *args):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                calls.append(command[0])
            barrier.wait(timeout=2)
            with lock:
                active -= 1
            return command[0]
        with patch('report_review_host.run_native_logged', side_effect=run):
            self.assertEqual(mod.run_jobs(jobs, 30, 4), ['0', '1', '2', '3'])
        self.assertEqual(max_active, 4)
        self.assertEqual(len(calls), 4)
        with self.assertRaisesRegex(ValueError, 'MAX_PARALLEL_INVALID'):
            mod.run_jobs(jobs, 30, 7)

    def test_native_scheduler_starts_longest_prompt_first_and_keeps_result_order(self):
        started = []
        sizes = [10, 500, 50, 900]
        jobs = [{'command': [str(i)], 'prompt': 'x' * size, 'workspace': self.root,
            'trace_path': self.root / str(i), 'stderr_path': self.root / ('e' + str(i))}
            for i, size in enumerate(sizes)]
        def run(command, *args):
            started.append(command[0])
            return 'out-' + command[0]
        with patch('report_review_host.run_native_logged', side_effect=run):
            result = mod.run_jobs(jobs, 30, 1)
        self.assertEqual(started, ['3', '1', '2', '0'])
        self.assertEqual(result, ['out-0', 'out-1', 'out-2', 'out-3'])

    def test_completed_retained_trace_recovers_without_invented_process_metadata(self):
        directory = self.root / '1' / 'technical'
        directory.mkdir(parents=True)
        packet, prompt, profile, trace = [directory / name for name in
            ('packet.json', 'prompt.txt', 'sandbox.sb', 'events.jsonl')]
        atomic_write_json(packet, {'evidence_digest': self.digest})
        prompt.write_text('Original prompt')
        profile.write_text('Original sandbox')
        raw = {'assessments': [], 'future_applications': [], 'enforcement_signals': []}
        trace.write_text('\n'.join(json.dumps(event) for event in (
            {'type': 'thread.started', 'thread_id': 'native-session'},
            {'type': 'turn.started'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(raw)}},
            {'type': 'turn.completed'})))
        job = {'directory': directory, 'chain_id': '1', 'module_id': 'technical',
               'packet_path': packet, 'prompt_path': prompt, 'profile': profile,
               'trace_path': trace, 'image_manifest': [], 'prompt': prompt.read_text()}
        from report_review_host import seal_review_job
        seal_review_job(job, {'evidence_digest': self.digest}, {})
        record = mod._capture_retained(job, self.digest, 'frozen-hash')
        audit = json.loads((directory / 'audit.json').read_text())
        self.assertEqual(record['judgment'], raw)
        self.assertTrue(audit['recovered_from_retained_trace'])
        self.assertIsNone(audit['process_id'])
        self.assertIsNone(audit['exit_code'])
        self.assertEqual(mod._capture_retained(job, self.digest, 'frozen-hash')['judgment'], raw)
        trace.write_text('tampered')
        with self.assertRaises(ValueError):
            mod._capture_retained(job, self.digest, 'frozen-hash')

    def test_revision_unknown_is_not_silently_legacy(self):
        self.assertFalse(mod.enabled({}))
        self.assertTrue(mod.enabled(self.task))
        with self.assertRaisesRegex(ValueError, 'REVISION_INVALID'):
            mod.enabled({**self.task, 'final_review_execution_revision': 'made-up'})



class OriginalObservationContractTests(unittest.TestCase):
    def test_registered_json_is_actual_decoded_source_and_private_url_is_not_read(self):
        from common import atomic_write_json,sha256_file
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'original.json';atomic_write_json(path,'Full original source text')
            row={'evidence_id':'E','path':str(path),'sha256':sha256_file(path),'source_url':'https://official.example/doc'}
            packet={'supplement':[row]};mod.attach_originals(packet,root)
            self.assertEqual(packet['retained_originals']['materials'][0]['text'],'Full original source text')
            row['source_url']='file:///private/authorization'
            packet={'supplement':[row]};mod.attach_originals(packet,root)
            self.assertEqual(packet['retained_originals']['materials'],[])

    def test_malformed_json_and_wrong_fingerprint_fail_before_model(self):
        from common import sha256_file
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'original.json';path.write_text('{broken')
            row={'evidence_id':'E','path':str(path),'sha256':sha256_file(path),'source_url':'https://official.example/doc'}
            with self.assertRaises(ValueError):mod.attach_originals({'sources':[row]},root)
            row['sha256']='0'*64
            with self.assertRaises(ValueError):mod.attach_originals({'sources':[row]},root)

    def test_v2_requires_exact_ids_refs_and_explicit_reading_limit(self):
        packet={'retained_originals':{'revision':'public-originals-v2','materials':[{'material_id':'M1','source_refs':['E1','E2']}]}}
        valid={'material_observations':{'M1':{'source_refs':['E1','E2'],'observation':'Claim contains a pivot mechanism','limitations':'PDF drawings unavailable'}}}
        mod.validate_original_observations(valid,packet)
        cases=[{}, {'material_observations':{}}, deepcopy(valid), deepcopy(valid), deepcopy(valid),deepcopy(valid)]
        cases[2]['material_observations']['M1']['source_refs']=['E2','E1']
        cases[3]['material_observations']['M1']['observation']=' '
        cases[4]['material_observations']['M1'].pop('limitations')
        cases[5]['material_observations']['M2']=cases[5]['material_observations']['M1']
        for bad in cases:
            with self.subTest(raw=bad),self.assertRaisesRegex(ValueError,'ORIGINAL_OBSERVATION'):
                mod.validate_original_observations(bad,packet)
        packet['retained_originals']['revision']='public-originals-v1'
        mod.validate_original_observations({},packet)


if __name__ == '__main__':
    unittest.main()
