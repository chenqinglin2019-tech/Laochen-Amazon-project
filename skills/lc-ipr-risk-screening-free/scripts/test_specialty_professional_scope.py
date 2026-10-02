"""Exact professional design dependency, with no source or expert conclusion."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import specialty_analysis as m
from common import sha256_json, sha256_file


class ProfessionalScopeTests(unittest.TestCase):
    def test_atomic_close_derives_only_selected_scope_unknown_and_exact_wait_packet(self):
        common = {**self.base, 'reviewer': 'actual-agent', 'reason': 'Read actual eight originals; line scope stays unknown'}
        gap_config = {key: copy.deepcopy(value) for key, value in self.req.items()
            if key not in {'obligation_bindings', 'professional_packet', 'affected_judgment', 'gap_id', 'unit_id', 'inventory_event_id'}}
        gap_config['blocker_reasons'] = ['SPECIALTY_DESIGN_SCOPE_UNKNOWN']
        follow_config = {'outcome': 'waiting', 'result_review': 'No qualified opinion yet',
            'remaining_impact': 'Only exact line scope remains unknown',
            'next_action_or_dependency': 'Qualified scope interpretation', 'resume_condition': 'Actual opinion read',
            'professional_dependency': 'qualified_design_scope_interpretation', 'evidence_refs': ['PDF']}
        gap_request, follow_request, blockers = m._comparison_close_requests(self.task, self.comp,
            {'gap': gap_config, 'followup': follow_config}, self.index, common)
        self.assertEqual({row['reason'] for row in blockers},
            {'SPECIALTY_COMPARISON_UNKNOWN', 'SPECIALTY_DESIGN_SCOPE_UNKNOWN'})
        self.assertEqual(len(gap_request['obligation_bindings']), 1)
        self.assertEqual(gap_request['obligation_bindings'][0]['basis_event_id'], self.comp['event_id'])
        gap = m._append(self.task, 'gap', m._gap(self.task, gap_request, self.index))
        follow_request['gap_event_id'] = gap['event_id']
        follow = m._followup(self.task, follow_request, self.index)
        self.assertEqual(follow['professional_packet_sha256'], sha256_json(gap['professional_packet']))
        self.assertEqual(self.comp['design_scope_parts'][0]['treatment'], 'unknown')
        self.assertEqual(self.comp['views'][0]['result'], 'unknown')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'original.pdf'; self.path.write_bytes(b'retained fixture bytes')
        self.scope = dict(candidate_id='D1', scenario_id='product_entry', jurisdiction='US', right_type='design')
        self.task = {'task_id': 'T', 'specialty_analysis_revision': m.REVISION}
        from candidate_triage_stage import _append as triage_append
        handoff = triage_append(self.task, {'kind': 'selected_handoff', **self.scope, 'annotation_id': 'A'})
        self.index = {'PDF': {'evidence_id': 'PDF', 'path': str(self.path), 'sha256': sha256_file(self.path)}}
        self.intake = m._append(self.task, 'intake', {**self.scope, 'assessment_date': '2026-09-27', 'annotation_id': 'A',
            'verification_gaps': [], 'selected_handoff_event_id': handoff['event_id'],
            'product_version_sha256': '0' * 64, 'candidate_version_sha256': '1' * 64})
        self.base = {**self.scope, 'assessment_date': '2026-09-27', 'intake_event_id': self.intake['event_id']}
        self.mat = m._append(self.task, 'material', {**self.base, 'source_form': 'original_document',
            'status': 'sufficient_for_listed_purposes', 'purposes': ['protection'], 'evidence_refs': ['PDF'],
            'reading_locations': ['all eight original sheets']})
        self.inv = m._append(self.task, 'inventory', {**self.base, 'evidence_refs': ['PDF'],
            'material_event_ids': [self.mat['event_id']], 'units': [{'unit_id': 'U', 'kind': 'design',
            'necessary_views': ['fig%d' % n for n in range(1, 9)]}]})
        self.comp = m._append(self.task, 'comparison', {**self.base, 'inventory_event_id': self.inv['event_id'],
            'unit_id': 'U', 'disposition': 'compared', 'evidence_refs': ['PDF'],
            'views': [{'view_id': 'fig%d' % n, 'result': 'unknown'} for n in range(1, 9)],
            'design_scope_parts': [{'part_id': 'ribs', 'treatment': 'unknown'}]})
        self.req = {**self.base, 'unit_id': 'U', 'inventory_event_id': self.inv['event_id'], 'gap_id': 'G',
            'question': 'Interpret solid/broken lines in all eight figures', 'affected_judgment': 'design scope',
            'action_kind': 'professional_review', 'minimum_action': 'Qualified scope interpretation',
            'completion_condition': 'Actual opinion received and exact comparison reviewed',
            'existing_material_check': 'All eight originals read; precise line attribution unknown',
            'next_value': 'Reliable scope', 'evidence_refs': ['PDF'], 'obligation_bindings': [{
                'reason': 'SPECIALTY_DESIGN_SCOPE_UNKNOWN', 'unit_id': 'U',
                'basis_event_id': self.comp['event_id'], 'reasoning': 'Only this unit line scope'}]}
        self.req['professional_packet'] = m.professional_scope_packet(self.task, self.req, self.index)

    def gap(self):
        return m._append(self.task, 'gap', m._gap(self.task, self.req, self.index))

    def follow(self, gap, **change):
        req = {**self.base, 'gap_id': 'G', 'gap_event_id': gap['event_id'], 'outcome': 'waiting',
            'result_review': 'Packet prepared; opinion not obtained', 'remaining_impact': 'Scope unknown',
            'next_action_or_dependency': 'Qualified design scope interpretation',
            'professional_dependency': 'qualified_design_scope_interpretation',
            'professional_packet_sha256': sha256_json(gap['professional_packet']),
            'resume_condition': 'Register opinion and review exact unit', 'evidence_refs': ['PDF'], **change}
        return m._append(self.task, 'followup', m._followup(self.task, req, self.index))

    def entry(self):
        with patch.object(m, '_current', return_value={'annotation': {'annotation_id': 'A'}}):
            return m.professional_wait_entry(self.task, {'collections': {'sources': list(self.index.values())}},
                                             {}, {}, self.scope, 'U')

    def test_exact_wait_is_external_without_clearance_or_query(self):
        self.follow(self.gap()); entry = self.entry()
        self.assertEqual(entry['state'], 'awaiting_access')
        self.assertEqual(entry['delivery_limit']['kind'], 'professional_wait')
        self.assertEqual(entry['official_verification'], 'not_verified')
        self.assertNotIn('query_id', entry)
        scope = {**self.scope, 'intake_event_id': self.intake['event_id'], 'blockers': [{
            'reason': 'SPECIALTY_DESIGN_SCOPE_UNKNOWN', 'unit_id': 'U', 'state': 'awaiting_access', 'source_dependency': entry}]}
        work = m.work_entries({'scopes': [scope]})[0]
        self.assertEqual(work['kind'], 'professional_review')
        from necessary_completion import _delivery_limit_valid
        with patch.object(m, '_current', return_value={'annotation': {'annotation_id': 'A'}}):
            self.assertTrue(_delivery_limit_valid(work, self.task,
                {'collections': {'sources': list(self.index.values())}}, {}, {}, candidates={}, ledger={}))

    def test_wrong_or_duplicate_binding_rejected(self):
        for bindings in ([{'reason': 'SPECIALTY_FACT_REQUIRED', 'fact_kind': 'status'}], self.req['obligation_bindings'] * 2):
            req = copy.deepcopy(self.req); req['obligation_bindings'] = bindings
            with self.assertRaises(ValueError): m._gap(self.task, req, self.index)

    def test_territory_current_effect_matches_only_typed_exact_proof(self):
        basis = {'fact_kind': 'territory'}; binding = {'reason': 'SPECIALTY_FACT_REQUIRED'}
        gap = {**self.scope, 'action_kind': 'verify_known_right', 'source_required_facts': ['current_status']}
        self.assertFalse(m._dependency_matches(gap, binding, basis))
        gap['source_plan_gap_proof'] = {'kind': 'territory_current_effect_plan_gap', 'fact_kind': 'territory'}
        self.assertTrue(m._dependency_matches(gap, binding, basis))
        gap['jurisdiction'] = 'EU'; self.assertFalse(m._dependency_matches(gap, binding, basis))

    def test_design_planner_uses_design_status_owner_gap_codes(self):
        import workflow_v24 as w
        from common import atomic_write_json
        root = self.path.parent
        atomic_write_json(root / 'search-plan.json', {'queries': {}})
        decision = {**self.scope, 'decision': 'selected', 'current': True}
        task = {'coverage_requirements': [{'jurisdiction': 'US', 'right_type': 'design',
            'phase': 'candidate_verification', 'requirement_id': 'DV',
            'routes': [{'provider': 'uspto_patent_browser', 'operation': 'candidate_verification'}]}]}
        candidate = {'candidate_id': 'D1', 'publication_number': 'USD1149217S', 'jurisdiction': 'US', 'right_type': 'design'}
        with patch.object(w, 'assert_recall_planning_contract'), patch.object(w, '_scenario_context', return_value=(task, {}, {})), \
             patch.object(w, 'scenario_supplement', return_value={}), patch.object(w, 'correction_enabled', return_value=True), \
             patch.object(w, 'bind_scenario_action', side_effect=lambda task, provider, row, **kwargs: row), \
             patch.object(w, '_owner_verification_required', return_value=True), \
             patch('decision_workflow.triage_summary', return_value={'records': [decision]}), \
             patch('decision_workflow.scenario_index', return_value={'product_entry': {}}), \
             patch('decision_workflow.necessary_scenario_right_types', return_value=['design']), \
             patch('decision_workflow.triage_scope_enabled', return_value=False):
            result = w.append_scenario_candidate_actions(root, task, {'patents': [candidate]}, gaps_only=True)
        self.assertEqual([r['code'] for r in result['candidate_action_gaps']],
            ['US_DESIGN_STATUS_ROUTE_UNIMPLEMENTED', 'US_DESIGN_OWNER_ROUTE_UNIMPLEMENTED'])
        self.assertEqual([r['required_facts'] for r in result['candidate_action_gaps']], [['current_status'], ['rights_holder']])

    def design_reading_reuse_fixture(self):
        self.task.update(workflow_correction_revision='workflow-correction-v1',
                         triage_stage_revision='candidate-triage-stage-v1')
        from pypdf import PdfWriter
        writer = PdfWriter()
        for _ in range(10): writer.add_blank_page(width=100, height=100)
        writer.write(self.path)
        self.index['PDF'].update(provider='public_source', kind='design_document', publication_number='USD1149217S',
            jurisdiction='US', right_type='design', sha256=sha256_file(self.path), bytes=self.path.stat().st_size,
            source_run_id='R', source_url='https://image-ppubs.uspto.gov/official.pdf', collected_at='2026-09-27T00:00:00Z')
        material = {k: v for k, v in self.mat.items() if k not in {'kind', 'event_id', 'previous_event_id', 'recorded_at'}}
        material.update(document_version='V', supported_facts=['identity', 'protection'])
        mat = m._append(self.task, 'material', material)
        for kind in ('identity', 'protection'):
            m._append(self.task, 'fact', {**self.base, 'fact_kind': kind, 'outcome': 'supported',
                'material_event_ids': [mat['event_id']], 'document_version': 'V',
                'reading_locations': ['actual original fixture'], 'evidence_refs': ['PDF']})
        inventory = {k: v for k, v in self.inv.items() if k not in {'kind', 'event_id', 'previous_event_id', 'recorded_at'}}
        inventory.update(material_event_ids=[mat['event_id']], document_version='V', reading_locations=['all8sheets'],
            completeness_reasoning='Exact complete fixture original inventory')
        m._append(self.task, 'inventory', inventory)
        self.row = {**self.scope, 'action_purpose': 'document_content', 'required_facts': ['protection_content'],
            'reading_scope': {'level': 'protection_content'}, 'record_number': 'USD1149217S'}
        self.evidence = {'collections': {'sources': list(self.index.values())}, 'source_runs': [{'run_id': 'R',
            'provider': 'public_source', 'operation': 'retained_document', 'status': 'success',
            'query': self.index['PDF']['source_url']}]}
        self.candidates = {'patents': [{'candidate_id': 'D1', 'publication_number': 'USD1149217S'}]}

    def reuse(self, row=None):
        from same_task_evidence import _specialty_document_content
        with patch.object(m, '_current', return_value={'annotation': {'annotation_id': 'A'}}):
            return _specialty_document_content(self.task, self.evidence, self.candidates, {}, 'uspto_patent_browser',
                row or self.row, supplement=None, directory=self.path.parent)

    def test_design_registered_original_reading_only_reuses_protection_content(self):
        self.design_reading_reuse_fixture(); value = self.reuse()
        self.assertEqual(value['satisfied_facts'], ['protection_content'])
        self.assertIn('inventory_sha256', value['specialty_reading_proof'])
        for changes in ({'required_facts': ['current_status']}, {'required_facts': ['rights_holder']},
                        {'record_number': 'USD999999S'}): self.assertIsNone(self.reuse({**self.row, **changes}))
        self.path.write_bytes(b'changed'); self.assertIsNone(self.reuse())

    def test_design_reading_requires_complete_inventory_and_formal_source_run(self):
        self.design_reading_reuse_fixture(); self.evidence['source_runs'][0]['status'] = 'error'
        self.assertIsNone(self.reuse()); self.evidence['source_runs'][0]['status'] = 'success'
        inventory = next(row for row in reversed(m.events(self.task)) if row['kind'] == 'inventory')
        payload = {k: v for k, v in inventory.items() if k not in {'kind', 'event_id', 'previous_event_id', 'recorded_at'}}
        payload['units'] = []; m._append(self.task, 'inventory', payload); self.assertIsNone(self.reuse())

    def test_forged_packet_or_wait_rejected(self):
        req = copy.deepcopy(self.req); req['professional_packet']['necessary_views'] = []
        with self.assertRaises(ValueError): m._gap(self.task, req, self.index)
        gap = self.gap()
        with self.assertRaises(ValueError): self.follow(gap, professional_packet_sha256='0' * 64)
        with self.assertRaises(ValueError): self.follow(gap, outcome='limited')

    def test_changed_file_reopens(self):
        self.follow(self.gap()); self.assertIsNotNone(self.entry())
        self.path.write_bytes(b'changed'); self.assertIsNone(self.entry())

    def test_changed_or_supported_scope_reopens(self):
        self.follow(self.gap())
        payload = {k: v for k, v in self.comp.items() if k not in {'kind', 'event_id', 'previous_event_id', 'recorded_at'}}
        payload['design_scope_parts'] = [{'part_id': 'ribs', 'treatment': 'claimed'}]
        m._append(self.task, 'comparison', payload); self.assertIsNone(self.entry())

    def test_changed_evidence_and_scoped_change_reopen(self):
        self.follow(self.gap()); self.index['PDF']['source_url'] = 'different'
        self.assertIsNone(self.entry())
        self.index['PDF'].pop('source_url')
        m._append(self.task, 'change', {**self.base, 'substantive': True, 'affected_event_ids': [self.mat['event_id']]})
        self.assertIsNone(self.entry())

    def test_new_incomplete_inventory_cannot_inherit_wait(self):
        self.follow(self.gap())
        payload = {k: v for k, v in self.inv.items() if k not in {'kind', 'event_id', 'previous_event_id', 'recorded_at'}}
        payload['units'] = [{'unit_id': 'U', 'kind': 'design', 'necessary_views': ['fig1']}]
        m._append(self.task, 'inventory', payload); self.assertIsNone(self.entry())

    def test_nonoriginal_or_unread_material_cannot_prepare_packet(self):
        for change in ({'source_form': 'summary'}, {'status': 'acquired'}, {'reading_locations': []}):
            task = copy.deepcopy(self.task)
            # Append a changed inventory referring to a legitimately signed new material.
            material = {k: v for k, v in self.mat.items() if k not in {'kind', 'event_id', 'previous_event_id', 'recorded_at'}}
            material.update(change); mat = m._append(task, 'material', material)
            inv = {k: v for k, v in self.inv.items() if k not in {'kind', 'event_id', 'previous_event_id', 'recorded_at'}}
            inv['material_event_ids'] = [mat['event_id']]; inv = m._append(task, 'inventory', inv)
            req = {**self.req, 'inventory_event_id': inv['event_id']}
            with self.assertRaises(ValueError): m.professional_scope_packet(task, req, self.index)


if __name__ == '__main__': unittest.main()
